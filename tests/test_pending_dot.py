"""The notification dot for a stuck relay bot and for a permission that is waiting.

Offscreen Qt. widget.json is a temp file. No network.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config
from botwidget.config import DOT_COLOR
from botwidget.openbot import ApiResult


def _temp_config():
    folder = tempfile.TemporaryDirectory()
    old = config.CONFIG_PATH
    config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
    os.makedirs(folder.name, exist_ok=True)
    with open(config.CONFIG_PATH, "w") as fh:
        json.dump({}, fh)
    config._config_read[:] = [None, {}]
    return folder, old


def _restore_config(folder, old):
    config.CONFIG_PATH = old
    config._config_read[:] = [None, {}]
    folder.cleanup()


class PendingDot(unittest.TestCase):
    """Should light the top-right dot for stuck, needs_you, and a local approval."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.folder, old = _temp_config()
        self.addCleanup(_restore_config, self.folder, old)
        from botwidget.qt_ui.face import FaceWindow
        self.window = FaceWindow("t", "Ada", spot=(300, 400))
        self.window._poll_timer.stop()
        self.window._anim_timer.stop()
        self.window._hint_shown = True
        self.window._latest = lambda: {"messages": [], "activity": ""}
        self.addCleanup(self._close)

    def _close(self):
        self.window.acp = None
        self.window.close_face()

    def _dot_lit(self) -> bool:
        from PySide6.QtGui import QColor, QImage
        from botwidget.qt_ui.face import DOT_SIZE
        self.window.show()
        self.app.processEvents()
        image = QImage(self.window.width(), self.window.height(), QImage.Format_ARGB32)
        image.fill(0)
        self.window.render(image)
        x = self.window.width() - DOT_SIZE // 2 - 2
        y = DOT_SIZE // 2
        return image.pixelColor(x, y).name() == QColor(DOT_COLOR).name()

    def test_should_light_the_dot_for_stuck_and_needs_you_and_clear_it_for_start_and_done(self):
        self.assertFalse(self.window.has_pending)
        self.window.show_live_status("stuck", "looping on a tool")
        self.assertTrue(self.window.has_pending)
        self.assertTrue(self._dot_lit())
        self.assertEqual(self.window.windowTitle(), "Ada · Stuck")
        self.assertEqual(self.window.toolTip(), "looping on a tool")
        self.window.show_live_status("needs_you", "pick a file")
        self.assertTrue(self.window.has_pending)
        self.assertTrue(self._dot_lit())
        self.window.show_live_status("start", "working")
        self.assertFalse(self.window.has_pending)
        self.assertFalse(self._dot_lit())
        self.window.show_live_status("done", "finished")
        self.assertFalse(self.window.has_pending)
        self.assertFalse(self._dot_lit())

    def test_should_keep_the_stuck_dot_when_the_bubble_opens_and_show_the_summary_without_buttons(self):
        self.window.show_live_status("stuck", "looping on a tool")
        self.window.pin()
        self.assertTrue(self.window.has_pending, "looking does not unstick the bot")
        self.window._sync_bubble({"messages": [{"role": "bot", "text": "Hi."}], "activity": ""}, force=True)
        self.app.processEvents()
        self.assertIn("looping on a tool", self.window.bubble.full_text)
        self.assertEqual(self.window.bubble._control_widgets, [])
        self.assertNotIn("Accept", self.window.bubble.full_text)
        self.assertNotIn("Decline", self.window.bubble.full_text)

    def test_should_keep_the_dot_for_a_local_approval_and_show_the_existing_buttons(self):
        self.window.acp = mock.Mock()
        self.window.acp.note.return_value = ""
        self.window.acp.active.return_value = False
        self.window.acp.stopped = False
        self.window.acp.chat.return_value = {"messages": [], "activity": ""}
        self.window._pointer_on_head = lambda: True
        plain = {"requestId": "p1", "reason": "Write a file"}
        self.window._set_attention({"prompts": [], "approvals": [plain], "browserTakeovers": []})
        self.window._sync_pending_dot()
        self.assertTrue(self.window.has_pending)
        self.assertTrue(self._dot_lit())
        self.window._sync_bubble({"messages": [], "activity": "reading"}, force=True)
        self.app.processEvents()
        self.assertEqual([w.text() for w in self.window.bubble._control_widgets], ["Accept", "Decline"])
        offered = {"requestId": "p2", "reason": "shell git status", "always": True}
        self.window._set_attention({"prompts": [], "approvals": [offered], "browserTakeovers": []})
        self.window._sync_bubble({"messages": [], "activity": "reading"}, force=True)
        self.app.processEvents()
        buttons = self.window.bubble._control_widgets
        self.assertEqual([w.text() for w in buttons], ["Accept", "Always allow", "Decline"])
        buttons[0].click()
        self.window.acp.decide.assert_called_once_with("p2", True)
        self.window.acp.reset_mock()
        self.window._set_attention({"prompts": [], "approvals": [offered], "browserTakeovers": []})
        self.window._sync_bubble({"messages": [], "activity": "reading"}, force=True)
        self.window.bubble._control_widgets[1].click()
        self.window.acp.decide.assert_called_once_with("p2", "allow_always")
        self.window.acp.reset_mock()
        self.window._set_attention({"prompts": [], "approvals": [offered], "browserTakeovers": []})
        self.window._sync_bubble({"messages": [], "activity": "reading"}, force=True)
        self.window.bubble._control_widgets[2].click()
        self.window.acp.decide.assert_called_once_with("p2", False)

    def test_should_post_an_openbot_decline_on_the_existing_respond_path(self):
        calls = []

        def post(path, body):
            calls.append((path, body))
            return ApiResult({"ok": True}, 200, "")

        approval = {"requestId": "p9", "kind": "command", "command": "ls", "reason": "list"}
        self.window._pointer_on_head = lambda: True
        self.window._set_attention({"prompts": [], "approvals": [approval], "browserTakeovers": []})
        self.window._sync_pending_dot()
        self.window._sync_bubble({"messages": [], "activity": "reading"}, force=True)
        self.app.processEvents()
        self.assertEqual([w.text() for w in self.window.bubble._control_widgets], ["Accept", "Decline"])
        import threading
        real = threading.Thread

        def immediate(*args, **kwargs):
            thread = real(*args, **kwargs)
            thread.start = thread.run
            return thread

        with mock.patch("botwidget.qt_ui.face.api_post", side_effect=post), \
                mock.patch("botwidget.qt_ui.face.threading.Thread", immediate):
            self.window.bubble._control_widgets[1].click()
        self.assertEqual(calls, [("/v1/agents/t/approvals/p9/respond", {"decision": "decline"})])

    def test_should_keep_a_stuck_dot_when_a_poll_finds_no_local_approval(self):
        self.window.show_live_status("stuck", "loop")

        class Link:
            stopped = False

            def attention(self):
                return {"prompts": [], "approvals": [], "browserTakeovers": []}

            def active(self):
                return False

            def chat(self):
                return {"messages": [], "activity": ""}

            def note(self):
                return ""

            def close(self):
                return None

        self.window.acp = Link()
        self.window._poll_pending()
        self.assertTrue(self.window.has_pending)
        self.window.show_live_status("done", "ok")
        self.window._poll_pending()
        self.assertFalse(self.window.has_pending)
        self.window.acp = None

    def test_should_light_the_dot_from_an_openbot_pending_poll(self):
        pending = {"prompts": [{"requestId": "q"}], "approvals": [], "browserTakeovers": []}
        with mock.patch("botwidget.qt_ui.face.api_get", return_value=pending), \
                mock.patch("botwidget.qt_ui.face.latest_chat", return_value={"messages": [], "activity": ""}):
            self.window._poll_pending()
        self.assertTrue(self.window.has_pending)
        self.assertTrue(self._dot_lit())
