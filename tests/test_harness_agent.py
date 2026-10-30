"""Phase 2: the lean agent's promises, against a fake model and a fake ACP client.

The widget is replaced by `harness.acp_client`, the model by `tests.fake_model`, so nothing here
needs a real model, a provider key or a network beyond localhost.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from harness.acp_client import AcpClient
from harness.agent import context
from harness.agent.store import SessionStore
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = f"{sys.executable} -m harness.agent"


class Store(unittest.TestCase):
    def test_a_restart_opens_the_same_conversation(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        first = SessionStore(folder)
        first.add("user", "Klaar?")
        first.add("bot", "Ja.")
        first.set_summary("They agreed on the plan.")
        first.close()
        again = SessionStore(folder)
        self.addCleanup(again.close)
        self.assertEqual([m["text"] for m in again.messages()], ["Klaar?", "Ja."])
        self.assertEqual(again.summary, "They agreed on the plan.")

    def test_a_usage_line_is_one_json_object_per_turn(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.addCleanup(store.close)
        store.usage({"bot": "Test", "ms": 12})
        store.usage({"bot": "Test", "ms": 34})
        lines = [json.loads(line) for line in open(os.path.join(folder, "usage.jsonl"))]
        self.assertEqual([line["ms"] for line in lines], [12, 34])


class Context(unittest.TestCase):
    def store(self, messages: int) -> SessionStore:
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.addCleanup(store.close)
        for step in range(messages):
            store.add("user" if step % 2 == 0 else "bot", f"line {step}")
        return store

    def test_the_prefix_is_the_same_every_turn_so_a_provider_can_cache_it(self):
        store = self.store(4)
        first = context.build(store, "T")
        store.add("user", "and now?")
        second = context.build(store, "T")
        self.assertEqual(first[0], second[0], "the system line never changes")
        self.assertEqual([message["content"] for message in first], [m["content"] for m in second[:len(first)]])

    def test_the_summary_and_the_facts_ride_along_with_the_recent_turns(self):
        store = self.store(4)
        store.set_summary("They like short answers.")
        store.set("facts", "The bot is called Test.")
        built = context.build(store, "T")
        self.assertIn("They like short answers.", built[1]["content"])
        self.assertIn("The bot is called Test.", built[2]["content"])
        self.assertEqual(built[-1]["content"], "line 3")

    def test_only_the_older_half_is_summarised_and_the_newest_turns_are_left_alone(self):
        store = self.store(context.SUMMARY_AFTER + 4)
        older = context.to_summarise(store)
        kept = context.KEEP_TURNS * 2
        self.assertEqual(len(older), context.SUMMARY_AFTER + 4 - kept,
                         "everything before the part that stays verbatim")
        self.assertEqual(older[0]["text"], "line 0")
        store.set("summary_upto", "4")
        self.assertEqual(context.to_summarise(store)[0]["text"], "line 4", "a second pass goes on where it stopped")


class Turns(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.model = FakeModel("Antwoord in twee woorden.")
        self.addCleanup(self.model.close)
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def client(self) -> AcpClient:
        return AcpClient(*AGENT.split(), cwd=ROOT,
                         env={"HARNESS_BOT": "Test", "HARNESS_MODEL_BASE_URL": self.model.base_url,
                              "HARNESS_MODEL": "fake-model", "HARNESS_AGENT_DIR": self.folder})

    async def test_a_turn_streams_the_answer_and_writes_a_usage_line(self):
        async with self.client() as client:
            await client.start()
            turn = await client.prompt("Hallo")
        self.assertEqual(turn.stop_reason, "end_turn")
        self.assertEqual("".join(update.text for update in turn.updates if update.kind == "text"),
                         "Antwoord in twee woorden. ")
        usage = [json.loads(line) for line in open(os.path.join(self.folder, "usage.jsonl"))]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["model"], "fake-model")
        self.assertEqual(usage[0]["bot"], "Test")
        self.assertGreater(usage[0]["output_tokens"], 0)
        self.assertGreater(usage[0]["first_ms"], 0, "the time to the first word is measured")

    async def test_a_restart_keeps_the_conversation_and_sends_it_again(self):
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("Mijn naam is Stefan.")
        again = self.client()
        async with again:
            await again.start()
            restored = []
            again.on_update = lambda update: restored.append(update.text)
            await again.conn.load_session(cwd=ROOT, session_id=session, mcp_servers=[])
            self.assertIn("Mijn naam is Stefan.", "".join(restored))
            await again.prompt("En nu?")
        last_request = self.model.requests[-1]
        sent = [message["content"] for message in last_request["messages"]]
        self.assertIn("Mijn naam is Stefan.", sent, "the earlier turn is part of the next request")

    async def test_a_local_and_a_hosted_provider_use_the_same_adapter(self):
        hosted = FakeModel("Van de hosted provider.")
        self.addCleanup(hosted.close)
        client = AcpClient(*AGENT.split(), cwd=ROOT,
                           env={"HARNESS_BOT": "Test", "HARNESS_MODEL_BASE_URL": hosted.base_url,
                                "HARNESS_MODEL": "hosted-model", "HARNESS_MODEL_API_KEY": "sk-test",
                                "HARNESS_AGENT_DIR": self.folder})
        async with client:
            await client.start()
            turn = await client.prompt("Hallo")
        self.assertEqual(turn.stop_reason, "end_turn")
        self.assertIn("Van de hosted provider.", "".join(update.text for update in turn.updates))
        self.assertEqual(hosted.headers[-1].get("Authorization"), "Bearer sk-test")

    async def test_a_summary_never_delays_the_turn_that_triggers_it(self):
        self.model.slow_complete = 3.0  # a summary that takes three seconds
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("first")
            # Fill the file past the threshold, as a long conversation would.
            store = SessionStore(self.folder)
            for step in range(context.SUMMARY_AFTER + 2):
                store.add("user" if step % 2 == 0 else "bot", f"line {step}")
            store.close()
            started = time.monotonic()
            turn = await client.prompt("and the next one?")
            took = time.monotonic() - started
            self.assertEqual(turn.stop_reason, "end_turn")
            self.assertLess(took, 2.0, "the answer comes back while the summary is still running")
            # The agent process has to stay up for the background summary to finish.
            deadline = time.monotonic() + 10
            summary = ""
            while time.monotonic() < deadline and not summary:
                await asyncio.sleep(0.1)
                store = SessionStore(self.folder)
                summary = store.summary
                store.close()
            self.assertEqual(session, client.session_id)
        self.assertTrue(summary, "the summary lands in the background, between turns")


if __name__ == "__main__":
    unittest.main()
