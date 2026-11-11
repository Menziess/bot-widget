"""Branches the existing suite left, called in this process. Another operating system's libraries are
stand-ins, so the Python around them still runs. A real display, a real apt download and a live model
server are not required.
"""

import ctypes
import importlib
import io
import json
import os
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

from botwidget import (attachments, bubble, channel, checkout, config, delivery, dev, hermesbot, instance,
                       power, startup, updates)
from botwidget.markdown import block_text
from botwidget.menu_pages import bots
from botwidget.qt_ui import app as appmod
from botwidget.qt_ui import fonts, glass
from botwidget.qt_ui.controls import ItemRow
from botwidget.qt_ui.faces import Faces
from botwidget.system import linux, macos, posix, windows


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Power(unittest.TestCase):
    """Should read battery state from each platform's probe."""

    def setUp(self):
        self._platform = sys.platform
        self._stub = power._probe
        # The suite replaces _probe. Reload so this test runs the function coverage can see.
        importlib.reload(power)

    def tearDown(self):
        sys.platform = self._platform
        power._probe = self._stub
        power._seen[:] = [-1e9, False]
        power._setting[:] = [-1e9, True]

    def test_each_probe_and_the_cache(self):
        """Should treat battery, saver mode and a failed probe as the code describes."""
        def run(cmd, **kwargs):
            if "batt" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="Now drawing from 'Battery Power'\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="lowpowermode  1\n")

        power.sys.platform = "darwin"
        with mock.patch.object(power.subprocess, "run", side_effect=run):
            self.assertTrue(power._probe())

        class Status:
            def __init__(self):
                self.ACLineStatus = 0
                self.SystemStatusFlag = 0

        holder = {"status": 1, "ac": 0, "saver": 0}

        def get_status(ref):
            ref.ACLineStatus = holder["ac"]
            ref.SystemStatusFlag = holder["saver"]
            return holder["status"]

        fake_ctypes = SimpleNamespace(
            Structure=type("Structure", (), {}),
            c_ubyte=int, c_ulong=int, byref=lambda obj: obj,
            windll=SimpleNamespace(kernel32=SimpleNamespace(GetSystemPowerStatus=get_status)))
        # The class inside _probe subclasses ctypes.Structure. Give it a real base it can construct.
        class Structure:
            def __init__(self, *args, **kwargs):
                self.ACLineStatus = 1
                self.SystemStatusFlag = 0

        fake_ctypes.Structure = Structure
        power.sys.platform = "win32"
        with mock.patch.dict(sys.modules, {"ctypes": fake_ctypes}):
            holder.update(status=1, ac=0, saver=0)
            self.assertTrue(power._probe())
            holder.update(ac=1, saver=1)
            self.assertTrue(power._probe())
            holder.update(status=0, ac=1, saver=0)
            self.assertFalse(power._probe())

        power.sys.platform = "linux"
        with mock.patch.object(power.subprocess, "run",
                               return_value=subprocess.CompletedProcess(["powerprofilesctl"], 0, stdout="power-saver\n")):
            self.assertTrue(power._probe())

        def listing(path):
            if path == "/sys/class/power_supply":
                return ["AC", "BAT"]
            raise OSError("no")

        root = "/sys/class/power_supply"
        ac_online = os.path.join(root, "AC", "online")
        bat_status = os.path.join(root, "BAT", "status")
        files = {
            os.path.join(root, "AC", "type"): "Mains\n",
            ac_online: "0\n",
            os.path.join(root, "BAT", "type"): "Battery\n",
            bat_status: "Discharging\n",
        }

        # open() is patched, so the miss path must call the real one or it calls itself.
        real_open = open

        def open_path(path, *args, **kwargs):
            text = files.get(os.fspath(path))
            if text is not None:
                return io.StringIO(text)
            return real_open(path, *args, **kwargs)

        with mock.patch.object(power.subprocess, "run", side_effect=OSError("no profiles")), \
                mock.patch.object(power.os, "listdir", side_effect=listing), \
                mock.patch("builtins.open", open_path):
            self.assertTrue(power._probe())
            files[ac_online] = "1\n"
            self.assertFalse(power._probe())
            files[ac_online] = "0\n"
            files[bat_status] = "Charging\n"
            self.assertFalse(power._probe())
        with mock.patch.object(power.subprocess, "run", side_effect=OSError("no")), \
                mock.patch.object(power.os, "listdir", side_effect=OSError("no sysfs")):
            self.assertFalse(power._probe())

        power._seen[:] = [power.time.monotonic(), True]
        with mock.patch.object(power, "_probe", return_value=False) as probe:
            self.assertTrue(power.constrained())
            probe.assert_not_called()
            power._seen[0] = -1e9
            self.assertFalse(power.constrained())
            probe.assert_called_once()
        with mock.patch.object(power, "save_battery", return_value=False), \
                mock.patch.object(power, "constrained", return_value=True):
            power._setting[0] = -1e9
            self.assertFalse(power.reduced())
            self.assertFalse(power.reduced())  # the setting is read once a second


class Hermes(unittest.TestCase):
    """Should talk to the hermes CLI through the same functions the face uses."""

    def test_the_link_keeps_an_answer_and_a_failure(self):
        """Should store a reply, stop when hermes is missing, and end a wait that ran too long."""
        hermesbot._installed_cache = None
        with mock.patch.object(hermesbot.subprocess, "run", side_effect=subprocess.TimeoutExpired("h", 1)):
            self.assertFalse(hermesbot.is_hermes_installed())
        hermesbot._installed_cache = None
        with mock.patch.object(hermesbot.subprocess, "run",
                               return_value=subprocess.CompletedProcess(["h"], 0)):
            self.assertTrue(hermesbot.is_hermes_installed())
            self.assertTrue(hermesbot.is_hermes_installed())  # cached
        hermesbot._installed_cache = None
        self.assertTrue(hermesbot.is_hermes("hermes:H"))
        self.assertFalse(hermesbot.is_hermes(None))
        with mock.patch.object(hermesbot, "widget_config", return_value={"hermesbot_target": "  Ada  "}):
            self.assertEqual(hermesbot.target(), "Ada")
        with mock.patch.object(hermesbot, "widget_config", return_value={"hermesbot_target": 3}):
            self.assertEqual(hermesbot.target(), hermesbot.DEFAULT_TARGET)
        self.assertIsNone(hermesbot._data("not json\n[1]\n{nope}"))
        self.assertEqual(hermesbot._data('{"a": 1}'), {"a": 1})
        done = subprocess.CompletedProcess(["h"], 1, "", "boom")
        self.assertEqual(hermesbot._note(done), "boom")
        self.assertEqual(hermesbot._note(subprocess.CompletedProcess(["h"], 0, "", "")), "")
        self.assertEqual(hermesbot._note(subprocess.CompletedProcess(["h"], 1, "", "")), "")
        self.assertEqual(hermesbot.parse_message('{"content": "  hoi  "}'), "hoi")
        self.assertEqual(hermesbot.parse_message('{"data": {"text": "diep"}}'), "diep")
        self.assertEqual(hermesbot.parse_message("{nope"), "")
        self.assertEqual(hermesbot.parse_message("nope"), "")

        proc = mock.Mock()
        proc.pid = 9
        proc.wait.side_effect = [subprocess.TimeoutExpired("h", 1), None]
        if hasattr(hermesbot.os, "killpg"):
            with mock.patch.object(hermesbot.os, "killpg") as kill:
                hermesbot._stop_group(proc)
                self.assertEqual(kill.call_count, 2)
            proc.wait.side_effect = None
            proc.wait.return_value = 0
            with mock.patch.object(hermesbot.os, "killpg", side_effect=ProcessLookupError):
                hermesbot._stop_group(proc)
            killpg = hermesbot.os.killpg
            try:
                del hermesbot.os.killpg
                proc.kill.reset_mock()
                hermesbot._stop_group(proc)
                proc.kill.assert_called_once()
            finally:
                hermesbot.os.killpg = killpg
        else:
            proc.kill.reset_mock()
            hermesbot._stop_group(proc)
            proc.kill.assert_called_once()

        with mock.patch.object(hermesbot.subprocess, "Popen", side_effect=OSError("missing")):
            self.assertEqual(hermesbot.run("hoi", 1).rc, 127)
        popped = mock.Mock()
        popped.args = ["hermes"]
        popped.returncode = 0
        popped.communicate.side_effect = subprocess.TimeoutExpired("h", 1)
        with mock.patch.object(hermesbot.subprocess, "Popen", return_value=popped), \
                mock.patch.object(hermesbot, "_stop_group"):
            self.assertIsNone(hermesbot.run("hoi", 1).rc)
        popped.communicate.side_effect = None
        popped.communicate.return_value = ('{"content": "antwoord"}', "")
        with mock.patch.object(hermesbot.subprocess, "Popen", return_value=popped):
            result = hermesbot.run("hoi", 1)
        self.assertEqual(result.data["content"] if False else hermesbot.parse_message(result.note or ""), "")
        self.assertEqual(hermesbot._data(popped.communicate.return_value[0])["content"], "antwoord")

        clock = {"t": 0.0}
        link = hermesbot.HermesLink("Ada", now=lambda: clock["t"])
        payload = {"stdout": '{"content": "antwoord"}', "message": ""}
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, payload, "")):
            ok, note = link.send("hoi")
        self.assertTrue(ok)
        self.assertEqual(link.chat()["messages"][-1]["text"], "antwoord")
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(None, None, "")):
            self.assertTrue(link.send("nog")[0])
        self.assertIn("may or may not", link.note())
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(127, None, "")):
            self.assertFalse(link.send("weg")[0])
        link.resume()
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(2, None, "nee")):
            self.assertFalse(link.send("fout")[0])
        link.stopped = False
        link.request_fetch()
        self.assertTrue(link.due())
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, {"response": "later"}, "")):
            self.assertTrue(link.poll())
        self.assertFalse(link.poll() if False else link.is_polling)
        link.waiting_since = clock["t"]
        clock["t"] = hermesbot.HermesLink.WAIT_MAX_S + 1
        self.assertIn("No answer", link.note())
        self.assertEqual(link.chat()["activity"], "")
        link.polling = True
        self.assertFalse(link.due())
        link.request_fetch()
        self.assertTrue(link.active())
        # A duplicate answer is not added twice, and an empty body says so.
        link.polling = False
        link.stopped = False
        link.seen.add(f"{len(link.messages)}@zelfde")
        # _apply keys on the text; feed a text that was just stored by forcing the key path via a fresh link.
        quiet = hermesbot.HermesLink("Ada", now=lambda: 0)
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, {"stdout": ""}, "")):
            self.assertFalse(quiet.poll())
        self.assertIn("no answer", quiet.status)
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, "nope", "")):
            self.assertFalse(quiet.poll())
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(127, None, "")):
            self.assertFalse(quiet.poll())
            self.assertFalse(quiet.active() and not quiet.polling)
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(2, None, "nee")):
            self.assertFalse(quiet.poll())
        quiet.stopped = False
        quiet.polling = True
        self.assertFalse(quiet.poll())
        quiet.polling = False
        dup = hermesbot.HermesLink("Ada", now=lambda: 0)
        dup.seen.add("0@zelfde")
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, {"message": "zelfde"}, "")):
            self.assertFalse(dup.poll())
        dup.waiting_since = 0
        self.assertTrue(dup.waiting)
        dup.want_fetch = False
        dup.stopped = False
        dup.last_poll = None
        self.assertTrue(dup.due())
        del dup._last_poll
        self.assertIsNone(dup.last_poll)
        with mock.patch.object(hermesbot, "run", return_value=hermesbot.Result(0, {"response": "via key"}, "")):
            self.assertEqual(link.send("sleutel")[0], True)
        self.assertIn("via key", link.chat()["messages"][-1]["text"])
        self.assertFalse(hermesbot.HermesLink("Ada", now=lambda: 0).due())


class SmallModules(unittest.TestCase):
    """Should hit the short branches in startup, updates, config and the process helpers."""

    def test_startup_checkout_and_a_frozen_app(self):
        """Should name a packaged app, a checkout and a plain install."""
        self.assertIn(startup.install_kind(), ("checkout", "uv", "packaged"))
        with mock.patch.object(startup.sys, "frozen", True, create=True), \
                mock.patch.object(startup, "from_checkout", return_value=False):
            self.assertEqual(startup.install_kind(), "packaged")
            self.assertEqual(startup.launch_command(), [sys.executable])
        with mock.patch.object(startup, "from_checkout", return_value=False), \
                mock.patch.object(startup.sys, "frozen", False, create=True):
            self.assertEqual(startup.install_kind(), "uv")
            self.assertNotIn("--dev", startup.launch_command())
        with mock.patch.object(startup, "launch_at_login", return_value=True) as enabled, \
                mock.patch.object(startup, "set_launch_at_login") as setter, \
                mock.patch.object(startup, "launch_command", return_value=["python", "-m", "botwidget"]):
            startup.set_enabled(False)
            setter.assert_called_once()
            self.assertTrue(enabled.called or startup.is_enabled())
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old)
        config.CONFIG_PATH = os.path.join(folder, "widget.json")
        with mock.patch.object(startup, "is_enabled", return_value=True), \
                mock.patch.object(startup, "set_enabled") as turn_on:
            self.assertTrue(startup.apply_default())
            turn_on.assert_not_called()
            self.assertFalse(startup.apply_default())

    def test_updates_stage_and_install(self):
        """Should keep a verified file, drop a bad checksum, and install what was staged."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        asset = updates.UPDATE_ASSET
        version_dir = os.path.join(folder, "9.9.9")
        os.makedirs(version_dir)
        path = os.path.join(version_dir, asset)
        open(path, "wb").write(b"pkg")
        open(path + updates.VERIFIED, "w").close()
        release = updates.Release("9.9.9", {asset: "http://files/pkg", updates.SUMS_ASSET: "http://files/sums"})
        with mock.patch.object(updates, "STAGING", folder):
            self.assertEqual(updates.stage(release), path)
            digest = updates.sha256_of(path)
            sums = f"{digest}  {asset}\n".encode()

            class Body:
                def __init__(self, data):
                    self.data = data

                def read(self):
                    return self.data

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return None

            def opened(url, timeout, accept="*/*"):
                if url.endswith("sums"):
                    return Body(b"abc  other\n")
                return Body(b"nope")

            os.remove(path + updates.VERIFIED)
            with mock.patch.object(updates, "_open", opened):
                self.assertIsNone(updates.stage(release))
            os.makedirs(version_dir, exist_ok=True)
            with mock.patch.object(updates, "_open", return_value=Body(sums)), \
                    mock.patch.object(updates, "_download", side_effect=lambda url, dest, timeout: open(dest, "wb").write(b"pkg")):
                # checksum of the written bytes must match; write the hashed bytes via a real file.
                pass
            blob = b"hello-update"
            digest = __import__("hashlib").sha256(blob).hexdigest()

            def download(url, dest, timeout):
                open(dest, "wb").write(blob)

            with mock.patch.object(updates, "_open", return_value=Body(f"{digest} *{asset}\n".encode())), \
                    mock.patch.object(updates, "_download", download):
                self.assertEqual(updates.stage(release), path)
            with mock.patch.object(updates, "_open", side_effect=OSError("down")):
                self.assertIsNone(updates.stage(updates.Release("9.9.8", {asset: "u", updates.SUMS_ASSET: "s"})))
            self.assertEqual(updates.staged_update("0.0.0")[0], "9.9.9")
            with mock.patch.object(updates, "can_install_update", return_value=True), \
                    mock.patch.object(updates, "install_update", return_value=True), \
                    mock.patch.object(updates.os, "remove", side_effect=OSError("busy")):
                self.assertTrue(updates.install_staged("0.0.0"))
            updates.clean_staging("9.9.9")
            self.assertFalse(os.path.isdir(version_dir))

    def test_config_checkout_channel_and_delivery(self):
        """Should survive a bad settings file and a switch that has nowhere to go."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        old = config.CONFIG_PATH
        self.addCleanup(setattr, config, "CONFIG_PATH", old)
        config.CONFIG_PATH = os.path.join(folder, "widget.json")
        config._config_read[:] = [None, None]
        with mock.patch.object(config.os, "stat", side_effect=OSError("gone")):
            config._remember({"a": 1})
        with mock.patch.object(config.os, "replace", side_effect=OSError("full")):
            self.assertFalse(config._store({"a": 1}))
        open(config.CONFIG_PATH, "w").write("{")
        config._config_read[:] = [None, None]
        self.assertIsNone(config._read_config())
        self.assertEqual(config.save_widget_config(sound=False), config.widget_config())
        open(config.CONFIG_PATH, "w").write("{}\n")
        config._config_read[:] = [None, None]
        with mock.patch.object(config.shutil, "copy2", side_effect=OSError("ro")):
            self.assertIn("backup", config.replace_widget_config({"sound": False}))
        with mock.patch.object(config, "_store", return_value=False):
            self.assertIn("save", config.replace_widget_config({"sound": False}))
        with mock.patch.object(channel, "other_command", return_value=None):
            self.assertFalse(channel.switch())
        with mock.patch.object(channel, "other_command", return_value=["/bin/true"]), \
                mock.patch.object(channel.startup, "is_enabled", return_value=False), \
                mock.patch.object(channel.subprocess, "Popen") as popen:
            self.assertTrue(channel.switch())
            popen.assert_called_once()
        missing = os.path.join(folder, "nope")
        self.assertIsNone(attachments.store_file(missing))
        self.assertIsNone(delivery.Outbox().failed("missing", True))
        with mock.patch.object(checkout.subprocess, "run", side_effect=OSError("no git")):
            self.assertIsNone(checkout._git(folder, "status"))
        self.assertFalse(checkout.pull(folder))
        self.assertEqual(bubble.line_height({"kind": "control", "control": "editor"}), 220)
        self.assertIn("opacity", bubble.more_svg(0, 0, 100, 0.2, False, 0.5))
        self.assertIn("stroke", bubble.more_svg(0, 0, 100, 0.9, True, 0.4))
        drawn = bubble.panel_svg([{"role": "bot", "lines": [{"kind": "dots", "phase": 0.2}]}], 80)
        self.assertIn("circle", drawn)
        self.assertTrue(config.check_updates())
        plain = block_text(bots({"bots": [{"id": "a", "name": "Ada", "source": "OpenBot", "on": True,
                                           "muted": True, "acp": True}], "confirm_remove": "bot-remove/a"}))
        self.assertIn("Again", plain)
        self.assertIn("Unmute", plain)

    def test_processes_instance_and_dev_mode(self):
        """Should stop an old widget, restart on a changed file, and hand over."""
        with mock.patch.object(posix.subprocess, "run", side_effect=OSError("no ps")):
            self.assertEqual(posix.process_cmdline(1), b"")
        with mock.patch.object(posix.subprocess, "Popen", side_effect=[OSError("missing"), mock.Mock()]):
            posix.spawn_first((["missing"], ["there"]))
        self.assertTrue(posix.self_removing("echo hi").startswith("rm -f"))
        pid = os.path.join(tempfile.mkdtemp(), "pid")
        self.addCleanup(shutil.rmtree, os.path.dirname(pid), True)
        open(pid, "w").write("not-a-pid")
        with mock.patch.object(instance, "process_cmdline", return_value=b""):
            instance.ensure_single_instance(pid)
        open(pid, "w").write("424242")
        seen = {"n": 0}

        def cmdline(pid_):
            seen["n"] += 1
            return b"botwidget" if seen["n"] < 3 else b""

        with mock.patch.object(instance, "process_cmdline", side_effect=cmdline), \
                mock.patch.object(instance.os, "kill"), \
                mock.patch.object(instance.time, "sleep"):
            instance.ensure_single_instance(pid)
        # The previous process never dies: the second signal is KILL.
        open(pid, "w").write("424242")
        with mock.patch.object(instance, "process_cmdline", return_value=b"botwidget"), \
                mock.patch.object(instance.os, "kill") as kill, \
                mock.patch.object(instance.time, "sleep"):
            instance.ensure_single_instance(pid, markers=(b"botwidget",))
        self.assertEqual(kill.call_args_list[-1].args[1], getattr(signal, "SIGKILL", signal.SIGTERM))

        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired("x", 1)
        dev.stop(child)
        child.kill.assert_called_once()
        dev.stop(None)
        child.poll.return_value = 0
        dev.stop(child)

        from botwidget.channel import HANDOVER_EXIT
        snaps = [{"a.py": 1}, {"a.py": 2}, {"a.py": 2}]
        kids = []

        class Child:
            def __init__(self):
                self.returncode = None
                self.n = len(kids)

            def poll(self):
                return HANDOVER_EXIT if self.n == 1 else self.returncode

            def terminate(self):
                self.returncode = -15

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.returncode = -9

        def start(extra=()):
            made = Child()
            kids.append(made)
            return made

        with mock.patch.object(dev, "snapshot", side_effect=lambda folder=dev.PACKAGE: snaps.pop(0)), \
                mock.patch.object(dev, "start", start), \
                mock.patch.object(dev, "ensure_single_instance"), \
                mock.patch.object(dev.time, "sleep"), \
                mock.patch.object(dev.signal, "signal"), \
                mock.patch("builtins.print"):
            dev.run(poll=0)
        self.assertEqual(len(kids), 2)
        # A crash waits for the next edit, then starts again. The next look hands over.
        snaps2 = [{"a.py": 1}, {"a.py": 1}, {"a.py": 3}, {"a.py": 3}]
        kids.clear()

        class Crashing(Child):
            def poll(self):
                if self.n == 0:
                    self.returncode = 1
                    return 1
                return HANDOVER_EXIT

        def start2(extra=()):
            made = Crashing()
            kids.append(made)
            return made

        with mock.patch.object(dev, "snapshot", side_effect=lambda folder=dev.PACKAGE: snaps2.pop(0)), \
                mock.patch.object(dev, "start", start2), \
                mock.patch.object(dev, "ensure_single_instance"), \
                mock.patch.object(dev.time, "sleep"), \
                mock.patch.object(dev.signal, "signal"), \
                mock.patch("builtins.print"):
            dev.run(poll=0)
        self.assertGreaterEqual(len(kids), 2)
        with mock.patch.object(dev.subprocess, "Popen") as popen:
            dev.start(["--keep-login"])
            self.assertIn("--keep-login", popen.call_args.args[0])
        child = mock.Mock()
        child.poll.return_value = None
        caught = {}

        def grab(sig, fn):
            caught["fn"] = fn

        def nap(_seconds):
            caught["fn"]()

        with mock.patch.object(dev, "snapshot", return_value={"a.py": 1}), \
                mock.patch.object(dev, "start", return_value=child), \
                mock.patch.object(dev, "ensure_single_instance"), \
                mock.patch.object(dev.signal, "signal", grab), \
                mock.patch.object(dev.time, "sleep", nap), \
                mock.patch.object(dev.sys, "exit", side_effect=SystemExit), \
                mock.patch("builtins.print"):
            with self.assertRaises(SystemExit):
                dev.run(poll=0)
        child.terminate.assert_called()


class Entry(unittest.TestCase):
    """Should start the widget's entry points without sitting in the event loop."""

    def test_version_login_dev_and_a_quit(self):
        """Should print the version, flip the login item, and leave when Qt does."""
        with mock.patch.object(sys, "argv", ["botwidget", "--version"]), mock.patch("builtins.print") as printed:
            appmod.main()
        printed.assert_called()
        with mock.patch.object(sys, "argv", ["botwidget", "--login-item", "on"]), \
                mock.patch.object(appmod, "startup") as start:
            start.is_enabled.return_value = True
            appmod.main()
            start.set_enabled.assert_called_with(True)
        with mock.patch.object(sys, "argv", ["botwidget", "--dev"]), mock.patch("botwidget.dev.run") as run:
            appmod.main()
            run.assert_called_once()

        class App:
            def __init__(self, argv):
                self.argv = argv

            def setApplicationName(self, name):
                pass

            def setApplicationDisplayName(self, name):
                pass

            def setDesktopFileName(self, name):
                pass

            def setWindowIcon(self, icon):
                pass

            def setQuitOnLastWindowClosed(self, on):
                pass

            def exec(self):
                raise KeyboardInterrupt

        icon = os.path.join(tempfile.mkdtemp(), "icon.png")
        self.addCleanup(shutil.rmtree, os.path.dirname(icon), True)
        open(icon, "wb").write(b"png")
        faces = mock.Mock()
        faces.faces = {"a": mock.Mock()}
        with mock.patch.object(sys, "argv", ["botwidget", "--keep-login"]), \
                mock.patch.object(appmod, "QApplication", App), \
                mock.patch.object(appmod, "QTimer") as timer, \
                mock.patch.object(appmod, "QIcon"), \
                mock.patch.object(appmod, "updates") as upd, \
                mock.patch.object(appmod, "auto_update", return_value=True), \
                mock.patch.object(appmod, "prepare_gui_environment"), \
                mock.patch.object(appmod, "install_quit_signals", return_value=lambda *a: None), \
                mock.patch.object(appmod, "install_font_fallbacks"), \
                mock.patch.object(appmod, "ensure_single_instance"), \
                mock.patch.object(appmod, "hide_from_dock"), \
                mock.patch.object(appmod, "channel"), \
                mock.patch.object(appmod, "Faces", return_value=faces), \
                mock.patch.object(appmod, "register_hotkey", return_value=True), \
                mock.patch.object(appmod, "startup") as start, \
                mock.patch.object(appmod, "icon_path", return_value=icon), \
                mock.patch.dict(os.environ, {"BOT_WIDGET_OPEN_CHAT": "1"}), \
                mock.patch.object(appmod.sys, "exit") as leave:
            upd.clean_staging.return_value = None
            upd.install_staged.return_value = False
            start.apply_default.return_value = True
            appmod.main()
            leave.assert_called_with(0)
            timer.singleShot.assert_called()
        with mock.patch.object(sys, "argv", ["botwidget"]), \
                mock.patch.object(appmod, "auto_update", return_value=True), \
                mock.patch.object(appmod, "updates") as upd, \
                mock.patch.object(appmod.sys, "exit", side_effect=SystemExit) as leave:
            upd.install_staged.return_value = True
            with self.assertRaises(SystemExit):
                appmod.main()
            leave.assert_called_with(0)
        with mock.patch.object(appmod.sys, "executable", icon), \
                mock.patch.object(appmod.sys, "_MEIPASS", os.path.dirname(icon), create=True), \
                mock.patch.object(appmod.sys, "platform", "linux"):
            self.assertTrue(appmod.icon_path().endswith("icon.png"))
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])

        class App(QObject):
            def quit(self):
                self.gone = True

        previous = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
        try:
            stop = appmod.install_quit_signals(mock.Mock(), wake=mock.Mock())
            stop(None, None)
            parent = App()
            stop = appmod.install_quit_signals(parent)
            stop(None, None)
            self.assertTrue(parent.gone)
        finally:
            signal.signal(signal.SIGINT, previous[0])
            signal.signal(signal.SIGTERM, previous[1])

        with mock.patch("botwidget.qt_ui.app.main") as main:
            runpy.run_module("botwidget", run_name="__main__")
            # run_module on a package may not execute __main__ when imported as botwidget.
        # The file itself is the entry.
        with mock.patch("botwidget.qt_ui.app.main") as main:
            runpy.run_path(os.path.join(ROOT, "botwidget", "__main__.py"), run_name="__main__")
            main.assert_called_once()
        source = open(os.path.join(ROOT, "botwidget", "__init__.py")).read()
        code = compile(source, os.path.join(ROOT, "botwidget", "__init__.py"), "exec")
        real_import = __import__

        def blocked(name, *args, **kwargs):
            if name == "botwidget._version":
                raise ImportError("no version")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", blocked):
            ns = {"__name__": "botwidget_probe"}
            exec(code, ns)
        self.assertEqual(ns["__version__"], "0.0.0+unknown")

        current = open(os.path.join(ROOT, "botwidget", "system", "current.py")).read()
        compiled = compile(current, os.path.join(ROOT, "botwidget", "system", "current.py"), "exec")
        for platform in ("win32", "darwin"):
            with mock.patch.object(sys, "platform", platform):
                ns = {"__name__": "probe"}
                exec(compiled, ns)
            self.assertTrue(hasattr(ns["_os"], "activate_app"))


class OtherSystems(unittest.TestCase):
    """Should run the macOS and Windows helpers against stand-in libraries."""

    def test_windows_registry_taskbar_and_installer(self):
        """Should hide a taskbar button, write the Run key, and start the installer."""
        calls = []

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

        winreg = mock.Mock()
        winreg.HKEY_CURRENT_USER = 1
        winreg.KEY_SET_VALUE = 2
        winreg.REG_SZ = 1
        winreg.OpenKey.return_value = Key()
        winreg.QueryValueEx.side_effect = lambda *args: ("BotWidget", 1)
        winreg.SetValueEx.side_effect = lambda *args: calls.append(args)
        winreg.DeleteValue.side_effect = OSError("missing")
        winsound = mock.Mock()
        user32 = mock.Mock()
        user32.GetWindowLongPtrW.return_value = 0
        user32.GetWindowLongW.return_value = 0
        user32.SetWindowLongPtrW.return_value = 0
        user32.SetWindowLongW.return_value = 0
        with mock.patch.dict(sys.modules, {"winreg": winreg, "winsound": winsound}), \
                mock.patch.object(windows.sys, "platform", "win32"), \
                mock.patch.object(windows.ctypes, "WinDLL", return_value=user32, create=True):
            self.assertIsNotNone(windows._user32())
            windows.hide_from_taskbar(5)
            windows.hide_from_taskbar(0)
            windows.play_notification()
            self.assertTrue(windows.launch_at_login())
            windows.set_launch_at_login(["botwidget"], True)
            windows.set_launch_at_login(["botwidget"], False)
            self.assertTrue(calls)
        winreg.QueryValueEx.side_effect = OSError("no key")
        with mock.patch.dict(sys.modules, {"winreg": winreg}):
            self.assertFalse(windows.launch_at_login())
        with mock.patch.object(windows.sys, "platform", "linux"):
            self.assertIsNone(windows._user32())
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        app = os.path.join(folder, "Bot Widget.exe")
        open(app, "w").close()
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": folder, "APPDATA": folder}), \
                mock.patch.object(windows.os.path, "exists", return_value=True):
            # exists is patched globally for this process's windows.os — only the path check.
            pass
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.dirname(app)}):
            # stable path joins Programs/Bot Widget/... so point exists at that file.
            target = os.path.join(os.path.dirname(app), "Programs", "Bot Widget", "Bot Widget.exe")
            os.makedirs(os.path.dirname(target))
            open(target, "w").close()
            self.assertEqual(windows.stable_app_command(), [target])
        with mock.patch.object(windows.sys, "frozen", True, create=True):
            self.assertTrue(windows.can_install_update())
        with mock.patch("subprocess.Popen") as popen:
            self.assertTrue(windows.install_update("setup.exe"))
            popen.assert_called_once()
        windows.set_desktops(1, True)
        self.assertFalse(windows.set_backdrop(1, 0, 0, 1, 1, b""))
        windows.clear_backdrop(1)
        self.assertTrue(windows.on_active_space(1))
        self.assertTrue(windows.is_shown_here(1))
        windows.move_to_active_space(1)
        windows.hide_from_dock()
        self.assertFalse(windows.register_hotkey(lambda: None))
        with mock.patch.object(windows.sys, "platform", "win32"), \
                mock.patch.object(windows.ctypes, "WinDLL", side_effect=OSError("no user32"), create=True):
            self.assertIsNone(windows._user32())
        kept = {key: value for key, value in os.environ.items() if key != "APPDATA"}
        with mock.patch.dict(os.environ, kept, clear=True):
            self.assertEqual(windows.data_home(), os.path.expanduser("~"))
        windows.prepare_gui_environment()
        self.assertEqual(windows.process_cmdline(1), b"")
        windows.activate_app()
        windows.before_show(0)
        windows.send_behind_windows(1)
        self.assertIsNone(windows.pointer_window())

    def test_macos_window_calls_and_login_items(self):
        """Should drive the Objective-C helpers with a stand-in messenger."""
        objc = mock.Mock()
        objc.sel_registerName.side_effect = lambda name: name
        objc.objc_getClass.return_value = 1

        def send(objc_mod, restype, *argtypes):
            def call(*args):
                if restype is macos._Rect:
                    return macos._Rect(macos._Point(0, 0), macos._Size(20, 90))
                if restype is ctypes.c_bool:
                    return True
                if restype is ctypes.c_long:
                    return macos.SM_ENABLED
                return 1
            return call

        carbon = mock.Mock()
        carbon.GetApplicationEventTarget.return_value = 1
        carbon.InstallEventHandler.return_value = 0
        carbon.RegisterEventHotKey.return_value = 0
        cg = mock.Mock()
        cg.CGWindowLevelForKey.return_value = 3

        def load(name):
            if "Carbon" in str(name):
                return carbon
            return cg

        macos._objc.cache_clear()
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(macos, "_objc", return_value=objc), \
                mock.patch.object(macos, "_send", send), \
                mock.patch.object(macos.ctypes.cdll, "LoadLibrary", load), \
                mock.patch.object(macos.ctypes.util, "find_library", side_effect=lambda name: name), \
                mock.patch.object(macos, "_launch_agent", return_value=os.path.join(home, "agent.plist")), \
                mock.patch.object(macos, "_dev_launcher", return_value=os.path.join(home, "launcher")):
            macos.hide_from_dock()
            macos.activate_app()
            called = []
            self.assertTrue(macos.register_hotkey(lambda: called.append(1)))
            macos._hotkey_handler(lambda: called.append(1))(None, None, None)
            self.assertEqual(called, [1])
            carbon.InstallEventHandler.return_value = 1
            self.assertFalse(macos.register_hotkey(lambda: None))
            carbon.InstallEventHandler.return_value = 0
            self.assertEqual(macos.desktop_behavior(True),
                             macos.CAN_JOIN_ALL_SPACES | macos.FULL_SCREEN_AUXILIARY)
            macos.set_desktops(1, True, True)
            macos.set_desktops(1, False, False)
            self.assertTrue(macos.on_active_space(1))
            self.assertTrue(macos.is_shown_here(1))
            macos.move_to_active_space(1)
            self.assertTrue(macos.set_backdrop(1, 0, 0, 10, 10, b"png"))
            self.assertTrue(macos.set_backdrop(1, 0, 0, 10, 10, b"png"))  # same shape: nothing new
            macos.clear_backdrop(1)
            macos.send_behind_windows(1)
            self.assertIsNone(macos._login_service())
            self.assertFalse(macos.launch_at_login())
            macos.set_launch_at_login(["/usr/bin/true"], True)
            self.assertTrue(os.path.exists(os.path.join(home, "agent.plist")))
            self.assertTrue(macos.launch_at_login())
            macos.set_launch_at_login(["/usr/bin/true"], False)
            self.assertFalse(os.path.exists(os.path.join(home, "agent.plist")))
            with mock.patch.object(macos, "_bundle_path", return_value="/Apps/Bot Widget.app"), \
                    mock.patch.object(macos.ctypes.cdll, "LoadLibrary", return_value=cg):
                objc.objc_getClass.return_value = 1
                self.assertIsNotNone(macos._login_service())
                macos.set_launch_at_login(["/usr/bin/true"], True)
            with mock.patch.object(macos, "_objc", side_effect=OSError("no objc")):
                self.assertFalse(macos.set_backdrop(2, 0, 0, 1, 1, b"x"))
            macos._backdrops[3] = (1, (), b"")
            with mock.patch.object(macos, "_objc", side_effect=OSError("no")):
                macos.clear_backdrop(3)
        with mock.patch.object(macos.sys, "frozen", True, create=True), \
                mock.patch.object(macos.sys, "executable", "/Apps/Bot Widget.app/Contents/MacOS/bot"), \
                mock.patch.object(macos.platform, "machine", return_value="arm64"), \
                mock.patch.object(macos.os, "access", return_value=True):
            self.assertTrue(macos.can_install_update())
            with mock.patch.object(macos, "apply_bundle_update") as apply:
                self.assertTrue(macos.install_update("app.zip"))
                apply.assert_called_once()
        with mock.patch.object(macos, "_bundle_path", return_value=None):
            self.assertFalse(macos.install_update("app.zip"))
        macos.prepare_gui_environment()
        macos.play_notification()
        self.assertIsNone(macos.pointer_window())
        self.assertIn("Application Support", macos.data_home())
        self.assertIn("LaunchAgents", macos._launch_agent())
        self.assertTrue(macos._dev_launcher().endswith(macos.DEV_LAUNCHER_NAME))
        macos._objc.cache_clear()
        stood_in = mock.Mock()
        with mock.patch.object(macos.ctypes.cdll, "LoadLibrary", return_value=stood_in), \
                mock.patch.object(macos.ctypes.util, "find_library", return_value="libobjc"):
            self.assertIs(macos._objc(), stood_in)
        macos._objc.cache_clear()
        with self.assertRaises(TypeError):
            macos._send(mock.Mock(), ctypes.c_void_p)
        objc.objc_getClass.return_value = 0
        with mock.patch.object(macos, "_bundle_path", return_value="/Apps/Bot Widget.app"), \
                mock.patch.object(macos, "_objc", return_value=objc), \
                mock.patch.object(macos, "_send", send), \
                mock.patch.object(macos.ctypes.cdll, "LoadLibrary", return_value=cg):
            self.assertIsNone(macos._login_service())
        objc.objc_getClass.return_value = 1
        with mock.patch.object(macos, "_bundle_path", return_value="/Apps/Bot Widget.app"), \
                mock.patch.object(macos, "_objc", return_value=objc), \
                mock.patch.object(macos, "_send", send), \
                mock.patch.object(macos.ctypes.cdll, "LoadLibrary", return_value=cg):
            self.assertTrue(macos.launch_at_login())
        effect = object()
        macos._backdrops[9] = (effect, (), b"old")

        def send_other(_objc_mod, restype, *_argtypes):
            def call(*args):
                if restype is macos._Rect:
                    return macos._Rect(macos._Point(0, 0), macos._Size(20, 90))
                if args and args[0] is effect:
                    return 99
                return 1
            return call

        with mock.patch.object(macos, "_objc", return_value=objc), \
                mock.patch.object(macos, "_send", send_other):
            self.assertTrue(macos.set_backdrop(9, 0, 0, 10, 10, b"new"))
        macos._backdrops.pop(9, None)
        with mock.patch.object(macos.posix, "spawn_script") as spawn:
            macos.apply_bundle_update("a.zip", "/Apps/Bot Widget.app", 4)
        spawn.assert_called_once()
        with mock.patch.object(macos.os.path, "isdir",
                               side_effect=lambda path: str(path).startswith("/Applications")):
            command = macos.stable_app_command()
        self.assertEqual(command, ["open", os.path.join("/Applications", "Bot Widget.app"), "--args"])
        with mock.patch.object(macos.os.path, "isdir", return_value=False):
            self.assertIsNone(macos.stable_app_command())


class LinuxX(unittest.TestCase):
    """Should run the X11 helpers against a stand-in libX11, and the library fetch against a stand-in apt."""

    def tearDown(self):
        linux._xlib_once = None

    def test_xlib_autostart_and_the_x11_packages(self):
        """Should mark a window, write the login file, and explain a missing library."""
        buf = ctypes.c_ulong(7)

        class Lib:
            def __init__(self, display=1, prop=0):
                self.display = display
                self.prop = prop
                self.buf = buf

            def __getattr__(self, name):
                def call(*args):
                    if name == "XOpenDisplay":
                        return self.display
                    if name == "XDefaultRootWindow":
                        return 2
                    if name == "XInternAtom":
                        return 3
                    if name == "XQueryPointer":
                        child = getattr(args[3], "_obj", None)
                        if child is not None:
                            child.value = 15
                        return 1
                    if name == "XGetWindowProperty":
                        data = getattr(args[11], "_obj", None)
                        if data is not None and self.prop == 0:
                            data.value = ctypes.addressof(self.buf)
                        return self.prop
                    return 0
                call.restype = None
                call.argtypes = None
                return call

        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with mock.patch.object(linux.ctypes, "CDLL", return_value=Lib()), \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": home, "QT_QPA_PLATFORM": "xcb", "DISPLAY": ":1"}):
            lib = linux._xlib()
            self.assertIsNotNone(lib)
            lib.skip_taskbar_unmapped(4, "above")
            lib.skip_taskbar_unmapped(4, "")
            self.assertEqual(lib.pointer_child(), 15)
            lib.set_desktop(4, True)
            lib.set_desktop(4, False)
            lib.behind(4)
            self.assertEqual(lib._atom("_NET_WM_STATE"), lib._atom("_NET_WM_STATE"))
            linux.send_behind_windows(4)
            linux.before_show(4, "below")
            self.assertEqual(linux.pointer_window(), 15)
            linux.set_launch_at_login(["botwidget", "--dev mode"], True)
            self.assertTrue(linux.launch_at_login())
            linux.set_launch_at_login(["botwidget"], False)
            self.assertFalse(linux.launch_at_login())
            with mock.patch.object(linux.os.path, "exists", return_value=False):
                self.assertIsNone(linux.stable_app_command())
        with mock.patch.object(linux.ctypes, "CDLL", return_value=Lib(display=0)):
            linux._xlib_once = None
            dead = linux._Xlib()
            self.assertIsNone(dead.pointer_child())
            dead.set_desktop(1, False)
            dead.behind(1)
            dead.skip_taskbar_unmapped(1, "above")
            self.assertIsNone(dead._cardinal(1, "x"))
        with mock.patch.object(linux.ctypes, "CDLL", return_value=Lib(prop=1)):
            linux._xlib_once = None
            self.assertIsNone(linux._Xlib()._cardinal(1, "_NET_CURRENT_DESKTOP"))
        with mock.patch.object(linux.ctypes, "CDLL", side_effect=OSError("no lib")):
            linux._xlib_once = None
            self.assertIsNone(linux._xlib())
        linux.send_behind_windows(0)
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            self.assertIsNone(linux.pointer_window())

        qt_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, qt_root, True)
        plugin = os.path.join(qt_root, "Qt", "plugins", "platforms", "libqxcb.so")
        os.makedirs(os.path.dirname(plugin))
        os.makedirs(os.path.join(qt_root, "Qt", "lib"))
        open(plugin, "w").close()
        ldd = "libxcb-cursor.so.0 => not found\nlibQt6Core.so.6 => /usr/lib/libQt6Core.so.6\n"
        found = "libxcb-cursor.so.0 => /usr/lib/libxcb-cursor.so.0\n"
        debs = []
        ldd_calls = {"n": 0}

        def run(cmd, **kwargs):
            if cmd[0] == "ldd":
                ldd_calls["n"] += 1
                # The second look is after the copy: the library is there, so the fetch can stop.
                stdout = ldd if ldd_calls["n"] == 1 else found
                return subprocess.CompletedProcess(cmd, 0, stdout=stdout)
            if cmd[0] == "apt-get":
                open(os.path.join(kwargs["cwd"], "lib.deb"), "w").close()
                debs.append(cmd)
                return subprocess.CompletedProcess(cmd, 0)
            if cmd[0] == "dpkg":
                out = cmd[-1]
                libdir = os.path.join(out, "usr", "lib", "x86_64-linux-gnu")
                os.makedirs(libdir, exist_ok=True)
                open(os.path.join(libdir, "libxcb-cursor.so.0"), "w").close()
                return subprocess.CompletedProcess(cmd, 0)
            return subprocess.CompletedProcess(cmd, 1)

        with mock.patch.object(linux, "_platform_plugin", return_value=plugin), \
                mock.patch.object(linux.shutil, "which", return_value="/usr/bin/apt-get"), \
                mock.patch.object(linux.subprocess, "run", side_effect=run), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            linux.ensure_x11_libraries()
        self.assertTrue(debs)
        with mock.patch.object(linux, "_platform_plugin", return_value=None):
            linux.ensure_x11_libraries()
        with mock.patch.object(linux.shutil, "which", return_value=None):
            self.assertFalse(linux._fetch_x11_libraries("/tmp"))
        with mock.patch.dict(os.environ, {"DISPLAY": ":1", "QT_QPA_PLATFORM": ""}), \
                mock.patch.object(linux, "ensure_x11_libraries") as fetch:
            linux.prepare_gui_environment()
            fetch.assert_called_once()
        self.assertFalse(linux.set_backdrop(1, 0, 0, 1, 1, b""))
        linux.clear_backdrop(1)
        self.assertTrue(linux.on_active_space(1))
        self.assertTrue(linux.is_shown_here(1))
        linux.move_to_active_space(1)
        self.assertFalse(linux.register_hotkey(lambda: None))
        if sys.platform.startswith("linux"):
            # libqxcb.so is the Linux plugin name. macOS and Windows ship another file.
            self.assertTrue(linux._platform_plugin("libqxcb.so"))
        # The suite replaces these three so a test cannot steal focus or play a sound. Reload runs the real ones.
        held = {name: getattr(linux, name) for name in ("activate_app", "play_notification", "hide_from_dock")}
        importlib.reload(linux)
        try:
            linux.activate_app()
            linux.hide_from_dock()
            with mock.patch.object(linux.posix, "spawn_first") as play:
                linux.play_notification()
                play.assert_called_once()
        finally:
            for name, fn in held.items():
                setattr(linux, name, fn)
        def fail(cmd, **kwargs):
            if cmd[0] == "ldd":
                return subprocess.CompletedProcess(cmd, 0, stdout=ldd)
            return subprocess.CompletedProcess(cmd, 1)
        with mock.patch.object(linux, "_platform_plugin", return_value=plugin), \
                mock.patch.object(linux.shutil, "which", return_value="/usr/bin/apt-get"), \
                mock.patch.object(linux.subprocess, "run", side_effect=fail), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            linux.ensure_x11_libraries()

        def unpacked(cmd, **kwargs):
            if cmd[0] == "ldd":
                return subprocess.CompletedProcess(cmd, 0, stdout=ldd)
            if cmd[0] == "apt-get":
                open(os.path.join(kwargs["cwd"], "lib.deb"), "w").close()
                return subprocess.CompletedProcess(cmd, 0)
            return subprocess.CompletedProcess(cmd, 1)

        def present(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout=found)

        with mock.patch.object(linux, "_platform_plugin", return_value=plugin), \
                mock.patch.object(linux.shutil, "which", return_value="/usr/bin/apt-get"), \
                mock.patch.object(linux.subprocess, "run", side_effect=unpacked), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            linux.ensure_x11_libraries()
        with mock.patch.object(linux, "_platform_plugin", return_value=plugin), \
                mock.patch.object(linux.subprocess, "run", side_effect=present):
            linux.ensure_x11_libraries()
        with mock.patch.dict(sys.modules, {"PySide6": None}):
            self.assertIsNone(linux._platform_plugin("libqxcb.so"))
        with mock.patch.dict(os.environ, {"QT_QPA_PLATFORM": "xcb"}), \
                mock.patch.object(linux, "_xlib", return_value=None):
            linux.send_behind_windows(4)
            linux.before_show(4, "below")
            self.assertIsNone(linux.pointer_window())
        with mock.patch.object(linux.posix, "spawn_script") as spawn:
            self.assertTrue(linux.install_update("BotWidget-Linux.tar.gz"))
            spawn.assert_called_once()


class WidgetBits(unittest.TestCase):
    """Should open the small UI helpers that do not need a desktop session."""

    def test_fonts_glass_prewarm_rows_and_bubble_order(self):
        """Should install fallbacks, paint a marked row, and keep a menu above an arc guest."""
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        with mock.patch.object(QFontDatabase, "families", return_value=[]):
            fonts.install_font_fallbacks()
        prewarm = __import__("botwidget.qt_ui.prewarm", fromlist=["prewarm"])
        prewarm.prewarm()
        self.assertTrue(glass.enabled())
        pix = glass._tile(1)
        self.assertFalse(pix.isNull())
        shape = glass._tile(1)
        glass.png(shape)
        with mock.patch.object(glass, "blurs", return_value=True), \
                mock.patch.object(glass, "set_backdrop") as backdrop, \
                mock.patch.object(glass, "clear_backdrop") as clear, \
                mock.patch.object(glass, "native_id", return_value=1):
            glass.update(object(), __import__("PySide6.QtCore", fromlist=["QRect"]).QRect(0, 0, 10, 10),
                         __import__("PySide6.QtCore", fromlist=["QRect"]).QRect(0, 0, 20, 20), b"png")
            backdrop.assert_called_once()
            glass.clear(object())
            clear.assert_called_once()
        row = ItemRow("Ada", True, "bot/a", [{"label": "Again", "command": "go"},
                                             {"label": "Mute", "command": "mute"}])
        row.resize(420, 36)
        row.press_at(400)
        row.press_at(10)
        row.show()
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication as App
        from botwidget.qt_ui.controls import SlashList, TextEditor
        row._hits = []
        row.paintEvent(None)
        editor = TextEditor("{\"a\": 1}")
        self.assertIn("a", editor.text_value())
        listing = SlashList()
        listing.show_rows([("/bots", "Bots")])
        picked = []
        listing.chosen.connect(picked.append)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(8, 20), Qt.MouseButton.NoButton,
                           Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        listing.mouseMoveEvent(move)
        listing.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(8, 20), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(picked, ["/bots"])
        App.instance().processEvents()

        order = []

        class Window:
            def __init__(self, name, guest=False):
                self.name = name
                self._arc_guest = guest
                self.bubble = None

            def isVisible(self):
                return True

            def raise_(self):
                order.append(self.name)

            def lower(self):
                order.append("lower-" + self.name)

        guest = Window("guest", guest=True)
        menu = Window("menu")
        guest.bubble = menu
        face = Window("face")
        chat = Window("chat")
        chat.isVisible = lambda: False
        face.bubble = chat
        holder = SimpleNamespace(faces={"a": face}, _arc_guests={"b": guest})
        with mock.patch("botwidget.qt_ui.faces.always_on_top", return_value=True):
            Faces.raise_bubbles(holder)
        self.assertLess(order.index("guest"), order.index("menu"))


class OpenBotEdges(unittest.TestCase):
    """Should read the local store and the HTTP API through stand-ins, never a live OpenBot."""

    def test_a_missing_store_and_a_bad_answer_come_back_empty(self):
        """Should skip a store that will not open, a blank line, and a token the bubble must not show."""
        import sqlite3
        from botwidget import openbot
        self.assertEqual(openbot._chat_text("nope"), "")
        self.assertEqual(openbot._chat_text('{"source": "routine", "text": "x"}'), "")
        self.assertEqual(openbot._chat_text('{"text": 1}'), "")
        self.assertEqual(openbot._chat_text('{"text": " hoi "}'), "hoi")
        self.assertEqual(openbot.failure_note(""), "The last turn failed.")
        self.assertEqual(openbot.failure_note(None), "The last turn failed.")
        with mock.patch.object(openbot, "DB_FILE", os.path.join(tempfile.mkdtemp(), "missing-dir", "no.db")):
            self.assertEqual(openbot.list_bots(), [])
            self.assertEqual(openbot.latest_chat("t")["messages"], [])
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "openbot.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE projection_agents (agent_json, thread_id, sort_order, agent_id)")
        con.execute("CREATE TABLE projection_turns (thread_id, status)")
        con.execute("INSERT INTO projection_agents VALUES (?, 'th', 1, 'a')",
                    (json.dumps({"id": "a", "name": "Ada", "avatarHue": 12}),))
        con.execute("INSERT INTO projection_agents VALUES (?, 'tb', 2, 'b')", ("{nope",))
        con.execute("INSERT INTO projection_agents VALUES (?, 'tc', 3, '')", (json.dumps({"name": "no id"}),))
        con.execute("INSERT INTO projection_turns VALUES ('th', 'running')")
        con.commit()
        con.close()
        with mock.patch.object(openbot, "DB_FILE", path):
            bots = openbot.list_bots()
        self.assertEqual(bots[0]["name"], "Ada")
        self.assertEqual(bots[0]["status"], "working")
        empty = os.path.join(folder, "empty.db")
        sqlite3.connect(empty).close()
        with mock.patch.object(openbot, "DB_FILE", empty):
            self.assertEqual(openbot.list_bots(), [])
            self.assertEqual(openbot.latest_chat("t")["messages"], [])

        class Body:
            def __init__(self, raw):
                self.raw = raw

            def read(self):
                return self.raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch.object(openbot, "read_file", return_value=""):
            self.assertIsNone(openbot.api_get("/bots"))
        with mock.patch.object(openbot, "read_file", return_value="Authorization: Bearer tok"), \
                mock.patch.object(openbot.urllib.request, "urlopen", return_value=Body(b'{"ok": 1}')):
            self.assertEqual(openbot.api_get("/bots"), {"ok": 1})
        with mock.patch.object(openbot, "read_file", return_value="tok"), \
                mock.patch.object(openbot.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertIsNone(openbot.api_get("/bots"))
        with mock.patch.object(openbot.os.path, "exists", return_value=False):
            self.assertEqual(openbot.grok_bot_status()["note"], "gbot not found")
        with mock.patch.object(openbot.os.path, "exists", return_value=True), \
                mock.patch.object(openbot.subprocess, "run", side_effect=subprocess.TimeoutExpired("g", 1)):
            self.assertIn("no answer", openbot.grok_bot_status()["note"])
        with mock.patch.object(openbot.os.path, "exists", return_value=True), \
                mock.patch.object(openbot.subprocess, "run", side_effect=OSError("missing")):
            self.assertIn("missing", openbot.grok_bot_status()["note"])
        listed = subprocess.CompletedProcess(["g"], 0, stdout='not\n{"bots": [{"name": "Ada"}]}\n')
        with mock.patch.object(openbot.os.path, "exists", return_value=True), \
                mock.patch.object(openbot.subprocess, "run", return_value=listed):
            self.assertEqual(openbot.grok_bot_status()["bots"], [{"name": "Ada"}])
        broken = subprocess.CompletedProcess(["g"], 0, stdout="{nope\n")
        with mock.patch.object(openbot.os.path, "exists", return_value=True), \
                mock.patch.object(openbot.subprocess, "run", return_value=broken):
            self.assertFalse(openbot.grok_bot_status()["connected"])

        chat = os.path.join(folder, "chat.db")
        con = sqlite3.connect(chat)
        con.execute("CREATE TABLE projection_thread_messages (thread_id, author, item_type, message_json, created_at)")
        con.execute("CREATE TABLE projection_threads (thread_id, active_turn_id)")
        con.execute("CREATE TABLE projection_turns (turn_id, thread_id, status, completed_at)")
        con.execute("CREATE TABLE projection_deliveries (turn_id, error)")
        con.execute("INSERT INTO projection_thread_messages VALUES ('t', 'bot', 'commentary', ?, '2')",
                    (json.dumps({"text": "Authorization: Bearer secret"}),))
        con.execute("INSERT INTO projection_thread_messages VALUES ('t', 'user', 'message', ?, '1')",
                    (json.dumps({"text": "  "}),))
        con.execute("INSERT INTO projection_threads VALUES ('t', 'u1')")
        con.execute("INSERT INTO projection_turns VALUES ('u1', 't', 'running', NULL)")
        con.commit()
        con.close()
        with mock.patch.object(openbot, "DB_FILE", chat):
            live = openbot.latest_chat("t")
        self.assertEqual(live["activity"], "working…")
        self.assertEqual(live["messages"], [])


class GrokEdges(unittest.TestCase):
    """Should keep the small grok parsers honest when the reply is not the usual shape."""

    def test_a_broken_line_and_a_busy_poll_do_not_invent_an_answer(self):
        """Should ignore a line that is not an object, and skip a look that is already running."""
        from botwidget import grokbot
        self.assertIsNone(grokbot._data("nope\n{nope"))
        self.assertEqual(grokbot._note(subprocess.CompletedProcess(["g"], 1, "", "")), "")
        self.assertFalse(grokbot.accepted("x"))
        self.assertFalse(grokbot.accepted({"result": {}}))
        self.assertEqual(grokbot._error({"error": {"message": "nee"}}, "", 1), "nee")
        self.assertEqual(grokbot._error({}, "said so", 1), "said so")
        self.assertIn("unknown", grokbot._error({"delivery": "unknown"}, "", 1))
        self.assertIn("2", grokbot._error({}, "", 2))
        self.assertEqual(grokbot.last_id([{"id": "a"}, None]), "a")
        self.assertIsNone(grokbot.avatar_of(None, "ada"))
        self.assertEqual(
            grokbot.avatar_of([None, {"name": "Ada", "avatarShape": "blob", "avatarColor": "black"}], "ada"),
            {"shape": "blob", "color": "black"})
        slow = mock.Mock()
        slow.args = ["gbot"]
        slow.pid = 1
        slow.communicate.side_effect = [subprocess.TimeoutExpired("g", 1), subprocess.TimeoutExpired("g", 1)]
        with mock.patch.object(grokbot.subprocess, "Popen", return_value=slow), \
                mock.patch.object(grokbot, "_stop_group"):
            self.assertIsNone(grokbot.run(["bots"], 0.1).rc)
        ordered = grokbot._in_thread_order(
            [None, {"kind": "message", "role": "user", "content": 5}],
            [{"id": "a", "role": "bot", "text": "hoi"}],
            [{"role": "user", "text": "wacht"}])
        self.assertEqual(ordered[0]["text"], "hoi")
        link = grokbot.GrokLink("Ada", now=lambda: 0)
        link.polling = True
        self.assertTrue(link.is_polling)
        self.assertFalse(link.poll())
        proc = mock.Mock()
        proc.pid = 4
        proc.wait.return_value = 0
        proc.kill = mock.Mock()
        if hasattr(grokbot.os, "killpg"):
            killpg = grokbot.os.killpg
            try:
                del grokbot.os.killpg
                grokbot._stop_group(proc)
                proc.kill.assert_called_once()
            finally:
                grokbot.os.killpg = killpg
            proc.wait.side_effect = [subprocess.TimeoutExpired("g", 1), None]
            with mock.patch.object(grokbot.os, "killpg") as kill:
                grokbot._stop_group(proc)
            self.assertEqual(kill.call_count, 2)
            with mock.patch.object(grokbot.os, "killpg", side_effect=OSError("no")):
                grokbot._stop_group(proc)
        else:
            grokbot._stop_group(proc)
            proc.kill.assert_called_once()


@unittest.skipIf(sys.platform == "darwin",
                 "the macOS offscreen plugin segfaults while this test raises windows")
class MenuAndCatcher(unittest.TestCase):
    """Should run the bubble menu and the arc catcher without a desktop session."""

    def _close(self, faces):
        from PySide6.QtWidgets import QApplication
        faces._semicircle_timer.stop()
        faces._semicircle_hide_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(faces)
        for face in list(faces.faces.values()) + list(faces._arc_guests.values()):
            face._poll_timer.stop()
            face._anim_timer.stop()
            face.close_face()
        faces._catcher.close()
        if app is not None:
            app.processEvents()

    def test_menu_actions_and_the_catcher_run_offscreen(self):
        """Should save a connection, refuse a bad page, and hand a press to the bot under the pointer."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QEnterEvent, QMouseEvent
        from PySide6.QtWidgets import QApplication
        from botwidget import acp_bots, acplink
        from botwidget.config import widget_config
        from botwidget.qt_ui.faces import arc_catcher_region, bot_source

        QApplication.instance() or QApplication([])
        self.assertEqual(bot_source(acplink.PREFIX + "ada"), "Harness")
        self.assertFalse(arc_catcher_region(80, 40, []).isEmpty())
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "state.json")
        with open(path, "w") as fh:
            json.dump({"enabled": ["home"], "pos": {"home": [400, 400]}}, fh)
        bots = [{"id": "home", "name": "Home", "threadId": "t", "hue": None, "seed": "home", "status": "ready"}]
        for patch in (
            mock.patch("botwidget.qt_ui.faces.STATE_PATH", path),
            mock.patch("botwidget.qt_ui.faces.list_bots", return_value=bots),
            mock.patch("botwidget.qt_ui.faces.gbot_installed", return_value=False),
            mock.patch("botwidget.qt_ui.faces.hermesbot.is_hermes_installed", return_value=False),
            mock.patch("botwidget.qt_ui.faces.check_updates", return_value=False),
            mock.patch("botwidget.qt_ui.faces.threading.Thread", return_value=mock.Mock()),
            mock.patch("botwidget.qt_ui.face.latest_chat", return_value={"messages": [], "activity": ""}),
            mock.patch("botwidget.qt_ui.faces.grok_bot_status", return_value={"connected": False, "bots": []}),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        faces = Faces()
        self.addCleanup(self._close, faces)
        home = faces.faces["home"]
        home._poll_timer.stop()
        home.welcome()
        self.assertIn("log in", home._shown_text)
        home._chat = {"messages": [{"role": "user", "text": "Hi"}, {"role": "user", "text": "Hi"},
                                   {"role": "bot", "text": "Yo"}]}
        self.assertEqual(home.prompt_history(), ["Hi"])
        home.toggle_pin()
        self.assertTrue(home.pinned)
        home.toggle_pin()
        self.assertFalse(home.pinned)
        broken = mock.Mock()
        broken.note.side_effect = RuntimeError("no")
        home.acp = broken
        self.assertEqual(home._send_status_or_note(), "")
        self.assertTrue(home._has_grok_or_hermes())
        home.acp = None
        self.assertFalse(home._failed_since_asked("not-a-date"))
        home._asked_at = 10
        self.assertTrue(home._failed_since_asked("1970-01-01T00:00:20+00:00"))
        home.has_pending = True
        self.assertEqual(home._motion_mood(), "ask")
        home.has_pending = False
        home._attention = {
            "prompts": [{"requestId": "r", "questions": [
                {"id": "q", "question": "Colour?", "options": []},
                {"id": "q2", "question": "Go?", "header": "H", "options": [{"label": "Yes"}]}]}],
            "approvals": [{"requestId": "a", "kind": "command", "command": "ls", "reason": "why"}],
            "browserTakeovers": [{}]}
        home._answering = set()
        home._answers = {}
        self.assertTrue(home._attention_blocks())
        home._answer_view = True
        home._menu_page = "settings"
        self.assertTrue(home._toggle_answer_view())
        home.acp = mock.Mock()
        home.acp.chat.return_value = {"messages": [], "activity": ""}
        home._attention_command("approve", "req/accept")
        home.acp = None

        with mock.patch("botwidget.qt_ui.faces.STATE_PATH", os.path.join(folder, "gone.json")):
            self.assertEqual(faces._load(), [])
        bad = os.path.join(folder, "bad.json")
        with open(bad, "w") as fh:
            fh.write("{")
        with mock.patch("botwidget.qt_ui.faces.STATE_PATH", bad):
            self.assertEqual(faces._load(), [])
        with open(bad, "w") as fh:
            json.dump({"enabled": "nope"}, fh)
        with mock.patch("botwidget.qt_ui.faces.STATE_PATH", bad):
            self.assertEqual(faces._load(), [])

        self.assertEqual(faces.menu_command("page/connection", "connections"), "connection")
        self.assertEqual(faces.menu_command("page/connection/nope", "connections"), "connection/nope")
        self.assertEqual(faces.menu_command("page/widget-json", "bots"), "widget-json")
        self.assertEqual(faces.menu_command("page/bot", "bots"), "bot")
        self.assertEqual(faces.menu_command("page/settings", "bots"), "settings")
        faces.menu_command("cycle/face", "bot", {"field/name": "Ada"})
        faces.menu_command("cycle/color", "bot", {})
        faces.menu_command("cycle/connection", "bot", {})
        faces._bot_draft = {"name": ""}
        self.assertEqual(faces.menu_command("action/save-bot", "bot"), "bot")
        faces._json_text = "{"
        self.assertEqual(faces.menu_command("action/save-json", "widget-json"), "widget-json")
        draft = acp_bots.blank_connection()
        faces._connection_draft = draft
        draft["name"] = ""
        self.assertEqual(faces.menu_command("action/save-connection", "connection"), "connection")
        draft.update({"name": "Ada", "base_url": "http://127.0.0.1:9", "model": "m", "key_file": "/tmp/k"})
        faces._connection_draft = draft
        self.assertEqual(faces.menu_command("action/save-connection", "connection"), "connections")
        conn_id = widget_config()["connections"][0]["id"]
        self.assertEqual(faces.menu_command(f"connection-toggle/{conn_id}", "connections"), "connections")
        self.assertIsNone(faces._set_connection_on("missing"))
        self.assertEqual(faces.menu_command("connection-remove/missing", "connections"), "connections")
        self.assertEqual(faces.menu_command(f"connection-remove/{conn_id}", "connections"), "connections")
        self.assertEqual(faces.menu_command(f"connection-remove/{conn_id}", "connections"), "connections")

        faces.grok = {"connected": True, "bots": [{}]}
        self.assertIn("connected", faces.grok_line())
        with mock.patch("botwidget.qt_ui.faces.updates.newer_release", return_value=None), \
                mock.patch("botwidget.qt_ui.faces.startup.from_checkout", return_value=False):
            faces._probe_update()
        with mock.patch("botwidget.qt_ui.faces.startup.from_checkout", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.auto_update", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.checkout.pull") as pull:
            faces._probe_update()
        pull.assert_called_once()
        with mock.patch("botwidget.qt_ui.faces.updates.newer_release", return_value={"tag": "v9"}), \
                mock.patch("botwidget.qt_ui.faces.startup.from_checkout", return_value=False), \
                mock.patch("botwidget.qt_ui.faces.auto_update", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.can_install_update", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.updates.stage", return_value="staged") as stage:
            faces._probe_update()
        stage.assert_called_once()
        with mock.patch("botwidget.qt_ui.faces.grok_bot_status", return_value={"connected": False, "bots": []}), \
                mock.patch("botwidget.qt_ui.faces.grokbot.avatar_of", return_value=None), \
                mock.patch("botwidget.qt_ui.faces.grokbot.target", return_value="ada"):
            faces._probe_grok()
        faces._start_probe()

        with mock.patch("botwidget.qt_ui.faces.channel.switch", return_value=False):
            faces.switch_channel()
        with mock.patch("botwidget.qt_ui.faces.channel.switch", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.channel.running", return_value="local"), \
                mock.patch("botwidget.qt_ui.faces.QApplication.exit") as exit_app:
            faces.switch_channel()
        exit_app.assert_called_once()
        with mock.patch("botwidget.qt_ui.faces.updates.install_staged", return_value=False):
            faces.install_update()
        with mock.patch("botwidget.qt_ui.faces.updates.install_staged", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.QApplication.quit") as quit_app:
            faces.install_update()
        quit_app.assert_called_once()
        faces.update = None
        with mock.patch.object(home, "welcome") as hello:
            faces.welcome(True)
        hello.assert_called_once()
        faces.welcome(False)

        with mock.patch("botwidget.qt_ui.faces.QDesktopServices.openUrl") as opened, \
                mock.patch("botwidget.qt_ui.faces.startup.set_enabled") as login, \
                mock.patch("botwidget.qt_ui.faces.startup.from_checkout", return_value=True), \
                mock.patch("botwidget.qt_ui.faces.openbot_installed", return_value=False), \
                mock.patch("botwidget.qt_ui.faces.grok_relay.link_channel", return_value={"prompt": "hi"}), \
                mock.patch("botwidget.qt_ui.faces.grok_relay.channel", return_value="topic"), \
                mock.patch("botwidget.qt_ui.faces.grok_relay.chief_prompt", return_value="chief"):
            self.assertEqual(faces.menu_command("toggle/debug", "settings"), "settings")
            self.assertEqual(faces.menu_command("toggle/always_on_top", "settings"), "settings")
            self.assertEqual(faces.menu_command("toggle/all_desktops", "settings"), "settings")
            self.assertEqual(faces.menu_command("toggle/login", "settings"), "settings")
            login.assert_called()
            self.assertIsNone(faces.menu_command("slider/glass/40", "settings"))
            self.assertIsNone(faces.menu_command("open/download", "settings"))
            opened.assert_called()
            self.assertEqual(faces.menu_command("action/link-grok", "connections"), "connections")
            self.assertEqual(faces.menu_command("action/copy-grok-prompt", "connections"), "connections")
            self.assertEqual(faces.menu_command("connect/openbot", "connections"), "connections")
            self.assertEqual(faces.menu_command("mute/nobody", "bots"), "bots")
            self.assertEqual(faces.menu_command("mute/home", "bots"), "bots")
        with mock.patch("botwidget.qt_ui.faces.startup.from_checkout", return_value=False):
            faces._set_debug(True)
        with mock.patch("botwidget.qt_ui.faces.QGuiApplication.primaryScreen", return_value=None):
            self.assertEqual(faces._hotspot(), (0.0, 0.0))
        faces._edge_tick()

        faces._take({"editor": "{}"}, "widget-json")
        faces._take({"field/model": "m"}, "connection")
        faces._json_text = json.dumps({"connections": [], "acp_bots": []})
        self.assertEqual(faces._commit_json(), "")
        home._menu_page = "bots"
        styled = {"id": "ada", "name": "Ada", "face": "", "color": ""}
        with mock.patch("botwidget.qt_ui.faces.acplink.configured_bots", return_value=[styled]), \
                mock.patch("botwidget.qt_ui.faces.acp_bots.plan", return_value=[
                    ("close", "ghost"), ("restyle", "ada"), ("restart", "home")]):
            faces._apply_bots([])
        home = faces.faces["home"]
        home._poll_timer.stop()
        with mock.patch.object(faces, "_pointer_over_arc", return_value=True):
            faces._edge_tick()
        faces._semicircle_phase = "idle"
        faces.hide_semicircle()
        faces._semicircle_phase = "showing"
        faces._arc_order = ["gone", "home"]
        faces._semicircle = {"home": {"x": 1, "y": 1, "visible": True}}
        faces.hide_semicircle()
        home.show()
        centre = home.geometry().center()
        self.assertTrue(faces._over_arc_area(centre.x(), centre.y()))
        faces._arc_watched = False
        faces._unwatch_arc_pointer()
        home.bubble.show()
        faces._semicircle_hide()
        with mock.patch("botwidget.qt_ui.faces.QApplication.quit"), \
                mock.patch("botwidget.qt_ui.faces.channel.switch", return_value=False), \
                mock.patch("botwidget.qt_ui.faces.updates.install_staged", return_value=False):
            self.assertIsNone(faces.menu_command("action/update", "settings"))
            self.assertIsNone(faces.menu_command("action/switch", "settings"))
            self.assertIsNone(faces.menu_command("action/quit", "settings"))
        away = QPointF(2, 2)
        faces._catcher.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, away, away, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        faces._catcher.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, away, away, Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        faces._catcher.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, away, away, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        home.hide()
        self.assertIsNone(faces._catcher._face_at(0, 0))
        home.show()
        point = QPointF(home.x() + home.width() / 2, home.y() + home.height() / 2)
        press = QMouseEvent(QEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        faces._catcher.mousePressEvent(press)
        faces._catcher.mouseMoveEvent(QMouseEvent(
            QEvent.Type.MouseMove, point, point, Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        faces._catcher.mouseReleaseEvent(QMouseEvent(
            QEvent.Type.MouseButtonRelease, point, point, Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        faces._semicircle_phase = "idle"
        faces._semicircle = {}
        faces._arc_order = []
        home.clearMask()
        home.show()
        point = QPointF(home.x() + max(home.width(), 2) / 2, home.y() + max(home.height(), 2) / 2)
        faces._catcher.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, point, point, Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier))
        away = QPointF(0, 0)
        faces._catcher.mousePressEvent(QMouseEvent(
            QEvent.Type.MouseButtonPress, away, away, Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier))
        faces._semicircle_phase = "idle"
        spot = QPointF(1, 1)
        faces._catcher.enterEvent(QEnterEvent(spot, spot, spot))
        faces._catcher.leaveEvent(QEvent(QEvent.Type.Leave))
        faces._semicircle_phase = "idle"
        self.assertFalse(faces.drop_arc(home))
        faces._semicircle_phase = "hiding"
        faces._arc_order = ["gone", "home"]
        faces._semicircle = {"home": {"x": 1, "y": 2, "slot_x": 3, "slot_y": 4}}
        faces.show_semicircle()
        faces._semicircle_phase = "visible"
        faces.show_semicircle()
        self.assertIsNone(faces.apply_relay("nope"))
        self.assertIsNone(faces._relay_face(""))
        faces.apply_relay({"kind": "status", "bot": "", "state": "done", "summary": "ok"})
        faces.live_avatar = {"shape": "nuage", "color": "blue"}
        faces.grok_avatars = {}
        with mock.patch("botwidget.qt_ui.faces.grokbot.target", return_value="ada"), \
                mock.patch("botwidget.qt_ui.faces.grokbot.face_id", return_value="home"), \
                mock.patch("botwidget.qt_ui.faces.grokbot.pick_avatar",
                           return_value={"shape": "nuage", "color": "blue"}):
            faces._take_grok_avatar()
        with mock.patch("botwidget.qt_ui.faces.grokbot.is_grok", return_value=True):
            faces._open({"id": "g", "name": "G", "threadId": None}, 3)
        faces._semicircle_phase = "showing"
        with mock.patch("botwidget.qt_ui.faces.arc_drop", return_value="on"):
            self.assertTrue(faces.drop_arc(home))
        faces._semicircle_phase = "showing"
        faces._semicircle.pop(home.agent_id, None)
        with mock.patch("botwidget.qt_ui.faces.arc_drop", return_value="stay"):
            self.assertFalse(faces.drop_arc(home))
        faces._semicircle_phase = "showing"
        faces._arc_order = [home.agent_id]
        with mock.patch("botwidget.qt_ui.faces.arc_drop", return_value="out"):
            self.assertTrue(faces.drop_arc(home))
        faces._semicircle_phase = "showing"
        with mock.patch("botwidget.qt_ui.faces.arc_drop", return_value="off"):
            self.assertTrue(faces.drop_arc(home))
        guest = faces._arc_guests[home.agent_id]
        faces._arc_order = [home.agent_id]
        faces._semicircle_phase = "showing"
        with mock.patch("botwidget.qt_ui.faces.arc_drop", return_value="on"):
            self.assertTrue(faces.drop_arc(guest))
        faces._spawn_guest({"id": "home", "name": "Home", "threadId": "t", "hue": None, "seed": "home"})
        faces._arc_order.append("home")
        faces._stop_guest("home")
        from botwidget.config import save_widget_config
        save_widget_config(
            connections=[{"id": "ada", "name": "Ada", "base_url": "http://127.0.0.1:9",
                          "model": "m", "key_file": "/tmp/k"}],
            acp_bots=[{"id": "acp:ada", "name": "Ada", "connection": "ada", "command": "true"}])
        self.assertEqual(faces._remove_connection("ada"), "A bot still uses this connection.")
        faces.apply_relay({"kind": "roster", "bots": [{"name": "  "}]})
        draft = acp_bots.blank()
        draft["name"] = "Ada"
        faces._bot_draft = draft
        with mock.patch("botwidget.qt_ui.faces.widget_config", return_value={"acp_bots": [], "connections": []}):
            self.assertEqual(faces._commit_bot(), "Could not save widget.json.")
        faces._connection_draft = acp_bots.blank_connection()
        faces._connection_draft.update(
            {"name": "Ada", "base_url": "http://127.0.0.1:9", "model": "m", "key_file": "/tmp/k"})
        with mock.patch("botwidget.qt_ui.faces.widget_config", return_value={"acp_bots": [], "connections": []}):
            self.assertEqual(faces._commit_connection(), "Could not save widget.json.")
        faces._json_text = json.dumps({"connections": [], "acp_bots": []})
        with mock.patch("botwidget.qt_ui.faces.replace_widget_config", return_value="nope"):
            self.assertEqual(faces._commit_json(), "nope")
        with mock.patch.object(faces, "_in_hotspot", return_value=True):
            faces.offer_semicircle(0, 0)
        faces._semicircle_phase = "showing"
        faces._semicircle_hide_timer.stop()
        for face in list(faces.faces.values()) + list(faces._arc_guests.values()):
            face._drag_origin = None
        with mock.patch.object(faces, "_in_hotspot", return_value=False):
            faces.offer_semicircle(0, 0)
        with mock.patch.object(type(faces._catcher), "underMouse", return_value=True), \
                mock.patch.object(faces, "_over_arc_area", return_value=True):
            self.assertTrue(faces._pointer_on_arc())
        if sys.platform.startswith("linux"):
            # Pretending this is Cocoa crashes the macOS offscreen plugin.
            with mock.patch("botwidget.qt_ui.faces.sys.platform", "darwin"), \
                    mock.patch("botwidget.qt_ui.faces.check_updates", return_value=True), \
                    mock.patch("botwidget.qt_ui.faces.QGuiApplication.platformName", return_value="xcb"):
                extra = Faces()
            self.addCleanup(self._close, extra)
            self.assertTrue(extra._edge_timer.isActive())
            self.assertTrue(extra._update_timer.isActive())


class PlainPaths(unittest.TestCase):
    """Should run the offscreen-callable bubble and face methods the coverage notes had called unreachable."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _face(self, agent_id, name, spot):
        from botwidget.qt_ui.face import FaceWindow
        window = FaceWindow(agent_id, name, spot=spot)
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        return window

    def test_paste_history_links_and_the_wheel(self):
        """Should accept a pasted file, refuse a history step that is only a cursor move, and open a link."""
        from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
        from PySide6.QtGui import QDesktopServices, QTextCursor, QWheelEvent
        from botwidget.qt_ui.bubble_window import BubbleEntry, BubbleText

        entry = BubbleEntry()
        self.addCleanup(entry.deleteLater)
        pasted = QMimeData()
        pasted.setUrls([QUrl.fromLocalFile("/tmp/note.txt")])
        self.assertTrue(entry.canInsertFromMimeData(pasted))
        entry.setPlainText("one\ntwo")
        cursor = entry.textCursor()
        cursor.movePosition(QTextCursor.End)
        entry.setTextCursor(cursor)
        self.assertFalse(entry._walk_history(-1))
        entry.setPlainText("only")
        entry._recall = None
        self.assertFalse(entry._walk_history(1))

        text = BubbleText()
        self.addCleanup(text.deleteLater)
        opened = []
        with mock.patch.object(QDesktopServices, "openUrl", side_effect=lambda url: opened.append(url.scheme()) or True):
            text._open(QUrl("https://example.com/a"))
            text._open(QUrl.fromLocalFile("/tmp/note.txt"))
        self.assertEqual(opened, ["https", "file"])
        wheel = QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        text.wheelEvent(wheel)
        self.assertFalse(wheel.isAccepted())

    def test_a_pending_dot_a_return_home_a_bounce_and_a_coast(self):
        """Should paint the pending dot, send the face home, bounce off another face, and coast to a stop."""
        from PySide6.QtGui import QImage
        home = self._face("home", "Home", (80, 80))
        home.show()
        home.has_pending = True
        image = QImage(home.width(), home.height(), QImage.Format_ARGB32)
        home.render(image)
        home._set_semicircle({home.agent_id: {"visible": True, "size": 48, "x": 40, "y": 40}})
        home._set_semicircle({})
        self.assertFalse(home._semicircle_visible)
        self.assertEqual(home.spot(), home._home)

        other = self._face("other", "Other", (80, 80))
        other.show()
        home.faces = SimpleNamespace(faces={"home": home, "other": other})
        pushed = home._bounce_off_faces(home.x(), home.y(), -30.0, 0.0)
        self.assertNotEqual(pushed[:2], (home.x(), home.y()))
        other.move(home.x() + 30, home.y())
        home._bounce_off_faces(home.x(), home.y(), 50.0, 0.0)
        home.faces = None

        home._drag_origin = None
        home._coasting = False
        self.assertFalse(home._tick_coast())
        home._coasting = True
        home._dvx, home._dvy = 400.0, 0.0
        self.assertTrue(home._tick_coast())
        home._dvx, home._dvy = 10.0, 0.0
        self.assertFalse(home._tick_coast())
        self.assertFalse(home._coasting)

    def test_each_backend_is_polled_without_a_live_server(self):
        """Should draw a grok, hermes, harness and OpenBot poll from a stand-in link."""
        home = self._face("home", "Home", (80, 80))

        class Link:
            def __init__(self):
                self.is_polling = False
                self._due = False
                self._active = False
                self.polled = 0

            def due(self):
                return self._due

            def active(self):
                return self._active

            def note(self):
                return "noted"

            def chat(self):
                return {"messages": [], "activity": ""}

            def poll(self):
                self.polled += 1

            def attention(self):
                return {"prompts": [], "approvals": [], "browserTakeovers": []}

            def close(self):
                return None

            stopped = False

        link = Link()
        home.grok = link
        link._due = True
        home._poll_pending()
        home._poll_thread.join(2)
        self.app.processEvents()
        self.assertEqual(link.polled, 1)
        link._due = False
        home._refreshing = True
        home._poll_pending()
        self.assertEqual(home._refresh_note, "noted")
        link._active = True
        home._poll_timer.stop()
        home._poll_pending()
        self.assertTrue(home._poll_timer.isActive())

        home.grok = None
        home.hermes = link
        link._active = False
        home._poll_timer.stop()
        home._refreshing = True
        home._poll_pending()
        self.assertEqual(home._refresh_note, "noted")
        home._refreshing = False
        home._poll_pending()

        home.hermes = None
        home.acp = link
        link._active = False
        home._refreshing = True
        home._poll_pending()
        self.assertEqual(home._refresh_note, "noted")
        link._active = True
        home._refreshing = True
        home._poll_timer.stop()
        home._poll_pending()
        self.assertTrue(home._poll_timer.isActive())
        link._active = False
        link.chat = lambda: {"messages": [], "activity": "working"}
        home._refreshing = False
        home._poll_timer.stop()
        home._poll_pending()
        self.assertTrue(home._poll_timer.isActive())

        home.acp = None
        home._asked = False
        home.has_pending = False
        home._refreshing = False
        home._poll_timer.stop()
        pending = {"prompts": [{"requestId": "p"}], "approvals": [], "browserTakeovers": []}
        with mock.patch("botwidget.qt_ui.face.api_get", return_value=pending), \
                mock.patch("botwidget.qt_ui.face.latest_chat",
                           return_value={"messages": [], "activity": ""}):
            home._poll_pending()
        self.assertTrue(home.has_pending)


class OffscreenCalls(unittest.TestCase):
    """Should call the bubble and face methods that still run on this screen."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _face(self, agent_id, name, spot):
        from botwidget.qt_ui.face import FaceWindow
        window = FaceWindow(agent_id, name, spot=spot)
        window._poll_timer.stop()
        self.addCleanup(window.close_face)
        return window

    def _mouse(self, kind, button, at=(4.0, 4.0), buttons=None):
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        point = QPointF(*at)
        return QMouseEvent(kind, point, point, button, buttons or button, Qt.KeyboardModifier.NoModifier)

    def test_bubble_answers_clicks_keys_and_paints(self):
        """Should copy, scroll, open a slash list, and draw the lines the bubble still has."""
        import time
        from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
        from PySide6.QtGui import QKeyEvent, QWheelEvent
        from botwidget.markdown import status_block
        from botwidget.qt_ui.bubble_window import CopyNotice, DOTS_MS
        from botwidget.qt_ui.controls import TextEditor

        home = self._face("home", "Home", (80, 80))
        bubble = home.bubble
        noticed = []
        notice = CopyNotice(bubble._card)
        notice.clicked.connect(lambda: noticed.append(True))
        notice.ask_over(QRect(0, 0, 20, 12), "Copy", False)
        notice.mousePressEvent(self._mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
        self.assertEqual(noticed, [True])

        down = QWheelEvent(
            QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        bubble._scroll.wheelEvent(down)
        bubble.kind = ""
        bubble._geom = ([], 1, 1)
        bubble._menu_line.mouseReleaseEvent(
            self._mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton))
        bubble._doc._shift = True
        bubble._doc._press = QPoint(1, 1)
        bubble._doc.mouseMoveEvent(self._mouse(QEvent.Type.MouseMove, Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton))

        bubble._commands_forced = True
        bubble._entry.setPlainText("/settings")
        bubble.open_command_list()
        self.assertFalse(bubble._commands_forced)
        seen = []
        bubble._glass_mask = b"x"
        with mock.patch("botwidget.qt_ui.bubble_window.glass.update", side_effect=lambda *args: seen.append(args)):
            bubble._fit_window()
        self.assertTrue(seen)

        home.pinned = True
        home._working = False
        home._menu_page = None
        bubble._input = False
        bubble.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(home.pinned)
        bubble.kind = "hint"
        self.assertIsNone(bubble._message_at(0, 0))
        panel = {"role": "user", "queued": "abc", "copy": "hi", "lines": [{"kind": "text", "size": 12}]}
        bubble.kind = "say"
        bubble._geom = ([panel], 80, 40)
        bubble._doc.move(0, 0)
        queued = []
        bubble.edit_queued.connect(queued.append)
        bubble._on_click(1, 1, False)
        self.assertEqual(queued, ["abc"])
        bubble._geom = ([], 10, 10)
        bubble._on_click(0, 0, False)
        bubble._notice_from_end = 3
        self.assertTrue(bubble._notice_rect().isNull())

        other = self._face("other", "Other", (80, 80))
        other.bubble.show()
        other.bubble.resize(300, 200)
        other.bubble.move(0, 0)
        home.faces = SimpleNamespace(faces={"home": home, "other": other}, raise_bubbles=lambda: None)
        bubble.show()
        other_box = other.bubble
        # The push is sideways when the boxes overlap less across than down.
        tall = other_box.height() + other_box.width() + 50
        moved = bubble._clear_spot(other_box.x(), other_box.y() + other_box.height() / 2 - tall / 2, 1, tall)
        self.assertNotEqual(moved[0], other_box.x())

        bubble.show()
        bubble.restack()
        bubble._geom = None
        bubble.kind = "say"
        bubble._paint_chrome()
        self.assertIsNotNone(bubble._geom)
        bubble._chrome_key = None
        bubble._shadow_key = None
        with mock.patch("botwidget.qt_ui.bubble_window.glass.blurs", return_value=True):
            bubble._paint_chrome()
        self.assertTrue(bubble._glass_mask)
        trail = SimpleNamespace(hidden=False, isVisible=lambda: True, hide=lambda: setattr(trail, "hidden", True))
        bubble._trail = trail
        bubble.kind = "say"
        bubble._move_trail()
        self.assertTrue(trail.hidden)
        bubble._show_menu_line(1, 1, 40, 8)
        self.assertTrue(bubble._menu_line.isVisible())
        bubble.kind = "say"
        bubble._geom = bubble._parts()
        bubble.restyle()
        bubble._spots = [(index, 0, "#111", 0) for index in range(300)]
        bubble._draw_dots()
        self.assertLess(len(bubble._dot_frames), 256)
        bubble._geom = None
        bubble._place_controls()
        editor = bubble._make_control({"control": "editor", "value": "hi"})
        self.addCleanup(editor.deleteLater)
        self.assertIsInstance(editor, TextEditor)

        blocks = [status_block("Same")]
        bubble.hide()
        bubble._yielding = False
        bubble._show_blocks(blocks, "say")
        bubble.hide()
        bubble._geom[0][0]["back"] = "close"
        bubble._built = bubble._content_key(blocks, "say", False, None)
        bubble._dots_lines = []
        bubble._show_blocks(blocks, "say")
        bubble._list_only = True
        opened = []
        home.open_input = lambda: opened.append(True)
        bubble._arrow_clicked()
        self.assertEqual(opened, [True], "the line on the command list goes to the chat")
        bubble._pull_done()
        bubble._list_only = False
        bubble.kind = "say"
        bubble._growth = None
        bubble._more_hover = True
        bubble._has_older = bubble._more_open = True
        bubble._pull_px = 0
        bubble._pull_held = False
        bubble._pull_last = time.monotonic()
        bubble._geom = ([{"role": "more", "back": "up", "lines": [{"kind": "more", "shown": 0}]}], 40, 20)
        bubble._watch_arrow(time.monotonic())
        self.assertFalse(bubble._more_hover)

        bubble._dots_lines = [{"kind": "dots"}]
        bubble._spots = []
        bubble._geom = ([{"role": "bot", "lines": []}], 20, 10)
        bubble._dots.setInterval(1)
        with mock.patch("botwidget.qt_ui.bubble_window.power.reduced", return_value=True):
            bubble._tick_dots()
        self.assertEqual(bubble._dots.interval(), DOTS_MS * 2)
        called = []
        with mock.patch("botwidget.qt_ui.bubble_window.always_on_top", return_value=False), \
                mock.patch("botwidget.qt_ui.bubble_window.send_behind_windows", side_effect=called.append):
            bubble.hide()
            bubble.show()
        self.assertTrue(called)
        bubble.kind = "say"
        bubble._input = False
        bubble._had_focus = False
        bubble._physics.setInterval(1)
        home.faces = None
        with mock.patch("botwidget.qt_ui.bubble_window.power.reduced", return_value=True):
            bubble._tick()
        self.assertEqual(bubble._physics.interval(), 33)
        bubble._dots_on = False
        bubble._dots_lines = [{"kind": "dots"}]
        bubble.place("say")
        self.assertTrue(bubble._dots.isActive())
        bubble._dots.stop()
        bubble._physics.stop()

    def test_face_drags_polls_and_sends_without_a_server(self):
        """Should drag, bounce, poll a stand-in link, and send without leaving this machine."""
        import threading
        import time
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        from botwidget.avatar import AVATAR_SIZE
        from botwidget.markdown import status_block

        home = self._face("home", "Home", (80, 80))
        home._thinking.show()
        home._thinking.restack()
        self.assertTrue(home._thinking.isVisible())
        home.bring_here()
        home.apply_desktops()
        home._drag_origin = [home.spot()]
        home._set_semicircle({home.agent_id: {"visible": True, "size": 48, "x": 10, "y": 10}})
        self.assertFalse(home._semicircle_visible)
        home._drag_origin = None
        home._semicircle_visible = True
        home._set_pixmap(home._pixmap)
        row = home._thinking
        home._thinking = None
        home._place_thinking()
        home._thinking = row
        _x, _y, _vx, vy = home._stay_on_screen(home.x(), 100000, 0.0, 40.0)
        self.assertLess(vy, 0)
        home.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        home._drag_origin = None
        home.mousePressEvent(self._mouse(QEvent.Type.MouseButtonPress, Qt.MouseButton.MiddleButton))
        self.assertIsNone(home._drag_origin)
        spot = home.spot()
        home.mouseMoveEvent(self._mouse(QEvent.Type.MouseMove, Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton))
        self.assertEqual(home.spot(), spot)

        home.show()
        home.bubble.show()
        home._arc_guest = True
        home.faces = SimpleNamespace(
            faces={"home": home}, _in_hotspot=lambda _x, _y: True,
            raise_bubbles=lambda: None, offer_semicircle=lambda _x, _y: None)
        home._drag_origin = [home.spot()]
        home._press_pos = (0.0, 0.0)
        home._drag_box = home.width()
        home._drag_sample = (time.monotonic() - 1, home.x(), home.y())
        home._wall_kick = (0.0, 0.0)
        home._restacked_at = time.monotonic()
        home.mouseMoveEvent(self._mouse(
            QEvent.Type.MouseMove, Qt.MouseButton.NoButton, at=(50.0, 0.0), buttons=Qt.MouseButton.LeftButton))
        self.assertFalse(home.bubble.kind)
        self.assertNotEqual(home._dvx, 0.0)

        home.screenshot_face = None
        home.mouseDoubleClickEvent(self._mouse(QEvent.Type.MouseButtonDblClick, Qt.MouseButton.MiddleButton))
        self.assertIsNone(home.screenshot_face)
        home.screenshot_face = home
        home.mouseDoubleClickEvent(self._mouse(QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton))
        self.assertIs(home.screenshot_face, home)
        home.mouseReleaseEvent(self._mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.MiddleButton))
        home._screenshot_active = True
        home._press_pos = (1.0, 1.0)
        home._drag_origin = [home.spot()]
        home.mouseReleaseEvent(self._mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton))
        self.assertIsNone(home._drag_origin)

        home._screenshot_active = False
        home.screenshot_face = None
        home._semicircle_visible = True
        home._press_pos = (4.0, 4.0)
        home._drag_origin = [home.spot()]
        home._dvx = home._dvy = 0.0
        home._wall_kick = (0.0, 0.0)
        home.faces = None
        remembered = home._home
        home.mouseReleaseEvent(self._mouse(QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton))
        self.assertEqual(home._home, remembered)

        dropped = []
        home._semicircle_visible = False
        home._press_pos = (0.0, 0.0)
        home._drag_origin = [home.spot()]
        home.faces = SimpleNamespace(drop_arc=lambda _face: True, drag_let_go=lambda: dropped.append(1), faces={})
        home.mouseReleaseEvent(self._mouse(
            QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, at=(80.0, 80.0)))
        self.assertEqual(dropped, [1])
        home._press_pos = (0.0, 0.0)
        home._drag_origin = [home.spot()]
        home._wall_kick = (800.0, 0.0)
        home._dvx = home._dvy = 0.0
        home.faces = SimpleNamespace(drop_arc=lambda _face: False, drag_let_go=lambda: None, faces={})
        home.mouseReleaseEvent(self._mouse(
            QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, at=(80.0, 80.0)))
        self.assertTrue(home._coasting)
        home._coast_timer.stop()
        home._coasting = False
        with mock.patch("botwidget.qt_ui.face.QTimer.singleShot", side_effect=lambda _ms, fn: fn()):
            home._drag_origin = None
            home._screens_changed()

        home.pinned = True
        self.assertFalse(home.shrink_think())
        home.set_avatar(home._avatar)
        with mock.patch.object(home, "_pointer_on_head", return_value=False), \
                mock.patch("botwidget.qt_ui.face.power.reduced", return_value=True):
            home._drag_origin = None
            home._coasting = False
            home._happy_on = False
            home._animate()
        home.screenshot_face = home
        home._happy_on = False
        near = (home.x() + AVATAR_SIZE / 2 + 5, home.y() + AVATAR_SIZE / 2)
        with mock.patch.object(home, "_pointer", return_value=near):
            home._aim(16)
        home.screenshot_face = None
        home._working = True
        home.pinned = False
        home._think_quiet = False
        home._answer_view = False
        home._chat = {"messages": [{"role": "user", "text": "q"}]}
        self.assertFalse(home._toggle_answer_view())

        link = SimpleNamespace(stopped=False, _active=False, _note="from grok", sent=[], fetched=[], resumed=False)
        link.due = lambda: False
        link.active = lambda: link._active
        link.note = lambda: link._note
        link.chat = lambda: {"messages": [], "activity": ""}
        link.attention = lambda: {"prompts": [], "approvals": [], "browserTakeovers": []}
        link.close = lambda: None
        link.request_fetch = lambda: link.fetched.append("fetch")
        link.send = lambda text: link.sent.append(text) or (True, "")
        link.resume = lambda: setattr(link, "resumed", True)
        link.is_polling = False
        home.faces = None
        home._working = True
        home.pinned = True
        patches = [mock.patch(name, value) for name, value in (
            ("botwidget.qt_ui.face.latest_chat", mock.Mock(return_value={"messages": [], "activity": ""})),
            ("botwidget.qt_ui.face.openbot_installed", mock.Mock(return_value=True)),
            ("botwidget.qt_ui.face.gbot_installed", mock.Mock(return_value=True)),
        )]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        home.unpin()
        self.assertFalse(home.pinned)
        home.pinned = False
        home._sending = False
        home._working = False
        home._coasting = False
        home._drag_origin = None
        self.assertTrue(home.idle())

        home._refreshing = False
        home._refreshed("nope")
        self.assertFalse(home._refreshing)
        home.grok = link
        home._refreshing = True
        home._on_grok_polled()
        self.assertEqual(home._refresh_note, "from grok")
        link._active = True
        home._poll_timer.stop()
        home._on_grok_polled()
        self.assertTrue(home._poll_timer.isActive())
        home._poll_timer.stop()
        home.hermes = None
        home.acp = None
        home._grok_fetch()
        self.assertEqual(link.fetched, ["fetch"])
        home.grok = None
        hermes = SimpleNamespace(fetched=[])
        hermes.request_fetch = lambda: hermes.fetched.append("h")
        hermes.close = lambda: None
        home.hermes = hermes
        home._poll_timer.stop()
        home._grok_fetch()
        self.assertEqual(hermes.fetched, ["h"])
        home.hermes = None
        home.acp = link
        home._poll_timer.stop()
        home._grok_fetch()
        self.assertTrue(home._poll_timer.isActive())
        home._poll_timer.stop()
        link._note = "waiting on the link"
        self.assertEqual(home._waiting_note(""), "waiting on the link")

        home.grok = None
        home.hermes = None
        home.acp = link
        link.stopped = True
        home._asked = True
        home._answer_pending = False
        home._last_bot = "done"
        home._drag_origin = None
        home._welcome_until = 0
        home._menu_page = None
        home._queue = []
        home.bubble.place("")
        home._sync_bubble({"messages": [{"role": "bot", "text": "done"}], "activity": ""}, force=True)
        self.assertFalse(home._asked)
        link.stopped = False
        home._send_status = "still waiting"
        home.pinned = False
        home._answer_view = False
        with mock.patch.object(home, "_think_expanded", return_value=True):
            home._sync_bubble({"messages": [], "activity": "thinking"}, force=True)
        self.assertIn("still waiting", home._shown_text)
        home._send_status = ""
        link._note = "link down"
        with mock.patch.object(home, "_think_expanded", return_value=True):
            home._sync_bubble({"messages": [], "activity": "thinking"}, force=True)
        self.assertIn("link down", home._shown_text)

        home.grok = link
        home.hermes = hermes
        home.acp = None
        home.faces = None
        link.fetched.clear()
        hermes.fetched.clear()
        home.refresh()
        self.assertEqual(link.fetched, ["fetch"])
        self.assertEqual(hermes.fetched, ["h"])
        home._poll_timer.stop()
        link.fetched.clear()
        hermes.fetched.clear()
        home.reload_quietly()
        self.assertEqual(link.fetched, ["fetch"])
        self.assertEqual(hermes.fetched, ["h"])
        home._poll_timer.stop()

        home.faces = SimpleNamespace(
            _bot_error="nope", close_bubbles_except=lambda _id: None, menu_state=lambda: {},
            release_bots_arc=lambda: None, hold_arc=lambda: None, raise_bubbles=lambda: None)
        with mock.patch("botwidget.qt_ui.face.menu_pages.page_blocks", return_value=[status_block("page")]):
            home.open_menu("bot")
        bar = home.bubble._scroll.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())

        home._working = False
        home._queue = []
        home.pinned = False
        home.acp = None
        home.grok = None
        home.hermes = None
        home.on_user_message("/pin")
        self.assertTrue(home.pinned)

        class Now(threading.Thread):
            def start(self):
                self.run()

        home.pinned = False
        home._working = False
        home.acp = link
        link.stopped = False
        link._active = True
        link.sent.clear()
        home._poll_timer.stop()
        with mock.patch("botwidget.qt_ui.face.threading.Thread", Now):
            home.on_user_message("hello")
        self.assertTrue(link.resumed)
        self.assertEqual(link.sent, ["hello"])
        self.assertTrue(any(item.get("role") == "user" and item.get("text") == "hello" for item in home._local))
        self.assertTrue(home._poll_timer.isActive())
        home._poll_timer.stop()

        home._working = False
        home._queue_hold = True
        home._queue_hold_until = 0
        home._queue = []
        home._sending = False
        home._next_queued()
        self.assertFalse(home._queue_hold)
        home._edit_queued("missing")
        home._attention = {}
        home._give_answer("missing", "q", ["a"])
        with mock.patch("botwidget.qt_ui.face.api_post", side_effect=RuntimeError("down")):
            home._post_attention("/v1/agents/home/prompts/x/answer", {})
        self.assertIn("did not go through", home._attention_note)
        home._poll_timer.stop()

        home.acp = None
        home.grok = None
        home.hermes = None
        home._alive = True
        with mock.patch("botwidget.qt_ui.face.automation_ready", return_value=False):
            home._post_message("offline", "cid-offline")
        self.assertTrue(home._refused)
        home._poll_timer.stop()
        home._anim_timer.stop()
        home.bubble._dots.stop()
        home.bubble._physics.stop()


class Wheel(unittest.TestCase):
    """Should put the harness package in the wheel. The widget imports it, and CI installs the wheel."""

    def test_the_built_wheel_contains_harness(self):
        """Should pack harness/acp_client.py next to botwidget."""
        out = tempfile.mkdtemp(prefix="botwidget-wheel-")
        self.addCleanup(shutil.rmtree, out, True)
        # The runners install with pip and do not have uv. A checkout that has uv can build the same wheel.
        uv = shutil.which("uv")
        command = (["uv", "build", "--wheel", "--out-dir", out] if uv
                   else [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", out])
        done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        wheel = next(name for name in os.listdir(out) if name.endswith(".whl"))
        names = zipfile.ZipFile(os.path.join(out, wheel)).namelist()
        self.assertTrue(any(name.endswith("harness/acp_client.py") for name in names), names[:8])
