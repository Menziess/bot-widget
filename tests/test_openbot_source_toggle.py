"""Turning OpenBot off on /connections must persist and actually hide its bots.

Uses only a temporary widget.json, never the real user config.
Offscreen Qt, no network.
"""

import json
from pathlib import Path
import os
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class OpenBotSourceToggle(unittest.TestCase):

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
            json.dump({"sound": True}, fh)
        self._state = os.path.join(self._folder.name, "state.json")
        with open(self._state, "w") as fh:
            json.dump({"enabled": ["home"], "pos": {"home": [400, 400]}}, fh)

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
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.list_bots", return_value=self.bots))
        stack.enter_context(mock.patch("botwidget.qt_ui.faces.openbot_installed", return_value=True))
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

    def test_turning_openbot_off_persists_and_drops_its_bots(self):
        from botwidget import config
        from botwidget.menu_pages import connections
        from botwidget.qt_ui.faces import _all_bots, bot_source

        self.assertTrue(config.source_enabled("openbot"))
        self.assertEqual({bot["id"] for bot in _all_bots()}, {"home", "away"})
        self.assertIn("home", self.faces.faces)
        self.assertEqual(bot_source("home"), "OpenBot")

        page = self.faces.menu_state()
        blocks = connections(page)
        text = " ".join(
            chunk[0] if isinstance(chunk, (list, tuple)) else ""
            for block in blocks
            for chunk in block.get("chunks") or []
        )
        # The page helper in other tests uses markdown.block_text; also check the toggle state.
        self.assertNotIn("openbot", page["sources_off"])

        result = self.faces.menu_command("connect/openbot", "connections")
        self.assertEqual(result, "connections")
        config._config_read[:] = [None, {}]
        self.assertFalse(config.source_enabled("openbot"))
        saved = json.loads(Path(self._config).read_text())
        self.assertEqual(saved.get("sources_off"), ["openbot"])
        self.assertNotIn("home", self.faces.faces)
        self.assertEqual(_all_bots(), [])

        state = self.faces.menu_state()
        text = _page_text(connections(state))
        self.assertIn("☐ OpenBot", text)
        self.assertIn("Off. OpenBot is installed, but its bots are not shown.", text)

        # Reopen: still off, from the file, not from "installed".
        config._config_read[:] = [None, {}]
        again = connections(self.faces.menu_state())
        self.assertIn("☐ OpenBot", _page_text(again))

        # Turning it back on clears the flag; bots are listed again.
        self.faces.menu_command("connect/openbot", "connections")
        config._config_read[:] = [None, {}]
        self.assertTrue(config.source_enabled("openbot"))
        self.assertEqual(json.loads(Path(self._config).read_text()).get("sources_off"), [])
        self.assertEqual({bot["id"] for bot in _all_bots()}, {"home", "away"})

    def test_does_not_write_the_user_widget_json(self):
        """The test file is the only widget.json this class may touch."""
        self.assertTrue(self._config.startswith(self._folder.name))
        from botwidget import config
        self.assertEqual(config.CONFIG_PATH, self._config)


def _page_text(blocks):
    from botwidget import markdown
    return markdown.block_text(blocks)
