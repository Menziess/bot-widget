"""A stand-in for any OpenAI-compatible server: streams words, reports usage, records requests.

No model, no network beyond localhost, and the same shape a local server and a hosted provider
answer in, so the adapter is tested once for both.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeModel:
    """One server on a free port; `reply` is what the model says, in words."""

    def __init__(self, reply: str = "Hello from the fake model.", slow_complete: float = 0.0,
                 first_delay: float = 0.0, script: list | None = None, status: int = 200,
                 context_size: int = 0):
        self.reply = reply
        self.slow_complete = slow_complete  # a summary call, when it must not block a turn
        self.first_delay = first_delay  # a model that thinks before its first token
        # A scripted answer per request: a string, or {"tool_calls": [...]} to ask for a tool first.
        self.script = list(script or [])
        self.model = "fake-model"
        self.status = status  # a server that answers, but not with an answer: a 401, say
        self.context_size = context_size  # what /props reports, like llama.cpp does
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.get_headers: list[dict] = []
        self.require_auth = False
        self._lock = threading.Lock()
        model = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_GET(self):
                with model._lock:
                    model.get_headers.append(dict(self.headers))
                if model.require_auth and not (self.headers.get("Authorization") or "").startswith("Bearer "):
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path.endswith("/props") and model.context_size:
                    payload = json.dumps({"default_generation_settings": {"n_ctx": model.context_size}}).encode()
                elif self.path.endswith("/models"):
                    payload = json.dumps({"data": [{"id": model.model}]}).encode()
                else:
                    payload = b"{}"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with model._lock:
                    model.requests.append(body)
                    model.headers.append(dict(self.headers))
                if model.status != 200:
                    payload = json.dumps({"error": {"message": "invalid api key"}}).encode()
                    self.send_response(model.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if body.get("stream"):
                    self._stream(body)
                else:
                    time.sleep(model.slow_complete)
                    self._once(body)

            def _once(self, body):
                payload = json.dumps({"id": "x", "object": "chat.completion",
                                      "choices": [{"index": 0, "message": {"role": "assistant",
                                                                          "content": model.reply},
                                                   "finish_reason": "stop"}],
                                      "usage": model.usage(body)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _stream(self, body):
                time.sleep(model.first_delay)
                with model._lock:
                    reply = model.script.pop(0) if model.script else model.reply
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                if isinstance(reply, dict):
                    for index, call in enumerate(reply["tool_calls"]):
                        part = {"index": index, "id": f"call-{index}", "type": "function",
                                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])}}
                        self.wfile.write(f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'tool_calls': [part]}}]})}\n\n".encode())
                    done = {"choices": [], "usage": model.usage(body)}
                    self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                    return
                for word in reply.split(" "):
                    chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.01)
                done = {"choices": [], "usage": model.usage(body)}
                self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @staticmethod
    def usage(body) -> dict:
        size = sum(len(message["content"]) for message in body.get("messages", []))
        return {"prompt_tokens": max(1, size // 4), "completion_tokens": 5,
                "total_tokens": max(1, size // 4) + 5}

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
