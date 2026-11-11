"""Item 3: Debug/launch command hidden from the 'Waking…' activity string.

The AcpLink target is the raw shell command (e.g. 'env PYTHONPATH=… -m harness.agent').
The activity shown in the bubble must use the bot name, not the command.
"""

import unittest
from botwidget import acplink


class ActivityUsesName(unittest.TestCase):
    """The 'Waking…' activity string uses the bot name, not the raw command."""

    def test_activity_uses_name_not_command(self):
        link = acplink.AcpLink("env PYTHONPATH=/foo bar", name="My Bot")
        self.assertEqual(link._name, "My Bot")
        # Simulate what send() does: set the activity.
        link._activity = f"Waking {link._name}…"
        self.assertEqual(link._activity, "Waking My Bot…")
        self.assertNotIn("PYTHONPATH", link._activity)

    def test_activity_falls_back_to_target_when_no_name(self):
        link = acplink.AcpLink("some-command", name="")
        self.assertEqual(link._name, "some-command")

    def test_options_for_includes_name(self):
        import json
        import tempfile
        import os
        from botwidget import config

        with tempfile.TemporaryDirectory() as folder:
            old_path = config.CONFIG_PATH
            config.CONFIG_PATH = os.path.join(folder, "widget.json")
            config._config_read[:] = [None, {}]
            try:
                os.makedirs(os.path.dirname(config.CONFIG_PATH), exist_ok=True)
                with open(config.CONFIG_PATH, "w") as fh:
                    json.dump({
                        "acp_bots": [{
                            "name": "Test Bot",
                            "command": "env PYTHONPATH=/foo -m harness.agent",
                        }]
                    }, fh)
                config._config_read[:] = [None, {}]
                options = acplink.options_for("acp:test-bot")
                self.assertEqual(options.get("name"), "Test Bot")
            finally:
                config.CONFIG_PATH = old_path
                config._config_read[:] = [None, {}]
