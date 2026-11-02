"""Harness bots are added from the widget. The key stays in its file, and a save does not restart the others."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

from botwidget import acp_bots, acplink, config
from botwidget.avatar import GROK_HEX, avatar_profile
from botwidget.menu_pages import bot_form, bots

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAKE = f"{sys.executable} {os.path.join(ROOT, 'tests', 'fake_acp_agent.py')}"
SENTINEL = "sk-sentinel-not-a-real-key"


def wait_for(condition, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


class ConfigFile(unittest.TestCase):
    """Should keep bots that are already in widget.json, and leave a broken file alone."""

    def test_a_setting_saved_later_keeps_the_bots_even_when_memory_is_stale(self):
        config.save_widget_config(acp_bots=[{"id": "a", "name": "A", "command": "python -m harness.agent"}])
        stat = os.stat(config.CONFIG_PATH)
        config._config_read[:] = [(config.CONFIG_PATH, stat.st_mtime_ns, stat.st_size), {"sound": False}]
        config.save_widget_config(sound=True)
        saved = config.widget_config()
        self.assertEqual(saved["acp_bots"][0]["name"], "A")
        self.assertIs(saved["sound"], True)

    def test_a_file_that_cannot_be_read_is_not_replaced(self):
        with open(config.CONFIG_PATH, "w") as fh:
            fh.write("{not json")
        before = open(config.CONFIG_PATH).read()
        config.save_widget_config(sound=True)
        self.assertEqual(open(config.CONFIG_PATH).read(), before)

    def test_the_editor_refuses_a_key_keeps_a_backup_and_saves_the_rest(self):
        config.save_widget_config(sound=True)
        refused, error = acp_bots.parse_editor(json.dumps({"sound": True, "api_key": SENTINEL}))
        self.assertIsNone(refused)
        self.assertIn("api_key", error)
        self.assertNotIn(SENTINEL, error)
        text = acp_bots.public_text({"sound": True, "env": {"HARNESS_MODEL_API_KEY": SENTINEL}, "note": "keep"})
        self.assertNotIn(SENTINEL, text)
        data, error = acp_bots.parse_editor(text)
        self.assertEqual(error, "")
        self.assertEqual(config.replace_widget_config(data), "")
        self.assertEqual(json.load(open(config.CONFIG_PATH + ".bak"))["sound"], True)
        saved = json.load(open(config.CONFIG_PATH))
        self.assertEqual(saved["note"], "keep")
        self.assertNotIn("HARNESS_MODEL_API_KEY", json.dumps(saved))


class BotForm(unittest.TestCase):
    """Should add two bots on one model, rename one, recolour it, and refuse to store the key."""

    def test_a_new_bot_starts_from_the_local_llama_server(self):
        shown = "\n".join(
            block.get("label", "") + " " + str(block.get("value") or "")
            for block in bot_form({}) if block.get("kind") == "control")
        self.assertIn("New bot", "\n".join(str(block.get("chunks")) for block in bot_form({})))
        self.assertIn("http://127.0.0.1:8080/v1", shown)
        self.assertIn("local", shown)
        self.assertIn("~/.config/llm/key", shown)
        self.assertIn("nuage", shown)
        self.assertIn("blue", shown)

    def test_the_bots_page_can_add_edit_and_remove_a_harness_bot(self):
        blocks = bots({"bots": [{"id": "acp:local", "name": "Local", "on": True, "acp": True}]})
        commands = [block.get("command") for block in blocks if block.get("kind") == "control"]
        self.assertIn("page/bot", commands)
        self.assertIn("page/bot/acp:local", commands)
        self.assertIn("bot-remove/acp:local", commands)
        self.assertIn("page/widget-json", commands)

    def test_two_bots_share_a_model_and_a_rename_keeps_the_id(self):
        first, error = acp_bots.commit({**acp_bots.blank(), "name": "Local"}, [])
        second, error = acp_bots.commit({**acp_bots.blank(), "name": "Other", "color": "green"}, first)
        self.assertEqual(error, "")
        self.assertIn("harness.agent", first[0]["command"])
        self.assertNotIn("11434", json.dumps(first))
        self.assertEqual([row["id"] for row in second], ["local", "other"])
        self.assertEqual({row["env"]["HARNESS_MODEL_BASE_URL"] for row in second}, {"http://127.0.0.1:8080/v1"})
        self.assertEqual({row["env"]["HARNESS_MODEL"] for row in second}, {"local"})
        renamed, error = acp_bots.commit({**acp_bots.fields_of({"id": "acp:local", "name": "Local",
                                                                "command": first[0]["command"], "env": first[0]["env"],
                                                                "key_file": first[0]["key_file"], "face": "nuage",
                                                                "color": "blue"}), "name": "Renamed"}, second)
        self.assertEqual(error, "")
        self.assertEqual(renamed[0]["id"], "local")
        self.assertEqual(renamed[0]["name"], "Renamed")
        self.assertNotIn(SENTINEL, json.dumps(renamed))

    def test_a_colour_change_does_not_restart_and_a_model_change_restarts_only_that_bot(self):
        before = [{"id": "acp:local", "name": "Local", "command": "run", "key_file": "k",
                   "env": {"HARNESS_MODEL": "local", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1",
                           "HARNESS_BOT": "Local"}, "face": "nuage", "color": "blue"},
                  {"id": "acp:other", "name": "Other", "command": "run", "key_file": "k",
                   "env": {"HARNESS_MODEL": "local", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1",
                           "HARNESS_BOT": "Other"}, "face": "nuage", "color": "green"}]
        recolour = [dict(before[0], color="violet"), before[1]]
        self.assertEqual(acp_bots.plan(before, recolour), [("restyle", "acp:local")])
        remodel = [dict(before[0], env={**before[0]["env"], "HARNESS_MODEL": "other"}), before[1]]
        self.assertEqual(acp_bots.plan(before, remodel), [("restart", "acp:local")])
        self.assertEqual(acp_bots.plan(before, before[:1]), [("close", "acp:other")])

    def test_a_chosen_face_and_colour_are_what_gets_drawn(self):
        profile = avatar_profile("acp:local", None, {"shape": "nuage", "color": "blue"})
        self.assertEqual(profile["shape"], "nuage")
        self.assertEqual(profile["hex"], GROK_HEX["blue"])


class WidgetSave(unittest.TestCase):
    """Should add a bot from the same commands the page sends, chat, rename, recolour and remove it."""

    def setUp(self):
        try:
            from botwidget.qt_ui.faces import Faces
        except ImportError as error:
            self.skipTest(f"no Qt: {error}")
        self.faces_cls = Faces
        self.calls = []
        self.box = self.faces_cls.__new__(self.faces_cls)
        self.box.faces = {}
        self.box._arc_guests = {}
        self.box._semicircle = {}
        self.box._arc_order = []
        self.box.toggle = lambda ident, on: self.calls.append(("toggle", ident, on))
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.key = os.path.join(folder, "key")
        with open(self.key, "w") as fh:
            fh.write(SENTINEL + "\n")

    def save(self, name: str, **extra):
        draft = {**acp_bots.blank(), "name": name, "key_file": self.key, "command": FAKE, **extra}
        self.box._bot_draft = draft
        fields = {f"field/{key}": draft[key] for key in ("name", "base_url", "model", "key_file")}
        return self.box.menu_command("action/save-bot", "bot", fields)

    def test_add_chat_rename_recolour_and_remove_on_a_fresh_config(self):
        self.assertEqual(self.save("Harness Check"), "bots")
        self.assertEqual(self.save("Second Check", color="green"), "bots")
        saved = json.load(open(config.CONFIG_PATH))
        self.assertNotIn(SENTINEL, json.dumps(saved), "the key file's contents stay out of widget.json")
        bots_saved = saved["acp_bots"]
        self.assertEqual([row["env"]["HARNESS_MODEL"] for row in bots_saved], ["local", "local"])
        self.assertEqual([row["env"]["HARNESS_MODEL_BASE_URL"] for row in bots_saved],
                         ["http://127.0.0.1:8080/v1", "http://127.0.0.1:8080/v1"])
        self.assertEqual([row["id"] for row in bots_saved], ["harness-check", "second-check"])
        self.assertEqual([call[1] for call in self.calls], ["acp:harness-check", "acp:second-check"])

        link = acplink.AcpLink(acplink.target_for("acp:harness-check"), **acplink.options_for("acp:harness-check"))
        self.addCleanup(link.close)
        self.addCleanup(shutil.rmtree, link.room(), True)
        link.send("hello")
        self.assertTrue(wait_for(lambda: not link.active() and any(
            message["role"] == "bot" for message in link.chat()["messages"])))
        self.assertIn("Answer hello", link.chat()["messages"][-1]["text"])
        room = link.room()
        link.close()

        face = type("Face", (), {})()
        face.bot_name = "Harness Check"
        face._menu_page = None
        face.avatar = None
        face.setWindowTitle = lambda name: setattr(face, "title", name)
        face.set_avatar = lambda avatar: setattr(face, "avatar", avatar)
        self.box.faces["acp:harness-check"] = face
        self.calls.clear()
        self.box.menu_command("page/bot/acp:harness-check", "bots")
        self.box.menu_command("cycle/color", "bot/acp:harness-check")
        self.assertEqual(self.box.menu_command("action/save-bot", "bot/acp:harness-check", {}), "bots")
        self.assertEqual(self.calls, [], "a new colour does not restart the agent")
        self.assertEqual(face.avatar["color"], "green")
        self.assertTrue(os.path.isdir(room), "recolouring leaves the session folder")

        self.box.menu_command("page/bot/acp:harness-check", "bots")
        self.assertEqual(self.box.menu_command("action/save-bot", "bot/acp:harness-check",
                                               {"field/name": "Renamed Check"}), "bots")
        self.assertEqual([call[:2] for call in self.calls], [("toggle", "acp:harness-check"),
                                                             ("toggle", "acp:harness-check")])
        self.assertNotIn("acp:second-check", [call[1] for call in self.calls])
        self.assertEqual(json.load(open(config.CONFIG_PATH))["acp_bots"][0]["id"], "harness-check")

        self.box.menu_command("bot-remove/acp:harness-check", "bots")
        left = json.load(open(config.CONFIG_PATH))["acp_bots"]
        self.assertEqual([row["id"] for row in left], ["second-check"])
        self.assertTrue(os.path.isdir(room), "removing the bot from the widget leaves its session folder")


class EditPage(unittest.TestCase):
    """Should open the edit page when the Edit button is clicked, not only when the command is sent by hand."""

    def setUp(self):
        try:
            from PySide6.QtWidgets import QApplication
            from botwidget.qt_ui.face import FaceWindow
            from botwidget.qt_ui.faces import Faces
        except ImportError as error:
            self.skipTest(f"no Qt: {error}")
        self.app = QApplication.instance() or QApplication([])
        self.FaceWindow, self.Faces = FaceWindow, Faces
        # As stored before a bot had a stable id: the page still has to open on that bot.
        config.save_widget_config(acp_bots=[{
            "name": "Local Bot", "command": "python -m harness.agent", "key_file": "/tmp/not-a-key",
            "env": {"HARNESS_BOT": "Local Bot", "HARNESS_MODEL": "local",
                    "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1"},
        }])

    def test_clicking_edit_opens_that_bots_page(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from botwidget.qt_ui.controls import ActionButton

        box = self.Faces.__new__(self.Faces)
        box.faces = {}
        box.toggle = lambda *_args: None
        box.close_bubbles_except = lambda *_args: None
        box.hold_arc = lambda: None

        def menu_state():
            return {
                "version": "0", "channel": "local", "switch_label": None, "hotkey": "",
                "update": "", "staged_update": "", "sound": False, "quiet_hours": False,
                "always_on_top": False, "can_pick_desktops": False, "can_glass": False, "glass_clear": 0,
                "all_desktops": False, "login": False, "check_updates": False, "save_battery": False,
                "can_install_updates": False, "auto_update": False,
                "bots": [{"id": "acp:local-bot", "name": "Local Bot", "on": False, "muted": False,
                          "source": "Harness", "acp": True}],
                "bot_form": getattr(box, "_bot_draft", None), "bot_error": getattr(box, "_bot_error", ""),
                "json_text": "", "json_error": "", "openbot": False, "automation_ready": False,
                "gbot": False, "grok": "", "grok_target": "", "hermes": False, "wanted": [],
            }

        box.menu_state = menu_state
        window = self.FaceWindow("t", "Test", spot=(300, 400), faces=box)
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        window.open_menu("bots")
        self.app.processEvents()
        bubble = window.bubble
        edit = next(w for w in bubble._control_widgets if isinstance(w, ActionButton) and w.text() == "Edit Local Bot")
        # Where the text window receives the click that was meant for the button.
        point = QPoint(edit.geometry().center().x() - bubble._doc.x(), edit.geometry().center().y() - bubble._doc.y())
        QTest.mouseClick(bubble._doc.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.app.processEvents()
        self.assertIn("Edit bot", bubble.full_text)
        self.assertIn("Name: Local Bot", bubble.full_text)
        self.assertEqual(window._menu_page, "bot/acp:local-bot")

    def test_a_missed_pointer_sample_after_edit_does_not_close_the_page(self):
        """Should keep Edit bot open when X names no window on the frame after the click.

        The pointer was on the bots page, so the page change counts as touched. XWayland
        often answers 0 for that next frame. That one miss is not leaving. Once a later
        frame sees the pointer, leaving still closes at once.
        """
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        from botwidget.qt_ui.controls import ActionButton
        from botwidget.qt_ui.native import native_id

        box = self.Faces.__new__(self.Faces)
        box.faces = {}
        box.toggle = lambda *_args: None
        box.close_bubbles_except = lambda *_args: None
        box.hold_arc = lambda: None

        def menu_state():
            return {
                "version": "0", "channel": "local", "switch_label": None, "hotkey": "",
                "update": "", "staged_update": "", "sound": False, "quiet_hours": False,
                "always_on_top": False, "can_pick_desktops": False, "can_glass": False, "glass_clear": 0,
                "all_desktops": False, "login": False, "check_updates": False, "save_battery": False,
                "can_install_updates": False, "auto_update": False,
                "bots": [{"id": "acp:local-bot", "name": "Local Bot", "on": False, "muted": False,
                          "source": "Harness", "acp": True}],
                "bot_form": getattr(box, "_bot_draft", None), "bot_error": getattr(box, "_bot_error", ""),
                "json_text": "", "json_error": "", "openbot": False, "automation_ready": False,
                "gbot": False, "grok": "", "grok_target": "", "hermes": False, "wanted": [],
            }

        box.menu_state = menu_state
        window = self.FaceWindow("t", "Test", spot=(300, 400), faces=box)
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        window.show()
        window.open_menu("bots")
        self.app.processEvents()
        bubble = window.bubble
        edit = next(w for w in bubble._control_widgets if isinstance(w, ActionButton) and w.text() == "Edit Local Bot")
        named = {"id": native_id(bubble)}

        def under_pointer():
            return named["id"]

        with mock.patch.object(QGuiApplication, "platformName", return_value="xcb"), \
                mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.pointer_window", side_effect=under_pointer):
            self.assertTrue(window.pointer_near(bubble), "the pointer is on the bots page")
            edit.click()
            self.app.processEvents()
            self.assertTrue(bubble.full_text.startswith("Edit bot"))
            self.assertTrue(bubble.isVisible())
            named["id"] = 0  # the frame after the click: X names nothing
            bubble._tick()
            self.assertTrue(bubble.isVisible(), "that miss is not leaving")
            self.assertTrue(bubble.full_text.startswith("Edit bot"))
            named["id"] = native_id(bubble)
            bubble._tick()
            named["id"] = 0
            bubble._tick()
            self.assertFalse(bubble.isVisible(), "once the pointer was seen, leaving closes at once")
