"""A model through the Chat Completions shape, streaming: the one adapter every provider and every
local server speaks, from Ollama and LM Studio to DeepSeek and OpenAI.

Only the standard library is used, so the agent starts with nothing but python and its own code.
"""

import json
import urllib.error
import urllib.request


class ModelError(Exception):
    """The provider said no, or answered with something that is not a stream."""


class ChatCompletions:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, messages: list[dict], stream: bool, tools: list[dict] | None = None):
        payload = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream_options"] = {"include_usage": True}
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return urllib.request.Request(f"{self.base_url}/chat/completions", data=body, headers=headers)

    def stream(self, messages: list[dict], tools: list[dict] | None = None, stop=None, opened=None):
        """Yield events: ("text", str), ("thought", str), ("usage", dict) and ("tool_calls", list).

        A tool call streams in pieces too, so the pieces are joined by index and handed over once,
        when the model has finished the step.

        stop is a threading.Event: once set, the stream ends at the next chunk, so a turn that was
        cancelled stops paying for the rest of the answer. opened receives the response, so the
        caller can close the socket from another thread.
        """
        request = self._request(messages, stream=True, tools=tools)
        calls: dict[int, dict] = {}
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                if opened is not None:
                    opened(reply)
                for raw in reply:
                    if stop is not None and stop.is_set():
                        break
                    line = raw.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if usage := chunk.get("usage"):
                        yield "usage", usage
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content"):
                            yield "thought", delta["reasoning_content"]
                        if delta.get("content"):
                            yield "text", delta["content"]
                        for part in delta.get("tool_calls") or []:
                            slot = calls.setdefault(part.get("index", 0),
                                                    {"id": "", "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                            if part.get("id"):
                                slot["id"] = part["id"]
                            function = part.get("function") or {}
                            slot["function"]["name"] += function.get("name") or ""
                            slot["function"]["arguments"] += function.get("arguments") or ""
                if calls:
                    yield "tool_calls", [calls[index] for index in sorted(calls)]
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise ModelError(f"HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ModelError(f"cannot reach {self.base_url}: {error.reason}") from error

    def complete(self, messages: list[dict]) -> str:
        """The whole answer at once; for a background summary, where streaming buys nothing."""
        request = self._request(messages, stream=False)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                body = json.loads(reply.read())
        except urllib.error.HTTPError as error:
            raise ModelError(f"HTTP {error.code}: {error.read().decode(errors='replace')[:300]}") from error
        except urllib.error.URLError as error:
            raise ModelError(f"cannot reach {self.base_url}: {error.reason}") from error
        choices = body.get("choices") or []
        return (choices[0].get("message") or {}).get("content", "") if choices else ""


def from_environment(env=None) -> ChatCompletions:
    """The model this bot uses: any OpenAI-compatible base URL, local or hosted."""
    import os
    env = env or os.environ
    base = env.get("HARNESS_MODEL_BASE_URL") or "http://127.0.0.1:11434/v1"
    return ChatCompletions(base, env.get("HARNESS_MODEL") or "qwen2.5:7b",
                           env.get("HARNESS_MODEL_API_KEY") or "")
