"""Read the one ntfy channel Grok bots publish on. The widget never writes to it."""

import json
import urllib.request
from threading import Event, Thread

import secrets

from botwidget.config import save_widget_config, widget_config

_STATES = {"start", "done", "stuck", "needs_you"}
_RETRY_S = 2
# Longer than a public ntfy keepalive, so a quiet stream is not treated as a drop.
_READ_TIMEOUT_S = 90


def channel() -> str:
    """The grok_relay topic or URL, or "" when the widget should not subscribe."""
    value = widget_config().get("grok_relay")
    if not isinstance(value, str):
        return ""
    return value.strip()


def stream_url(value: str) -> str:
    """The JSON stream for a topic name or an http(s) URL. "" when value is blank."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        if text.endswith("/"):
            text = text[:-1]
        if not text.endswith("/json"):
            text += "/json"
        return text
    return "https://ntfy.sh/" + text + "/json"


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _timestamp(value):
    """An int, a float, or a non-empty string. A bool is not a timestamp."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None



def new_topic() -> str:
    """A fresh public ntfy topic name the widget created."""
    return "bw-" + secrets.token_urlsafe(18)


def chief_prompt(topic: str) -> str:
    """One pasteable instruction for General so every Grok bot shares this relay."""
    topic = topic.strip()
    return (
        f"Bot Widget linked Grok bots on ntfy topic {topic} (https://ntfy.sh/{topic}). "
        "Tell every Grok bot to publish status JSON there: "
        '{bot, state: start|done|stuck|needs_you, summary, ts}. '
        "Send one roster once as "
        "{bots:[{name, team, color, face, chat_url}, ...]}; a routine may resend roster and usage. "
        "Do not ask the user to configure each bot."
    )


def link_channel(*, topic: str | None = None) -> dict:
    """Create (or reuse) the channel in widget.json. Returns topic + chief prompt."""
    name = (topic or new_topic()).strip()
    if not name:
        name = new_topic()
    save_widget_config(grok_relay=name)
    return {"topic": name, "prompt": chief_prompt(name)}


def parse(raw):
    """A roster or a status line, or None when the message is not one of those."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    if "event" in raw:
        if raw.get("event") != "message":
            return None
        return parse(raw.get("message"))
    if "bots" in raw:
        bots = raw["bots"]
        if not isinstance(bots, list):
            return None
        kept = []
        for entry in bots:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            kept.append({
                "name": name.strip(),
                "team": _text(entry.get("team")),
                "color": _text(entry.get("color")),
                "face": _text(entry.get("face")),
                "chat_url": _text(entry.get("chat_url")),
            })
        return {"kind": "roster", "bots": kept}
    bot = raw.get("bot")
    state = raw.get("state")
    if not isinstance(bot, str) or not bot.strip():
        return None
    if not isinstance(state, str) or state.strip().lower() not in _STATES:
        return None
    return {
        "kind": "status",
        "bot": bot.strip(),
        "state": state.strip().lower(),
        "summary": _text(raw.get("summary")),
        "ts": _timestamp(raw.get("ts")),
    }


def listen(url, on_text, stop):
    """GET the stream until stop. Each non-empty line is handed to on_text.

    shortcut: fixed 2s retry, back off if a public ntfy starts to rate-limit.
    """
    while not stop.is_set():
        try:
            with urllib.request.urlopen(url, timeout=_READ_TIMEOUT_S) as response:
                while not stop.is_set():
                    line = response.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", "replace").strip()
                    if text:
                        on_text(text)
        except Exception:
            pass
        if stop.wait(_RETRY_S):
            return


class Relay:
    """Start the subscriber once. listen owns reconnects; this thread does not loop."""

    def __init__(self, on_message, listen=None):
        self._on_message = on_message
        self._listen = listen
        self._thread = None
        self._stop = Event()

    def start(self):
        # A second start (the link button writes the channel, then starts) must not open two streams.
        if self._thread is not None:
            return
        url = stream_url(channel())
        if not url:
            return
        # Look up the module function now, so a test patch of grok_relay.listen is the one that runs.
        # Thread is the class captured at import, so a patch of faces.threading.Thread does not swallow it.
        worker = self._listen or globals()["listen"]
        self._thread = Thread(target=worker, args=(url, self._deliver, self._stop), daemon=True)
        self._thread.start()

    def _deliver(self, raw):
        parsed = parse(raw)
        if isinstance(parsed, dict):
            self._on_message(parsed)
