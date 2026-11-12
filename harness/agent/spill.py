"""Large tool output goes to a file, and the model gets the path with the start and the end.

A hard cut at 4000 or 20000 characters hides the part the model needed and gives no way to get it.
Here the whole output is kept in a file under /tmp (read_file and read-only shell commands may read
that folder), and the model sees the head, the tail and where the rest is.

Settings: HARNESS_TOOL_OUTPUT_LIMIT (characters shown before an output spills, default 8000, 0 turns
spilling off), HARNESS_SPILL_DIR (folder), HARNESS_SPILL_KEEP_DAYS (files older than this are removed
when a new one is written, default 7).
"""

import hashlib
import os
import tempfile
import time

DEFAULT_LIMIT = 8000
HEAD_SHARE, TAIL_SHARE = 0.5, 0.3  # of the limit


def limit() -> int:
    try:
        return int(os.environ.get("HARNESS_TOOL_OUTPUT_LIMIT") or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT


def spill_dir() -> str:
    return os.environ.get("HARNESS_SPILL_DIR") or os.path.join(tempfile.gettempdir(), "botwidget-tool-outputs")


def in_spill_dir(real_path: str) -> bool:
    root = os.path.realpath(spill_dir())
    return real_path == root or real_path.startswith(root + os.sep)


def _prune(folder: str) -> None:
    try:
        days = float(os.environ.get("HARNESS_SPILL_KEEP_DAYS") or 7)
    except ValueError:
        days = 7
    cutoff = time.time() - days * 86400
    try:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.endswith(".txt") and os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
    except OSError:
        pass


def spill(text: str, name: str = "tool") -> tuple[str, str]:
    """Return ``(shown, path)``. *shown* is *text* itself when it is small (path is ''), else the head,
    a note with the path and the tail. When the file cannot be written, the head and tail are still shown."""
    cap = limit()
    if cap <= 0 or len(text) <= cap:
        return text, ""
    head, tail = text[:int(cap * HEAD_SHARE)], text[-int(cap * TAIL_SHARE):]
    omitted = len(text) - len(head) - len(tail)
    path = ""
    folder = spill_dir()
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        _prune(folder)
        safe = "".join(ch if ch.isalnum() else "-" for ch in name)[:24] or "tool"
        digest = hashlib.sha256(text.encode(errors="replace")).hexdigest()[:8]
        path = os.path.join(folder, f"{time.strftime('%Y%m%d-%H%M%S')}-{safe}-{digest}.txt")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
    except OSError:
        path = ""
    lines = text.count("\n") + 1
    where = (f"The full output ({len(text)} characters, {lines} lines) is in {path}. Read part of it with "
             f"read_file (offset and limit are line numbers) or search it with rg."
             if path else "The rest could not be saved.")
    return f"{head}\n[... {omitted} characters omitted. {where} ...]\n{tail}", path
