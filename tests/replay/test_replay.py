"""Replay recorded backend events through the agent and the bubble."""

import glob
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from botwidget.acplink import _append_message
from botwidget.markdown import plain_text
from harness.agent.agent import LeanAgent
from harness.agent.store import SessionStore
from harness.stream_text import fold_chunk, note_raw, outside_checkout, play, steps_from_log
from tests.test_h7_diffs import _Conn


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))


def fixtures():
    paths = glob.glob(os.path.join(HERE, "*.json"))
    extra = os.environ.get("BOTWIDGET_REPLAY_DIR", "").strip()
    if extra:
        paths.extend(glob.glob(os.path.join(os.path.expanduser(extra), "*.json")))
    return sorted(paths)


def script_for(step):
    events = []
    for event in step:
        kind = event.get("kind")
        if kind in ("text", "final"):
            events.append(("text", event.get("text") or ""))
        elif kind == "tool":
            name = event.get("name") or ""
            events.append(("tool_calls", [{"id": name, "function": {"name": name, "arguments": "{}"}}]))
        elif kind == "finish":
            events.append(("finish", event.get("reason") or "stop"))
        elif kind == "usage":
            events.append(("usage", event.get("usage") or {}))
    return events or [("finish", "stop")]


def widget_text(chunks) -> str:
    messages = []
    for chunk in chunks:
        _append_message(messages, "bot", chunk, fold=True)
    return messages[-1]["text"] if messages else ""


class Replay(unittest.IsolatedAsyncioTestCase):
    """Should show the fixture's bubble text after the real agent and the bubble join."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    async def _run(self, fixture):
        skill_root = os.path.join(self.tmp, "skills")
        if fixture.get("skill"):
            folder = os.path.join(skill_root, "parking")
            os.makedirs(folder)
            with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write("---\nname: parking\ndescription: Book a parking bay\n---\nSTEP ONE: book it\n")
        patched = mock.patch.dict(os.environ, {"HARNESS_CONTEXT_PATHS": skill_root if fixture.get("skill") else ""})
        patched.start()
        self.addCleanup(patched.stop)
        from tests.test_h7_diffs import ScriptModel
        conn = _Conn()
        agent = LeanAgent("Ada", ScriptModel([script_for(step) for step in fixture["steps"]]),
                          folder=os.path.join(self.tmp, "bot-" + os.urandom(4).hex()))
        agent.on_connect(conn)
        session = (await agent.new_session(cwd=self.tmp)).session_id
        await agent.prompt(session, [type("Block", (), {"text": fixture["user"]})()])
        chunks = []
        for _session, update in conn.updates:
            if getattr(update, "session_update", "") == "agent_message_chunk":
                chunks.append(update.content.text)
        return "".join(chunks), chunks

    async def test_every_fixture_matches_the_bubble(self):
        """Should replay each saved transcript through the agent and the widget join."""
        found = [path for path in fixtures() if os.path.basename(path) != "capture.json"]
        self.assertGreaterEqual(len(found), 4)
        for path in found:
            with self.subTest(path=os.path.basename(path)):
                with open(path, encoding="utf-8") as fh:
                    fixture = json.load(fh)
                bubble = fixture["bubble"]
                self.assertEqual(play(fixture["steps"]), bubble)
                text, chunks = await self._run(fixture)
                self.assertEqual(text, bubble)
                self.assertEqual(widget_text(chunks), bubble)
                if not any(event.get("kind") == "nudge" for step in fixture["steps"] for event in step):
                    raw = [event["text"] for step in fixture["steps"] for event in step
                           if event.get("kind") in ("text", "final")]
                    self.assertEqual(widget_text(raw), bubble)

    def test_the_glued_sentinel_is_the_notforme_glitch_before_the_stage(self):
        """Should still explain the old bubble spelling, on the synthetic sentence only."""
        with open(os.path.join(HERE, "notformenotforme.json"), encoding="utf-8") as fh:
            fixture = json.load(fh)
        self.assertIn("notformenotforme", plain_text(fixture_text(fixture)).replace(" ", ""))
        self.assertNotIn("notforme", plain_text(play(fixture["steps"])))

    def test_a_trailing_wait_for_user_is_the_same_leak(self):
        """Should drop a glued wait_for_user the way not_for_me is dropped."""
        self.assertEqual(fold_chunk("Booked.", "wait_for_user"), "Booked.")
        self.assertEqual(fold_chunk("Booked.", "waitforuser"), "Booked.")

    def test_a_log_becomes_steps_and_stays_out_of_the_checkout(self):
        """Should prefer the model source, and refuse a log path inside the checkout."""
        log = "\n".join([
            json.dumps({"source": "acp", "kind": "text", "text": "already clean"}),
            json.dumps({"source": "model", "kind": "step"}),
            json.dumps({"source": "model", "kind": "text", "text": "Bay 4 is free.not_for_me"}),
        ])
        steps = steps_from_log(log)
        self.assertEqual(play(steps), "Bay 4 is free.")
        self.assertFalse(outside_checkout(os.path.join(ROOT, "leak.json")))
        self.assertTrue(outside_checkout(os.path.join(tempfile.gettempdir(), "botwidget-replay", "leak.json")))
        inside = os.path.join(self.tmp, "inside.jsonl")
        # self.tmp is outside the checkout. A path under ROOT is refused.
        os.environ["BOTWIDGET_REPLAY_LOG"] = os.path.join(ROOT, "tests", "replay", "private.jsonl")
        self.addCleanup(os.environ.pop, "BOTWIDGET_REPLAY_LOG", None)
        note_raw({"kind": "text", "text": "secret"})
        self.assertFalse(os.path.exists(os.path.join(ROOT, "tests", "replay", "private.jsonl")))
        os.environ["BOTWIDGET_REPLAY_LOG"] = inside
        note_raw({"source": "model", "kind": "text", "text": "hello"})
        with open(inside, encoding="utf-8") as fh:
            self.assertIn("hello", fh.read())
        from scripts.replay_capture import write_fixture
        with self.assertRaises(SystemExit):
            write_fixture([[{"kind": "text", "text": "secret"}]], os.path.join(ROOT, "secret.json"), None, "replay")
        out = os.path.join(self.tmp, "captured.json")
        self.assertEqual(write_fixture(steps_from_log(log), out, None, "replay"), "Bay 4 is free.")
        self.assertTrue(outside_checkout(out))

    def test_a_session_folder_is_a_transcript_of_final_answers(self):
        """Should turn stored bot lines into final events the stage can replay."""
        from scripts.replay_capture import steps_from_session
        folder = os.path.join(self.tmp, "session")
        store = SessionStore(folder)
        store.add("user", "hello")
        store.add("bot", "Bay 4 is free.")
        store.close()
        steps = steps_from_session(folder)
        self.assertEqual(play(steps), "Bay 4 is free.")


def fixture_text(fixture) -> str:
    return "".join(event.get("text") or "" for step in fixture["steps"] for event in step
                   if event.get("kind") in ("text", "final"))
