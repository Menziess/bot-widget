"""Harness action 5: a configurable step limit (default 30) and a stop on the same call repeated."""

import json
import os
import shutil
import tempfile
import unittest

from acp.schema import AgentMessageChunk, TextContentBlock

from harness.agent import agent as agent_module
from harness.agent.agent import LeanAgent
from harness.agent.tools import Tool
from tests.test_h7_diffs import ScriptModel, _Conn


def _call(i, name="ping", **args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class Steps(unittest.IsolatedAsyncioTestCase):
    async def _run(self, scripts, **env):
        for key, value in env.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key, None)
        os.environ["HARNESS_WORKSPACE"] = "off"
        self.addCleanup(os.environ.pop, "HARNESS_WORKSPACE", None)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model = ScriptModel(scripts)
        agent = LeanAgent("st", model, folder=folder)
        conn = _Conn()
        self.conn = conn
        agent.on_connect(conn)
        self.pings = []
        agent.tools.add(Tool("ping", "x", {"type": "object", "properties": {"n": {"type": "integer"}}},
                             lambda a: self.pings.append(a) or "pong"))
        opened = await agent.new_session(cwd=folder)
        await agent.prompt(opened.session_id, [TextContentBlock(type="text", text="go")])
        text = "".join(u.content.text for _s, u in conn.updates if isinstance(u, AgentMessageChunk))
        return agent, model, text

    def test_default_is_thirty_and_not_six(self):
        self.assertEqual(agent_module.MAX_STEPS, 30)

    async def test_a_long_task_of_different_calls_runs_past_six_steps(self):
        scripts = [[("tool_calls", [_call(i, n=i)]), ("finish", "tool_calls")] for i in range(10)]
        scripts.append([("text", "all done"), ("finish", "stop")])
        _agent, _model, text = await self._run(scripts)
        self.assertEqual(len(self.pings), 10)
        self.assertIn("all done", text)

    async def test_the_same_call_three_times_in_a_row_stops_the_run(self):
        scripts = [[("tool_calls", [_call(i, n=1)]), ("finish", "tool_calls")] for i in range(10)]
        agent, model, text = await self._run(scripts)
        self.assertEqual(len(self.pings), 2)  # the third identical call is never run
        self.assertEqual(len(model.scripts), 7)  # three model steps were used
        self.assertIn("same arguments 3 times in a row", text)

    async def test_the_same_call_three_times_inside_one_answer_still_runs_once(self):
        scripts = [[("tool_calls", [_call(i, n=1) for i in range(3)]), ("finish", "tool_calls")],
                   [("text", "fine"), ("finish", "stop")]]
        _agent, _model, text = await self._run(scripts)
        self.assertEqual(len(self.pings), 1)
        self.assertIn("fine", text)
        self.assertNotIn("I stopped", text)

    async def test_only_the_closing_step_is_the_answer_what_came_before_a_tool_call_is_progress(self):
        scripts = [[("text", "All done, ik ben klaar."), ("tool_calls", [_call(0, n=1)]), ("finish", "tool_calls")],
                   [("text", "Het is gelukt."), ("finish", "stop")]]
        _agent, _model, text = await self._run(scripts)
        self.assertEqual(text, "Het is gelukt.")
        self.assertEqual(_agent.stores[next(iter(_agent.stores))].messages()[-1]["text"], "Het is gelukt.")

    async def test_a_turn_without_a_closing_message_still_shows_the_last_thing_said(self):
        scripts = [[("text", "Ik zoek het uit."), ("tool_calls", [_call(0, n=1)]), ("finish", "tool_calls")]]
        _agent, _model, text = await self._run(scripts, HARNESS_MAX_STEPS="1")
        self.assertIn("Ik zoek het uit.", text)
        self.assertIn("I stopped after 1 steps", text)

    async def test_the_answer_and_a_notice_are_separate_messages(self):
        scripts = [[("text", "Ik zoek het uit."), ("tool_calls", [_call(0, n=1)]), ("finish", "tool_calls")]]
        await self._run(scripts, HARNESS_MAX_STEPS="1")
        chunks = [(u.content.text, u.message_id) for _s, u in self.conn.updates if isinstance(u, AgentMessageChunk)]
        self.assertEqual([text for text, _id in chunks][0], "Ik zoek het uit.")
        self.assertTrue(all(mid for _text, mid in chunks), "every piece says which message it belongs to")
        self.assertEqual(len({mid for _text, mid in chunks}), 2, "the answer and the notice are two messages")

    async def test_different_arguments_do_not_count_as_a_loop(self):
        scripts = [[("tool_calls", [_call(0, n=1)]), ("finish", "tool_calls")],
                   [("tool_calls", [_call(1, n=2)]), ("finish", "tool_calls")],
                   [("tool_calls", [_call(2, n=1)]), ("finish", "tool_calls")],
                   [("text", "fine"), ("finish", "stop")]]
        _agent, _model, text = await self._run(scripts)
        self.assertIn("fine", text)
        self.assertNotIn("I stopped", text)

    async def test_repeat_limit_is_configurable_and_can_be_off(self):
        scripts = [[("tool_calls", [_call(i, n=1)]), ("finish", "tool_calls")] for i in range(6)]
        scripts.append([("text", "end"), ("finish", "stop")])
        _agent, model, text = await self._run(scripts, HARNESS_LOOP_REPEATS="0")
        self.assertNotIn("I stopped", text)
        self.assertEqual(model.scripts, [])
        scripts = [[("tool_calls", [_call(i, n=1)]), ("finish", "tool_calls")] for i in range(6)]
        _agent, model, text = await self._run(scripts, HARNESS_LOOP_REPEATS="2")
        self.assertIn("2 times in a row", text)

    async def test_the_step_limit_is_configurable_and_says_so(self):
        scripts = [[("tool_calls", [_call(i, n=i)]), ("finish", "tool_calls")] for i in range(10)]
        agent, model, text = await self._run(scripts, HARNESS_MAX_STEPS="4")
        self.assertEqual(len(self.pings), 4)
        self.assertIn("stopped after 4 steps", text)
        self.assertEqual(len(model.scripts), 6)

    async def test_a_bad_value_falls_back_to_the_default(self):
        scripts = [[("text", "ok"), ("finish", "stop")]]
        _agent, _model, text = await self._run(scripts, HARNESS_MAX_STEPS="lots")
        self.assertIn("ok", text)


if __name__ == "__main__":
    unittest.main()
