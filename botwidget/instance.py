"""Eén widget tegelijk: een eerder gestarte widget wordt eerst gestopt."""

import atexit
import os
import signal
import tempfile
import time

from botwidget.config import read_file
from botwidget.system.current import process_cmdline

PIDFILE = os.path.join(tempfile.gettempdir(), "bot_widget.pid")
# De gebundelde app heet "Bot Widget"; de andere namen zijn de losse start via Python.
LAUNCHERS = (b"bot_widget.py", b"botwidget", b"Bot Widget")


def looks_like_widget(cmdline: bytes, markers: tuple = LAUNCHERS) -> bool:
    return any(name in cmdline for name in markers)


def ensure_single_instance(pidfile: str = PIDFILE, markers: tuple = LAUNCHERS):
    """Stop een eerder gestarte widget, zodat er één venster overblijft."""
    try:
        old = int(read_file(pidfile))
    except ValueError:
        old = None
    if old and old != os.getpid() and looks_like_widget(process_cmdline(old), markers):
        os.kill(old, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            if not process_cmdline(old):
                break
        else:
            os.kill(old, signal.SIGKILL)
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(pidfile) and os.remove(pidfile))
