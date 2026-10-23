"""The local OpenBot: HTTP API, store (sqlite) and gbot."""

import json
import os
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from typing import NamedTuple

from botwidget.config import DB_FILE, HEADERS_FILE, OPENBOT_DIR, api_url, read_file

# Why a message could not even be tried: OpenBot has not switched its local API on.
AUTOMATION_OFF = "automation off"
# A UTF-8 byte-order mark is not content; a body of only that is empty.
BOM = b"\xef\xbb\xbf"
# A bot answers 403 until its own setting "Local scripts" is on; new bots start with it off.
LOCAL_SCRIPTS_HINT = 'In OpenBot open this bot\'s settings and turn on "Local scripts"'
ERROR_DETAIL_CHARS = 200


class ApiResult(NamedTuple):
    """Outcome of a POST: data on success, otherwise the HTTP status (None = no answer).

    retry says whether the same message may be tried again; None means the status decides.
    """
    data: dict | None
    status: int | None
    error: str
    retry: bool | None = None

    @property
    def ok(self) -> bool:
        return self.data is not None

    @property
    def retryable(self) -> bool:
        """A dropped link, a timeout, a server error or an unreadable answer can heal;
        a refusal will not."""
        if self.retry is not None:
            return self.retry
        return self.status is None or self.status >= 500 or self.status in (408, 429)


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
    url = f"{api_url()}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def _error_detail(err: urllib.error.HTTPError) -> str:
    """What OpenBot said about a refusal, when it said it in JSON as {"error": "..."}."""
    try:
        answer = json.loads(err.read().decode())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ""
    detail = answer.get("error") if isinstance(answer, dict) else None
    return detail.strip().rstrip(".")[:ERROR_DETAIL_CHARS] if isinstance(detail, str) else ""


def api_post(path: str, body: dict) -> ApiResult:
    """POST JSON to the local API and say why it failed, not only that it did."""
    token = read_auth_token()
    url = f"{api_url()}{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body, status = resp.read(), resp.status
    except urllib.error.HTTPError as err:
        detail = _error_detail(err)
        err.close()
        if err.code == 403:
            detail = f"{detail or 'this bot does not allow local scripts'}. {LOCAL_SCRIPTS_HINT}"
        return ApiResult(None, err.code, detail or f"HTTP {err.code}")
    except (urllib.error.URLError, OSError) as err:
        return ApiResult(None, None, str(err))
    stripped = body.strip()
    while stripped.startswith(BOM):
        stripped = stripped[len(BOM):].strip()
    if not stripped:
        # Nothing but whitespace and byte-order marks will not turn into JSON, however many marks
        # the store puts in front; trying again only repeats it.
        return ApiResult(None, status, "empty answer", retry=False)
    try:
        answer = json.loads(stripped.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Not JSON at all: the connection worked, so this is a blip, not a refusal.
        return ApiResult(None, status, "unreadable answer", retry=True)
    if not isinstance(answer, dict):
        # A body that parses but is not the object we asked for will not get better.
        return ApiResult(None, status, "unexpected answer", retry=False)
    return ApiResult(answer, status, "")


GBOT = shutil.which("gbot") or os.path.expanduser("~/.local/bin/gbot")


def openbot_installed() -> bool:
    """OpenBot leaves its folder behind once it has been started once."""
    return os.path.isdir(OPENBOT_DIR)


def gbot_installed() -> bool:
    return os.path.exists(GBOT)


def grok_bot_status(timeout: float = 10.0) -> dict:
    """Ask gbot about the bots of Grok Bot.

    Without a login gbot exits 75 with a reason on stderr; that comes back as a
    note, so the menu can say why there is no route.
    """
    if not os.path.exists(GBOT):
        return {"connected": False, "bots": [], "note": "gbot not found"}
    try:
        done = subprocess.run([GBOT, "bots", "list", "--json"], capture_output=True,
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
    """All bots with name and status from the local OpenBot store."""
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
    except (ValueError, TypeError):
        return ""
    if msg.get("source") == "routine":
        return ""
    text = msg.get("text")
    if not isinstance(text, str):
        return ""
    return text.strip()


# The bubble scrolls, so this only guards against a runaway message; a cut shows as an ellipsis.
MESSAGE_CHARS = 4000
ACTIVITY_MAX_CHARS = 4000


def _clip(text: str) -> str:
    return text if len(text) <= MESSAGE_CHARS else text[:MESSAGE_CHARS].rstrip() + "…"


def latest_chat(thread_id: str, limit: int = 20) -> dict:
    """Latest chat lines plus one busy line.

    The final answer is only in the store when the turn is done. In between, loose
    commentary lines come in; the newest of those is the sign that the turn is
    still running.
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
            messages.append({"role": "bot", "text": _clip(text)})
        elif author == "user":
            messages.append({"role": "user", "text": _clip(text)})
    messages.reverse()
    activity = ""
    if live:
        line = _chat_text(live[0]).strip()[:ACTIVITY_MAX_CHARS]
        if line and ("bearer " in line.lower() or "authorization" in line.lower()):
            line = "working…"
        activity = line
    return {"messages": messages, "activity": activity}
