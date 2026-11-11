# Ensure tests always run in offscreen mode, even when the desktop session
# already exports QT_QPA_PLATFORM (setdefault would then be a no-op)
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Nothing in a test may reach the real desktop of the person running it: bringing the app to the front took the
# keyboard away from whatever they were typing in, and a notification played a sound.
from botwidget.system import current as _current  # noqa: E402

for _name in ("activate_app", "play_notification", "hide_from_dock"):
    setattr(_current, _name, lambda *args, **kwargs: None)
    setattr(_current._os, _name, lambda *args, **kwargs: None)

# An offscreen window has no native view: on macOS these two dereference it and crash the whole run. Only the
# `current` aliases are replaced, so the tests of the macOS module itself still reach the real functions. Only on
# macOS: the other systems have run them on offscreen windows without trouble, and the tests were written with them.
import sys  # noqa: E402

if sys.platform == "darwin":
    for _name in ("send_behind_windows", "raise_window"):
        setattr(_current, _name, lambda *args, **kwargs: None)

# Tests that pretend to run on X11 must not call the real desktop functions of this system on an offscreen window.
from botwidget.qt_ui import desktops  # noqa: E402

desktops.set_desktops = lambda *args: None
desktops.is_shown_here = lambda *args: True
desktops.on_active_space = lambda *args: True
desktops.move_to_active_space = lambda *args: None

# The widget's own settings and drafts of a test go to a folder of its own, never to the widget.json of the person
# running it.
import tempfile  # noqa: E402

# macOS temp folders sit behind a symlink (/var -> /private/var); the workspace code compares real paths.
tempfile.tempdir = os.path.realpath(tempfile.gettempdir())

from botwidget import config as _config  # noqa: E402

_folder = tempfile.mkdtemp(prefix="botwidget-tests-")
_config.CONFIG_PATH = os.path.join(_folder, "widget.json")

# A test that answers a question must not write to the approval log of the person running it.
from harness import approvals as _approvals  # noqa: E402

_approvals.PATH = os.path.join(_folder, "approvals.jsonl")

# ...and what a bot remembered must not leak into a test: a stored memory adds a message to every built context.
os.environ["HARNESS_MEMORY_DIR"] = os.path.join(_folder, "memory")

# ...and each test starts with no widget.json at all: a draft or setting of one test must not reach the next.
import unittest  # noqa: E402

_run = unittest.TestCase.run


def _run_clean(self, result=None):
    try:
        os.remove(_config.CONFIG_PATH)
    except OSError:
        pass
    return _run(self, result)


unittest.TestCase.run = _run_clean

# Whether the computer that runs the tests is on its battery must not change what they find.
from botwidget import power as _power  # noqa: E402

_power._probe = lambda: False

# The grace a bubble gets after the pointer left depends on time and speed. Tests that are not about it expect the
# bubble to go when the pointer is gone; the ones about the grace set it back.
from botwidget.qt_ui import bubble_window as _bubble_window  # noqa: E402

_bubble_window.LEAVE_MAX_S = 0.0
