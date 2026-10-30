"""The lean agent v0: an ACP agent with one bot's conversation on disk and a chat completions model
behind it.

No tools yet. A turn is: store the message, build the request, stream the answer into the bubble,
store the answer, write a usage line, and only then let a background summary run. Nothing in the
turn path ever waits for a summary.
"""

import asyncio
import os
import time

from acp import PROTOCOL_VERSION
from acp.schema import (AgentMessageChunk, AgentThoughtChunk, InitializeResponse, NewSessionResponse,
                        PromptResponse, TextContentBlock)

from harness.agent import context
from harness.agent.models import ModelError
from harness.agent.store import SessionStore


class LeanAgent:
    """One bot per process: the widget starts one agent per face, with HARNESS_BOT naming the file."""

    def __init__(self, bot: str, model, folder: str | None = None):
        self.bot = bot
        self.model = model
        self.folder = folder or os.environ.get("HARNESS_AGENT_DIR") or os.path.expanduser(
            f"~/.local/share/botwidget/harness/agent/{bot}")
        self.stores: dict[str, SessionStore] = {}
        self.conn = None
        self._cancelled: set[str] = set()
        self._summarising = False

    # ── ACP ─────────────────────────────────────────────────────

    def on_connect(self, conn) -> None:
        self.conn = conn

    async def initialize(self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs):
        return InitializeResponse(protocol_version=PROTOCOL_VERSION,
                                  agent_capabilities={"loadSession": True},
                                  agent_info={"name": f"lean-agent ({self.bot})", "version": "0"})

    async def new_session(self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs):
        session_id = f"{self.bot}-{int(time.time())}"
        self.stores[session_id] = SessionStore(self.folder)
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, mcp_servers=None,
                           additional_directories=None, **kwargs):
        """A restart finds the conversation where it was: the same file, replayed to the widget."""
        store = self.stores.setdefault(session_id, SessionStore(self.folder))
        for message in store.messages(limit=context.KEEP_TURNS * 2):
            await self._chunk(session_id, "user" if message["role"] == "user" else "agent", message["text"])
        return None

    async def cancel(self, session_id: str, **kwargs) -> None:
        self._cancelled.add(session_id)

    async def prompt(self, session_id: str, prompt, **kwargs) -> PromptResponse:
        store = self.stores.setdefault(session_id, SessionStore(self.folder))
        text = "".join(block.text for block in prompt if getattr(block, "text", ""))
        store.add("user", text)
        started = time.monotonic()
        first = 0.0
        answer = []
        usage = {}
        try:
            for kind, value in self.model.stream(context.build(store, self.bot)):
                if session_id in self._cancelled:
                    break
                if kind == "usage":
                    usage = value
                    continue
                if not first:
                    first = time.monotonic()
                if kind == "text":
                    answer.append(value)
                await self._chunk(session_id, "agent" if kind == "text" else "thought", value)
        except ModelError as error:
            store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                         "ms": round((time.monotonic() - started) * 1000), "error": str(error)[:300]})
            return PromptResponse(stop_reason="refusal")
        cancelled = session_id in self._cancelled
        self._cancelled.discard(session_id)
        said = "".join(answer)
        if said:
            store.add("bot", said)
        store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                     "ms": round((time.monotonic() - started) * 1000),
                     "first_ms": round((first - started) * 1000) if first else 0,
                     "input_tokens": (usage.get("prompt_tokens")
                                      or sum(context.estimate(m["content"]) for m in context.build(store, self.bot))),
                     "output_tokens": usage.get("completion_tokens") or context.estimate(said),
                     "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                     "cancelled": cancelled})
        # Never in the turn path: the answer is out before the summary starts.
        if not cancelled:
            asyncio.create_task(self.summarise(store))
        return PromptResponse(stop_reason="cancelled" if cancelled else "end_turn")

    async def _chunk(self, session_id: str, role: str, text: str) -> None:
        if not text or self.conn is None:
            return
        content = TextContentBlock(type="text", text=text)
        update = (AgentMessageChunk(session_update="agent_message_chunk", content=content) if role == "agent"
                  else AgentThoughtChunk(session_update="agent_thought_chunk", content=content))
        await self.conn.session_update(session_id=session_id, update=update)

    async def summarise(self, store: SessionStore) -> None:
        """Fold the older half into the summary, between turns; a second one at a time, never in a turn."""
        if self._summarising:
            return
        older = context.to_summarise(store)
        if not older:
            return
        self._summarising = True
        try:
            text = "\n".join(f"{message['role']}: {message['text']}" for message in older)
            summary = await asyncio.to_thread(
                self.model.complete,
                [{"role": "system", "content": context.SUMMARY_PROMPT},
                 {"role": "user", "content": (store.summary + "\n" if store.summary else "") + text}])
            if summary.strip():
                store.set_summary(summary.strip())
                store.set("summary_upto", str(len(store.messages()) - context.KEEP_TURNS * 2))
        except ModelError:
            pass  # the next turn still works; the summary is simply tried again later
        finally:
            self._summarising = False
