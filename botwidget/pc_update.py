"""Fast-forward a checkout and restart the dev widget that is already running.

The release updater in botwidget/updates.py stays as it is. This is the git checkout on a PC.
"""

import os
import signal
import subprocess


def porcelain(cwd: str) -> str:
    done = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True)
    if done.returncode != 0:
        return "?"
    return done.stdout


def fast_forward(cwd: str) -> str:
    """'dirty' leaves the tree alone. 'updated' is a fast-forward of origin/main. 'failed' is anything else."""
    if porcelain(cwd).strip():
        return "dirty"
    done = subprocess.run(["git", "pull", "--ff-only", "origin", "main"], cwd=cwd,
                          capture_output=True, text=True)
    return "updated" if done.returncode == 0 else "failed"


def plan_restart(pid_text: str, busy: bool) -> str:
    """Restart only a recorded dev pid that is not marked busy. Never means 'start one'."""
    if busy or not pid_text.strip().isdigit():
        return "busy" if busy else "absent"
    return "restart"


def signal_restart(pid: int) -> None:
    """Ask the existing --dev supervisor to restart its child. Does not spawn a widget.

    SIGUSR1 is the poke on Unix. Windows has no such signal, so the same call uses SIGTERM.
    """
    os.kill(pid, getattr(signal, "SIGUSR1", signal.SIGTERM))
