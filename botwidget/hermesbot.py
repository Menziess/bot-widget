"""Hermes Bot through the hermes CLI: one bot's thread and what it answers.

Uses the hermes chat --format stream-json command for non-interactive
single-query mode, with the same polling/thread model as Grok Bot.
"""

import json
import subprocess
import time

from botwidget.cli_json import (
    Result,
    finish_cli,
    first_line_note as _note,
    json_object as _data,
    stop_group as _stop_group,
)
from botwidget.config import named_text, widget_config
from botwidget.link_poll import PolledLink

PREFIX = "hermes:"
DEFAULT_TARGET = "Hermes"


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
    return named_text(widget_config(), "hermesbot_target", DEFAULT_TARGET)


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
    return finish_cli(proc, timeout, "hermes gave no answer", _stop_group)


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


def _answer_text(data: dict) -> str:
    """The first answer hermes put in a JSON object."""
    text = parse_message(data.get("stdout", "") or "")
    if text:
        return text
    message = data.get("message", "")
    if message:
        return message
    for key in ("response", "content", "answer", "output"):
        value = data.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class HermesLink(PolledLink):
    """One Hermes Bot bot: its thread, what it answered and what is still missing.

    It only asks when there is a reason: after a message went out, and once when
    the bubble opens. With nothing to wait for there is no polling at all.
    """

    FAST_S = 5
    WAIT_MAX_S = 300
    KEEP = 100
    TIMEOUT_S = 120
    UNSURE_MARK = " (?)"
    # How many recent messages to include in a query context.
    QUERY_HISTORY = 10

    def _gave_up(self) -> str:
        return f"No answer from {self.target} yet; try again later."

    def request_fetch(self):
        """The bubble opened: look once for what came in."""
        with self._lock:
            if not self.stopped and not self.polling:
                self.want_fetch = True

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
            text = _answer_text(result.data)
            if not text:
                text = parse_message(result.data.get("stdout", ""))
            if not text:
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
            text = _answer_text(result.data)
            if text:
                with self._lock:
                    self.messages.append({"role": "bot", "text": text})
                    del self.messages[:-self.KEEP]
            return True, ""
        return False, f"Hermes Bot: {result.note or f'exit {result.rc}'}"
