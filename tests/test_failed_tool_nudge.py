"""After a tool failed, a closing message that does not say so is nudged once, and nothing guessed shows first."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from harness.agent.agent import FAILED_NUDGE, LeanAgent
from tests.test_harness_direct import Block, Conn, ScriptModel


class Watch(ScriptModel):
    def __init__(self, scripts):
        super().__init__(scripts)
        self.seen = []

    def stream(self, messages, tools=None, stop=None, opened=None):
        self.seen.append(json.dumps(messages))
        return super().stream(messages, tools, stop, opened)


def call(name, **arguments):
    return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": json.dumps(arguments)}}])


class FailedTool(unittest.IsolatedAsyncioTestCase):
    async def run_turn(self, scripts, ask="Wat staat er in nope.txt?"):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        model = Watch(scripts)
        conn = Conn()
        agent = LeanAgent("bot", model, folder=os.path.join(folder, "agent"))
        agent.on_connect(conn)
        with mock.patch.dict(os.environ, {"HARNESS_WORKSPACE": folder}):
            session = (await agent.new_session(cwd=folder)).session_id
            await agent.prompt(session, [Block(ask)])
        shown = "".join(update.content.text for _s, update in conn.updates
                        if getattr(update, "session_update", "") == "agent_message_chunk")
        return model, shown

    async def test_an_answer_from_memory_after_a_failed_read_is_nudged_and_never_shown(self):
        model, shown = await self.run_turn([
            [call("read_file", path="nope.txt"), ("finish", "tool_calls")],
            [("text", "Het bestand bevat: hallo."), ("finish", "stop")],
            [("text", "Het lezen is mislukt: het bestand bestaat niet."), ("finish", "stop")]])
        self.assertIn(FAILED_NUDGE, model.seen[-1])
        self.assertEqual(shown, "Het lezen is mislukt: het bestand bestaat niet.")

    async def test_an_answer_that_owns_up_to_the_failure_needs_no_second_round(self):
        model, shown = await self.run_turn([
            [call("read_file", path="nope.txt"), ("finish", "tool_calls")],
            [("text", "Dat bestand is niet gevonden."), ("finish", "stop")]])
        self.assertEqual(len(model.seen), 2)
        self.assertEqual(shown, "Dat bestand is niet gevonden.")

    async def test_nothing_failed_nothing_nudged(self):
        model, shown = await self.run_turn([[("text", "Hallo."), ("finish", "stop")]])
        self.assertEqual(len(model.seen), 1)
        self.assertEqual(shown, "Hallo.")
