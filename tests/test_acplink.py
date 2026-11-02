"""Phase 1: an ACP agent behind the calls the face already makes, driven by the fake agent."""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

from botwidget import acplink
from botwidget.acplink import AcpLink

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = f"{sys.executable} {os.path.join(ROOT, 'tests', 'fake_acp_agent.py')}"


def wait_for(condition, timeout: float = 20.0):
    """Wait for something the agent pushes; the link answers from another thread."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


CONFIGURED = {"acp_bots": [
    {"name": "Local Bot", "command": "python -m harness.agent",
     "env": {"HARNESS_MODEL": "local", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1",
             "PATH": "/nope", "api_key": "leak"}, "key_file": "~/.config/llm/key"},
    {"name": "no command"},
    "not an entry",
]}


class Configured(unittest.TestCase):
    """A face per bot in widget.json, with its own command, env and key file."""

    def test_a_configured_bot_becomes_a_face_with_its_command_and_its_harness_env(self):
        with mock.patch.object(acplink, "widget_config", return_value=CONFIGURED):
            bots = acplink.configured_bots()
            self.assertEqual([bot["id"] for bot in bots], ["acp:local-bot"])
            self.assertEqual(bots[0]["name"], "Local Bot")
            self.assertEqual(acplink.target_for("acp:local-bot"), "python -m harness.agent")
            options = acplink.options_for("acp:local-bot")
        self.assertEqual(options["face"], "acp:local-bot")
        self.assertEqual(options["env"], {"HARNESS_MODEL": "local",
                                          "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1"})
        self.assertEqual(options["key_file"], "~/.config/llm/key",
                         "only the path is in widget.json, never the key")

    def test_an_unconfigured_face_falls_back_to_the_settings(self):
        with mock.patch.object(acplink, "widget_config", return_value={"acp_target": "hermes-acp"}):
            self.assertEqual(acplink.target_for("acp:whatever"), "hermes-acp")
            self.assertEqual(acplink.options_for("acp:whatever"), {})

    def test_the_key_is_read_from_its_file_into_the_environment(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        key = os.path.join(folder, "key")
        with open(key, "w") as fh:
            fh.write("sk-from-file\n")
        link = AcpLink("python -m harness.agent", env={"HARNESS_MODEL": "local"}, key_file=key)
        self.addCleanup(link.close)
        self.addCleanup(shutil.rmtree, link.room(), True)
        self.assertEqual(link._environment(),
                         {"HARNESS_MODEL": "local", "HARNESS_MODEL_API_KEY": "sk-from-file"})

    def test_a_key_file_that_cannot_be_read_says_which_file(self):
        link = AcpLink("python -m harness.agent", key_file="/nonexistent/llm/key")
        self.addCleanup(link.close)
        self.addCleanup(shutil.rmtree, link.room(), True)
        with self.assertRaises(RuntimeError) as caught:
            link._environment()
        self.assertIn("/nonexistent/llm/key", str(caught.exception))


class AcpTurns(unittest.TestCase):
    def link(self, **kwargs) -> AcpLink:
        face = "acp:test-" + next(tempfile._get_candidate_names())
        kwargs.setdefault("face", face)
        link = AcpLink(FAKE, **kwargs)
        self.addCleanup(shutil.rmtree, link.room(), True)
        self.addCleanup(link.close)
        return link

    def test_a_message_shows_the_thought_as_activity_and_then_the_answer(self):
        link = self.link()
        ok, error = link.send("slow down")
        self.assertTrue(ok, error)
        self.assertTrue(link.active(), "the face keeps drawing while the turn runs")
        self.assertTrue(wait_for(lambda: link.chat()["activity"].startswith("step 0")))
        link.cancel()
        self.assertTrue(wait_for(lambda: not link.active()))
        chat = link.chat()
        self.assertEqual(chat["activity"], "")
        self.assertEqual([message["role"] for message in chat["messages"]], ["user", "bot"])
        self.assertIn("part 0", chat["messages"][-1]["text"])

    def test_a_restart_loads_the_saved_session(self):
        face = "acp:restart-" + next(tempfile._get_candidate_names())
        first = AcpLink(FAKE, face=face)
        self.addCleanup(shutil.rmtree, first.room(), True)
        first.send("hello")
        self.assertTrue(wait_for(lambda: not first.active()))
        first.close()
        second = AcpLink(FAKE, face=face)
        self.addCleanup(second.close)
        second.send("again")
        self.assertTrue(wait_for(lambda: not second.active()))
        messages = second.chat()["messages"]
        self.assertEqual([message["role"] for message in messages], ["user", "bot"],
                         "the replayed history comes before the new message")
        self.assertIn("restored", messages[1]["text"])

    def test_a_model_error_is_shown_in_the_note_instead_of_a_bare_refusal(self):
        from harness.acp_client import Turn
        link = self.link()

        class Stub:
            async def prompt(self, text):
                return Turn(stop_reason="refusal", error="HTTP 401: invalid api key")

        async def fake_ensure():
            return Stub()

        link._ensure = fake_ensure
        link.send("hoi")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.note(), "HTTP 401: invalid api key")

    def test_a_cancel_with_nothing_running_never_reaches_the_agent(self):
        link = self.link()

        class Stub:
            cancels = 0

            async def cancel(self):
                Stub.cancels += 1

        link._client = Stub()
        link.cancel()
        self.assertEqual(Stub.cancels, 0)
        link._client = None

    def test_a_short_turn_still_leaves_the_answer_and_no_activity(self):
        link = self.link()
        link.send("hello")
        self.assertTrue(wait_for(lambda: not link.active()))
        chat = link.chat()
        self.assertEqual(chat["activity"], "")
        self.assertIn("Answer hello", chat["messages"][-1]["text"])

    def test_a_permission_request_waits_for_the_bubble_and_the_choice_reaches_the_agent(self):
        link = self.link()
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]), "the bubble shows Accept and Decline")
        request = link.attention()["approvals"][0]
        self.assertIn("Write", request["reason"])
        link.decide(request["requestId"], True)
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["messages"][-1]["text"], "chose yes")

    def test_declining_says_no_to_the_agent(self):
        link = self.link()
        link.send("please ask")
        self.assertTrue(wait_for(lambda: link.attention()["approvals"]))
        link.decide(link.attention()["approvals"][0]["requestId"], False)
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["messages"][-1]["text"], "chose no")

    def test_a_running_turn_can_be_cancelled(self):
        link = self.link()
        link.send("slow down")
        self.assertTrue(wait_for(lambda: link.chat()["activity"].startswith("step")))
        link.cancel()
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.note(), "Cancelled.")

    def test_a_failed_turn_says_so_under_the_conversation(self):
        link = self.link()
        link.send("this will fail")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertEqual(link.chat()["failed"], "The model refused to answer.")

    def test_the_context_meter_and_the_compaction_notice_reach_the_note(self):
        from harness.acp_client import Update
        link = self.link()
        link._updated(Update("usage", extra={"used": 80, "size": 100}))
        self.assertEqual(link.note(), "Context 80% full.")
        link._updated(Update("usage", extra={"used": 20, "size": 100}))
        self.assertEqual(link.note(), "", "a roomy context says nothing")
        link._updated(Update("usage", extra={"used": 20, "size": 100, "compacted": True}))
        self.assertEqual(link.note(), "Compacted older turns.")

    def test_an_agent_that_cannot_start_does_not_hang_the_face(self):
        link = AcpLink(f"{sys.executable} -c 'raise SystemExit(1)'")
        self.addCleanup(link.close)
        ok, _error = link.send("hello")
        self.assertTrue(ok, "the message was accepted; the failure comes as a note")
        self.assertTrue(wait_for(lambda: not link.active()))
        self.assertIn("did not start", link.chat()["failed"])
        self.assertTrue(link.stopped)


class AcpFace(unittest.TestCase):
    """An `acp:` id gives a face an ACP link, and nothing else in the face changes."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_face_picks_the_acp_link_for_an_acp_id_and_none_otherwise(self):
        from unittest import mock
        from botwidget.qt_ui import face
        with mock.patch.object(face, "latest_chat", return_value={"messages": [], "activity": ""}), \
                mock.patch.object(face, "automation_ready", return_value=False):
            window = face.FaceWindow("acp:" + FAKE, "T", spot=(300, 400))
            self.addCleanup(window.close_face)
            window._poll_timer.stop()
            self.assertIsNotNone(window.acp)
            self.assertIs(window.link, window.acp)
            self.assertIsNone(window.grok)
            self.assertIsNone(window.hermes)
            self.assertEqual(window._latest(), {"messages": [], "activity": "", "failed": "", "approvals": []})
