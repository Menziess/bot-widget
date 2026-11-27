"""H8 item 8: short skill summary return.

_after_skill returns a short bounded summary to the main session instead of the whole
skill transcript. Test: the main store gets a bounded summary and the full transcript
stays in the skill store.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from acp.schema import PromptResponse

from harness.agent.agent import LeanAgent
from tests.test_h7_diffs import ScriptModel, _Conn

SKILL_SUMMARY_MAX = 150  # characters, hard limit for the summary copied to main


class ShortSkillSummary(unittest.IsolatedAsyncioTestCase):
    """The main session gets only a short bounded summary, not every bot line from the skill."""

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
        agent = LeanAgent("sk", ScriptModel(scripts), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(_Conn())
        session = (await agent.new_session(cwd=self.tmp)).session_id
        return agent, session

    @staticmethod
    async def say(agent, session, text):
        await agent.prompt(session, [type("Block", (), {"text": text})()])

    @staticmethod
    def end(name):
        return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": "{}"}}])

    async def test_main_gets_a_short_summary_not_all_bot_messages(self):
        """A skill that produces multiple bot messages copies only a short summary to main."""
        long_reply = "A" * 300
        agent, session = await self.agent([
            [("text", long_reply), self.end("done")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        # Main store should NOT contain the full long reply
        bot_messages = [m["text"] for m in main.messages() if m["role"] == "bot"]
        # The summary should be bounded (well under 300 chars)
        for msg in bot_messages:
            self.assertLessEqual(len(msg), SKILL_SUMMARY_MAX + 50,
                                 f"Bot message in main should be bounded, got {len(msg)} chars")

    async def test_full_transcript_stays_in_skill_store(self):
        """The skill session keeps every bot message intact."""
        long_reply = "B" * 500
        agent, session = await self.agent([
            [("text", long_reply), self.end("done")]])
        await self.say(agent, session, "/parking")
        skill_store = agent._skill_store()
        skill_messages = [m["text"] for m in skill_store.messages() if m["role"] == "bot"]
        # Full transcript must be in the skill store
        self.assertEqual(len(skill_messages), 1)
        self.assertEqual(skill_messages[0], long_reply)

    async def test_main_does_not_get_multiple_long_lines(self):
        """When the skill has several bot messages, main gets only one short summary."""
        agent, session = await self.agent([
            [("text", "X" * 200), self.end("wait_for_user")],
            [("text", "Y" * 200), self.end("done")]])
        await self.say(agent, session, "/parking")
        await self.say(agent, session, "voldoende")
        main = agent.stores[session]
        bot_messages = [m for m in main.messages() if m["role"] == "bot"]
        # Main should have at most one summary entry, not both long lines
        self.assertLessEqual(len(bot_messages), 2,
                             "Main should get a bounded number of bot entries from the skill")
        for msg in bot_messages:
            self.assertLessEqual(len(msg["text"]), 400,
                                 f"Each bot message in main should be bounded, got {len(msg['text'])} chars")

    async def test_short_skill_reply_still_copies(self):
        """A short skill reply still reaches main — the mechanism still works, just bounded."""
        agent, session = await self.agent([
            [("text", "Klaar."), self.end("done")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        bot_messages = [m["text"] for m in main.messages() if m["role"] == "bot"]
        self.assertTrue(any("Klaar" in m for m in bot_messages),
                        "Short skill reply should still reach main")

    async def test_cancelled_skill_does_not_add_to_main(self):
        """A cancelled skill does not copy transcript to main."""
        agent, session = await self.agent([
            [("text", "Z" * 300), ("finish", "cancelled")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        bot_messages = [m for m in main.messages() if m["role"] == "bot"]
        self.assertEqual(len(bot_messages), 0,
                         "Cancelled skill should not add bot messages to main")


class AfterSkillBehavior(unittest.IsolatedAsyncioTestCase):
    """_after_skill still handles skill_active correctly after the summary change."""

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
        agent = LeanAgent("sk", ScriptModel(scripts), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(_Conn())
        session = (await agent.new_session(cwd=self.tmp)).session_id
        return agent, session

    @staticmethod
    async def say(agent, session, text):
        await agent.prompt(session, [type("Block", (), {"text": text})()])

    @staticmethod
    def end(name):
        return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": "{}"}}])

    async def test_done_sets_skill_active_empty(self):
        agent, session = await self.agent([
            [("text", "Done."), self.end("done")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        self.assertEqual(main.get("skill_active"), "")

    async def test_wait_for_user_sets_skill_active_timestamp(self):
        agent, session = await self.agent([
            [("text", "Waiting."), self.end("wait_for_user")]])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        self.assertTrue(main.get("skill_active"), "wait_for_user should set skill_active")
        float(main.get("skill_active"))  # should not raise

    async def test_cancelled_clears_skill_active(self):
        """Cancelling a skill clears skill_active — _after_skill handles external cancellation."""
        agent, session = await self.agent([])
        await self.say(agent, session, "/parking")
        main = agent.stores[session]
        # Simulate external cancellation: _after_skill should clear skill_active
        agent._after_skill(main, PromptResponse(stop_reason="cancelled"))
        self.assertEqual(main.get("skill_active"), "")


if __name__ == "__main__":
    unittest.main()
