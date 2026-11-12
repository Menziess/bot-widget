"""The lean agent v0: an ACP agent with one bot's conversation on disk and a chat completions model
behind it.

No tools yet. A turn is: store the message, build the request, stream the answer into the bubble,
store the answer, write a usage line, and only then let a background summary run. Nothing in the
turn path ever waits for a summary.
"""

import asyncio
import hashlib
import json
import sqlite3
import inspect
import os
import threading
import time

from acp import PROTOCOL_VERSION
from acp.schema import (AgentMessageChunk, AgentThoughtChunk, InitializeResponse, LoadSessionResponse,
                        NewSessionResponse,
                        PermissionOption, PromptResponse, TextContentBlock, ToolCallProgress, ToolCallStart,
                        ToolCallUpdate, UsageUpdate, UserMessageChunk)

from harness import RESUME_PROMPT, approvals
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
        workspace = os.environ.get("HARNESS_WORKSPACE") or ""
        permission = os.environ.get("HARNESS_WORKSPACE_PERMISSIONS") or "allow"
        permission = {"allowlist": "allow", "allow-for-session": "allow_session"}.get(permission, permission)
        diff_mode = os.environ.get("HARNESS_DIFF_PERMISSIONS") or "ask"
        self.diff_edit_mode = diff_mode  # ask | always | never
        self.tools = tools or Tools(os.environ.get("HARNESS_MCP_SERVER") or "",
                                    {name.strip() for name in
                                     (os.environ.get("HARNESS_MCP_READ_ONLY") or "").split(",") if name.strip()},
                                    workspace=workspace, permission=permission)
        self.folder = folder or os.environ.get("HARNESS_AGENT_DIR") or os.path.expanduser(
            f"~/.local/share/botwidget/harness/agent/{bot}")
        self.stores: dict[str, SessionStore] = {}
        self._cwds: dict[str, str] = {}  # the folder the ACP client opened each session in
        self._own_tools = tools is None  # only tools built here follow the session's folder
        from harness.agent.workspace import ShellAllow
        self.shell_allow = ShellAllow(
            os.environ.get("HARNESS_SHELL_ALLOW_FILE") or os.path.join(self.folder, "shell-allow.json"),
            tuple((os.environ.get("HARNESS_SHELL_ALLOW") or "").split(",")))
        # HARNESS_SHELL_READONLY=0 makes every shell command ask again.
        self.shell_readonly_free = os.environ.get("HARNESS_SHELL_READONLY", "1") != "0"
        self.conn = None
        self._cancelled: set[str] = set()
        self._turns: set[str] = set()  # a session with a turn running: only then does a cancel mean anything
        self._checked = False  # the model server was reached once already
        self._stops: dict[str, threading.Event] = {}
        self._replies: dict[str, object] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._summarising = False
        self.jobs = None  # background shell jobs; created once a workspace exists
        self._job_tools_ready = False
        self._tool_session = ""
        self._workspace = ""
        self._inbox: dict[str, list[str]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._aio = None
        self._shutting = False

    # ── ACP ─────────────────────────────────────────────────────

    def on_connect(self, conn) -> None:
        self.conn = conn

    async def initialize(self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs):
        return InitializeResponse(protocol_version=PROTOCOL_VERSION,
                                  agent_capabilities={"loadSession": True},
                                  agent_info={"name": f"lean-agent ({self.bot})", "version": "0"})

    async def new_session(self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs):
        session_id = f"{self.bot}-{int(time.time())}"
        self._cwds[session_id] = cwd or ""
        self.stores[session_id] = SessionStore(self.folder)
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, mcp_servers=None,
                           additional_directories=None, **kwargs):
        """A restart finds the conversation where it was: the same file, replayed to the widget."""
        store = self.stores.setdefault(session_id, SessionStore(self.folder))
        self._cwds[session_id] = cwd or ""
        for message in store.messages(limit=context.KEEP_TURNS * 2):
            if message["role"] == "tool":
                # An ordinary tool line stays out of the bubble. A decline must still be said,
                # or a restart looks like the write happened.
                if "declined" not in message["text"]:
                    continue
                await self._chunk(session_id, "agent", message["text"])
                continue
            await self._chunk(session_id, "user" if message["role"] == "user" else "agent", message["text"])
        # A turn that was open when the process went away: say so, so the widget can ask it to pick up again.
        return LoadSessionResponse(field_meta={"interrupted": True}) if store.get("open_turn") else None

    async def cancel(self, session_id: str, **kwargs) -> None:
        """Stop the turn now. A cancel with no turn running is dropped: it used to arrive before the
        turn it was meant for, and cancel that one."""
        if session_id not in self._turns:
            return
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
        if text != RESUME_PROMPT:
            store.add("user", text)
        store.set("open_turn", "1")
        self._cancelled.discard(session_id)
        self._aio = asyncio.get_running_loop()
        # The lock keeps a job result out of this turn. It is delivered after the lock drops.
        async with self._session_lock(session_id):
            self._turns.add(session_id)
            try:
                response = await self._answer(session_id, store)
                # Only a turn that ended says so. One cut off by a vanished client (an error, a cancelled task) leaves
                # the flag, and the next start picks the turn up again.
                store.set("open_turn", "")
                return response
            finally:
                self._turns.discard(session_id)
                self._cancelled.discard(session_id)

    async def _answer(self, session_id: str, store: SessionStore) -> PromptResponse:
        self._tool_session = session_id
        self._aio = asyncio.get_running_loop()
        self._workspace = self._workspace_for(session_id)
        await self.tools.start()
        self._ensure_job_tools()
        self.tools.add(self._pin(store))
        for t in self._memory_tools():
            self.tools.add(t)
        self.tools.add(Tool("approval_log", "Who accepted or declined which action recently, and how (bubble, cli, timeout).",
                            {"type": "object", "properties": {}}, lambda _args: approvals.recent()))
        started = time.monotonic()
        first = 0.0
        answer = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        cancelled = False
        steps = 0
        last = {}
        try:
            if not self._checked and hasattr(self.model, "ready"):
                await asyncio.to_thread(self.model.ready)
                self._checked = True
            messages = context.build(store, self.bot, model=self.model, workspace=self._workspace)
            await self._usage(session_id, store)
            for _step in range(MAX_STEPS):
                steps += 1
                calls = []
                step_text, thought_chars, finish = [], 0, ""
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
                    if kind == "finish":
                        finish = value
                        continue
                    if kind == "thought":
                        thought_chars += len(value)
                    if kind == "text" and not first:
                        first = time.monotonic()  # the first word, not the first event
                    if kind == "text":
                        answer.append(value)
                        step_text.append(value)
                    await self._chunk(session_id, "agent" if kind == "text" else "thought", value)
                # What the last step looked like, so a turn that ends on talk without the call can be explained.
                last = {"finish": finish, "calls": len(calls), "thought_chars": thought_chars,
                        "text_tail": "".join(step_text)[-200:]}
                if cancelled or not calls:
                    break
                messages.append({"role": "assistant", "content": "", "tool_calls": calls})
                # H6: execute tool calls with parallel reads, cheap-first, dedup, and guard-rails.
                results = await self._execute_calls(session_id, store, calls)
                for call, result in zip(calls, results):
                    messages.append({"role": "tool", "tool_call_id": call["id"],
                                     "content": TOOL_OUTPUT + "\n" + result})
        except ModelError as error:
            store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                         "ms": round((time.monotonic() - started) * 1000), "error": str(error)[:300]})
            # The reason travels in _meta: "refusal" alone cannot tell a 401 from a bad prompt.
            return PromptResponse(stop_reason="refusal", field_meta={"error": str(error)[:300]})
        cancelled = cancelled or session_id in self._cancelled
        self._cancelled.discard(session_id)
        said = "".join(answer)
        if said:
            store.add("bot", said)
        counted = bool(usage["prompt_tokens"])
        store.usage({"at": round(time.time(), 3), "bot": self.bot, "model": self.model.model,
                     "ms": round((time.monotonic() - started) * 1000),
                     "first_ms": round((first - started) * 1000) if first else 0,
                     "steps": steps, "last_step": last,
                     "input_tokens": usage["prompt_tokens"] or sum(context.estimate(m["content"])
                                                                   for m in messages if m.get("content")),
                     "output_tokens": usage["completion_tokens"] or context.estimate(said),
                     "cached_tokens": usage["cached_tokens"],
                     # A cancel before the first usage chunk has no cache figure; 0 would look measured.
                     "estimated": not counted,
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

    def _memory_tools(self) -> list:
        """Three memory tools for durable, topic-scoped storage."""
        from harness.agent.memory import memory_tools_for
        return memory_tools_for(workspace=self._workspace or "")

    def _workspace_for(self, session_id: str) -> str:
        """The folder this session works in: configured, else the ACP cwd, else home. Tools that were
        handed in keep their own workspace."""
        if not self._own_tools:
            return getattr(self.tools, "workspace", "") or ""
        from harness.agent.workspace import default_workspace
        workspace = default_workspace(os.environ.get("HARNESS_WORKSPACE") or "", self._cwds.get(session_id, ""))
        self.tools.workspace = workspace
        return workspace

    def shutdown(self) -> None:
        """Kill background jobs. The bubble closing does not call this; the agent process does."""
        self._shutting = True
        if self.jobs is not None:
            self.jobs.shutdown()

    def _session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def _ensure_job_tools(self) -> None:
        workspace = getattr(self.tools, "workspace", "") or ""
        if not workspace or self._job_tools_ready:
            return
        from harness.agent.jobs import JobRunner, config_from_env

        settings = config_from_env()
        self.jobs = JobRunner(workspace, self._job_finished, **settings)
        command = {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number",
                            "description": "Seconds before the job is killed. Omit to let it run until it exits."},
                "hook_command": {"type": "string",
                                 "description": "Shell command run on exit. The JSON payload is its stdin."},
                "hook_url": {"type": "string",
                             "description": "Webhook called on exit with the JSON payload. No default URL."},
                "hook_key_file": {"type": "string",
                                  "description": "Path to a file with the webhook bearer token. Never the token itself."},
            },
            "required": ["command"],
        }
        self.tools.add(Tool(
            "shell_background",
            "Start a shell command in the background inside the workspace and return immediately. "
            "Same permission, workspace scope and refusal rules as shell. The job keeps running after "
            "this turn and after the bubble closes. When it exits, this session gets the exit code and "
            "a short tail of the output as a new message. Optional hook_command and hook_url run then; "
            "hook_key_file is a path to the webhook bearer token, never the token.",
            command, self._start_job, writes=True))
        self.tools.add(Tool(
            "jobs",
            "List background shell jobs for this session: id, status and command.",
            {"type": "object", "properties": {}}, self._list_jobs))
        self.tools.add(Tool(
            "job_cancel",
            "Stop one background shell job by id. Its result still arrives as a new message.",
            {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]},
            self._cancel_job))
        self._job_tools_ready = True

    def _start_job(self, arguments: dict) -> str:
        if self.jobs is None:
            raise ToolError("no workspace, so background shell is not available")
        timeout = arguments.get("timeout")
        result = self.jobs.start(
            self._tool_session, arguments.get("command") or "",
            timeout=None if timeout in (None, "") else float(timeout),
            hook_command=str(arguments.get("hook_command") or ""),
            hook_url=str(arguments.get("hook_url") or ""),
            hook_key_file=str(arguments.get("hook_key_file") or ""))
        self._ping_soon()
        return result

    def _list_jobs(self, _arguments: dict) -> str:
        if self.jobs is None:
            return "(no background jobs)"
        return self.jobs.list(self._tool_session)

    def _cancel_job(self, arguments: dict) -> str:
        if self.jobs is None:
            raise ToolError("no background jobs")
        result = self.jobs.cancel(self._tool_session, str(arguments.get("job_id") or ""))
        self._ping_soon()
        return result

    def _ping_soon(self, followup: bool | None = None) -> None:
        session = self._tool_session
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._jobs_ping(session, followup))

    async def _jobs_ping(self, session_id: str, followup: bool | None = None) -> None:
        """A small note for the bubble: how many jobs are running, and whether a result is being read."""
        if self.conn is None:
            return
        meta = {"jobs_only": True, "jobs": self.jobs.running_count() if self.jobs else 0}
        if followup is not None:
            meta["followup"] = followup
        update = UsageUpdate(session_update="usage_update", used=0, size=0, field_meta=meta)
        await self.conn.session_update(session_id=session_id, update=update)

    def _job_finished(self, session_id: str, text: str) -> None:
        """Watcher thread: queue the result. Never enter a turn that is already running."""
        if self._shutting:
            return
        loop = self._aio
        if loop is None or loop.is_closed():
            self._inbox.setdefault(session_id, []).append(text)
            return
        loop.call_soon_threadsafe(self._enqueue_job, session_id, text)

    def _enqueue_job(self, session_id: str, text: str) -> None:
        self._inbox.setdefault(session_id, []).append(text)
        asyncio.create_task(self._drain_jobs(session_id))

    async def _drain_jobs(self, session_id: str) -> None:
        """One finished job, then the next. Waits out a user turn instead of mixing with it."""
        if self._shutting:
            return
        async with self._session_lock(session_id):
            while self._inbox.get(session_id) and not self._shutting:
                text = self._inbox[session_id].pop(0)
                store = self.stores.setdefault(session_id, SessionStore(self.folder))
                self._turns.add(session_id)
                self._cancelled.discard(session_id)
                try:
                    store.set("open_turn", "1")
                    store.add("user", text)
                    await self._jobs_ping(session_id, followup=True)
                    await self._chunk(session_id, "user", text)
                    await self._answer(session_id, store)
                    store.set("open_turn", "")
                finally:
                    self._turns.discard(session_id)
                    self._cancelled.discard(session_id)
                    await self._jobs_ping(session_id, followup=False)

    async def _usage(self, session_id: str, store: SessionStore, compacted: bool = False) -> None:
        """The context meter, and a one-line notice when a summary has just landed."""
        if self.conn is None:
            return
        used, size = context.meter(store, self.bot, getattr(self.model, "context_size", 0), model=self.model,
                                   workspace=self._workspace_for(session_id))
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
        if tool.writes:
            remembered = (getattr(self.tools, "permission", "ask") == "allow_session"
                          and title in getattr(self.tools, "_session_allows", ()))
            command = str(arguments.get("command") or "")
            if name in ("shell", "shell_background") and not remembered and self._shell_free(command):
                remembered = True  # read-only, or a prefix the user saved: no question
            # H7: show diff in bubble for write_file, respect diff_edit_mode
            if name in ("write_file", "edit") and not remembered:
                result = await self._handle_write_file(session_id, call, arguments, store, title)
                return result
            if not remembered:
                prefix = self._shell_prefix(command) if name in ("shell", "shell_background") else ""
                choice = await self._ask_choice(session_id, call["id"], title, prefix)
                if not choice:
                    await self._tool_call(session_id, call["id"], title, "completed", "failed")
                    return self._note_tool(store, name, "declined by the user; nothing was done",
                                           "The user declined this action. Do not try it another way.")
                if choice == "allow_always" and prefix:
                    self.shell_allow.add(getattr(self.tools, "workspace", "") or "", prefix)
                if getattr(self.tools, "permission", "ask") == "allow_session":
                    self.tools._session_allows.add(title)
        try:
            result = tool.run(arguments)
            if inspect.isawaitable(result):
                result = await result
        except ToolError as error:
            await self._tool_call(session_id, call["id"], title, "completed", "failed")
            return self._note_tool(store, name, f"failed: {error}", f"The tool failed: {error}")
        await self._tool_call(session_id, call["id"], title, "completed", "completed")
        return self._note_tool(store, name, "ok", result)

    async def _handle_write_file(self, session_id: str, call: dict, arguments: dict,
                                  store: SessionStore, title: str) -> str:
        """H7: Show a diff in the bubble for write_file and edit, then apply/reject/never."""
        from harness.agent.workspace import _check_inside, compute_edit, _diff_text

        name = (call.get("function") or {}).get("name") or "write_file"
        path = str(arguments.get("path", ""))
        workspace = getattr(self.tools, "workspace", "") or ""

        # 1) The proposed content and its diff. An edit that cannot apply fails here, before any prompt.
        content = arguments.get("content", "")
        if name == "edit":
            try:
                _real, before, content = compute_edit(
                    workspace, path, str(arguments.get("old_string", "")),
                    str(arguments.get("new_string", "")), bool(arguments.get("replace_all")))
            except ToolError as error:
                await self._tool_call(session_id, call["id"], title, "completed", "failed")
                return self._note_tool(store, name, f"failed: {error}", f"The tool failed: {error}")
            diff_text = _diff_text(path, before, content)
        else:
            diff_text = ""
            diff_tool = self.tools.find("diff")
            if diff_tool:
                try:
                    diff_text = diff_tool.run({"path": path, "content": content})
                except ToolError:
                    diff_text = "(cannot compute diff)"

        # 2) Show the diff in the bubble (as a tool_call_update with kind="edit")
        diff_title = f"{name} {path}"
        await self._tool_call(session_id, call["id"], diff_title, "pending", "in_progress")

        # 3) Decide based on diff_edit_mode
        mode = self.diff_edit_mode

        if mode == "never":
            # Show diff as proposal, do not apply
            await self._tool_call(session_id, call["id"], diff_title, "completed", "completed")
            return self._note_tool(store, name, "skipped (diff mode: never)",
                                   f"Proposal for {path}:\n{diff_text}\n\nThe file was not changed (diff mode is 'never').")

        if mode == "ask":
            # Show diff, wait for user to apply or reject
            if not await self._ask_diff(session_id, call["id"], diff_title, diff_text):
                await self._tool_call(session_id, call["id"], diff_title, "completed", "failed")
                return self._note_tool(store, name, "declined by the user; nothing was done",
                                       "The user declined this action. Do not try it another way.")

        # mode is "always" or user approved: apply the write
        # Record bytes before write (for undo)
        edit = getattr(self.tools, "_edit", None)
        real_path = path
        if edit:
            try:
                real_path = _check_inside(workspace, path) if workspace else path
                # Read current on-disk content so undo restores it
                try:
                    with open(real_path, "rb") as fh:
                        existing = fh.read()
                except FileNotFoundError:
                    existing = b""
                edit.before(real_path, existing.decode(errors="replace"))
            except ToolError:
                pass  # path is outside workspace or secret; the tool will refuse

        # Now actually write
        write_tool = self.tools.find(name)
        result = f"Wrote to {path}."
        if write_tool:
            try:
                result = write_tool.run(arguments)
                # Record on the undo stack for LIFO undo
                if edit:
                    try:
                        edit.record(_check_inside(workspace, path) if workspace else path, content)
                    except ToolError:
                        pass
            except ToolError as error:
                await self._tool_call(session_id, call["id"], diff_title, "completed", "failed")
                return self._note_tool(store, name, f"failed: {error}",
                                       f"The tool failed: {error}")
        await self._tool_call(session_id, call["id"], diff_title, "completed", "completed")
        return self._note_tool(store, name, "ok", result if name == "edit" else f"Wrote to {path}.")

    async def _ask_diff(self, session_id: str, call_id: str, title: str, diff_text: str) -> bool:
        """Show a diff in the bubble and wait for Apply or Reject. Returns True if applied."""
        if self.conn is None:
            return False
        # Use kind="edit" so the widget knows this is an edit diff.
        # The diff_text is stored in field_meta so the widget can display it in the bubble.
        response = await self.conn.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id=call_id, title=title, kind="edit", status="pending",
                                     field_meta={"diff": diff_text}),
            options=[PermissionOption(option_id="allow", name="Apply", kind="allow_once"),
                     PermissionOption(option_id="decline", name="Reject", kind="reject_once")])
        outcome = response.outcome
        return getattr(outcome, "outcome", "") == "selected" and getattr(outcome, "option_id", "") == "allow"

    # ── H6: parallel tool execution ───────────────────────────────────

    # Cheap-first ordering: groups of tool names, cheapest first.
    _CHEAP_FIRST = [
        {"list_dir", "memory_read"},          # group 0: search/list/git-read/memory_read
        {"read_file"},                         # group 1: read_file
        {"write_file", "delete_file", "edit", "shell", "shell_background", "memory_forget"},  # group 2: writes
    ]

    def _tool_cost_key(self, name: str) -> int:
        """Return a group index for cheap-first ordering (lower = cheaper)."""
        for idx, group in enumerate(self._CHEAP_FIRST):
            if name in group:
                return idx
        return len(self._CHEAP_FIRST)  # unknown tools go last

    @staticmethod
    def _call_cache_key(call: dict) -> str:
        """Canonical JSON for deduplication: tool name + sorted arguments."""
        name = (call.get("function") or {}).get("name") or ""
        raw_args = (call.get("function") or {}).get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
            canonical = json.dumps({"name": name, "args": args}, sort_keys=True)
        except json.JSONDecodeError:
            canonical = raw_args
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def _execute_calls(self, session_id: str, store: SessionStore, calls: list) -> list:
        """Execute a list of tool calls. H6 features:
        - Cheap-first ordering (within one model step only).
        - Parallel read-only tools via asyncio.gather.
        - Writes stay serial and go through _ask.
        - No repeated calls: deduplicate by (name + args).
        - Stop when good enough: skip writes if a read of the same path failed.
        """
        parallel = os.environ.get("HARNESS_TOOL_PARALLEL", "1") != "0"

        # 1) Classify calls: read-only vs write, and detect no-tool errors.
        classified = []  # list of dict with: call, tool, is_write, is_no_tool, cache_key
        for call in calls:
            name = (call.get("function") or {}).get("name") or ""
            tool = self.tools.find(name)
            cache_key = None
            if tool is None:
                classified.append({"call": call, "tool": None, "is_write": False,
                                   "is_no_tool": True, "result": f"There is no tool called {name}."})
                continue
            cache_key = self._call_cache_key(call) if not tool.writes else None
            classified.append({"call": call, "tool": tool, "is_write": tool.writes,
                               "is_no_tool": False, "cache_key": cache_key})

        # 2) Dedup reads (writes are NOT cached).
        seen_cache_keys: dict[str, str] = {}  # cache_key -> result text
        deduped = []
        for item in classified:
            if item.get("is_no_tool"):
                deduped.append(item)
                continue
            ck = item.get("cache_key")
            if ck is not None and ck in seen_cache_keys:
                item["result"] = f"Already done earlier in this turn: {ck[:12]}."
                item["deduped"] = True
            deduped.append(item)
            if ck is not None:
                seen_cache_keys[ck] = None  # placeholder; will be filled after execution

        # 3) Split reads and writes, order reads cheap-first.
        reads = [item for item in deduped if not item["is_write"] and not item.get("deduped")]
        writes = [item for item in deduped if item["is_write"] or item.get("deduped")]

        if reads:
            reads.sort(key=lambda item: self._tool_cost_key(
                (item["call"].get("function") or {}).get("name") or ""))

        # 4) Execute reads in parallel.
        read_results = []
        if reads:
            if parallel:
                coros = [self._run_single_call(session_id, store, item["call"], item["tool"])
                         for item in reads]
                raw = await asyncio.gather(*coros, return_exceptions=True)
                for r in raw:
                    if isinstance(r, Exception):
                        read_results.append(f"tool error: {r}")
                    else:
                        read_results.append(r)
            else:
                for item in reads:
                    r = await self._run_single_call(session_id, store, item["call"], item["tool"])
                    read_results.append(r)

        # Map read results back to their items.
        read_idx = 0
        for item in reads:
            item["result"] = read_results[read_idx]
            if item.get("cache_key"):
                seen_cache_keys[item["cache_key"]] = read_results[read_idx]
            read_idx += 1

        # 5) Execute writes serially, checking "stop when good enough".
        for item in writes:
            if item.get("deduped"):
                continue  # dedup already handled
            if not await self._should_write(session_id, store, item["call"]):
                item["result"] = ("Skipping write: the preceding read of this path failed or was denied.")
                continue
            item["result"] = await self._use_tool(session_id, store, item["call"])

        # 6) Restore original order.
        results = []
        deduped_iter = iter(deduped)
        for original in classified:
            if original.get("is_no_tool"):
                results.append(original["result"])
                continue
            # Advance deduped until we find the same call id.
            while True:
                d = next(deduped_iter)
                if d["call"] is original["call"]:
                    results.append(d["result"])
                    break

        return results

    async def _should_write(self, session_id: str, store: SessionStore, call: dict) -> bool:
        """Check if a preceding read of the same path failed or was denied.

        If the model asked for a read then a write on the same path, and the read
        failed or was denied, skip the write (the model should know the read failed).
        """
        path_arg = call.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(path_arg) if isinstance(path_arg, str) else path_arg
        except json.JSONDecodeError:
            return True

        target_path = args.get("path", "")
        if not target_path:
            return True

        # Look at the last tool result in the store for a read of the same path.
        messages = store.messages()
        for msg in reversed(messages):
            if msg["role"] == "tool" and "read_file" in msg.get("text", ""):
                if target_path in msg.get("text", ""):
                    if "declined" in msg["text"].lower() or "cannot" in msg["text"].lower() or "failed" in msg["text"].lower():
                        return False
                    break
        return True

    async def _run_single_call(self, session_id: str, store: SessionStore, call: dict,
                                tool: object) -> str:
        """Run one tool call."""
        return await self._use_tool(session_id, store, call)

    @staticmethod
    def _note_tool(store: SessionStore, name: str, outcome: str, answer: str) -> str:
        """One short line per call in the session, so a restart still knows what a tool did — or that
        the user said no. The complete answer is kept too; the model is shown the answer itself, or its
        head and tail with the path of a file that holds the rest when it is large."""
        from harness.agent.spill import spill
        shown, path = spill(answer, name) if isinstance(answer, str) else (answer, "")
        store.add("tool", f"{name}: {' '.join(outcome.split())[:200]}")
        if outcome == "ok" and isinstance(answer, str) and answer:
            store.add_tool_result(name, shown, answer, path)
        return shown

    def _shell_free(self, command: str) -> bool:
        """A shell command that needs no question: read-only, or covered by a saved prefix."""
        workspace = getattr(self.tools, "workspace", "") or ""
        if not workspace or not command:
            return False
        return self.shell_allow.allows(workspace, command, read_only=self.shell_readonly_free)

    @staticmethod
    def _shell_prefix(command: str) -> str:
        from harness.agent.workspace import suggest_prefix
        return suggest_prefix(command)

    async def _ask(self, session_id: str, call_id: str, title: str) -> bool:
        """Accept and Decline in the bubble; anything but an explicit allow counts as no."""
        return bool(await self._ask_choice(session_id, call_id, title))

    async def _ask_choice(self, session_id: str, call_id: str, title: str, always_prefix: str = "") -> str:
        """'allow', 'allow_always' (only offered with a prefix to save) or '' for anything else."""
        if self.conn is None:
            return ""
        options = [PermissionOption(option_id="allow", name="Allow", kind="allow_once")]
        if always_prefix:
            options.append(PermissionOption(option_id="allow_always", name=f"Always allow `{always_prefix}`",
                                            kind="allow_always"))
        options.append(PermissionOption(option_id="decline", name="Decline", kind="reject_once"))
        response = await self.conn.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id=call_id, title=title, kind="edit", status="pending"),
            options=options)
        outcome = response.outcome
        if getattr(outcome, "outcome", "") != "selected":
            return ""
        chosen = getattr(outcome, "option_id", "")
        return chosen if chosen in ("allow", "allow_always") else ""

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
        self._summarising = True
        try:
            older = context.to_summarise(store)
            if not older:
                return
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
        except (OSError, sqlite3.OperationalError, sqlite3.ProgrammingError):
            pass  # the session folder may already have been removed (tests, --live teardown)
        finally:
            self._summarising = False
