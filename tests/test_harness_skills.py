"""A skill in HARNESS_CONTEXT_PATHS is a slash command: advertised to the widget, and its text goes to the model
once the user runs it."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from harness.agent import context
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from harness.agent.tools import Tool
from tests.test_h7_diffs import ScriptModel, _Conn


class Skills(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        skill = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w") as fh:
            fh.write("---\nname: parking\ndescription: Book a parking ticket\n---\nSTEP ONE: book it")
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": os.path.join(self.tmp, "skills")})
        patched.start()
        self.addCleanup(patched.stop)

    def agent(self):
        conn = _Conn()
        agent = LeanAgent("sk", ScriptModel(), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(conn)
        return agent, conn

    async def test_a_skill_is_advertised_as_a_command_when_a_session_opens(self):
        agent, conn = self.agent()
        await agent.new_session(cwd=self.tmp)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        names = [(c.name, c.description) for _, u in conn.updates
                 if getattr(u, "session_update", "") == "available_commands_update" for c in u.available_commands]
        self.assertEqual(names, [("parking", "Book a parking ticket")])

    async def test_running_the_skill_puts_its_text_in_front_of_the_model_until_another_is_run(self):
        agent, _ = self.agent()
        store = SessionStore(os.path.join(self.tmp, "bot"))
        agent._run_skill(store, "/Parking 2026-11-20")
        sent = " ".join(m["content"] for m in context.build(store, "sk"))
        self.assertIn("STEP ONE: book it", sent)
        self.assertNotIn("name: parking", sent)
        agent._run_skill(store, "thanks")
        self.assertIn("STEP ONE", " ".join(m["content"] for m in context.build(store, "sk")))
        fresh = SessionStore(os.path.join(self.tmp, "other"))
        agent._run_skill(fresh, "/unknown")
        self.assertNotIn("STEP ONE", " ".join(m["content"] for m in context.build(fresh, "sk")))


class SkillTurnsEndOnPurpose(unittest.IsolatedAsyncioTestCase):
    """A skill is only over when the model says so: a message that is only a promise is not an end."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        skill = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w") as fh:
            fh.write("---\nname: parking\ndescription: Book a parking ticket\n---\nSTEP ONE: book it")
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": os.path.join(self.tmp, "skills")})
        patched.start()
        self.addCleanup(patched.stop)
        self.ran = []

    async def turn(self, text, scripts):
        agent = LeanAgent("sk", ScriptModel(scripts), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(_Conn())
        session = (await agent.new_session(cwd=self.tmp)).session_id
        agent.tools.add(Tool("book", "Book it.", {"type": "object", "properties": {}},
                             lambda _args: self.ran.append("book") or "Booked."))
        block = type("Block", (), {"text": text})()
        await agent.prompt(session, [block])
        return agent

    @staticmethod
    def call(name):
        return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": json.dumps({})}}])

    async def test_a_promise_without_a_tool_call_gets_one_nudge_and_the_skill_goes_on(self):
        promise = [("text", "Laat me even kijken."), ("finish", "stop")]
        agent = await self.turn("/parking vrijdag", [promise, [self.call("book"), ("finish", "tool_calls")],
                                                      [("text", "Geboekt."), self.call("done")]])
        self.assertEqual(self.ran, ["book"])
        self.assertEqual(agent.model.scripts, [], "all three model calls were made")

    async def test_done_and_wait_for_user_end_the_turn_without_another_model_call(self):
        for ending in ("done", "wait_for_user"):
            with self.subTest(ending=ending):
                agent = await self.turn("/parking", [[("text", "Welke datum?"), self.call(ending)], [("text", "never")]])
                self.assertEqual(len(agent.model.scripts), 1, "the turn ended at the marker")

    async def test_a_skill_that_keeps_promising_is_nudged_twice_and_then_left_alone(self):
        promise = [("text", "Ik ga kijken."), ("finish", "stop")]
        agent = await self.turn("/parking", [promise, promise, promise, [("text", "never")]])
        self.assertEqual(len(agent.model.scripts), 1, "two nudges, then the third message ends the turn")

    async def test_a_turn_without_a_skill_is_not_nudged(self):
        agent = await self.turn("hallo", [[("text", "Hoi."), ("finish", "stop")], [("text", "never")]])
        self.assertEqual(len(agent.model.scripts), 1)


if __name__ == "__main__":
    unittest.main()
