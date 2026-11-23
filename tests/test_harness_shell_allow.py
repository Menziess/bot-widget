"""Harness action 2: read-only shell commands run without asking; 'always allow this prefix' is saved."""

import json
import os
import shutil
import tempfile
import unittest

from harness.agent.agent import LeanAgent
from harness.agent.tools import Tools
from harness.agent.workspace import (
    EditStore,
    ShellAllow,
    is_read_only_command,
    shell_segments,
    suggest_prefixes,
    workspace_builtins,
)
from tests.test_h7_diffs import ScriptModel, _Conn


class ReadOnlyClassifier(unittest.TestCase):
    def setUp(self):
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.ws, True)

    def free(self, command):
        return is_read_only_command(self.ws, command)

    def test_plain_reads_are_free(self):
        for cmd in ("ls", "ls -la src", "cat README.md", "rg foo src", "git status", "git log --oneline -5",
                    "git diff HEAD~1", "pwd", "find . -name '*.py'", "head -n 5 a.txt"):
            self.assertTrue(self.free(cmd), cmd)

    def test_compound_reads_are_judged_per_part(self):
        self.assertTrue(self.free("ls && git status | head -5"))
        self.assertFalse(self.free("ls && npm install"))
        self.assertFalse(self.free("ls; rm a.txt"))

    def test_writes_and_tricks_ask(self):
        for cmd in ("rm a.txt", "touch a", "git commit -m x", "git push", "ls > out.txt", "cat a >> b",
                    "echo $(whoami)", "echo `id`", "ls &", "find . -delete", "find . -exec rm {} ;",
                    "git diff --output=x", "git -c core.pager=x log", "rg --pre ./x foo", "python x.py",
                    "ls\nrm a", "cat 'unbalanced", ""):
            self.assertFalse(self.free(cmd), repr(cmd))

    def test_secrets_ask_and_paths_outside_the_workspace_are_read_free(self):
        for cmd in ("cat .env", "cat .env.production", "cat .ssh/id_rsa", "cat ~/.ssh/id_rsa", "cat .e*",
                    "cat $HOME/x", "cat ../../.env", "cat /home/x/.ssh/id_rsa", "cat /.env", "ls /root/.ssh",
                    "cat ../../../../../../../../.env.local", "cat ../../../../../../../../home/x/.aws/credentials"):
            self.assertFalse(self.free(cmd), cmd)
        for cmd in ("cat /etc/passwd", "ls ../..", "cat .env.example", f"cat {self.ws}/a.txt"):
            self.assertTrue(self.free(cmd), cmd)

    def test_root_is_not_a_secret_but_secret_names_still_ask_at_root(self):
        from harness.agent.workspace import _is_secret_name, _is_secret_path
        self.assertFalse(_is_secret_name(""))
        self.assertFalse(_is_secret_path("/"))
        self.assertTrue(_is_secret_path("/.env"))
        self.assertTrue(_is_secret_path("/.ssh"))
        deep = "../" * (self.ws.count("/") + 3)
        self.assertTrue(self.free("ls /") and self.free(f"ls {deep}"))
        self.assertFalse(self.free(f"cat {deep}.env") or self.free(f"cat {deep}.ssh/id_rsa"))

    def test_segments(self):
        self.assertEqual(shell_segments("ls -l | wc -l"), [["ls", "-l"], ["wc", "-l"]])
        self.assertIsNone(shell_segments("ls |"))


class SuggestAndSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.allow = ShellAllow(os.path.join(self.dir, "allow.json"))

    def test_suggested_prefix(self):
        self.assertEqual(suggest_prefixes("npm test"), ["npm test"])
        self.assertEqual(suggest_prefixes("pytest -x tests"), ["pytest"])
        self.assertEqual(suggest_prefixes("git commit -m x"), ["git commit"])
        for risky in ("sudo apt install x", "bash -c 'x'", "python x.py", "./run.sh"):
            self.assertEqual(suggest_prefixes(risky, self.ws), [], risky)

    def test_nothing_that_runs_other_code_or_other_commands_is_offered_in_any_version_or_spelling(self):
        for risky in ("python3.12.5 -c 'print(1)'", "python3.12 x.py", "/opt/homebrew/bin/python3.15 x.py", "python3.12.exe x.py",
                      "node18 x.js", "nodejs x.js", "pypy3 x.py", "php8.3 x.php", "uvx ruff check", "npx prettier .",
                      "timeout 300 pytest", "nice -n 5 make", "command ls", "kill 1996", "pkill -f x", "killall python"):
            self.assertEqual(suggest_prefixes(risky, self.ws), [], risky)
            self.assertFalse(self.allow.add(self.ws, risky.split()[0]), risky)
        self.assertEqual(suggest_prefixes("npm test"), ["npm test"], "a program that only does its own work still is")
        self.assertEqual(suggest_prefixes("pythonista --x"), ["pythonista"], "the family is a name, not a prefix of one")

    def test_a_chain_offers_one_prefix_per_part_unless_one_part_cannot_be_saved(self):
        self.assertEqual(suggest_prefixes("npm test && npm run build"), ["npm test", "npm run"])
        self.assertEqual(suggest_prefixes("acli jira a && acli jira b | tail -5"), ["acli jira", "tail"])
        self.assertEqual(suggest_prefixes("npm test && python x.py", self.ws), [])
        self.assertEqual(suggest_prefixes("npm test > out.txt"), [])
        self.assertEqual(suggest_prefixes("cd .. && npm test", self.ws, skip_read_only=True), ["npm test"])

    def test_a_redirect_that_only_merges_or_discards_output_does_not_count(self):
        self.assertEqual(suggest_prefixes("acli jira a --x 2>&1 | tail -80"), ["acli jira", "tail"])
        self.assertEqual(suggest_prefixes("npm test 2>/dev/null"), ["npm test"])
        self.assertEqual(suggest_prefixes("npm test >/dev/null 2>&1"), ["npm test"])
        self.assertEqual(suggest_prefixes("npm test &>/dev/null"), ["npm test"])
        self.assertEqual(suggest_prefixes("npm test > out.txt"), [])
        self.assertEqual(suggest_prefixes("npm test 2> err.txt"), [])
        self.assertEqual(suggest_prefixes("npm test >&2"), [])

    def test_program_by_absolute_path_is_offered_unless_inside_the_workspace_or_a_shell(self):
        self.assertEqual(suggest_prefixes("/opt/tool/bin/tool run --help", self.ws), ["/opt/tool/bin/tool run"])
        self.assertEqual(suggest_prefixes(f"{self.ws}/run.sh", self.ws), [])
        self.assertEqual(suggest_prefixes("/bin/bash -c x", self.ws), [])
        self.assertEqual(suggest_prefixes("/opt/tool/bin/tool run", ""), [])
        self.assertFalse(self.allow.add(self.ws, "/bin/bash -c"))

    def test_saved_prefix_allows_only_matching_commands_in_that_workspace(self):
        self.assertTrue(self.allow.add(self.ws, "npm test"))
        self.assertTrue(self.allow.allows(self.ws, "npm test -- --watch=false"))
        self.assertTrue(self.allow.allows(self.ws, "npm test && ls"))
        self.assertFalse(self.allow.allows(self.ws, "npm install"))
        self.assertFalse(self.allow.allows(self.ws, "npm testing"))
        self.assertFalse(self.allow.allows(self.ws, "npm test > out"))
        self.assertFalse(self.allow.allows(self.ws, "npm test && rm x"))
        self.assertFalse(self.allow.allows(self.ws + "-other", "npm test"))

    def test_bot_wide_and_fixed_prefixes(self):
        self.allow.add(self.ws, "make", everywhere=True)
        self.assertTrue(self.allow.allows("/somewhere/else", "make all"))
        fixed = ShellAllow(os.path.join(self.dir, "none.json"), ("cargo check", " "))
        self.assertTrue(fixed.allows(self.ws, "cargo check"))

    def test_dangerous_prefix_is_not_saved_and_file_persists(self):
        self.assertFalse(self.allow.add(self.ws, "sudo rm"))
        self.allow.add(self.ws, "npm test")
        again = ShellAllow(self.allow.path)
        self.assertEqual(again.prefixes(self.ws), ["npm test"])


class ShellThroughAgent(unittest.IsolatedAsyncioTestCase):
    async def _agent(self, conn):
        self.folder = tempfile.mkdtemp()
        self.ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.addCleanup(shutil.rmtree, self.ws, True)
        agent = LeanAgent("sh", ScriptModel(), folder=self.folder)
        agent.on_connect(conn)
        agent.tools = Tools("", set(), workspace=self.ws, permission="ask")
        for tool in workspace_builtins(self.ws, EditStore()):
            agent.tools.add(tool)
        opened = await agent.new_session(cwd=self.ws)
        return agent, opened.session_id, agent.stores[opened.session_id]

    def _call(self, command, name="shell"):
        return {"id": "s1", "function": {"name": name, "arguments": json.dumps({"command": command})}}

    async def test_read_only_command_runs_without_a_question(self):
        conn = _Conn(auto_allow=False)
        agent, sid, store = await self._agent(conn)
        with open(os.path.join(self.ws, "hello.txt"), "w") as fh:
            fh.write("hi\n")
        result = await agent._use_tool(sid, store, self._call("ls"))
        self.assertIn("hello.txt", result)
        self.assertEqual(conn.permission_requests, [])

    async def test_other_command_asks_and_offers_always(self):
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn)
        await agent._use_tool(sid, store, self._call("echo hi > f.txt"))
        self.assertEqual(len(conn.permission_requests), 1)
        names = [o.option_id for o in conn.permission_requests[0]["options"]]
        self.assertEqual(names, ["allow", "decline"])  # a redirect has no prefix to save
        conn2 = _Conn(auto_allow=True)
        agent2, sid2, store2 = await self._agent(conn2)
        await agent2._use_tool(sid2, store2, self._call("touch made.txt"))
        names = [o.option_id for o in conn2.permission_requests[0]["options"]]
        self.assertEqual(names, ["allow", "allow_always", "decline"])

    async def test_always_allow_saves_the_prefix_and_the_next_call_runs_free(self):
        conn = _Conn()
        conn._responses.append(("selected", "allow_always"))
        agent, sid, store = await self._agent(conn)
        await agent._use_tool(sid, store, self._call("touch one.txt"))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "one.txt")))
        self.assertEqual(agent.shell_allow.prefixes(self.ws), ["touch one.txt"])
        await agent._use_tool(sid, store, self._call("touch one.txt"))
        self.assertEqual(len(conn.permission_requests), 1)
        # a different command still asks (declined here: the default answer is cancelled)
        result = await agent._use_tool(sid, store, self._call("touch two.txt"))
        self.assertIn("declined", result)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "two.txt")))

    async def test_always_allow_on_a_chain_saves_each_part_and_a_cd_needs_no_saving(self):
        conn = _Conn()
        conn._responses.append(("selected", "allow_always"))
        agent, sid, store = await self._agent(conn)
        await agent._use_tool(sid, store, self._call("cd . && touch one.txt && touch two.txt"))
        self.assertEqual([o.option_id for o in conn.permission_requests[0]["options"]],
                         ["allow", "allow_always", "decline"])
        self.assertIn("`touch one.txt, touch two.txt`", conn.permission_requests[0]["options"][1].name)
        self.assertEqual(agent.shell_allow.prefixes(self.ws), ["touch one.txt", "touch two.txt"])
        await agent._use_tool(sid, store, self._call("cd . && touch two.txt"))
        self.assertEqual(len(conn.permission_requests), 1)

    async def test_readonly_switch_off_asks_again(self):
        os.environ["HARNESS_SHELL_READONLY"] = "0"
        self.addCleanup(os.environ.pop, "HARNESS_SHELL_READONLY", None)
        conn = _Conn(auto_allow=True)
        agent, sid, store = await self._agent(conn)
        await agent._use_tool(sid, store, self._call("ls"))
        self.assertEqual(len(conn.permission_requests), 1)


if __name__ == "__main__":
    unittest.main()
