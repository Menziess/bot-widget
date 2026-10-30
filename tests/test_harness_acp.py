"""Phase 0: the spike's promises, checked against a real ACP conversation over stdio."""

import asyncio
import os
import sys
import unittest

from harness.acp_client import AcpClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = [sys.executable, os.path.join(ROOT, "tests", "fake_acp_agent.py")]


class AcpConversation(unittest.IsolatedAsyncioTestCase):
    async def talk(self, text: str, allow=None):
        client = AcpClient(*FAKE, cwd=ROOT, allow=allow)
        async with client:
            info = await client.start()
            turn = await client.prompt(text)
        return client, info, turn

    async def test_thoughts_and_answer_chunks_arrive_in_the_order_the_agent_sent_them(self):
        _client, info, turn = await self.talk("hello")
        self.assertEqual(info["protocol"], 1)
        self.assertTrue(info["session"], "the agent opened a session")
        self.assertEqual([update.kind for update in turn.updates], ["thought", "text", "text"])
        self.assertEqual(turn.updates[0].text, "Reading the question")
        self.assertIn("Answer hello", turn.updates[1].text)

    async def test_the_first_update_is_timed_so_the_face_knows_how_long_it_waited(self):
        _client, _info, turn = await self.talk("hello")
        self.assertGreater(turn.first_update, turn.started)
        self.assertGreaterEqual(turn.total_ms, turn.first_update_ms)

    async def test_a_permission_request_can_be_allowed(self):
        _client, _info, turn = await self.talk("please ask", allow=lambda _title: True)
        self.assertEqual([update.text for update in turn.updates], ["chose yes"])

    async def test_a_permission_request_is_declined_by_default(self):
        _client, _info, turn = await self.talk("please ask")
        self.assertEqual([update.text for update in turn.updates], ["chose no"], "nothing is allowed unasked")

    async def test_a_running_turn_is_cancelled_and_ends_with_that_stop_reason(self):
        client = AcpClient(*FAKE, cwd=ROOT)
        async with client:
            await client.start()
            turn = asyncio.create_task(client.prompt("slow down"))
            await asyncio.sleep(0.2)
            await client.cancel()
            result = await asyncio.wait_for(turn, timeout=5)
        self.assertEqual(result.stop_reason, "cancelled")
        self.assertLess(result.total_ms, 2000, "cancel must not wait for the rest of the turn")

    async def test_a_refused_turn_says_why(self):
        _client, _info, turn = await self.talk("this will fail")
        self.assertEqual(turn.stop_reason, "refusal")
        self.assertEqual(turn.error, "")


if __name__ == "__main__":
    unittest.main()
