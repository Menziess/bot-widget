"""H8 #6: Lazy skill body — the request after /skill carries no full SKILL.md body.

The full body is read only when the model asks for it (via read_file on the skill's path).
store.set('skill') holds name, path and a short summary — not the SKILL.md content.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from harness.agent import context
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from tests.test_h7_diffs import ScriptModel, _Conn


class LazySkillBody(unittest.IsolatedAsyncioTestCase):
    """The full SKILL.md body is not stored in session store; only metadata."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.skill_dir = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(self.skill_dir)
        self.long_body = (
            "STEP ONE: open the Schiphal booking page\n"
            "STEP TWO: enter the date and vehicle details\n"
            "STEP THREE: confirm the booking and save the reference\n\n"
            "Important notes:\n"
            "- Bank card is required\n"
            "- Personnel discount applies\n"
            "Repeat these steps for every booking." * 100
        )
        with open(os.path.join(self.skill_dir, "SKILL.md"), "w") as fh:
            fh.write(
                f"---\nname: parking\ndescription: Book a Schiphol P12 parking ticket\n"
                f"deny-tools: browser_*\n---\n{self.long_body}"
            )
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": os.path.join(self.tmp, "skills")})
        patched.start()
        self.addCleanup(patched.stop)

    def agent(self):
        conn = _Conn()
        agent = LeanAgent("sk", ScriptModel(), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(conn)
        return agent, conn

    async def test_the_store_skill_key_has_no_full_body(self):
        """store.set('skill') does not contain the SKILL.md body — only name, path and a short summary."""
        agent, _ = self.agent()
        store = SessionStore(os.path.join(self.tmp, "bot"))
        agent._run_skill(store, "/parking 2026-11-20")
        stored = store.get("skill")
        # The full body (repeated 100x) is NOT in the stored text.
        # Only the first two lines appear as a short summary.
        self.assertNotIn("Repeat these steps for every booking.STEP ONE", stored)
        # But metadata IS present
        self.assertIn("parking", stored.lower())
        self.assertIn(self.skill_dir, stored)
        self.assertIn("Read the full skill with read_file", stored)

    async def test_the_context_request_has_no_full_body(self):
        """The messages built for the model do not carry the full SKILL.md body."""
        agent, _ = self.agent()
        store = SessionStore(os.path.join(self.tmp, "bot"))
        agent._run_skill(store, "/parking 2026-11-20")
        sent = " ".join(m["content"] for m in context.build(store, "sk"))
        # The full body (repeated 100x) should NOT appear.
        self.assertNotIn("Repeat these steps for every booking.STEP ONE", sent)
        # But metadata should be there
        self.assertIn("parking", sent.lower())
        self.assertIn(self.skill_dir, sent)

    async def test_the_bot_can_read_the_full_body_with_read_file(self):
        """read_file on the skill's path returns the full SKILL.md body."""
        from harness.agent.tools import read_file
        body = read_file(os.path.join(self.skill_dir, "SKILL.md"))
        self.assertIn("STEP ONE: open the Schiphal booking page", body)
        self.assertIn("Bank card is required", body)

    async def test_a_second_skill_run_overwrites_the_metadata(self):
        """Running a different skill replaces the metadata, not appends to it."""
        # Create a second skill
        skill2_dir = os.path.join(self.tmp, "skills", "weather")
        os.makedirs(skill2_dir)
        with open(os.path.join(skill2_dir, "SKILL.md"), "w") as fh:
            fh.write("---\nname: weather\ndescription: Check the weather\n---\nOpen the weather app.")
        # Reload skills as a dict keyed by name
        from harness.agent.workspace import load_skills
        agent, _ = self.agent()
        agent.skills = {s["name"].lower(): s for s in load_skills(os.path.join(self.tmp, "skills"))}

        store = SessionStore(os.path.join(self.tmp, "bot"))
        agent._run_skill(store, "/parking")
        stored = store.get("skill")
        self.assertIn("parking", stored.lower())
        self.assertNotIn("weather", stored.lower())

        agent._run_skill(store, "/weather")
        stored = store.get("skill")
        self.assertIn("weather", stored.lower())
        self.assertNotIn("parking", stored.lower())
        self.assertNotIn("STEP ONE: open the Schiphal booking page", stored)


class LazySkillInTurn(unittest.IsolatedAsyncioTestCase):
    """The full body is absent from the model's prompt after /skill."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.skill_dir = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(self.skill_dir)
        # Use a body where the first line is a description, not a step.
        # The body's unique token (used three times) should not appear in the prompt.
        with open(os.path.join(self.skill_dir, "SKILL.md"), "w") as fh:
            fh.write(
                "---\nname: parking\ndescription: Book a parking ticket\n---\n"
                "Instructions for booking a Schiphol P12 parking ticket.\n\n"
                "STEP ONE: book it. STEP TWO: confirm.\n\n"
                "TOKEN_UNIQUE_XYZ should not appear in the model's prompt" * 3
            )
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": os.path.join(self.tmp, "skills")})
        patched.start()
        self.addCleanup(patched.stop)

    async def test_the_model_prompt_after_skill_has_no_body(self):
        """RecordingModel sees a prompt without the SKILL.md body."""
        from tests.test_harness_skills import RecordingModel

        model = RecordingModel([[("text", "Welke datum?"), ("finish", "stop")]])
        agent = LeanAgent("sk", model, folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(_Conn())
        session = (await agent.new_session(cwd=self.tmp)).session_id
        await agent.prompt(session, [type("Block", (), {"text": "/parking vrijdag"})()])
        prompt_text = model.sent[0]
        # The unique repeated token should NOT appear in the prompt.
        self.assertNotIn("TOKEN_UNIQUE_XYZ", prompt_text)
        # But metadata should be there (description, path, read_file instruction).
        self.assertIn("parking", prompt_text.lower())


if __name__ == "__main__":
    unittest.main()
