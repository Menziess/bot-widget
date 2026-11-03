"""A muted Thinking line under each face that is working.

Offscreen Qt only: no display and no network.
"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ThinkingRowUnderWorkingFace(unittest.TestCase):
    """Should show a muted Thinking line under a face only while that bot is working."""

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
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w") as fh:
            json.dump({"enabled": ["home", "away"], "pos": {"home": [400, 400], "away": [520, 400]}}, fh)
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
        stack.enter_context(mock.patch("botwidget.qt_ui.face.openbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.gbot_installed", return_value=False))
        self.faces = self.Faces()
        self.window = self.faces.faces["home"]
        self.other = self.faces.faces["away"]
        self.app.processEvents()
        for face in self.faces.faces.values():
            face._poll_timer.stop()
            face._anim_timer.stop()
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

    def _rows(self, face):
        """Visible Thinking lines that belong to this face."""
        from PySide6.QtWidgets import QApplication
        found = []
        for widget in QApplication.allWidgets():
            if widget is face or not widget.isVisible():
                continue
            text = widget.text() if callable(getattr(widget, "text", None)) else ""
            if text != "Thinking":
                continue
            if widget.parent() is face or getattr(widget, "face", None) is face:
                found.append(widget)
        return found

    def _work(self, face, on: bool):
        """The same turn state the thinking cloud uses: activity while the bot works."""
        face._sync_bubble({"messages": [], "activity": "reading" if on else ""})

    def _geom(self, face):
        return (face.x(), face.y(), face.width(), face.height())

    def test_should_hide_the_row_when_the_face_is_idle(self):
        self._work(self.window, False)
        self.assertEqual(self._rows(self.window), [])

    def test_should_show_thinking_under_a_working_face(self):
        from PySide6.QtCore import QPoint, Qt
        self._work(self.window, True)
        rows = self._rows(self.window)
        self.assertEqual(len(rows), 1, "a working face shows one Thinking row")
        row = rows[0]
        self.assertEqual(row.text(), "Thinking")
        top = row.mapToGlobal(QPoint(0, 0))
        face_bottom = self.window.mapToGlobal(QPoint(0, int(self.window.head_bottom)))
        self.assertGreaterEqual(top.y(), face_bottom.y())
        self.assertLessEqual(top.y(), self.window.frameGeometry().bottom() + 8)
        face_mid = self.window.mapToGlobal(QPoint(self.window.width() // 2, 0)).x()
        row_mid = row.mapToGlobal(QPoint(row.width() // 2, 0)).x()
        self.assertLessEqual(abs(face_mid - row_mid), 4)
        click_through = bool(row.windowFlags() & Qt.WindowTransparentForInput) or row.testAttribute(
            Qt.WA_TransparentForMouseEvents)
        self.assertTrue(click_through, "the row must not take clicks meant for the face")

    def test_should_hide_the_row_when_the_turn_stops(self):
        self._work(self.window, True)
        self.assertEqual(len(self._rows(self.window)), 1)
        self._work(self.window, False)
        self.assertEqual(self._rows(self.window), [])

    def test_should_keep_the_face_geometry_while_working(self):
        before = self._geom(self.window)
        self._work(self.window, True)
        during = self._geom(self.window)
        self._work(self.window, False)
        after = self._geom(self.window)
        self.assertEqual(before, during)
        self.assertEqual(during, after)

    def test_should_show_a_row_only_under_the_working_bot(self):
        self._work(self.window, True)
        self._work(self.other, False)
        self.assertEqual(len(self._rows(self.window)), 1)
        self.assertEqual(self._rows(self.other), [])

    def test_should_keep_the_row_when_the_thinking_cloud_is_muted(self):
        with mock.patch("botwidget.qt_ui.face.openbot_installed", return_value=True):
            self.window._muted = False
            self._work(self.window, True)
            self.window._muted = True
            self._work(self.window, True)
            self.assertNotEqual(self.window.bubble.kind, "think")
            self.assertEqual(len(self._rows(self.window)), 1)

    def test_should_draw_the_row_in_a_muted_colour(self):
        from PySide6.QtGui import QColor, QImage
        from botwidget.theme import SAND_INK
        self._work(self.window, True)
        row = self._rows(self.window)[0]
        image = QImage(row.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        row.render(image)
        ink = None
        for y in range(image.height()):
            for x in range(image.width()):
                pixel = image.pixelColor(x, y)
                if pixel.alpha() > (ink.alpha() if ink is not None else 0):
                    ink = pixel
        self.assertIsNotNone(ink, "the row draws no text")
        normal = QColor(SAND_INK)
        muted = ink.alpha() < normal.alpha() or (ink.red() + ink.green() + ink.blue()) > (
            normal.red() + normal.green() + normal.blue())
        self.assertTrue(muted, f"row ink {ink.name(QColor.HexArgb)} is not quieter than {normal.name()}")
