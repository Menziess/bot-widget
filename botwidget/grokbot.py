"""Grok Bot through the gbot command: one bot's thread and what it answers."""

import json
import os
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


def run(args: list, timeout: float) -> Result:
    """Ask gbot something and keep what it said."""
    env = dict(os.environ)
    env.setdefault("GBOT_WAKE_TIMEOUT", "20")
    env.setdefault("GBOT_RETRY_TIMEOUT", "30")
    try:
        done = subprocess.run([openbot.GBOT, *args], capture_output=True, text=True,
                              timeout=timeout, stdin=subprocess.DEVNULL, env=env, check=False)
    except subprocess.TimeoutExpired:
        return Result(None, None, "gbot gave no answer")
    except OSError as err:
        return Result(127, None, str(err))
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


def _key(message: dict) -> str:
    """What makes an answer the same one as before."""
    entry_id = message.get("id")
    return entry_id if isinstance(entry_id, str) and entry_id else "text:" + message["text"]


def _stopped(rc: int, note: str) -> str:
    """Why the link is closed."""
    if rc == 75:
        return f"Grok Bot: no live route ({note})" if note else "Grok Bot: no live route"
    return "Grok Bot: gbot is not installed or Node is missing"


class GrokLink:
    """One Grok Bot bot: its thread, what it answered and what is still missing."""

    FAST_S = 3
    IDLE_S = 60
    WAIT_MAX_S = 600
    KEEP = 200
    LIMIT = 40
    TIMEOUT_S = 90

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
        self.seen = set()
        self._lock = threading.Lock()

    @property
    def waiting(self) -> bool:
        """Is the bot still working on an answer?"""
        with self._lock:
            self._wait_over(self.now())
            return self.waiting_since is not None

    def _wait_over(self, now: float) -> bool:
        """The waiting ends by itself after a while; after that the widget checks every minute."""
        if self.waiting_since is not None and now - self.waiting_since >= self.WAIT_MAX_S:
            self.waiting_since = None
            self.status = f"No answer from {self.target} yet; I'll check every minute."
            return True
        return False

    def due(self) -> bool:
        """Is it time to look for an answer?"""
        with self._lock:
            if self.stopped or self.polling:
                return False
            now = self.now()
            self._wait_over(now)
            if self.last_poll is None:
                return True
            waited = now - self.last_poll
            return waited >= (self.FAST_S if self.waiting_since is not None else self.IDLE_S)

    def poll(self) -> bool:
        """Look for new answers; True when something new came in."""
        with self._lock:
            if self.polling:
                return False
            self.polling = True
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
                self.status = _stopped(result.rc, result.note)
                return False
            if result.rc != 0 or not isinstance(result.data, dict):
                self.status = f"Grok Bot did not answer: {result.note or 'no answer'}"
                return False
            data = result.data
            entries = _entries(data)
            parsed = parse_entries(entries)
            if not self.cursor or data.get("gapReset"):
                # The thread was cut off: what came back is all there is.
                kept = self._user_lines_after_the_last_bot()
                self.messages = [{"role": m["role"], "text": m["text"]} for m in parsed] + kept
                self.seen = {_key(m) for m in parsed}
                added = bool(parsed)
            else:
                fresh = [m for m in parsed if _key(m) not in self.seen]
                self.messages += [{"role": m["role"], "text": m["text"]} for m in fresh]
                self.seen |= {_key(m) for m in fresh}
                added = bool(fresh)
            del self.messages[:-self.KEEP]
            if added:
                self.waiting_since = None
            self.status = ""
            self.cursor = _cursor(data, entries, self.cursor)
            return added

    def send(self, text: str) -> tuple[bool, str]:
        """Send a message to the bot; never twice, a retry could send it twice."""
        result = run(["send", self.target, "--json", "--", text], timeout=self.TIMEOUT_S)
        if result.rc is None:
            return False, "no answer from gbot; the message may or may not have gone out"
        if result.rc in STOPPED:
            with self._lock:
                self.stopped = True
                self.waiting_since = None
                self.status = _stopped(result.rc, result.note)
            return False, self.status
        delivery = (result.data or {}).get("delivery")
        if result.rc == 0 and delivery != "rejected":
            with self._lock:
                self.messages.append({"role": "user", "text": text})
                del self.messages[:-self.KEEP]
                self.waiting_since = self.now()
                self.stopped = False
                self.status = ""
            return True, ""
        error = (result.data or {}).get("error")
        if isinstance(error, dict):
            error = error.get("message")
        if not isinstance(error, str) or not error.strip():
            error = result.note or f"exit {result.rc}"
        return False, error.strip()[:NOTE_CHARS]

    def resume(self):
        """The user sends again: one fresh attempt, no loop."""
        with self._lock:
            self.stopped = False
            self.status = ""

    def chat(self) -> dict:
        """The conversation so far, and what is still coming."""
        with self._lock:
            self._wait_over(self.now())
            messages = [{"role": m["role"], "text": m["text"]} for m in self.messages[-self.KEEP:]]
            activity = f"Waiting for {self.target}…" if self.waiting_since is not None else ""
        return {"messages": messages, "activity": activity}
