"""Harness action 1: the exact-replace edit tool, alone and through the agent's diff flow."""

import json
import os
import shutil
import tempfile
import unittest

from harness.agent.agent import LeanAgent
from harness.agent.tools import Tools, ToolError
from harness.agent.workspace import EditStore, replace_once, workspace_builtins
from tests.test_h7_diffs import ScriptModel, _Conn


class ReplaceOnce(unittest.TestCase):
    def test_unique_match_is_replaced(self):
        self.assertEqual(replace_once("a\nb\nc\n", "b", "B"), "a\nB\nc\n")

    def test_missing_match_fails_with_closest_lines(self):
        with self.assertRaises(ToolError) as caught:
            replace_once("def run(x):\n    return x\n", "def run(y):", "def go(y):")
        self.assertIn("not found", str(caught.exception))
        self.assertIn("1: def run(x):", str(caught.exception))

    def test_several_matches_need_replace_all(self):
        with self.assertRaises(ToolError) as caught:
            replace_once("x\nx\n", "x", "y")
        self.assertIn("2 places", str(caught.exception))
        self.assertEqual(replace_once("x\nx\n", "x", "y", replace_all=True), "y\ny\n")

    def test_empty_and_identical_are_refused(self):
        with self.assertRaises(ToolError):
            replace_once("abc", "", "x")
        with self.assertRaises(ToolError):
            replace_once("abc", "a", "a")

    def test_whitespace_must_match_exactly(self):
        with self.assertRaises(ToolError):
            replace_once("a  b\n", "a b", "c")


class EditTool(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.tool = {t.name: t for t in workspace_builtins(self.ws, EditStore())}["edit"]

    def test_tool_is_a_write_and_returns_a_diff(self):
        self.assertTrue(self.tool.writes)
        path = os.path.join(self.ws, "f.txt")
        open(path, "w").write("one\ntwo\n")
        out = self.tool.run({"path": "f.txt", "old_string": "two", "new_string": "2"})
        self.assertIn("-two", out)
        self.assertIn("+2", out)
        self.assertEqual(open(path).read(), "one\n2\n")

    def test_secret_files_are_refused(self):
        open(os.path.join(self.ws, ".env"), "w").write("K=v\n")
        with self.assertRaises(ToolError):
            self.tool.run({"path": ".env", "old_string": "v", "new_string": "w"})
        self.assertEqual(open(os.path.join(self.ws, ".env")).read(), "K=v\n")


class EditThroughAgent(unittest.IsolatedAsyncioTestCase):
    async def _agent(self, conn):
        self.folder = tempfile.mkdtemp()
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.ws, True)
        os.environ["HARNESS_DIFF_PERMISSIONS"] = "ask"
        self.addCleanup(os.environ.pop, "HARNESS_DIFF_PERMISSIONS", None)
        agent = LeanAgent("edit", ScriptModel(), folder=self.folder)
        agent.on_connect(conn)
        agent.tools = Tools("", set(), workspace=self.ws, permission="ask")
        agent.tools._edit = EditStore()
        for tool in workspace_builtins(self.ws, agent.tools._edit):
            agent.tools.add(tool)
        opened = await agent.new_session(cwd=self.ws)
        return agent, opened.session_id, agent.stores[opened.session_id]

    def _call(self, **args):
        return {"id": "e1", "function": {"name": "edit", "arguments": json.dumps(args)}}

    async def test_accepted_edit_applies_and_shows_a_diff_once(self):
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn)
        path = os.path.join(self.ws, "a.txt")
        open(path, "w").write("hello\nworld\n")
        result = await agent._use_tool(sid, store, self._call(path="a.txt", old_string="world", new_string="there"))
        self.assertEqual(open(path).read(), "hello\nthere\n")
        self.assertIn("+there", result)
        self.assertEqual(len(conn.permission_requests), 1)
        meta = getattr(conn.permission_requests[0]["tool_call"], "field_meta", None) or {}
        self.assertIn("-world", meta["diff"])
        # undo restores the file
        undo = {t.name: t for t in agent.tools.tools.values()}["undo_last"]
        undo.run({})
        self.assertEqual(open(path).read(), "hello\nworld\n")

    async def test_rejected_edit_changes_nothing(self):
        conn = _Conn(auto_allow=False)
        conn._responses.append(("selected", "decline"))
        agent, sid, store = await self._agent(conn)
        path = os.path.join(self.ws, "a.txt")
        open(path, "w").write("hello\n")
        result = await agent._use_tool(sid, store, self._call(path="a.txt", old_string="hello", new_string="bye"))
        self.assertIn("declined", result)
        self.assertEqual(open(path).read(), "hello\n")

    async def test_a_miss_fails_without_asking(self):
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn)
        open(os.path.join(self.ws, "a.txt"), "w").write("hello\n")
        result = await agent._use_tool(sid, store, self._call(path="a.txt", old_string="nope", new_string="x"))
        self.assertIn("not found", result)
        self.assertEqual(conn.permission_requests, [])


if __name__ == "__main__":
    unittest.main()
