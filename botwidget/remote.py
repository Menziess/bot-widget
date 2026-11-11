"""Talk to the running widget's bots from a shell: `botwidget bots | read BOT | ask BOT TEXT | approve|decline BOT ID --as NAME`.

The widget serves a few calls on localhost; the commands here are the client. The port and a token
are in a file only the owner can read, so another user on the machine cannot talk to your bots.
"""

import json
import os
import secrets
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INFO = os.path.join(tempfile.gettempdir(), "bot_widget_remote.json")
ASK_WAIT_S = 300


def serve(faces) -> ThreadingHTTPServer:
    """Answer the CLI from the widget's live links, on a thread of their own."""
    token = secrets.token_hex(16)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _reply(self, code: int, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, bot: str, text, decision: dict | None = None):
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._reply(403, {"error": "bad token"})
            if bot == "":
                return self._reply(200, {"bots": list(faces.faces)})
            face = faces.faces.get(bot)
            if face is None or face.link is None:
                return self._reply(404, {"error": f"no running bot {bot!r}", "bots": list(faces.faces)})
            if decision is not None:
                done = face.link.decide(decision["id"], decision["accept"], "cli", decision["by"])
                return self._reply(200 if done else 404, {"ok": done, "error": "" if done else "no such question waits"})
            if text is None:
                chat = face.link.chat()
                return self._reply(200, {**chat, "active": face.link.active(), "note": face.link.note()})
            ok, error = face.link.send(text)
            self._reply(200 if ok else 409, {"ok": ok, "error": error})

        def do_GET(self):
            self._handle(self.path.removeprefix("/").strip(), None)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            decision = ({"id": str(body["id"]), "accept": bool(body["accept"]), "by": str(body["by"])}
                        if "accept" in body else None)
            self._handle(str(body.get("bot") or ""), str(body.get("text") or ""), decision)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fd = os.open(INFO, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"port": server.server_address[1], "token": token}, fh)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _call(path: str, body: dict | None = None) -> dict:
    try:
        with open(INFO) as fh:
            info = json.load(fh)
        request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/{path}",
                                         data=None if body is None else json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {info['token']}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        return json.load(error)
    except (OSError, ValueError):
        sys.exit('The widget is not running, or remote control is off: set "remote_control": true in widget.json and restart it.')


def main(args: list) -> None:
    """bots | read BOT | ask BOT TEXT: the answer of `ask` is printed once the bot is done."""
    command, rest = (args or ["bots"])[0], (args or ["bots"])[1:]
    if command == "bots":
        print("\n".join(_call("")["bots"]))
    elif command == "read" and len(rest) == 1:
        print(json.dumps(_call(rest[0]), indent=2, ensure_ascii=False))
    elif command == "ask" and len(rest) == 2:
        bot, text = rest
        before = len(_call(bot).get("messages", []))
        sent = _call("send", {"bot": bot, "text": text})
        if not sent.get("ok"):
            sys.exit(sent.get("error") or "not sent")
        deadline = time.monotonic() + ASK_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(1)
            chat = _call(bot)
            if chat["approvals"] or not chat["active"]:
                break
        for message in chat["messages"][before + 1:]:
            print(message["text"])
        for approval in chat["approvals"]:
            print(f"[waiting for approval: {approval['reason']} -- botwidget approve|decline {bot} {approval['requestId']} --as NAME]")
        if chat.get("failed") or chat.get("note"):
            print(f"[{chat.get('failed') or chat['note']}]", file=sys.stderr)
    elif command in ("approve", "decline") and len(rest) == 4 and rest[2] == "--as":
        bot, request_id, _, by = rest
        done = _call("decide", {"bot": bot, "id": request_id, "accept": command == "approve", "by": by})
        print("ok" if done.get("ok") else done.get("error", "failed"))
    else:
        sys.exit("usage: botwidget bots | read BOT | ask BOT TEXT | approve|decline BOT REQUEST_ID --as NAME")
