"""Files and pictures sent along with a message.

OpenBot hands an agent a file as a path under the shared folder, in a list at the end of the message,
so that is what a pasted file becomes: a copy there, and its path in the text.
"""

import shutil
import uuid
from pathlib import Path

TRANSFERS = Path.home() / "OpenBot" / "Shared" / "Transfers"
LIST_HEADING = "Attached local files:"


def _fresh_folder() -> Path:
    folder = TRANSFERS / str(uuid.uuid4())
    folder.mkdir(parents=True)
    return folder


def store_file(source: str) -> Path:
    """A copy of a file in its own folder under the shared folder, with its own name."""
    path = Path(source)
    target = _fresh_folder() / path.name
    shutil.copy2(path, target)
    return target


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
