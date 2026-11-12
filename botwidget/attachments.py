"""Files and pictures sent along with a message.

A pasted file becomes a copy in the system temp folder, and its path goes in a list at the end of the message,
the way OpenBot hands an agent a file.
"""

import shutil
import tempfile
import uuid
from pathlib import Path

TRANSFERS = Path(tempfile.gettempdir()) / "botwidget-transfers"
LIST_HEADING = "Attached local files:"


def _fresh_folder() -> Path:
    TRANSFERS.mkdir(parents=True, exist_ok=True, mode=0o700)  # /tmp is shared on Linux; a screenshot is private
    folder = TRANSFERS / str(uuid.uuid4())
    folder.mkdir()
    return folder


def store_file(source: str) -> Path | None:
    """A copy of a file in its own folder under the shared folder, with its own name."""
    try:
        path = Path(source)
        target = _fresh_folder() / path.name
        shutil.copy2(path, target)
        return target
    except (OSError, shutil.Error):
        return None


def store_bytes(name: str, data: bytes) -> Path:
    target = _fresh_folder() / name
    target.write_bytes(data)
    return target


def message_with(text: str, files: list) -> str:
    """The message and, below it, the list of files the agent can read."""
    if not files:
        return text
    lines = "\n".join(f"- {path.name}: {path}" for path in files)
    return f"{text}\n\n{LIST_HEADING}\n{lines}".strip()


def label_with(text: str, files: list) -> str:
    """The message as it shows in the bubble while it waits: its words and the names of its files."""
    return (text + "".join(f"\n📎 {path.name}" for path in files)).strip()
