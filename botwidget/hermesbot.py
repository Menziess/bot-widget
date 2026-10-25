"""Hermes Bot through the hermes CLI: one bot's thread and what it answers.

Uses the hermes chat --format stream-json command for non-interactive
single-query mode, with the same polling/thread model as Grok Bot.
"""

import json
import os
import signal
import subprocess
import threading
import time
from subprocess import CompletedProcess
from typing import NamedTuple

from botwidget.config import widget_config

PREFIX = "hermes:"
DEFAULT_TARGET = "Hermes"
NOTE_CHARS = 200


class Result(NamedTuple):
    """What hermes said: its exit code, the JSON it printed and a note in plain words."""
    rc: int | None
    data: dict | None
    note: str


HERMES_CLI = "hermes"

# `hermes --version` takes about 0.2 s. The arc asks on the drag path, so the answer is kept a while.
INSTALLED_TTL_S = 300.0
_installed_cache: tuple | None = None  # (when, answer)


def is_hermes_installed() -> bool:
    """Check if the hermes CLI is installed and available; asked again after INSTALLED_TTL_S."""
    global _installed_cache
    now = time.monotonic()
    if _installed_cache is not None and now - _installed_cache[0] < INSTALLED_TTL_S:
        return _installed_cache[1]
    try:
        result = subprocess.run([HERMES_CLI, "--version"], capture_output=True, timeout=5)
        installed = result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        installed = False
    _installed_cache = (now, installed)
    return installed

def face_id(target: str = DEFAULT_TARGET) -> str:
    """The id of the face of a Hermes Bot bot."""
    return PREFIX + target


def is_hermes(agent_id: str) -> bool:
    """Is this the id of a Hermes Bot face?"""
    return isinstance(agent_id, str) and agent_id.startswith(PREFIX)


def target() -> str:
    """The Hermes Bot the widget talks to."""
    configured = widget_config().get("hermesbot_target")
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


def _note(done: CompletedProcess) -> str:
    """The first line hermes complained about, in plain words."""
    if done.returncode == 0:
        return ""
    for text in (done.stderr, done.stdout):
        for line in (text or "").splitlines():
            if line.strip():
                return line.strip()[:NOTE_CHARS]
    return ""


KILL_GRACE_S = 2


def _stop_group(proc):
    """Stop hermes and everything it started: TERM first, KILL when that is not enough."""
    if not hasattr(os, "killpg"):
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


def run(query: str, timeout: float) -> Result:
    """Ask hermes something and keep what it said.

    Uses the hermes chat --oneshot --format stream-json command for
    non-interactive mode. The output is JSON-lines with turn data.
    """
    try:
        proc = subprocess.Popen(
            [HERMES_CLI, "chat", "-q", query, "--oneshot", "--format", "stream-json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, start_new_session=True,
        )
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
        return Result(None, None, "hermes gave no answer")
    done = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    return Result(done.returncode, _data(done.stdout), _note(done))


# 127 means hermes is not found.
STOPPED = (127,)


def parse_message(stdout: str) -> str:
    """Extract the bot's answer from stream-json output."""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            # stream-json emits { "type": "response", "content": "..." } or similar
            content = obj.get("content") or obj.get("text") or obj.get("message")
            if isinstance(content, str) and content.strip():
                return content.strip()
            # Fallback: try deeper nesting
            data = obj.get("data")
            if isinstance(data, dict):
                content = data.get("content") or data.get("text")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return ""


class HermesLink:
    """One Hermes Bot bot: its thread, what it answered and what is still missing.

    It only asks when there is a reason: after a message went out, and once when
    the bubble opens. With nothing to wait for there is no polling at all.
    """

    FAST_S = 5
    WAIT_MAX_S = 300
    KEEP = 100
    FIRST_SHOW = 5
    TIMEOUT_S = 120
    UNSURE_MARK = " (?)"
    # How many recent messages to include in a query context.
    QUERY_HISTORY = 10

    def __init__(self, target: str, now=time.monotonic):
        self.target = target
        self.now = now
        self.messages = []
        self.status = ""
        self.stopped = False
        self.waiting_since = None
        self.last_poll = None
        self.polling = False
        self.want_fetch = False
        # Stays in sight until an answer comes or the waiting ends.
        self.unsure = ""
        self.seen = set()
        self._lock = threading.Lock()

    @property
    def is_polling(self) -> bool:
        """Is a poll running right now?"""
        with self._lock:
            return self.polling

    @property
    def waiting(self) -> bool:
        """Is the bot still working on an answer?"""
        with self._lock:
            self._wait_over(self.now())
            return self.waiting_since is not None

    def _wait_over(self, now: float) -> bool:
        """The waiting ends by itself after WAIT_MAX_S."""
        if self.waiting_since is not None and now - self.waiting_since >= self.WAIT_MAX_S:
            self.waiting_since = None
            self.unsure = ""
            self.status = f"No answer from {self.target} yet; try again later."
            return True
        return False

    def request_fetch(self):
        """The bubble opened: look once for what came in."""
        with self._lock:
            if not self.stopped and not self.polling:
                self.want_fetch = True

    def active(self) -> bool:
        """Is there a reason to keep a timer?"""
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
            return self.last_poll is None or now - self.last_poll >= self.FAST_S

    @property
    def last_poll(self):
        return getattr(self, "_last_poll", None)

    @last_poll.setter
    def last_poll(self, value):
        self._last_poll = value

    def poll(self) -> bool:
        """Look for new answers; True when something new came in."""
        with self._lock:
            if self.polling:
                return False
            self.polling = True
            self.want_fetch = False
        try:
            result = run(self._build_query(), timeout=self.TIMEOUT_S)
        finally:
            with self._lock:
                self.polling = False
                self.last_poll = self.now()
        return self._apply(result)

    def _build_query(self) -> str:
        """Build the query string from the conversation history."""
        with self._lock:
            recent = self.messages[-self.QUERY_HISTORY:] if self.messages else []
        lines = []
        for m in recent:
            role = "User" if m["role"] == "user" else self.target
            lines.append(f"{role}: {m['text']}")
        lines.append(f"{self.target}:")
        return "\n".join(lines) if lines else "Hello"

    def _apply(self, result: Result) -> bool:
        """What came back of the query: a new answer, or why there is none."""
        with self._lock:
            if result.rc in STOPPED:
                self.stopped = True
                self.waiting_since = None
                self.want_fetch = False
                self.status = f"Hermes Bot: hermes is not installed or not found"
                return False
            if result.rc != 0:
                self.status = f"Hermes Bot did not answer: {result.note or 'no answer'}"
                return False
            if not isinstance(result.data, dict):
                self.status = "Hermes Bot: unexpected response"
                return False
            text = parse_message(result.data.get("stdout", "") or "")
            if not text:
                text = result.data.get("message", "")
            if not text and isinstance(result.data, dict):
                for key in ("response", "content", "answer", "output"):
                    val = result.data.get(key, "")
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
            if not text:
                text = parse_message(result.data.get("stdout", ""))
            if not text:
                # Fallback: try the raw stdout from the result
                text = parse_message(result.data.get("raw", ""))
            if not text:
                self.status = "Hermes Bot: no answer content"
                return False
            # Add the answer if it's new (not a duplicate)
            key = f"{len(self.messages)}@{text[:50]}"
            if key not in self.seen:
                self.messages.append({"role": "bot", "text": text})
                self.seen.add(key)
                added = True
            else:
                added = False
            del self.messages[:-self.KEEP]
            if added:
                self.waiting_since = None
                self.unsure = ""
            self.status = ""
            return added

    def _sent(self, line: str):
        self.messages.append({"role": "user", "text": line})
        del self.messages[:-self.KEEP]
        self.waiting_since = self.now()
        self.stopped = False

    def send(self, text: str) -> tuple[bool, str]:
        """Send a message to the bot.

        Hermes uses --oneshot mode: it answers immediately and returns.
        A send that timed out may have gone out.
        """
        result = run(text, timeout=self.TIMEOUT_S)
        if result.rc is None:
            with self._lock:
                self._sent(text + self.UNSURE_MARK)
                self.unsure = "No answer from hermes; the message may or may not have gone out."
            return True, ""
        if result.rc in STOPPED:
            with self._lock:
                self.stopped = True
                self.waiting_since = None
                self.status = "Hermes Bot: hermes is not installed or not found"
            return False, self.status
        if result.rc == 0 and result.data:
            with self._lock:
                self._sent(text)
                self.unsure = ""
                self.status = ""
            # The answer comes back immediately — store it.
            text = parse_message(result.data.get("stdout", "") or "")
            if not text:
                text = result.data.get("message", "")
            if not text and isinstance(result.data, dict):
                for key in ("response", "content", "answer", "output"):
                    val = result.data.get(key, "")
                    if isinstance(val, str) and val.strip():
                        text = val.strip()
                        break
            if text:
                with self._lock:
                    self.messages.append({"role": "bot", "text": text})
                    del self.messages[:-self.KEEP]
            return True, ""
        return False, f"Hermes Bot: {result.note or f'exit {result.rc}'}"

    def resume(self):
        """The user sends again: one fresh attempt, no loop."""
        with self._lock:
            self.stopped = False
            self.status = ""

    def note(self) -> str:
        """What the bubble says under the conversation."""
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
