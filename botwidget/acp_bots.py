"""Add, edit and remove the harness bots the widget shows, and check widget.json before it is saved.

The key itself never enters this file. A bot only names the file the key is read from.
"""

import json
import os
import shlex
import sys

from botwidget.acplink import PREFIX, _slug
from botwidget.avatar import GROK_HEX, SUPPORTED_SHAPES

FACES = SUPPORTED_SHAPES
COLORS = ("blue", "green", "violet", "orange", "red", "cyan", "magenta", "yellow")
DEFAULT_BASE = "http://127.0.0.1:8081/v1"
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
    quote = (lambda path: f'"{path}"') if os.name == "nt" else shlex.quote  # "Bot Widget.app" has a space
        return f"env PYTHONPATH={quote(root)} {quote(sys.executable)} -m harness.agent"
    return f"{quote(sys.executable)} -m harness.agent"


def blank() -> dict:
    """What New bot shows before anything is typed. With no connection picked, the address is the local server."""
    return {"id": "", "stored_id": "", "name": "", "face": "nuage", "color": "blue", "connection": "",
            "base_url": DEFAULT_BASE, "model": DEFAULT_MODEL, "key_file": DEFAULT_KEY,
            "command": "", "workspace": "", "workspace_permissions": "allow"}


def fields_of(bot: dict) -> dict:
    """The form for a bot that already exists."""
    env = bot.get("env") or {}
    face_id = bot.get("id") or ""
    stored = face_id[len(PREFIX):] if str(face_id).startswith(PREFIX) else str(face_id)
    ws = env.get("HARNESS_WORKSPACE") or ""
    ws_perm = env.get("HARNESS_WORKSPACE_PERMISSIONS") or "allow"
    return {"id": face_id, "stored_id": stored, "name": bot.get("name") or "",
            "face": bot.get("face") or "", "color": bot.get("color") or "",
            "connection": bot.get("connection") or "",
            "base_url": env.get("HARNESS_MODEL_BASE_URL") or DEFAULT_BASE,
            "model": env.get("HARNESS_MODEL") or DEFAULT_MODEL,
            "key_file": bot.get("key_file") or DEFAULT_KEY,
            "command": bot.get("command") or "",
            "workspace": ws, "workspace_permissions": ws_perm}


WS_PERMISSIONS = ("ask", "allow", "allow_session")
# "allow" is the durable allowlist for reads/search/git-read; "allow_session"
# remembers a granted write until the process exits.
WS_PERMISSION_ALIASES = {"allowlist": "allow", "allow-for-session": "allow_session"}


def normalise_workspace_permission(value: str) -> str:
    raw = (value or "allow").strip()
    return WS_PERMISSION_ALIASES.get(raw, raw)


def cycle(kind: str, current: str) -> str:
    if kind == "workspace_permission":
        options = WS_PERMISSIONS
        current = normalise_workspace_permission(current)
    else:
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
    # Empty keeps the seed's face. Filling in nuage here would repaint the bot on a plain save.
    if face and face not in FACES:
        return None, "Pick a face from the list."
    if color and color not in COLORS:
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
    ws = str(fields.get("workspace") or "").strip()
    if ws and ws != "(none)":
        env["HARNESS_WORKSPACE"] = ws
    else:
        env.pop("HARNESS_WORKSPACE", None)
    ws_perm = normalise_workspace_permission(str(fields.get("workspace_permissions") or "").strip())
    if ws_perm and ws_perm in WS_PERMISSIONS:
        env["HARNESS_WORKSPACE_PERMISSIONS"] = ws_perm
    else:
        env.pop("HARNESS_WORKSPACE_PERMISSIONS", None)
    command = str(fields.get("command") or (previous or {}).get("command") or "").strip() or default_command()
    entry = {"id": stored, "name": name, "command": command, "env": env, "key_file": key_file}
    connection = str(fields.get("connection") or "").strip()
    if connection:
        entry["connection"] = connection
    if face:
        entry["face"] = face
    if color:
        entry["color"] = color
    return entry, ""


def commit(fields: dict, existing, connections=None) -> tuple:
    """The bot list with this form saved into it. The first item is None when the form is not usable.

    A chosen connection supplies the address, model and key file. Without one, the form's own values do,
    which is how a bot saved before connections existed keeps its model.
    """
    fields = dict(fields)
    connection = str(fields.get("connection") or "").strip()
    if connection:
        row = next((item for item in public_connections(connections) if item["id"] == connection), None)
        if row is None:
            return None, "Pick a connection."
        fields["base_url"] = row["base_url"]
        fields["model"] = row["model"]
        fields["key_file"] = row["key_file"]
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


def blank_connection() -> dict:
    """What New connection shows. The address is the usual local llama.cpp server."""
    return {"id": "", "stored_id": "", "name": "", "base_url": DEFAULT_BASE, "model": DEFAULT_MODEL,
            "key_file": DEFAULT_KEY}


def public_connections(existing) -> list:
    """Connections the pages can show. A row without an id or a name is skipped."""
    rows = []
    for row in existing if isinstance(existing, list) else []:
        if not isinstance(row, dict):
            continue
        ident, name = str(row.get("id") or "").strip(), str(row.get("name") or "").strip()
        if not ident or not name:
            continue
        rows.append({"id": ident, "name": name, "base_url": str(row.get("base_url") or ""),
                     "model": str(row.get("model") or ""), "key_file": str(row.get("key_file") or ""),
                     "on": row.get("enabled") is not False})
    return rows


def first_connection(existing) -> str:
    rows = public_connections(existing)
    return rows[0]["id"] if rows else ""


def fields_of_connection(row: dict) -> dict:
    return {"id": row.get("id") or "", "stored_id": row.get("id") or "", "name": row.get("name") or "",
            "base_url": row.get("base_url") or DEFAULT_BASE, "model": row.get("model") or DEFAULT_MODEL,
            "key_file": row.get("key_file") or DEFAULT_KEY}


def cycle_connection(current: str, existing) -> str:
    """The next connection, or none, and back around."""
    ids = [""] + [row["id"] for row in public_connections(existing)]
    if current not in ids:
        return ids[1] if len(ids) > 1 else ""
    return ids[(ids.index(current) + 1) % len(ids)]


def commit_connection(fields: dict, existing) -> tuple:
    """The connection list with this form saved into it."""
    name = str(fields.get("name") or "").strip()
    if not name or any(ch in name for ch in "\n\r"):
        return None, "A connection needs a name."
    base = str(fields.get("base_url") or "").strip()
    if not base.startswith(("http://", "https://")):
        return None, "The model address has to start with http:// or https://."
    model = str(fields.get("model") or "").strip()
    if not model:
        return None, "A connection needs a model name."
    key_file = str(fields.get("key_file") or "").strip()
    if not key_file:
        return None, "A connection needs a key file. The file holds the key; this form only keeps the path."
    rows = public_connections(existing)
    stored = str(fields.get("stored_id") or "").strip()
    taken = {row["id"] for row in rows if row["id"] != stored}
    if not stored:
        stored = _unique(name, taken)
    elif stored in taken:
        return None, "Another connection already uses that id."
    kept = next((row for row in rows if row["id"] == stored), None)
    entry = {"id": stored, "name": name, "base_url": base, "model": model, "key_file": key_file}
    # A new connection starts on. Saving the form does not turn an existing one back on.
    if kept is not None and not kept["on"]:
        entry["enabled"] = False
    out, replaced = [], False
    for row in rows:
        if row["id"] == stored:
            out.append(entry)
            replaced = True
        else:
            out.append(_stored_connection(row))
    if not replaced:
        out.append(entry)
    return out, ""


def _stored_connection(row: dict) -> dict:
    """The connection as widget.json keeps it. Off is stored; on is the absence of that flag."""
    entry = {"id": row["id"], "name": row["name"], "base_url": row.get("base_url") or "",
             "model": row.get("model") or "", "key_file": row.get("key_file") or ""}
    if row.get("on") is False or row.get("enabled") is False:
        entry["enabled"] = False
    return entry


def set_connection_on(existing, conn_id: str, on: bool):
    """The connection list with this one on or off. None when that id is not there."""
    rows = public_connections(existing)
    if not any(row["id"] == conn_id for row in rows):
        return None
    out = []
    for row in rows:
        entry = _stored_connection(row)
        if row["id"] == conn_id:
            if on:
                entry.pop("enabled", None)
            else:
                entry["enabled"] = False
        out.append(entry)
    return out


def connection_in_use(bots, conn_id: str) -> bool:
    rows = bots if isinstance(bots, list) else []
    return any(isinstance(row, dict) and str(row.get("connection") or "") == conn_id for row in rows)


def drop_connection(existing, conn_id: str, bots) -> tuple:
    """The list without this connection, or an error when a bot still names it."""
    if connection_in_use(bots, conn_id):
        return None, "A bot still uses this connection."
    return [_stored_connection(row) for row in public_connections(existing) if row["id"] != conn_id], ""


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
        # Validate workspace_permissions if present.
        ws_perm = (env or {}).get("HARNESS_WORKSPACE_PERMISSIONS")
        if ws_perm and normalise_workspace_permission(ws_perm) not in WS_PERMISSIONS:
            return f"Bot {index} has an invalid workspace_permissions value."
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
    error = _check_connections(data.get("connections"))
    if error:
        return None, error
    return data, ""


def _check_connections(rows) -> str:
    if rows is None:
        return ""
    if not isinstance(rows, list):
        return "connections has to be a list."
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            return f"Connection {index} has to be an object."
        if not str(row.get("name") or "").strip() or not str(row.get("id") or "").strip():
            return f"Connection {index} needs a name and an id."
        if str(row["id"]) in seen:
            return f"Connection {index} uses an id another connection already has."
        seen.add(str(row["id"]))
    return ""
