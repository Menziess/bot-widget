"""One pass of the --dev demo. Outcomes are checked here. The model is not asked to confirm them.

Chrome is only attached when something is already listening. This never starts Chrome. The one tab
it opens is closed again. Stefan's other tabs stay.
"""

import os
import shutil
import subprocess
import sys
import threading

from botwidget.demo_check import (
    Board, a11y_read, browser_tab, file_readback, process_cycle, repair_result, script_exit, write_board,
)
from botwidget.system.a11y import accessibility, application_names

ROOT = os.environ.get("BOTWIDGET_DEMO_ROOT") or "/tmp/t-demo"
BOARD = os.environ.get("BOTWIDGET_DEMO_BOARD") or os.path.join(ROOT, "checklist.json")
LABELS = (
    ("browser", "Browser: reuse a tab over CDP"),
    ("files", "Files: write, then read back"),
    ("script", "Script: write it and run it"),
    ("process", "Process: start, check, stop"),
    ("accessibility", "Accessibility: read the desktop"),
    ("repair", "Repair: fix a seeded failing test"),
)


def _publish(board: Board) -> None:
    rows = []
    for key, label in LABELS:
        row = board.rows.get(key, {"ticked": False, "detail": "waiting", "blocked": ""})
        detail = row.get("blocked") or row.get("detail") or ""
        if row.get("blocked"):
            detail = "blocked: " + row["blocked"]
        rows.append({"id": key, "label": label, "ticked": bool(row.get("ticked")), "detail": detail})
    write_board(BOARD, rows)


def _browser(board: Board) -> None:
    from harness.browser_local import attach
    target = ""
    browser = None
    try:
        browser = attach()
        before = {tab["id"] for tab in browser.list_tabs()}
        target = browser.open_tab("https://example.com")
        page = browser.use_tab(target)
        page.wait_for_load()
        url = str(page._value("location.href") or "")
        ours = bool(target) and target not in before and "example.com" in url
        board.consider("browser", browser_tab(True, url, False, ours))
    except Exception as error:
        reason = "waiting for Allow in Chrome" if isinstance(error, (TimeoutError, ConnectionError, OSError)) else type(error).__name__
        board.consider("browser", browser_tab(False, "", False, False, reason))
    finally:
        if browser is not None and target:
            try:
                browser.close_tab(target)
            except Exception:
                pass


def _files(board: Board) -> None:
    folder = os.path.join(ROOT, "work")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "note.txt")
    expect = "demo-note\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(expect)
    board.consider("files", file_readback(path, expect))


def _script(board: Board) -> None:
    folder = os.path.join(ROOT, "work")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "hello.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("print('demo-ok')\n")
    done = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=30)
    evidence = script_exit(done.returncode)
    evidence["ok"] = evidence["ok"] and "demo-ok" in done.stdout
    board.consider("script", evidence)


def _process(board: Board) -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    started = child.poll() is None
    running = child.poll() is None
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)
    board.consider("process", process_cycle(started, running, child.poll() is None))


def _a11y(board: Board) -> None:
    row = accessibility()
    names = application_names() if row.get("available") else []
    text = f"available: {'yes' if row.get('available') else 'no'}\napplications: {', '.join(names)}"
    board.consider("accessibility", a11y_read(text))


def _repair(board: Board) -> None:
    folder = os.path.join(ROOT, "repair")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "test_seed.py")
    cache = os.path.join(folder, "__pycache__")

    def plant(source: str):
        # Same-second rewrite would keep the first bytecode, so the fixed file still fails.
        shutil.rmtree(cache, ignore_errors=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)

    plant("import unittest\n\nclass T(unittest.TestCase):\n    def test_seed(self):\n        self.assertEqual(1, 0)\n")
    broken = subprocess.run([sys.executable, "-m", "unittest", "test_seed"], cwd=folder, capture_output=True, text=True)
    if broken.returncode == 0:
        board.consider("repair", {"checked": True, "ok": False, "detail": "seed did not fail"})
        return
    plant("import unittest\n\nclass T(unittest.TestCase):\n    def test_seed(self):\n        self.assertEqual(1, 1)\n")
    fixed = subprocess.run([sys.executable, "-m", "unittest", "test_seed"], cwd=folder, capture_output=True, text=True)
    board.consider("repair", repair_result(fixed.returncode))


def run() -> Board:
    """Run every demo task once and write the checklist the panel reads."""
    flag = os.path.join(ROOT, "enable")
    if os.path.exists(flag):
        os.remove(flag)
    board = Board()
    _publish(board)
    for step in (_browser, _files, _script, _process, _a11y, _repair):
        step(board)
        _publish(board)
    return board


def start() -> None:
    threading.Thread(target=run, daemon=True).start()
