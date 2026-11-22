"""The one-widget check groups a --dev reloader with its child. It kills nothing."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from botwidget.instance import ensure_single_instance, instances_main, is_widget_cmd, parse_ps, widget_groups

DEV = "python -m botwidget --dev"
CHILD = "python -m botwidget"


class Groups(unittest.TestCase):
    """Should count a dev supervisor and its child as one widget."""

    def test_dev_and_child_are_one_group(self):
        procs = [(10, 1, DEV), (11, 10, CHILD), (30, 1, "python -m pytest")]
        self.assertEqual(widget_groups(procs), [[10, 11]])

    def test_a_grandchild_stays_in_the_dev_group(self):
        procs = [(10, 1, DEV), (11, 10, CHILD), (12, 11, CHILD)]
        self.assertEqual(widget_groups(procs), [[10, 11, 12]])

    def test_two_independent_widgets(self):
        procs = [(10, 1, DEV), (11, 10, CHILD), (20, 1, CHILD)]
        self.assertEqual(widget_groups(procs), [[10, 11], [20]])

    def test_two_dev_supervisors(self):
        procs = [(10, 1, DEV), (11, 10, CHILD), (20, 1, DEV), (21, 20, CHILD)]
        self.assertEqual(widget_groups(procs), [[10, 11], [20, 21]])

    def test_a_prompt_that_mentions_the_widget_is_not_one(self):
        grok = ("/usr/bin/python /opt/grok agent The live botwidget --dev widget "
                "and python -m botwidget --instances")
        procs = [(99, 1, grok), (10, 1, DEV), (11, 10, CHILD)]
        self.assertEqual(widget_groups(procs), [[10, 11]])

    def test_the_check_process_is_not_a_widget(self):
        procs = [(4, 1, "python -m botwidget --instances"), (10, 1, CHILD)]
        self.assertEqual(widget_groups(procs, own_pid=4), [[10]])
        self.assertEqual(widget_groups([(4, 1, CHILD)], own_pid=4), [])

    def test_macos_windows_and_exe_commands_are_widgets(self):
        mac = "/Applications/Bot Widget.app/Contents/MacOS/Bot Widget --dev"
        windows = r"C:\Users\s\venv\Scripts\python.exe -m botwidget"
        pythonw = r"C:\Users\s\venv\Scripts\pythonw.exe -m botwidget"
        exe = r"C:\Program Files\Bot Widget\Bot Widget.exe"
        self.assertTrue(is_widget_cmd(mac))
        self.assertTrue(is_widget_cmd(windows))
        self.assertTrue(is_widget_cmd(pythonw))
        self.assertTrue(is_widget_cmd(exe))
        self.assertFalse(is_widget_cmd("python -m botwidget --instances"))

    def test_a_reused_pid_whose_prompt_mentions_the_widget_is_left_alone(self):
        folder = tempfile.mkdtemp()
        pid = os.path.join(folder, "pid")
        with open(pid, "w") as fh:
            fh.write("424242")
        prompt = b"/usr/bin/python /opt/grok agent The live botwidget --dev widget"
        with mock.patch("botwidget.instance.process_cmdline", return_value=prompt), \
                mock.patch("botwidget.instance.os.kill") as kill:
            ensure_single_instance(pid)
        kill.assert_not_called()

    def test_ps_rows(self):
        text = "  10   1 python -m botwidget --dev\n  11  10 python -m botwidget\n"
        self.assertEqual(parse_ps(text), [(10, 1, DEV), (11, 10, CHILD)])


class Status(unittest.TestCase):
    """Should exit 0 for one widget and non-zero for two, without killing anyone."""

    def _run(self, procs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = instances_main(procs, own_pid=None)
        return code, out.getvalue(), err.getvalue()

    def test_one_dev_group_exits_0(self):
        code, out, err = self._run([(10, 1, DEV), (11, 10, CHILD)])
        self.assertEqual(code, 0)
        self.assertIn("1 widget running", out)
        self.assertIn("child 11", out)
        self.assertEqual(err, "")

    def test_none_exits_0(self):
        code, out, _err = self._run([(1, 0, "init")])
        self.assertEqual(code, 0)
        self.assertIn("0 widgets running", out)

    def test_two_widgets_exit_nonzero(self):
        code, out, _err = self._run([(10, 1, DEV), (11, 10, CHILD), (20, 1, CHILD)])
        self.assertNotEqual(code, 0)
        self.assertIn("2 widgets running", out)
        self.assertIn("20 python -m botwidget", out)

    def test_a_failed_listing_exits_nonzero_and_kills_nothing(self):
        with mock.patch("botwidget.instance.read_process_table", return_value=None), \
                mock.patch("botwidget.instance.os.kill") as kill:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = instances_main(None)
            self.assertEqual(code, 2)
            self.assertIn("cannot list processes", err.getvalue())
            kill.assert_not_called()
