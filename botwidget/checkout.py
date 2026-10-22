"""A widget that runs from a git checkout keeps its code up to date: fetch, and pull only when that cannot hurt."""

import os
import subprocess

BRANCH = "main"
REMOTE = "origin"


def _git(root: str, *args: str, timeout: float = 60.0) -> str | None:
    try:
        done = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def pull(root: str) -> bool:
    """Fetch, and fast-forward when the checkout is on the main branch with no changes of its own. True when new code
    came in. Anything else (changes, other branch, commits not pushed, no network) leaves the checkout alone."""
    if _git(root, "rev-parse", "--abbrev-ref", "HEAD") != BRANCH:
        return False
    if _git(root, "fetch", REMOTE, BRANCH) is None:
        return False
    if _git(root, "status", "--porcelain", "--untracked-files=no") != "":
        return False
    if _git(root, "rev-list", "--count", f"HEAD..{REMOTE}/{BRANCH}") in (None, "0"):
        return False
    return _git(root, "merge", "--ff-only", f"{REMOTE}/{BRANCH}") is not None
