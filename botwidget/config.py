"""Fixed settings: paths, the bot id, window sizes and widget.json."""

import json
import os

from botwidget.system.current import data_home

# The widget's own state (position, settings); separate from OpenBot.
APP_DIR = os.path.join(data_home(), "botwidget")

# The bot list comes from the local OpenBot store: the agent token of the automation only gives
# access to its own agent, not to the others.
OPENBOT_DIR = os.environ.get("BOT_WIDGET_OPENBOT_DIR") or os.path.join(data_home(), "OpenBot")
URL_FILE = os.path.join(OPENBOT_DIR, "automation", "url")
HEADERS_FILE = os.path.join(OPENBOT_DIR, "automation", "headers")
DB_FILE = os.path.join(OPENBOT_DIR, "openbot.db")

STATE_PATH = os.path.join(APP_DIR, "faces.json")

OPENBOT_URL = "https://openbot.run/"
GROKBOT_URL = "https://x.ai/bot"

# The face shown as long as none of the user's bots is found.
UNLINKED_ID = "unlinked"
UNLINKED_NAME = "Bot"


def read_file(path: str) -> str:
    """Read and strip whitespace from a config file; return '' on failure."""
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except (OSError, IOError):
        return ""


def _resolve_url() -> str:
    """Return the API base URL from the config file, falling back to a default."""
    url = read_file(URL_FILE)
    return url or "http://127.0.0.1:41673"


# Runtime-resolved values (read once at import)
API_URL: str = _resolve_url()

DOT_COLOR = "#FF4757"
POLL_INTERVAL = 3  # seconds, when the bot is quiet
WORK_POLL_INTERVAL = 1  # second, while the turn is running


# Settings are separate from faces.json; no secrets go in here.
CONFIG_PATH = os.path.join(APP_DIR, "widget.json")


SETTING_KEYS = ("sound", "always_on_top", "check_updates", "auto_update", "login_default_applied",
                "local_command")


def always_on_top() -> bool:
    """Above other windows by default, so the face is always visible."""
    return widget_config().get("always_on_top") is not False


def check_updates() -> bool:
    """By default ask once per start whether there is a newer version."""
    return widget_config().get("check_updates") is not False


def auto_update() -> bool:
    """By default stage updates ourselves and install them at the next start."""
    return widget_config().get("auto_update") is not False


def widget_config() -> dict:
    """widget.json, or empty if the file is missing or broken."""
    try:
        with open(CONFIG_PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_widget_config(**values) -> dict:
    """Update widget.json; only the keys the widget knows."""
    data = widget_config()
    data.update({k: v for k, v in values.items() if k in SETTING_KEYS})
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
    except OSError:
        pass
    return data
