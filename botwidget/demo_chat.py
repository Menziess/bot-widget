"""The /demo command. The six tasks go out through the chat. Code checks what they left behind.

This does not run the in-process demo that performs each task itself.
"""

import os
import subprocess
import sys

from botwidget.demo_check import (
    Board, a11y_read, browser_tab, file_readback, repair_result, script_exit, write_board,
)
from botwidget.demo_run import BOARD, LABELS, ROOT

PROMPTS = {
    "browser": (
        "Demo task browser. Do not open, close, or switch any Chrome tab. "
        "Reply with exactly: browser noted"
    ),
    "files": (
        "Demo task files. Write the file /tmp/t-demo/work/note.txt so its exact bytes are "
        "demo-note followed by one newline. Do not write any other path."
    ),
    "script": (
        "Demo task script. Write /tmp/t-demo/work/hello.py so it prints demo-ok, then run "
        "that file with python. Do not touch any path outside /tmp/t-demo."
    ),
    "process": (
        "Demo task process. Start a python process that sleeps for 30 seconds, confirm it is "
        "running, then stop that process. When it has stopped, write /tmp/t-demo/work/process.txt "
        "with the exact bytes stopped and one newline. Keep every file under /tmp/t-demo."
    ),
    "accessibility": (
        "Demo task accessibility. Which applications are open on my desktop? "
        "Use your accessibility tool. Leave query empty. Do not invent names."
    ),
    "repair": (
        "Demo task repair. The file /tmp/t-demo/repair/test_seed.py is a failing unittest. "
        "Change only that file so `python -m unittest test_seed` passes when run with the "
        "working directory /tmp/t-demo/repair. Do not touch any other path."
    ),
}


def dev_running() -> bool:
    """The --dev supervisor's child does not see --dev on its own command line."""
    return os.environ.get("BOTWIDGET_DEV") == "1" or "--dev" in sys.argv[1:]


def check(key: str) -> dict:
    """Read the outcome. Does not perform the task."""
    if key == "files":
        return file_readback(os.path.join(ROOT, "work", "note.txt"), "demo-note\n")
    if key == "script":
        path = os.path.join(ROOT, "work", "hello.py")
        if not os.path.exists(path):
            return {"checked": True, "ok": False, "detail": "missing"}
        done = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=30)
        evidence = script_exit(done.returncode)
        evidence["ok"] = evidence["ok"] and "demo-ok" in done.stdout
        return evidence
    if key == "repair":
        folder = os.path.join(ROOT, "repair")
        if not os.path.exists(os.path.join(folder, "test_seed.py")):
            return {"checked": True, "ok": False, "detail": "missing"}
        done = subprocess.run(
            [sys.executable, "-m", "unittest", "test_seed"], cwd=folder, capture_output=True, text=True)
        return repair_result(done.returncode)
    if key == "accessibility":
        from botwidget.system.a11y import accessibility, application_names
        row = accessibility()
        names = application_names() if row.get("available") else []
        text = f"available: {'yes' if row.get('available') else 'no'}\napplications: {', '.join(names)}"
        return a11y_read(text)
    if key == "process":
        return file_readback(os.path.join(ROOT, "work", "process.txt"), "stopped\n")
    if key == "browser":
        return browser_tab(False, "", False, False, "not opened by the checker")
    return {"checked": True, "ok": False, "detail": "not seen from here"}


def publish(board: Board) -> None:
    rows = []
    for key, label in LABELS:
        row = board.rows.get(key, {"ticked": False, "detail": "waiting", "blocked": ""})
        detail = row.get("blocked") or row.get("detail") or ""
        rows.append({"id": key, "label": label, "ticked": bool(row.get("ticked")), "detail": detail})
    write_board(BOARD, rows)


class Session:
    """Send one prompt when the chat is idle, then tick that task from check()."""

    def __init__(self):
        self.queue = [key for key, _label in LABELS]
        self.waiting = ""
        self.board = Board()

    def tick(self, idle: bool, send) -> None:
        if not idle:
            return
        if self.waiting:
            self.board.consider(self.waiting, check(self.waiting))
            publish(self.board)
            self.waiting = ""
        if not self.queue:
            return
        key = self.queue.pop(0)
        self.waiting = key
        send(PROMPTS[key])

    def done(self) -> bool:
        return not self.queue and not self.waiting


def begin(face) -> None:
    """Show the checklist and feed the chat. No second widget."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None and getattr(app, "_demo_board", None) is None:
        from botwidget.qt_ui.demo_board import DemoBoard
        app._demo_board = DemoBoard()
    session = Session()
    publish(session.board)
    face._demo_session = session

    def step():
        session.tick(not (face._working or face._sending or face._outbox.items), face.on_user_message)
        if not session.done():
            QTimer.singleShot(500, step)

    QTimer.singleShot(0, step)
