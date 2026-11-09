"""A menu page replaces the chat in the face's own bubble and can come back to it.

Offscreen Qt only: no display and no network.
"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class SettingsInTheChatWindow(unittest.TestCase):
    """Should show settings in the chat bubble and return to that chat."""

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
        # The chat is hidden until one of these is true. CI has neither app installed.
        stack.enter_context(mock.patch("botwidget.qt_ui.face.openbot_installed", return_value=True))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.gbot_installed", return_value=True))
        # Offscreen still reports a cursor position. Trusting it closes a click-opened chat on CI.
        stack.enter_context(mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False))
        self.faces = self.Faces()
        self.window = self.faces.faces["home"]
        self.window._poll_timer.stop()
        self.bubble = self.window.bubble
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

    def _finish(self):
        self.bubble._slide.stop()
        self.bubble._growth_done()
        type(self).app.processEvents()

    def _visible_ids(self):
        from PySide6.QtWidgets import QApplication
        return {id(widget) for widget in QApplication.topLevelWidgets() if widget.isVisible()}

    def _open_chat(self):
        self.window.pin()
        self._finish()
        self.assertTrue(self.bubble.isVisible())
        self.assertIn("Hello from the bot.", self.bubble.full_text)

    def _click(self, widget, button, press: bool):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        point = QPointF(10, 10)
        kind = QEvent.MouseButtonPress if press else QEvent.MouseButtonRelease
        buttons = button if press else Qt.NoButton
        QApplication.sendEvent(widget, QMouseEvent(kind, point, point, button, buttons, Qt.NoModifier))

    def right_click(self):
        from PySide6.QtCore import Qt
        self._click(self.window, Qt.RightButton, True)

    def _type_settings(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self._open_chat()
        before = self._visible_ids()
        bubble_id = id(self.bubble)
        self.bubble._entry.setText("/settings")
        QTest.keyClick(self.bubble._entry, Qt.Key_Return)
        self._finish()
        return before, bubble_id

    def _reveal_arc(self):
        """The right-click arc is already opening; let its guest show before the settings snapshot."""
        import time
        if self.faces._semicircle_phase in ("showing", "hiding"):
            self.faces._arc_t0 = time.monotonic() - 10
            self.faces._semicircle_tick()
            type(self).app.processEvents()

    def _pick_settings_row(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        self._open_chat()
        self.right_click()
        self._reveal_arc()
        self._finish()
        before = self._visible_ids()
        slash = self.bubble._slash
        commands = [command for command, _note in slash.rows]
        self.assertIn("/settings", commands)
        index = commands.index("/settings")
        point = QPointF(20, index * slash.ROW_H + slash.ROW_H // 2 + 4)
        QApplication.sendEvent(slash, QMouseEvent(
            QEvent.MouseButtonRelease, point, point, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self._finish()
        return before

    def _assert_settings_in_same_bubble(self, before, bubble_id):
        self.assertIs(self.window.bubble, self.bubble)
        self.assertEqual(id(self.bubble), bubble_id)
        self.assertEqual(self.window._menu_page, "settings")
        self.assertIn("Sound on a new answer", self.bubble.full_text)
        self.assertTrue(self.bubble.isVisible())
        self.assertLessEqual(self._visible_ids(), before)
        face = self.window.frameGeometry()
        card = self.bubble.card()
        gap_x = max(0, max(face.left() - card.right(), card.left() - face.right()))
        gap_y = max(0, max(face.top() - card.bottom(), card.top() - face.bottom()))
        self.assertLess(gap_x + gap_y, 200, "the bubble stays anchored next to the face")

    def _chat_anchor(self):
        """The heading link back to the chat, or None when the page has none."""
        from PySide6.QtGui import QTextCursor
        doc = self.bubble._doc.document()
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.isAnchor() and "page/chat" in fmt.anchorHref():
                    cursor = QTextCursor(doc)
                    cursor.setPosition(frag.position())
                    cursor.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                    return cursor
                it += 1
            block = block.next()
        return None

    def _top_line_alpha(self):
        image = self.bubble._text.pixmap().toImage()
        peak = 0
        for y in range(min(16, image.height())):
            for x in range(image.width()):
                peak = max(peak, image.pixelColor(x, y).alpha())
        return peak

    def _assert_no_chat_link(self):
        """A page heading is the title only. The fading line above it is the way back to the chat."""
        self.assertIsNone(self._chat_anchor(), "the heading still has a ‹ Chat link")
        self.assertNotIn("‹ Chat", self.bubble.full_text)
        self.assertNotIn("goes back to commands", self.bubble.full_text)
        self.assertEqual(self.bubble._scroll.verticalScrollBar().value(), 0)
        self.assertEqual(self.bubble._geom[0][0].get("role"), "more")
        self.assertEqual(self.bubble._geom[0][0].get("back"), "page/commands")
        self.assertEqual(self._top_line_alpha(), 0, "the line stays hidden until a scroll or a pointer")

    def _click_top_line(self):
        """A left click on the fading line, which is the first row even while it is faded out."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        from botwidget.bubble import panel_rects
        top, _height = panel_rects(self.bubble._geom[0])[0]
        viewport = self.bubble._doc.viewport()
        point = QPointF(40, top + 4 - self.bubble._doc.y())
        global_point = QPointF(viewport.mapToGlobal(point.toPoint()))
        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseButtonPress, point, global_point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        QApplication.sendEvent(viewport, QMouseEvent(
            QEvent.MouseButtonRelease, point, global_point, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self._finish()

    def _wheel_up(self, times: int = 1):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        for _ in range(times):
            QApplication.sendEvent(self.bubble._scroll.viewport(), QWheelEvent(
                QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))

    def _assert_chat_field(self):
        """Back on the chat, the typing field is in the bubble even though the pointer is not."""
        self._assert_chat_shown()
        self.assertFalse(self.window.pointer_near(self.bubble), "the pointer is on the bubble, so the field would show anyway")
        self.assertTrue(self.bubble._input)
        self.assertIsNotNone(self.bubble._entry)
        self.assertTrue(self.bubble._entry.isVisibleTo(self.bubble))

    def _assert_chat_shown(self):
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(self.bubble.isVisible())
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)
        self.assertFalse(self.bubble._list_only)

    def test_should_open_typed_settings_in_the_chat_bubble(self):
        before, bubble_id = self._type_settings()
        self._assert_settings_in_same_bubble(before, bubble_id)

    def test_should_open_the_command_row_in_the_chat_bubble(self):
        before = self._pick_settings_row()
        self._assert_settings_in_same_bubble(before, id(self.bubble))

    def test_should_not_put_a_chat_link_on_any_page(self):
        """Should leave every page heading as a title. The way back is the line on top, and it targets the command list."""
        for page in ("settings", "bots", "connections"):
            self.window.open_menu(page)
            self._finish()
            self._assert_no_chat_link()

    def test_should_return_to_the_command_list_when_the_top_line_is_clicked(self):
        """Should open the command list when the fading line on a page is clicked."""
        self.window.open_menu("settings")
        self._finish()
        self.assertEqual(self.bubble._back_command(), "page/commands")
        self._click_top_line()
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(self.bubble._list_only)

    def test_should_return_to_the_command_list_when_scrolled_up_past_the_top(self):
        """Should stay on the page for one notch, and go back to the command list once the line is pulled far enough."""
        self.window.open_menu("bots")
        self._finish()
        self._wheel_up()
        self.assertEqual(self.window._menu_page, "bots", "one notch only pulls the line")
        self.assertGreater(self.bubble._pull_px, 0)
        self.assertIn("Shift+click", self.bubble.full_text)
        self._wheel_up(3)
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(self.bubble._list_only)

    def test_should_return_to_the_chat_with_the_field_on_a_left_click(self):
        """Should leave a page for the chat when its face is left-clicked, and never open settings that way."""
        from PySide6.QtCore import Qt
        for page in ("settings", "bots", "connections"):
            self.window.open_menu(page)
            self._finish()
            self.assertEqual(self.window._menu_page, page)
            self._click(self.window, Qt.LeftButton, True)
            self._click(self.window, Qt.LeftButton, False)
            self._finish()
            self._assert_chat_field()
            self.assertNotEqual(self.window._menu_page, "settings")
            self.assertNotIn("Sound on a new answer", self.bubble.full_text)
        self._click(self.window, Qt.LeftButton, True)
        self._click(self.window, Qt.LeftButton, False)
        self._finish()
        self.assertNotEqual(self.window._menu_page, "settings")
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)

    def test_should_return_to_the_chat_with_the_field_on_a_left_click_while_thinking(self):
        """Should show the chat, not settings and not the cloud, when the face of a working bot is left-clicked."""
        from PySide6.QtCore import Qt
        self.window.open_menu("settings")
        self._finish()
        self.chat["activity"] = "reading"
        self.window._chat = {"messages": list(self.chat["messages"]), "activity": "reading"}
        self.window._working = True
        self._click(self.window, Qt.LeftButton, True)
        self._click(self.window, Qt.LeftButton, False)
        self._finish()
        self._assert_chat_field()
        self.assertNotEqual(self.bubble.kind, "think")

    def test_should_return_to_the_chat_when_escape_is_pressed_on_the_page(self):
        """Should bring the chat back, with its typing field, when Escape is pressed on a page."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self._open_chat()
        self.window.open_menu("settings")
        self._finish()
        self.assertEqual(self.window._menu_page, "settings")
        QTest.keyClick(self.bubble, Qt.Key_Escape)
        self._finish()
        self._assert_chat_field()

    def test_should_return_to_the_chat_when_escape_is_pressed_on_the_face(self):
        """Should bring the chat back when Escape is pressed with the keyboard on the face of an open page."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.open_menu("connections")
        self._finish()
        self.assertEqual(self.window._menu_page, "connections")
        self.window.setFocus()
        QTest.keyClick(self.window, Qt.Key_Escape)
        self._finish()
        self._assert_chat_field()

    def test_should_leave_the_command_list_for_the_chat_when_scrolled_up_past_the_top(self):
        """Should go back to the chat when a right-click list is pulled far enough, as a page goes back."""
        self.right_click()
        self._finish()
        self.assertTrue(self.bubble._list_only)
        self.assertEqual(self.bubble._back_command(), "close")
        self._wheel_up(4)
        self._finish()
        self.assertFalse(self.bubble._list_only)
        self.assertIsNone(self.window._menu_page)

    def test_should_still_close_the_chat_when_escape_is_pressed_there(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self._open_chat()
        self.bubble._entry.setFocus()
        QTest.keyClick(self.bubble._entry, Qt.Key_Escape)
        self.assertFalse(self.bubble.isVisible())
        self.assertFalse(self.window.pinned)
        self.assertEqual(self.bubble.kind, "")

    def test_should_still_open_the_command_list_on_a_right_click(self):
        self.right_click()
        self.assertTrue(self.bubble.isVisible())
        self.assertTrue(self.bubble._list_only)
        commands = [command for command, _note in self.bubble._slash.rows]
        self.assertIn("/settings", commands)
        self.assertIsNone(self.window._menu_page)
