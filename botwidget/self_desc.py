"""What the bot may ask the widget about itself: its commands and settings, and a few things to run or change.

Nothing here is sent up front. The agent asks per topic, so the prompt stays as short as it was.
"""

import json

from botwidget import config
from botwidget.acp_bots import strip_secrets

# Settings that grant access or hold a one-time marker are never changed by the bot.
LOCKED = {"remote_control", "login_default_applied", "unlinked_hint_shown"}


def commands_text(rows) -> str:
    return "\n".join(f"{name}: {note}" for name, note in rows)


def settings_text(key: str = "") -> str:
    shown = strip_secrets(config.widget_config())
    if not key:
        return "Settings (ask with a key for the value): " + ", ".join(sorted(config.SETTING_KEYS))
    if key not in config.SETTING_KEYS:
        return f"There is no setting called {key}. Do not guess one."
    return json.dumps(shown[key], ensure_ascii=False) if key in shown else f"{key} is not set: the default applies."


def change_setting(key: str, value: str) -> str:
    """An error text, or empty when it was saved."""
    if key not in config.SETTING_KEYS or key in LOCKED:
        return f"{key} cannot be changed here."
    current = config.widget_config().get(key)
    if isinstance(current, (dict, list)):
        return f"{key} holds a list or a group: change it on the /bots or /connections page."
    try:
        new = json.loads(value)
    except ValueError:
        new = value
    if isinstance(new, (dict, list)) or (current is not None and type(new) is not type(current)):
        return f"{key} is {json.dumps(current)}: give a value of the same kind."
    config.save_widget_config(**{key: new})
    return ""


def answer(method: str, params: dict, rows, start, move) -> dict:
    """The widget's reply to one question from the agent. `start` sends a command through the face and `move` puts
    the face somewhere, both on the UI thread."""
    if method == "commands":
        return {"text": commands_text(rows)}
    if method == "settings":
        return {"text": settings_text(str(params.get("key") or ""))}
    if method == "run":
        text = str(params.get("name") or "").strip()
        if text.split(" ", 1)[0].lower() not in {row[0].lower() for row in rows}:
            return {"error": f"{text} is not one of the commands in about_me topic commands."}
        start(text)
        return {"text": f"{text} started."}
    if method == "move":
        from botwidget.system.control import ControlUnavailable, desktop, edge_point
        try:
            x, y = (edge_point(str(params["edge"]), desktop.screen, desktop.size) if params.get("edge")
                    else (int(params.get("x") or 0), int(params.get("y") or 0)))
        except ControlUnavailable as error:
            return {"error": str(error)}
        move(x, y)
        return {"text": f"moved to {x},{y}"}
    if method == "set":
        problem = change_setting(str(params.get("key") or ""), str(params.get("value") or ""))
        return {"error": problem} if problem else {"text": "Saved. Some settings apply after a restart."}
    return {"error": f"unknown question {method}"}
