"""What the bot may ask the widget: lazy topics, one safe command to run, settings read and changed within limits."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from botwidget import config, self_desc
from harness.acp_client import AcpClient

ROWS = (("/bots", "Your bots"), ("/demo", "Play the chat demo"))


class SelfDesc(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.path = os.path.join(folder, "widget.json")
        with open(self.path, "w") as fh:
            json.dump({"page_memory_s": 60, "save_battery": False, "remote_control": False,
                       "acp_bots": [{"id": "a", "api_key": "sk-secret"}]}, fh)
        patched = mock.patch.object(config, "CONFIG_PATH", self.path)
        patched.start()
        self.addCleanup(patched.stop)
        self.started = []
        self.moved = []

    def ask(self, method, **params):
        return self_desc.answer(method, params, ROWS, self.started.append, lambda x, y: self.moved.append((x, y)))

    def test_commands_come_as_a_list(self):
        self.assertEqual(self.ask("commands")["text"], "/bots: Your bots\n/demo: Play the chat demo")

    def test_only_a_listed_command_starts_and_keeps_its_arguments(self):
        self.assertIn("started", self.ask("run", name="/demo")["text"])
        self.assertIn("started", self.ask("run", name="/Bots now")["text"])
        self.assertEqual(self.started, ["/demo", "/Bots now"])
        self.assertIn("error", self.ask("run", name="/screenshot"))
        self.assertIn("error", self.ask("run", name="hello"))
        self.assertEqual(len(self.started), 2)

    def test_the_widget_moves_itself_to_a_place_or_an_edge(self):
        from botwidget.system import control
        with mock.patch.object(control.desktop, "screen", (1000, 800)), mock.patch.object(control.desktop, "size", (100, 100)):
            self.assertIn("moved", self.ask("move", x=15, y=25)["text"])
            self.assertIn("moved", self.ask("move", edge="right")["text"])
            self.assertIn("error", self.ask("move", edge="nowhere"))
        self.assertEqual(self.moved, [(15, 25), (900, 350)])

    def test_settings_come_by_name_and_never_with_a_key(self):
        listing = self.ask("settings")["text"]
        self.assertIn("page_memory_s", listing)
        self.assertEqual(self.ask("settings", key="page_memory_s")["text"], "60")
        self.assertNotIn("sk-secret", self.ask("settings", key="acp_bots")["text"])
        self.assertIn("default applies", self.ask("settings", key="sound")["text"])
        self.assertIn("no setting", self.ask("settings", key="font_size")["text"])

    def test_a_setting_changes_only_to_a_value_of_the_same_kind(self):
        self.assertIn("text", self.ask("set", key="page_memory_s", value="30"))
        self.assertEqual(config.widget_config()["page_memory_s"], 30)
        for key, value in (("page_memory_s", "soon"), ("remote_control", "true"), ("acp_bots", "[]"),
                           ("nonsense", "1")):
            with self.subTest(key=key):
                self.assertIn("error", self.ask("set", key=key, value=value))
        self.assertEqual(config.widget_config()["remote_control"], False)

    async def test_the_client_hands_a_question_from_the_agent_to_the_widget(self):
        client = AcpClient("x", widget=lambda method, params: {"text": f"{method}:{params['key']}"})
        self.assertEqual(await client.ext_method("settings", {"key": "k"}), {"text": "settings:k"})


class ToolTitle(unittest.TestCase):
    def test_a_call_reads_as_a_line_not_as_a_dict(self):
        from harness.agent.agent import tool_title
        self.assertEqual(tool_title("shell", {"command": "ls -la"}), "shell: ls -la")
        self.assertEqual(tool_title("change_setting", {"key": "sound", "value": "false"}),
                         "change_setting: key=sound, value=false")
        self.assertTrue(tool_title("shell", {"command": "echo " + "x" * 500 + " && rm -rf /"}).endswith("rm -rf /"))


class WriteResult(unittest.TestCase):
    def test_a_write_says_how_the_file_ends(self):
        from harness.agent.tools import wrote
        self.assertEqual(wrote("demo-note\n", "/x"), "Wrote 10 characters to /x (ends with a newline).")
        self.assertEqual(wrote("demo-note", "/x"), "Wrote 9 characters to /x (has no final newline).")
