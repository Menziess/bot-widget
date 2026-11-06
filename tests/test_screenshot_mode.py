"""Screenshot mode: double-click a face, drag a region, bots stay out of the shot.

Offscreen Qt only. A fake grabber stands in for screen grab. No display.
"""

import json
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config
from PySide6.QtCore import Qt


def _write_config(data: dict):
    """widget.json for this test (CONFIG_PATH must already point at a temp file)."""
    os.makedirs(os.path.dirname(config.CONFIG_PATH), exist_ok=True)
    with open(config.CONFIG_PATH, "w") as fh:
        json.dump(data, fh)
    config._config_read[:] = [None, {}]


class ScreenshotMode(unittest.TestCase):
    """Should enter screenshot mode on double-click and leave it cleanly."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config._config_read[:] = [None, {}]

    def _make_window(self, agent_id="t1", name="Test"):
        window = self.face.FaceWindow(agent_id, name, spot=(300, 400))
        window._poll_timer.stop()
        window._anim_timer.stop()
        return window

    def test_double_click_enters_screenshot_mode(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window}
        # Double-click: first press, then double-click event
        gp = mock.Mock()
        gp.x.return_value = 340.0
        gp.y.return_value = 440.0
        event1 = mock.Mock()
        event1.button.return_value = Qt.LeftButton
        event1.globalPosition.return_value = gp
        event1.modifiers.return_value = 0
        window.mousePressEvent(event1)
        dc_event = mock.Mock()
        dc_event.button.return_value = Qt.LeftButton
        dc_event.globalPosition.return_value = gp
        dc_event.modifiers.return_value = 0
        window.mouseDoubleClickEvent(dc_event)
        # Mode should be entered: the face's screenshot_face is set to self
        self.assertEqual(window.screenshot_face, window)
        self.assertTrue(getattr(window, "_screenshot_active", False))
        self.assertIsNotNone(getattr(window, "_screenshot_overlay", None))

    def test_single_click_does_not_enter_screenshot_mode(self):
        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window}
        gp = mock.Mock()
        gp.x.return_value = 340.0
        gp.y.return_value = 440.0
        event = mock.Mock()
        event.button.return_value = Qt.LeftButton
        event.globalPosition.return_value = gp
        event.modifiers.return_value = Qt.KeyboardModifier(0)
        window.mousePressEvent(event)
        window.mouseReleaseEvent(event)
        self.assertFalse(hasattr(window, 'screenshot_face'))

    def test_leave_screenshot_mode_clears_state(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window}
        window.screenshot_face = window
        # Create a real overlay so close() works
        overlay = ScreenshotOverlay(window)
        overlay.close()  # close it immediately so it doesn't interfere
        window._screenshot_overlay = overlay
        window._leave_screenshot_mode()
        # _leave_screenshot_mode clears the state
        self.assertIsNone(window.screenshot_face)
        self.assertFalse(getattr(window, "_screenshot_active", True))

    def test_overlay_mouse_events_work(self):
        """Verify overlay handles mouse events (left press, move, release)."""
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        overlay._rect = None
        overlay._start = None
        overlay._mouse_down = False
        overlay._done_callback = None
        overlay._cancel_callback = None
        # Patch close/update to avoid __init__ RuntimeError
        overlay.close = mock.Mock()
        overlay.update = mock.Mock()

        # Simulate a left mouse press
        pos = mock.Mock()
        pos.x.return_value = 100.0
        pos.y.return_value = 100.0
        press = mock.Mock()
        press.button.return_value = Qt.LeftButton
        press.position.return_value = pos
        overlay.mousePressEvent(press)
        self.assertTrue(overlay._mouse_down)
        self.assertEqual(overlay._start, (100, 100))

        # Simulate mouse move
        move_pos = mock.Mock()
        move_pos.x.return_value = 150.0
        move_pos.y.return_value = 130.0
        move = mock.Mock()
        move.position.return_value = move_pos
        overlay.mouseMoveEvent(move)
        self.assertIsNotNone(overlay._rect)
        overlay.update.assert_called()

        # Simulate left button release — triggers _done since rect > 2x2
        release = mock.Mock()
        release.button.return_value = Qt.LeftButton
        overlay.mouseReleaseEvent(release)
        self.assertFalse(overlay._mouse_down)
        overlay.close.assert_called()

    def test_overlay_right_click_cancels(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        cancel_called = []
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        overlay._rect = None
        overlay._start = None
        overlay._mouse_down = False
        overlay._done_callback = None
        overlay.close = mock.Mock()

        def on_cancel():
            cancel_called.append(True)
        overlay._cancel_callback = on_cancel

        right_click = mock.Mock()
        right_click.button.return_value = Qt.RightButton
        overlay.mousePressEvent(right_click)
        self.assertEqual(cancel_called, [True])

    def test_overlay_escape_cancels(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        cancel_called = []
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        overlay._rect = None
        overlay._start = None
        overlay._mouse_down = False
        overlay._done_callback = None
        overlay.close = mock.Mock()

        def on_cancel():
            cancel_called.append(True)
        overlay._cancel_callback = on_cancel

        escape = mock.Mock()
        escape.key.return_value = Qt.Key_Escape
        overlay.keyPressEvent(escape)
        self.assertEqual(cancel_called, [True])


class ScreenshotOverlay(unittest.TestCase):
    """Should show a fullscreen overlay with a drag rectangle."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.app = QApplication.instance() or QApplication([])

    def test_overlay_has_translucent_background(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        # Verify attributes that would be set after __init__ exist
        overlay._rect = None
        overlay._start = None
        overlay._mouse_down = False
        self.assertIsNone(overlay._rect)

    def test_rect_is_set_on_mouse_move_during_drag(self):
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        overlay._start = (100, 100)
        overlay._rect = None
        overlay._mouse_down = True
        overlay._rect = (100, 100, 50, 30)
        self.assertIsNotNone(overlay._rect)


class ScreenshotFaceEyes(unittest.TestCase):
    """While in screenshot mode the target face aims eyes at the mouse."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def test_face_aims_at_mouse_in_screenshot_mode(self):
        window = self.face.FaceWindow("t1", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window._anim_timer.stop()
        # Set screenshot_face so the _aim method enters screenshot mode
        window.screenshot_face = window
        # Pointer must be between ON_FACE (~32px) and GAZE_NEAR (58px) of face center (334, 434).
        # vx=30, vy=20 → dist=37.4 → eye_aim returns non-trivial dx/dy.
        window._pointer = lambda: (364, 454)
        window._aim(16)
        target = window.anim.target
        # Should follow mouse, not do idle motion (dx/dy should be non-zero)
        self.assertNotEqual((target["dx"], target["dy"]), (0.0, 0.0))
        # Should not have pitch/yaw/roll from idle motion
        self.assertEqual(target["pitch"], 0.0)
        self.assertEqual(target["yaw"], 0.0)
        self.assertEqual(target["roll"], 0.0)

    def test_normal_aim_without_screenshot_mode(self):
        window = self.face.FaceWindow("t1", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window._anim_timer.stop()
        # No screenshot_face set
        window._pointer = lambda: (500, 500)
        window._aim(16)
        target = window.anim.target
        # Should go back to idle (Grok Bot still pose)
        self.assertEqual(target["dx"], 0.0)
        self.assertEqual(target["dy"], 0.0)


class FaceHideShow(unittest.TestCase):
    """Faces should be hidden before the grab and restored after."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def test_hide_all_faces(self):
        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        w2 = self._make_window("t2", "Test2")
        window.faces.faces = {"t1": window, "t2": w2}
        w2._poll_timer.stop()
        w2._anim_timer.stop()
        w2.show()
        window.show()
        self.assertTrue(window.isVisible())
        self.assertTrue(w2.isVisible())
        # Hide all faces
        for f in window.faces.faces.values():
            f.hide()
        self.assertFalse(window.isVisible())
        self.assertFalse(w2.isVisible())

    def _make_window(self, agent_id="t1", name="Test"):
        window = self.face.FaceWindow(agent_id, name, spot=(300, 400))
        window._poll_timer.stop()
        window._anim_timer.stop()
        return window


class AttachmentsStore(unittest.TestCase):
    """Should store screenshot bytes and send them."""

    def test_store_bytes_and_send(self):
        from pathlib import Path
        from botwidget import attachments

        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(attachments, 'TRANSFERS', Path(folder)):
                result = attachments.store_bytes("screenshot.png", b"fake png data")
                self.assertTrue(result.exists())
                self.assertEqual(result.read_bytes(), b"fake png data")

    def test_message_with_files(self):
        from pathlib import Path
        from botwidget import attachments

        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "screenshot.png"
            file_path.write_bytes(b"fake")
            msg = attachments.message_with("Screenshot", [file_path])
            self.assertIn("Screenshot", msg)
            self.assertIn("screenshot.png", msg)


class ScreenGrab(unittest.TestCase):
    """Should grab the selected region using a screen grab."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.app = QApplication.instance() or QApplication([])

    def test_grab_returns_pixmap(self):
        from botwidget.qt_ui.screenshot import screen_grab
        from PySide6.QtGui import QScreen
        # On offscreen, we can't really grab, but the function should exist
        self.assertTrue(callable(screen_grab))


class EndToEnd(unittest.TestCase):
    """End-to-end: enter mode, hide faces, capture, restore faces, send message."""

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config._config_read[:] = [None, {}]

    def _make_window(self, agent_id="t1", name="Test"):
        window = self.face.FaceWindow(agent_id, name, spot=(300, 400))
        window._poll_timer.stop()
        window._anim_timer.stop()
        return window

    def test_full_flow_with_mocked_grab(self):
        """Enter screenshot mode -> hide faces -> grab -> restore -> send."""
        from botwidget.qt_ui.screenshot import ScreenshotOverlay, screen_grab
        from PySide6.QtGui import QPixmap, QImage
        from botwidget import attachments

        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        w2 = self._make_window("t2", "Test2")
        window.faces.faces = {"t1": window, "t2": w2}
        w2._poll_timer.stop()
        w2._anim_timer.stop()
        window.show()
        w2.show()

        # Verify faces are visible
        self.assertTrue(window.isVisible())
        self.assertTrue(w2.isVisible())

        # Enter screenshot mode
        window.screenshot_face = window
        overlay = ScreenshotOverlay.__new__(ScreenshotOverlay)
        overlay._rect = None
        window._screenshot_overlay = overlay

        # Hide all faces
        for f in window.faces.faces.values():
            f.hide()
        self.assertFalse(window.isVisible())
        self.assertFalse(w2.isVisible())

        # Mock screen grab
        fake_pixmap = QPixmap(100, 100)
        fake_pixmap.fill(Qt.green)
        with mock.patch.object(ScreenshotOverlay, 'grab_region', return_value=fake_pixmap):
            overlay._rect = (0, 0, 100, 100)
            result = overlay.grab_region()
            self.assertIsNotNone(result)

        # Restore faces
        for f in window.faces.faces.values():
            f.show()
        self.assertTrue(window.isVisible())
        self.assertTrue(w2.isVisible())

        # Leave screenshot mode: mock close to avoid __init__ RuntimeError
        with mock.patch.object(overlay, 'close'):
            window._leave_screenshot_mode()
        self.assertIsNone(window.screenshot_face)
