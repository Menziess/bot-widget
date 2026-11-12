"""Harness action 4: large tool output spills to a file; full results stay in the session; old ones shrink."""

import json
import os
import shutil
import tempfile
import time
import unittest

from harness.agent import context, spill
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from harness.agent.tools import Tools
from harness.agent.workspace import EditStore, _ws_read, is_read_only_command, workspace_builtins
from tests.test_h7_diffs import ScriptModel, _Conn


class _SpillEnv(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        for key, value in (("HARNESS_SPILL_DIR", self.dir), ("HARNESS_TOOL_OUTPUT_LIMIT", "1000")):
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)


class Spill(_SpillEnv):
    def test_small_output_is_untouched(self):
        self.assertEqual(spill.spill("short", "shell"), ("short", ""))

    def test_large_output_gets_head_tail_and_a_path(self):
        text = "HEAD" + "x" * 5000 + "TAIL"
        shown, path = spill.spill(text, "shell")
        self.assertTrue(shown.startswith("HEAD"))
        self.assertTrue(shown.endswith("TAIL"))
        self.assertIn(path, shown)
        self.assertLess(len(shown), 1300)
        with open(path) as fh:
            self.assertEqual(fh.read(), text)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_limit_can_be_turned_off_or_changed(self):
        os.environ["HARNESS_TOOL_OUTPUT_LIMIT"] = "0"
        self.assertEqual(spill.spill("y" * 50000)[1], "")
        os.environ["HARNESS_TOOL_OUTPUT_LIMIT"] = "100"
        self.assertTrue(spill.spill("y" * 500)[1])

    def test_an_unwritable_folder_still_shows_head_and_tail(self):
        os.environ["HARNESS_SPILL_DIR"] = os.path.join(self.dir, "file")
        open(os.path.join(self.dir, "file"), "w").close()
        shown, path = spill.spill("z" * 5000)
        self.assertEqual(path, "")
        self.assertIn("could not be saved", shown)

    def test_old_spill_files_are_pruned(self):
        old = os.path.join(self.dir, "old.txt")
        open(old, "w").close()
        os.utime(old, (time.time() - 30 * 86400,) * 2)
        spill.spill("q" * 5000)
        self.assertFalse(os.path.exists(old))


class ReadingTheSpill(_SpillEnv):
    def test_read_file_reads_parts_of_a_spilled_file_outside_the_workspace(self):
        ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, ws, True)
        _shown, path = spill.spill("\n".join(f"line {i}" for i in range(1, 400)), "shell")
        self.assertEqual(_ws_read(ws, path, 5, 2), "line 5\nline 6\n")
        self.assertTrue(is_read_only_command(ws, f"rg 'line 3' {path}"))


class AgentKeepsFullResults(_SpillEnv, unittest.IsolatedAsyncioTestCase):
    async def test_model_sees_head_and_tail_and_the_session_keeps_everything(self):
        folder = tempfile.mkdtemp()
        ws = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(shutil.rmtree, ws, True)
        big = "A" + "m" * 6000 + "Z"
        with open(os.path.join(ws, "big.txt"), "w") as fh:
            fh.write(big)
        agent = LeanAgent("sp", ScriptModel(), folder=folder)
        agent.on_connect(_Conn())
        agent.tools = Tools("", set(), workspace=ws, permission="allow")
        for tool in workspace_builtins(ws, EditStore()):
            agent.tools.add(tool)
        opened = await agent.new_session(cwd=ws)
        store = agent.stores[opened.session_id]
        call = {"id": "r1", "function": {"name": "read_file", "arguments": json.dumps({"path": "big.txt"})}}
        shown = await agent._use_tool(opened.session_id, store, call)
        self.assertLess(len(shown), 1300)
        self.assertTrue(shown.startswith("A") and shown.endswith("Z"))
        kept = store.tool_results()
        self.assertEqual(kept[0]["full"], big)
        self.assertTrue(os.path.exists(kept[0]["path"]))
        # the next turn's request still carries what the model was shown, with the path
        text = "\n".join(m["content"] for m in context.build(store, "sp"))
        self.assertIn(kept[0]["path"], text)


class ShrinkingOldResults(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.store = SessionStore(self.dir)
        self.addCleanup(self.store.close)

    def _results(self, n, size):
        for i in range(n):
            self.store.add_tool_result(f"read_file{i}", f"R{i}" + "." * size, "full", "")

    def test_with_room_every_result_is_shown_whole(self):
        self._results(3, 200)
        text = "\n".join(m["content"] for m in context.build(self.store, "b"))
        self.assertNotIn("(shortened)", text)

    def test_when_tight_old_results_shrink_and_the_newest_stay(self):
        os.environ["HARNESS_CONTEXT_TOKENS"] = "3200"  # about 1200 characters of room
        self.addCleanup(os.environ.pop, "HARNESS_CONTEXT_TOKENS", None)
        self._results(4, 900)
        text = "\n".join(m["content"] for m in context.build(self.store, "b"))
        self.assertIn("(shortened)", text)
        self.assertIn("[read_file3]\nR3", text)  # the newest is whole
        self.assertIn("[read_file0] (shortened)", text)

    def test_declined_and_failed_results_are_not_replayed(self):
        LeanAgent._note_tool(self.store, "shell", "declined by the user", "declined")
        LeanAgent._note_tool(self.store, "shell", "ok", "fine")
        self.assertEqual([r["full"] for r in self.store.tool_results()], ["fine"])


if __name__ == "__main__":
    unittest.main()
