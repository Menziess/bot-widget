"""Gedeeld door Linux en macOS: processen en losse geluidsopdrachten."""

import os
import subprocess
import tempfile


def process_cmdline(pid: int) -> bytes:
    """Commandoregel van pid, of leeg als het proces niet bestaat of onleesbaar is."""
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                              capture_output=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return b""


def spawn_first(candidates) -> None:
    """Start de eerste opdracht die bestaat; stil als geen enkele lukt."""
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue


def spawn_script(script: str, *args: str) -> None:
    """Een shellscript dat blijft draaien nadat de widget is afgesloten."""
    handle, path = tempfile.mkstemp(suffix=".sh", prefix="botwidget-")
    with os.fdopen(handle, "w") as fh:
        fh.write(script)
    subprocess.Popen(["/bin/sh", path, *args], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
