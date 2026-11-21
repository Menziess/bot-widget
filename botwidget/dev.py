"""Dev mode: start the widget and restart it as soon as a .py file changes."""

import os
import signal
import subprocess
import sys
import tempfile
import time

from botwidget.channel import HANDOVER_EXIT
from botwidget.instance import ensure_single_instance
from botwidget.pc_update import fast_forward
from botwidget.supervisor import retry_delay

PACKAGE = os.path.dirname(os.path.abspath(__file__))
DEV_PIDFILE = os.path.join(tempfile.gettempdir(), "bot_widget_dev.pid")
DEV_WANT_BUSY = os.path.join(tempfile.gettempdir(), "bot_widget_dev.want_busy")
DEV_BUSY = os.path.join(tempfile.gettempdir(), "bot_widget_dev.busy")
POLL_S = 0.5


def note_tool(active: bool) -> None:
    """The widget asks the dev loop to treat a tool as in progress."""
    path = os.environ.get("BOTWIDGET_DEV_WANT") or DEV_WANT_BUSY
    if active:
        open(path, "a").close()
        return
    if os.path.exists(path):
        os.remove(path)


def publish_busy() -> bool:
    """Copy the widget's tool flag into the busy file the updater reads. The loop owns that file."""
    want = os.environ.get("BOTWIDGET_DEV_WANT") or DEV_WANT_BUSY
    busy = os.environ.get("BOTWIDGET_DEV_BUSY") or DEV_BUSY
    on = os.path.exists(want)
    if on:
        open(busy, "a").close()
    elif os.path.exists(busy):
        os.remove(busy)
    return on


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


def on_child_exit(returncode: int | None) -> str:
    """A handover stops. Any other exit, including a SyntaxError, is retried."""
    if returncode == HANDOVER_EXIT:
        return "stop"
    return "retry"


def prepare_retry(checkout: str, attempt: int) -> tuple[str, float]:
    """Fast-forward when the checkout is clean, then say how long to wait."""
    return fast_forward(checkout), retry_delay(attempt)


def run(folder: str = PACKAGE, poll: float = POLL_S, checkout: str | None = None):
    """Keeps the widget running with the newest code. A crash retries with backoff after a fast-forward."""
    ensure_single_instance(DEV_PIDFILE, (b"--dev",))
    extra = [flag for flag in ("--keep-login", "--demo") if flag in sys.argv]
    seen = snapshot(folder)
    started = launched(seen)
    child = start(extra)
    attempt = 0
    restart_now = False

    def goodbye(*_):
        stop(child)
        sys.exit(0)

    def poke(*_):
        nonlocal restart_now
        restart_now = True

    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, poke)
    signal.signal(signal.SIGTERM, goodbye)
    root = checkout or os.path.dirname(folder)
    print(f"botwidget --dev: watching {folder}", flush=True)
    try:
        while True:
            publish_busy()
            time.sleep(poll)
            current = snapshot(folder)
            code = child.poll()
            if restart_now or needs_restart(current, seen, started):
                restart_now = False
                seen, attempt = current, 0
                print("code changed, restarting", flush=True)
                stop(child)
                started = launched(seen)
                child = start(extra)
            elif code == HANDOVER_EXIT:
                print("handed over to the stable version", flush=True)
                return
            elif code is not None and on_child_exit(code) == "retry":
                pulled, delay = prepare_retry(root, attempt)
                attempt += 1
                print(f"widget exited with {code}; {pulled}; retry in {delay:.0f}s", flush=True)
                time.sleep(delay)
                seen = snapshot(folder)
                started = launched(seen)
                child = start(extra)
    finally:
        stop(child)
