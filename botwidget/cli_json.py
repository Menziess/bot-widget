"""What a CLI prints, and how its process group is stopped.

The Grok and Hermes links both read one JSON object off stdout, keep the first
line of a failure, and stop the process group on a timeout. The command each
link runs stays in that link.
"""

import json
import os
import signal
import subprocess
from subprocess import CompletedProcess
from typing import NamedTuple

# A long note helps nobody; the first words are enough.
NOTE_CHARS = 200
KILL_GRACE_S = 2


class Result(NamedTuple):
    """Exit code, the JSON object the CLI printed, and a note in plain words."""

    rc: int | None
    data: dict | None
    note: str


def json_object(stdout: str) -> dict | None:
    """The first line of stdout that is a JSON object."""
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def first_line_note(done: CompletedProcess, limit: int = NOTE_CHARS) -> str:
    """The first line a CLI complained about, in plain words."""
    if done.returncode == 0:
        return ""
    for text in (done.stderr, done.stdout):
        for line in (text or "").splitlines():
            if line.strip():
                return line.strip()[:limit]
    return ""


def stop_group(proc, grace_s: float = KILL_GRACE_S) -> None:
    """Stop a CLI and everything it started: TERM first, KILL when that is not enough."""
    if not hasattr(os, "killpg"):
        # Windows has no process groups to signal; stop at least the CLI itself.
        proc.kill()
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=grace_s)
            return
        except subprocess.TimeoutExpired:
            continue
