"""The screenshot is on the command list (right-click or a typed slash), next to the double-click on a face."""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config, menu_pages


class Discoverable(unittest.TestCase):
    def test_the_command_list_offers_screenshot_and_the_note_names_the_double_click(self):
        rows = dict(menu_pages.commands())
        self.assertIn("/screenshot", rows)
        self.assertIn("double-click", rows["/screenshot"])

    def test_the_slash_command_enters_screenshot_mode_and_nothing_else(self):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui import face
        except ImportError as error:
            raise unittest.SkipTest(f"no Qt: {error}")
        with tempfile.TemporaryDirectory() as folder:
            old = config.CONFIG_PATH
            config.CONFIG_PATH = os.path.join(folder, "widget.json")
            config._config_read[:] = [None, {}]
            try:
                QApplication.instance() or QApplication([])
                window = face.FaceWindow("t1", "Test", spot=(300, 400))
                window._poll_timer.stop()
                window._anim_timer.stop()
                with mock.patch("botwidget.qt_ui.screenshot.enter_screenshot_mode") as enter:
                    window.on_user_message("/screenshot")
                    window.on_user_message("/screenshot")  # already in the mode: window.screenshot_face is set
                enter.assert_called_once_with(window)
                self.assertTrue(window._screenshot_active)
                window._leave_screenshot_mode()
                self.assertFalse(window._screenshot_active)
            finally:
                config.CONFIG_PATH = old
                config._config_read[:] = [None, {}]


if __name__ == "__main__":
    unittest.main()
