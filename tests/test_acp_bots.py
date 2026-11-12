"""Harness bots are added from the widget. The key stays in its file, and a save does not restart the others."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

from botwidget import acp_bots, acplink, config
from botwidget.avatar import GROK_HEX, avatar_profile
from botwidget.markdown import block_text
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

    def test_without_a_checkout_the_command_is_just_the_agent(self):
        """Should not point PYTHONPATH at a folder that has no harness."""
        with mock.patch.object(acp_bots.os.path, "isdir", return_value=False):
            self.assertEqual(acp_bots.default_command(), f"{sys.executable} -m harness.agent")

    def test_a_path_with_a_space_survives_the_command_line(self):
        """Should not cut /Applications/Bot Widget.app/... at the space."""
        from harness.acp_client import split_command
        path = "/Applications/Bot Widget.app/Contents/MacOS/Bot Widget"
        with mock.patch.object(acp_bots.os.path, "isdir", return_value=False), \
                mock.patch.object(acp_bots.sys, "executable", path):
            self.assertEqual(split_command(acp_bots.default_command()), [path, "-m", "harness.agent"])

    def test_approve_keys_are_checked_before_widget_json_is_saved(self):
        row = {"name": "A", "command": "c", "approve": {"/^shell ls/": True}}
        self.assertEqual(acp_bots.parse_editor(json.dumps({"acp_bots": [row]}))[1], "")
        for bad in ({"x": "yes"}, {"/(/": True}):
            self.assertIn("approve", acp_bots.parse_editor(json.dumps({"acp_bots": [{**row, "approve": bad}]}))[1])

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
        self.assertIn("Connection: none yet", shown)
        self.assertNotIn("Model address", shown)
        self.assertIn("nuage", shown)
        self.assertIn("blue", shown)
        preview = next(block for block in bot_form({}) if block.get("control") == "preview")
        self.assertEqual(preview["value"], "nuage|blue|new")
        from botwidget.bubble import line_height
        from botwidget.avatar import AVATAR_SIZE
        self.assertEqual(line_height(preview), AVATAR_SIZE)
        refused = block_text(bot_form({"bot_error": "A bot needs a name."}))
        self.assertLess(refused.index("Connection: none yet"), refused.index("A bot needs a name."))
        self.assertLess(refused.index("A bot needs a name."), refused.index("Save bot"))

    def test_saving_an_unset_face_does_not_repaint_the_bot(self):
        stored = {"id": "local", "name": "Local Bot", "command": "run", "key_file": "k",
                  "env": {"HARNESS_MODEL": "local", "HARNESS_MODEL_BASE_URL": "http://127.0.0.1:8080/v1"}}
        form = acp_bots.fields_of({**stored, "id": "acp:local"})
        self.assertEqual(form["face"], "")
        self.assertEqual(form["color"], "")
        shown = [block.get("label", "") for block in bot_form({"bot_form": form})
                 if block.get("kind") == "control"]
        self.assertIn("Face: automatic", shown)
        self.assertIn("Colour: automatic", shown)
        saved, error = acp_bots.commit(form, [stored])
        self.assertEqual(error, "")
        self.assertNotIn("face", saved[0])
        self.assertNotIn("color", saved[0])

    def test_the_bots_page_can_add_edit_and_remove_a_harness_bot(self):
        blocks = bots({"bots": [{"id": "acp:local", "name": "Local", "on": True, "acp": True}]})
        commands = [block.get("command") for block in blocks if block.get("kind") == "control"]
        commands += [action["command"] for block in blocks for action in block.get("actions") or []]
        self.assertIn("page/bot", commands)
        self.assertIn("page/bot/acp:local", commands)
        self.assertIn("bot-remove/acp:local", commands)
        armed = bots({"bots": [{"id": "acp:a", "name": "One", "on": True, "acp": True},
                               {"id": "acp:b", "name": "Two", "on": True, "acp": True}],
                      "confirm_remove": "bot-remove/acp:a"})
        removes = [(action["label"], action["command"]) for block in armed for action in block.get("actions") or []
                   if str(action["command"]).startswith("bot-remove/")]
        self.assertEqual(removes, [("Again", "bot-remove/acp:a"), ("Remove", "bot-remove/acp:b")])
        self.assertIn("page/widget-json", commands)

    def test_two_bots_share_a_model_and_a_rename_keeps_the_id(self):
        first, error = acp_bots.commit({**acp_bots.blank(), "name": "Local"}, [])
        second, error = acp_bots.commit({**acp_bots.blank(), "name": "Other", "color": "green"}, first)
        self.assertEqual(error, "")
        self.assertIn("harness.agent", first[0]["command"])
        self.assertNotIn("11434", json.dumps(first))
        self.assertEqual([row["id"] for row in second], ["local", "other"])
        self.assertEqual({row["env"]["HARNESS_MODEL_BASE_URL"] for row in second}, {"http://127.0.0.1:8081/v1"})
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

    def test_a_bot_uses_the_connection_it_names_and_an_edit_restarts_only_that_bot(self):
        """Should copy the chosen connection onto the bot, restart only that bot when it changes, and refuse a remove while it is in use."""
        from unittest import mock
        here, error = acp_bots.commit_connection(
            {**acp_bots.blank_connection(), "name": "Here", "base_url": "http://127.0.0.1:8080/v1",
             "model": "local", "key_file": "k"}, [])
        self.assertEqual(error, "")
        there, error = acp_bots.commit_connection(
            {**acp_bots.blank_connection(), "name": "There", "base_url": "http://10.0.0.2:9/v1",
             "model": "other", "key_file": "k2"}, here)
        self.assertEqual(error, "")
        self.assertEqual(acp_bots.first_connection(there), "here")
        qwen, error = acp_bots.commit({**acp_bots.blank(), "name": "Qwen", "connection": "there"}, [], there)
        self.assertEqual(error, "")
        self.assertEqual(qwen[0]["connection"], "there")
        self.assertEqual(qwen[0]["env"]["HARNESS_MODEL_BASE_URL"], "http://10.0.0.2:9/v1")
        both, error = acp_bots.commit({**acp_bots.blank(), "name": "Other"}, qwen, there)
        self.assertEqual(error, "")
        self.assertNotIn("connection", both[1])
        shown = [block.get("label", "") for block in bot_form(
            {"connections": there, "bot_form": {**acp_bots.blank(), "connection": "there", "name": "Qwen"}})]
        self.assertIn("Connection: There", shown)
        with mock.patch.object(acplink, "widget_config", return_value={"acp_bots": both, "connections": there}):
            before = acplink.configured_bots()
        edited, error = acp_bots.commit_connection(
            {**acp_bots.fields_of_connection(there[1]), "base_url": "http://10.0.0.8:9/v1"}, there)
        self.assertEqual(error, "")
        with mock.patch.object(acplink, "widget_config", return_value={"acp_bots": both, "connections": edited}):
            after = acplink.configured_bots()
        self.assertEqual(acp_bots.plan(before, after), [("restart", "acp:qwen")])
        refused, message = acp_bots.drop_connection(there, "there", both)
        self.assertIsNone(refused)
        self.assertEqual(message, "A bot still uses this connection.")
        kept, message = acp_bots.drop_connection(there, "here", both)
        self.assertEqual(message, "")
        self.assertEqual([row["id"] for row in kept], ["there"])
        off = acp_bots.set_connection_on(there, "there", False)
        self.assertEqual(off[1]["enabled"], False)
        with mock.patch.object(acplink, "widget_config", return_value={"acp_bots": both, "connections": off}):
            stopped = acplink.configured_bots()
        self.assertEqual(acp_bots.plan(before, stopped), [("close", "acp:qwen")])
        self.assertEqual([bot["id"] for bot in stopped], ["acp:other"])
        edited_off, error = acp_bots.commit_connection(
            {**acp_bots.fields_of_connection(off[1]), "model": "renamed"}, off)
        self.assertEqual(error, "")
        self.assertEqual(edited_off[1].get("enabled"), False)

    def test_a_chosen_face_and_colour_are_what_gets_drawn(self):
        profile = avatar_profile("acp:local", None, {"shape": "nuage", "color": "blue"})
        self.assertEqual(profile["shape"], "nuage")
        self.assertEqual(profile["hex"], GROK_HEX["blue"])

    def test_a_form_that_cannot_be_saved_says_why(self):
        """Should name the missing piece, and keep a pasted key out of the file."""
        blank = acp_bots.blank()
        self.assertIn("name", acp_bots.commit({**blank, "name": ""}, [])[1])
        self.assertIn("name", acp_bots.commit({**blank, "name": "a\nb"}, [])[1])
        self.assertIn("http", acp_bots.commit({**blank, "name": "Ada", "base_url": "ftp://x"}, [])[1])
        self.assertIn("model", acp_bots.commit(
            {**blank, "name": "Ada", "base_url": "http://x", "model": ""}, [])[1])
        self.assertIn("key", acp_bots.commit(
            {**blank, "name": "Ada", "base_url": "http://x", "model": "m", "key_file": ""}, [])[1])
        self.assertIn("face", acp_bots.commit({**blank, "name": "Ada", "face": "nope"}, [])[1])
        self.assertIn("colour", acp_bots.commit({**blank, "name": "Ada", "color": "nope"}, [])[1])
        self.assertIn("id", acp_bots._entry({**blank, "name": "Ada", "stored_id": "ada"}, None, {"ada"})[1])
        self.assertIn("connection", acp_bots.commit({**blank, "name": "Ada", "connection": "gone"}, [], [])[1])
        saved, error = acp_bots.commit({**blank, "name": "Ada", "stored_id": "acp:ada"}, [])
        self.assertEqual(error, "")
        self.assertEqual(saved[0]["id"], "ada")
        again, error = acp_bots.commit({**blank, "name": "Ada"}, saved)
        self.assertEqual(error, "")
        self.assertEqual(again[1]["id"], "ada-2")
        legacy, error = acp_bots.commit({**blank, "name": "Ada 2", "stored_id": "ada"},
                                        [{"name": "Ada", "command": "run"}])
        self.assertEqual(error, "")
        self.assertEqual(legacy[0]["id"], "ada")
        self.assertEqual(acp_bots.cycle("face", "nope"), acp_bots.FACES[0])
        self.assertEqual(acp_bots.cycle_connection("nope", []), "")
        self.assertEqual(acp_bots.public_connections(["x", {"id": "", "name": "A"}, {"name": "A"}]), [])
        base = acp_bots.blank_connection()
        self.assertIn("name", acp_bots.commit_connection({**base, "name": "\n"}, [])[1])
        self.assertIn("http", acp_bots.commit_connection({**base, "name": "A", "base_url": "nope"}, [])[1])
        self.assertIn("model", acp_bots.commit_connection(
            {**base, "name": "A", "base_url": "http://x", "model": ""}, [])[1])
        self.assertIn("key", acp_bots.commit_connection(
            {**base, "name": "A", "base_url": "http://x", "model": "m", "key_file": ""}, [])[1])
        made, error = acp_bots.commit_connection({**base, "name": "A"}, [])
        self.assertEqual(error, "")
        self.assertEqual(acp_bots.cycle_connection("nope", made), made[0]["id"])
        self.assertEqual(acp_bots.cycle_connection(made[0]["id"], made), "")
        self.assertEqual(acp_bots.parse_editor('{"acp_bots": [{"name": "A", "command": "c"}]}')[1], "")
        self.assertEqual(acp_bots.parse_editor('{"connections": [{"id": "a", "name": "A"}]}')[1], "")
        self.assertIsNone(acp_bots.set_connection_on(made, "missing", True))
        off = acp_bots.set_connection_on(made, made[0]["id"], False)
        back, error = acp_bots.commit_connection({**base, "name": "B"}, off)
        self.assertEqual(error, "")
        self.assertEqual(back[0].get("enabled"), False)
        on = acp_bots.set_connection_on(off, made[0]["id"], True)
        self.assertNotIn("enabled", on[0])
        self.assertEqual(acp_bots.plan([], [{"id": "a"}]), [("open", "a")])
        self.assertEqual(acp_bots.without(None, "acp:a"), [])
        self.assertFalse(acp_bots.connection_in_use("nope", "a"))
        self.assertIn("JSON", acp_bots.parse_editor("{")[1])
        self.assertIn("object", acp_bots.parse_editor("[]")[1])
        self.assertIn("api_key", acp_bots.parse_editor('{"api_key": "x"}')[1])
        self.assertIn("list", acp_bots.parse_editor('{"acp_bots": {}}')[1])
        self.assertIn("object", acp_bots.parse_editor('{"acp_bots": [1]}')[1])
        self.assertIn("name", acp_bots.parse_editor('{"acp_bots": [{}]}')[1])
        self.assertIn("env", acp_bots.parse_editor(
            '{"acp_bots": [{"name": "A", "command": "c", "env": []}]}')[1])
        self.assertIn("face", acp_bots.parse_editor(
            '{"acp_bots": [{"name": "A", "command": "c", "face": "nope"}]}')[1])
        self.assertIn("colour", acp_bots.parse_editor(
            '{"acp_bots": [{"name": "A", "command": "c", "color": "nope"}]}')[1])
        self.assertIn("list", acp_bots.parse_editor('{"connections": {}}')[1])
        self.assertIn("object", acp_bots.parse_editor('{"connections": [1]}')[1])
        self.assertIn("name", acp_bots.parse_editor('{"connections": [{}]}')[1])
        self.assertIn("id", acp_bots.parse_editor(
            '{"connections": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]}')[1])
        self.assertIn("token", acp_bots.parse_editor('{"bots": [{"token": "x"}]}')[1])
        self.assertNotIn("x", acp_bots.public_text({"items": [{"token": "x"}], "name": "A"}))

    def test_workspace_is_saved_as_env_and_clears_when_empty(self):
        blank = acp_bots.blank()
        saved, error = acp_bots.commit({
            **blank, "name": "Ada", "stored_id": "acp:ada",
            "workspace": "/tmp/ws-example", "workspace_permissions": "allowlist",
        }, [])
        self.assertEqual(error, "")
        env = saved[0].get("env") or {}
        self.assertEqual(env.get("HARNESS_WORKSPACE"), "/tmp/ws-example")
        self.assertEqual(env.get("HARNESS_WORKSPACE_PERMISSIONS"), "allow")
        cleared, error = acp_bots.commit({
            **blank, "name": "Ada", "stored_id": "acp:ada", "workspace": "",
        }, saved)
        self.assertEqual(error, "")
        env = cleared[0].get("env") or {}
        self.assertNotIn("HARNESS_WORKSPACE", env)
        self.assertEqual(acp_bots.cycle("workspace_permission", "ask"), "allow")
        self.assertEqual(acp_bots.cycle("workspace_permission", "allow-for-session"), "ask")
        self.assertEqual(acp_bots.normalise_workspace_permission("allowlist"), "allow")


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
        self.box._naps = {}
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
        self.assertIsNone(self.save("Harness Check"), "the bubble is closed, not shown again")
        self.assertIsNone(self.save("Second Check", color="green"))
        saved = json.load(open(config.CONFIG_PATH))
        self.assertNotIn(SENTINEL, json.dumps(saved), "the key file's contents stay out of widget.json")
        bots_saved = saved["acp_bots"]
        self.assertEqual([row["env"]["HARNESS_MODEL"] for row in bots_saved], ["local", "local"])
        self.assertEqual([row["env"]["HARNESS_MODEL_BASE_URL"] for row in bots_saved],
                         ["http://127.0.0.1:8081/v1", "http://127.0.0.1:8081/v1"])
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
        face.bubble = mock.Mock()
        face.setWindowTitle = lambda name: setattr(face, "title", name)
        face.set_avatar = lambda avatar: setattr(face, "avatar", avatar)
        self.box.faces["acp:harness-check"] = face
        self.calls.clear()
        self.box.menu_command("page/bot/acp:harness-check", "bots")
        self.box.menu_command("cycle/color", "bot/acp:harness-check")
        self.assertIsNone(self.box.menu_command("action/save-bot", "bot/acp:harness-check", {}))
        face.bubble.close_bubble.assert_called_with("saved")
        self.assertEqual(self.calls, [], "a new colour does not restart the agent")
        self.assertEqual(face.avatar["color"], "green")
        self.assertTrue(os.path.isdir(room), "recolouring leaves the session folder")

        self.box.menu_command("page/bot/acp:harness-check", "bots")
        self.assertIsNone(self.box.menu_command("action/save-bot", "bot/acp:harness-check",
                                                {"field/name": "Renamed Check"}))
        self.assertEqual([call[:2] for call in self.calls], [("toggle", "acp:harness-check"),
                                                             ("toggle", "acp:harness-check")])
        self.assertNotIn("acp:second-check", [call[1] for call in self.calls])
        self.assertEqual(json.load(open(config.CONFIG_PATH))["acp_bots"][0]["id"], "harness-check")

        self.assertEqual(self.box.menu_command("bot-remove/acp:harness-check", "bots"), "bots")
        still = json.load(open(config.CONFIG_PATH))["acp_bots"]
        self.assertEqual([row["id"] for row in still], ["harness-check", "second-check"])
        self.box.menu_command("bot-remove/acp:harness-check", "bots")
        left = json.load(open(config.CONFIG_PATH))["acp_bots"]
        self.assertEqual([row["id"] for row in left], ["second-check"])
        self.assertTrue(os.path.isdir(room), "removing the bot from the widget leaves its session folder")


class MemoryPage(WidgetSave):
    """The /memory page: every row can be edited or forgotten, and a save changes that memory in place."""

    def setUp(self):
        super().setUp()
        from harness.agent import memory
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        patched = mock.patch.dict(os.environ, {"HARNESS_MEMORY_DIR": folder})
        patched.start()
        self.addCleanup(patched.stop)
        self.memory = memory

    def test_each_row_has_edit_and_forget_and_they_work(self):
        first = self.memory.write_memory("Eerste", "user")
        second = self.memory.write_memory("Tweede", "user")
        from botwidget import menu_pages
        text = json.dumps(menu_pages.memory_page({}), default=str)
        for ident in (first, second):
            self.assertIn(f"cmd:page/memory/edit/{ident}", text)
            self.assertIn(f"cmd:memory-forget/{ident}", text)
        self.assertEqual(self.box.menu_command(f"page/memory/edit/{first}", "memory"), f"memory/edit/{first}")
        self.assertEqual(self.box._memory_text, "Eerste")
        fields = {"field/memory_text": "Eerste, aangepast", "field/memory_topic": "t"}
        self.assertEqual(self.box.menu_command("action/memory-save", "memory/edit/" + first, fields), "memory")
        texts = {m["id"]: (m["text"], m["topic"]) for m in self.memory.list_memories()}
        self.assertEqual(texts, {first: ("Eerste, aangepast", "t"), second: ("Tweede", "")})
        self.assertEqual(self.box.menu_command(f"memory-forget/{second}", "memory"), "memory")
        self.assertEqual([m["id"] for m in self.memory.list_memories()], [first])

    def test_a_new_memory_takes_the_typed_fields(self):
        fields = {"field/memory_text": "Nieuw", "field/memory_scope": "user", "field/memory_topic": ""}
        self.box.menu_command("page/memory/new", "memory")
        self.assertEqual(self.box.menu_command("action/memory-save", "memory/new", fields), "memory")
        self.assertEqual([m["text"] for m in self.memory.list_memories()], ["Nieuw"])

    def test_new_memory_starts_empty_after_an_edit(self):
        ident = self.memory.write_memory("Eerste", "user")
        self.box.menu_command(f"page/memory/edit/{ident}", "memory")
        self.box.menu_command("page/memory/new", "memory")
        self.assertEqual((self.box._memory_id, self.box._memory_text), ("", ""))


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
        """Should mute and open Edit when the click lands on the row that sits over the text."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from botwidget.qt_ui.controls import ItemRow

        box = self.Faces.__new__(self.Faces)

        box._naps = {}
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
        row = next(w for w in bubble._control_widgets if isinstance(w, ItemRow))
        self.assertGreater(bubble._text.children().index(row), bubble._text.children().index(bubble._doc))
        mute = next(rect for _label, command, rect in row._hits if command == "mute/acp:local-bot")
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(mute.center().x()), int(mute.center().y())))
        self.app.processEvents()
        self.assertEqual(config.muted_bots(), ["acp:local-bot"])
        self.assertEqual(window._menu_page, "bots")
        row = next(w for w in bubble._control_widgets if isinstance(w, ItemRow))
        edit = next(rect for _label, command, rect in row._hits if command == "page/bot/acp:local-bot")
        QTest.mouseClick(row, Qt.LeftButton, Qt.NoModifier,
                         QPoint(int(edit.center().x()), int(edit.center().y())))
        self.app.processEvents()
        self.assertIn("Edit bot", bubble.full_text)
        self.assertIn("Name: Local Bot", bubble.full_text)
        self.assertEqual(window._menu_page, "bot/acp:local-bot")

    def test_clicking_the_name_and_save_stores_the_bot(self):
        """Should keep a name typed into the field when the click lands on the text, then save it."""
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from botwidget.qt_ui.controls import ActionButton, TextField

        box = self.Faces.__new__(self.Faces)

        box._naps = {}
        box.faces = {}
        box._arc_guests = {}
        box._arc_order = []
        box._semicircle = {}
        box.toggle = lambda *_args: None
        box.close_bubbles_except = lambda *_args: None
        box.hold_arc = lambda: None
        box._stop_guest = lambda *_args: None

        def menu_state():
            return {
                "version": "0", "channel": "local", "switch_label": None, "hotkey": "",
                "update": "", "staged_update": "", "sound": False, "quiet_hours": False,
                "always_on_top": False, "can_pick_desktops": False, "can_glass": False, "glass_clear": 0,
                "all_desktops": False, "login": False, "check_updates": False, "save_battery": False,
                "can_install_updates": False, "auto_update": False, "bots": [],
                "bot_form": getattr(box, "_bot_draft", None), "bot_error": getattr(box, "_bot_error", ""),
                "json_text": "", "json_error": "", "openbot": False, "automation_ready": False,
                "gbot": False, "grok": "", "grok_target": "", "hermes": False, "wanted": [],
            }

        box.menu_state = menu_state
        window = self.FaceWindow("t", "Test", spot=(300, 400), faces=box)
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        box.faces = {"t": window}
        window.open_menu("bot")
        self.app.processEvents()
        bubble = window.bubble
        name = next(w for w in bubble._control_widgets if isinstance(w, TextField))
        point = QPoint(name.geometry().center().x() - bubble._doc.x(),
                       name.geometry().center().y() - bubble._doc.y())
        QTest.mouseClick(bubble._doc.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.assertIs(bubble.focusWidget(), name.edit)
        QTest.keyClicks(name.edit, "Lokal")
        save = next(w for w in bubble._control_widgets if isinstance(w, ActionButton) and w.text() == "Save bot")
        point = QPoint(save.geometry().center().x() - bubble._doc.x(),
                       save.geometry().center().y() - bubble._doc.y())
        QTest.mouseClick(bubble._doc.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.app.processEvents()
        self.assertIsNone(window._menu_page)
        self.assertFalse(bubble.kind, "saving closes the bubble at once")
        with open(config.CONFIG_PATH) as fh:
            names = [row["name"] for row in json.load(fh)["acp_bots"]]
        self.assertIn("Lokal", names)

    def test_a_missed_pointer_sample_after_edit_does_not_close_the_page(self):
        """Should keep Edit bot open when X names no window on the frame after the click.

        The pointer was on the bots page, so the page change counts as touched. XWayland
        often answers 0 for that next frame. That one miss is not leaving. Once a later
        frame sees the pointer, leaving still closes at once.
        """
        from unittest import mock
        from PySide6.QtGui import QGuiApplication
        from botwidget.qt_ui.controls import ItemRow
        from botwidget.qt_ui.native import native_id

        box = self.Faces.__new__(self.Faces)

        box._naps = {}
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
        row = next(w for w in bubble._control_widgets if isinstance(w, ItemRow))
        edit = next(rect for _label, command, rect in row._hits if command == "page/bot/acp:local-bot")
        named = {"id": native_id(bubble)}

        def under_pointer():
            return named["id"]

        with mock.patch.object(QGuiApplication, "platformName", return_value="xcb"), \
                mock.patch("botwidget.qt_ui.face.global_pointer", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.pointer_window", side_effect=under_pointer):
            bubble._physics.stop()
            self.assertTrue(window.pointer_near(bubble), "the pointer is on the bots page")
            row.press_at(edit.center().x())
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


class ItemRowPills(unittest.TestCase):
    """Should light the Edit and Mute pills when the pointer is on them."""

    def test_the_pill_under_the_pointer_turns_blue(self):
        """Should paint the action under the pointer in the same blue as the other buttons."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        from botwidget.qt_ui.controls import ItemRow

        app = QApplication.instance() or QApplication([])
        row = ItemRow("Local Bot", False, "bot/a", [
            {"label": "Mute", "command": "mute/a"},
            {"label": "Edit", "command": "page/bot/a"},
            {"label": "Again", "command": "bot-remove/a"},
        ])
        row.resize(420, 36)
        row.show()
        app.processEvents()
        self.assertTrue(row.hasMouseTracking())
        edit = next(rect for _label, command, rect in row._hits if command == "page/bot/a")
        again = next(rect for _label, command, rect in row._hits if command == "bot-remove/a")

        def fill(rect):
            from PySide6.QtGui import QImage
            image = QImage(row.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(0)
            row.render(image)
            return image.pixelColor(int(rect.left()) + 8, int(rect.center().y()))

        def move(rect):
            point = QPointF(rect.center())
            app.sendEvent(row, QMouseEvent(
                QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))

        idle = fill(edit)
        self.assertLess(abs(idle.red() - idle.blue()), 8)
        move(edit)
        hot = fill(edit)
        self.assertGreater(hot.blue(), hot.red() + 15)
        self.assertEqual(row._hover, "page/bot/a")
        move(again)
        self.assertEqual(fill(edit).rgba(), idle.rgba())
        armed = fill(again)
        self.assertGreater(armed.alpha(), 200)
        self.assertGreater(armed.blue(), armed.red() + 80)
        app.sendEvent(row, QEvent(QEvent.Type.Leave))
        self.assertIsNone(row._hover)
        self.assertEqual(fill(edit).rgba(), idle.rgba())
