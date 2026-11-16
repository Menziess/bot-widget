"""One remembered variant, one widget.

Autostart and the desktop launcher call this. Takeover stops that widget, runs a custom command,
and starts the variant again when the command exits, crashes, or the lease times out.
"""

import os
import signal
import subprocess
import sys
import time

from botwidget.config import widget_config
from botwidget.startup import launch_command

VARIANTS = ("dev", "installed")


def remembered_variant() -> str | None:
    value = widget_config().get("variant")
    return value if value in VARIANTS else None


def selected_argv() -> list:
    """The command the remembered variant starts. With no variant, the command this copy already used."""
    kind = remembered_variant()
    if kind is None:
        return launch_command()
    if kind == "dev":
        saved = widget_config().get("local_command")
        if isinstance(saved, list) and saved and all(isinstance(part, str) for part in saved):
            return list(saved)
        return [sys.executable, "-m", "botwidget", "--dev"]
    from botwidget.system.current import stable_app_command
    stable = stable_app_command()
    return list(stable) if stable else [sys.executable, "-m", "botwidget"]


def login_command() -> list:
    """Autostart goes through the supervisor only when a variant is remembered."""
    if remembered_variant() is None:
        return launch_command()
    return [sys.executable, "-m", "botwidget.supervisor", "run"]


def try_lock(path: str):
    """Exclusive lock. None when another supervisor already holds it."""
    fh = open(path, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def retry_delay(attempt: int) -> float:
    return min(60.0, float(2 ** min(max(attempt, 0), 6)))


def variant_pidfile() -> str:
    """Where the selected variant records its pid. Dev is the --dev supervisor; otherwise the widget."""
    if remembered_variant() == "dev":
        from botwidget.dev import DEV_PIDFILE
        return os.environ.get("BOTWIDGET_DEV_PID") or DEV_PIDFILE
    from botwidget.instance import PIDFILE
    return os.environ.get("BOTWIDGET_PID") or PIDFILE


def stop_selected() -> None:
    """Stop the widget the remembered variant started. A missing pid is left alone."""
    try:
        with open(variant_pidfile()) as fh:
            pid = int(fh.read().strip())
    except (OSError, ValueError):
        return
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def takeover(cmd: list, timeout: float, *, stop, spawn, wait, restore) -> str:
    """Stop the selected widget, run cmd, then restore it. The caller holds the single-instance lock."""
    stop()
    proc = spawn(cmd)
    status = wait(proc, timeout)
    restore()
    return status


def wait_proc(proc, timeout: float) -> str:
    try:
        code = proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        return "timeout"
    return "exit" if code == 0 else "crash"


def run_selected() -> int:
    lock_path = os.path.join(os.environ.get("TMPDIR") or "/tmp", "botwidget-supervisor.lock")
    held = try_lock(lock_path)
    if held is None:
        print("botwidget-supervisor: already running", file=sys.stderr)
        return 1
    argv = selected_argv()
    proc = subprocess.Popen(argv)
    code = proc.wait()
    held.close()
    return code


def launch() -> None:
    argv = selected_argv()
    os.execv(argv[0], argv)


def main(argv: list[str]) -> int:
    if argv[:1] == ["run"]:
        return run_selected()
    if argv[:1] == ["launch"]:
        launch()
        return 0
    if argv[:1] == ["takeover"]:
        cmd, timeout = [], 30.0
        args = argv[1:]
        while args:
            if args[0] == "--timeout" and len(args) > 1:
                timeout = float(args[1])
                args = args[2:]
            elif args[0] == "--cmd" and len(args) > 1:
                cmd = args[1:]
                break
            else:
                args = args[1:]
        if not cmd:
            print("usage: botwidget-supervisor takeover --cmd <command> --timeout N", file=sys.stderr)
            return 2
        lock_path = os.path.join(os.environ.get("TMPDIR") or "/tmp", "botwidget-supervisor.lock")
        held = try_lock(lock_path)
        if held is None:
            return 1

        def stop():
            stop_selected()

        def spawn(command):
            return subprocess.Popen(command)

        def restore():
            subprocess.Popen(selected_argv(), start_new_session=True)

        status = takeover(cmd, timeout, stop=stop, spawn=spawn, wait=wait_proc, restore=restore)
        held.close()
        print(status)
        return 0
    print("usage: botwidget-supervisor run | launch | takeover --cmd ... --timeout N", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
