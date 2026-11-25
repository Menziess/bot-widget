"""The bubble shows the model's final text once, and not a trailing tool-call echo."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from botwidget.acplink import _append_message
from botwidget.markdown import plain_text
from harness.agent.agent import LeanAgent
from tests.test_h7_diffs import ScriptModel, _Conn


def shown(conn) -> str:
    parts = []
    for _session, update in conn.updates:
        if getattr(update, "session_update", "") == "agent_message_chunk":
            parts.append(update.content.text)
    return "".join(parts)


class FoldedBubble(unittest.TestCase):
    """Should fold chunks the way the bubble stores them."""

    def test_a_doubled_sentinel_reads_as_notformenotforme_until_it_is_folded(self):
        """Should show why the bubble used to end in notformenotforme, and not after the fold."""
        raw = "beschikbaar in deze chat.not_for_menot_for_me"
        self.assertIn("notformenotforme", plain_text(raw).replace(" ", ""))
        messages = []
        _append_message(messages, "bot", "beschikbaar in deze chat.", fold=True)
        _append_message(messages, "bot", "not_for_me", fold=True)
        _append_message(messages, "bot", "not_for_me", fold=True)
        self.assertEqual(messages, [{"role": "bot", "text": "beschikbaar in deze chat."}])
        self.assertNotIn("notforme", plain_text(messages[0]["text"]))

    def test_a_repeated_final_chunk_is_the_answer_once(self):
        """Should replace a short prefix when the next chunk is the whole answer again."""
        messages = []
        final = "De tools zijn beschikbaar in deze chat."
        _append_message(messages, "bot", "De tools", fold=True)
        _append_message(messages, "bot", final, fold=True)
        _append_message(messages, "bot", final, fold=True)
        self.assertEqual(messages[0]["text"], final)


class AnswerText(unittest.IsolatedAsyncioTestCase):
    """Should render the final answer once, with no not_for_me sentinel."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    async def agent(self, scripts, skills=""):
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": skills})
        patched.start()
        self.addCleanup(patched.stop)
        conn = _Conn()
        agent = LeanAgent("Ada", ScriptModel(scripts), folder=os.path.join(self.tmp, "bot"))
        agent.on_connect(conn)
        session = (await agent.new_session(cwd=self.tmp)).session_id
        return agent, conn, session

    async def say(self, agent, session, text):
        await agent.prompt(session, [type("Block", (), {"text": text})()])

    async def test_cumulative_chunks_and_a_repeated_final_message_show_once(self):
        """Should keep the model's final text once when a later chunk repeats it."""
        final = "De tools zijn beschikbaar in deze chat."
        agent, conn, session = await self.agent([[
            ("text", "De tools"),
            ("text", final),
            ("text", final),
        ]])
        await self.say(agent, session, "Kun je mijn computer besturen?")
        self.assertEqual(shown(conn), final)
        self.assertEqual(agent.stores[session].messages()[-1]["text"], final)

    async def test_a_skill_nudge_does_not_glue_not_for_me_onto_the_answer(self):
        """Should drop the not_for_me echo a skill nudge appends, once or twice."""
        skill = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w") as fh:
            fh.write("---\nname: parking\ndescription: Book a parking ticket\n---\nSTEP ONE: book it\n")
        final = "De tools zijn beschikbaar in deze chat."
        agent, conn, session = await self.agent([
            [("text", final), ("finish", "stop")],
            [("text", "not_for_me"), ("finish", "stop")],
            [("text", "not_for_me"), ("finish", "stop")],
        ], skills=os.path.join(self.tmp, "skills"))
        await self.say(agent, session, "/parking")
        text = shown(conn)
        self.assertEqual(text, final)
        self.assertNotIn("not_for_me", text)
        self.assertNotIn("notforme", text)
        self.assertEqual(agent.stores[session].messages()[-1]["text"], final)

    @staticmethod
    def tool(name):
        return ("tool_calls", [{"id": name, "function": {"name": name, "arguments": "{}"}}])

    async def test_a_not_for_me_nudge_hides_its_sentence_and_another_tool_shows_one(self):
        """Should leave the shown answer unchanged when a nudge's only tool is not_for_me, and show a sentence that arrives with another tool."""
        skill = os.path.join(self.tmp, "skills", "parking")
        os.makedirs(skill)
        with open(os.path.join(skill, "SKILL.md"), "w") as fh:
            fh.write("---\nname: parking\ndescription: Book a parking ticket\n---\nSTEP ONE: book it\n")
        final = "De tools zijn beschikbaar in deze chat."
        sentence = "Dit bericht hoort niet bij deze skill."
        agent, conn, session = await self.agent([
            [("text", final), ("finish", "stop")],
            [("text", sentence), self.tool("not_for_me")],
            [("finish", "stop")],
        ], skills=os.path.join(self.tmp, "skills"))
        await self.say(agent, session, "/parking")
        self.assertEqual(shown(conn), final)
        stored = " ".join(message["text"] for message in agent.stores[session].messages())
        stored += " ".join(message["text"] for message in agent._skill_store().messages())
        self.assertNotIn(sentence, stored)
        logged = os.path.join(self.tmp, "bot", "skill", "usage.jsonl")
        with open(logged) as fh:
            tails = [json.loads(line)["last_step"]["text_tail"] for line in fh]
        self.assertIn(sentence, tails)

        other = "Geboekt voor vrijdag."
        agent, conn, session = await self.agent([
            [("text", "Ik kijk."), ("finish", "stop")],
            [("text", other), self.tool("done")],
        ], skills=os.path.join(self.tmp, "skills"))
        await self.say(agent, session, "/parking vrijdag")
        self.assertIn("Ik kijk.", shown(conn))
        self.assertIn(other, shown(conn))
        self.assertIn(other, agent.stores[session].messages()[-1]["text"])

    async def test_a_glued_sentinel_is_not_part_of_the_final_text(self):
        """Should strip a not_for_me run glued onto the end of one chunk."""
        agent, conn, session = await self.agent([[
            ("text", "Prima.not_for_menot_for_me"),
        ]])
        await self.say(agent, session, "hoi")
        self.assertEqual(shown(conn), "Prima.")
        self.assertEqual(agent.stores[session].messages()[-1]["text"], "Prima.")
