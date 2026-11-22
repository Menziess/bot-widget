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
STOPS_LOG = os.path.join(tempfile.gettempdir(), "bot_widget_stops.log")
# The packaged app is called "Bot Widget"; the other names are the plain start through Python.
LAUNCHERS = (b"bot_widget.py", b"botwidget", b"Bot Widget")


def looks_like_widget(cmdline: bytes, markers: tuple = LAUNCHERS) -> bool:
    return any(name in cmdline for name in markers)


def _cmdline_text(raw) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return raw.replace("\x00", " ")


def log_stopper(old: int):
    """The victim's SIGTERM carries no sender, so the stopper writes who it is and who started it."""
    me, parent = os.getpid(), os.getppid()
    line = (f"{time.strftime('%F %T')} stopping {old} ({process_cmdline(old)!r}) "
            f"from {me} ({process_cmdline(me)!r}), parent {parent} ({process_cmdline(parent)!r})\n")
    with open(STOPS_LOG, "a") as fh:
        fh.write(line)


def ensure_single_instance(pidfile: str = PIDFILE, markers: tuple = LAUNCHERS):
    """Stop a previously started widget, so one window remains.

    markers stays for callers that still pass it. The kill uses the command check, so a
    reused pid whose prompt merely mentions the widget is left alone.
    """
    try:
        old = int(read_file(pidfile))
    except ValueError:
        old = None
    if old and old != os.getpid() and is_widget_cmd(_cmdline_text(process_cmdline(old))):
        log_stopper(old)
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


_BUNDLE = "Bot Widget.app/Contents/MacOS/Bot Widget"


def _stem(token: str) -> str:
    name = os.path.basename(token.replace("\\", "/"))
    if name.lower().endswith(".exe"):
        name = name[:-4]
    if name.endswith(".app"):
        name = name[:-4]
    return name


def is_widget_cmd(cmd: str) -> bool:
    """A real widget: the executable or `python -m botwidget` near the start of the command.

    A process whose prompt only mentions those words is not a widget. The bundle path is
    matched before the shell split, because the executable name contains spaces.
    """
    raw = (cmd or "").replace("\x00", " ").strip()
    if not raw or "--instances" in raw.split():
        return False
    flat = raw.replace("\\", "/")
    if _BUNDLE in flat:
        return True
    low = flat.lower()
    if "/botwidget.exe" in low or low.endswith("botwidget.exe") or "/bot widget.exe" in low:
        return True
    # A Windows command keeps backslashes. posix shlex would eat them.
    posix = os.name != "nt" and "\\" not in raw
    try:
        argv = shlex.split(raw, posix=posix)
    except ValueError:
        argv = raw.split()
    if not argv:
        return False
    window = argv[:8]
    exe = _stem(argv[0])
    if exe in ("botwidget", "Bot Widget", "bot_widget.py"):
        return True
    if not exe.lower().startswith("python"):
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
