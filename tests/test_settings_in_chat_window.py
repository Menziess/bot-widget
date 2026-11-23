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
            raise unittest.SkipTest(f"no Qt: {error}") from error
        cls.Faces = Faces
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        # Windows that earlier tests left behind can still show up while this one runs; they are not this test's.
        self.left_behind = list(QApplication.topLevelWidgets())
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
        # Whether the face is the active window depends on the machine: a bubble whose field once had the keyboard
        # goes when another window has it, so these tests say that none does.
        stack.enter_context(mock.patch("botwidget.qt_ui.bubble_window.QApplication.activeWindow",
                                       side_effect=lambda: getattr(self, "window", None)))
        self.faces = self.Faces()
        self.window = self.faces.faces["home"]
        self.window._poll_timer.stop()
        self.bubble = self.window.bubble
        # Who closed the bubble, for the message of a test that finds it closed.
        self.closed_by = []
        close, place = self.bubble.close_bubble, self.bubble.place

        def traced_close(reason):
            result = close(reason)
            self.closed_by.append((f"close_bubble({reason!r})={result}", self._callers()))
            return result

        def traced_place(kind):
            if not kind:
                self.closed_by.append(("place('')", self._callers()))
            return place(kind)

        self.bubble.close_bubble, self.bubble.place = traced_close, traced_place
        self.addCleanup(self._close)

    @staticmethod
    def _callers():
        import traceback
        return [frame.name for frame in traceback.extract_stack()[-5:-2]]

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
        old = {id(widget) for widget in self.left_behind}
        return {id(widget) for widget in QApplication.topLevelWidgets() if widget.isVisible() and id(widget) not in old}

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
        self.assertEqual(self.bubble._back_command(), "page/commands")
        self.assertNotEqual(self.bubble._geom[0][0].get("role"), "more", "no room for the line until it is asked for")

    def _click_top_line(self):
        """A left click on the line, the first row once it has come in."""
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
        b, w = self.bubble, self.window
        self.assertTrue(b.isVisible(), f"kind={b.kind!r} near={w.pointer_near(b)} was_near={b._was_near} "
                        f"holding={b.holding()} input={b._input} pinned={w.pinned} yielding={b._yielding} "
                        f"left_since={b._left_since} entry_focus={b._entry.hasFocus()} keep_draft={b._keep_draft} "
                        f"changed={b.changed} state={b.state()} consistent={b.consistent()} closed_by={self.closed_by}")
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)
        self.assertFalse(self.bubble.commands_held())

    def test_should_open_typed_settings_in_the_chat_bubble(self):
        before, bubble_id = self._type_settings()
        self._assert_settings_in_same_bubble(before, bubble_id)

    def test_should_open_the_command_row_in_the_chat_bubble(self):
        before = self._pick_settings_row()
        self._assert_settings_in_same_bubble(before, id(self.bubble))

    def test_should_replace_the_command_list_when_a_skill_row_is_picked(self):
        """Should not leave the right-click list open while the bot works on the skill that was picked."""
        self._open_chat()
        self.right_click()
        self._reveal_arc()
        self._finish()
        self.assertTrue(self.bubble.commands_held())
        with mock.patch.object(self.window, "_pump_outbox"):
            self.bubble._run_command("/parking")
        self._finish()
        self.assertFalse(self.bubble.commands_held(), "the cloud takes the place of the list")

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
        self._wheel_up()
        self._finish()
        self._click_top_line()
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(self.bubble.commands_held())

    def test_should_return_to_the_command_list_when_scrolled_up_past_the_top(self):
        """Should stay on the page for one notch, and go back to the command list once the line is pulled far enough."""
        self.window.open_menu("bots")
        self._finish()
        self._wheel_up()
        self._finish()
        self.assertEqual(self.window._menu_page, "bots", "one notch only pulls the line")
        self.assertGreater(self.bubble._pull_px, 0)
        self.assertIn("Shift+click", self.bubble.full_text)
        self._wheel_up(3)
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertTrue(self.bubble.commands_held())

    def test_should_collapse_when_the_pointer_clicks_outside_the_bubble(self):
        """Should hide the bubble when a press lands outside it and its face, and forget the page."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication, QWidget
        self.window.open_menu("settings")
        self._finish()
        self.assertTrue(self.bubble.isVisible())
        other = QWidget()
        other.show()
        self.addCleanup(other.close)
        point = QPointF(4, 4)
        QApplication.sendEvent(other, QMouseEvent(
            QEvent.MouseButtonPress, point, point, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self._finish()
        self.assertFalse(self.bubble.isVisible())
        self.assertEqual(self.bubble.kind, "")
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)

    def test_should_leave_the_page_when_escape_is_delivered_to_the_focus_window_after_hover(self):
        """Should hear Escape the way the window system sends it: only the active window, after a hover."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
        self.window.open_menu("settings")
        self._finish()
        self.bubble._physics.stop()
        other = QWidget()
        other.setFocusPolicy(Qt.StrongFocus)
        other.resize(40, 40)
        other.show()
        other.activateWindow()
        other.setFocus()
        self.addCleanup(other.close)
        QApplication.processEvents()
        self.bubble.enterEvent(QEvent(QEvent.Enter))
        with mock.patch.object(self.window, "pointer_near", return_value=True):
            self.bubble._tick()
        QApplication.processEvents()
        self.assertIs(QGuiApplication.focusWindow(), self.bubble.windowHandle())
        target = QApplication.focusWidget()
        self.assertTrue(self.bubble.isAncestorOf(target) or target is self.bubble)
        QTest.keyClick(target, Qt.Key_Escape)
        self._finish()
        self.assertTrue(self.bubble.isVisible())
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        edit = QLineEdit(self.bubble)
        edit.show()
        self.window.open_menu("settings")
        self._finish()
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key_Escape)
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertIn("Hello from the bot.", self.bubble.full_text)

    def test_should_collapse_when_escape_is_pressed(self):
        """Should return from a menu page to the chat on Escape, and forget the page."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.open_menu("settings")
        self._finish()
        QTest.keyClick(self.bubble, Qt.Key_Escape)
        self._finish()
        self.assertTrue(self.bubble.isVisible())
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)

    def test_should_return_to_the_chat_when_escape_follows_a_restored_page(self):
        """Should hand Escape to whatever has the keyboard after a hover brings Settings back."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtTest import QTest
        self.window.open_menu("settings")
        self._finish()
        self._leave_page("left")
        self._hover()
        self.assertEqual(self.window._menu_page, "settings")
        # Offscreen leaves QApplication.focusWidget empty when no window is the app's active one.
        # The platform delivers the key to the focus window's own focus widget.
        self.assertIs(QGuiApplication.focusWindow(), self.bubble.windowHandle())
        focused = self.bubble.focusWidget()
        self.assertIsNotNone(focused, "a restored page has no keyboard, so Escape never arrives")
        QTest.keyClick(focused, Qt.Key_Escape)
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)

    def test_should_return_to_the_chat_when_escape_lands_in_a_page_field(self):
        """Should leave a page when Escape is typed into a field on that page."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        self.window.open_menu("widget-json")
        self._finish()
        editor = next(widget for widget in self.bubble._control_widgets if hasattr(widget, "text_value")
                      and widget.__class__.__name__ == "TextEditor")
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key_Escape)
        self._finish()
        self.assertIsNone(self.window._menu_page)
        self.assertIn("Hello from the bot.", self.bubble.full_text)

    def test_should_reopen_the_same_page_when_the_pointer_comes_back(self):
        """Should show Settings again after the pointer left that page, without writing config."""
        self.window.open_menu("settings")
        self._finish()
        with mock.patch.object(self.window, "pointer_near", return_value=False):
            self.assertTrue(self.bubble.close_bubble("left"))
        self.window._sync_bubble(self.window._latest(), force=True)
        self.assertEqual(self.window._page_memory, "settings")
        self.assertIsNone(self.window._menu_page)
        self.assertFalse(self.bubble.isVisible())
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.face.pointer_on", return_value=True), \
                mock.patch.object(self.window, "_pointer_is_busy", return_value=False):
            self.window._check_hover()
        self._finish()
        self.assertEqual(self.window._menu_page, "settings")
        self.assertIn("Sound on a new answer", self.bubble.full_text)
        self.assertIsNone(self.window._page_memory)

    def _leave_page(self, reason: str):
        with mock.patch.object(self.window, "pointer_near", return_value=False):
            self.assertTrue(self.bubble.close_bubble(reason), reason)
        self.window._sync_bubble(self.window._latest(), force=True)

    def _hover(self):
        with mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.face.pointer_on", return_value=True), \
                mock.patch.object(self.window, "_pointer_is_busy", return_value=False):
            self.window._check_hover()
        self._finish()

    def test_should_close_a_page_when_the_pointer_leaves(self):
        """Should hide the bubble when the pointer leaves a menu page, and keep that page for the next hover."""
        self.window.open_menu("settings")
        self._finish()
        self._leave_page("left")
        self.assertFalse(self.bubble.isVisible())
        self.assertIsNone(self.window._menu_page)
        self.assertEqual(self.window._page_memory, "settings")

    def test_should_show_the_chat_when_the_pointer_returns_after_the_page_memory(self):
        """Should open the normal chat once the remembered page is older than the limit."""
        import time
        self.window.open_menu("settings")
        self._finish()
        self._leave_page("left")
        self.window._page_memory_until = time.monotonic() - 1
        self._hover()
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)

    def test_should_forget_the_page_when_a_click_away_closes_it(self):
        """Should close on a click into another window and open the chat on the next hover."""
        self.window.open_menu("settings")
        self._finish()
        self._leave_page("focus_elsewhere")
        self.assertFalse(self.bubble.isVisible())
        self.assertIsNone(self.window._page_memory)
        self._hover()
        self.assertIsNone(self.window._menu_page)
        self.assertIn("Hello from the bot.", self.bubble.full_text)

    def test_should_forget_the_page_when_escape_closes_it(self):
        """Should leave the page on Escape and not bring that page back on the next hover."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        self.window.open_menu("settings")
        self._finish()
        self.bubble.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self._finish()
        self.assertTrue(self.bubble.isVisible())
        self.assertIsNone(self.window._menu_page)
        self.assertIsNone(self.window._page_memory)
        self.assertIn("Hello from the bot.", self.bubble.full_text)
        self.assertNotIn("Sound on a new answer", self.bubble.full_text)

    def test_should_take_the_page_memory_limit_from_the_setting(self):
        """Should keep a page for the seconds named in widget.json, and for 60 when that key is absent."""
        import time

        from botwidget.config import page_memory_s
        self.assertEqual(page_memory_s(), 60)
        with mock.patch("botwidget.config.widget_config", return_value={"page_memory_s": 12}):
            self.assertEqual(page_memory_s(), 12)
        with mock.patch("botwidget.qt_ui.face.page_memory_s", return_value=12):
            self.window.open_menu("bots")
            self._finish()
            before = time.monotonic()
            self._leave_page("left")
        self.assertEqual(self.window._page_memory, "bots")
        self.assertAlmostEqual(self.window._page_memory_until - before, 12, delta=2)

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

    def test_should_collapse_when_escape_is_pressed_on_the_page_or_the_face(self):
        """Should hide the bubble when Escape is pressed on a page, or on the face that holds it."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        for page, on_face in (("settings", False), ("connections", True)):
            with self.subTest(page=page, on_face=on_face):
                if not on_face:
                    self._open_chat()
                self.window.open_menu(page)
                self._finish()
                self.assertEqual(self.window._menu_page, page)
                if on_face:
                    self.window.setFocus()
                    QTest.keyClick(self.window, Qt.Key_Escape)
                else:
                    QTest.keyClick(self.bubble, Qt.Key_Escape)
                self._finish()
                self.assertTrue(self.bubble.isVisible(), "Escape returns to the chat, not one level up")
                self.assertIsNone(self.window._menu_page)
                self.assertIsNone(self.window._page_memory)
                self.assertFalse(self.bubble.commands_held())
                self.assertIn("Hello from the bot.", self.bubble.full_text)

    def test_should_leave_the_command_list_for_the_chat_when_escape_is_pressed(self):
        """Should go back to the chat when Escape is pressed on the inline command list."""
        self.right_click()
        self._finish()
        self.assertTrue(self.bubble.commands_held())
        self.assertNotEqual(self.bubble._back_command(), "close")
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        QTest.keyClick(self.bubble._entry, Qt.Key_Escape)
        self._finish()
        self.assertFalse(self.bubble.commands_held())
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
        self.assertTrue(self.bubble.commands_held())
        commands = [command for command, _note in self.bubble._slash.rows]
        self.assertIn("/settings", commands)
        self.assertIsNone(self.window._menu_page)
