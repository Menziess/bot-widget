"""Desktop accessibility is reported without a real bus."""

import unittest
from unittest import mock

from botwidget.system import a11y


class _Child:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class _Desktop:
    def __init__(self, names):
        self._names = names

    def get_child_count(self):
        return len(self._names)

    def get_child_at_index(self, index):
        return _Child(self._names[index])


class _Bus:
    def __init__(self, names=("botwidget", "gnome-shell")):
        self.names = names

    def get_desktop(self, index):
        return _Desktop(self.names)


class AccessibilityProbe(unittest.TestCase):
    def setUp(self):
        a11y.clear()

    def test_a_working_bus_is_available(self):
        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertTrue(row["available"])
        self.assertEqual(row["reason"], "AT-SPI")
        self.assertEqual(row["platform"], "linux")

    def test_a_missing_typelib_is_unavailable_and_names_the_desktop_packages(self):
        def load():
            raise ImportError("Atspi typelib")

        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=load)
        self.assertFalse(row["available"])
        self.assertIn("gir1.2-atspi-2.0", row["reason"])
        self.assertIn("python3-gi", row["reason"])
        self.assertNotIn("sudo", row["reason"])
        self.assertNotIn("pyatspi", row["reason"])

    def test_an_empty_desktop_is_unavailable(self):
        with mock.patch.object(a11y, "_platform_name", return_value="linux"):
            row = a11y.accessibility(load=lambda: type("B", (), {"get_desktop": lambda self, i: None})())
        self.assertFalse(row["available"])
        self.assertIn("no desktop", row["reason"])

    def test_the_status_is_logged_once(self):
        lines = []
        with mock.patch.object(a11y, "_probe", return_value={"available": True, "reason": "AT-SPI", "platform": "linux"}):
            a11y.log_once(lines.append)
            a11y.log_once(lines.append)
        self.assertEqual(lines, ["accessibility: yes (AT-SPI)"])

    def test_application_names_come_from_the_bus(self):
        names = a11y.application_names(load=lambda: _Bus(("botwidget", "Chrome")))
        self.assertEqual(names, ["botwidget", "Chrome"])

    def test_install_does_nothing_until_the_user_agrees(self):
        calls = []
        self.assertIn("agreement", a11y.install_after_agree(False, run=calls.append))
        self.assertEqual(calls, [])
        a11y.install_after_agree(True, run=lambda command, check=False: calls.append(command))
        self.assertEqual(calls, [["pkexec", "apt-get", "install", "-y", "gir1.2-atspi-2.0", "python3-gi"]])

    def test_windows_and_macos_are_named_and_not_available(self):
        with mock.patch.object(a11y, "_platform_name", return_value="windows"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertFalse(row["available"])
        self.assertIn("UI Automation", row["reason"])
        with mock.patch.object(a11y, "_platform_name", return_value="macos"):
            row = a11y.accessibility(load=lambda: _Bus())
        self.assertFalse(row["available"])
        self.assertIn("AX", row["reason"])
