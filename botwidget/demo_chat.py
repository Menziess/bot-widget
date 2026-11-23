"""The /demo command. The six tasks go out through the chat. Code checks what they left behind.

"""

import os
import re
import shutil
import subprocess
import sys

from botwidget.demo_check import (
    Board,
    a11y_read,
    file_readback,
    plant_seed,
    repair_result,
    script_exit,
)

ROOT = os.environ.get("BOTWIDGET_DEMO_ROOT") or "/tmp/t-demo"
LABELS = (
    ("browser", "Browser: reuse a tab over CDP"),
    ("files", "Files: write, then read back"),
    ("script", "Script: write it and run it"),
    ("process", "Process: start, check, stop"),
    ("accessibility", "Accessibility: read the desktop"),
    ("repair", "Repair: fix a seeded failing test"),
    ("computer", "Computer: move a window and type into it"),
)
# Checked by code alone, once the chat tasks are done: nothing to ask the bot.
LOCAL = ("computer",)

PROMPTS = {
    "browser": (
        "Demo task browser. Use your browser_tabs tool. "
        "Reply with the number of open tabs as digits and nothing else."
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


def _parent_runs_dev() -> bool:
    """An old supervisor never put BOTWIDGET_DEV in the child's environment."""
    ppid = os.getppid()
    path = os.environ.get("BOTWIDGET_DEV_PID") or os.path.join(
        __import__("tempfile").gettempdir(), "bot_widget_dev.pid")
    try:
        with open(path) as fh:
            recorded = int(fh.read().strip())
    except (OSError, ValueError):
        recorded = None
    if recorded == ppid:
        return True
    try:
        with open(f"/proc/{ppid}/cmdline", "rb") as fh:
            raw = fh.read()
    except OSError:
        return False
    return b"--dev" in raw


def dev_running() -> bool:
    """The --dev supervisor's child does not see --dev on its own command line."""
    return os.environ.get("BOTWIDGET_DEV") == "1" or "--dev" in sys.argv[1:] or _parent_runs_dev()


def check(key: str, reply: str = "") -> dict:
    """Read the outcome. Does not perform the task. `reply` is what the bot said last."""
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
        # The number of tabs is a fact the bot can only know by asking Chrome, so the right number is the evidence.
        from harness.browser_local import attach
        try:
            tabs = len(attach().list_tabs())
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError):
            return {"checked": True, "ok": False, "blocked": "Chrome is not listening"}
        said = re.findall(r"\d+", reply)
        return {"checked": True, "ok": bool(said) and int(said[-1]) == tabs, "detail": f"{tabs} tabs open"}
    if key == "computer":
        from botwidget.system.control import throwaway
        try:
            return throwaway()
        except Exception as error:  # a desktop that cannot do it says so; it is not a failed tick to retry
            return {"checked": True, "ok": False, "blocked": type(error).__name__}
    return {"checked": True, "ok": False, "detail": "not seen from here"}


class Session:
    """Send one prompt when the chat is idle, then tick that task from check()."""

    def __init__(self):
        # What an earlier run left behind must not tick this one.
        shutil.rmtree(os.path.join(ROOT, "work"), ignore_errors=True)
        plant_seed(os.path.join(ROOT, "repair"), False)
        self.queue = [*PROMPTS, *LOCAL]
        self.waiting = ""
        self.board = Board()

    def tick(self, idle: bool, send, reply: str = "") -> None:
        if not idle:
            return
        if self.waiting:
            self.board.consider(self.waiting, check(self.waiting, reply))
            self.waiting = ""
        while self.queue and self.queue[0] in LOCAL:
            key = self.queue.pop(0)
            self.board.consider(key, check(key))
        if not self.queue:
            return
        key = self.queue.pop(0)
        self.waiting = key
        send(PROMPTS[key])

    def done(self) -> bool:
        return not self.queue and not self.waiting

    def summary(self) -> str:
        """The checklist as markdown: one line per task."""
        lines = []
        for key, label in LABELS:
            row = self.board.rows.get(key, {})
            detail = row.get("blocked") or row.get("detail") or "not run"
            lines.append(f"- {'✔' if row.get('ticked') else '✘'} {label}: {detail}")
        ticked = sum(bool(self.board.ticked(key)) for key, _label in LABELS)
        return f"**Demo checklist: {ticked} of {len(LABELS)} ticked**\n\n" + "\n".join(lines)


def begin(face) -> None:
    """Feed the chat one task at a time; when the last one is checked, the checklist opens in the bubble."""
    from PySide6.QtCore import QTimer

    from botwidget.markdown import md_blocks

    session = Session()
    face._demo_session = session

    def last_reply() -> str:
        bots = [m["text"] for m in face._latest().get("messages") or [] if m.get("role") == "bot"]
        return bots[-1] if bots else ""

    def step():
        session.tick(not (face._working or face._sending or face._outbox.items), face.on_user_message,
                     last_reply() if session.waiting else "")
        if not session.done():
            QTimer.singleShot(500, step)
            return
        face.bubble.show_blocks(md_blocks(session.summary()), "say")
        face.pin()

    QTimer.singleShot(0, step)
