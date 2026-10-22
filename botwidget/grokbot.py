"""Grok Bot through the gbot command: one bot's thread and what it answers."""

import json
import os
import signal
import subprocess
import threading
import time
from typing import NamedTuple

from botwidget import openbot
from botwidget.config import widget_config

PREFIX = "grok:"
DEFAULT_TARGET = "General"
# A long note helps nobody; the first words are enough.
NOTE_CHARS = 200


class Result(NamedTuple):
    """What gbot said: its exit code, the JSON it printed and a note in plain words."""
    rc: int | None
    data: dict | None
    note: str


def face_id(target: str) -> str:
    """The id of the face of a Grok Bot bot."""
    return PREFIX + target


def avatar_of(bots, target: str) -> dict | None:
    """The shape and colour Grok Bot draws for this bot, from a roster entry.

    Grok Bot names its own colours ("black", "brown", ...) and shapes ("blob", "cloud", ...); a
    bot without them gets None and keeps the face the widget derives from its seed.
    """
    for bot in bots or []:
        if not isinstance(bot, dict):
            continue
        if str(bot.get("name") or "").strip().lower() != (target or "").strip().lower():
            continue
        avatar = {key: bot.get(field) for key, field in (("shape", "avatarShape"), ("color", "avatarColor"))
                  if isinstance(bot.get(field), str) and bot.get(field)}
        return avatar or None
    return None



def is_grok(agent_id: str) -> bool:
    """Is this the id of a Grok Bot face?"""
    return isinstance(agent_id, str) and agent_id.startswith(PREFIX)


def target() -> str:
    """The Grok Bot the widget talks to."""
    configured = widget_config().get("grokbot_target")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return DEFAULT_TARGET


def _data(stdout: str) -> dict | None:
    """The first line of stdout that is a JSON object."""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _note(done) -> str:
    """The first line gbot complained about, in plain words."""
    if done.returncode == 0:
        return ""
    for text in (done.stderr, done.stdout):
        for line in (text or "").splitlines():
            if line.strip():
                return line.strip()[:NOTE_CHARS]
    return ""


KILL_GRACE_S = 2


def _stop_group(proc):
    """Stop gbot and everything it started (node, gbot.mjs): TERM first, KILL when that is not enough."""
    if not hasattr(os, "killpg"):
        # Windows has no process groups to signal; stop at least gbot itself.
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=KILL_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            continue


def run(args: list, timeout: float, wake: bool = False) -> Result:
    """Ask gbot something and keep what it said.

    Only a send may wake the Grok Bot app (wake=True); a read never starts or focuses it.
    gbot runs in its own process group, so a timeout stops node and gbot.mjs too.
    """
    env = dict(os.environ)
    env.setdefault("GBOT_WAKE_TIMEOUT", "20")
    env.setdefault("GBOT_RETRY_TIMEOUT", "30")
    if wake:
        env.pop("GBOT_NO_WAKE", None)
    else:
        env["GBOT_NO_WAKE"] = "1"
    try:
        proc = subprocess.Popen([openbot.GBOT, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.DEVNULL, text=True, env=env, start_new_session=True)
    except OSError as err:
        return Result(127, None, str(err))
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_group(proc)
        try:
            proc.communicate(timeout=KILL_GRACE_S)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass
        return Result(None, None, "gbot gave no answer")
    done = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    return Result(done.returncode, _data(done.stdout), _note(done))


# 75 means there is no live route, 127 that gbot or Node is not there: both stop the link.
STOPPED = (75, 127)


def parse_entries(entries) -> list[dict]:
    """Only what the bot showed the user: its own text messages."""
    parsed = []
    for entry in entries or []:
        if not isinstance(entry, dict) or entry.get("kind") != "send-message" or "toAgent" in entry:
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("type") != "text":
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parsed.append({"role": "bot", "text": content.strip(), "id": entry.get("id"),
                       "at": entry.get("timestampMs") or 0})
    return parsed


def last_id(entries) -> str:
    """The id of the last entry that has one, of any kind."""
    for entry in reversed(entries or []):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            return entry_id
    return ""


def _entries(data: dict) -> list:
    """The entries of the transcript, however gbot wrapped them."""
    transcript = data.get("transcript")
    entries = transcript.get("entries") if isinstance(transcript, dict) else None
    return entries if isinstance(entries, list) else []


def _cursor(data: dict, entries: list, old: str) -> str:
    """Where to ask for the answers that come after this."""
    cursor = data.get("cursor")
    if not isinstance(cursor, str) or not cursor:
        cursor = last_id(entries)
    return cursor or old


def _key(message: dict) -> str | None:
    """What makes an answer the same one as before: its id and time. Without an id there is
    no telling, so a second identical answer still shows."""
    entry_id = message.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return None
    return f"{entry_id}@{message.get('at') or 0}"


# A read that found no route stops the link; only a message of the user tries again.
STOPPED_READ = "Grok Bot: connection stopped{why}; send a message to try again."
UNSURE_NOTE = "No answer from gbot; the message may or may not have gone out."


def _stopped(rc: int, note: str, read: bool = False) -> str:
    """Why the link is closed."""
    if rc == 75 and read:
        return STOPPED_READ.format(why=f" ({note})" if note else "")
    if rc == 75:
        return f"Grok Bot: no live route ({note})" if note else "Grok Bot: no live route"
    return "Grok Bot: gbot is not installed or Node is missing"


def accepted(data) -> bool:
    """gbot 0.12 says delivery "unknown" even when the message went out; result.accepted is the answer."""
    if not isinstance(data, dict):
        return False
    result = data.get("result")
    return isinstance(result, dict) and result.get("accepted") is True


def _error(data, note: str, rc) -> str:
    """Why a message did not go out, in words."""
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        error = error.get("message")
    if isinstance(error, str) and error.strip():
        return error.strip()[:NOTE_CHARS]
    if note:
        return note
    if isinstance(data, dict) and data.get("delivery"):
        return f"not accepted (delivery: {data['delivery']})"[:NOTE_CHARS]
    return f"exit {rc}"


class GrokLink:
    """One Grok Bot bot: its thread, what it answered and what is still missing.

    It only asks when there is a reason: every FAST_S seconds for WAIT_MAX_S after a message
    went out, and once when the bubble opens. With nothing to wait for there is no polling at all.
    """

    FAST_S = 5
    WAIT_MAX_S = 600
    KEEP = 200
    LIMIT = 40
    # A first look (or a gap) shows only the latest few answers as history.
    FIRST_SHOW = 5
    TIMEOUT_S = 90
    UNSURE_MARK = " (?)"

    def __init__(self, target: str, now=time.monotonic):
        self.target = target
        self.now = now
        self.messages = []
        self.cursor = ""
        self.status = ""
        self.stopped = False
        self.waiting_since = None
        self.last_poll = None
        self.polling = False
        self.want_fetch = False
        # Stays in sight until an answer comes or the waiting ends: a look in between does not clear it.
        self.unsure = ""
        self.seen = set()
        self._lock = threading.Lock()

    @property
    def waiting(self) -> bool:
        """Is the bot still working on an answer?"""
        with self._lock:
            self._wait_over(self.now())
            return self.waiting_since is not None

    def _wait_over(self, now: float) -> bool:
        """The waiting ends by itself after WAIT_MAX_S; then the widget stops asking."""
        if self.waiting_since is not None and now - self.waiting_since >= self.WAIT_MAX_S:
            self.waiting_since = None
            self.unsure = ""
            self.status = f"No answer from {self.target} yet; open the chat later to look again."
            return True
        return False

    def request_fetch(self):
        """The bubble opened: look once for what came in."""
        with self._lock:
            recent = self.last_poll is not None and self.now() - self.last_poll < self.FAST_S
            if not self.stopped and not recent:
                self.want_fetch = True

    def active(self) -> bool:
        """Is there a reason to keep a timer: a look is asked for, running, or an answer is awaited."""
        with self._lock:
            self._wait_over(self.now())
            if self.stopped:
                return self.polling
            return self.want_fetch or self.polling or self.waiting_since is not None

    def due(self) -> bool:
        """Is it time to look for an answer?"""
        with self._lock:
            if self.stopped or self.polling:
                return False
            now = self.now()
            self._wait_over(now)
            if self.want_fetch:
                return True
            if self.waiting_since is None:
                return False
            return self.last_poll is None or self.last_poll < self.waiting_since or now - self.last_poll >= self.FAST_S

    def poll(self) -> bool:
        """Look for new answers; True when something new came in."""
        with self._lock:
            if self.polling:
                return False
            self.polling = True
            self.want_fetch = False
            cursor = self.cursor
        args = ["thread", self.target, "--limit", str(self.LIMIT)]
        if cursor:
            args += ["--after", cursor]
        args.append("--json")
        try:
            result = run(args, timeout=self.TIMEOUT_S)
        finally:
            with self._lock:
                self.polling = False
                self.last_poll = self.now()
        return self._apply(result)

    def _user_lines_after_the_last_bot(self) -> list:
        """The lines the user sent after the last answer of the bot."""
        last = -1
        for index, message in enumerate(self.messages):
            if message.get("role") == "bot":
                last = index
        return [m for m in self.messages[last + 1:] if m.get("role") == "user"]

    def _apply(self, result: Result) -> bool:
        """What came back of the thread: new answers, or the reason there are none."""
        with self._lock:
            if result.rc in STOPPED:
                self.stopped = True
                self.waiting_since = None
                self.want_fetch = False
                self.status = _stopped(result.rc, result.note, read=True)
                return False
            if result.rc != 0 or not isinstance(result.data, dict):
                self.status = f"Grok Bot did not answer: {result.note or 'no answer'}"
                return False
            data = result.data
            entries = _entries(data)
            parsed = parse_entries(entries)
            if not self.cursor or data.get("gapReset"):
                # A first look, or the thread was cut off: only the latest few answers, as history.
                shown = parsed[-self.FIRST_SHOW:]
                kept = self._user_lines_after_the_last_bot()
                self.messages = [{"role": m["role"], "text": m["text"]} for m in shown] + kept
                self.seen = {k for k in map(_key, parsed) if k}
                added = bool(shown)
            else:
                fresh = [m for m in parsed if _key(m) is None or _key(m) not in self.seen]
                self.messages += [{"role": m["role"], "text": m["text"]} for m in fresh]
                self.seen |= {k for k in map(_key, fresh) if k}
                added = bool(fresh)
            del self.messages[:-self.KEEP]
            if added:
                self.waiting_since = None
                self.unsure = ""
            self.status = ""
            self.cursor = _cursor(data, entries, self.cursor)
            return added

    def _sent(self, line: str):
        self.messages.append({"role": "user", "text": line})
        del self.messages[:-self.KEEP]
        self.waiting_since = self.now()
        self.stopped = False

    def send(self, text: str) -> tuple[bool, str]:
        """Send a message to the bot, never twice: a retry could send it twice.

        A send that timed out may have gone out: its line shows with a question mark, the
        widget waits for an answer as usual, and the status says it is not sure.
        """
        result = run(["send", self.target, "--json", "--", text], timeout=self.TIMEOUT_S, wake=True)
        if result.rc is None:
            with self._lock:
                self._sent(text + self.UNSURE_MARK)
                self.unsure = UNSURE_NOTE
            return True, ""
        if result.rc in STOPPED:
            with self._lock:
                self.stopped = True
                self.waiting_since = None
                self.status = _stopped(result.rc, result.note)
            return False, self.status
        if result.rc == 0 and accepted(result.data):
            with self._lock:
                self._sent(text)
                self.unsure = ""
                self.status = ""
            return True, ""
        return False, _error(result.data, result.note, result.rc)

    def resume(self):
        """The user sends again: one fresh attempt, no loop."""
        with self._lock:
            self.stopped = False
            self.status = ""

    def note(self) -> str:
        """What the bubble says under the conversation: why the link stopped, or that a send is unsure."""
        with self._lock:
            self._wait_over(self.now())
            return self.status or self.unsure

    def chat(self) -> dict:
        """The conversation so far, and what is still coming."""
        with self._lock:
            self._wait_over(self.now())
            messages = [{"role": m["role"], "text": m["text"]} for m in self.messages[-self.KEEP:]]
            activity = f"Waiting for {self.target}…" if self.waiting_since is not None else ""
        return {"messages": messages, "activity": activity}
