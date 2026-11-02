"""The lean agent v0: an ACP agent with one bot's conversation on disk and a chat completions model
behind it.

No tools yet. A turn is: store the message, build the request, stream the answer into the bubble,
store the answer, write a usage line, and only then let a background summary run. Nothing in the
turn path ever waits for a summary.
"""

import asyncio
import inspect
import os
import threading
import time

from acp import PROTOCOL_VERSION
from acp.schema import (AgentMessageChunk, AgentThoughtChunk, InitializeResponse, NewSessionResponse,
                        PermissionOption, PromptResponse, TextContentBlock, ToolCallProgress, ToolCallStart,
                        ToolCallUpdate, UsageUpdate, UserMessageChunk)

from harness.agent import context
from harness.agent.models import ModelError
from harness.agent.store import SessionStore
from harness.agent.tools import TOOL_OUTPUT, Tool, ToolError, Tools

MAX_STEPS = 6  # a tool loop that never settles must still end the turn


class LeanAgent:
    """One bot per process: the widget starts one agent per face, with HARNESS_BOT naming the file."""

    def __init__(self, bot: str, model, folder: str | None = None, tools: Tools | None = None):
        self.bot = bot
        self.model = model
        self.tools = tools or Tools(os.environ.get("HARNESS_MCP_SERVER") or "",
                                    {name.strip() for name in
                                     (os.environ.get("HARNESS_MCP_READ_ONLY") or "").split(",") if name.strip()})
        self.folder = folder or os.environ.get("HARNESS_AGENT_DIR") or os.path.expanduser(
            f"~/.local/share/botwidget/harness/agent/{bot}")
        self.stores: dict[str, SessionStore] = {}
        self.conn = None
        self._cancelled: set[str] = set()
        self._stops: dict[str, threading.Event] = {}
        self._replies: dict[str, object] = {}
        self._queues: dict[str, asyncio.Queue] = {}
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
            if message["role"] == "tool":
                continue  # a tool line is context for the model, not something the bot said
            await self._chunk(session_id, "user" if message["role"] == "user" else "agent", message["text"])
        return None

    async def cancel(self, session_id: str, **kwargs) -> None:
        """Stop the turn now: the model stream is read in a thread, so this loop is free to answer."""
        self._cancelled.add(session_id)
        if stop := self._stops.get(session_id):
            stop.set()
        if reply := self._replies.get(session_id):
            try:
                reply.close()  # unblocks the reading thread between chunks
            except Exception:
                pass
        if queue := self._queues.get(session_id):
            queue.put_nowait(("cancelled", ""))

    async def prompt(self, session_id: str, prompt, **kwargs) -> PromptResponse:
        store = self.stores.setdefault(session_id, SessionStore(self.folder))
        text = "".join(block.text for block in prompt if getattr(block, "text", ""))
        store.add("user", text)
        await self.tools.start()
        self.tools.add(self._pin(store))
        await self._usage(session_id, store)
        started = time.monotonic()
        first = 0.0
        answer = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        messages = context.build(store, self.bot)
        cancelled = False
        steps = 0
        try:
            for _step in range(MAX_STEPS):
                steps += 1
                calls = []
                async for kind, value in self._events(session_id, messages):
                    if kind == "cancelled":
                        cancelled = True
                        break
                    if kind == "usage":
                        usage["prompt_tokens"] += value.get("prompt_tokens") or 0
                        usage["completion_tokens"] += value.get("completion_tokens") or 0
                        usage["cached_tokens"] += (value.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                        continue
                    if kind == "tool_calls":
                        calls = value
                        continue
                    if not first:
                        first = time.monotonic()
                    if kind == "text":
                        answer.append(value)
                    await self._chunk(session_id, "agent" if kind == "text" else "thought", value)
                if cancelled or not calls:
                    break
                messages.append({"role": "assistant", "content": "", "tool_calls": calls})
                for call in calls:
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": TOOL_OUTPUT + "\n" + await self._use_tool(session_id, store, call)})
        except ModelError as error:
            store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                         "ms": round((time.monotonic() - started) * 1000), "error": str(error)[:300]})
            return PromptResponse(stop_reason="refusal")
        cancelled = cancelled or session_id in self._cancelled
        self._cancelled.discard(session_id)
        said = "".join(answer)
        if said:
            store.add("bot", said)
        store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                     "ms": round((time.monotonic() - started) * 1000),
                     "first_ms": round((first - started) * 1000) if first else 0,
                     "steps": steps,
                     "input_tokens": usage["prompt_tokens"] or sum(context.estimate(m["content"])
                                                                   for m in messages if m.get("content")),
                     "output_tokens": usage["completion_tokens"] or context.estimate(said),
                     "cached_tokens": usage["cached_tokens"],
                     "cancelled": cancelled})
        # Never in the turn path: the answer is out before the summary starts.
        if not cancelled:
            asyncio.create_task(self.summarise(store))
        return PromptResponse(stop_reason="cancelled" if cancelled else "end_turn")

    def _pin(self, store: SessionStore) -> Tool:
        """A fact the user wants kept: written to the store, so it rides along after the summary folds
        the turns it came from."""
        def pin(arguments: dict) -> str:
            fact = str(arguments.get("fact") or "").strip()
            known = [line for line in store.get("facts").splitlines() if line.strip()]
            if fact and fact not in known:
                store.set("facts", "\n".join(known + [fact]))
            return "Remembered." if fact else "Nothing to remember."

        return Tool("pin_fact", "Keep one fact in every later request, even after older turns are summarised.",
                    {"type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]}, pin)

    async def _usage(self, session_id: str, store: SessionStore, compacted: bool = False) -> None:
        """The context meter, and a one-line notice when a summary has just landed."""
        if self.conn is None:
            return
        used, size = context.meter(store, self.bot)
        update = UsageUpdate(session_update="usage_update", used=used, size=size,
                             field_meta={"compacted": True} if compacted else None)
        await self.conn.session_update(session_id=session_id, update=update)

    async def _use_tool(self, session_id: str, store: SessionStore, call: dict) -> str:
        """Run one tool the model asked for; a write waits for the bubble's Accept first."""
        import json

        name = (call.get("function") or {}).get("name") or ""
        try:
            arguments = json.loads((call.get("function") or {}).get("arguments") or "{}")
        except json.JSONDecodeError:
            return "The arguments were not valid JSON."
        tool = self.tools.find(name)
        if tool is None:
            return f"There is no tool called {name}."
        title = f"{name} {arguments}"
        await self._tool_call(session_id, call["id"], title, "pending", "in_progress")
        if tool.writes and not await self._ask(session_id, call["id"], title):
            await self._tool_call(session_id, call["id"], title, "completed", "failed")
            return self._note_tool(store, name, "declined by the user; nothing was done",
                                   "The user declined this action. Do not try it another way.")
        try:
            result = tool.run(arguments)
            if inspect.isawaitable(result):
                result = await result
        except ToolError as error:
            await self._tool_call(session_id, call["id"], title, "completed", "failed")
            return self._note_tool(store, name, f"failed: {error}", f"The tool failed: {error}")
        await self._tool_call(session_id, call["id"], title, "completed", "completed")
        return self._note_tool(store, name, "ok", result)

    @staticmethod
    def _note_tool(store: SessionStore, name: str, outcome: str, answer: str) -> str:
        """One short line per call in the session, so a restart still knows what a tool did — or that
        the user said no."""
        store.add("tool", f"{name}: {' '.join(outcome.split())[:200]}")
        return answer

    async def _ask(self, session_id: str, call_id: str, title: str) -> bool:
        """Accept and Decline in the bubble; anything but an explicit allow counts as no."""
        if self.conn is None:
            return False
        response = await self.conn.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id=call_id, title=title, kind="edit", status="pending"),
            options=[PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
                     PermissionOption(option_id="decline", name="Decline", kind="reject_once")])
        outcome = response.outcome
        return getattr(outcome, "outcome", "") == "selected" and getattr(outcome, "option_id", "") == "allow"

    async def _tool_call(self, session_id: str, call_id: str, title: str, status: str, progress: str) -> None:
        """Tell the bubble what the bot is doing, so the cloud shows the tool instead of a frozen thought."""
        if self.conn is None:
            return
        update = (ToolCallStart(session_update="tool_call", tool_call_id=call_id, title=title,
                                kind="other", status=status)
                  if progress == "in_progress"
                  else ToolCallProgress(session_update="tool_call_update", tool_call_id=call_id,
                                        title=title, kind="other", status=progress))
        await self.conn.session_update(session_id=session_id, update=update)

    async def _events(self, session_id: str, messages: list[dict]):
        """The model stream, read in a thread: a 56 s wait must not freeze the ACP loop, or a cancel
        and a permission request would only be seen after the answer.
        """
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        stop = threading.Event()
        done = object()
        self._stops[session_id] = stop
        self._queues[session_id] = queue

        def pump() -> None:
            try:
                for event in self.model.stream(messages, tools=self.tools.specs(), stop=stop,
                                               opened=lambda reply: self._replies.__setitem__(session_id, reply)):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except ModelError as error:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", error))
            except Exception as error:
                if not stop.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, ("error", ModelError(f"{type(error).__name__}: {error}")))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, done)

        threading.Thread(target=pump, daemon=True, name="harness-model").start()
        try:
            while True:
                event = await queue.get()
                if event is done:
                    return
                if event[0] == "error":
                    raise event[1]
                yield event
        finally:
            self._stops.pop(session_id, None)
            self._queues.pop(session_id, None)
            self._replies.pop(session_id, None)

    async def _chunk(self, session_id: str, role: str, text: str) -> None:
        if not text or self.conn is None:
            return
        content = TextContentBlock(type="text", text=text)
        if role == "agent":
            update = AgentMessageChunk(session_update="agent_message_chunk", content=content)
        elif role == "user":
            update = UserMessageChunk(session_update="user_message_chunk", content=content)
        else:
            update = AgentThoughtChunk(session_update="agent_thought_chunk", content=content)
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
                for session_id in self.stores:
                    await self._usage(session_id, store, compacted=True)
        except ModelError:
            pass  # the next turn still works; the summary is simply tried again later
        finally:
            self._summarising = False
