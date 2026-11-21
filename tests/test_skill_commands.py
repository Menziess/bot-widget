"""Slash commands from an ACP available_commands_update, after the built-ins.

Offscreen Qt where a face is needed. widget.json is a temp file. No network.
"""

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from botwidget import config, menu_pages
from botwidget.acplink import AcpLink
from harness.acp_client import AcpClient, Update


SKILLS = (
    ("review", "Look at a diff"),
    ("/screenshot", "should not replace the built-in"),
    ("screenshot", "same collision"),
    ("", "skip"),
    ("   ", "blank"),
    ("/Review", "same name, different case"),
)


def _temp_config():
    folder = tempfile.TemporaryDirectory()
    old = config.CONFIG_PATH
    config.CONFIG_PATH = os.path.join(folder.name, "widget.json")
    os.makedirs(folder.name, exist_ok=True)
    with open(config.CONFIG_PATH, "w") as fh:
        json.dump({}, fh)
    config._config_read[:] = [None, {}]
    return folder, old


def _restore_config(folder, old):
    config.CONFIG_PATH = old
    config._config_read[:] = [None, {}]
    folder.cleanup()


class MergeCommands(unittest.TestCase):
    """Should keep built-ins first and drop a skill that reuses one of their names."""

    def test_should_return_only_built_ins_when_a_bot_has_no_skills(self):
        self.assertEqual(menu_pages.commands(), menu_pages.COMMANDS)
        self.assertEqual(menu_pages.commands(()), menu_pages.COMMANDS)

    def test_should_list_skills_after_built_ins_and_drop_collisions_and_blanks(self):
        rows = menu_pages.commands(SKILLS)
        self.assertEqual(rows[:len(menu_pages.COMMANDS)], menu_pages.COMMANDS)
        self.assertEqual(rows[len(menu_pages.COMMANDS):], (("/review", "Look at a diff"),))
        names = [name for name, _note in rows]
        self.assertEqual(names.count("/screenshot"), 1)
        self.assertIn("double-click", dict(rows)["/screenshot"])


class AvailableCommandsUpdate(unittest.IsolatedAsyncioTestCase):
    """Should store an ACP available_commands_update on the link the face reads."""

    async def test_should_turn_the_update_into_command_rows(self):
        from acp.schema import AvailableCommand, AvailableCommandsUpdate
        client = AcpClient("unused")
        seen = []
        client.on_update = seen.append
        await client.session_update("s", AvailableCommandsUpdate(
            session_update="available_commands_update",
            available_commands=[
                AvailableCommand(name="review", description="Look at a diff"),
                AvailableCommand(name="/screenshot", description="nope"),
            ]))
        self.assertEqual(seen, [Update("commands", extra={"commands": [
            ("review", "Look at a diff"), ("/screenshot", "nope")]})])
        link = AcpLink.__new__(AcpLink)
        link._lock = threading.Lock()
        link._commands = ()
        link._updated(seen[0])
        self.assertEqual(link.available_commands(), (("review", "Look at a diff"), ("/screenshot", "nope")))
        link._updated(Update("commands", extra={"commands": []}))
        self.assertEqual(link.available_commands(), ())


class SkillRowsInTheBubble(unittest.TestCase):
    """Should show the skill on that bot's list and send it as a normal message."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.folder, old = _temp_config()
        self.addCleanup(_restore_config, self.folder, old)
        from botwidget.qt_ui.face import FaceWindow
        self.window = FaceWindow("t", "Ada", spot=(300, 400))
        self.window._poll_timer.stop()
        self.window._anim_timer.stop()
        self.window._hint_shown = True
        self.window._pump_outbox = lambda: None
        self.window._latest = lambda: {"messages": [], "activity": ""}
        self.addCleanup(self._close)

    def _close(self):
        self.window.acp = None
        self.window.close_face()

    def _link(self, commands):
        class Link:
            stopped = False

            def available_commands(self):
                return commands

            def close(self):
                return None

            def resume(self):
                return None

            def note(self):
                return ""

            def active(self):
                return False

            def chat(self):
                return {"messages": [], "activity": ""}

        self.window.acp = Link()

    def test_should_show_only_built_ins_when_the_bot_has_no_skills(self):
        self.window.bubble.show_command_menu()
        from botwidget.demo_chat import dev_running
        self.assertEqual(self.window.bubble._slash.rows, list(menu_pages.commands(dev=dev_running())))

    def test_should_show_the_update_on_this_bot_and_send_the_skill_with_typed_arguments(self):
        self._link((("review", "Look at a diff"), ("screenshot", "nope"), ("", "skip")))
        self.assertEqual(self.window.command_rows()[:len(menu_pages.COMMANDS)], menu_pages.COMMANDS)
        self.window.bubble._entry.setText("/review the diff")
        self.window.bubble.show_command_menu()
        rows = self.window.bubble._slash.rows
        from botwidget.demo_chat import dev_running
        built_in = list(menu_pages.commands(dev=dev_running()))
        self.assertEqual(rows[:len(built_in)], built_in)
        self.assertEqual(rows[len(built_in):], [("/review", "Look at a diff")])
        with mock.patch.object(self.window, "start_screenshot") as shot, \
                mock.patch.object(self.window, "open_menu") as page:
            self.window.bubble._slash.chosen.emit("/review")
        self.assertEqual([item["text"] for item in self.window._outbox.items], ["/review the diff"])
        shot.assert_not_called()
        page.assert_not_called()
        self.assertIsNone(self.window._menu_page)
        self.window._poll_timer.stop()

    def test_should_filter_a_typed_skill_and_not_open_a_built_in_page(self):
        self._link((("review", "Look at a diff"),))
        self.window.bubble.show_blocks([], "say", input=True)
        self.window.bubble._entry.setText("/rev")
        self.app.processEvents()
        self.assertEqual(self.window.bubble._slash.rows, [("/review", "Look at a diff")])
        self.window.bubble._slash.chosen.emit("/review")
        self.assertEqual([item["text"] for item in self.window._outbox.items], ["/review"])
        self.assertIsNone(self.window._menu_page)
        self.window._poll_timer.stop()
