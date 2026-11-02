"""A stand-in for the Anthropic Messages API: real SSE shape, cache accounting, no network beyond localhost.

It models one thing a real provider does: a prefix it has already seen is reported as a cache read,
so a test can prove the adapter marks a stable prefix and that later turns are mostly cached.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAnthropic:
    def __init__(self, replies: list | None = None):
        self.replies = list(replies or [{"text": "Hallo."}])
        self.requests: list[dict] = []
        self.seen_prefixes: list[str] = []
        self._lock = threading.RLock()  # usage() takes it while do_POST holds it
        model = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with model._lock:
                    model.requests.append(body)
                    reply = model.replies.pop(0) if len(model.replies) > 1 else model.replies[0]
                    usage = model.usage(body)
                if body.get("stream"):
                    self._stream(reply, usage)
                else:
                    self._once(reply, usage)

            def _once(self, reply, usage):
                payload = json.dumps({"id": "msg_x", "type": "message", "role": "assistant",
                                      "content": [{"type": "text", "text": reply["text"]}],
                                      "usage": {**usage, "output_tokens": 5}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _stream(self, reply, usage):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()

                def event(kind: str, data: dict) -> None:
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
                    self.wfile.flush()

                event("message_start", {"type": "message_start",
                                        "message": {"id": "msg_x", "usage": usage}})
                event("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": {"type": "text", "text": ""}})
                for word in [w for w in reply["text"].split(" ") if w]:
                    event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                  "delta": {"type": "text_delta", "text": word + " "}})
                event("content_block_stop", {"type": "content_block_stop", "index": 0})
                if reply.get("tool"):
                    event("content_block_start", {"type": "content_block_start", "index": 1,
                                                  "content_block": {"type": "tool_use", "id": "toolu_1",
                                                                    "name": reply["tool"]["name"], "input": {}}})
                    event("content_block_delta", {"type": "content_block_delta", "index": 1,
                                                  "delta": {"type": "input_json_delta",
                                                            "partial_json": json.dumps(reply["tool"]["input"])}})
                event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                                        "usage": {"output_tokens": 7}})
                event("message_stop", {"type": "message_stop"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def usage(self, body: dict) -> dict:
        """A prefix the provider has already seen is a cache read; the rest is fresh input."""
        stable = "".join(block["text"] for block in body.get("system") or []) + "\n"
        turns = body.get("messages") or []
        stable += "\n".join(json.dumps(turn, sort_keys=True) for turn in turns[:-1])
        fresh = json.dumps(turns[-1:], sort_keys=True)
        cached = 0
        with self._lock:
            # A real provider matches the longest prefix it has already cached, not the whole body.
            cached_chars = max((len(seen) for seen in self.seen_prefixes if stable.startswith(seen)), default=0)
            cached = cached_chars // 4
            self.seen_prefixes.append(stable)
        return {"input_tokens": max(1, len(fresh) // 4), "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": 0, "output_tokens": 7}

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
