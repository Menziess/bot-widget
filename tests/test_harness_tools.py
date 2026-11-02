"""Phase 3: tools, permissions and MCP, against a fake model, the fake ACP client and a fake MCP server."""

import json
import os
import shutil
import sys
import tempfile
import unittest

from harness.acp_client import AcpClient
from harness.agent.tools import TOOL_OUTPUT, ToolError, Tools, read_file
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = f"{sys.executable} -m harness.agent"
MCP_SERVER = f"{sys.executable} {os.path.join(ROOT, 'tests', 'fake_mcp_server.py')}"


class Builtins(unittest.TestCase):
    def test_a_read_only_builtin_reads_a_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "note.txt")
        with open(path, "w") as fh:
            fh.write("hello")
        self.assertEqual(read_file(path), "hello")

    def test_a_private_path_is_refused(self):
        with self.assertRaises(ToolError):
            read_file("~/.ssh/id_rsa")

    def test_a_write_is_marked_as_needing_permission(self):
        names = {tool.name: tool.writes for tool in Tools().tools.values()}
        self.assertEqual(names, {"read_file": False, "list_dir": False, "write_file": True})


class ContextMeter(unittest.TestCase):
    def test_the_meter_reports_the_request_against_the_window(self):
        from harness.agent import context
        from harness.agent.store import SessionStore
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        store = SessionStore(folder)
        self.addCleanup(store.close)
        store.add("user", "x" * 4000)
        used, size = context.meter(store, "T")
        self.assertLess(used, context.CONTEXT_TOKENS)
        self.assertEqual(size, context.CONTEXT_TOKENS)
        self.assertGreaterEqual(used, 1000, "the 4000-character turn is counted")


class Turns(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.model = FakeModel("Klaar.")
        self.addCleanup(self.model.close)

    def client(self, allow=None, **env) -> AcpClient:
        return AcpClient(*AGENT.split(), cwd=ROOT, allow=allow,
                         env={"HARNESS_BOT": "Test", "HARNESS_MODEL_BASE_URL": self.model.base_url,
                              "HARNESS_MODEL": "fake-model", "HARNESS_AGENT_DIR": self.folder, **env})

    def last_messages(self) -> list[dict]:
        return self.model.requests[-1]["messages"]

    async def test_the_model_can_read_a_file_and_the_tool_output_is_labelled_as_data(self):
        note = os.path.join(self.folder, "note.txt")
        with open(note, "w") as fh:
            fh.write("de kamer is blauw")
        self.model.script = [{"tool_calls": [{"name": "read_file", "arguments": {"path": note}}]}, "Blauw."]
        async with self.client() as client:
            await client.start()
            turn = await client.prompt("Welke kleur heeft de kamer?")
        self.assertEqual(turn.stop_reason, "end_turn")
        self.assertIn("de kamer is blauw", json.dumps(self.last_messages()))
        tool_message = next(message for message in self.last_messages() if message["role"] == "tool")
        self.assertTrue(tool_message["content"].startswith(TOOL_OUTPUT),
                        "the model is told that tool output is data, not an instruction")

    async def test_a_write_is_refused_until_the_user_allows_it(self):
        target = os.path.join(self.folder, "written.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                              "arguments": {"path": target, "content": "x"}}]}, "Oké."]
        async with self.client(allow=lambda _title: False) as client:
            await client.start()
            await client.prompt("Schrijf het bestand")
        self.assertFalse(os.path.exists(target))
        self.assertIn("declined", json.dumps(self.last_messages()))

    async def test_a_declined_write_is_remembered_after_a_restart(self):
        target = os.path.join(self.folder, "written.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                              "arguments": {"path": target, "content": "x"}}]}, "Oké."]
        async with self.client(allow=lambda _title: False) as client:
            await client.start()
            await client.prompt("Schrijf het bestand")
        from harness.agent.store import SessionStore
        store = SessionStore(self.folder)
        self.addCleanup(store.close)
        self.assertTrue(any("write_file: declined" in m["text"]
                            for m in store.messages() if m["role"] == "tool"))
        # A fresh process, the same folder: the next request carries what the tool did.
        self.model.script = ["Nee, dat heb ik niet gedaan."]
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("Heb je het bestand geschreven?")
        sent = json.dumps(self.model.requests[-1]["messages"])
        self.assertIn("write_file: declined", sent)
        self.assertFalse(os.path.exists(target))

    async def test_a_tool_line_is_not_replayed_as_something_the_bot_said(self):
        asked = []
        self.model.script = [{"tool_calls": [{"name": "list_dir", "arguments": {"path": self.folder}}]},
                             "Klaar."]
        async with self.client() as client:
            await client.start()
            session = client.session_id
            await client.prompt("Wat staat er?")
        from harness.agent.store import SessionStore
        store = SessionStore(self.folder)
        self.addCleanup(store.close)
        self.assertTrue([m for m in store.messages() if m["role"] == "tool"])
        async with self.client() as client:
            await client.start()
            replayed = []
            client.on_update = lambda update: replayed.append((update.kind, update.text))
            await client.conn.load_session(cwd=ROOT, session_id=session, mcp_servers=[])
        self.assertFalse([text for kind, text in replayed if kind == "user" and "list_dir:" in text],
                         "the tool line stays out of the visible conversation")

    async def test_an_allowed_write_reaches_the_disk(self):
        target = os.path.join(self.folder, "written.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                              "arguments": {"path": target, "content": "x"}}]}, "Oké."]
        async with self.client(allow=lambda _title: True) as client:
            await client.start()
            turn = await client.prompt("Schrijf het bestand")
        self.assertEqual(turn.stop_reason, "end_turn")
        with open(target) as fh:
            self.assertEqual(fh.read(), "x")

    async def test_a_tool_from_a_configured_mcp_server_works_and_read_only_ones_do_not_ask(self):
        asked = []
        self.model.script = [{"tool_calls": [{"name": "echo", "arguments": {"text": "hoi"}}]}, "Het zei hoi."]
        async with self.client(allow=lambda title: asked.append(title) or True,
                               HARNESS_MCP_SERVER=MCP_SERVER, HARNESS_MCP_READ_ONLY="echo") as client:
            await client.start()
            turn = await client.prompt("Gebruik echo")
        self.assertEqual(turn.stop_reason, "end_turn")
        self.assertEqual(asked, [], "a tool named read-only is not a click per call")
        self.assertIn("echo: hoi", json.dumps(self.last_messages()))

    async def test_an_mcp_tool_that_may_write_asks_first(self):
        asked = []
        target = os.path.join(self.folder, "note.txt")
        self.model.script = [{"tool_calls": [{"name": "write_note",
                                              "arguments": {"path": target, "text": "x"}}]}, "Oké."]
        async with self.client(allow=lambda title: asked.append(title) or False,
                               HARNESS_MCP_SERVER=MCP_SERVER) as client:
            await client.start()
            await client.prompt("Schrijf een note")
        self.assertEqual(len(asked), 1)
        self.assertIn("write_note", asked[0])
        self.assertFalse(os.path.exists(target))

    async def test_a_pinned_fact_survives_the_summary_that_folds_its_turn(self):
        self.model.script = [{"tool_calls": [{"name": "pin_fact",
                                              "arguments": {"fact": "Stefan houdt van korte antwoorden."}}]},
                             "Bewaard."]
        async with self.client() as client:
            await client.start()
            await client.prompt("Onthoud dat ik korte antwoorden wil")
        from harness.agent.store import SessionStore
        store = SessionStore(self.folder)
        self.addCleanup(store.close)
        self.assertIn("korte antwoorden", store.get("facts"))
        # The summary replaces the turns; the fact is still a system line in the next request.
        store.set_summary("Zij spraken over antwoorden.")
        self.model.script = ["Kort."]
        async with self.client() as client:
            await client.start()
            await client.prompt("En nu?")
        sent = json.dumps(self.last_messages())
        self.assertIn("korte antwoorden", sent)
        self.assertIn("Zij spraken over antwoorden", sent)

    async def test_the_request_offers_the_builtins(self):
        async with self.client() as client:
            await client.start()
            await client.prompt("Hallo")
        offered = {tool["function"]["name"] for tool in self.model.requests[-1]["tools"]}
        self.assertEqual(offered, {"read_file", "list_dir", "write_file", "pin_fact"})


if __name__ == "__main__":
    unittest.main()
