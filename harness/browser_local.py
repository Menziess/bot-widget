"""Read a page from a file, or from the Chrome the user already has open.

Live control talks to 127.0.0.1:9222 after the user has turned on remote
debugging in chrome://inspect and answered Allow once. This module never
starts Chrome and never passes --remote-debugging-port. No extension, no
second profile, no browser-use, no Playwright.
"""

import base64
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

_SECRET = re.compile(
    r"(?i)(bearer\s+)\S+"
    r"|(\"(?:access_token|refresh_token|id_token|token|api_key|authorization)\"\s*:\s*\")[^\"]*"
)


def redact(text: str) -> str:
    """Hide bearer strings and token fields. The logged-in cookie stays in the page."""
    return _SECRET.sub(lambda match: (match.group(1) or match.group(2)) + "[redacted]", text)


def fixture_title(path: str) -> str:
    """The <title> of a local HTML file. Empty when the file has none."""
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    found = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return found.group(1).strip() if found else ""


def read_page(path: str) -> dict:
    return {"url": os.path.abspath(path), "title": fixture_title(path), "transport": "fixture"}


class Cdp:
    """DevTools calls. *call* is ``(method, params, session_id) -> result``."""

    def __init__(self, call, session_id: str | None = None):
        self._call = call
        self.session_id = session_id

    def call(self, method: str, params: dict | None = None):
        return self._call(method, params or {}, self.session_id)

    def list_tabs(self) -> list:
        info = self.call("Target.getTargets")
        return [
            {"id": target["targetId"], "title": target.get("title") or "", "url": target.get("url") or ""}
            for target in info.get("targetInfos", [])
            if target.get("type") == "page"
        ]

    def switch_tab(self, target_id: str) -> None:
        """Bring an existing tab forward. Does not open a window or a tab."""
        self.call("Target.activateTarget", {"targetId": target_id})

    def open_tab(self, url: str) -> str:
        """One new tab in the window that is already open. Never a new window."""
        created = self.call("Target.createTarget", {"url": url, "newWindow": False})
        return created.get("targetId") or ""

    def close_tab(self, target_id: str) -> None:
        """Close one tab this session opened. Other tabs stay."""
        if target_id:
            self.call("Target.closeTarget", {"targetId": target_id})

    def use_tab(self, target_id: str) -> "Cdp":
        attached = self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return Cdp(self._call, attached.get("sessionId"))

    def goto_url(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        self.wait_for_load()

    def wait_for_load(self) -> None:
        for _ in range(50):
            if self._value("document.readyState") == "complete":
                return
            time.sleep(0.1)
        raise TimeoutError("page did not finish loading")

    def read_text(self) -> str:
        return self._value("document.body ? document.body.innerText : ''") or ""

    def screenshot(self) -> str:
        """PNG of this tab. Does not activate it, so a background tab stays in the background."""
        shot = self.call("Page.captureScreenshot", {"format": "png"})
        return shot.get("data") or ""

    def click_text(self, text: str) -> bool:
        quoted = json.dumps(text)
        expression = (
            "(() => { const want = " + quoted + "; "
            "const element = [...document.querySelectorAll('a,button,input,[role=\"button\"]')]"
            ".find(node => ((node.innerText || node.value || '').trim()).includes(want)); "
            "if (!element) return false; element.click(); return true; })()"
        )
        return bool(self._value(expression))

    def page_fetch(self, url: str) -> dict:
        """fetch() inside the page, so the logged-in session is the browser's. Tokens are not returned."""
        quoted = json.dumps(url)
        expression = (
            "(async () => { const res = await fetch(" + quoted + ", {credentials: 'include'}); "
            "const body = await res.text(); return {status: res.status, body}; })()"
        )
        value = self._value(expression, await_promise=True)
        if not isinstance(value, dict):
            return {"status": 0, "body": redact(str(value or ""))}
        return {"status": value.get("status") or 0, "body": redact(str(value.get("body") or ""))}

    def _value(self, expression: str, await_promise: bool = False):
        result = self.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": await_promise,
        })
        return (result.get("result") or {}).get("value")


def devtools_version(port: int = 9222, timeout: float = 0.4) -> dict | None:
    """The browser's /json/version, or None when nothing is listening.

    Listening means the user already allowed remote debugging. This does not start Chrome.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (OSError, urllib.error.URLError, ValueError, TimeoutError):
        return None


def websocket_from_port_file(text: str) -> str:
    """The browser socket written in DevToolsActivePort. Chrome's HTTP /json/version is often closed."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].isdigit() or not lines[1].startswith("/"):
        raise ValueError("not a DevToolsActivePort file")
    return f"ws://127.0.0.1:{lines[0]}{lines[1]}"


def _port_file_url() -> str | None:
    home = os.path.expanduser("~")
    for path in (os.path.join(home, ".config/google-chrome/DevToolsActivePort"),
                 os.path.join(home, ".config/chromium/DevToolsActivePort"),
                 os.path.join(home, "Library/Application Support/Google/Chrome/DevToolsActivePort"),
                 os.path.join(home, "Library/Application Support/Chromium/DevToolsActivePort"),
                 os.path.join(os.environ.get("LOCALAPPDATA", home), "Google/Chrome/User Data/DevToolsActivePort")):
        try:
            with open(path, encoding="utf-8") as fh:
                return websocket_from_port_file(fh.read())
        except (OSError, ValueError):
            continue
    return None


def _listening_urls() -> list:
    """Where Chrome listens on this machine, from the system and not from a file in Chrome's own folder: macOS
    keeps other apps out of that folder. Chrome takes the socket without the id that the port file holds."""
    try:
        out = subprocess.run(["lsof", "-nP", "-a", "-iTCP", "-sTCP:LISTEN", "-c", "Google", "-c", "Chromium", "-c", "chrome", "-Fn"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [f"ws://127.0.0.1:{line.rsplit(':', 1)[1]}/devtools/browser"
            for line in out.splitlines() if line.startswith("n127.0.0.1:")]


def attach(port: int = 9222, port_file: str | None = None) -> Cdp:
    """The browser socket for the Chrome that is already showing the consent dialog's result.

    The port file is tried first. Chrome's built-in debugging toggle answers /json/version with 404
    and puts the real socket path in that file.
    """
    version = devtools_version(port)
    from_file = None
    if port_file:
        try:
            with open(port_file, encoding="utf-8") as fh:
                from_file = websocket_from_port_file(fh.read())
        except (OSError, ValueError):
            from_file = None
    else:
        from_file = _port_file_url()
    urls = [*_shared, from_file, *([version["webSocketDebuggerUrl"]] if version else []), *_listening_urls()]
    refused = set()  # ports where Chrome answered the connection itself: no other path there will ask less
    for url in filter(None, urls):
        port_of = (urlparse(url).hostname, urlparse(url).port)
        if port_of in refused:
            continue
        with _shared_lock:
            try:
                _shared.get(url) or _shared.setdefault(url, WebSocketCdp(url))
            except NotABrowser:
                continue  # an answer that is not Chrome's debugging socket: the next address may be
            except OSError:
                # Closed or silent after the Allow popup: it was declined, or it is still open. Asking again at
                # another address of the same Chrome would only show the popup twice.
                refused.add(port_of)
                continue
        return Cdp(_shared_call(url))
    raise ConnectionError(
        "Chrome is not listening on 127.0.0.1:%s. Turn on remote debugging in "
        "chrome://inspect and choose Allow. This does not relaunch Chrome." % port)


_shared: dict = {}
_shared_lock = threading.Lock()


class NotABrowser(ConnectionError):
    """The address answered, but not as Chrome's debugging socket (a 403, a 404)."""


def _shared_call(url: str):
    """One socket for the life of the process: Chrome asks the user to Allow for every new connection."""
    def call(method, params=None, session_id=None):
        with _shared_lock:
            known = _shared.get(url)
            fresh = known is None
            try:
                if fresh:
                    known = _shared[url] = WebSocketCdp(url)
                return known.call(method, params, session_id)
            except TimeoutError:
                raise  # a slow answer is not a dead socket: a new one means a new Allow popup
            except OSError:
                _shared.pop(url, None)
                if fresh:
                    raise
                known = _shared[url] = WebSocketCdp(url)  # the old socket had died
                return known.call(method, params, session_id)
    return call


CONSENT_WAIT_S = 120


class WebSocketCdp:
    """A small DevTools websocket. One text frame per call."""

    def __init__(self, url: str, timeout: float = 5):
        parsed = urlparse(url)
        # Chrome holds the handshake until the user has answered its Allow popup.
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), max(timeout, CONSENT_WAIT_S))
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = parsed.hostname if not parsed.port else f"{parsed.hostname}:{parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            raw += chunk
        head, self._pending = raw.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise NotABrowser(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.sock.settimeout(timeout)
        self._id = 0

    def call(self, method: str, params: dict | None = None, session_id: str | None = None):
        self._id += 1
        payload = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self._send(json.dumps(payload).encode())
        while True:
            message = json.loads(self._recv())
            if message.get("id") != self._id:
                continue
            if "error" in message:
                raise RuntimeError(str((message["error"] or {}).get("message") or "cdp error"))
            return message.get("result") or {}

    def _send(self, data: bytes) -> None:
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack("!H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack("!Q", length)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + masked)

    def _read(self, count: int) -> bytes:
        while len(self._pending) < count:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("socket closed")
            self._pending += chunk
        data, self._pending = self._pending[:count], self._pending[count:]
        return data

    def _recv(self) -> bytes:
        while True:
            header = self._read(2)
            opcode = header[0] & 0x0F
            length = header[1] & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if header[1] & 0x80:
                mask = self._read(4)
                data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(self._read(length)))
            else:
                data = self._read(length)
            if opcode == 0x8:
                raise ConnectionError("websocket closed")
            if opcode == 0x1:
                return data
