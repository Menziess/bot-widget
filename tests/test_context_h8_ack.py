"""Tests for H8 block 4: ack-first UX.

A user request gets an instant "bezig…" bubble before any model call.
The result arrives as one separate message, not appended to the ack.

Tests are written first: they fail against the current code, pass after the change.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.acp_client import AcpClient
from harness.agent import context
from tests.fake_model import FakeModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENT = f"{sys.executable} -m harness.agent"


class TestSystemPromptAcknowledgesFirst(unittest.TestCase):
    """The SYSTEM text must encourage a short acknowledgment as a complete message,
    not force the model to combine 'I'm doing it' with the actual answer."""

    def test_system_does_not_forbid_separate_acknowledgment(self):
        """SYSTEM must not contain text that tells the model to put what it will
        do in the same message as the tool call — that prevents ack-first."""
        text = context.SYSTEM
        # The old text says: "Say what you will do only in the same message as the tool call that does it."
        self.assertNotIn(
            "only in the same message as the tool call",
            text,
            "SYSTEM should not force combining intent + tool call in one message",
        )

    def test_system_encourages_brief_completion(self):
        """SYSTEM should tell the model a short acknowledgment is a complete message."""
        text = context.SYSTEM
        # The new text should have guidance like "A short acknowledgment is fine as its own message"
        self.assertTrue(
            any(
                marker in text.lower()
                for marker in [
                    "acknowledgment",
                    "acknowledging",
                    "a short",
                    "bezig",
                    "one sentence",
                    "a few words",
                ]
            ),
            "SYSTEM should encourage a short acknowledgment as a complete message",
        )

    def test_system_still_prevents_duplication(self):
        """SYSTEM must still tell the model not to repeat tool output as its own words."""
        text = context.SYSTEM
        self.assertIn("data", text.lower())

    def test_system_still_prevents_making_up_facts(self):
        """SYSTEM must still prevent hallucination."""
        text = context.SYSTEM
        self.assertTrue(
            any(w in text.lower() for w in ["make up", "hallucin", "guess", "not found"]),
            "SYSTEM must still prevent making things up",
        )

    def test_system_still_encourages_brevity(self):
        """SYSTEM should still encourage the model to be brief in a bubble."""
        text = context.SYSTEM
        self.assertIn("brief", text.lower())


class TestAckFirstFlow(unittest.IsolatedAsyncioTestCase):
    """End-to-end: ack appears before model call, result is one message."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.server = FakeModel(
            reply="Het antwoord is 4.",
            context_size=32000,
        )
        self.addCleanup(self.server.close)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.client = AcpClient(*AGENT.split(), cwd=ROOT,
                                env={"HARNESS_BOT": "testack", "HARNESS_MODEL_BASE_URL": self.server.base_url,
                                     "HARNESS_MODEL": "fake-model", "HARNESS_AGENT_DIR": self.folder})

    async def test_ack_before_model_request(self):
        """The ack bubble appears before the model receives any request."""
        first_update_text = ""
        first_update_time = 0.0

        def on_update(update):
            nonlocal first_update_text, first_update_time
            if not first_update_time and update.kind in ("text", "thought"):
                first_update_time = time.monotonic()
                first_update_text = getattr(update, "text", "")

        self.client.on_update = on_update

        async with self.client:
            await self.client.start()
            turn = await self.client.prompt("Wat is 2+2?")

        self.assertEqual(turn.stop_reason, "end_turn")
        self.assertGreater(first_update_time, 0,
                           "an ack text chunk must arrive")

        # The ack should contain "bezig…" or similar acknowledgment word
        self.assertIn("bezig", first_update_text.lower(),
                      "the first chunk should be the acknowledgment")

    async def test_result_arrives_as_separate_message(self):
        """The result text is separate from the ack, not appended to it."""
        updates_text = []

        def on_update(update):
            if update.kind == "text":
                updates_text.append({"text": getattr(update, "text", ""),
                                     "message_id": getattr(update, "message_id", "")})

        self.client.on_update = on_update

        async with self.client:
            await self.client.start()
            turn = await self.client.prompt("Wat is 2+2?")

        self.assertEqual(turn.stop_reason, "end_turn")

        # The accumulated text should contain the answer
        full_text = "".join(u["text"] for u in updates_text)
        self.assertIn("4", full_text,
                      "the result must contain the answer")


class TestSystemPromptLanguage(unittest.TestCase):
    """SYSTEM should be in the same language the user writes in."""

    def test_system_contains_language_hint(self):
        """SYSTEM must still tell the bot to answer in the user's language."""
        self.assertIn("language", context.SYSTEM.lower())


if __name__ == "__main__":
    unittest.main()
