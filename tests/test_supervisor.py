"""Checkout fast-forward, the remembered variant, takeover, and the dev crash retry."""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from botwidget import config, dev, pc_update, startup, supervisor


class FastForward(unittest.TestCase):
    """Should fast-forward only a clean checkout."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        subprocess.check_call(["git", "init"], cwd=self.dir, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@example.com"], cwd=self.dir)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=self.dir)
        open(os.path.join(self.dir, "a.txt"), "w").close()
        subprocess.check_call(["git", "add", "a.txt"], cwd=self.dir)
        subprocess.check_call(["git", "commit", "-m", "a"], cwd=self.dir, stdout=subprocess.DEVNULL)
        bare = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, bare, True)
        subprocess.check_call(["git", "init", "--bare", bare], stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "remote", "add", "origin", bare], cwd=self.dir)
        subprocess.check_call(["git", "push", "-u", "origin", "HEAD:main"], cwd=self.dir, stdout=subprocess.DEVNULL)

    def test_a_dirty_tree_is_not_fast_forwarded(self):
        open(os.path.join(self.dir, "a.txt"), "w").write("dirty")
        before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.dir, text=True)
        self.assertEqual(pc_update.fast_forward(self.dir), "dirty")
        after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.dir, text=True)
        self.assertEqual(before, after)

    def test_a_clean_tree_fast_forwards(self):
        self.assertEqual(pc_update.fast_forward(self.dir), "updated")


class RestartPlan(unittest.TestCase):
    """Should restart only an existing idle dev pid."""

    def test_absent_busy_and_idle(self):
        self.assertEqual(pc_update.plan_restart("", False), "absent")
        self.assertEqual(pc_update.plan_restart("123", True), "busy")
        self.assertEqual(pc_update.plan_restart("123", False), "restart")


class Variant(unittest.TestCase):
    """Should keep the old launch command until a variant is remembered."""

    def test_no_variant_matches_launch_command_and_a_variant_uses_the_supervisor(self):
        self.assertIsNone(supervisor.remembered_variant())
        self.assertEqual(supervisor.login_command(), startup.launch_command())
        self.assertEqual(supervisor.selected_argv(), startup.launch_command())
        config.save_widget_config(variant="dev", local_command=["/usr/bin/true", "--dev"])
        self.assertEqual(supervisor.remembered_variant(), "dev")
        self.assertEqual(supervisor.selected_argv(), ["/usr/bin/true", "--dev"])
        self.assertEqual(supervisor.login_command()[-2:], ["botwidget.supervisor", "run"])
        config.save_widget_config(variant="installed", local_command=["/usr/bin/true", "--dev"])
        with mock.patch("botwidget.system.current.stable_app_command", return_value=["/opt/botwidget"]):
            self.assertEqual(supervisor.selected_argv(), ["/opt/botwidget"])


class LockAndTakeover(unittest.TestCase):
    """Should refuse a second supervisor and restore the variant after takeover."""

    def test_the_lock_refuses_a_second_holder(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        path = os.path.join(folder, "lock")
        first = supervisor.try_lock(path)
        self.assertIsNotNone(first)
        self.assertIsNone(supervisor.try_lock(path))
        first.close()

    def test_takeover_stops_runs_and_restores_on_exit_crash_and_timeout(self):
        events = []

        class Proc:
            def __init__(self, status):
                self.status = status

        def stop():
            events.append("stop")

        def spawn(cmd):
            events.append(("spawn", cmd))
            return Proc(spawn.status)

        def wait(proc, timeout):
            events.append(("wait", timeout))
            return proc.status

        def restore():
            events.append("restore")

        for status in ("exit", "crash", "timeout"):
            events.clear()
            spawn.status = status
            self.assertEqual(supervisor.takeover(["/bin/custom"], 5, stop=stop, spawn=spawn, wait=wait, restore=restore), status)
            self.assertEqual(events[0], "stop")
            self.assertEqual(events[1], ("spawn", ["/bin/custom"]))
            self.assertEqual(events[-1], "restore")


class CrashRetry(unittest.TestCase):
    """Should retry a crash instead of waiting forever, and fast-forward before the retry."""

    def test_a_syntax_error_retries_and_a_handover_stops(self):
        self.assertEqual(dev.on_child_exit(1), "retry")
        self.assertEqual(dev.on_child_exit(dev.HANDOVER_EXIT), "stop")
        self.assertLess(supervisor.retry_delay(0), supervisor.retry_delay(3))
        self.assertEqual(supervisor.retry_delay(20), 60.0)

    def test_prepare_retry_fast_forwards_a_clean_checkout(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        subprocess.check_call(["git", "init"], cwd=folder, stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "config", "user.email", "t@example.com"], cwd=folder)
        subprocess.check_call(["git", "config", "user.name", "t"], cwd=folder)
        open(os.path.join(folder, "a.txt"), "w").close()
        subprocess.check_call(["git", "add", "a.txt"], cwd=folder)
        subprocess.check_call(["git", "commit", "-m", "a"], cwd=folder, stdout=subprocess.DEVNULL)
        bare = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, bare, True)
        subprocess.check_call(["git", "init", "--bare", bare], stdout=subprocess.DEVNULL)
        subprocess.check_call(["git", "remote", "add", "origin", bare], cwd=folder)
        subprocess.check_call(["git", "push", "-u", "origin", "HEAD:main"], cwd=folder, stdout=subprocess.DEVNULL)
        pulled, delay = dev.prepare_retry(folder, 0)
        self.assertEqual(pulled, "updated")
        self.assertEqual(delay, 1.0)
        open(os.path.join(folder, "a.txt"), "w").write("x")
        self.assertEqual(dev.prepare_retry(folder, 1)[0], "dirty")


class LaunchScript(unittest.TestCase):
    """Should point the desktop entry at the launcher."""

    def test_install_script_and_launcher_read_the_variant(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        install = open(os.path.join(root, "packaging", "install.sh")).read()
        launch = open(os.path.join(root, "packaging", "botwidget-launch")).read()
        self.assertIn("botwidget-launch", install)
        self.assertIn("botwidget.supervisor launch", launch)
        unit = open(os.path.join(root, "packaging", "systemd", "botwidget-update.service")).read()
        timer = open(os.path.join(root, "packaging", "systemd", "botwidget-update.timer")).read()
        self.assertIn("botwidget-pc-update", unit)
        self.assertIn("OnUnitActiveSec", timer)
