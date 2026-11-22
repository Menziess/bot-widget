"""Capability scores for a local run. No network and no live desktop.

Each score is 1 when the check did the thing, and 0 when this machine cannot
(computer use needs a display). History is JSONL, one object per run, appended.
"""

import json
import os
import py_compile
import subprocess
import sys
import time

NAMES = ("create_edit_files", "web_browsing", "background_processes", "computer_use", "running_scripts", "fixing_errors")


def _create_edit(scratch: str) -> float:
    path = os.path.join(scratch, "note.txt")
    with open(path, "w") as fh:
        fh.write("one")
    with open(path, "a") as fh:
        fh.write("-two")
    with open(path) as fh:
        return 1.0 if fh.read() == "one-two" else 0.0


def _browse(scratch: str) -> float:
    page = os.path.join(scratch, "page.html")
    with open(page, "w") as fh:
        fh.write("<html><head><title>Local fixture</title></head><body>token-bridge</body></html>")
    with open(page) as fh:
        text = fh.read()
    return 1.0 if "Local fixture" in text and "token-bridge" in text else 0.0


def _background(scratch: str) -> float:
    out = os.path.join(scratch, "bg.txt")
    proc = subprocess.Popen([sys.executable, "-c", "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('bg')", out])
    code = proc.wait(timeout=10)
    with open(out) as fh:
        return 1.0 if code == 0 and fh.read() == "bg" else 0.0


def _computer_use() -> tuple[float, str]:
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform == "darwin":
        return 0.0, "a display is present; this score stays 0 until a fixture drives it"
    return 0.0, "no display; computer use is not scored from a blank session"


def _script(scratch: str) -> float:
    path = os.path.join(scratch, "hi.py")
    with open(path, "w") as fh:
        fh.write("print('hi-script')\n")
    done = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=10)
    return 1.0 if done.returncode == 0 and "hi-script" in done.stdout else 0.0


def _fix(scratch: str) -> float:
    path = os.path.join(scratch, "broken.py")
    with open(path, "w") as fh:
        fh.write("def value(\n    return 1\n")
    with open(path) as fh:
        source = fh.read()
    fixed = source.replace("def value(\n", "def value():\n")
    with open(path, "w") as fh:
        fh.write(fixed)
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError:
        return 0.0
    return 1.0


def score(scratch: str) -> dict:
    os.makedirs(scratch, exist_ok=True)
    computer, limit = _computer_use()
    scores = {
        "create_edit_files": _create_edit(scratch),
        "web_browsing": _browse(scratch),
        "background_processes": _background(scratch),
        "computer_use": computer,
        "running_scripts": _script(scratch),
        "fixing_errors": _fix(scratch),
    }
    return {"scores": scores, "limits": {"computer_use": limit, "web_browsing": "fixture file, no network"}}


def commit_id(cwd: str | None = None) -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ""


def record(history: str, scratch: str, cwd: str | None = None) -> dict:
    body = score(scratch)
    row = {"commit": commit_id(cwd), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **body}
    os.makedirs(os.path.dirname(history) or ".", exist_ok=True)
    with open(history, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def main(argv: list[str]) -> int:
    scratch = "/tmp/botwidget-capability"
    history = os.path.join(scratch, "history.jsonl")
    args = list(argv)
    while args:
        if args[0] == "--scratch" and len(args) > 1:
            scratch = args[1]
            history = os.path.join(scratch, "history.jsonl")
            args = args[2:]
        elif args[0] == "--history" and len(args) > 1:
            history = args[1]
            args = args[2:]
        else:
            args = args[1:]
    row = record(history, scratch)
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
