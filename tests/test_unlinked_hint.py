import os
import tempfile
import unittest
from unittest import mock

from botwidget import config


class UnlinkedHint(unittest.TestCase):
    """The placeholder bot says it has no bot yet once; a bot with a backend of its own never does."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui import face
        cls.face = face
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
        self.addCleanup(setattr, config, "CONFIG_PATH", old_path)
        config._config_read[:] = [None, {}]
        for name in ("openbot_installed", "gbot_installed"):
            patcher = mock.patch.object(self.face, name, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def shows_hint(self, **kwargs):
        window = self.face.FaceWindow("unlinked" if "link" not in kwargs else "acp:x", "Bot", spot=(300, 400), **kwargs)
        self.addCleanup(window.close_face)
        window._poll_timer.stop()
        window._anim_timer.stop()
        window.faces = mock.Mock()
        window.faces.faces = {}
        window._sync_bubble({"messages": [], "activity": ""}, force=True)
        return window.bubble.kind == "hint"

    def test_the_placeholder_bot_says_so_the_first_time_only(self):
        self.assertTrue(self.shows_hint())
        self.assertFalse(self.shows_hint(), "told once, not at every start")

    def test_a_bot_with_its_own_backend_never_says_so(self):
        self.assertFalse(self.shows_hint(link=mock.Mock(note=lambda: "", active=lambda: False)))
        self.assertFalse(config.widget_config().get("unlinked_hint_shown"), "and it does not use up the one time")


if __name__ == "__main__":
    unittest.main()
