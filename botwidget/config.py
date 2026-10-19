"""Vaste instellingen: paden, de bot-id, venstermaten en widget.json."""

import json
import os

from botwidget.system.current import data_home

# Eigen toestand van de widget (positie, instellingen); los van OpenBot.
APP_DIR = os.path.join(data_home(), "botwidget")

# De botlijst komt uit de lokale OpenBot-store: het agent-token van de
# automatisering geeft alleen toegang tot de eigen agent, niet tot de andere.
OPENBOT_DIR = os.environ.get("BOT_WIDGET_OPENBOT_DIR") or os.path.join(data_home(), "OpenBot")
URL_FILE = os.path.join(OPENBOT_DIR, "automation", "url")
HEADERS_FILE = os.path.join(OPENBOT_DIR, "automation", "headers")
DB_FILE = os.path.join(OPENBOT_DIR, "openbot.db")

STATE_PATH = os.path.join(APP_DIR, "faces.json")

OPENBOT_URL = "https://openbot.run/"
GROKBOT_URL = "https://x.ai/bot"

# Het gezicht dat er staat zolang er geen bot van de gebruiker is gevonden.
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
POLL_INTERVAL = 3  # seconds, als de bot stil is
WORK_POLL_INTERVAL = 1  # seconde, zolang de beurt loopt


# Instellingen staan los van faces.json; hier komen geen secrets in.
CONFIG_PATH = os.path.join(APP_DIR, "widget.json")


SETTING_KEYS = ("sound", "always_on_top", "check_updates")


def always_on_top() -> bool:
    """Standaard boven andere vensters, zodat het gezicht altijd te zien is."""
    return widget_config().get("always_on_top") is not False


def check_updates() -> bool:
    """Standaard één keer per start vragen of er een nieuwere versie is."""
    return widget_config().get("check_updates") is not False


def widget_config() -> dict:
    """widget.json, of leeg als het bestand ontbreekt of stuk is."""
    try:
        with open(CONFIG_PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_widget_config(**values) -> dict:
    """widget.json bijwerken; alleen de sleutels die de widget kent."""
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
