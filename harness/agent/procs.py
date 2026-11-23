"""A command in a process group of its own, and stopping all of it.

Shell commands and background jobs both need this: stopping only the shell left what it started running.
"""

import os
import signal
import subprocess
import time


def group_kwargs() -> dict:
    """Popen arguments that give the command a process group of its own."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def stop(target: "subprocess.Popen | int", grace: float = 1.0) -> None:
    """Stop a process and everything it started: ask first, kill once `grace` seconds have passed.

    `target` is a Popen, or the pid of a process that was started with group_kwargs (a job a previous agent left).

    Signals reach the members of a group one after the other. A parent that sees its child die can run its next
    command (`a; b`) before its own signal arrives, so the group is frozen first, told to end while frozen, and
    only then let go: each member ends the moment it runs again.
    """
    proc = target if isinstance(target, subprocess.Popen) else None
    pid = proc.pid if proc else int(target)

    def gone() -> bool:
        if proc is not None:
            proc.poll()  # reaps the leader: a zombie keeps its group alive
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False  # not permitted: a member is still there, only in a state that refuses signals
        return False

    def send(sig) -> None:
        try:
            os.killpg(pid, sig)
        except OSError:
            if proc is not None and sig in (signal.SIGTERM, signal.SIGKILL):
                proc.kill()

    if gone():
        return
    if os.name == "nt":
        if proc is not None:
            proc.terminate()
        return
    send(signal.SIGSTOP)
    send(signal.SIGTERM)
    send(signal.SIGCONT)
    deadline = time.monotonic() + grace
    while not gone() and time.monotonic() < deadline:
        time.sleep(0.05)
    if not gone():
        send(signal.SIGSTOP)
        send(signal.SIGKILL)
