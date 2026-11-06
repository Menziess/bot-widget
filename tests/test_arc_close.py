"""The right-click arc closes without the pointer ever touching a hidden bot.

Offscreen Qt only: no display and no network.
"""

import json
import os
import tempfile
import time
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ArcClosesWithoutVisitingBots(unittest.TestCase):
    """Should close the right-click arc when the pointer leaves, clicks away, or presses Esc."""

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
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.STATE_PATH", path))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.list_bots", return_value=bots))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.gbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.hermesbot.is_hermes_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.check_updates", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.threading.Thread", return_value=mock.Mock()))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.latest_chat", return_value={"messages": [], "activity": ""}))
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

    def _leave(self, widget):
        from PySide6.QtCore import QEvent
        # Offscreen does not deliver hover from QCursor to these tool windows.
        # Enter and leave are the events the face actually gets when the pointer crosses it.
        self.app.sendEvent(widget, QEvent(QEvent.Leave))

    def _enter(self, widget):
        from PySide6.QtCore import QEvent
        self.app.sendEvent(widget, QEvent(QEvent.Enter))

    def right_click(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        local = QPointF(10, self.window.height() - 10)
        where = QPointF(self.window.x() + 10, self.window.y() + self.window.height() - 10)
        QApplication.sendEvent(self.window, QMouseEvent(
            QEvent.MouseButtonPress, local, where, Qt.RightButton, Qt.RightButton, Qt.NoModifier))

    def _open_arc(self):
        self.right_click()
        self.assertNotEqual(self.faces._semicircle_phase, "idle")
        self.assertIn("away", self.faces._arc_guests)
        self.assertFalse(self.faces._arc_guests["away"].underMouse())

    def _settle_closed(self):
        if self.faces._semicircle_hide_timer.isActive():
            self.faces._semicircle_hide()
        self.assertIn(self.faces._semicircle_phase, ("hiding", "idle"))
        if self.faces._semicircle_phase == "hiding":
            self.faces._arc_t0 = time.monotonic() - 10
            self.faces._semicircle_tick()
        self.assertEqual(self.faces._semicircle_phase, "idle")
        self.assertEqual(self.faces._arc_guests, {})

    def test_should_close_when_the_pointer_leaves_without_visiting_a_bot(self):
        self._open_arc()
        self._leave(self.window)
        self.assertFalse(self.faces._arc_guests["away"].underMouse())
        self._settle_closed()

    def test_should_close_on_a_click_outside_the_arc(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QWidget
        self._open_arc()
        other = QWidget()
        other.setGeometry(10, 680, 30, 30)
        other.show()
        self.addCleanup(other.close)
        point, where = QPointF(5, 5), QPointF(15, 685)
        QApplication.sendEvent(other, QMouseEvent(
            QEvent.MouseButtonPress, point, where, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self._settle_closed()

    def test_should_close_on_escape(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication
        self._open_arc()
        QApplication.sendEvent(self.window, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        self._settle_closed()

    def test_should_keep_the_arc_while_the_pointer_is_on_a_hidden_bot(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self._open_arc()
        self.faces._arc_t0 = time.monotonic() - 10
        self.faces._semicircle_tick()
        self.assertEqual(self.faces._semicircle_phase, "visible")
        guest = self.faces._arc_guests["away"]
        self.assertTrue(guest.isVisible())
        self._enter(guest)
        self.assertTrue(guest.underMouse())
        self._leave(self.window)
        self.assertFalse(self.faces._semicircle_hide_timer.isActive())
        self.assertEqual(self.faces._semicircle_phase, "visible")
        local = QPointF(guest.width() / 2, guest.height() / 2)
        where = QPointF(guest.x() + local.x(), guest.y() + local.y())
        QApplication.sendEvent(guest, QMouseEvent(
            QEvent.MouseButtonPress, local, where, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.assertEqual(self.faces._semicircle_phase, "visible")
        QApplication.sendEvent(guest, QMouseEvent(
            QEvent.MouseButtonRelease, local, where, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertIn("away", self.faces.faces)
