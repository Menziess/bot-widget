"""Approval rules: what an accepted call leaves behind per permission mode, and Copilot-style keys in widget.json."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from harness.agent import tools as agent_tools
from harness.agent.agent import LeanAgent
from harness.agent.tools import Tools
from harness.agent.workspace import ApproveRules, EditStore, check_rules, rule_matches, workspace_builtins
from tests.test_h7_diffs import ScriptModel, _Conn


class Keys(unittest.TestCase):
    def test_a_plain_key_matches_the_start_up_to_a_word_end(self):
        self.assertTrue(rule_matches("shell git status", "shell git status -s"))
        self.assertTrue(rule_matches("mkdir", "mkdir"))
        self.assertFalse(rule_matches("mkdir", "mkdirx"))
        self.assertTrue(rule_matches("write_file /a/b/", "write_file /a/b/sub/c.py"))
        self.assertFalse(rule_matches("write_file /a/b/", "write_file /a/bc/c.py"))

    def test_a_key_in_slashes_is_a_regex_and_i_ignores_case(self):
        self.assertTrue(rule_matches("/^shell git (status|diff)\\b/", "shell git diff HEAD"))
        self.assertFalse(rule_matches("/^shell git (status|diff)\\b/", "shell git push"))
        self.assertTrue(rule_matches("/DANGEROUS/i", "shell run dangerous thing"))
        self.assertFalse(rule_matches("/DANGEROUS/", "shell run dangerous thing"))

    def test_bad_rules_are_named(self):
        self.assertEqual(check_rules({"/^ok/": True, "x": False}), "")
        self.assertIn("true or false", check_rules({"x": "yes"}))
        self.assertIn("regular expression", check_rules({"/(/": True}))
        self.assertIn("object", check_rules(["x"]))


class Decide(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "approved.json")

    def test_false_wins_and_every_part_must_be_covered(self):
        rules = ApproveRules(self.path, {"shell git": True, "shell git push": False, "/rm/": False})
        decide = lambda *texts: rules.decide(list(texts), session=True, saved=True)
        self.assertIs(decide("shell git status"), True)
        self.assertIs(decide("shell git push origin"), False)
        self.assertIs(decide("shell git status", "shell rm -rf x"), False)
        self.assertIsNone(decide("shell git status", "shell npm test"))
        self.assertIsNone(decide())

    def test_a_remembered_prefix_lives_for_the_session_or_in_the_file(self):
        rules = ApproveRules(self.path)
        rules.remember("shell npm test", persist=False)
        self.assertIs(rules.decide(["shell npm test"], session=True, saved=True), True)
        self.assertIsNone(rules.decide(["shell npm test"], session=False, saved=True))
        self.assertIsNone(ApproveRules(self.path).decide(["shell npm test"], session=True, saved=True))
        rules.remember("shell make", persist=True)
        again = ApproveRules(self.path)
        self.assertIs(again.decide(["shell make all"], session=False, saved=True), True)
        self.assertIsNone(again.decide(["shell make all"], session=True, saved=False))


class ThroughAgent(unittest.IsolatedAsyncioTestCase):
    async def _agent(self, conn, folder=None, mode="ask", approve=None):
        self.folder = folder or tempfile.mkdtemp()
        self.ws = getattr(self, "ws", None) or os.path.realpath(tempfile.mkdtemp())
        self.trash = getattr(self, "trash", None) or tempfile.mkdtemp()
        for path in (self.folder, self.ws, self.trash):
            self.addCleanup(shutil.rmtree, path, True)
        patched = mock.patch.dict(os.environ, {"HARNESS_WORKSPACE_PERMISSIONS": mode,
                                               "HARNESS_APPROVE": json.dumps(approve or {})})
        patched.start()
        self.addCleanup(patched.stop)
        trashed = mock.patch.object(agent_tools, "TRASH", self.trash)
        trashed.start()
        self.addCleanup(trashed.stop)
        agent = LeanAgent("ap", ScriptModel(), folder=self.folder)
        agent.on_connect(conn)
        agent.tools = Tools("", set(), workspace=self.ws, permission=mode)
        for tool in workspace_builtins(self.ws, EditStore()):
            agent.tools.add(tool)
        opened = await agent.new_session(cwd=self.ws)
        return agent, opened.session_id, agent.stores[opened.session_id]

    def delete(self, name):
        path = os.path.join(self.ws, name)
        open(path, "w").close()
        return {"id": "d", "function": {"name": "delete_file", "arguments": json.dumps({"path": path})}}

    async def asked(self, mode, approve=None):
        """How many questions two deletes in one folder asked, then one more in a restarted agent."""
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn, mode=mode, approve=approve)
        await agent._use_tool(sid, store, self.delete("a.txt"))
        await agent._use_tool(sid, store, self.delete("b.txt"))
        first = len(conn.permission_requests)
        conn2 = _Conn(auto_allow=True)
        agent2, sid2, store2 = await self._agent(conn2, folder=self.folder, mode=mode, approve=approve)
        await agent2._use_tool(sid2, store2, self.delete("c.txt"))
        return first, len(conn2.permission_requests)

    async def test_the_modes_differ_in_how_far_an_accept_reaches(self):
        self.assertEqual(await self.asked("ask"), (2, 1))
        self.assertEqual(await self.asked("allow_session"), (1, 1))
        self.assertEqual(await self.asked("allow"), (1, 0))

    async def test_an_accept_covers_the_tool_in_that_folder_and_below(self):
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn, mode="allow_session")
        await agent._use_tool(sid, store, self.delete("a.txt"))
        os.mkdir(os.path.join(self.ws, "sub"))
        await agent._use_tool(sid, store, self.delete("sub/x.txt"))
        self.assertEqual(len(conn.permission_requests), 1)
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        open(os.path.join(elsewhere, "y.txt"), "w").close()
        other = {"id": "d", "function": {"name": "delete_file",
                                         "arguments": json.dumps({"path": os.path.join(elsewhere, "y.txt")})}}
        await agent._use_tool(sid, store, other)
        self.assertEqual(len(conn.permission_requests), 2)

    async def test_a_key_in_the_config_approves_and_a_false_one_asks_even_after_an_accept(self):
        approve = {"/^delete_file .*\\.tmp$/": True, "delete_file /nope/": False}
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn, mode="ask", approve=approve)
        await agent._use_tool(sid, store, self.delete("x.tmp"))
        self.assertEqual(conn.permission_requests, [])
        await agent._use_tool(sid, store, self.delete("x.txt"))
        self.assertEqual(len(conn.permission_requests), 1)

        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn, mode="allow_session", approve={"delete_file /": False})
        await agent._use_tool(sid, store, self.delete("a.txt"))
        await agent._use_tool(sid, store, self.delete("b.txt"))
        self.assertEqual(len(conn.permission_requests), 2, "a deny rule is never skipped by what was accepted")

    async def test_shell_keeps_its_command_prefix(self):
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn, mode="allow_session")
        run = lambda command: {"id": "s", "function": {"name": "shell", "arguments": json.dumps({"command": command})}}
        await agent._use_tool(sid, store, run("touch one.txt"))
        await agent._use_tool(sid, store, run("touch one.txt"))
        self.assertEqual(len(conn.permission_requests), 1)
        await agent._use_tool(sid, store, run("mkdir d"))
        self.assertEqual(len(conn.permission_requests), 2)


if __name__ == "__main__":
    unittest.main()
