"""An ACP agent as a bot in the bubble: the same calls as the Grok and Hermes links, filled from
ACP events pushed by the agent instead of answers polled over HTTP.

The face never learns which backend it has. It sends, asks for the conversation, and asks
whether the bot is working; this class answers all three from one long-lived agent process that
runs asyncio in a background thread, so no Qt thread ever waits on the agent.
"""

import asyncio
import concurrent.futures
import json
import os
import re
import shlex
import threading
import time

from botwidget.config import widget_config
from harness.acp_client import AcpClient

PREFIX = "acp:"
DEFAULT_TARGET = "hermes-acp"
ACTIVITY_CHARS = 60
PERMISSION_WAIT_S = 120


def face_id(target: str = DEFAULT_TARGET) -> str:
    """The id of the face of an ACP bot."""
    return PREFIX + target


def is_acp(agent_id: str) -> bool:
    """Is this the id of a face that talks ACP?"""
    return isinstance(agent_id, str) and agent_id.startswith(PREFIX)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def configured_bots() -> list[dict]:
    """The ACP faces in widget.json, one entry each: name, command, HARNESS_* env and a key file.

    The key itself is never in widget.json: `key_file` names a file the link reads at start.
    """
    entries = widget_config().get("acp_bots")
    bots = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        name, command = str(entry.get("name") or "").strip(), str(entry.get("command") or "").strip()
        if not name or not command:
            continue
        env = {key: str(value) for key, value in (entry.get("env") or {}).items()
               if str(key).startswith("HARNESS_") and str(key) != "HARNESS_MODEL_API_KEY"}
        stored = str(entry.get("id") or "").strip()
        if stored.startswith(PREFIX):
            stored = stored[len(PREFIX):]
        ident = stored or _slug(name)
        if any(bot["id"] == PREFIX + ident for bot in bots):
            continue  # the same id twice would be one face with two agents
        bots.append({"id": PREFIX + ident, "name": name, "command": command, "env": env,
                     "key_file": str(entry.get("key_file") or ""),
                     "face": str(entry.get("face") or ""), "color": str(entry.get("color") or "")})
    return bots


def target_for(agent_id: str) -> str:
    """The agent command for this face: a configured bot's own command, else the settings or the id."""
    for bot in configured_bots():
        if bot["id"] == agent_id:
            return bot["command"]
    configured = widget_config().get("acp_target")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return agent_id[len(PREFIX):] or DEFAULT_TARGET


def options_for(agent_id: str) -> dict:
    """The rest of a configured face: its env, its own folder, and the key file it reads at start."""
    bot = next((bot for bot in configured_bots() if bot["id"] == agent_id), None)
    if bot is None:
        return {}
    return {"face": agent_id, "env": bot["env"], "key_file": bot["key_file"]}


def _bubble_line(text: str) -> str:
    """One short line for the cloud: the first line of a thought, cut where the bubble would."""
    line = " ".join((text or "").split())
    return line[:ACTIVITY_CHARS]


class AcpLink:
    """One bot on an ACP agent: a session that stays open, and one turn at a time."""

    def __init__(self, target: str, face: str = "", env: dict | None = None, key_file: str = "",
                 now=time.monotonic):
        self.target = target
        self.face = face or face_id(target)
        self.env = dict(env or {})
        self.key_file = key_file
        self.now = now
        self.messages = []
        self.stopped = False
        self.failed = ""
        # Read by the face; guarded by the lock because the agent's thread writes them.
        self._lock = threading.Lock()
        self._activity = ""
        self._note = ""
        self._context = ""
        self._sending = False
        self._said = False  # did this turn put any text in the bubble
        self._loading = False  # replaying a stored session: that text goes in front of the new message
        self._history: list[dict] = []
        self._asks = 0
        self._approvals = {}
        self._decisions = {}  # request id -> (future on the agent's loop, title)
        self._client = None
        self._closed = False
        self._booting = True  # history loads at start, before the first message
        self._gate = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._gate = asyncio.Lock()
        self._loop.call_soon(lambda: self._loop.create_task(self._boot()))
        self._loop.run_forever()

    async def _boot(self) -> None:
        """Load the saved session as the widget starts. A failure here is reported on the first send."""
        try:
            await self._ensure()
        except Exception:
            pass

    # ── the calls the face knows ────────────────────────────────

    def send(self, text: str) -> tuple[bool, str]:
        """Hand the message to the agent. True once it is on its way; a slow start is not an error."""
        with self._lock:
            if self._sending:
                return False, "still answering the last message"
            self._sending = True
            self._note = ""
            self.failed = ""
            self.messages.append({"role": "user", "text": text})
            self._said = False
            self._activity = f"Waking {self.target}…"
        asyncio.run_coroutine_threadsafe(self._turn(text), self._loop)
        return True, ""

    def chat(self) -> dict:
        """The conversation so far, one line of activity, and any approval that waits."""
        with self._lock:
            messages = [dict(message) for message in self.messages]
            return {"messages": messages, "activity": self._activity, "failed": self.failed,
                    "approvals": [{"requestId": rid, "reason": title}
                                  for rid, title in self._approvals.items()]}

    def attention(self) -> dict:
        """What waits for you, in the shape the bubble already draws buttons from."""
        with self._lock:
            return {"prompts": [], "browserTakeovers": [],
                    "approvals": [{"requestId": rid, "reason": title}
                                  for rid, title in self._approvals.items()]}

    def decide(self, request_id: str, accept: bool) -> None:
        """Answer a permission request: Accept or Decline, as the bubble's buttons say."""
        with self._lock:
            pending = self._decisions.pop(request_id, None)
            if pending is None:
                return
            self._approvals.pop(request_id, None)
        future, _title = pending
        self._loop.call_soon_threadsafe(lambda: future.done() or future.set_result(accept))

    def active(self) -> bool:
        """Is a turn running? The face then keeps looking, so a pushed answer is drawn at once."""
        with self._lock:
            return self._sending or self._booting

    def due(self) -> bool:
        """Nothing to poll: the agent pushes its updates."""
        return False

    @property
    def is_polling(self) -> bool:
        return False

    def poll(self) -> None:
        """Nothing to poll."""

    def request_fetch(self) -> None:
        """Nothing to fetch: the pushed updates are already here."""

    def resume(self) -> None:
        """A new message is a fresh attempt: the old note no longer stands."""
        with self._lock:
            self.stopped = False
            self._note = ""

    def note(self) -> str:
        """A grey line under the conversation: why it stopped, that a send is unsure, or how full the
        context is."""
        with self._lock:
            return self._note or self._context

    def cancel(self) -> None:
        """Stop the running turn; the agent ends it with the cancelled stop reason. With nothing
        running there is nothing to stop, and a cancel sent anyway would end the next turn."""
        if not self.active():
            return
        if self._client is not None:
            asyncio.run_coroutine_threadsafe(self._client.cancel(), self._loop)

    def close(self) -> None:
        """Stop the agent process and the loop behind it."""
        if self._closed:
            return
        self._closed = True

        async def shutdown():
            if self._client is not None:
                try:
                    await self._client.__aexit__(None, None, None)
                except Exception:
                    pass
            # Boot and the connection's reader tasks outlive a quick close otherwise.
            rest = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in rest:
                task.cancel()
            await asyncio.gather(*rest, return_exceptions=True)

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self._loop).result(5)
        except Exception:
            pass  # a dead agent has nothing left to close
        self._loop.call_soon_threadsafe(self._loop.stop)

    # ── the agent, in the background ────────────────────────────

    async def _turn(self, text: str) -> None:
        try:
            client = await self._ensure()
            turn = await client.prompt(text)
        except Exception as error:
            with self._lock:
                self.stopped = True
                self.failed = f"{self.target} did not start: {error}"
                self._note = self.failed
                self._activity = ""
                self._sending = False
            return
        with self._lock:
            self._activity = ""
            self._sending = False
            if turn.error:
                self.stopped = True
                self.failed = turn.error
                self._note = turn.error
            elif turn.stop_reason == "refusal":
                self.failed = turn.error or "The model refused to answer."
                self._note = self.failed
            elif turn.stop_reason == "cancelled":
                self._note = "Cancelled."
            elif not self._said:
                # Nothing was said: better a line than a bubble that waits forever.
                self._note = f"The turn ended ({turn.stop_reason or 'no reason given'}) with no answer."

    def room(self) -> str:
        """This face's own folder: one session file and a usage log per bot, also after a restart."""
        return os.path.expanduser(f"~/.local/share/botwidget/harness/{_slug(self.face[len(PREFIX):])}")

    def _saved_session(self) -> str:
        try:
            with open(os.path.join(self.room(), "session.json")) as fh:
                return str(json.load(fh).get("session") or "")
        except (OSError, ValueError):
            return ""

    def _save_session(self, session_id: str) -> None:
        try:
            os.makedirs(self.room(), exist_ok=True)
            with open(os.path.join(self.room(), "session.json"), "w") as fh:
                json.dump({"session": session_id}, fh)
        except OSError:
            pass  # the conversation still works; it just starts empty next time

    def _environment(self) -> dict:
        """The face's own HARNESS_* values, plus the key read from its file: never from widget.json."""
        env = dict(self.env)
        if self.key_file:
            try:
                with open(os.path.expanduser(self.key_file)) as fh:
                    env["HARNESS_MODEL_API_KEY"] = fh.read().strip()
            except OSError as error:
                raise RuntimeError(f"cannot read the key file {self.key_file}: {error.strerror}") from error
        return env

    async def _ensure(self):
        """Start the agent on first use, then keep it: a session that stays open is what makes a
        second message cheap."""
        try:
            async with self._gate:
                return await self._open()
        finally:
            with self._lock:
                self._booting = False

    async def _open(self):
        if self._client is not None:
            return self._client
        room = self.room()
        os.makedirs(room, exist_ok=True)
        env = self._environment()
        client = AcpClient(*shlex.split(self.target), cwd=room, env=env,
                           allow=self._ask, on_update=self._updated)
        await client.__aenter__()
        with self._lock:
            self._loading = True
        try:
            info = await client.start(load=self._saved_session())
        except BaseException:
            await client.__aexit__(None, None, None)  # a half-started agent still owns a process
            raise
        finally:
            with self._lock:
                self._loading = False
                # The replayed history belongs before the message that woke the agent.
                if self._history:
                    self.messages[:0] = self._history
                    self._history = []
        self._save_session(info["session"])
        self._client = client
        with self._lock:
            self._booting = False
            # A send that is already waiting keeps the waking line; a startup load stays quiet.
            if self._sending:
                self._activity = f"{info['name'] or self.target} is awake"
        return client

    async def _ask(self, title: str) -> bool:
        """A permission request: put Accept and Decline in the bubble and wait for one of them.

        The wait is a future on the agent's loop, not a sleeping thread, so the agent's other
        events keep flowing while the question stands.
        """
        request_id = f"acp-{self._asks}-{round(time.time() * 1000)}"
        self._asks += 1
        future = self._loop.create_future()
        with self._lock:
            self._approvals[request_id] = title
            self._decisions[request_id] = (future, title)
        try:
            return await asyncio.wait_for(future, PERMISSION_WAIT_S)
        except asyncio.TimeoutError:
            with self._lock:
                self._decisions.pop(request_id, None)
                self._approvals.pop(request_id, None)
                self._note = "No answer in time, so the action was declined."
            return False

    def _updated(self, update) -> None:
        """One pushed update: a thought is the activity, answer text is the answer, a tool is its title."""
        with self._lock:
            if self._loading and update.kind in ("text", "user") and update.text:
                role = "user" if update.kind == "user" else "bot"
                if self._history and self._history[-1]["role"] == role:
                    self._history[-1]["text"] += update.text
                else:
                    self._history.append({"role": role, "text": update.text})
                return
            if update.kind == "thought" and update.text.strip():
                self._activity = _bubble_line(update.text)
            elif update.kind == "tool":
                self._activity = _bubble_line(update.text) or self._activity
            elif update.kind == "usage":
                used, size = update.extra.get("used") or 0, update.extra.get("size") or 0
                if update.extra.get("compacted"):
                    self._context = "Compacted older turns."
                elif size:
                    percent = used * 100 / size
                    shown = "<1" if percent < 1 else str(int(percent))
                    self._context = f"Context {shown}% full."
                else:
                    self._context = ""
            elif update.kind == "text" and update.text:
                self._said = True
                # shortcut: one answer message per turn; ACP message ids are ignored for now.
                if self.messages and self.messages[-1]["role"] == "bot":
                    self.messages[-1]["text"] += update.text
                else:
                    self.messages.append({"role": "bot", "text": update.text})
