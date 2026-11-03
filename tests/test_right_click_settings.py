"""Settings opens from the right-click list or from typing /settings, never from a left click.

Offscreen Qt only: no display and no network.
"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class RightClickOnlySettings(unittest.TestCase):
    """Should keep a left click on the chat, and open /settings only from the command list."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui.faces import Faces
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.Faces = Faces
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from botwidget.qt_ui.faces import Faces
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as fh:
            json.dump({"enabled": ["home"], "pos": {"home": [400, 400]}}, fh)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        bots = [
            {"id": "home", "name": "Home", "threadId": "t-home", "hue": None, "seed": "home", "status": "ready"},
            {"id": "away", "name": "Away", "threadId": "t-away", "hue": None, "seed": "away", "status": "ready"},
        ]
        self.chat = {"messages": [{"role": "bot", "text": "Hello from the bot."}], "activity": ""}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.STATE_PATH", path))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.list_bots", return_value=bots))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.gbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.hermesbot.is_hermes_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.check_updates", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.threading.Thread", return_value=mock.Mock()))
        stack.enter_context(mock.patch(
            "botwidget.qt_ui.face.latest_chat",
            side_effect=lambda thread_id="", limit=20: self.chat))
        self.faces = Faces()
        self.window = self.faces.faces["home"]
        self.window._poll_timer.stop()
        self.addCleanup(self._close)

    def _close(self):
        self.faces._semicircle_timer.stop()
        self.faces._semicircle_hide_timer.stop()
        app = type(self).app
        app.removeEventFilter(self.faces)
        for face in list(self.faces.faces.values()) + list(self.faces._arc_guests.values()):
            face._poll_timer.stop()
            face._anim_timer.stop()
            face.close_face()
        self.faces._catcher.close()
        app.processEvents()

    def _click(self, widget, button, press: bool):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        point = QPointF(10, 10)
        kind = QEvent.MouseButtonPress if press else QEvent.MouseButtonRelease
        buttons = button if press else Qt.NoButton
        QApplication.sendEvent(widget, QMouseEvent(kind, point, point, button, buttons, Qt.NoModifier))

    def left_click(self, widget=None):
        widget = self.window if widget is None else widget
        from PySide6.QtCore import Qt
        self._click(widget, Qt.LeftButton, True)
        self._click(widget, Qt.LeftButton, False)

    def right_click(self):
        from PySide6.QtCore import Qt
        self._click(self.window, Qt.RightButton, True)

    def _settings_bubble(self) -> bool:
        bubble = self.window.bubble
        return bool(bubble.isVisible() and "Sound on a new answer" in (bubble.full_text or ""))

    def _busy_on_settings(self):
        """Settings is up, and the bot is thinking with an answer already in the chat."""
        self.window.open_menu("settings")
        self.chat["activity"] = "reading"
        self.window._chat = {"messages": list(self.chat["messages"]), "activity": "reading"}
        self.window._working = True
        self.assertEqual(self.window._menu_page, "settings")
        self.assertTrue(self._settings_bubble())
        self.assertTrue(self.window._show_think())
        self.assertTrue(any(m.get("role") == "bot" for m in self.window._chat["messages"]))

    def _assert_left_settings(self):
        self.assertNotEqual(self.window._menu_page, "settings")
        self.assertFalse(self._settings_bubble(), "the bubble is still the settings page")

    def test_should_not_show_settings_on_a_left_click_when_idle(self):
        self.left_click()
        self._assert_left_settings()

    def test_should_leave_settings_on_a_left_click_when_idle(self):
        self.window.open_menu("settings")
        self.assertEqual(self.window._menu_page, "settings")
        self.assertTrue(self._settings_bubble())
        self.left_click()
        self._assert_left_settings()

    def test_should_leave_settings_on_a_left_click_while_thinking(self):
        self._busy_on_settings()
        self.left_click()
        self._assert_left_settings()

    def test_should_open_settings_from_the_right_click_list(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self.right_click()
        slash = self.window.bubble._slash
        commands = [command for command, _note in slash.rows]
        self.assertIn("/settings", commands)
        self.assertTrue(self.window.bubble._list_only)
        index = commands.index("/settings")
        point = QPointF(20, index * slash.ROW_H + slash.ROW_H // 2 + 4)
        QApplication.sendEvent(slash, QMouseEvent(
            QEvent.MouseButtonRelease, point, point, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(self.window._menu_page, "settings")
        self.assertTrue(self._settings_bubble())
