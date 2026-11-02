"""Add, edit and remove the harness bots the widget shows, and check widget.json before it is saved.

The key itself never enters this file. A bot only names the file the key is read from.
"""

import json
import os
import sys

from botwidget.acplink import PREFIX, _slug
from botwidget.avatar import GROK_HEX, SUPPORTED_SHAPES

FACES = SUPPORTED_SHAPES
COLORS = ("blue", "green", "violet", "orange", "red", "cyan", "magenta", "yellow")
DEFAULT_BASE = "http://127.0.0.1:8080/v1"
DEFAULT_MODEL = "local"
DEFAULT_KEY = "~/.config/llm/key"
# A pasted key hides under one of these names. The path in key_file is not a secret.
SECRET_KEYS = {"api_key", "apikey", "token", "secret", "password", "authorization", "harness_model_api_key"}


def _secret(key: str) -> bool:
    folded = str(key).lower().replace("-", "_")
    return folded in SECRET_KEYS or folded.endswith("_api_key") or folded.endswith("_token")


def default_command() -> str:
    """The lean agent from this checkout, or the installed one when the checkout is not beside the package."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(root, "harness")):
        return f"env PYTHONPATH={root} {sys.executable} -m harness.agent"
    return f"{sys.executable} -m harness.agent"


def blank() -> dict:
    """What New bot shows before anything is typed. The address is the local llama.cpp server."""
    return {"id": "", "stored_id": "", "name": "", "face": "nuage", "color": "blue",
            "base_url": DEFAULT_BASE, "model": DEFAULT_MODEL, "key_file": DEFAULT_KEY, "command": ""}


def fields_of(bot: dict) -> dict:
    """The form for a bot that already exists."""
    env = bot.get("env") or {}
    face_id = bot.get("id") or ""
    stored = face_id[len(PREFIX):] if str(face_id).startswith(PREFIX) else str(face_id)
    return {"id": face_id, "stored_id": stored, "name": bot.get("name") or "",
            "face": bot.get("face") or "nuage", "color": bot.get("color") or "blue",
            "base_url": env.get("HARNESS_MODEL_BASE_URL") or DEFAULT_BASE,
            "model": env.get("HARNESS_MODEL") or DEFAULT_MODEL,
            "key_file": bot.get("key_file") or DEFAULT_KEY,
            "command": bot.get("command") or ""}


def cycle(kind: str, current: str) -> str:
    options = FACES if kind == "face" else COLORS
    if current not in options:
        return options[0]
    return options[(options.index(current) + 1) % len(options)]


def _unique(name: str, taken: set) -> str:
    base = _slug(name) or "bot"
    ident, n = base, 2
    while ident in taken:
        ident = f"{base}-{n}"
        n += 1
    return ident


def _entry(fields: dict, previous: dict | None, taken: set) -> tuple:
    """One acp_bots object, or an error the page can show."""
    name = str(fields.get("name") or "").strip()
    if not name or any(ch in name for ch in "\n\r"):
        return None, "A bot needs a name."
    base = str(fields.get("base_url") or "").strip()
    if not base.startswith(("http://", "https://")):
        return None, "The model address has to start with http:// or https://."
    model = str(fields.get("model") or "").strip()
    if not model:
        return None, "A bot needs a model name."
    key_file = str(fields.get("key_file") or "").strip()
    if not key_file:
        return None, "A bot needs a key file. The file holds the key; this form only keeps the path."
    face, color = str(fields.get("face") or ""), str(fields.get("color") or "")
    if face not in FACES:
        return None, "Pick a face from the list."
    if color not in COLORS:
        return None, "Pick a colour from the list."
    stored = str(fields.get("stored_id") or "").strip()
    if stored.startswith(PREFIX):
        stored = stored[len(PREFIX):]
    if not stored:
        stored = _unique(name, taken)
    elif stored in taken:
        return None, "Another bot already uses that id."
    env = {key: str(value) for key, value in ((previous or {}).get("env") or {}).items()
           if str(key).startswith("HARNESS_") and not _secret(key)}
    env.update(HARNESS_BOT=name, HARNESS_MODEL_BASE_URL=base, HARNESS_MODEL=model)
    command = str(fields.get("command") or (previous or {}).get("command") or "").strip() or default_command()
    return {"id": stored, "name": name, "command": command, "env": env, "key_file": key_file,
            "face": face, "color": color}, ""


def commit(fields: dict, existing) -> tuple:
    """The bot list with this form saved into it. The first item is None when the form is not usable."""
    rows = [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    stored = str(fields.get("stored_id") or "")
    if stored.startswith(PREFIX):
        stored = stored[len(PREFIX):]
    previous = next((row for row in rows if str(row.get("id") or "") == stored), None) if stored else None
    taken = {str(row.get("id") or "") for row in rows if str(row.get("id") or "") != stored}
    # A bot saved before ids existed is still the one being edited when the face id matches its name.
    if previous is None and stored:
        previous = next((row for row in rows if _slug(str(row.get("name") or "")) == stored and not row.get("id")), None)
    entry, error = _entry(fields, previous, taken)
    if error:
        return None, error
    out, replaced = [], False
    for row in rows:
        same = previous is not None and row is previous
        if same or (str(row.get("id") or "") == entry["id"]):
            out.append(entry)
            replaced = True
        else:
            out.append(row)
    if not replaced:
        out.append(entry)
    return out, ""


def without(existing, face_id: str) -> list:
    stored = face_id[len(PREFIX):] if str(face_id).startswith(PREFIX) else str(face_id)
    rows = [row for row in existing if isinstance(row, dict)] if isinstance(existing, list) else []
    return [row for row in rows if str(row.get("id") or _slug(str(row.get("name") or ""))) != stored]


def _agent(bot: dict) -> tuple:
    env = tuple(sorted((bot.get("env") or {}).items()))
    return (bot.get("command") or "", bot.get("key_file") or "", env)


def plan(before: list, after: list) -> list:
    """What one save changes: open a new bot, restyle a look, restart one agent, or close one.

    A new colour does not restart the agent. A new model does, and only for that bot.
    """
    old = {bot["id"]: bot for bot in before}
    new = {bot["id"]: bot for bot in after}
    steps = [("close", ident) for ident in old if ident not in new]
    for ident, bot in new.items():
        if ident not in old:
            steps.append(("open", ident))
        elif _agent(old[ident]) != _agent(bot):
            steps.append(("restart", ident))
        elif (old[ident].get("name"), old[ident].get("face"), old[ident].get("color")) != (
                bot.get("name"), bot.get("face"), bot.get("color")):
            steps.append(("restyle", ident))
    return steps


def strip_secrets(value):
    """The same document with every key-shaped field removed, so the editor cannot show one."""
    if isinstance(value, dict):
        return {key: strip_secrets(item) for key, item in value.items() if not _secret(key)}
    if isinstance(value, list):
        return [strip_secrets(item) for item in value]
    return value


def public_text(data: dict) -> str:
    return json.dumps(strip_secrets(data if isinstance(data, dict) else {}), indent=2) + "\n"


def _secret_path(value, path: str) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            if _secret(key):
                return path + key
            found = _secret_path(item, path + key + ".")
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _secret_path(item, path)
            if found:
                return found
    return ""


def _check_bots(rows) -> str:
    if rows is None:
        return ""
    if not isinstance(rows, list):
        return "acp_bots has to be a list."
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return f"Bot {index} has to be an object."
        if not str(row.get("name") or "").strip() or not str(row.get("command") or "").strip():
            return f"Bot {index} needs a name and a command."
        env = row.get("env")
        if env is not None and not isinstance(env, dict):
            return f"Bot {index} has an env that is not an object."
        face, color = row.get("face"), row.get("color")
        if face not in (None, "") and face not in FACES:
            return f"Bot {index} has a face the widget cannot draw."
        if color not in (None, "") and color not in COLORS:
            return f"Bot {index} has a colour the widget does not know."
    return ""


def parse_editor(text: str) -> tuple:
    """The document to save, or an error. Nothing is written here."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        return None, f"widget.json is not valid JSON ({error.msg})."
    if not isinstance(data, dict):
        return None, "widget.json has to be a JSON object."
    secret = _secret_path(data, "")
    if secret:
        return None, f"The key stays in key_file. Remove {secret} from the text."
    error = _check_bots(data.get("acp_bots"))
    if error:
        return None, error
    return data, ""
