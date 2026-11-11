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


class FirstText(unittest.IsolatedAsyncioTestCase):
    """The number the face shows is when the answer starts, not when anything arrives."""

    async def test_a_usage_update_is_not_the_first_text(self):
        from acp.schema import AgentMessageChunk, TextContentBlock, UsageUpdate
        from harness.acp_client import AcpClient, Turn
        client = AcpClient("x")
        client._turn = Turn(started=time.monotonic())
        await client.session_update(session_id="s", update=UsageUpdate(
            session_update="usage_update", used=10, size=100))
        self.assertEqual(client._turn.first_update, 0, "the meter goes out before the model answers")
        await client.session_update(session_id="s", update=AgentMessageChunk(
            session_update="agent_message_chunk", content=TextContentBlock(type="text", text="hoi")))
        self.assertGreater(client._turn.first_update, 0)


class Defaults(unittest.TestCase):
    def test_the_model_server_reports_its_own_context_size(self):
        from harness.agent.models import ChatCompletions
        server = FakeModel(context_size=4096)
        self.addCleanup(server.close)
        model = ChatCompletions(server.base_url, "fake-model")
        model.ready(timeout=2.0)
        self.assertEqual(model.context_size, 4096)

    def test_props_sends_the_bearer_key(self):
        from harness.agent.models import ChatCompletions
        server = FakeModel(context_size=131072)
        server.require_auth = True
        self.addCleanup(server.close)
        model = ChatCompletions(server.base_url, "fake-model", api_key="sk-test")
        model.ready(timeout=2.0)
        self.assertEqual(model.context_size, 131072, "a keyed /props is what fills the meter")
        bare = ChatCompletions(server.base_url, "fake-model")
        bare.ready(timeout=2.0)
        self.assertEqual(bare.context_size, 0, "without the key the server answers 401 and the guess stays")

    def test_a_server_without_props_keeps_the_guess(self):
        from harness.agent.models import ChatCompletions
        server = FakeModel()
        self.addCleanup(server.close)
        model = ChatCompletions(server.base_url, "fake-model")
        model.ready(timeout=2.0)
        self.assertEqual(model.context_size, 0)

    def test_a_missing_model_server_is_a_sentence_after_seconds_not_a_hang(self):
        import time as clock
        from harness.agent.models import ChatCompletions, ModelError
        model = ChatCompletions("http://127.0.0.1:9/v1", "local")
        started = clock.monotonic()
        with self.assertRaises(ModelError) as caught:
            model.ready(timeout=2.0, wait=30.0)
        self.assertLess(clock.monotonic() - started, 5.0)
        self.assertIn("no model server", str(caught.exception))
        self.assertIn("Connection refused", str(caught.exception))

    def test_a_probe_that_timed_out_on_a_closed_port_is_still_a_missing_server(self):
        """Should not wait out the whole time when the probe timed out only because a refusal is slow, as on Windows."""
        import time as clock
        import urllib.error
        from unittest import mock
        from harness.agent.models import ChatCompletions, ModelError
        model = ChatCompletions("http://127.0.0.1:9/v1", "local")
        started = clock.monotonic()
        with mock.patch.object(ChatCompletions, "_probe", side_effect=urllib.error.URLError(TimeoutError("timed out"))):
            with self.assertRaises(ModelError) as caught:
                model.ready(timeout=0.5, wait=30.0)
        self.assertLess(clock.monotonic() - started, 6.0)
        self.assertIn("Connection refused", str(caught.exception))

    def test_a_server_that_accepts_and_then_answers_is_still_loading(self):
        """Should wait out a first quiet accept, which is the proxy while the model loads."""
        import socket
        import threading
        import time as clock
        from harness.agent.models import ChatCompletions

        gate = threading.Event()
        done = threading.Event()

        def serve():
            server = socket.socket()
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen(5)
            port.append(server.getsockname()[1])
            gate.set()
            seen = 0
            while not done.is_set():
                server.settimeout(0.2)
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                seen += 1
                if seen == 1:
                    clock.sleep(0.6)
                    conn.close()
                    continue
                conn.settimeout(1)
                try:
                    conn.recv(4096)
                except OSError:
                    pass
                body = b"{}"
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n" + body)
                conn.close()
            server.close()

        port = []
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertTrue(gate.wait(2))
        self.addCleanup(done.set)
        model = ChatCompletions(f"http://127.0.0.1:{port[0]}/v1", "local")
        started = clock.monotonic()
        model.ready(timeout=0.2, wait=2.0)
        self.assertLess(clock.monotonic() - started, 2.0)
        self.assertGreater(clock.monotonic() - started, 0.2)

    def test_the_default_model_server_is_the_local_llama_cpp_one(self):
        from harness.agent.models import from_environment
        model = from_environment({})
        self.assertEqual(model.base_url, "http://127.0.0.1:8081/v1")
        self.assertEqual(model.model, "local")


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

    def test_instructions_summary_and_facts_are_system_messages(self):
        from harness.agent import context
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.addCleanup(store.close)
        store.add("user", "Hallo")
        store.add("bot", "Hoi")
        store.set_summary("Zij begroetten elkaar.")
        store.set("facts", "Stefan wil korte antwoorden.")
        store.add("tool", "write_file: declined by the user; nothing was done")
        built = context.build(store, "Test")
        self.assertEqual([message["role"] for message in built],
                         ["system", "system", "system", "user", "assistant", "user"],
                         "a tool outcome rides on a user turn, never as a system line mid-chat")
        self.assertIn("write_file: declined", built[-1]["content"])

    def test_a_limited_read_is_the_newest_messages_in_order(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.addCleanup(store.close)
        for step in range(50):
            store.add("user" if step % 2 == 0 else "bot", f"line {step}")
        self.assertEqual([m["text"] for m in store.messages(limit=4)],
                         ["line 46", "line 47", "line 48", "line 49"])
        self.assertEqual(len(store.messages()), 50)

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
        last = usage[0]["last_step"]
        self.assertEqual(last["calls"], 0)
        self.assertTrue(last["text_tail"].endswith("twee woorden. "), "a turn that ends on talk keeps how it ended")

    async def test_a_turn_cut_off_by_a_restart_is_offered_again_and_answered_without_a_second_user_line(self):
        from harness import RESUME_PROMPT
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("Maak een bestand.")
        store = SessionStore(self.folder)
        self.addCleanup(store.close)
        store.add("user", "Nog een opdracht.")
        store.set("open_turn", "1")  # the process went away in the middle of this turn
        again = self.client()
        async with again:
            info = await again.start(load=session)
            self.assertTrue(info["interrupted"])
            turn = await again.prompt(RESUME_PROMPT)
        self.assertEqual(turn.stop_reason, "end_turn")
        users = [m["text"] for m in store.messages() if m["role"] == "user"]
        self.assertEqual(users, ["Maak een bestand.", "Nog een opdracht."], "the resume prompt is not a message")
        self.assertEqual(store.get("open_turn"), "", "an answered turn is closed")
        async with self.client() as quiet:
            self.assertFalse((await quiet.start(load=session))["interrupted"])

    async def test_a_restart_keeps_the_conversation_and_sends_it_again(self):
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("Mijn naam is Stefan.")
        again = self.client()
        async with again:
            await again.start()
            restored = []
            again.on_update = lambda update: restored.append((update.kind, update.text))
            await again.conn.load_session(cwd=ROOT, session_id=session, mcp_servers=[])
            self.assertIn(("user", "Mijn naam is Stefan."), restored,
                          "the replayed history keeps the user's lines, so the bubble can show them")
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

    async def test_a_cancel_ends_the_turn_while_the_model_is_still_thinking(self):
        self.model.first_delay = 5.0  # a model that has not sent a single token yet
        async with self.client() as client:
            await client.start()
            turn = asyncio.create_task(client.prompt("Hallo"))
            await asyncio.sleep(0.5)
            started = time.monotonic()
            await client.cancel()
            result = await asyncio.wait_for(turn, timeout=5)
            took = time.monotonic() - started
        self.assertEqual(result.stop_reason, "cancelled")
        self.assertLess(took, 1.0, "a cancel is read while the model stream is still open")
        usage = [json.loads(line) for line in open(os.path.join(self.folder, "usage.jsonl"))]
        self.assertTrue(usage[-1]["estimated"], "a cancel before any usage chunk is an estimate, not a measured 0")
        self.assertGreater(usage[-1]["input_tokens"], 0)

    async def test_a_cancel_mid_stream_stops_the_answer_and_says_cancelled(self):
        self.model.first_delay = 0.0
        async with self.client() as client:
            await client.start()
            turn = asyncio.create_task(client.prompt("Hallo"))
            await asyncio.sleep(0.005)
            started = time.monotonic()
            await client.cancel()
            result = await asyncio.wait_for(turn, timeout=5)
            took = time.monotonic() - started
        self.assertEqual(result.stop_reason, "cancelled")
        self.assertLess(took, 1.0)

    async def test_the_context_meter_uses_the_window_the_server_reports(self):
        self.model.context_size = 4096
        seen = []
        client = AcpClient(*AGENT.split(), cwd=ROOT, on_update=seen.append,
                           env={"HARNESS_BOT": "Test", "HARNESS_MODEL_BASE_URL": self.model.base_url,
                                "HARNESS_MODEL": "fake-model", "HARNESS_AGENT_DIR": self.folder})
        async with client:
            await client.start()
            await client.prompt("Hallo")
        sizes = [update.extra["size"] for update in seen if update.kind == "usage"]
        self.assertEqual(sizes[0], 4096, "the meter draws against the server's n_ctx, not a fixed 32000")

    async def test_the_usage_line_times_the_first_word(self):
        self.model.first_delay = 0.3
        async with self.client() as client:
            await client.start()
            await client.prompt("Hallo")
        usage = [json.loads(line) for line in open(os.path.join(self.folder, "usage.jsonl"))]
        self.assertGreaterEqual(usage[-1]["first_ms"], 250,
                                "the first word's delay is measured, not an earlier event")

    async def test_a_cancel_sent_before_the_turn_does_not_cancel_it(self):
        async with self.client() as client:
            await client.start()
            await client.cancel()  # nothing runs yet; this used to land on the next turn
            turn = await client.prompt("Hallo")
        self.assertEqual(turn.stop_reason, "end_turn")
        usage = [json.loads(line) for line in open(os.path.join(self.folder, "usage.jsonl"))]
        self.assertFalse(usage[-1]["cancelled"], "the turn was not cancelled and its summary is not skipped")

    async def test_a_model_server_that_is_not_there_ends_the_turn_in_seconds(self):
        client = AcpClient(*AGENT.split(), cwd=ROOT,
                           env={"HARNESS_BOT": "Test", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:9/v1",
                                "HARNESS_MODEL": "local", "HARNESS_AGENT_DIR": self.folder})
        async with client:
            await client.start()
            started = time.monotonic()
            turn = await client.prompt("Hallo")
        self.assertEqual(turn.stop_reason, "refusal")
        self.assertIn("no model server", turn.error)
        self.assertLess(time.monotonic() - started, 10.0, "a missing server does not hold the bubble for minutes")

    async def test_a_model_error_reaches_the_widget_with_its_reason(self):
        self.model.status = 401
        async with self.client() as client:
            await client.start()
            turn = await client.prompt("Hallo")
        self.assertEqual(turn.stop_reason, "refusal")
        self.assertIn("401", turn.error, "a refusal alone cannot tell a 401 from a bad prompt")

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

