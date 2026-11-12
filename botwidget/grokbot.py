"""Grok Bot through the gbot command: one bot's thread and what it answers."""

import os
import subprocess
import time

from botwidget import openbot
from botwidget.cli_json import (
    NOTE_CHARS,
    Result,
    finish_cli,
    first_line_note as _note,
    json_object as _data,
    stop_group as _stop_group,
)
from botwidget.config import named_text, widget_config
from botwidget.link_poll import PolledLink

PREFIX = "grok:"
DEFAULT_TARGET = "General"


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


def _clean_avatar(value) -> dict | None:
    """Only the shape and colour of an avatar, both as non-empty strings."""
    if not isinstance(value, dict):
        return None
    avatar = {key: value[key].strip() for key in ("shape", "color")
              if isinstance(value.get(key), str) and value[key].strip()}
    return avatar or None


def _by_name(mapping, target: str) -> dict | None:
    if not isinstance(mapping, dict):
        return None
    wanted = (target or "").strip().lower()
    for name, value in mapping.items():
        if isinstance(name, str) and name.strip().lower() == wanted:
            return _clean_avatar(value)
    return None


def configured_avatar(target: str) -> dict | None:
    """The avatar widget.json names for this bot under grokbot_avatars, e.g.
    {"General": {"shape": "blob", "color": "black"}}: for when Grok Bot cannot be asked."""
    return _by_name(widget_config().get("grokbot_avatars"), target)


def pick_avatar(live, target: str, cached=None) -> dict | None:
    """The face a Grok Bot bot wears: what Grok Bot says now, else widget.json, else what Grok
    Bot said last time (cached by name); None keeps the face the widget derives from its seed."""
    return _clean_avatar(live) or configured_avatar(target) or _by_name(cached, target)


def is_grok(agent_id: str) -> bool:
    """Is this the id of a Grok Bot face?"""
    return isinstance(agent_id, str) and agent_id.startswith(PREFIX)


def target() -> str:
    """The Grok Bot the widget talks to."""
    return named_text(widget_config(), "grokbot_target", DEFAULT_TARGET)


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
    return finish_cli(proc, timeout, "gbot gave no answer", _stop_group)


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


def _in_thread_order(entries: list, shown: list, kept: list) -> list:
    """The latest answers with the lines the user sent here, each where the thread has it.

    A line the thread already holds goes before the answers that came after it; a line it does
    not hold yet goes last.
    """
    ids = {m.get("id") for m in shown if m.get("id")}
    texts = {m["text"]: m for m in shown}
    waiting = list(kept)
    ordered = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") == "message" and entry.get("role") == "user":
            content = entry.get("content")
            if not isinstance(content, str):
                continue
            line = next((m for m in waiting if m["text"].removesuffix(GrokLink.UNSURE_MARK) == content.strip()), None)
            if line is not None:
                waiting.remove(line)
                ordered.append(line)
        elif entry.get("kind") == "send-message":
            match = [m for m in shown if m.get("id") and m.get("id") == entry.get("id")]
            if match and match[0]["id"] in ids:
                ids.discard(match[0]["id"])
                ordered.append({"role": "bot", "text": match[0]["text"]})
    if ids or len([m for m in ordered if m["role"] == "bot"]) != len(shown):
        ordered = [m for m in ordered if m["role"] == "user"]
        ordered = [{"role": "bot", "text": m["text"]} for m in shown] + ordered
    return ordered + waiting


def _key(message: dict) -> str | None:
    """What makes an answer the same one as before: its id and time. Without an id there is
    no telling, so a second identical answer still shows."""
    entry_id = message.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return None
    return f"{entry_id}@{message.get('at') or 0}"


# A read that found no route stops the link; only a message of the user tries again.
STOPPED_READ = "Grok Bot: connection stopped{why}; send a message to try again."
NO_ROUTE_WAITING = "Grok Bot is out of reach for a moment; still looking for the answer."
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


class GrokLink(PolledLink):
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
        super().__init__(target, now)
        self.cursor = ""

    def request_fetch(self):
        """The bubble opened: look once for what came in."""
        with self._lock:
            recent = self.last_poll is not None and self.now() - self.last_poll < self.FAST_S
            if not self.stopped and not recent:
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
            if result.rc == 75 and self.waiting_since is not None:
                # The route can drop for a moment, e.g. while the app restarts right after a send: an
                # answer is still on its way, so keep looking until the wait ends instead of stopping.
                self.status = NO_ROUTE_WAITING
                return False
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
                self.messages = _in_thread_order(entries, shown, kept)
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
