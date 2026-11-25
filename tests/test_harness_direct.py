"""In-process calls of the harness. The ACP tests start the agent as another process, which coverage
never sees, so these tests call the same functions in this process.
"""

import asyncio
import json
import os
import runpy
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from harness.acp_client import AcpClient, Turn, _text_of
from harness.agent.agent import LeanAgent
from harness.agent.context import (
    BUDGET_CHARS,
    FILL_SUMMARISE,
    KEEP_TURNS,
    SUMMARY_AFTER,
    build,
    fill_ratio,
    to_summarise,
)
from harness.agent.models import (
    AnthropicMessages,
    ChatCompletions,
    ModelError,
    _anthropic_content,
    from_environment,
)
from harness.agent.store import SessionStore
from harness.agent.tools import Tool, ToolError, Tools, list_dir, read_file, write_file
from tests.fake_anthropic import FakeAnthropic
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP_SERVER = f"{sys.executable} {os.path.join(ROOT, 'tests', 'fake_mcp_server.py')}"


class ScriptModel:
    """Yields scripted stream events. A callable script waits on the stop event itself."""

    def __init__(self, scripts=()):
        self.model = "script"
        self.context_size = 4096
        self.scripts = list(scripts)
        self.ready_calls = 0
        self.completed = []
        self.complete_result = "notes"
        self.reply = None
        self.required = []  # the tool each step had to call, "" when it was free

    def ready(self):
        self.ready_calls += 1

    def stream(self, messages, tools=None, stop=None, opened=None, tool=""):
        self.required.append(tool)
        step = self.scripts.pop(0)
        if opened is not None and self.reply is not None:
            opened(self.reply)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            yield from step(stop)
            return
        for event in step:
            if stop is not None and stop.is_set():
                return
            yield event

    def complete(self, messages):
        self.completed.append(messages)
        if isinstance(self.complete_result, Exception):
            raise self.complete_result
        return self.complete_result


class Reply:
    def __init__(self, broken=False):
        self.broken = broken
        self.closed = False

    def close(self):
        self.closed = True
        if self.broken:
            raise RuntimeError("socket")


class Conn:
    def __init__(self, allow=True):
        self.allow = allow
        self.updates = []

    async def session_update(self, session_id, update):
        self.updates.append((session_id, update))

    async def request_permission(self, **kwargs):
        class Outcome:
            outcome = "selected" if self.allow else "cancelled"
            option_id = "allow" if self.allow else ""

        class Response:
            outcome = Outcome()

        return Response()


class Block:
    def __init__(self, text=None):
        if text is not None:
            self.text = text


def call(name, arguments, call_id="1"):
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "function": {"name": name, "arguments": raw}}


class DirectAgent(unittest.IsolatedAsyncioTestCase):
    """Should drive one lean agent without starting a second Python."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    async def test_a_turn_streams_usage_and_a_reply_and_folds_a_long_chat(self):
        """Should store the answer, count cached tokens, and summarise once the chat is long."""
        store = SessionStore(self.folder)
        for number in range(41):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        model = ScriptModel([[("text", "hoi"),
                              ("usage", {"prompt_tokens": 4, "completion_tokens": 1,
                                         "prompt_tokens_details": {"cached_tokens": 2}})]])
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        conn = Conn()
        agent.on_connect(conn)
        info = await agent.initialize(1)
        agent_info = info.agent_info
        name = agent_info["name"] if isinstance(agent_info, dict) else agent_info.name
        self.assertIn("Ada", name)
        opened = await agent.new_session("/tmp")
        # The seeded file is the same folder, so the new session sees those lines plus the prompt.
        agent.stores[opened.session_id] = store
        result = await agent.prompt(opened.session_id, [Block("vraag"), Block()])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(model.ready_calls, 1)
        self.assertEqual(store.messages()[-1]["text"], "hoi")
        await asyncio.sleep(0.2)
        self.assertTrue(model.completed, "the summary runs after the answer, not before it")
        self.assertTrue(store.summary)
        self.assertGreater(store.count(), 40)
        # A second summary is skipped while one is running, and a blank one is not stored.
        agent._summarising = True
        await agent.summarise(store)
        agent._summarising = False
        model.complete_result = "  "
        await agent.summarise(store)
        model.complete_result = ModelError("later")
        store.set("summary_upto", "0")
        await agent.summarise(store)
        # Ready is asked once.
        model.scripts.append([("text", "nog")])
        again = await agent.prompt(opened.session_id, [Block("twee")])
        self.assertEqual(again.stop_reason, "end_turn")
        self.assertEqual(model.ready_calls, 1)

    async def test_compaction_fires_at_the_threshold_and_not_before(self):
        """Should summarise once the stored chat passes SUMMARY_AFTER, and not on the message that lands on it."""
        under = await self._prompt_with_history(SUMMARY_AFTER - 2, "under")
        await under._summary_task
        self.assertEqual(under.model.completed, [])
        self.assertEqual(len(under.store.messages()), SUMMARY_AFTER)
        self.assertEqual(to_summarise(under.store), [])

        over = await self._prompt_with_history(SUMMARY_AFTER - 1, "over")
        await over._summary_task
        self.assertEqual(len(over.model.completed), 1)
        self.assertTrue(over.store.summary)
        self.assertEqual(len(over.store.messages()), SUMMARY_AFTER + 1)

    async def _prompt_filled(self, tokens: int, size: int, reply: str = "ok", usage: bool = True):
        """One answer on a short thread, so only the window can start a summary."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        step = [("text", reply)]
        if usage:
            step.append(("usage", {"prompt_tokens": tokens, "completion_tokens": 1}))
        model = ScriptModel([step])
        model.context_size = size
        agent = LeanAgent("Ada", model, folder=folder, tools=Tools("", workspace=folder))
        agent.conn = Conn()
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(KEEP_TURNS * 2 + 2):
            store.add("user" if number % 2 == 0 else "bot", f"line {number} " + ("x" * 20))
        await agent.prompt(session, [Block("vraag")])
        await agent._summary_task
        agent.store = store
        return agent

    async def test_a_full_window_starts_a_summary_and_a_short_one_does_not(self):
        """Should summarise at FILL_SUMMARISE of the reported window, and not below it."""
        window = 100
        under_tokens = int(FILL_SUMMARISE * window) - 1
        over_tokens = int(FILL_SUMMARISE * window)
        under = await self._prompt_filled(under_tokens, window)
        self.assertLess(under_tokens / window, FILL_SUMMARISE)
        self.assertEqual(under.model.completed, [])
        self.assertEqual(under.store.summary, "")
        self.assertLess(len(under.store.messages()), SUMMARY_AFTER)
        over = await self._prompt_filled(over_tokens, window)
        self.assertGreaterEqual(over_tokens / window, FILL_SUMMARISE)
        self.assertEqual(len(over.model.completed), 1)
        self.assertEqual(over.store.summary, "notes")

    async def test_an_unreported_usage_estimates_tokens_as_characters_over_four(self):
        """Should use the character estimate when the model sends no token count."""
        full = await self._prompt_filled(0, 300, usage=False)
        ratio = fill_ratio(0, counted=False, store=full.store, bot="Ada", model=full.model, workspace=full.folder)
        self.assertGreaterEqual(ratio, FILL_SUMMARISE)
        self.assertEqual(len(full.model.completed), 1)
        quiet = await self._prompt_filled(0, 32000, usage=False)
        self.assertLess(fill_ratio(0, counted=False, store=quiet.store, bot="Ada", model=quiet.model,
                                   workspace=quiet.folder), FILL_SUMMARISE)
        self.assertEqual(quiet.model.completed, [])

    async def test_a_fill_summary_never_runs_while_the_answer_streams(self):
        """Should start the model call only between answers, and store it once the stream has stopped."""
        gate = threading.Event()
        release_stream = threading.Event()
        order = []
        agent_box = []
        self.addCleanup(gate.set)
        self.addCleanup(release_stream.set)

        class Gated(ScriptModel):
            def complete(self, messages):
                order.append(("summary", agent_box[0]._streaming))
                if not gate.wait(5):
                    raise TimeoutError("summary gate")
                return super().complete(messages)

        def slow(stop):
            yield ("text", "tweede")
            if not release_stream.wait(5):
                raise TimeoutError("stream")

        model = Gated([[("text", "eerste"), ("usage", {"prompt_tokens": 80, "completion_tokens": 1})], slow])
        model.context_size = 100
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        agent_box.append(agent)
        agent.conn = Conn()
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(KEEP_TURNS * 2 + 2):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        first = await agent.prompt(session, [Block("een")])
        self.assertEqual(first.stop_reason, "end_turn")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and ("summary", False) not in order:
            await asyncio.sleep(0.01)
        self.assertIn(("summary", False), order)
        self.assertNotIn(("summary", True), order)
        with mock.patch("harness.agent.context.SUMMARY_WAIT_S", 0.05):
            started = time.monotonic()
            second = asyncio.create_task(agent.prompt(session, [Block("twee")]))
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and not agent._streaming:
                await asyncio.sleep(0.01)
        self.assertTrue(agent._streaming)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(store.summary, "")
        release_stream.set()
        result = await asyncio.wait_for(second, timeout=3)
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(store.summary, "")
        self.assertFalse(agent._streaming)
        gate.set()
        await asyncio.wait_for(agent._summary_task, timeout=2)
        self.assertEqual(store.summary, "notes")
        self.assertNotIn(("summary", True), order)

    async def test_the_next_send_does_not_wait_when_the_summary_already_finished(self):
        """Should build the next request at once when the background summary is done."""
        sent = []
        model = ScriptModel([[("text", "eerste"), ("usage", {"prompt_tokens": 80, "completion_tokens": 1})],
                             [("text", "tweede")]])
        model.context_size = 100

        def stream(messages, tools=None, stop=None, opened=None):
            sent.append(messages)
            return ScriptModel.stream(model, messages, tools, stop, opened)

        model.stream = stream
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        agent.conn = Conn()
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(KEEP_TURNS * 2 + 2):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        await agent.prompt(session, [Block("een")])
        await agent._summary_task
        self.assertEqual(store.summary, "notes")
        with mock.patch("harness.agent.context.SUMMARY_WAIT_S", 5):
            started = time.monotonic()
            result = await agent.prompt(session, [Block("twee")])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertLess(time.monotonic() - started, 2)
        blob = " ".join(message.get("content") or "" for message in sent[-1])
        self.assertIn("notes", blob)

    async def test_compaction_never_runs_while_an_answer_streams(self):
        """Should finish folding older turns before the next answer streams, never during it."""
        gate = threading.Event()
        order = []
        agent_box = []

        class Gated(ScriptModel):
            def stream(self, messages, tools=None, stop=None, opened=None):
                order.append(("stream", agent_box[0]._streaming))
                yield from super().stream(messages, tools, stop, opened)

            def complete(self, messages):
                order.append(("summary", agent_box[0]._streaming))
                self.assert_wait(gate)
                return super().complete(messages)

            @staticmethod
            def assert_wait(flag):
                if not flag.wait(5):
                    raise TimeoutError("summary gate")

        model = Gated([[("text", "eerste")], [("text", "tweede")]])
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        agent_box.append(agent)
        conn = Conn()
        agent.on_connect(conn)
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(SUMMARY_AFTER - 1):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        first = await agent.prompt(session, [Block("een")])
        self.assertEqual(first.stop_reason, "end_turn")
        self.assertFalse(agent._streaming)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and ("summary", False) not in order:
            await asyncio.sleep(0.01)
        self.assertIn(("summary", False), order)
        second = asyncio.create_task(agent.prompt(session, [Block("twee")]))
        await asyncio.sleep(0.15)
        self.assertEqual([item for item in order if item[0] == "stream"], [("stream", True)])
        gate.set()
        result = await asyncio.wait_for(second, timeout=3)
        self.assertEqual(result.stop_reason, "end_turn")
        summary_at = order.index(("summary", False))
        second_stream = order.index(("stream", True), summary_at)
        self.assertGreater(second_stream, summary_at)
        kinds = []
        for _sid, update in conn.updates:
            name = getattr(update, "session_update", "")
            if name == "agent_message_chunk":
                kinds.append("text")
            elif name == "usage_update" and (getattr(update, "field_meta", None) or {}).get("compacted"):
                kinds.append("compacted")
        self.assertEqual(kinds[:3], ["text", "compacted", "text"])

    async def test_a_slow_summary_does_not_block_the_next_send_past_the_timeout(self):
        """Should send once SUMMARY_WAIT_S passes, keep the summary off the streaming answer, and apply it before a later turn."""
        summary_gate = threading.Event()
        release_stream = threading.Event()
        returned = threading.Event()
        self.addCleanup(summary_gate.set)
        self.addCleanup(release_stream.set)
        text_seen = threading.Event()
        sent = []

        def slow_step(stop):
            yield ("text", "tweede")
            text_seen.set()
            if not release_stream.wait(5):
                raise TimeoutError("stream")

        model = ScriptModel([[("text", "eerste")], slow_step, [("text", "derde")]])

        def complete(messages):
            model.completed.append(messages)
            if not summary_gate.wait(5):
                raise TimeoutError("summary")
            returned.set()
            return "folded notes"

        model.complete = complete

        def stream(messages, tools=None, stop=None, opened=None):
            sent.append(messages)
            return ScriptModel.stream(model, messages, tools, stop, opened)

        model.stream = stream
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        conn = Conn()
        agent.on_connect(conn)
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(SUMMARY_AFTER - 1):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        first = await agent.prompt(session, [Block("een")])
        self.assertEqual(first.stop_reason, "end_turn")
        self.assertEqual(store.summary, "")

        def compacted():
            return sum(1 for _sid, update in conn.updates
                       if getattr(update, "session_update", "") == "usage_update"
                       and (getattr(update, "field_meta", None) or {}).get("compacted"))

        with mock.patch("harness.agent.context.SUMMARY_WAIT_S", 0.05):
            started = time.monotonic()
            second = asyncio.create_task(agent.prompt(session, [Block("twee")]))
            saw_text = await asyncio.to_thread(text_seen.wait, 2)
        self.assertTrue(saw_text)
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(summary_gate.is_set())
        self.assertEqual(store.summary, "")
        during = compacted()
        summary_gate.set()
        self.assertTrue(await asyncio.to_thread(returned.wait, 2))
        await asyncio.sleep(0.05)
        self.assertTrue(agent._streaming)
        self.assertEqual(store.summary, "")
        self.assertEqual(compacted(), during)
        release_stream.set()
        result = await asyncio.wait_for(second, timeout=3)
        self.assertEqual(result.stop_reason, "end_turn")
        await asyncio.wait_for(agent._summary_task, timeout=2)
        self.assertEqual(store.summary, "folded notes")
        self.assertGreater(compacted(), during)
        self.assertFalse(agent._streaming)
        await agent.prompt(session, [Block("drie")])
        blob = " ".join(message.get("content") or "" for message in sent[-1])
        self.assertIn("folded notes", blob)

    async def _prompt_with_history(self, seeded: int, reply: str):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model = ScriptModel([[("text", reply)]])
        agent = LeanAgent("Ada", model, folder=folder, tools=Tools("", workspace=folder))
        agent.conn = Conn()
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        for number in range(seeded):
            store.add("user" if number % 2 == 0 else "bot", f"line {number}")
        await agent.prompt(session, [Block("vraag")])
        agent.model = model
        agent.store = store
        return agent

    async def test_tools_a_cancel_and_a_refusal(self):
        """Should run a tool step, stop a live stream, and report a model error."""
        target = os.path.join(self.folder, "note.txt")

        async def async_tool(arguments):
            return "async " + arguments.get("text", "")

        def wait_then_fail(stop):
            stop.wait(2)
            raise RuntimeError("closed")
            yield  # pragma: no cover - makes this a generator

        model = ScriptModel([
            [("thought", "even "), ("text", "prima")],
            [("tool_calls", [call("missing", {}),
                              call("read_file", "not-json", "2"),
                              call("write_file", {"path": target, "content": "x"}, "3"),
                              call("read_file", {"path": os.path.join(self.folder, "nope")}, "4"),
                              call("echo_async", {"text": "ja"}, "5"),
                              call("pin_fact", {"fact": "houdt van thee"}, "6"),
                              call("pin_fact", {"fact": "houdt van thee"}, "7"),
                              call("pin_fact", {}, "8")])],
            [("text", "na tools")],
            ModelError("HTTP 401: no"),
            wait_then_fail,
        ])
        model.reply = Reply(broken=True)
        tools = Tools("", workspace=self.folder)
        tools.add(Tool("echo_async", "echo", {"type": "object"}, async_tool))
        agent = LeanAgent("Ada", model, folder=self.folder, tools=tools)
        agent.conn = Conn(allow=False)
        session = (await agent.new_session(".")).session_id
        store = agent.stores[session]
        store.add("user", "oud")
        store.add("tool", "read_file: the file says hoi")
        store.add("tool", "read_file: declined by the user")
        store.add("bot", "eerder")
        replayed = []
        agent.conn.updates.clear()
        await agent.load_session(".", session)
        self.assertTrue(any(True for _sid, update in agent.conn.updates))
        # A tool line that is not a decline stays out of the bubble; the decline is said.
        kinds = [getattr(update, "session_update", "") for _sid, update in agent.conn.updates]
        said = " ".join(getattr(getattr(update, "content", None), "text", "") or ""
                        for _sid, update in agent.conn.updates)
        self.assertIn("user_message_chunk", kinds)
        self.assertIn("agent_message_chunk", kinds)
        self.assertIn("declined", said)
        self.assertNotIn("the file says hoi", said)

        thought = await agent.prompt(session, [Block("denk")])
        self.assertEqual(thought.stop_reason, "end_turn")
        tools_turn = await agent.prompt(session, [Block("gereedschap")])
        self.assertEqual(tools_turn.stop_reason, "end_turn")
        self.assertEqual(store.get("facts"), "houdt van thee")
        self.assertFalse(os.path.exists(target), "a declined write does not touch the disk")
        refused = await agent.prompt(session, [Block("kapot")])
        self.assertEqual(refused.stop_reason, "refusal")
        self.assertIn("401", refused.field_meta["error"])

        await agent.cancel(session)  # no turn running: dropped
        running = asyncio.create_task(agent.prompt(session, [Block("wacht")]))
        await asyncio.sleep(0.05)
        await agent.cancel(session)
        cancelled = await asyncio.wait_for(running, timeout=2)
        self.assertEqual(cancelled.stop_reason, "cancelled")
        self.assertTrue(model.reply.closed)
        model.scripts.append(RuntimeError("down"))
        broken = await agent.prompt(session, [Block("stream")])
        self.assertEqual(broken.stop_reason, "refusal")
        self.assertIn("RuntimeError: down", broken.field_meta["error"])

        # No connection: a write is declined and usage is skipped.
        agent.conn = None
        model.scripts.append([("tool_calls", [call("write_file", {"path": target, "content": "y"})])])
        model.scripts.append([("text", "")])
        quiet = await agent.prompt(session, [Block("zonder verbinding")])
        self.assertEqual(quiet.stop_reason, "end_turn")
        await agent._chunk(session, "agent", "")
        await agent._usage(session, store)

    async def test_a_model_without_ready_still_answers(self):
        """Should skip the probe when the model has no ready method."""
        class NoReady:
            """A model that has no ready() probe."""

            model = "script"
            context_size = 0

            def stream(self, messages, tools=None, stop=None, opened=None):
                yield "usage", {"prompt_tokens": 0, "completion_tokens": 0}
                yield "text", "x"

            def complete(self, messages):
                return ""

        model = NoReady()
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        session = (await agent.new_session(".")).session_id
        result = await agent.prompt(session, [Block("hoi")])
        self.assertEqual(result.stop_reason, "end_turn")
        usage = [json.loads(line) for line in Path(os.path.join(self.folder, "usage.jsonl")).read_text().splitlines()]
        self.assertTrue(usage[-1]["estimated"])

    async def test_a_step_limit_stops_the_loop(self):
        """Should end a tool loop that never settles, at HARNESS_MAX_STEPS."""
        os.environ["HARNESS_MAX_STEPS"] = "6"
        self.addCleanup(os.environ.pop, "HARNESS_MAX_STEPS", None)
        model = ScriptModel([[("tool_calls", [call("pin_fact", {"fact": f"n{n}"})])] for n in range(6)])
        agent = LeanAgent("Ada", model, folder=self.folder, tools=Tools("", workspace=self.folder))
        session = (await agent.new_session(".")).session_id
        result = await agent.prompt(session, [Block("loop")])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(len(model.scripts), 0)

    async def test_a_broken_mcp_command_does_not_take_the_turn_down(self):
        """Should remember that the MCP server failed and still answer."""
        model = ScriptModel([[("text", "toch")]])
        tools = Tools("this-command-does-not-exist-xyz")
        agent = LeanAgent("Ada", model, folder=self.folder, tools=tools)
        session = (await agent.new_session(".")).session_id
        result = await agent.prompt(session, [Block("hoi")])
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertTrue(tools.problems)

    async def test_an_mcp_server_is_started_once_and_its_tools_run(self):
        """Should publish the fake server's tools and refuse an error result."""
        tools = Tools(MCP_SERVER, {"echo"})
        await tools.start()
        echo = tools.find("echo")
        self.assertFalse(echo.writes)
        self.assertTrue(tools.find("write_note").writes)
        self.assertEqual(await echo.run({"text": "hoi"}), "echo: hoi")
        await tools.start()  # already connected: nothing starts again
        self.assertTrue(tools.specs())
        await tools.close()
        self.assertIsNone(tools._session)

        class Session:
            async def call_tool(self, name, arguments):
                class Part:
                    text = ""

                class Result:
                    content = [Part()]
                    isError = True

                return Result()

        with self.assertRaises(ToolError):
            await Tools._caller("x", Session())({})


class DirectModels(unittest.TestCase):
    """Should read a local chat server and the Anthropic shape without a real model."""

    def serve(self, chunks: list[bytes], status: int = 200):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                seen.append(json.loads(self.rfile.read(length) or b"{}"))
                body = b"".join(chunks)
                self.send_response(status)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f"http://127.0.0.1:{server.server_port}", seen

    def test_a_chat_stream_joins_tool_calls_and_a_complete_reads_the_message(self):
        """Should yield thought, text, usage and one joined tool call, then a whole answer."""
        sse = "\n".join([
            ": keep-alive",
            'data: {"choices":[{"delta":{"reasoning_content":"denk"}}]}',
            'data: {"choices":[{"delta":{"content":"hoi"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"read_file","arguments":"{\\"path\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"a\\"}"}}]}}]}',
            'data: {"usage":{"prompt_tokens":3},"choices":[]}',
            "data: [DONE]",
            "",
        ]).encode()
        base, seen = self.serve([sse])
        model = ChatCompletions(base + "/v1", "local", api_key="k")
        opened = []
        events = list(model.stream([{"role": "user", "content": "lees"}], tools=[{"type": "function"}],
                                    opened=opened.append))
        self.assertIn(("thought", "denk"), events)
        self.assertIn(("text", "hoi"), events)
        calls = next(value for kind, value in events if kind == "tool_calls")
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a"})
        self.assertTrue(seen[0]["stream"])
        self.assertIn("tools", seen[0])
        self.assertEqual(opened[0].status, 200)

    def test_complete_and_the_error_paths(self):
        """Should return the message, an empty completion, and both HTTP and a closed port."""
        body = json.dumps({"choices": [{"message": {"content": "klaar"}}]}).encode()
        base, _seen = self.serve([body])
        model = ChatCompletions(base + "/v1", "local")
        self.assertEqual(model.complete([{"role": "user", "content": "x"}]), "klaar")
        empty, _seen = self.serve([b'{"choices": []}'])
        self.assertEqual(ChatCompletions(empty + "/v1", "local").complete([{"role": "user", "content": "x"}]), "")
        denied, _seen = self.serve([b'{"error":"no"}'], status=401)
        with self.assertRaises(ModelError):
            ChatCompletions(denied + "/v1", "local").complete([{"role": "user", "content": "x"}])
        with self.assertRaises(ModelError):
            list(ChatCompletions(denied + "/v1", "local").stream([{"role": "user", "content": "x"}]))
        missing = ChatCompletions("http://127.0.0.1:1/v1", "local", timeout=0.5)
        with self.assertRaises(ModelError):
            missing.complete([{"role": "user", "content": "x"}])
        with self.assertRaises(ModelError):
            list(missing.stream([{"role": "user", "content": "x"}]))
        stop = threading.Event()
        stop.set()
        base, _seen = self.serve([b'data: {"choices":[{"delta":{"content":"nooit"}}]}\n\n'])
        opened = []
        events = list(ChatCompletions(base + "/v1", "local").stream(
            [{"role": "user", "content": "x"}], stop=stop, opened=opened.append))
        self.assertEqual(events, [])
        self.assertEqual(len(opened), 1)

    def test_the_fake_model_server_is_read_in_this_process(self):
        """Should exercise the same adapter the subprocess tests use, here where coverage can see it."""
        server = FakeModel("Hallo daar.", script=[{"tool_calls": [{"name": "read_file", "arguments": {"path": "a"}}]},
                                                   "Klaar."])
        self.addCleanup(server.close)
        model = ChatCompletions(server.base_url, "fake-model", api_key="sk")
        first = list(model.stream([{"role": "user", "content": "lees"}], tools=[{"type": "function"}]))
        self.assertTrue(any(kind == "tool_calls" for kind, _value in first))
        second = "".join(value for kind, value in model.stream([{"role": "user", "content": "en"}]) if kind == "text")
        self.assertIn("Klaar", second)
        self.assertIn("Hallo", model.complete([{"role": "user", "content": "som"}]))

    def test_anthropic_edges(self):
        """Should merge two user turns, ignore bad tool JSON, stop, think, and complete."""
        server = FakeAnthropic([{"text": "Hallo."}])
        self.addCleanup(server.close)
        model = AnthropicMessages("claude-test", "sk", server.base_url)
        messages = [{"role": "system", "content": "s"},
                    {"role": "user", "content": "een"},
                    {"role": "user", "content": "twee"},
                    {"role": "assistant", "content": "",
                     "tool_calls": [{"id": "c", "function": {"name": "t", "arguments": "not-json"}}]}]
        self.assertEqual(_anthropic_content(messages[-1])[-1]["input"], {})
        list(model.stream(messages))
        sent = server.requests[-1]["messages"]
        self.assertEqual(sent[0]["role"], "user")
        self.assertGreaterEqual(len(sent[0]["content"]), 2, "two user messages of the same role are one turn")
        self.assertIn("Hallo", model.complete([{"role": "user", "content": "som"}]))
        stop = threading.Event()
        stop.set()
        opened = []
        self.assertEqual(list(model.stream([{"role": "user", "content": "x"}], stop=stop, opened=opened.append)), [])
        self.assertEqual(len(opened), 1)
        thinking = "\n".join([
            'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hmm"}}',
            'data: {"type":"message_delta","usage":{"output_tokens":1}}',
            "",
        ]).encode()
        base, _seen = DirectModels.serve(self, [thinking])
        events = list(AnthropicMessages("claude-test", "", base).stream([{"role": "user", "content": "x"}]))
        self.assertIn(("thought", "hmm"), events)
        denied, _seen = DirectModels.serve(self, [b'{"error":"no"}'], status=401)
        broken = AnthropicMessages("claude-test", "sk", denied)
        with self.assertRaises(ModelError):
            list(broken.stream([{"role": "user", "content": "x"}]))
        with self.assertRaises(ModelError):
            broken.complete([{"role": "user", "content": "x"}])
        offline = AnthropicMessages("claude-test", "", "http://127.0.0.1:1", timeout=0.5)
        with self.assertRaises(ModelError):
            list(offline.stream([{"role": "user", "content": "x"}]))
        with self.assertRaises(ModelError):
            offline.complete([{"role": "user", "content": "x"}])
        self.assertIsInstance(from_environment({"HARNESS_MODEL_PROVIDER": "chat", "HARNESS_MODEL": "local"}),
                              ChatCompletions)


class DirectTools(unittest.TestCase):
    """Should cover the file tools' refusals and the cuts."""

    def test_reads_lists_and_writes_including_the_failures(self):
        """Should cut a long file, refuse a private name, and report a path it cannot use."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "note.txt")
        self.assertIn("Wrote", write_file(path, "abc"))
        self.assertEqual(read_file(path), "abc")
        self.assertEqual(read_file(path, limit=2), "ab\n…[cut]")
        os.remove(path)
        self.assertEqual(list_dir(folder), "(empty)")
        nested = os.path.join(folder, "sub", "a.txt")
        write_file(nested, "z")
        self.assertIn("a.txt", list_dir(os.path.join(folder, "sub")))
        secret = os.path.join(folder, ".env")
        with self.assertRaises(ToolError):
            read_file(secret)
        with self.assertRaises(ToolError):
            read_file(os.path.join(folder, ".ssh", "id"))
        with self.assertRaises(ToolError):
            read_file(os.path.join(folder, "missing"))
        with self.assertRaises(ToolError):
            list_dir(os.path.join(folder, "missing"))
        write_file(path, "file")
        with self.assertRaises(ToolError):
            write_file(os.path.join(path, "child"), "no")
        self.assertEqual(Tool("n", "d", {}, lambda arguments: "").spec()["function"]["name"], "n")

    def test_context_drops_what_does_not_fit_and_folds_a_tool_line(self):
        """Should stop when the budget is spent and attach a tool line to the next user turn."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.assertEqual(to_summarise(store), [])
        store.add("tool", "read_file: ok")
        store.add("user", "en nu")
        sent = build(store, "Ada")
        self.assertIn("Tool outcomes:", sent[-1]["content"])
        store.add("tool", "list_dir: ok")
        tail = build(store, "Ada")
        self.assertTrue(any(message["content"].startswith("Tool outcomes:") for message in tail))
        huge = SessionStore(folder + "-huge")
        self.addCleanup(shutil.rmtree, folder + "-huge", True)
        huge.add("user", "x" * (BUDGET_CHARS + 10))
        built = build(huge, "Ada")
        self.assertTrue(all(message["role"] == "system" for message in built))
        self.assertEqual(store.count(), 3)


class DirectClient(unittest.IsolatedAsyncioTestCase):
    """Should cover the ACP client branches that a live agent does not hit."""

    async def test_load_prompt_and_unknown_updates(self):
        """Should keep a loaded session, time the startup, and ignore an unknown update."""
        client = AcpClient("unused")
        self.assertEqual(client.startup_ms, 0)
        self.assertEqual(_text_of([type("P", (), {"text": "a"})(), type("P", (), {})()]), "a")

        class Info:
            protocol_version = 1

            class agent_info:
                name = "lean"
                version = "0"

        class Loaded:
            session_id = "kept"

        class Fresh:
            session_id = "new"

        class Conn:
            def __init__(self):
                self.loaded = 0

            async def initialize(self, **kwargs):
                return Info()

            async def load_session(self, **kwargs):
                self.loaded += 1
                if kwargs.get("session_id") == "missing":
                    raise RuntimeError("no such session")
                return Loaded()

            async def new_session(self, **kwargs):
                return Fresh()

            async def prompt(self, **kwargs):
                raise RuntimeError("gone")

            async def cancel(self, **kwargs):
                self.cancelled = True

        client.conn = Conn()
        info = await client.start(load="kept")
        self.assertEqual(info["session"], "kept")
        self.assertGreaterEqual(client.startup_ms, 0)
        self.assertEqual(Turn().first_update_ms, 0)
        failed = await client.prompt("hoi")
        self.assertEqual(failed.stop_reason, "error")
        self.assertIn("RuntimeError", failed.error)
        again = AcpClient("unused")
        again.conn = Conn()
        self.assertEqual((await again.start(load="missing"))["session"], "new")

        seen = []
        client.on_update = seen.append
        client._turn = Turn(started=1)

        class Update:
            def __init__(self, kind, content="", title="", status=""):
                self.session_update = kind
                self.content = content
                self.title = title
                self.status = status
                self.field_meta = {"compacted": True}
                self.used = 1
                self.size = 2
                self.cost = None

        await client.session_update("s", Update("agent_message_chunk", [type("P", (), {"text": "hoi"})()]))
        await client.session_update("s", Update("user_message_chunk", type("P", (), {"text": "jij"})()))
        await client.session_update("s", Update("tool_call", title="read", status="done"))
        await client.session_update("s", Update("usage_update"))
        await client.session_update("s", Update("nope"))
        self.assertEqual(client._turn.updates[0].text, "hoi")
        self.assertEqual(client._turn.updates[0].kind, "text")
        self.assertTrue(client._turn.first_update)
        self.assertEqual(len(seen), 4)

        async def allow(_title, _options=()):
            return True

        client.allow = allow

        class Option:
            def __init__(self, option_id, kind):
                self.option_id = option_id
                self.kind = kind

        reply = await client.request_permission("s", type("T", (), {"title": "schrijf"})(),
                                                [Option("no", "reject_once"), Option("yes", "allow_once")])
        chosen = getattr(reply.outcome, "option_id", None)
        self.assertEqual(chosen, "yes")
        client.allow = lambda _title, _options=(): False
        declined = await client.request_permission("s", type("T", (), {"title": ""})(), [Option("yes", "allow_once")])
        self.assertEqual(getattr(declined.outcome, "outcome", ""), "cancelled")

        offered = [Option("allow", "allow_once"), Option("allow_always", "allow_always"),
                   Option("decline", "reject_once")]
        client.allow = lambda _title, _options=(): True
        once = await client.request_permission("s", type("T", (), {"title": "shell git"})(), offered)
        self.assertEqual(getattr(once.outcome, "option_id", None), "allow")
        client.allow = lambda _title, _options=(): "allow_always"
        always = await client.request_permission("s", type("T", (), {"title": "shell git"})(), offered)
        self.assertEqual(getattr(always.outcome, "option_id", None), "allow_always")
        missing = await client.request_permission("s", type("T", (), {"title": "shell git"})(),
                                                  [Option("allow", "allow_once"), Option("decline", "reject_once")])
        self.assertEqual(getattr(missing.outcome, "outcome", ""), "cancelled")
        client.allow = lambda _title, _options=(): True
        only_always = await client.request_permission(
            "s", type("T", (), {"title": "shell git"})(), [Option("keep", "allow_always")])
        self.assertEqual(getattr(only_always.outcome, "option_id", None), "keep")


class Entrypoints(unittest.TestCase):
    """Should run the module entry points without a real pipe or a live agent."""

    def test_a_windows_command_keeps_its_backslashes(self):
        """Should leave a Windows path intact. POSIX splitting would delete every backslash."""
        from harness.acp_client import split_command
        with mock.patch("harness.acp_client.os.name", "nt"):
            self.assertEqual(split_command(r"C:\Python\python.exe C:\repo\agent.py"),
                             [r"C:\Python\python.exe", r"C:\repo\agent.py"])

    def test_the_agent_module_swallows_a_closed_pipe(self):
        """Should return 0 when the client hangs up or the user hits Ctrl+C."""
        import harness.agent.__main__ as entry
        with mock.patch.object(entry.asyncio, "run", side_effect=BrokenPipeError):
            self.assertEqual(entry.main(), 0)
        with mock.patch.object(entry.asyncio, "run", side_effect=KeyboardInterrupt):
            self.assertEqual(entry.main(), 0)
        def abandon(coro, *args, **kwargs):
            coro.close()
            raise KeyboardInterrupt

        with mock.patch("asyncio.run", abandon):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(entry.__file__, run_name="__main__")
        self.assertEqual(raised.exception.code, 0)

    async def _serve(self):
        import harness.agent.__main__ as entry

        async def streams():
            return mock.Mock(at_eof=lambda: True), None

        with mock.patch.object(entry, "stdio_streams", streams), \
                mock.patch.object(entry.os, "_exit") as leave, \
                mock.patch.object(entry, "AgentSideConnection") as side, \
                mock.patch.object(entry, "from_environment", return_value=mock.Mock(model="local")), \
                mock.patch.dict(os.environ, {"HARNESS_BOT": "Ada"}, clear=False):
            await entry.serve()
        agent = side.call_args.args[0](None)
        self.assertEqual(agent.bot, "Ada")
        leave.assert_called_once_with(0)

    def test_serve_waits_on_the_connection(self):
        """Should build the named bot and wait until the client closes."""
        asyncio.run(self._serve())

    def test_the_spike_prints_a_turn_and_a_failure(self):
        """Should return the stop codes the spike documents."""
        import harness.spike as spike

        class Client:
            startup_ms = 4

            def __init__(self, *args, **kwargs):
                self.allow = kwargs.get("allow")
                self.mode = Client.mode

            async def __aenter__(self):
                if self.mode == "explode":
                    raise RuntimeError("down")
                return self

            async def __aexit__(self, *exc):
                return None

            async def start(self):
                return {"name": "lean", "version": "0", "protocol": 1, "session": "s"}

            async def prompt(self, text):
                if self.mode == "slow":
                    await asyncio.sleep(0.05)
                error = "no" if self.mode == "refused" else ""
                reason = "error" if self.mode == "error" else "end_turn"
                return Turn(stop_reason=reason, error=error, started=0, ended=0.01, first_update=0.01)

            async def cancel(self):
                self.cancelled = True

        Client.mode = "ok"
        with mock.patch.object(spike, "AcpClient", Client):
            self.assertEqual(asyncio.run(spike.run("agent", "hoi", None, True, 0)), 0)
            Client.mode = "refused"
            self.assertEqual(asyncio.run(spike.run("agent", "hoi", None, False, 0)), 1)
            Client.mode = "error"
            self.assertEqual(asyncio.run(spike.run("agent", "hoi", None, False, 0)), 1)
            Client.mode = "explode"
            self.assertEqual(asyncio.run(spike.run("agent", "hoi", None, False, 0)), 2)
            Client.mode = "slow"
            self.assertEqual(asyncio.run(spike.run("agent --flag", "hoi", "/tmp", False, 0.01)), 0)
            Client.mode = "ok"
            self.assertEqual(spike.main(["--agent", "python -m x", "--cwd", "/tmp", "--ask", "hoi"]), 0)
        with mock.patch.object(sys, "argv", ["spike", "--agent", "python -m x", "hoi"]), \
                mock.patch("asyncio.run", return_value=0):
            with self.assertRaises(SystemExit) as raised:
                runpy.run_path(spike.__file__, run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
