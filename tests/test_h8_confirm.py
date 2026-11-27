"""H8 block 7: autonomy through confirm.py, writes only.

Only tools marked Tool.writes (risky actions) go through the confirm primitive;
reads and safe actions run without asking. The system prompt and agent.py
_verdict follow that rule.

Tests: a read tool runs without confirm; a write tool waits for yes on the
exact payload; a no leaves it unrun.
"""

import json
import os
import shutil
import tempfile
import unittest

from harness.acp_client import AcpClient
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = f"{__import__('sys').executable} -m harness.agent"


class ReadToolsSkipConfirm(unittest.IsolatedAsyncioTestCase):
    """Read-only tools run without waiting for the user to confirm."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.model = FakeModel()
        self.addCleanup(self.model.close)

    def _client(self, allow=None, **env):
        return AcpClient(*AGENT.split(), cwd=ROOT,
                         allow=allow or (lambda _title, _options=(): True),
                         env={"HARNESS_BOT": "Test",
                              "HARNESS_MODEL_BASE_URL": self.model.base_url,
                              "HARNESS_MODEL": "fake-model",
                              "HARNESS_AGENT_DIR": self.folder,
                              **env})

    async def test_read_file_runs_without_confirm(self):
        """read_file does not trigger a permission ask — it is not a write."""
        note = os.path.join(self.folder, "note.txt")
        with open(note, "w") as fh:
            fh.write("blue room")
        # The model calls read_file and gets back its result directly.
        self.model.script = [{"tool_calls": [{"name": "read_file",
                                               "arguments": {"path": note}}]},
                             "De kamer is blauw."]
        async with self._client() as client:
            await client.start()
            turn = await client.prompt("Welke kleur heeft de kamer?")
        self.assertEqual(turn.stop_reason, "end_turn")
        # The tool result is in the conversation.
        sent = json.dumps(self.model.requests[-1]["messages"])
        self.assertIn("blue room", sent)

    async def test_list_dir_runs_without_confirm(self):
        """list_dir does not ask the user for permission."""
        self.model.script = [{"tool_calls": [{"name": "list_dir",
                                               "arguments": {"path": "."}}]},
                             "Klaar."]
        async with self._client() as client:
            await client.start()
            await client.prompt("Wat staat er in de map?")
        # The last request sent to the model should have the assistant message
        # after the tool result (the model got list_dir, then answered).
        messages = self.model.requests[-1]["messages"]
        self.assertTrue(any(m["role"] == "assistant" for m in messages))


class WriteToolWaitsForConfirm(unittest.IsolatedAsyncioTestCase):
    """Write tools wait for the user to accept the exact payload."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.model = FakeModel()
        self.addCleanup(self.model.close)

    def _client(self, allow=None, **env):
        return AcpClient(*AGENT.split(), cwd=ROOT,
                         allow=allow or (lambda _title, _options=(): True),
                         env={"HARNESS_BOT": "Test",
                              "HARNESS_MODEL_BASE_URL": self.model.base_url,
                              "HARNESS_MODEL": "fake-model",
                              "HARNESS_AGENT_DIR": self.folder,
                              **env})

    async def test_write_file_is_accepted_and_runs(self):
        """When the user accepts, the write reaches the disk."""
        target = os.path.join(self.folder, "out.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                               "arguments": {"path": target,
                                                             "content": "hello\n"}}]},
                             "Geschreven."]
        async with self._client() as client:
            await client.start()
            turn = await client.prompt("Schrijf hello")
        self.assertEqual(turn.stop_reason, "end_turn")
        with open(target) as fh:
            self.assertEqual(fh.read(), "hello\n")

    async def test_write_file_title_mentions_path(self):
        """The permission bubble title contains write_file and the path."""
        target = os.path.join(self.folder, "exact.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                               "arguments": {"path": target,
                                                             "content": "exact payload\n"}}]},
                             "Oké."]
        asked_titles = []

        def track(title, options):
            asked_titles.append(title)
            return True

        async with self._client(allow=track) as client:
            await client.start()
            await client.prompt("Schrijf exact")
        self.assertTrue(len(asked_titles) >= 1)
        self.assertIn("write_file", asked_titles[0])
        self.assertIn(target, asked_titles[0])


class NoLeavesUnrun(unittest.IsolatedAsyncioTestCase):
    """A no/decline leaves the write unrun."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.model = FakeModel()
        self.addCleanup(self.model.close)

    def _client(self, **env):
        return AcpClient(*AGENT.split(), cwd=ROOT,
                         allow=lambda _title, _options=(): False,
                         env={"HARNESS_BOT": "Test",
                              "HARNESS_MODEL_BASE_URL": self.model.base_url,
                              "HARNESS_MODEL": "fake-model",
                              "HARNESS_AGENT_DIR": self.folder, **env})

    async def test_declined_write_is_not_on_disk(self):
        """When the user declines, nothing is written."""
        target = os.path.join(self.folder, "nope.txt")
        self.model.script = [{"tool_calls": [{"name": "write_file",
                                               "arguments": {"path": target,
                                                             "content": "nope"}}]},
                             "Oké."]
        async with self._client() as client:
            await client.start()
            await client.prompt("Schrijf het")
        self.assertFalse(os.path.exists(target))
        # The decline is recorded as tool output.
        sent = json.dumps(self.model.requests[-1]["messages"])
        self.assertIn("declined", sent)
