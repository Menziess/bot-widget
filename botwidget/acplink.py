"""An ACP agent as a bot in the bubble: the same calls as the Grok and Hermes links, filled from
ACP events pushed by the agent instead of answers polled over HTTP.

The face never learns which backend it has. It sends, asks for the conversation, and asks
whether the bot is working; this class answers all three from one long-lived agent process that
runs asyncio in a background thread, so no Qt thread ever waits on the agent.
"""

import asyncio
import concurrent.futures
import os
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


def target_for(agent_id: str) -> str:
    """The agent command for this face: `acp:hermes-acp` runs hermes-acp, unless the settings say otherwise."""
    configured = widget_config().get("acp_target")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return agent_id[len(PREFIX):] or DEFAULT_TARGET


def _bubble_line(text: str) -> str:
    """One short line for the cloud: the first line of a thought, cut where the bubble would."""
    line = " ".join((text or "").split())
    return line[:ACTIVITY_CHARS]


class AcpLink:
    """One bot on an ACP agent: a session that stays open, and one turn at a time."""

    def __init__(self, target: str, now=time.monotonic):
        self.target = target
        self.now = now
        self.messages = []
        self.stopped = False
        self.failed = ""
        # Read by the face; guarded by the lock because the agent's thread writes them.
        self._lock = threading.Lock()
        self._activity = ""
        self._note = ""
        self._sending = False
        self._said = False  # did this turn put any text in the bubble
        self._asks = 0
        self._approvals = {}
        self._decisions = {}  # request id -> (future on the agent's loop, title)
        self._client = None
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

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
            return self._sending

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
        """A grey line under the conversation: why it stopped, or that a send is unsure."""
        with self._lock:
            return self._note

    def cancel(self) -> None:
        """Stop the running turn; the agent ends it with the cancelled stop reason."""
        if self._client is not None:
            asyncio.run_coroutine_threadsafe(self._client.cancel(), self._loop)

    def close(self) -> None:
        """Stop the agent process and the loop behind it."""
        if self._closed:
            return
        self._closed = True
        if self._client is not None:
            async def shutdown():
                try:
                    await self._client.__aexit__(None, None, None)
                finally:
                    # The connection leaves reader and sender tasks behind; stopping the loop with
                    # them still pending prints a warning per task.
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
                self.failed = "The model refused to answer."
                self._note = self.failed
            elif turn.stop_reason == "cancelled":
                self._note = "Cancelled."
            elif not self._said:
                # Nothing was said: better a line than a bubble that waits forever.
                self._note = f"The turn ended ({turn.stop_reason or 'no reason given'}) with no answer."

    async def _ensure(self):
        """Start the agent on first use, then keep it: a session that stays open is what makes a
        second message cheap."""
        if self._client is not None:
            return self._client
        room = os.path.expanduser(f"~/.local/share/botwidget/harness/{self.target}")
        os.makedirs(room, exist_ok=True)
        client = AcpClient(*shlex.split(self.target), cwd=room,
                           allow=self._ask, on_update=self._updated)
        await client.__aenter__()
        try:
            info = await client.start()
        except BaseException:
            await client.__aexit__(None, None, None)  # a half-started agent still owns a process
            raise
        self._client = client
        with self._lock:
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
            if update.kind == "thought" and update.text.strip():
                self._activity = _bubble_line(update.text)
            elif update.kind == "tool":
                self._activity = _bubble_line(update.text) or self._activity
            elif update.kind == "text" and update.text:
                self._said = True
                # shortcut: one answer message per turn; ACP message ids are ignored for now.
                if self.messages and self.messages[-1]["role"] == "bot":
                    self.messages[-1]["text"] += update.text
                else:
                    self.messages.append({"role": "bot", "text": update.text})
