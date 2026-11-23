"""The slash list lives under the field. A / button and a right-click open that same list.

There is no second command screen, so the field is never live behind one. While the list
is open the chat text is hidden, and it comes back when the list closes.
"""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config


class SlashButton(unittest.TestCase):
    """Should open one inline command list from the field, and hide the chat text while it shows."""

    def setUp(self):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        self.face = face
        self.app = QApplication.instance() or QApplication([])
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(setattr, config, "CONFIG_PATH", config.CONFIG_PATH)
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        config._config_read[:] = [None, {}]
        self.addCleanup(config._config_read.__setitem__, slice(None), [None, {}])
        old = face.latest_chat
        self.addCleanup(setattr, face, "latest_chat", old)
        face.latest_chat = lambda thread_id, limit=20: {
            "messages": [{"role": "bot", "text": "Hello from the bot."}], "activity": ""}
        self.window = face.FaceWindow("t", "Test", spot=(300, 400))
        self.window._poll_timer.stop()
        self.window._anim_timer.stop()
        self.window._pump_outbox = lambda: None
        self.addCleanup(self.window.close_face)
        self.bubble = self.window.bubble

    def _open_chat(self):
        self.window.show()
        self.window._sync_bubble(self.window._latest(), force=True, show_field=True)
        self.app.processEvents()
        self.bubble._entry.setFocus()

    def _rows(self):
        return [command for command, _note in self.bubble._slash.rows]

    def test_should_keep_the_field_in_front_of_the_only_command_list(self):
        """Should not leave a typeable field behind a command screen. Right-click uses the field's own list."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent
        from PySide6.QtWidgets import QApplication
        self._open_chat()
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertTrue(self.bubble._scroll.isVisibleTo(self.bubble))
        point = QPointF(8, 8)
        QApplication.sendEvent(self.window, QMouseEvent(
            QEvent.MouseButtonPress, point, point, Qt.RightButton, Qt.RightButton, Qt.NoModifier))
        self.assertFalse(hasattr(self.bubble, "_list_only"), "the separate command screen is gone")
        self.assertTrue(self.bubble._entry.isVisibleTo(self.bubble))
        self.assertTrue(self.bubble._slash.isVisibleTo(self.bubble))
        self.assertGreaterEqual(self.bubble._slash.y(), self.bubble._entry.y() + self.bubble._entry.height() - 2)
        self.assertFalse(self.bubble._entry.geometry().intersects(self.bubble._slash.geometry()))
        self.assertFalse(self.bubble._scroll.isVisible())
        self.assertIn("/settings", self._rows())
        from PySide6.QtTest import QTest
        QTest.keyClick(self.bubble._entry, Qt.Key_S)
        self.assertIn("s", self.bubble._entry.text())
        self.assertTrue(self.bubble._entry.isVisibleTo(self.bubble))

    def test_should_open_the_same_list_from_the_slash_button_at_the_right_of_the_field(self):
        """Should put a / button inside the field, at the far right, and open the list under it."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self._open_chat()
        button = self.bubble._entry.slash_button
        self.assertTrue(button.isVisibleTo(self.bubble._entry))
        self.assertGreater(button.x(), self.bubble._entry.width() / 2)
        self.assertLessEqual(button.geometry().right(), self.bubble._entry.width())
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertTrue(self.bubble._slash.isVisibleTo(self.bubble))
        self.assertIn("/settings", self._rows())
        self.assertFalse(self.bubble._scroll.isVisible())
        self.assertTrue(self.bubble._entry.isVisibleTo(self.bubble))
        self.assertGreaterEqual(self.bubble._slash.y(), self.bubble._entry.geometry().bottom() - 2)

    def test_should_hide_the_chat_text_while_a_typed_slash_list_is_open_and_show_it_again(self):
        """Should hide the messages for a typed slash, and bring them back on Escape, on a picked command, and when the slash is deleted."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self._open_chat()
        self.bubble._entry.setText("/")
        self.assertTrue(self.bubble._slash.rows)
        self.assertFalse(self.bubble._scroll.isVisible())
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        QTest.keyClick(self.bubble._entry, Qt.Key_Escape)
        self.assertFalse(self.bubble._slash.rows)
        self.assertTrue(self.bubble._scroll.isVisibleTo(self.bubble))
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.bubble._entry.setText("/set")
        self.assertFalse(self.bubble._scroll.isVisible())
        self.bubble._entry.setText("hello")
        self.assertFalse(self.bubble._slash.rows)
        self.assertTrue(self.bubble._scroll.isVisibleTo(self.bubble))
        self.bubble._entry.setText("/")
        self.assertFalse(self.bubble._scroll.isVisible())
        self.bubble._slash.chosen.emit("/refresh")
        self.app.processEvents()
        self.assertFalse(self.bubble._slash.rows)
        self.assertTrue(self.bubble._scroll.isVisibleTo(self.bubble))
