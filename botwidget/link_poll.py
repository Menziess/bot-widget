"""The part of a polled bot link that is the same for Grok and Hermes.

Each link still asks in its own way. This only keeps the wait, the timer and the
conversation the two links already kept the same way.
"""

import threading
import time


class PolledLink:
    """One bot: what it answered, and whether the widget is still waiting."""

    WAIT_MAX_S = 600
    KEEP = 200

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

    def _gave_up(self) -> str:
        return f"No answer from {self.target} yet; open the chat later to look again."

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
        """The waiting ends by itself after WAIT_MAX_S; then the widget stops asking."""
        if self.waiting_since is not None and now - self.waiting_since >= self.WAIT_MAX_S:
            self.waiting_since = None
            self.unsure = ""
            self.status = self._gave_up()
            return True
        return False

    def active(self) -> bool:
        """Is there a reason to keep a timer: a look is asked for, running, or an answer is awaited."""
        with self._lock:
            self._wait_over(self.now())
            if self.stopped:
                return self.polling
            return self.want_fetch or self.polling or self.waiting_since is not None

    def _sent(self, line: str):
        self.messages.append({"role": "user", "text": line})
        del self.messages[:-self.KEEP]
        self.waiting_since = self.now()
        self.stopped = False

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
