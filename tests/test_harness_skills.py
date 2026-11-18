"""A skill in HARNESS_CONTEXT_PATHS is a slash command: advertised to the widget, and its text goes to the model
once the user runs it."""

import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from harness.agent import context
from acp.schema import PromptResponse
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


class RecordingModel(ScriptModel):
    """A scripted model that keeps what it was sent, one entry per call."""

    def __init__(self, scripts=()):
        super().__init__(scripts)
        self.sent = []

    def stream(self, messages, tools=None, stop=None, opened=None):
        self.sent.append(" || ".join(str(m.get("content")) for m in messages))
        yield from super().stream(messages, tools=tools, stop=stop, opened=opened)


class SkillSession(unittest.IsolatedAsyncioTestCase):
    """A skill runs in a session of its own: the skill and a brief of the conversation, not the conversation."""

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

    async def agent(self, scripts):
        model = RecordingModel(scripts)
        agent = LeanAgent("sk", model, folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(_Conn())
        session = (await agent.new_session(cwd=self.tmp)).session_id
        return agent, model, session

    @staticmethod
    async def say(agent, session, text):
        await agent.prompt(session, [type("Block", (), {"text": text})()])

    @staticmethod
    def end(name):
        return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": "{}"}}])

    @mock.patch("harness.agent.agent.BRIEF_SHORT", 0)
    async def test_the_skill_gets_its_own_context_with_a_brief_and_the_chat_does_not_get_the_skill(self):
        agent, model, session = await self.agent([
            [("text", "Prima."), ("finish", "stop")],
            [("text", "Geboekt."), self.end("done")],
            [("text", "Graag gedaan."), ("finish", "stop")]])
        await self.say(agent, session, "Mijn kenteken staat in de notities.")
        await self.say(agent, session, "/parking vrijdag")
        skill_call = model.sent[1]
        self.assertIn("STEP ONE: book it", skill_call)
        self.assertIn("/parking vrijdag", skill_call)
        self.assertIn("notes", skill_call, "the brief from the conversation, here what complete() returned")
        self.assertNotIn("Prima.", skill_call, "the conversation itself stays out")
        await self.say(agent, session, "Bedankt")
        self.assertNotIn("STEP ONE", model.sent[2], "the chat does not carry the skill after it is done")

    async def test_what_the_skill_says_is_in_the_conversation_of_the_bot(self):
        agent, _model, session = await self.agent([[("text", "Welke datum?"), self.end("wait_for_user")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        self.assertEqual([(m["role"], m["text"]) for m in main.messages()],
                         [("user", "/parking"), ("bot", "Welke datum?")])

    async def test_a_message_while_the_skill_waits_goes_to_the_skill_until_it_is_done(self):
        agent, model, session = await self.agent([
            [("text", "Welke datum?"), self.end("wait_for_user")],
            [("text", "Geboekt."), self.end("done")]])
        await self.say(agent, session, "/parking")
        await self.say(agent, session, "20 november")
        self.assertIn("STEP ONE", model.sent[1], "the answer went to the skill")
        self.assertIn("20 november", model.sent[1])
        self.assertEqual(agent.stores[session].get("skill_active"), "", "done gives the chat back")

    async def test_a_message_that_is_not_about_the_skill_goes_to_the_chat_without_the_user_doing_anything(self):
        agent, model, session = await self.agent([
            [("text", "Welke datum?"), self.end("wait_for_user")],
            [self.end("not_for_me")],
            [("text", "Vier."), ("finish", "stop")]])
        await self.say(agent, session, "/parking")
        await self.say(agent, session, "Wat is 2 + 2?")
        main = agent.stores[session]
        self.assertEqual(main.get("skill_active"), "")
        self.assertEqual(main.messages()[-1], {"role": "bot", "text": "Vier."})
        self.assertNotIn("STEP ONE", model.sent[2], "the chat answered, without the skill")

    async def test_a_skill_that_waited_too_long_is_over_and_the_chat_answers(self):
        agent, model, session = await self.agent([
            [("text", "Welke datum?"), self.end("wait_for_user")],
            [("text", "Hoi."), ("finish", "stop")]])
        await self.say(agent, session, "/parking")
        agent.stores[session].set("skill_active", str(time.time() - 3600))
        await self.say(agent, session, "Hallo")
        self.assertNotIn("STEP ONE", model.sent[1])

    async def test_cancelling_the_turn_ends_the_skill(self):
        agent, _model, session = await self.agent([[("text", "Welke datum?"), self.end("wait_for_user")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        self.assertTrue(main.get("skill_active"))
        agent._after_skill(main, PromptResponse(stop_reason="cancelled"))
        self.assertEqual(main.get("skill_active"), "")

    async def test_a_job_that_finishes_while_the_skill_runs_is_told_to_the_skill(self):
        agent, model, session = await self.agent([
            [("text", "Ik wacht op de boeking."), self.end("wait_for_user")],
            [("text", "Geboekt."), self.end("done")]])
        await self.say(agent, session, "/parking")
        agent._inbox.setdefault(session, []).append("JOB-FINISHED exit_code: 0")
        await agent._drain_jobs(session)
        self.assertIn("STEP ONE", model.sent[1])
        self.assertIn("JOB-FINISHED", model.sent[1])
        main = agent.stores[session]
        self.assertEqual(main.messages()[-1], {"role": "bot", "text": "Geboekt."})
        self.assertEqual(main.get("skill_active"), "")

    async def test_a_short_conversation_goes_to_the_skill_as_it_is_without_a_model_call(self):
        agent, model, session = await self.agent([[("text", "Prima."), self.end("done")]])
        calls = []
        model.complete = lambda messages: calls.append(messages) or "notes"
        main = agent.stores[session]
        main.add("user", "Het is voor vrijdag.")
        await self.say(agent, session, "/parking")
        self.assertEqual(calls, [])
        self.assertIn("Het is voor vrijdag.", model.sent[0])


if __name__ == "__main__":
    unittest.main()
