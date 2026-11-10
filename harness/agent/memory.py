"""H5: topic-scoped, durable memory for harness bots.

Three scopes
------------
user     – per bot, survives compaction and restarts
project  – keyed by workspace realpath, lives in the bot's data directory
topic    – scoped to a topic name, stored in the project memory file

Storage
-------
A single JSON-lines file per scope lives in the bot's data directory (or
HARNESS_MEMORY_DIR when set).  Each line is a JSON object:

    {"id": "h1", "scope": "user", "topic": "", "text": "…", "ts": 0.0}

The file is opened on every write / read so that a restart sees it, and
closed after every turn so that two processes never fight over the lock.

Topic assignment
----------------
When the agent receives a user message it picks the topic that best matches
the text using simple token overlap (capitalised identifiers, then word
intersection).  If no existing topic scores above the threshold, a new
topic is started.

Retrieval
---------
When building the next request, top-k memories are injected as a system
message.  Scoring is token overlap with a boost when the query topic matches
the memory's topic.  A character cap (default 2048) keeps the injection small.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Optional

# ── Defaults ────────────────────────────────────────────────────────

TOPIC_THRESHOLD = 0.15  # overlap score to reuse a topic
RETRIEVE_TOP_K = 10     # max memories injected per request
RETRIEVE_MAX_CHARS = 2048  # character cap for injected memory text


# ── ID helpers ──────────────────────────────────────────────────────

def _id() -> str:
    """A short, unique ID for a memory line."""
    return uuid.uuid4().hex[:10]


# ── Tokenisation ────────────────────────────────────────────────────

def _tokenise(text: str) -> set[str]:
    """Lowercase words; also keep CAPS-LIKE tokens as-is."""
    words: set[str] = set()
    caps: set[str] = set()
    for word in re.findall(r"\b\w+\b", text.lower()):
        if len(word) >= 2:
            words.add(word)
    for word in re.findall(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b", text):
        caps.add(word)
    return words | caps


def _overlap_score(a: str, b: str) -> float:
    """Jaccard-like overlap between two texts."""
    ta = _tokenise(a)
    tb = _tokenise(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / (len(ta) + len(tb) - inter)


# ── File I/O ────────────────────────────────────────────────────────

def _memory_path(scope: str, workspace: str | None = None) -> str | None:
    """Return the path for a scope, or None when a project scope needs a workspace."""
    if scope == "project":
        if not workspace:
            return None
        # Project memories live in the bot's data directory, keyed by workspace hash.
        data_dir = _data_dir()
        ws_hash = hashlib_sha256(workspace)[:12]
        return os.path.join(data_dir, f"memory_project_{ws_hash}.jsonl")
    # user and topic both live in the bot's data directory.
    return os.path.join(_data_dir(), f"memory_{scope}.jsonl")


def _data_dir() -> str:
    """The bot's data directory, configurable via HARNESS_MEMORY_DIR."""
    return os.environ.get("HARNESS_MEMORY_DIR") or os.path.expanduser(
        "~/.local/share/botwidget/harness/memory"
    )


def _read_lines(path: str) -> list[dict]:
    """Read all lines from a memory file; return empty list if missing or corrupt."""
    if path is None or not os.path.isfile(path):
        return []
    lines: list[dict] = []
    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return lines


def _write_line(path: str, entry: dict) -> None:
    """Append one JSON object as a line to the memory file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _remove_lines(path: str, keep_ids: set[str]) -> None:
    """Rewrite the file keeping only entries whose ID is in *keep_ids*."""
    if path is None:
        return
    lines = _read_lines(path)
    kept = [l for l in lines if l.get("id") in keep_ids]
    try:
        with open(path, "w") as fh:
            for entry in kept:
                fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# Hash helper – imported at call site to avoid issues if hashlib isn't available
def hashlib_sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


# ── Write ───────────────────────────────────────────────────────────

def write_memory(text: str, scope: str = "user", topic: str = "",
                 workspace: str | None = None) -> str:
    """Persist one memory line. Returns the ID."""
    path = _memory_path(scope, workspace)
    if path is None:
        return ""
    entry = {
        "id": _id(),
        "scope": scope,
        "topic": topic,
        "text": text,
        "ts": time.time(),
    }
    _write_line(path, entry)
    return entry["id"]


def write_memory_list(entries: list[dict], scope: str = "user",
                      workspace: str | None = None) -> list[str]:
    """Write several entries at once (used for migrating pin_fact into memory)."""
    ids: list[str] = []
    for entry in entries:
        entry["scope"] = scope
        entry["ts"] = entry.get("ts") or time.time()
        eid = entry.get("id") or _id()
        entry["id"] = eid
        path = _memory_path(scope, workspace)
        if path is not None:
            _write_line(path, entry)
            ids.append(eid)
    return ids


# ── Read / Retrieve ─────────────────────────────────────────────────

def retrieve_memories(query: str, top_k: int = RETRIEVE_TOP_K,
                      max_chars: int = RETRIEVE_MAX_CHARS,
                      workspace: str | None = None) -> list[dict]:
    """Score all memories against *query* and return the top-k, capped at *max_chars*.

    Topics that match the query get a 2× boost.
    """
    q_tokens = _tokenise(query)
    if not q_tokens:
        return []

    # Determine the best topic for this query.
    best_topic = _pick_topic(query, workspace)

    all_entries: list[dict] = []
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope, workspace)
        if path is None:
            continue
        all_entries.extend(_read_lines(path))

    if not all_entries:
        return []

    scored: list[tuple[float, dict]] = []
    for entry in all_entries:
        score = _overlap_score(query, entry.get("text", ""))
        # Boost: topic match.
        if entry.get("topic") == best_topic and best_topic:
            score *= 2
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    # Cap total characters.
    result: list[dict] = []
    used = 0
    for score, entry in top:
        text = entry.get("text", "")
        if used + len(text) > max_chars and result:
            break
        result.append(entry)
        used += len(text)

    return result


# ── Topic assignment ────────────────────────────────────────────────

def _pick_topic(query: str, workspace: str | None = None) -> str:
    """Find the topic whose memories best match the query. Returns the topic name."""
    all_entries: list[dict] = []
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope, workspace)
        if path is None:
            continue
        all_entries.extend(_read_lines(path))

    if not all_entries:
        return ""

    best_score = 0.0
    best_topic = ""
    for entry in all_entries:
        topic = entry.get("topic", "")
        if not topic:
            continue
        text = entry.get("text", "")
        score = _overlap_score(query, text)
        if score > best_score:
            best_score = score
            best_topic = topic

    if best_score < TOPIC_THRESHOLD:
        return ""
    return best_topic


def suggest_topic(text: str) -> str | None:
    """Should a new topic be started? Returns a short note or None."""
    all_entries: list[dict] = []
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope)
        if path is None:
            continue
        all_entries.extend(_read_lines(path))

    if not all_entries:
        return None

    max_score = max(_overlap_score(text, e.get("text", "")) for e in all_entries)
    if max_score < TOPIC_THRESHOLD / 2:
        return "new topic"
    return None


def topic_for_message(text: str) -> str:
    """Return the topic name for *text*, or start a new one and return its name."""
    existing = _pick_topic(text)
    if existing:
        return existing

    # Start a new topic: derive a short name from the text.
    words = text.split()
    name_parts = []
    for w in words:
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", w)
        if cleaned and cleaned.lower() not in ("the", "a", "is", "and", "for", "in", "of", "to", "my", "your"):
            name_parts.append(cleaned)
        if len(name_parts) >= 3:
            break
    if not name_parts:
        name_parts = ["untitled"]
    name = "_".join(name_parts).lower()
    return name


# ── Forget / Delete ─────────────────────────────────────────────────

def forget_memory(id_or_text: str, workspace: str | None = None) -> str:
    """Remove a memory by ID (exact) or by matching text. Returns a note."""
    # Check if it looks like an ID (hex string).
    if re.match(r"^[0-9a-f]+$", id_or_text) and len(id_or_text) >= 6:
        return _forget_by_id(id_or_text, workspace)

    # Otherwise treat as text and find the best match.
    best = None
    best_path = None
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope, workspace)
        if path is None:
            continue
        for entry in _read_lines(path):
            if id_or_text.lower() in entry.get("text", "").lower():
                best = entry
                best_path = path
                break
        if best:
            break

    if best:
        _forget_by_id(best["id"], workspace, path=best_path)
        return f"Removed: {id_or_text[:60]}…"

    return f"Not found: {id_or_text[:60]}"


def _forget_by_id(entry_id: str, workspace: str | None = None,
                  path: str | None = None) -> str:
    """Remove the entry with *entry_id* from its file."""
    if path is None:
        path = _find_entry_path(entry_id, workspace)
    if path is None:
        return f"Not found: {entry_id}"
    lines = _read_lines(path)
    try:
        with open(path, "w") as fh:
            for entry in lines:
                if entry.get("id") != entry_id:
                    fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return "Removed."


def _find_entry_path(entry_id: str, workspace: str | None = None) -> str | None:
    """Find which file contains the entry with *entry_id*."""
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope, workspace)
        if path is None:
            continue
        for entry in _read_lines(path):
            if entry.get("id") == entry_id:
                return path
    return None


def list_memories(workspace: str | None = None) -> list[dict]:
    """Return all memories across all scopes, newest first."""
    all_entries: list[dict] = []
    for scope in ("user", "project", "topic"):
        path = _memory_path(scope, workspace)
        if path is None:
            continue
        all_entries.extend(_read_lines(path))
    all_entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return all_entries


# ── Tools ───────────────────────────────────────────────────────────

def memory_write_tool(workspace: str | None = None):
    """Return a Tool for memory_write."""
    from harness.agent.tools import Tool

    def run(arguments: dict) -> str:
        text = str(arguments.get("text") or "").strip()
        if not text:
            return "Nothing to write."
        scope = str(arguments.get("scope") or "user")
        if scope not in ("user", "project", "topic"):
            scope = "user"
        topic = str(arguments.get("topic") or "")
        eid = write_memory(text, scope, topic, workspace)
        return f"Stored ({eid[:8]}). {scope}"

    return Tool(
        "memory_write",
        "Write a memory that persists across sessions and compaction. Use for facts, decisions, preferences.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "scope": {"type": "string", "enum": ["user", "project", "topic"]},
                "topic": {"type": "string"},
            },
            "required": ["text"],
        },
        run,
        writes=False,
    )


def memory_read_tool(workspace: str | None = None):
    """Return a Tool for memory_read."""
    from harness.agent.tools import Tool

    def run(arguments: dict) -> str:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return "(no memories)"
        results = retrieve_memories(query, workspace=workspace)
        if not results:
            return "(no matching memories)"
        lines = []
        for r in results:
            scope = r.get("scope", "?")
            topic = f" [{r['topic']}]" if r.get("topic") else ""
            lines.append(f"[{scope}{topic}] {r['text']}")
        return "\n".join(lines)

    return Tool(
        "memory_read",
        "Read memories relevant to a query. Use before writing to avoid duplicates.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
        run,
    )


def memory_forget_tool():
    """Return a Tool for memory_forget."""
    from harness.agent.tools import Tool

    def run(arguments: dict) -> str:
        target = str(arguments.get("target") or arguments.get("id") or arguments.get("text") or "").strip()
        if not target:
            return "Nothing to forget."
        return forget_memory(target)

    return Tool(
        "memory_forget",
        "Forget (delete) a memory by ID or by exact text match. Requires permission.",
        {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["target"],
        },
        run,
        writes=True,
    )


def memory_tools_for(workspace: str | None = None) -> list:
    """Return the three memory tools."""
    return [
        memory_write_tool(workspace),
        memory_read_tool(workspace),
        memory_forget_tool(),
    ]
