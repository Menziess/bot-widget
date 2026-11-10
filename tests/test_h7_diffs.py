"""H7: diffs in the bubble — always / ask / never with apply / reject / undo.

Tests for the diff_edit_mode feature:
  - ask:   show diff, wait for Apply/Reject
  - always: show diff, auto-apply, still record for undo
  - never: show diff as proposal, don't apply
  - undo_last: LIFO undo stack
  - hard denies (secrets, out-of-workspace) still block even in always mode
"""

import json
import os
import shutil
import tempfile
import unittest

from harness.agent.agent import LeanAgent
from harness.agent.tools import Tool, Tools
from harness.agent.workspace import EditStore, workspace_builtins
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Conn:
    """Minimal ACP connection that records permission requests."""

    def __init__(self, auto_allow=False, diff_mode="ask"):
        self.auto_allow = auto_allow
        self.diff_mode = diff_mode
        self.permission_requests = []
        self.updates = []
        self._responses = []  # list of (outcome, option_id) — set by tests

    async def session_update(self, session_id, update):
        self.updates.append((session_id, update))

    async def request_permission(self, **kwargs):
        self.permission_requests.append(kwargs)
        # If test set explicit responses, use them
        if self._responses:
            outcome, option_id = self._responses.pop(0)
            class Outcome:
                pass
            o = Outcome()
            o.outcome = outcome
            o.option_id = option_id
            class Response:
                pass
            r = Response()
            r.outcome = o
            return r
        # Default behavior
        class Outcome:
            pass
        o = Outcome()
        o.outcome = "selected" if self.auto_allow else "cancelled"
        o.option_id = "allow" if self.auto_allow else ""
        class Response:
            pass
        r = Response()
        r.outcome = o
        return r


class ScriptModel:
    """Yields scripted stream events."""

    def __init__(self, scripts=()):
        self.model = "script"
        self.context_size = 4096
        self.scripts = list(scripts)

    def ready(self):
        pass

    def stream(self, messages, tools=None, stop=None, opened=None):
        step = self.scripts.pop(0)
        if callable(step):
            if opened is not None:
                opened("")
            yield from step(stop) if stop else iter(())
            return
        for event in step:
            if stop is not None and stop.is_set():
                return
            yield event

    def complete(self, messages):
        return "notes"


class H7DiffAsk(unittest.IsolatedAsyncioTestCase):
    """ask mode: show diff, wait for Apply/Reject."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_ask_mode_shows_diff_and_applies(self):
        """In ask mode, the diff is shown and Apply applies the write."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "ask"
        try:
            agent = LeanAgent("test-ask", ScriptModel(), folder=self.folder)
            conn = _Conn(auto_allow=True, diff_mode="ask")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            test_path = os.path.join(self.workspace, "h7_test.txt")
            call = {
                "id": "1",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_test.txt", "content": "hello h7\n"})
                }
            }

            result = await agent._use_tool(session_id, store, call)
            self.assertIn("Wrote", result)
            # Should have recorded one permission request (the diff)
            self.assertEqual(len(conn.permission_requests), 1)
            req = conn.permission_requests[0]
            # ToolCallUpdate is an object, not a dict
            tool_call = req.get("tool_call", {})
            field_meta = getattr(tool_call, "field_meta", None) or {}
            self.assertIn("diff", field_meta)
            # Verify file was actually written
            self.assertTrue(os.path.exists(test_path))
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)

    async def test_ask_mode_rejects(self):
        """In ask mode, Reject means the file is NOT written."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "ask"
        try:
            agent = LeanAgent("test-ask-reject", ScriptModel(), folder=self.folder)
            conn = _Conn(auto_allow=False, diff_mode="ask")
            conn._responses.append(("selected", "decline"))  # user rejects
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            test_path = os.path.join(self.workspace, "h7_reject.txt")
            call = {
                "id": "2",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_reject.txt", "content": "should not exist\n"})
                }
            }
            result = await agent._use_tool(session_id, store, call)
            self.assertIn("declined", result.lower())
            self.assertFalse(os.path.exists(test_path))
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7DiffAlways(unittest.IsolatedAsyncioTestCase):
    """always mode: show diff, auto-apply, still record for undo."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_always_mode_auto_applies(self):
        """In always mode, the write is applied without user interaction."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "always"
        try:
            agent = LeanAgent("test-always", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="always")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            test_path = os.path.join(self.workspace, "h7_always.txt")
            call = {
                "id": "3",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_always.txt", "content": "auto applied\n"})
                }
            }
            result = await agent._use_tool(session_id, store, call)
            self.assertIn("Wrote", result)
            self.assertTrue(os.path.exists(test_path))
            with open(test_path) as f:
                self.assertEqual(f.read(), "auto applied\n")
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)

    async def test_always_mode_records_for_undo(self):
        """In always mode, the write is recorded on the undo stack."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "always"
        try:
            agent = LeanAgent("test-always-undo", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="always")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)
            agent.tools._add_workspace_tools()

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            edit = agent.tools._edit

            # First write
            call1 = {
                "id": "4",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_undo.txt", "content": "version 1\n"})
                }
            }
            await agent._use_tool(session_id, store, call1)
            # Second write (overwrites)
            call2 = {
                "id": "5",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_undo.txt", "content": "version 2\n"})
                }
            }
            await agent._use_tool(session_id, store, call2)

            # Verify the stack has entries
            self.assertGreater(len(edit._stack), 0)
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7DiffNever(unittest.IsolatedAsyncioTestCase):
    """never mode: show diff as proposal, don't apply."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_never_mode_no_apply(self):
        """In never mode, the file is NOT written; only a proposal is shown."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "never"
        try:
            agent = LeanAgent("test-never", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="never")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            test_path = os.path.join(self.workspace, "h7_never.txt")
            call = {
                "id": "6",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "h7_never.txt", "content": "proposed only\n"})
                }
            }
            result = await agent._use_tool(session_id, store, call)
            self.assertIn("never", result.lower())
            self.assertFalse(os.path.exists(test_path))
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7UndoStack(unittest.IsolatedAsyncioTestCase):
    """LIFO undo stack: undo_last pops the most recent edit."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_undo_last_lifo(self):
        """undo_last should undo the most recent write first (LIFO).

        Write A v1 → B v1 → A v2.
        Stack: [(a, None, v1), (b, None, v1), (a, v1, v2)]
        First undo_last: pops (a, v1, v2) — has prev_bytes → returns a.txt
        Second undo_last: pops (b, None, v1) — prev is None, skip
        Third undo_last: pops (a, None, v1) — prev is None, skip → None
        """
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "always"
        try:
            agent = LeanAgent("test-undo-lifo", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="always")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)
            agent.tools._add_workspace_tools()

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]
            edit = agent.tools._edit

            # Write file A v1, then B v1, then A v2
            call_a1 = {
                "id": "10",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "a.txt", "content": "A v1\n"})
                }
            }
            call_b = {
                "id": "11",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "b.txt", "content": "B v1\n"})
                }
            }
            call_a2 = {
                "id": "12",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "a.txt", "content": "A v2\n"})
                }
            }
            await agent._use_tool(session_id, store, call_a1)
            await agent._use_tool(session_id, store, call_b)
            await agent._use_tool(session_id, store, call_a2)

            # undo_last pops (a, v1, v2) first — LIFO, has prev_bytes
            result = edit.undo_last()
            self.assertIsNotNone(result)
            self.assertIn("a.txt", result[0])
            # File should be restored to v1
            with open(os.path.join(self.workspace, "a.txt")) as f:
                self.assertEqual(f.read(), "A v1\n")

            # Second undo: pops (b, None, v1) — prev is None, skipped
            result2 = edit.undo_last()
            self.assertIsNone(result2)

            # Third undo: pops (a, None, v1) — prev is None, skipped
            result3 = edit.undo_last()
            self.assertIsNone(result3)
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)

    async def test_undo_last_empty_stack(self):
        """undo_last on empty stack returns None."""
        edit = EditStore()
        result = edit.undo_last()
        self.assertIsNone(result)


class H7HardDenies(unittest.IsolatedAsyncioTestCase):
    """Hard denies (secrets, out-of-workspace) still block even in always mode."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_secret_path_blocked_in_always(self):
        """Writing to a secret path is refused even in always mode."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "always"
        try:
            agent = LeanAgent("test-secret", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="always")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            # .env is a secret path
            call = {
                "id": "20",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": ".env", "content": "secret=leaked\n"})
                }
            }
            result = await agent._use_tool(session_id, store, call)
            self.assertIn("private", result.lower())
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)

    async def test_out_of_workspace_blocked_in_always(self):
        """Writing outside workspace is refused even in always mode."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "always"
        try:
            agent = LeanAgent("test-oow", ScriptModel(), folder=self.folder)
            conn = _Conn(diff_mode="always")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            # Path outside workspace
            call = {
                "id": "21",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "/tmp/escape.txt", "content": "escaped\n"})
                }
            }
            result = await agent._use_tool(session_id, store, call)
            self.assertIn("outside", result.lower())
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7DiffInBubble(unittest.IsolatedAsyncioTestCase):
    """The diff should appear in the bubble via field_meta."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_diff_appears_in_field_meta(self):
        """In ask mode, the permission request should contain the diff in field_meta."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "ask"
        try:
            agent = LeanAgent("test-bubble", ScriptModel(), folder=self.folder)
            conn = _Conn(auto_allow=True, diff_mode="ask")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            call = {
                "id": "30",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "bubble.txt", "content": "new content for bubble\n"})
                }
            }
            await agent._use_tool(session_id, store, call)

            # Check that the permission request had the diff
            self.assertEqual(len(conn.permission_requests), 1)
            req = conn.permission_requests[0]
            # ToolCallUpdate is an object, use getattr
            tool_call = req.get("tool_call", {})
            field_meta = getattr(tool_call, "field_meta", None) or {}
            diff_text = field_meta.get("diff", "")
            self.assertIn("bubble.txt", diff_text)
            self.assertIn("+", diff_text)
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7TitleNotDoubled(unittest.IsolatedAsyncioTestCase):
    """Titles should not be doubled — the diff path uses a clean title."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.workspace = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.workspace, True)

    async def test_title_is_clean(self):
        """The diff title should be 'write_file <path>', not doubled with args."""
        os.environ["HARNESS_WORKSPACE"] = self.workspace
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "ask"
        try:
            agent = LeanAgent("test-title", ScriptModel(), folder=self.folder)
            conn = _Conn(auto_allow=True, diff_mode="ask")
            agent.on_connect(conn)
            tools = workspace_builtins(self.workspace, EditStore())
            agent.tools = Tools("", set(), workspace=self.workspace, permission="ask")
            for t in tools:
                agent.tools.add(t)

            opened = await agent.new_session(cwd=self.workspace)
            session_id = opened.session_id
            store = agent.stores[session_id]

            call = {
                "id": "40",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": "clean.txt", "content": "clean title\n"})
                }
            }
            await agent._use_tool(session_id, store, call)

            # The title in the permission request should be clean
            req = conn.permission_requests[0]
            tool_call = req.get("tool_call", {})
            title = getattr(tool_call, "title", "")
            # Should not contain the arguments dict
            self.assertNotIn("arguments", title.lower())
            self.assertNotIn("json", title.lower())
            self.assertEqual(title, "write_file clean.txt")
        finally:
            os.environ.pop("HARNESS_WORKSPACE", None)
            os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)


class H7DefaultMode(unittest.IsolatedAsyncioTestCase):
    """The default diff_edit_mode should be 'ask'."""

    def test_default_diff_edit_mode_is_ask(self):
        """When HARNESS_DIFF_PERMISSIONS is unset, diff_edit_mode defaults to 'ask'."""
        os.environ.pop("HARNESS_DIFF_PERMISSIONS", None)
        agent = LeanAgent("test-default", ScriptModel(), folder=tempfile.mkdtemp())
        self.assertEqual(agent.diff_edit_mode, "ask")
        shutil.rmtree(agent.folder, True)
