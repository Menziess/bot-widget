"""Shared by Linux and macOS: processes and plain sound commands."""

import os
import subprocess
import tempfile


def process_cmdline(pid: int) -> bytes:
    """Command line of pid, or empty if the process does not exist or is unreadable."""
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return b""


def spawn_first(candidates) -> None:
    """Start the first command that exists; silent if none succeeds."""
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


def spawn_script(script: str, *args: str) -> None:
    """A shell script that keeps running after the widget has quit."""
    handle, path = tempfile.mkstemp(suffix=".sh", prefix="botwidget-")
    with os.fdopen(handle, "w") as fh:
        fh.write(script)
    subprocess.Popen(["/bin/sh", path, *args], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.unlink(path)
