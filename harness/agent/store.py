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
create table if not exists tool_results (
    id integer primary key autoincrement,
    name text not null,
    shown text not null,
    full text not null,
    path text not null,
    ts real not null
);
create table if not exists meta (key text primary key, value text not null);
"""


MAX_STORED_RESULT = 2_000_000  # characters of one tool answer kept in the session


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

    def add_tool_result(self, name: str, shown: str, full: str, path: str = "") -> None:
        """One tool's complete answer, next to what the model was shown of it (head and tail when it spilled)."""
        self.db.execute("insert into tool_results (name, shown, full, path, ts) values (?, ?, ?, ?, ?)",
                        (name, shown, full[:MAX_STORED_RESULT], path, time.time()))
        self.db.commit()

    def tool_results(self, limit: int = 8) -> list[dict]:
        """The newest tool results, oldest first. `full` is the complete answer."""
        rows = self.db.execute("select name, shown, full, path from tool_results order by id desc limit ?",
                               (limit,)).fetchall()[::-1]
        return [{"name": n, "shown": sh, "full": fl, "path": pa} for n, sh, fl, pa in rows]

    def messages(self, limit: int | None = None) -> list[dict]:
        """The newest `limit` messages in order, straight from sqlite; every turn asks twice."""
        if limit:
            rows = self.db.execute("select role, text from messages order by id desc limit ?",
                                   (limit,)).fetchall()[::-1]
        else:
            rows = self.db.execute("select role, text from messages order by id").fetchall()
        return [{"role": role, "text": text} for role, text in rows]

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
