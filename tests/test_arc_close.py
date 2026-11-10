"""Hidden bots show only while /bots is open. An arc opened another way still closes on its own.

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
    """Should keep hidden bots off the slash list, and close an arc that /bots is not holding."""

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
        """The top edge still opens the arc. A right-click must not."""
        self.faces.show_semicircle()
        self.assertNotEqual(self.faces._semicircle_phase, "idle")
        self.assertIn("away", self.faces._arc_guests)
        self.assertFalse(self.faces._arc_guests["away"].underMouse())

    def test_should_keep_hidden_bots_off_a_right_click(self):
        """Should leave inactive bots hidden when the slash list opens."""
        self.right_click()
        self.assertEqual(self.faces._semicircle_phase, "idle")
        self.assertEqual(self.faces._arc_guests, {})

    def test_should_show_hidden_bots_only_while_the_bots_page_is_open(self):
        """Should show a hidden bot on /bots, keep it when the pointer leaves, and drop it when the page closes."""
        self.right_click()
        self.assertEqual(self.faces._arc_guests, {})
        self.window.open_menu("bots")
        self.assertNotEqual(self.faces._semicircle_phase, "idle")
        self.assertIn("away", self.faces._arc_guests)
        self._leave(self.window)
        self.assertFalse(self.faces._semicircle_hide_timer.isActive())
        self.window.open_input()
        self.assertTrue(self.faces._semicircle_hide_timer.isActive())

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

    def test_should_keep_the_arc_open_when_the_pointer_moves_onto_a_guest(self):
        """Leave first (the hide timer starts), then enter a bot; the hide callback must not close."""
        self._open_arc()
        self.faces._arc_t0 = time.monotonic() - 10
        self.faces._semicircle_tick()
        self.assertEqual(self.faces._semicircle_phase, "visible")
        guest = self.faces._arc_guests["away"]
        self.assertTrue(guest.isVisible())
        # The gap between leaving the catcher and entering a bot used to close the arc.
        self._leave(self.faces._catcher)
        self.assertTrue(self.faces._semicircle_hide_timer.isActive())
        self._enter(guest)
        self.assertTrue(guest.pointer_over())
        self.faces._semicircle_hide()
        self.assertEqual(self.faces._semicircle_phase, "visible")
        self.assertIn("away", self.faces._arc_guests)

    def test_should_keep_the_arc_open_when_the_pointer_moves_onto_a_desktop_face(self):
        self._open_arc()
        self.faces._arc_t0 = time.monotonic() - 10
        self.faces._semicircle_tick()
        self._leave(self.faces._catcher)
        self.assertTrue(self.faces._semicircle_hide_timer.isActive())
        self._enter(self.window)
        self.assertTrue(self.window.pointer_over())
        self.faces._semicircle_hide()
        self.assertEqual(self.faces._semicircle_phase, "visible")


    def test_should_put_an_open_bubble_on_the_top_layer_while_the_arc_is_open(self):
        """On Linux a stay-behind bubble cannot raise above stay-on-top guests; share the top layer."""
        from PySide6.QtCore import Qt
        from botwidget.qt_ui.bubble_window import window_layer
        with mock.patch("botwidget.qt_ui.bubble_window.always_on_top", return_value=False), \
                mock.patch("botwidget.config.always_on_top", return_value=False):
            self.assertEqual(window_layer(self.window), Qt.WindowStaysOnBottomHint)
            self._open_arc()
            self.assertEqual(self.faces._semicircle_phase, "showing")
            self.assertEqual(window_layer(self.window), Qt.WindowStaysOnTopHint)
            bubble = self.window.bubble
            bubble._apply_flags()
            flags = bubble.windowFlags()
            self.assertTrue(bool(flags & Qt.WindowStaysOnTopHint), flags)
            self.assertFalse(bool(flags & Qt.WindowStaysOnBottomHint), flags)
            # Closing the arc puts a stay-behind bubble back below other windows.
            self.faces._finish_arc()
            self.assertEqual(self.faces._semicircle_phase, "idle")
            self.assertEqual(window_layer(self.window), Qt.WindowStaysOnBottomHint)
            bubble._apply_flags()
            flags = bubble.windowFlags()
            self.assertTrue(bool(flags & Qt.WindowStaysOnBottomHint), flags)

    def _finish_hiding_arc(self):
        """What happens after leaving /bots or the catcher: the hide timer fires and the arc finishes."""
        if self.faces._semicircle_hide_timer.isActive():
            self.faces._semicircle_hide()
        if self.faces._semicircle_phase == "hiding":
            self.faces._arc_t0 = time.monotonic() - 10
            self.faces._semicircle_tick()
        if self.faces._semicircle_phase != "idle":
            self.faces._finish_arc()
        self.app.processEvents()
        # The face poll calls heal() whenever the pointer is on the bot; a remapped window
        # used to look inconsistent and close the page.
        self.window.bubble.heal()
        self.app.processEvents()

    def test_opening_the_edit_page_from_bots_keeps_the_panel_open(self):
        """Should keep the bubble on the bot form after /bots releases the arc (9bbca67 restack)."""
        self.window.open_menu("bots")
        self.assertTrue(self.window.bubble.isVisible())
        self.assertNotEqual(self.faces._semicircle_phase, "idle")
        self.window.open_menu("bot")
        self._finish_hiding_arc()
        self.assertEqual(self.window._menu_page, "bot")
        self.assertTrue(self.window.bubble.isVisible(), "edit page closed when the arc hid")
        self.assertTrue(self.window.bubble.kind)

    def test_every_menu_page_stays_open_when_the_arc_hides_or_restacks(self):
        """Should keep the panel on every menu page, not only the bot form."""
        from botwidget.menu_pages import PAGES
        for page in PAGES:
            with self.subTest(page=page):
                self.window.open_menu("bots")
                self.window.open_menu(page)
                self._finish_hiding_arc()
                self.assertEqual(self.window._menu_page, page)
                self.assertTrue(self.window.bubble.isVisible(), f"{page} closed")
                self.assertTrue(self.window.bubble.kind)

    def test_heal_after_a_flag_remap_does_not_close_a_menu_page(self):
        """set_flags hides and destroys the native window; the hover poll then calls heal()."""
        from botwidget.menu_pages import PAGES
        for page in PAGES:
            with self.subTest(page=page):
                self.window.open_menu(page)
                bubble = self.window.bubble
                self.assertTrue(bubble.isVisible(), page)
                # Unchanged flags must not remap (and must not hide) a page that is already on the right layer.
                bubble._apply_flags()
                self.assertTrue(bubble.isVisible(), f"{page} hidden by a no-op flag update")
                # A real remap (layer change, or Qt setWindowFlags) hides the widget the way Linux does.
                created = bubble.windowHandle() is not None
                bubble.setWindowFlags(bubble.windowFlags())
                if created:
                    bubble.destroy()
                self.assertFalse(bubble.isVisible())
                self.assertEqual(bubble.state(), "open")
                bubble.heal()
                self.assertEqual(self.window._menu_page, page)
                self.assertTrue(bubble.isVisible(), f"{page} closed after heal")
                self.assertTrue(bubble.kind)
                self.assertTrue(bubble.consistent())

    def test_restack_after_the_arc_closes_does_not_drop_a_menu_page(self):
        """always_on_top off: leaving the arc changes the bubble layer and remaps the window."""
        with mock.patch("botwidget.qt_ui.bubble_window.always_on_top", return_value=False), \
                mock.patch("botwidget.config.always_on_top", return_value=False):
            self.window.open_menu("bot")
            self.assertTrue(self.window.bubble.isVisible())
            self._open_arc()
            self.faces._restack_open_bubbles()
            self.app.processEvents()
            self.window.bubble.heal()
            self.assertTrue(self.window.bubble.isVisible())
            self.faces._finish_arc()
            self.app.processEvents()
            self.window.bubble.heal()
            self.assertEqual(self.window._menu_page, "bot")
            self.assertTrue(self.window.bubble.isVisible(), "restack after the arc closed hid the edit page")
            self.assertTrue(self.window.bubble.kind)
