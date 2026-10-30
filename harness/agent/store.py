"""The conversation of one bot on disk: messages, a rolling summary and the facts that must survive it.

One sqlite file per bot. A restart opens the same file, so the conversation is still there; the
usage lines sit next to it, one JSON object per turn, because a log is easier to read with tail
and jq than a table is to query.
"""

import json
import os
import sqlite3
import time

SCHEMA = """
create table if not exists messages (
    id integer primary key autoincrement,
    role text not null,
    text text not null,
    ts real not null
);
create table if not exists meta (key text primary key, value text not null);
"""


class SessionStore:
    """One bot's file. Writes are small and immediate, so a crash loses at most the last line."""

    def __init__(self, folder: str):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "session.sqlite")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def add(self, role: str, text: str) -> None:
        self.db.execute("insert into messages (role, text, ts) values (?, ?, ?)", (role, text, time.time()))
        self.db.commit()

    def messages(self, limit: int | None = None) -> list[dict]:
        rows = self.db.execute("select role, text from messages order by id").fetchall()
        messages = [{"role": role, "text": text} for role, text in rows]
        return messages[-limit:] if limit else messages

    def count(self) -> int:
        return self.db.execute("select count(*) from messages").fetchone()[0]

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("select value from meta where key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute("insert into meta (key, value) values (?, ?) "
                        "on conflict(key) do update set value = excluded.value", (key, value))
        self.db.commit()

    @property
    def summary(self) -> str:
        return self.get("summary")

    def set_summary(self, text: str) -> None:
        self.set("summary", text)

    def usage(self, line: dict) -> None:
        """One turn's numbers, in the same folder, for the measurement in phase 5."""
        with open(os.path.join(self.folder, "usage.jsonl"), "a") as fh:
            fh.write(json.dumps(line) + "\n")

    def close(self) -> None:
        self.db.close()
