"""Item 8: Trail window stays on top and doesn't raise every frame.

On Linux/X11, a Trail window with WindowStaysOnBottomHint + frequent raise() calls
during drag leaves black artefacts around the bot. The fix: Trail always uses
WindowStaysOnTopHint and raises only once on first show.
"""

import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


class TrailWindowFlags(unittest.TestCase):
    """The Trail window should use WindowStaysOnTopHint, not WindowStaysOnBottomHint."""

    @classmethod
    def setUpClass(cls):
        try:
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        cls.app = QApplication.instance() or QApplication([])

    def test_trail_has_stays_on_top(self):
        from botwidget.qt_ui.bubble_window import Trail
        from unittest import mock

        bubble = mock.Mock()
        bubble.face = mock.Mock()
        trail = Trail(bubble)
        # Should have WindowStaysOnTopHint (the fix)
        self.assertTrue(trail.windowFlags() & Qt.WindowStaysOnTopHint,
                        "Trail must stay on top to avoid black artefacts during drag")
        # Should still be Tool (no taskbar), frameless, and transparent for input
        self.assertTrue(trail.windowFlags() & Qt.Tool)
        self.assertTrue(trail.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(trail.windowFlags() & Qt.WindowTransparentForInput)

    def test_trail_raises_only_once(self):
        """Verify _raised flag prevents repeated raise() calls."""
        from botwidget.qt_ui.bubble_window import Trail
        from unittest import mock
        from PySide6.QtCore import QRect, QPointF
        from PySide6.QtGui import QPaintEvent

        bubble = mock.Mock()
        bubble.face = mock.Mock()
        trail = Trail(bubble)
        trail._balls = [[100, 100, 0, 0], [105, 105, 0, 0], [110, 110, 0, 0]]

        # Mock raise_window
        with mock.patch('botwidget.qt_ui.bubble_window.raise_window') as mock_raise:
            with mock.patch.object(trail, 'update'):
                cloud = mock.Mock()
                cloud.center.return_value = QPointF(105, 100)
                cloud.width.return_value = 200
                cloud.height.return_value = 60
                bot = QPointF(200, 300)

                # First step: should raise
                trail.step(cloud, bot)
                self.assertEqual(mock_raise.call_count, 1)

                # Second step: should NOT raise again
                trail.step(cloud, bot)
                self.assertEqual(mock_raise.call_count, 1,
                                 "Trail should only raise once, not every frame")
