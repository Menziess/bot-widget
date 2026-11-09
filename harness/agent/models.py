"""A model through the Chat Completions shape, streaming: the one adapter every provider and every
local server speaks, from Ollama and LM Studio to DeepSeek and OpenAI.

Only the standard library is used, so the agent starts with nothing but python and its own code.
"""

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


class ModelError(Exception):
    """The provider said no, or answered with something that is not a stream."""


class ChatCompletions:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.context_size = 0

    def _request(self, messages: list[dict], stream: bool, tools: list[dict] | None = None):
        payload = {"model": self.model, "messages": messages, "stream": stream}
        if tools:
            payload["tools"] = tools
        if stream:
            payload["stream_options"] = {"include_usage": True}
        body = json.dumps(payload).encode()
        return urllib.request.Request(f"{self.base_url}/chat/completions", data=body,
                                      headers=self._headers({"Content-Type": "application/json"}))

    def _headers(self, headers: dict | None = None) -> dict:
        """llama.cpp (--api-key) answers 401 on /models and /props without the Bearer key, and the
        meter then falls back to a made-up window."""
        headers = dict(headers or {})
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def ready(self, timeout: float = 3.0, wait: float = 30.0) -> None:
        """Answer now whether anything is at the base URL, so a missing server is a sentence instead
        of a three-minute hang. Any answer at all counts: a bad key is the turn's error, not this one.
        Then ask the server how large its context is, if it tells (llama.cpp does).

        Connection refused fails at once. A port that accepts and then stays quiet is a model still
        loading behind the proxy, so try again until wait seconds.
        """
        deadline = time.monotonic() + max(wait, timeout)
        while True:
            slice_s = deadline - time.monotonic()
            if slice_s <= 0:
                self._missing(TimeoutError("timed out"))
            try:
                self._probe(min(timeout, slice_s))
                return
            except (urllib.error.URLError, OSError) as error:
                reason = getattr(error, "reason", error)
                if not isinstance(reason, TimeoutError) or time.monotonic() >= deadline:
                    self._missing(reason, error)
                self._refused(timeout, error)

    def _refused(self, timeout: float, error: BaseException) -> None:
        """A quiet port may be a model still loading, or on Windows a closed one: a refusal there takes about two
        seconds, longer than the probe waits. Only a refusal says nothing is listening."""
        parts = urllib.parse.urlsplit(self.base_url)
        try:
            socket.create_connection((parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)),
                                     timeout=max(timeout, 4.0)).close()
        except ConnectionRefusedError as refused:
            self._missing(refused, error)
        except OSError:
            pass

    def _missing(self, reason, error: BaseException | None = None) -> None:
        # strerror is "Connection refused". str(reason) is the long "[Errno 111] ..." line.
        detail = "Connection refused" if isinstance(reason, ConnectionRefusedError) else (
            getattr(reason, "strerror", None) or reason)
        raise ModelError(f"no model server at {self.base_url} ({detail}). Start it, or change "
                         f"the address in Connections.") from error

    def _probe(self, timeout: float) -> None:
        request = urllib.request.Request(f"{self.base_url}/models", headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                reply.read(1)
        except urllib.error.HTTPError:
            return self._read_props(timeout)
        self._read_props(timeout)

    def _read_props(self, timeout: float) -> None:
        """The model's own window, so the context meter is not a made-up 32000."""
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{root}/props", headers=self._headers()),
                                         timeout=timeout) as reply:
                props = json.loads(reply.read())
        except Exception:
            return  # not a llama.cpp server, or an old one: the guess stays
        settings = props.get("default_generation_settings") or {}
        self.context_size = int(settings.get("n_ctx") or props.get("n_ctx") or 0)

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


def _anthropic_content(message: dict) -> list[dict]:
    """One stored message in the shape the Anthropic API reads, tool calls and results included."""
    role, content = message["role"], message.get("content") or ""
    if role == "tool":
        return [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": content}]
    blocks: list[dict] = [{"type": "text", "text": content}] if content else []
    for call in message.get("tool_calls") or []:
        try:
            arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        blocks.append({"type": "tool_use", "id": call["id"],
                       "name": (call.get("function") or {}).get("name", ""), "input": arguments})
    return blocks


class AnthropicMessages:
    """The Anthropic Messages API, with a cache mark on the stable prefix and on the newest turn.

    Anthropic caches only what a request marks, and it charges a quarter for a cached read, so the
    system block (which never changes) and the last message (which makes the whole history a
    cacheable prefix next time) carry the mark.
    """

    version = "2023-06-01"

    def __init__(self, model: str, api_key: str, base_url: str = "https://api.anthropic.com",
                 timeout: float = 300, max_tokens: int = 4096):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.context_size = 0  # filled from the server's /props, when it has one

    def _body(self, messages: list[dict], stream: bool, tools: list[dict] | None) -> dict:
        system, conversation = [], []
        for message in messages:
            if message["role"] == "system":
                system.append({"type": "text", "text": message["content"],
                               "cache_control": {"type": "ephemeral"}})
                continue
            blocks = _anthropic_content(message)
            role = "assistant" if message["role"] == "assistant" else "user"
            if conversation and conversation[-1]["role"] == role:
                conversation[-1]["content"].extend(blocks)
            else:
                conversation.append({"role": role, "content": blocks})
        if conversation:
            conversation[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        body = {"model": self.model, "max_tokens": self.max_tokens, "system": system,
                "messages": conversation, "stream": stream}
        if tools:
            body["tools"] = [{"name": tool["function"]["name"],
                              "description": tool["function"]["description"],
                              "input_schema": tool["function"]["parameters"]} for tool in tools]
        return body

    def _request(self, body: dict) -> urllib.request.Request:
        headers = {"Content-Type": "application/json", "anthropic-version": self.version}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return urllib.request.Request(f"{self.base_url}/v1/messages", data=json.dumps(body).encode(),
                                      headers=headers)

    @staticmethod
    def _usage(source: dict) -> dict:
        """The same numbers every adapter reports, so the usage log reads the same for both."""
        return {"prompt_tokens": (source.get("input_tokens") or 0) + (source.get("cache_read_input_tokens") or 0)
                                + (source.get("cache_creation_input_tokens") or 0),
                "completion_tokens": source.get("output_tokens") or 0,
                "prompt_tokens_details": {"cached_tokens": source.get("cache_read_input_tokens") or 0}}

    def stream(self, messages: list[dict], tools: list[dict] | None = None, stop=None, opened=None):
        """The same events as the Chat Completions adapter, from Anthropic's SSE shape."""
        request = self._request(self._body(messages, True, tools))
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
                    event = json.loads(line[5:].strip())
                    kind = event.get("type")
                    if kind == "message_start":
                        yield "usage", self._usage((event.get("message") or {}).get("usage") or {})
                    elif kind == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            calls[event.get("index", 0)] = {"id": block.get("id", ""), "type": "function",
                                                            "function": {"name": block.get("name", ""),
                                                                         "arguments": ""}}
                    elif kind == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            yield "text", delta.get("text", "")
                        elif delta.get("type") == "thinking_delta":
                            yield "thought", delta.get("thinking", "")
                        elif delta.get("type") == "input_json_delta":
                            slot = calls.setdefault(event.get("index", 0),
                                                    {"id": "", "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                            slot["function"]["arguments"] += delta.get("partial_json") or ""
                    elif kind == "message_delta":
                        yield "usage", self._usage(event.get("usage") or {})
                if calls:
                    yield "tool_calls", [calls[index] for index in sorted(calls)]
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            raise ModelError(f"HTTP {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise ModelError(f"cannot reach {self.base_url}: {error.reason}") from error

    def complete(self, messages: list[dict]) -> str:
        request = self._request(self._body(messages, False, None))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                body = json.loads(reply.read())
        except urllib.error.HTTPError as error:
            raise ModelError(f"HTTP {error.code}: {error.read().decode(errors='replace')[:300]}") from error
        except urllib.error.URLError as error:
            raise ModelError(f"cannot reach {self.base_url}: {error.reason}") from error
        return "".join(block.get("text", "") for block in body.get("content") or []
                       if block.get("type") == "text")


def from_environment(env=None):
    """The model this bot uses: Chat Completions for every provider that speaks it, or Anthropic."""
    import os
    env = env or os.environ
    if (env.get("HARNESS_MODEL_PROVIDER") or "").lower() == "anthropic":
        return AnthropicMessages(env.get("HARNESS_MODEL") or "claude-sonnet-4-5",
                                 env.get("HARNESS_MODEL_API_KEY") or "",
                                 env.get("HARNESS_MODEL_BASE_URL") or "https://api.anthropic.com")
    # The default is the llama.cpp server the README starts: port 8080, model name "local". A bot
    # that points elsewhere sets HARNESS_MODEL_BASE_URL; the precheck then says plainly when nothing
    # answers there, instead of a turn that hangs.
    base = env.get("HARNESS_MODEL_BASE_URL") or "http://127.0.0.1:8080/v1"
    return ChatCompletions(base, env.get("HARNESS_MODEL") or "local",
                           env.get("HARNESS_MODEL_API_KEY") or "")
