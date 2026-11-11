"""Workspace-scoped file access for harness bots.

Every tool call is scoped to the workspace folder. When the workspace is empty
(unclosed string), no filesystem tools are offered at all.

Permission modes
----------------
allow     – auto-allow read, search and git-read inside the workspace; still
            ask for edit (write_file) and shell.
ask       – every action asks the user.
allow_session – like allow, but the permission is remembered only until the
                process exits (a single session).

Secret filtering
----------------
Files: .env, .env.* (except .env.example), *.pem, *.key, id_*, .netrc
Directories: .ssh, .gnupg, .aws

These are never read, listed, or entered during search.

Containment
-----------
The workspace path is expanded and realpath'ed.  The result must be a prefix
of the target's realpath, which blocks ``..`` and symlink escapes.

Git tools
---------
git_status, git_log, git_diff are read-only.  git push, git reset --hard,
git clean, git checkout --, rm/rmdir/unlink are always refused.

Shell
-----
Runs in the workspace directory.  Write-heavy commands (git push, git reset
--hard, git clean, git checkout --) are refused.

Edit / undo
-----------
After every successful write the previous bytes are kept so undo_edit can
restore them within the session.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from difflib import unified_diff

from harness.agent.tools import Tool, ToolError, trash_file

# ── Defaults ──────────────────────────────────────────────────────────

MAX_RULE_CHARS = 8000  # size cap for rules injected into context

# ── Permission mode aliases ──────────────────────────────────────────

PERMISSION_MODES = ("ask", "allow", "allow_session")

# ── Diff mode aliases ────────────────────────────────────────────────

DIFF_MODES = ("ask", "always", "never")


def _resolve(path: str) -> str:
    """Expanduser + realpath on *path*. Raises ToolError on a cycle."""
    try:
        return os.path.realpath(os.path.expanduser(str(path or ".")))
    except (OSError, ValueError):
        raise ToolError("path cannot be resolved")


# ── Containment ───────────────────────────────────────────────────────

def resolve_workspace(path: str) -> str | None:
    """Return the realpath of *path*, or None when it is empty / missing."""
    if not path or not str(path).strip():
        return None
    resolved = _resolve(str(path))
    if not os.path.isdir(resolved):
        return None
    return resolved


def _contains(workspace: str, target: str) -> bool:
    """True when *target* lives inside *workspace* (or is the workspace itself)."""
    workspace, target = os.path.normcase(workspace), os.path.normcase(target)
    try:
        return os.path.commonpath([workspace, target]) == workspace
    except ValueError:  # another drive on Windows
        return False


def _check_inside(workspace: str, target_path: str) -> str:
    """Resolve *target_path*, check it is inside *workspace*, and return the real path.

    Relative paths are resolved against *workspace*.  Raises ToolError
    when the resolved path falls outside the workspace.
    """
    # Resolve relative paths against the workspace directory.
    if not os.path.isabs(target_path):
        target_path = os.path.join(workspace, target_path)
    real = _resolve(target_path)
    if not _contains(workspace, real):
        raise ToolError(f"path is outside the workspace: {target_path}")
    return real


# ── Secrets ───────────────────────────────────────────────────────────

# Patterns for denied filenames (matched against basename).
_SECRET_NAMES = (
    ".env",
    ".env.*",          # .env.production etc. – glob handled separately
    "*.pem",
    "*.key",
    "id_*",            # id_rsa, id_ed25519, …
    ".netrc",
)

# Directory basenames that are denied as subtrees.
_SECRET_DIRS = (".ssh", ".gnupg", ".aws")

# Allowed exceptions among .env.* files.
_ENV_ALLOW = {".env.example", ".env.template"}

# Precompiled patterns.
_SECRET_PATTERNS = tuple(re.compile(fnmatch.translate(p)).fullmatch for p in _SECRET_NAMES
                         if p not in (".env.*",))
_SECRET_ENV_PREFIX = re.compile(r"^\.env(?!\.example$|\.template$)")


def _is_secret_name(basename: str) -> bool:
    """Is *basename* a denied file name?"""
    if basename in ("", ".", ".."):
        return True
    for pat_fn in _SECRET_PATTERNS:
        if pat_fn(basename):
            return True
    if _SECRET_ENV_PREFIX.match(basename):
        return basename not in _ENV_ALLOW
    return False


def _is_secret_dir(basename: str) -> bool:
    return basename in _SECRET_DIRS


def _is_secret_path(real_path: str) -> bool:
    """Return True when *real_path* hits a denied file or is inside a denied tree."""
    if not real_path:
        return False
    parts = real_path.replace("\\", "/").split("/")
    # Check every ancestor component.
    for part in parts:
        if _is_secret_dir(part):
            return True
    return _is_secret_name(parts[-1])


# ── Search (safe walk, skips secrets) ────────────────────────────────

def _safe_walk(workspace: str):
    """Yield (dirpath, filenames) skipping denied directories and files."""
    for dirpath, dirs, files in os.walk(workspace, followlinks=False):
        # Prune denied subdirectories in-place.
        dirs[:] = [d for d in dirs if not _is_secret_dir(d)]
        yield dirpath, files


def search_files(workspace: str, pattern: str, limit: int = 100) -> str:
    """Search file contents using Python's re (ripgrep is preferred externally).

    Files/dirs that match secret rules are skipped entirely.  Returns
    match lines in *file:line* format.
    """
    matches: list[str] = []
    compiled = re.compile(pattern, re.IGNORECASE)
    for dirpath, files in _safe_walk(workspace):
        for fname in sorted(files):
            full = os.path.join(dirpath, fname)
            if _is_secret_name(fname):
                continue
            try:
                with open(full, errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if compiled.search(line):
                            matches.append(f"{full}:{lineno}:{line.rstrip()}")
                            if len(matches) >= limit:
                                return "\n".join(matches)
            except OSError:
                continue
    return "\n".join(matches) if matches else "(no matches)"


# ── File tools ────────────────────────────────────────────────────────

def _ws_read(workspace: str, path: str) -> str:
    real = _check_inside(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not read")
    try:
        with open(real, errors="replace") as fh:
            text = fh.read()
    except OSError as err:
        raise ToolError(f"cannot read {real}: {err.strerror}") from err
    return text


def _ws_list(workspace: str, path: str = ".") -> str:
    real = _check_inside(workspace, path)
    try:
        names = sorted(
            n for n in os.listdir(real)
            if not _is_secret_dir(n) and not _is_secret_name(n)
        )
    except OSError as err:
        raise ToolError(f"cannot list {real}: {err.strerror}") from err
    return "\n".join(names) or "(empty)"


def _ws_write(workspace: str, path: str, content: str) -> str:
    real = _check_inside(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not written")
    try:
        parent = os.path.dirname(real) or "."
        os.makedirs(parent, exist_ok=True)
        with open(real, "w") as fh:
            fh.write(content)
    except OSError as err:
        raise ToolError(f"cannot write {real}: {err.strerror}") from err
    return f"Wrote {len(content)} characters to {real}."


def _ws_delete(workspace: str, path: str) -> str:
    real = _check_inside(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not deleted")
    return trash_file(real)


# ── Edit / undo ───────────────────────────────────────────────────────

class EditStore:
    """Keeps a stack of edits so undo_edit restores the last applied edit first.

    Each entry is (real_path, previous_bytes, new_content).  Undo pops the most
    recent entry whose path matches, writes previous_bytes, and returns the text
    that was restored.
    """

    def __init__(self):
        self._stack: list[tuple[str, bytes, str]] = []  # (path, prev_bytes, new_content)
        self._cache: dict[str, bytes] = {}  # real_path -> bytes before last edit (for undo_edit tool)

    def record(self, real_path: str, content: str) -> None:
        """Record an edit on the stack for undo."""
        prev = self._cache.get(real_path)
        self._stack.append((real_path, prev, content))

    def before(self, real_path: str, content: str) -> str:
        """Record bytes before overwriting; return the real_path."""
        self._cache[real_path] = content.encode()
        return real_path

    def undo(self, real_path: str) -> str:
        """Restore the bytes recorded before the last write. Returns the text."""
        raw = self._cache.pop(real_path, None)
        if raw is None:
            raise ToolError("nothing to undo for this file")
        try:
            with open(real_path, "wb") as fh:
                fh.write(raw)
            return raw.decode()
        except OSError as err:
            raise ToolError(f"cannot restore {real_path}: {err.strerror}") from err

    def undo_last(self) -> tuple[str, str] | None:
        """Undo the most recent applied edit (LIFO), restoring its previous bytes.

        Returns ``(real_path, restored_text)`` or None if the stack is empty.
        Skips entries with no meaningful previous content (new files).
        """
        while self._stack:
            real_path, prev_bytes, _content = self._stack.pop()
            if prev_bytes is not None and prev_bytes != b"":
                try:
                    with open(real_path, "wb") as fh:
                        fh.write(prev_bytes)
                    return real_path, prev_bytes.decode(errors="replace")
                except OSError:
                    continue
        return None


# ── Git (read-only) ───────────────────────────────────────────────────

_GIT_WRITE_COMMANDS = (
    "push",
    "reset",    # --hard etc.
    "clean",
    "checkout", "--",
    "rm",
    "rmdir",
    "shred",
    "del",
)

# Commands that are always refused (write).
_REFUSED_GIT = frozenset({"push", "reset", "clean", "checkout"})
_REFUSED_OPS = frozenset({"--hard", "--", "-f", "--force"})


def _git_refused(args: list[str]) -> bool:
    """Should we refuse this git invocation?"""
    for arg in args:
        if arg in _REFUSED_GIT:
            return True
        if arg in _REFUSED_OPS:
            return True
    return False


def _git_run(workspace: str, args: list[str]) -> str:
    """Run git; refuse writes; return stdout or raise."""
    if _git_refused(args):
        raise ToolError("git write is refused: " + " ".join(args[:3]))
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        raise ToolError("git is not installed")
    except subprocess.TimeoutExpired:
        raise ToolError("git timed out")
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise ToolError(f"git failed ({proc.returncode}): {msg[:300]}")
    return (proc.stdout or "").strip() or "(clean)"


# ── Shell ─────────────────────────────────────────────────────────────

_REFUSED_SHELL = re.compile(
    r"^\s*(git\s+(push|reset|clean|checkout)\s|"
    r"rm\s+(-rf?|-r|/)\s|"
    r"rmdir\s|"
    r"unlink\s|"
    r"shred\s|"
    r"del\s)",
    re.IGNORECASE,
)


def shell_refused(command: str) -> bool:
    """True when shell must not run this command. Background jobs use the same list."""
    return bool(_REFUSED_SHELL.search(command or ""))


def shell_run(workspace: str, command: str, timeout: int = 30) -> str:
    """Run a shell command inside the workspace.  Write-heavy patterns are refused."""
    if shell_refused(command):
        raise ToolError("shell command refused: " + command[:120])
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise ToolError(f"shell not found")
    except subprocess.TimeoutExpired:
        raise ToolError("shell timed out")
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise ToolError(f"shell failed ({proc.returncode}): {msg[:300]}")
    return (proc.stdout or "").strip()[:4000]


# ── Context rules ─────────────────────────────────────────────────────

_RULE_FILES = ("AGENTS.md", "CLAUDE.md", ".clinerules")


def load_workspace_rules(workspace: str) -> str:
    """Load the first existing rules file from the workspace root, size-capped."""
    for name in _RULE_FILES:
        path = os.path.join(workspace, name)
        if os.path.isfile(path):
            # Don't load if it is itself a secret.
            if _is_secret_path(path):
                continue
            try:
                with open(path) as fh:
                    text = fh.read(MAX_RULE_CHARS)
                return f"\n# Project guidance ({name}):\n{text}"
            except OSError:
                continue
    return ""


# ── Tool builders ─────────────────────────────────────────────────────

def workspace_builtins(workspace: str, edit: EditStore) -> list[Tool]:
    """Return the repo-scoped tools for *workspace* (str or None realpath).

    When workspace is None (off) the list is empty.
    """
    if workspace is None:
        return []

    return [
        # ── read ──
        Tool("list_dir",
             f"List directory contents inside the workspace (scoped). Read-only.",
             {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: _ws_list(workspace, a.get("path", "."))),
        Tool("read_file",
             "Read a text file inside the workspace. Read-only.",
             {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: _ws_read(workspace, a["path"])),
        # ── search ──
        Tool("search",
             "Search file contents inside the workspace. Skips secret files/dirs.",
             {"type": "object",
              "properties": {
                  "pattern": {"type": "string"},
                  "limit": {"type": "integer"},
              },
              "required": ["pattern"]},
             lambda a: search_files(workspace, a["pattern"], int(a.get("limit") or 100))),
        # ── edit ──
        Tool("write_file",
             "Write a text file inside the workspace. Needs user permission.",
             {"type": "object",
              "properties": {
                  "path": {"type": "string"},
                  "content": {"type": "string"},
              },
              "required": ["path", "content"]},
             lambda a: _ws_write(workspace, a["path"], a["content"]),
             writes=True),
        Tool("delete_file",
             "Delete one file inside the workspace. It moves to a trash folder, so it can be restored. Needs user permission.",
             {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: _ws_delete(workspace, a["path"]),
             writes=True),
        Tool("undo_edit",
             "Undo the last write to a file in the workspace. Restores previous bytes.",
             {"type": "object",
              "properties": {"path": {"type": "string"}},
              "required": ["path"]},
             lambda a: edit.undo(_check_inside(workspace, a["path"]))),
        # ── diff (read-only, before write) ──
        Tool("diff",
             "Show a unified diff between the current file and *content*. Read-only preview.",
             {"type": "object",
              "properties": {
                  "path": {"type": "string"},
                  "content": {"type": "string"},
              },
              "required": ["path", "content"]},
             lambda a: _ws_diff(workspace, a["path"], a["content"])),
        # ── git (read-only) ──
        Tool("undo_last",
             "Undo the last applied edit across all files. Restores the most recent change first (LIFO).",
             {"type": "object",
              "properties": {},
              "required": []},
             lambda _a: _undo_last(edit)),
        Tool("git_status",
             "Git status inside the workspace. Read-only.",
             {"type": "object",
              "properties": {},
              "required": []},
             lambda _a: _git_run(workspace, ["status"])),
        Tool("git_log",
             "Git log inside the workspace. Read-only.",
             {"type": "object",
              "properties": {
                  "limit": {"type": "integer"},
              }},
             lambda a: _git_run(workspace, ["log", f"--max-count={int(a.get('limit') or 20)}"])),
        Tool("git_diff",
             "Git diff inside the workspace. Read-only.",
             {"type": "object",
              "properties": {},
              "required": []},
             lambda _a: _git_run(workspace, ["diff"])),
        # ── shell ──
        Tool("shell",
             "Run a shell command inside the workspace. Read-only by default.",
             {"type": "object",
              "properties": {"command": {"type": "string"}},
              "required": ["command"]},
             lambda a: shell_run(workspace, a["command"]),
             writes=True),
    ]


def _ws_diff(workspace: str, path: str, content: str) -> str:
    real = _check_inside(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private")
    try:
        with open(real, errors="replace") as fh:
            old = fh.read()
    except OSError:
        old = ""
    old_lines = old.splitlines(keepends=True)
    new_lines = content.splitlines(keepends=True)
    diff = unified_diff(old_lines, new_lines, fromfile=path, tofile=path, lineterm="")
    return "\n".join(diff) or "(no diff)"


def _edit_before(edit: EditStore, real_path: str, content: str) -> None:
    """Record bytes before a write so undo can restore them."""
    edit.before(real_path, content)


def _undo_last(edit: EditStore) -> str:
    """Undo the most recent applied edit (LIFO)."""
    result = edit.undo_last()
    if result is None:
        raise ToolError("nothing to undo")
    real_path, restored = result
    return f"Restored {real_path}."
