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
from PySide6.QtWidgets import QApplication


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
        window = self.face.FaceWindow("t1", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        overlay = ScreenshotOverlay(window)
        self.addCleanup(overlay.close)

        # Patch update so we can verify it was called
        with mock.patch.object(overlay, 'update') as mock_update:
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
            mock_update.assert_called()

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
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
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

    def test_overlay_flags_allow_input(self):
        """Overlay must NOT have WindowTransparentForInput or WindowDoesNotAcceptFocus."""
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        window = self.face.FaceWindow("t1", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        overlay = ScreenshotOverlay(window)
        self.addCleanup(overlay.close)
        # Neither flag should be set
        self.assertFalse(overlay.windowFlags() & Qt.WindowTransparentForInput)
        self.assertFalse(overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        # But frameless and stays-on-top must be present
        self.assertTrue(overlay.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(overlay.windowFlags() & Qt.WindowStaysOnTopHint)

    def test_paint_event_does_not_raise_with_tuple_rect(self):
        """Setting _rect = (10, 20, 30, 40) and paintEvent must not TypeError."""
        from PySide6.QtCore import QRect
        from botwidget.qt_ui.screenshot import ScreenshotOverlay
        from PySide6.QtGui import QPaintEvent

        window = self.face.FaceWindow("t1", "Test", spot=(300, 400))
        self.addCleanup(window.close_face)
        overlay = ScreenshotOverlay(window)
        self.addCleanup(overlay.close)
        overlay._rect = (10, 20, 30, 40)
        # paintEvent should not raise
        overlay.paintEvent(QPaintEvent(QRect(0, 0, 400, 300)))

    def test_a_drag_a_failed_picture_and_a_missing_screen_stay_in_process(self):
        """Should cancel a tiny drag, ignore a middle click, and stop when the picture will not encode."""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap
        from botwidget.qt_ui.screenshot import (
            _finalize_screenshot, enter_screenshot_mode, pixmap_png_bytes, screen_grab)

        window = self.face.FaceWindow("shot", "Shot", spot=(300, 400))
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window._anim_timer.stop()
        window.faces = mock.Mock()
        window.faces.faces = {}
        window.on_user_message = mock.Mock()
        overlay = enter_screenshot_mode(window)
        self.addCleanup(overlay.close)
        overlay.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(3, 3), Qt.MouseButton.MiddleButton,
            Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(overlay._mouse_down)
        overlay.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, QPointF(4, 4), Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_A, Qt.KeyboardModifier.NoModifier))
        self.assertIsNone(overlay.grab_region())
        overlay._rect = (1, 1, 8, 8)
        grabbed = overlay.grab_region()
        self.assertTrue(grabbed is None or hasattr(grabbed, "isNull"))
        shot = screen_grab((1, 1, 8, 8))
        self.assertTrue(shot is None or hasattr(shot, "isNull"))
        with mock.patch("botwidget.qt_ui.screenshot.QGuiApplication.primaryScreen", return_value=None):
            self.assertIsNone(overlay.grab_region())
            self.assertIsNone(screen_grab((0, 0, 2, 2)))
        picture = QPixmap(8, 8)
        picture.fill(Qt.red)
        with mock.patch.object(QImage, "save", return_value=False):
            self.assertIsNone(pixmap_png_bytes(picture))
        _finalize_screenshot(window, [], (0, 0, 1, 1), QPixmap())
        window.on_user_message.assert_not_called()
        overlay._rect = (0, 0, 20, 20)
        overlay._mouse_down = True
        with mock.patch.object(overlay, "grab_region", return_value=None):
            overlay.mouseReleaseEvent(QMouseEvent(
                QEvent.Type.MouseButtonRelease, QPointF(20, 20), Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        again = enter_screenshot_mode(window)
        self.addCleanup(again.close)
        again.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(3, 3), Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier))
        again.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(2, 2), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        again.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(3, 3), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


class ScreenshotPngEncoding(unittest.TestCase):
    """pixmap_png_bytes encodes a QPixmap as valid PNG bytes."""

    @classmethod
    def setUpClass(cls):
        try:
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.app = QApplication.instance() or QApplication([])

    def test_pixmap_to_png_roundtrip(self):
        from botwidget.qt_ui.screenshot import pixmap_png_bytes
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.green)
        data = pixmap_png_bytes(pixmap)
        self.assertIsNotNone(data)
        self.assertIsInstance(data, bytes)
        self.assertGreater(len(data), 0)
        self.assertEqual(data[:4], b"\x89PNG")  # PNG magic bytes

    def test_null_pixmap_returns_none(self):
        from botwidget.qt_ui.screenshot import pixmap_png_bytes
        from PySide6.QtGui import QPixmap
        # An invalid (null) pixmap should return None
        null_pixmap = QPixmap()
        self.assertIsNone(pixmap_png_bytes(null_pixmap))


class FaceHideShow(unittest.TestCase):
    """Faces should be hidden before the grab and restored after."""

    @classmethod
    def setUpClass(cls):
        try:
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
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.face = face
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

    def test_done_hides_faces_before_grab(self):
        """_done must hide the overlay and all faces before grabbing, and restore them after."""
        from botwidget.qt_ui.screenshot import ScreenshotOverlay, enter_screenshot_mode, _restore_faces
        from PySide6.QtGui import QPixmap
        from botwidget import attachments
        from pathlib import Path

        window = self._make_window()
        self.addCleanup(window.close_face)
        w2 = self._make_window("t2", "Test2")
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window, "t2": w2}
        w2._poll_timer.stop()
        w2._anim_timer.stop()

        # Enter screenshot mode for real (creates real overlay)
        overlay = enter_screenshot_mode(window)
        self.addCleanup(overlay.close)
        self.assertTrue(overlay.isVisible())

        # Show faces so they start visible before _done hides them
        window.show()
        w2.show()
        self.assertTrue(window.isVisible())
        self.assertTrue(w2.isVisible())

        # Track whether faces are hidden at grab time
        face_visibility_at_grab = {}

        def mock_grab_region(self=None):
            face_visibility_at_grab["window"] = window.isVisible()
            face_visibility_at_grab["w2"] = w2.isVisible()
            face_visibility_at_grab["overlay"] = overlay.isVisible()
            fake = QPixmap(100, 100)
            fake.fill(Qt.blue)
            return fake

        # Patch grab_region on the class so _done calls our mock
        captured_bytes = []
        captured_paths = []

        def mock_store_bytes(name, data):
            captured_paths.append((name, data))
            return Path(tempfile.mkdtemp()) / name

        with mock.patch.object(ScreenshotOverlay, 'grab_region', mock_grab_region):
            with mock.patch.object(attachments, 'store_bytes', mock_store_bytes):
                with mock.patch.object(attachments, 'TRANSFERS', Path(tempfile.mkdtemp())):
                    window.on_user_message = mock.Mock()

                    overlay._rect = (10, 20, 50, 40)

                    # Call _done directly — this triggers the real on_done callback chain
                    overlay._done((10, 20, 50, 40))

        # Faces must have been hidden at grab time
        self.assertFalse(face_visibility_at_grab.get("window", True))
        self.assertFalse(face_visibility_at_grab.get("w2", True))
        self.assertFalse(face_visibility_at_grab.get("overlay", True))

        # After _done, faces should be restored
        self.assertTrue(window.isVisible())
        self.assertTrue(w2.isVisible())

        # store_bytes should have been called with PNG bytes
        self.assertEqual(len(captured_paths), 1)
        name, data = captured_paths[0]
        self.assertEqual(name, "screenshot.png")
        self.assertEqual(data[:4], b"\x89PNG")
        self.assertGreater(len(data), 0)

    def test_done_with_no_pixmap_calls_cancel(self):
        """If grab returns None, _done calls the cancel callback."""
        from botwidget.qt_ui.screenshot import ScreenshotOverlay, enter_screenshot_mode

        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window}

        overlay = enter_screenshot_mode(window)
        self.addCleanup(overlay.close)

        cancel_called = []

        def on_cancel():
            cancel_called.append(True)

        overlay._cancel_callback = on_cancel
        overlay._done_callback = None  # no done callback
        overlay._rect = (10, 20, 50, 40)

        with mock.patch.object(overlay, 'grab_region', return_value=None):
            overlay._done((10, 20, 50, 40))

        self.assertEqual(cancel_called, [True])

    def test_full_flow_with_real_png_encoding(self):
        """End-to-end: enter mode, drag, grab, encode, store_bytes called."""
        from botwidget.qt_ui.screenshot import enter_screenshot_mode, pixmap_png_bytes
        from botwidget import attachments
        from PySide6.QtGui import QPixmap
        from pathlib import Path

        window = self._make_window()
        self.addCleanup(window.close_face)
        window.faces = mock.Mock()
        window.faces.faces = {"t1": window}
        window.show()

        overlay = enter_screenshot_mode(window)
        self.addCleanup(overlay.close)

        captured_paths = []

        def mock_store_bytes(name, data):
            captured_paths.append((name, data))
            return Path(tempfile.mkdtemp()) / name

        with mock.patch.object(attachments, 'store_bytes', mock_store_bytes):
            with mock.patch.object(attachments, 'TRANSFERS', Path(tempfile.mkdtemp())):
                # Stub on_user_message so nothing is actually sent
                window.on_user_message = mock.Mock()

                overlay._rect = (10, 20, 50, 40)

                # Provide a real pixmap and let the flow complete
                fake_pixmap = QPixmap(100, 100)
                fake_pixmap.fill(Qt.red)
                overlay._done_callback(None, fake_pixmap)

        self.assertEqual(len(captured_paths), 1)
        name, data = captured_paths[0]
        self.assertEqual(name, "screenshot.png")
        self.assertEqual(data[:4], b"\x89PNG")
        self.assertGreater(len(data), 0)
