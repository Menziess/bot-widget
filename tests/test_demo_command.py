"""The /demo command is dev-only and ticks from checkers, not from the in-process demo."""

import os
import tempfile
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

    def test_should_see_dev_when_the_parent_is_the_supervisor(self):
        """Should count a child as dev when its parent is the --dev supervisor, even without BOTWIDGET_DEV."""
        from botwidget.demo_chat import dev_running
        pidfile = os.path.join(tempfile.gettempdir(), "bot-widget-dev-test.pid")
        with open(pidfile, "w") as fh:
            fh.write(str(os.getppid()))
        self.addCleanup(lambda: os.path.exists(pidfile) and os.remove(pidfile))
        env = {"BOTWIDGET_DEV_PID": pidfile}
        env.pop("BOTWIDGET_DEV", None)
        with mock.patch("sys.argv", ["botwidget"]), mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("BOTWIDGET_DEV", None)
            self.assertTrue(dev_running())
        with mock.patch("sys.argv", ["botwidget"]), mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("botwidget.demo_chat._parent_runs_dev", return_value=True):
            os.environ.pop("BOTWIDGET_DEV", None)
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
        from botwidget.demo_chat import Session
        sent = []
        session = Session()
        session.tick(True, sent.append)
        self.assertEqual(len(sent), 1)
        self.assertIn("Demo task browser", sent[0])
        session.tick(False, sent.append)
        self.assertEqual(len(sent), 1, "a busy chat does not take the next task")

    def test_the_checklist_is_text_for_the_bubble_with_one_line_per_chat_task(self):
        from botwidget.demo_chat import LABELS, Session
        session = Session()
        session.board.consider("files", {"checked": True, "ok": True, "detail": "match"})
        session.board.consider("browser", {"checked": True, "ok": False, "blocked": "not checked from the chat"})
        text = session.summary()
        self.assertIn("1 of %d ticked" % len(LABELS), text)
        self.assertIn("✔ Files: write, then read back: match", text)
        self.assertIn("✘ Browser: reuse a tab over CDP: not checked from the chat", text)
        self.assertIn("✘ Script: write it and run it: not run", text)
        self.assertEqual(text.count("\n- "), len(LABELS))

    def test_the_checklist_opens_in_the_bubble_only_after_the_last_task(self):
        from botwidget import demo_chat
        face = mock.Mock(_working=False, _sending=False)
        face._outbox.items = []
        face._latest.return_value = {"messages": []}
        with mock.patch("PySide6.QtCore.QTimer.singleShot", side_effect=lambda _ms, call: call()), \
                mock.patch.object(demo_chat, "check", return_value={"checked": True, "ok": True, "detail": "ok"}):
            demo_chat.begin(face)
        self.assertEqual(face.on_user_message.call_count, len(demo_chat.PROMPTS))
        face.bubble.show_blocks.assert_called_once()
        self.assertEqual(face.bubble.show_blocks.call_args.args[1], "say")
        face.pin.assert_called_once()

    def test_the_browser_row_ticks_on_the_number_only_chrome_can_tell(self):
        from botwidget import demo_chat
        chrome = mock.Mock()
        chrome.list_tabs.return_value = [{}, {}, {}]
        with mock.patch("harness.browser_local.attach", return_value=chrome):
            self.assertTrue(demo_chat.check("browser", "3")["ok"])
            self.assertTrue(demo_chat.check("browser", "There are 3 tabs.")["ok"])
            self.assertFalse(demo_chat.check("browser", "5")["ok"])
            self.assertFalse(demo_chat.check("browser", "no idea")["ok"])
        with mock.patch("harness.browser_local.attach", side_effect=ConnectionError("down")):
            self.assertEqual(demo_chat.check("browser", "3")["blocked"], "Chrome is not listening")

    def test_the_computer_row_is_checked_by_code_after_the_chat_tasks_without_a_prompt(self):
        from botwidget import demo_chat
        sent = []
        session = demo_chat.Session()
        with mock.patch.object(demo_chat, "check", return_value={"checked": True, "ok": True, "detail": "ok"}):
            while not session.done():
                session.tick(True, sent.append)
        self.assertEqual(len(sent), len(demo_chat.PROMPTS))
        self.assertTrue(session.board.ticked("computer"))
        self.assertNotIn("computer", " ".join(sent).lower().split("demo task")[-1][:20])
