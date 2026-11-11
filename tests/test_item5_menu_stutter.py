"""Item 5: Menu stutter fix — _show_command_menu no longer double-lays out.

_before: _show_command_menu called _layout_children() then place("say") which
also called _layout_children(). The fix: _show_command_menu delegates layout
to place() and removes its own _layout_children call.
"""

import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config


class MenuStutter(unittest.TestCase):
    """_show_command_menu should layout only once, not twice."""

    def test_show_command_menu_does_not_double_layout(self):
        """Verify _layout_children is called only once during menu open."""
        try:
            from unittest import mock
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face

            with tempfile.TemporaryDirectory() as folder:
                old_path = config.CONFIG_PATH
                config.CONFIG_PATH = os.path.join(folder, "widget.json")
                config._config_read[:] = [None, {}]
                try:
                    app = QApplication.instance() or QApplication([])
                    window = face.FaceWindow("t1", "Test", spot=(300, 400))
                    window._poll_timer.stop()
                    window._anim_timer.stop()
                    window.faces = mock.Mock()
                    window.faces.faces = {"t1": window}
                    window.show()

                    # Open a message bubble first
                    window._outbox.add("test", "c1")
                    window._pump_outbox = lambda: None
                    window._sync_bubble({"messages": [{"role": "bot", "text": "hello"}], "activity": ""})
                    # Wait for growth animation to finish
                    time.sleep(0.3)
                    app.processEvents()

                    bubble = window.bubble
                    original_layout = bubble._layout_children

                    calls = []
                    def counted_layout(*args):
                        calls.append(time.monotonic())
                        return original_layout(*args)

                    bubble._layout_children = counted_layout

                    # Now open the command menu
                    # No event loop turn here: a timer of the earlier animation would add its own call.
                    bubble._show_command_menu()

                    # Should be exactly one layout call
                    # (The previous buggy code had 2)
                    self.assertEqual(len(calls), 1,
                                     f"_layout_children was called {len(calls)} times; expected 1")

                finally:
                    config.CONFIG_PATH = old_path
                    config._config_read[:] = [None, {}]
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
