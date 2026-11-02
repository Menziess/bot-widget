"""Dev mode: start the widget and restart it as soon as a .py file changes."""

import os
import signal
import subprocess
import sys
import tempfile
import time

from botwidget.channel import HANDOVER_EXIT
from botwidget.instance import ensure_single_instance

PACKAGE = os.path.dirname(os.path.abspath(__file__))
DEV_PIDFILE = os.path.join(tempfile.gettempdir(), "bot_widget_dev.pid")
POLL_S = 0.5


def snapshot(folder: str = PACKAGE) -> dict:
    """Path and modification time of every .py file under folder."""
    seen = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                seen[path] = os.stat(path).st_mtime_ns
    return seen


def start(extra: list = ()) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "botwidget", *extra])


def needs_restart(current: dict, seen: dict, started_ns: int) -> bool:
    """A .py file appeared, disappeared, or was written after this child started.

    The snapshot taken after start() used to count a write during startup as already
    seen, so the child kept the code it had imported a moment earlier.
    """
    return current != seen or any(mtime > started_ns for mtime in current.values())


def launched(accepted: dict) -> int:
    """The instant this child may claim those files. A mtime already in the snapshot is not a new write."""
    newest = max(accepted.values(), default=0)
    return max(time.time_ns(), newest)


def stop(child: subprocess.Popen | None, wait: float = 3.0):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(wait)
    except subprocess.TimeoutExpired:
        child.kill()


def run(folder: str = PACKAGE, poll: float = POLL_S):
    """Keeps the widget running with the newest code. A crash waits for the next change."""
    ensure_single_instance(DEV_PIDFILE, (b"--dev",))
    extra = ["--keep-login"] if "--keep-login" in sys.argv else []
    seen = snapshot(folder)
    started = launched(seen)
    child = start(extra)
    waiting = False

    def goodbye(*_):
        stop(child)
        sys.exit(0)

    signal.signal(signal.SIGTERM, goodbye)
    print(f"botwidget --dev: watching {folder}", flush=True)
    try:
        while True:
            time.sleep(poll)
            current = snapshot(folder)
            if needs_restart(current, seen, started):
                seen, waiting = current, False
                print("code changed, restarting", flush=True)
                stop(child)
                started = launched(seen)
                child = start(extra)
            elif child.poll() == HANDOVER_EXIT:
                print("handed over to the stable version", flush=True)
                return
            elif child.poll() is not None and not waiting:
                waiting = True
                print(f"widget exited with {child.returncode}; waiting for a change", flush=True)
    finally:
        stop(child)
