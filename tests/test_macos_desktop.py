"""The macOS backend, against a stand-in for osascript: what is asked, how the answers read, and what the user is told."""

import json
import unittest
from types import SimpleNamespace

from botwidget.system import control, macos_desktop
from botwidget.system.macos_desktop import Macos, explain, parse_combo


class Osascript:
    def __init__(self, stdout="", stderr="", code=0):
        self.calls = []
        self.answer = SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)

    def __call__(self, argv):
        self.calls.append(argv)
        return self.answer


class Backend(unittest.TestCase):
    def test_an_action_is_a_constant_script_and_its_arguments_are_json(self):
        osa = Osascript()
        Macos(osa).type_text("it's \"quoted\" `x` $(rm -rf /)")
        argv = osa.calls[0]
        self.assertEqual(argv[:4], ["osascript", "-l", "JavaScript", "-e"])
        self.assertEqual(json.loads(argv[5]), {"text": "it's \"quoted\" `x` $(rm -rf /)"})
        self.assertNotIn("rm -rf", argv[4], "text from the model is data, never part of the code")

    def test_each_action_carries_what_it_needs(self):
        osa = Osascript()
        mac = Macos(osa)
        mac.click(10, 20, "right")
        mac.scroll(0, -3)
        mac.drag(1, 2, 3, 4)
        mac.move_window("Chrome", 5, 6, 700, 500)
        mac.key("cmd+shift+a")
        mac.window_state("Chrome", "minimize")
        sent = [json.loads(call[5]) for call in osa.calls]
        self.assertEqual(sent[0], {"x": 10, "y": 20, "button": "right"})
        self.assertEqual(sent[1], {"dx": 0, "dy": -3})
        self.assertEqual(sent[2], {"x": 1, "y": 2, "to_x": 3, "to_y": 4})
        self.assertEqual(sent[3], {"app": "Chrome", "x": 5, "y": 6, "width": 700, "height": 500, "index": 0})
        self.assertEqual(sent[4], {"key": "a", "code": None, "mods": ["command down", "shift down"]})
        self.assertEqual(sent[5], {"app": "Chrome", "state": "minimize", "index": 0})

    def test_windows_come_back_as_data(self):
        listing = [{"app": "Chrome", "frontmost": True, "windows": [{"title": "Tab", "x": 1, "y": 2, "width": 3, "height": 4}]}]
        self.assertEqual(Macos(Osascript(stdout=json.dumps(listing))).windows(), listing)

    def test_a_refusal_tells_the_user_what_to_allow(self):
        for stderr, word in (("execution error: NOT_TRUSTED", "Accessibility"),
                             ("Not authorized to send Apple events to System Events. (-1743)", "Automation"),
                             ("Can't get process \"Nope\". (-1728)", "no running app")):
            with self.subTest(stderr=stderr), self.assertRaises(control.ControlUnavailable) as caught:
                Macos(Osascript(stderr=stderr, code=1)).click(1, 1)
            self.assertIn(word, str(caught.exception))
        self.assertEqual(explain("boom\nwhat happened"), "what happened")

    def test_a_key_is_a_named_key_or_one_character_and_a_modifier_is_known(self):
        self.assertEqual(parse_combo("enter"), {"key": "enter", "code": 36, "mods": []})
        self.assertEqual(parse_combo("ctrl+a")["mods"], ["control down"])
        for bad in ("hyper+a", "ctrl+", "ctrl+ab", ""):
            with self.subTest(combo=bad), self.assertRaises(control.ControlUnavailable):
                parse_combo(bad)

    def test_this_is_the_backend_on_darwin(self):
        self.assertIsInstance(control.make_backend("darwin"), Macos)
        self.assertTrue(macos_desktop.PRELUDE.strip().startswith("ObjC.import"))


if __name__ == "__main__":
    unittest.main()
