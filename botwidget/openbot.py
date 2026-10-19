"""De lokale OpenBot: HTTP-API, store (sqlite) en gbot."""

import json
import os
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request

from botwidget.config import API_URL, DB_FILE, HEADERS_FILE, OPENBOT_DIR, read_file


def read_auth_token() -> str:
    """Read Bearer token from the headers file; empty when OpenBot is not installed."""
    line = read_file(HEADERS_FILE).split("\n", 1)[0].strip()
    # The file may contain "Authorization: Bearer <token>" or just the token
    if line.startswith("Authorization:"):
        return line.split("Bearer", 1)[1].strip()
    return line


def api_get(path: str) -> dict | list | None:
    """GET a JSON response from the local API."""
    token = read_auth_token()
    url = f"{API_URL}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def api_post(path: str, body: dict) -> dict | None:
    """POST JSON to the local API."""
    token = read_auth_token()
    url = f"{API_URL}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


GBOT = shutil.which("gbot") or os.path.expanduser("~/.local/bin/gbot")


def openbot_installed() -> bool:
    """OpenBot laat zijn map achter zodra het één keer gestart is."""
    return os.path.isdir(OPENBOT_DIR)


def gbot_installed() -> bool:
    return os.path.exists(GBOT)


def grok_bot_status(timeout: float = 10.0) -> dict:
    """Vraag gbot naar de bots van Grok Bot.

    Zonder aanmelding geeft gbot exit 75 en een reden op stderr; die komt als
    note terug, zodat het menu kan zeggen waarom er geen route is.
    """
    if not os.path.exists(GBOT):
        return {"connected": False, "bots": [], "note": "gbot not found"}
    try:
        done = subprocess.run([GBOT, "--json", "bots", "list"], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"connected": False, "bots": [], "note": "gbot gave no answer"}
    except OSError as err:
        return {"connected": False, "bots": [], "note": str(err)}
    for line in (done.stdout or "").splitlines():
        line = line.strip()
        if line[:1] in "{[":
            try:
                data = json.loads(line)
            except ValueError:
                continue
            bots = data.get("bots", data) if isinstance(data, dict) else data
            return {"connected": True, "bots": bots if isinstance(bots, list) else [],
                    "note": ""}
    note = next((line for line in (done.stderr or done.stdout or "").splitlines()
                 if line.strip()), "no answer")
    return {"connected": False, "bots": [], "note": note.strip()[:200]}


def list_bots() -> list[dict]:
    """Alle bots met naam en status uit de lokale OpenBot-store."""
    query = """
        SELECT a.agent_json, t.status
        FROM projection_agents a
        LEFT JOIN projection_turns t ON t.rowid = (
            SELECT max(rowid) FROM projection_turns WHERE thread_id = a.thread_id
        )
        ORDER BY a.sort_order, a.agent_id
    """
    try:
        con = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(query).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    bots = []
    for agent_json, turn_status in rows:
        try:
            agent = json.loads(agent_json)
        except ValueError:
            continue
        agent_id = agent.get("id")
        if not agent_id:
            continue
        bots.append({
            "id": agent_id,
            "name": agent.get("name") or agent_id,
            "threadId": agent.get("threadId") or ("openbot-thread-" + agent_id),
            "status": "working" if turn_status == "running" else "ready",
            "hue": agent.get("avatarHue"),
            "seed": agent.get("avatarSeed") or agent_id,
        })
    return bots


def _chat_text(raw: str) -> str:
    try:
        msg = json.loads(raw)
    except ValueError:
        return ""
    if msg.get("source") == "routine":
        return ""
    text = msg.get("text")
    if not isinstance(text, str):
        return ""
    return text.strip()


def latest_chat(thread_id: str, limit: int = 8) -> dict:
    """Laatste chatregels plus één bezig-regel.

    Het eindantwoord staat pas in de store als de beurt klaar is. Tussendoor
    komen losse commentary-regels binnen; de nieuwste daarvan is het teken
    dat de beurt nog loopt.
    """
    empty = {"messages": [], "activity": ""}
    try:
        con = sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return empty
    try:
        rows = con.execute(
            """
            SELECT author, item_type, message_json
            FROM projection_thread_messages
            WHERE thread_id = ? AND IFNULL(item_type, '') != 'commentary'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (thread_id, limit),
        ).fetchall()
        live = con.execute(
            """
            SELECT c.message_json
            FROM projection_thread_messages c
            WHERE c.thread_id = ? AND c.item_type = 'commentary'
              AND c.created_at > COALESCE((
                SELECT max(created_at) FROM projection_thread_messages
                WHERE thread_id = ? AND item_type = 'final_answer'
              ), '')
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            (thread_id, thread_id),
        ).fetchone()
    except sqlite3.Error:
        return empty
    finally:
        con.close()
    messages = []
    for author, item_type, raw in rows:
        text = _chat_text(raw)
        if not text:
            continue
        if item_type == "final_answer":
            messages.append({"role": "bot", "text": text[:500]})
        elif author == "user":
            messages.append({"role": "user", "text": text[:500]})
    messages.reverse()
    activity = ""
    if live:
        line = _chat_text(live[0]).split("\n", 1)[0][:200]
        if line and ("bearer " in line.lower() or "authorization" in line.lower()):
            line = "working…"
        activity = line
    return {"messages": messages, "activity": activity}
