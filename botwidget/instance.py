"""One widget at a time: a previously started widget is stopped first.

`instances_main` only lists processes. A `--dev` reloader and its child are one widget.
"""

import atexit
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time

from botwidget.config import read_file
from botwidget.system.current import process_cmdline

PIDFILE = os.path.join(tempfile.gettempdir(), "bot_widget.pid")
# The packaged app is called "Bot Widget"; the other names are the plain start through Python.
LAUNCHERS = (b"bot_widget.py", b"botwidget", b"Bot Widget")


def looks_like_widget(cmdline: bytes, markers: tuple = LAUNCHERS) -> bool:
    return any(name in cmdline for name in markers)


def ensure_single_instance(pidfile: str = PIDFILE, markers: tuple = LAUNCHERS):
    """Stop a previously started widget, so one window remains."""
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
            # Windows has SIGTERM and no SIGKILL.
            os.kill(old, getattr(signal, "SIGKILL", signal.SIGTERM))
    with open(pidfile, "w") as fh:
        fh.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(pidfile) and os.remove(pidfile))


def is_widget_cmd(cmd: str) -> bool:
    """A real widget: the executable or `python -m botwidget` near the start of the command.

    A process whose prompt only mentions those words is not a widget.
    """
    try:
        argv = shlex.split(cmd)
    except ValueError:
        argv = cmd.split()
    if not argv:
        return False
    window = argv[:8]
    if "--instances" in window:
        return False
    exe = os.path.basename(argv[0])
    if exe in ("botwidget", "Bot Widget", "bot_widget.py"):
        return True
    if not exe.startswith("python"):
        return False
    if "-m" in window:
        nxt = window[window.index("-m") + 1:window.index("-m") + 2]
        if nxt and (nxt[0] == "botwidget" or nxt[0].startswith("botwidget.")):
            return True
    return any(part.endswith("bot_widget.py") for part in window[1:])


def parse_ps(text: str) -> list:
    """pid, ppid, command rows from `ps -o pid=,ppid=,command=`."""
    rows = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        rows.append((pid, ppid, parts[2] if len(parts) > 2 else ""))
    return rows


def widget_groups(procs, own_pid=None) -> list:
    """Group a --dev supervisor with widget descendants. Each group is one widget.

    A child of the reloader (or of that child) shares the supervisor's group.
    """
    widgets = []
    for pid, ppid, cmd in procs:
        if own_pid and pid == own_pid:
            continue
        if is_widget_cmd(cmd):
            widgets.append((pid, ppid, cmd))
    by_pid = {pid: ppid for pid, ppid, _cmd in widgets}
    dev = {pid for pid, _ppid, cmd in widgets if "--dev" in cmd.split()}
    members = {}
    for pid in by_pid:
        leader = None
        walk = pid
        seen = set()
        while walk in by_pid and walk not in seen:
            seen.add(walk)
            if walk in dev:
                leader = walk
                break
            walk = by_pid[walk]
        if leader is None:
            leader = pid
        members.setdefault(leader, []).append(pid)
    groups = []
    for leader, pids in members.items():
        groups.append([leader] + [pid for pid in pids if pid != leader])
    return groups


def render_instances(groups, procs) -> str:
    cmds = {pid: cmd for pid, _ppid, cmd in procs}
    n = len(groups)
    noun = "widget" if n == 1 else "widgets"
    lines = [f"botwidget: {n} {noun} running"]
    for group in groups:
        bits = [f"{group[0]} {cmds.get(group[0], '').strip()}"]
        for kid in group[1:]:
            bits.append(f"child {kid} {cmds.get(kid, '').strip()}")
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines) + "\n"


def read_process_table():
    """Process rows, or None when the table cannot be read. Never kills a process."""
    if os.name == "nt":
        return None
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return parse_ps(result.stdout)


def instances_main(procs=None, own_pid=None) -> int:
    """Exit 0 when at most one widget is running. Never kills anything."""
    if procs is None:
        procs = read_process_table()
        own_pid = os.getpid()
        if procs is None:
            print("botwidget: cannot list processes", file=sys.stderr)
            return 2
    groups = widget_groups(procs, own_pid=own_pid)
    sys.stdout.write(render_instances(groups, procs))
    return 0 if len(groups) <= 1 else 1
