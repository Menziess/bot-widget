"""The /demo command is dev-only and ticks from checkers, not from the in-process demo."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DemoCommand(unittest.TestCase):
    """Should offer /demo only with --dev, and ignore the old enable file."""

    def test_should_hide_demo_unless_dev(self):
        from botwidget import menu_pages
        from botwidget.demo_chat import dev_running
        self.assertNotIn("/demo", [name for name, _note in menu_pages.commands()])
        self.assertIn("/demo", [name for name, _note in menu_pages.commands(dev=True)])
        with mock.patch("sys.argv", ["botwidget"]), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOTWIDGET_DEV", None)
            self.assertFalse(dev_running())
        with mock.patch("sys.argv", ["botwidget", "--dev"]):
            self.assertTrue(dev_running())
        with mock.patch("sys.argv", ["botwidget"]), mock.patch.dict(os.environ, {"BOTWIDGET_DEV": "1"}):
            self.assertTrue(dev_running())

    def test_should_reject_demo_when_not_dev(self):
        from botwidget.qt_ui.face import FaceWindow
        face = FaceWindow.__new__(FaceWindow)
        shown = []
        face.bubble = mock.Mock()
        face.bubble.show_blocks = lambda blocks, kind: shown.append(blocks[0].get("text") or str(blocks))
        with mock.patch("sys.argv", ["botwidget"]), mock.patch.dict(os.environ, {"BOTWIDGET_DEV": ""}):
            face._start_demo()
        self.assertTrue(shown)
        self.assertFalse(hasattr(face, "_demo_session"))

    def test_should_send_prompts_and_not_run_the_in_process_demo(self):
        from botwidget import demo_run
        from botwidget.demo_chat import Session
        sent = []
        session = Session()
        with mock.patch.object(demo_run, "_files", side_effect=AssertionError("ran the task")):
            session.tick(True, sent.append)
        self.assertEqual(len(sent), 1)
        self.assertIn("Demo task browser", sent[0])
        session.tick(False, sent.append)
        self.assertEqual(len(sent), 1, "a busy chat does not take the next task")

    def test_should_ignore_an_enable_file(self):
        from botwidget.qt_ui.demo_board import demo_wanted
        with mock.patch("sys.argv", ["botwidget"]), \
                mock.patch("os.path.exists", return_value=True):
            self.assertFalse(demo_wanted())
        with mock.patch("sys.argv", ["botwidget", "--demo"]):
            self.assertTrue(demo_wanted())
