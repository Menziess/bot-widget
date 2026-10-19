"""Ontwikkelmodus: start de widget en start hem opnieuw zodra een .py-bestand verandert."""

import os
import signal
import subprocess
import sys
import tempfile
import time

from botwidget.instance import ensure_single_instance

PACKAGE = os.path.dirname(os.path.abspath(__file__))
DEV_PIDFILE = os.path.join(tempfile.gettempdir(), "bot_widget_dev.pid")
POLL_S = 0.5


def snapshot(folder: str = PACKAGE) -> dict:
    """Pad en wijzigingstijd van elk .py-bestand onder folder."""
    seen = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                seen[path] = os.stat(path).st_mtime_ns
    return seen


def start() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "botwidget"])


def stop(child: subprocess.Popen | None, wait: float = 3.0):
    if child is None or child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(wait)
    except subprocess.TimeoutExpired:
        child.kill()


def run(folder: str = PACKAGE, poll: float = POLL_S):
    """Houdt de widget draaiend met de nieuwste code. Een crash wacht op de volgende wijziging."""
    ensure_single_instance(DEV_PIDFILE, (b"--dev",))
    child = start()
    seen = snapshot(folder)
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
            if current != seen:
                seen, waiting = current, False
                print("code changed, restarting", flush=True)
                stop(child)
                child = start()
            elif child.poll() is not None and not waiting:
                waiting = True
                print(f"widget exited with {child.returncode}; waiting for a change", flush=True)
    finally:
        stop(child)
