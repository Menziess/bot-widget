"""A skill in HARNESS_CONTEXT_PATHS is a slash command: advertised to the widget, and its text goes to the model
once the user runs it."""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest import mock

from harness.agent import context
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
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


if __name__ == "__main__":
    unittest.main()
