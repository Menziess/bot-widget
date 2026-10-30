"""A small ACP client: spawn an agent, start a session, run a prompt, answer permissions.

Async, with no opinion about the widget: the spike prints what comes in, the widget adapter
turns it into the dictionary the bubble draws from.
"""

import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field

from acp import PROTOCOL_VERSION, RequestPermissionResponse, text_block
from acp.schema import PermissionOption, ToolCallUpdate
from acp.stdio import spawn_agent_process


@dataclass
class Update:
    """One thing that came in while a turn ran, already flattened to what a reader needs."""

    kind: str  # thought | text | tool | usage | user
    text: str = ""
    # Free-form extras: a tool call's status, a usage update's numbers.
    extra: dict = field(default_factory=dict)


@dataclass
class Turn:
    """How one prompt ended, and what it cost in wall time."""

    stop_reason: str = ""
    updates: list = field(default_factory=list)
    started: float = 0.0
    first_update: float = 0.0
    ended: float = 0.0
    error: str = ""

    @property
    def first_update_ms(self) -> int:
        return round((self.first_update - self.started) * 1000) if self.first_update else 0

    @property
    def total_ms(self) -> int:
        return round((self.ended - self.started) * 1000) if self.ended else 0


def _text_of(content) -> str:
    if isinstance(content, list):
        return "".join(getattr(part, "text", "") for part in content)
    return getattr(content, "text", "") or ""


class AcpClient:
    """One agent process and one session in it.

    allow(title) decides a permission request: True allows it once, False declines, and a
    coroutine is awaited so a caller can wait for the user. The default declines everything, so
    a mistake cannot let an agent write something on its own.
    """

    def __init__(self, command: str, *args: str, cwd: str | None = None, env: dict | None = None,
                 allow=None, on_update=None):
        self.command, self.args, self.cwd, self.env = command, args, cwd, env
        self.allow = allow or (lambda _title: False)
        self.on_update = on_update or (lambda _update: None)
        self.conn = None
        self.process = None
        self.session_id = ""
        self.started = 0.0
        self._open = None
        self._turn = None

    async def __aenter__(self):
        self.started = time.monotonic()
        # The agent needs the whole environment: PATH, HOME and its own provider keys live there.
        env = {**os.environ, **(self.env or {})}
        self._open = spawn_agent_process(self._client, self.command, *self.args, cwd=self.cwd, env=env)
        self.conn, self.process = await self._open.__aenter__()
        return self

    async def __aexit__(self, *exc):
        await self._open.__aexit__(*exc)

    @property
    def startup_ms(self) -> int:
        """Milliseconds from spawn to a session that can take a prompt."""
        return round((self._ready - self.started) * 1000) if getattr(self, "_ready", 0.0) else 0

    async def start(self) -> dict:
        """Initialize and open a session; returns what the agent says about itself."""
        info = await self.conn.initialize(protocol_version=PROTOCOL_VERSION, client_capabilities={})
        session = await self.conn.new_session(cwd=self.cwd or ".", mcp_servers=[])
        self.session_id = session.session_id
        self._ready = time.monotonic()
        return {"protocol": info.protocol_version,
                "name": getattr(getattr(info, "agent_info", None), "name", ""),
                "version": getattr(getattr(info, "agent_info", None), "version", ""),
                "session": self.session_id}

    async def prompt(self, text: str) -> Turn:
        """Send one message and wait for the end of the turn, collecting what came in."""
        turn = Turn(started=time.monotonic())
        self._turn = turn
        try:
            reply = await self.conn.prompt(session_id=self.session_id, prompt=[text_block(text)])
            turn.stop_reason = reply.stop_reason
        except Exception as error:  # a dead agent must read as a failed turn, not a traceback
            turn.error = f"{type(error).__name__}: {error}"
            turn.stop_reason = "error"
        finally:
            turn.ended = time.monotonic()
            self._turn = None
        return turn

    async def cancel(self) -> None:
        await self.conn.cancel(session_id=self.session_id)

    # ── the client half of ACP ──────────────────────────────────

    def _client(self, conn):
        self.conn = conn
        return self

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        kind = getattr(update, "session_update", "")
        if kind in ("agent_thought_chunk", "agent_message_chunk", "user_message_chunk"):
            event = Update(kind={"agent_thought_chunk": "thought", "agent_message_chunk": "text",
                                 "user_message_chunk": "user"}[kind], text=_text_of(update.content))
        elif kind in ("tool_call", "tool_call_update"):
            event = Update("tool", text=getattr(update, "title", "") or "",
                           extra={"status": getattr(update, "status", "") or ""})
        elif kind == "usage_update":
            event = Update("usage", extra={name: getattr(update, name, None)
                                           for name in ("used", "size", "cost")})
        else:
            return
        turn = self._turn
        if turn is not None:
            if not turn.first_update:
                turn.first_update = time.monotonic()
            turn.updates.append(event)
        self.on_update(event)

    async def request_permission(self, session_id: str, tool_call: ToolCallUpdate,
                                 options: list[PermissionOption], **kwargs) -> RequestPermissionResponse:
        title = getattr(tool_call, "title", "") or "an action"
        allowed = self.allow(title)
        if inspect.isawaitable(allowed):
            allowed = await allowed
        chosen = next((option.option_id for option in options
                       if allowed and option.kind.startswith("allow")), None)
        outcome = {"outcome": "selected", "optionId": chosen} if chosen else {"outcome": "cancelled"}
        return RequestPermissionResponse(outcome=outcome)
