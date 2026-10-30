"""Phase 1: an ACP agent behind the calls the face already makes, driven by the fake agent."""

import os
import sys
import time
import unittest

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


class AcpTurns(unittest.TestCase):
    def link(self) -> AcpLink:
        link = AcpLink(FAKE)
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
