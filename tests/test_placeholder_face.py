"""The placeholder face exists exactly when no bot exists: none on the desktop, none in the arc.

Uses only a temporary widget.json. Offscreen Qt, no network.
"""

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PlaceholderFace(unittest.TestCase):

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
        from botwidget import config
        from botwidget.qt_ui.faces import Faces

        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self._config = os.path.join(self._folder.name, "widget.json")
        with open(self._config, "w") as fh:
            json.dump({"sound": True, "acp_bots": [{"name": "Mine", "command": "true"}]}, fh)
        self._state = os.path.join(self._folder.name, "state.json")
        with open(self._state, "w") as fh:
            json.dump({"enabled": ["acp:mine"], "pos": {"unlinked": [500, 300]}}, fh)

        self.bots = [
            {"id": "home", "name": "Home", "threadId": "t-home", "hue": None, "seed": "home", "status": "ready"},
            {"id": "away", "name": "Away", "threadId": "t-away", "hue": None, "seed": "away", "status": "ready"},
        ]
        stack = ExitStack()
        self.addCleanup(stack.close)
        self._old_path = config.CONFIG_PATH
        config.CONFIG_PATH = self._config
        config._config_read[:] = [None, {}]
        stack.callback(self._restore_config)
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.STATE_PATH", self._state))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.list_bots", return_value=[]))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.openbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.gbot_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.hermesbot.is_hermes_installed", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.check_updates", return_value=False))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.threading.Thread", return_value=mock.Mock()))
        stack.enter_context(mock.patch("botwidget.qt_ui.face.latest_chat", return_value={"messages": [], "activity": ""}))
        self.faces = Faces()
        self.addCleanup(self._close)

    def _restore_config(self):
        from botwidget import config
        config.CONFIG_PATH = self._old_path
        config._config_read[:] = [None, {}]

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

    def test_removing_the_last_bot_shows_the_placeholder_and_a_new_bot_takes_its_spot(self):
        from botwidget import acp_bots
        self.assertEqual(list(self.faces.faces), ["acp:mine"])
        self.faces._remove_bot("acp:mine")
        self.assertEqual(list(self.faces.faces), ["unlinked"])
        spot = self.faces.faces["unlinked"].spot()

        self.faces._bot_draft = {**acp_bots.blank(), "name": "Again", "command": "true"}
        self.assertEqual(self.faces._commit_bot(), "")
        self.assertEqual(list(self.faces.faces), ["acp:again"])
        self.assertEqual(self.faces.faces["acp:again"].spot(), spot)

    def test_a_bot_hidden_in_the_arc_is_still_a_bot(self):
        self.faces.toggle("acp:mine", False)
        self.assertEqual(list(self.faces.faces), [], "no placeholder next to a bot in the arc")

    def test_removing_a_hidden_last_bot_shows_the_placeholder(self):
        self.faces.toggle("acp:mine", False)
        self.faces._remove_bot("acp:mine")
        self.assertEqual(list(self.faces.faces), ["unlinked"])


if __name__ == "__main__":
    unittest.main()
