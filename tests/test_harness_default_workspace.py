"""Harness action 3: the ACP cwd (else home) is the workspace; AGENTS.md from the project root down to it;
one default permission everywhere."""

import os
import shutil
import tempfile
import unittest

from botwidget import acp_bots
from harness.agent.agent import LeanAgent
from harness.agent.workspace import default_workspace, load_workspace_rules, project_root
from tests.test_h7_diffs import ScriptModel


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class DefaultWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_configured_wins_then_cwd_then_home(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        self.assertEqual(default_workspace(other, self.tmp), other)
        self.assertEqual(default_workspace("", self.tmp), self.tmp)
        self.assertEqual(default_workspace("", ""), os.path.realpath(os.path.expanduser("~")))
        self.assertEqual(default_workspace("", "/"), os.path.realpath(os.path.expanduser("~")))
        self.assertEqual(default_workspace("", os.path.join(self.tmp, "missing")),
                         os.path.realpath(os.path.expanduser("~")))

    def test_off_means_no_workspace(self):
        self.assertEqual(default_workspace("off", self.tmp), "")


class Rules(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, ".git"))
        self.sub = os.path.join(self.tmp, "pkg", "inner")
        os.makedirs(self.sub)

    def test_project_root_is_the_git_folder(self):
        self.assertEqual(project_root(self.sub), self.tmp)

    def test_root_down_to_cwd_in_that_order(self):
        _write(os.path.join(self.tmp, "AGENTS.md"), "ROOT RULE")
        _write(os.path.join(self.tmp, "pkg", "CLAUDE.md"), "PKG RULE")
        _write(os.path.join(self.sub, "AGENTS.md"), "INNER RULE")
        text = load_workspace_rules(self.sub)
        self.assertLess(text.index("ROOT RULE"), text.index("PKG RULE"))
        self.assertLess(text.index("PKG RULE"), text.index("INNER RULE"))
        self.assertIn("(CLAUDE.md in ..)", text)

    def test_without_git_only_the_cwd_counts(self):
        plain = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, plain, True)
        _write(os.path.join(plain, "AGENTS.md"), "HERE")
        self.assertIn("HERE", load_workspace_rules(plain))

    def test_cap_keeps_the_nearest_files(self):
        _write(os.path.join(self.tmp, "AGENTS.md"), "R" * 300)
        _write(os.path.join(self.sub, "AGENTS.md"), "N" * 300)
        os.environ["HARNESS_RULES_MAX_CHARS"] = "400"
        self.addCleanup(os.environ.pop, "HARNESS_RULES_MAX_CHARS", None)
        text = load_workspace_rules(self.sub)
        self.assertGreaterEqual(text.count("N"), 300)
        self.assertLess(text.count("R"), 300)

    def test_clinerules_is_read(self):
        _write(os.path.join(self.sub, ".clinerules"), "OK")
        self.assertIn("OK", load_workspace_rules(self.sub))


class AgentFollowsCwd(unittest.IsolatedAsyncioTestCase):
    async def test_session_cwd_becomes_the_workspace_and_home_is_the_fallback(self):
        os.environ.pop("HARNESS_WORKSPACE", None)
        folder = tempfile.mkdtemp()
        cwd = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(shutil.rmtree, cwd, True)
        agent = LeanAgent("cwd", ScriptModel(), folder=folder)
        first = await agent.new_session(cwd=cwd)
        self.assertEqual(agent._workspace_for(first.session_id), cwd)
        self.assertEqual(agent.tools.workspace, cwd)
        await agent.tools.start()
        self.assertIn("edit", agent.tools.tools)
        agent._cwds[first.session_id] = ""
        self.assertEqual(agent._workspace_for(first.session_id), os.path.realpath(os.path.expanduser("~")))

    async def test_env_workspace_beats_cwd(self):
        cfg = os.path.realpath(tempfile.mkdtemp())
        cwd = os.path.realpath(tempfile.mkdtemp())
        folder = tempfile.mkdtemp()
        for p in (cfg, cwd, folder):
            self.addCleanup(shutil.rmtree, p, True)
        os.environ["HARNESS_WORKSPACE"] = cfg
        self.addCleanup(os.environ.pop, "HARNESS_WORKSPACE", None)
        agent = LeanAgent("cfg", ScriptModel(), folder=folder)
        opened = await agent.new_session(cwd=cwd)
        self.assertEqual(agent._workspace_for(opened.session_id), cfg)


class OneDefaultPermission(unittest.TestCase):
    def test_new_and_existing_bots_agree(self):
        self.assertEqual(acp_bots.blank()["workspace_permissions"], "ask")
        self.assertEqual(acp_bots.fields_of({"env": {}})["workspace_permissions"], "ask")
        self.assertEqual(acp_bots.fields_of({"env": {"HARNESS_WORKSPACE_PERMISSIONS": "allow"}})
                         ["workspace_permissions"], "allow")

    def test_the_agent_default_is_the_same(self):
        os.environ.pop("HARNESS_WORKSPACE_PERMISSIONS", None)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.assertEqual(LeanAgent("p", ScriptModel(), folder=folder).tools.permission, "ask")


if __name__ == "__main__":
    unittest.main()
