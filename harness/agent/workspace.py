"""Workspace-scoped file access for harness bots.

Reads, listings, writes and read-only shell commands may use any folder, as in OpenCode, except private paths.
A write outside the workspace is labelled as such when it asks. When the workspace is empty (unclosed string), no filesystem tools are offered
at all.

Workspace
---------
HARNESS_WORKSPACE if set ("off" for none), else the folder the ACP client opened the session in,
else the home folder.

Permission modes
----------------
Reads, search and git-read are free in every mode. Writes (write_file, edit,
delete_file) and shell commands ask, except read-only shell commands and saved prefixes.
ask       – the default everywhere (form, config and agent): every one asks.
allow_session – an approved action is remembered until the process exits.
allow     – an approved action is remembered for good (write-allow.json in the bot's folder).

Secret filtering
----------------
Files: .env, .env.* (except .env.example), *.pem, *.key, id_*, .netrc
Directories: .ssh, .gnupg, .aws

These are never read, listed, or entered during search.

Containment
-----------
The workspace path is expanded and realpath'ed.  A target outside it, also through ``..`` or a symlink, is
labelled "(outside the workspace)" in the question for a write.

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
    if basename in (".", ".."):
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

MAX_READ_CHARS = 5_000_000  # one read never loads more than this; large answers spill to a file


def _real_path(workspace: str, path: str) -> str:
    """The real path of a tool's path argument: relative to the workspace, any folder."""
    path = os.path.expanduser(path)
    return _resolve(path if os.path.isabs(path) else os.path.join(workspace, path))


def outside_workspace(workspace: str, path: str) -> bool:
    """A write there asks first, with a note that it leaves the workspace."""
    return bool(workspace and path) and not _contains(workspace, _real_path(workspace, path))


def _ws_read(workspace: str, path: str, offset: int = 0, limit: int = 0) -> str:
    """The file's text. offset and limit are line numbers (offset counts from 1) for reading part of it."""
    real = _real_path(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not read")
    try:
        with open(real, errors="replace") as fh:
            text = fh.read(MAX_READ_CHARS)
    except OSError as err:
        raise ToolError(f"cannot read {real}: {err.strerror}") from err
    if offset or limit:
        lines = text.splitlines(keepends=True)
        start = max(int(offset or 1) - 1, 0)
        end = start + int(limit) if limit else len(lines)
        if start >= len(lines) and lines:
            raise ToolError(f"offset {offset} is past the end ({len(lines)} lines)")
        text = "".join(lines[start:end])
    return text


def _ws_list(workspace: str, path: str = ".") -> str:
    real = _real_path(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not listed")
    try:
        names = sorted(
            n for n in os.listdir(real)
            if not _is_secret_dir(n) and not _is_secret_name(n)
        )
    except OSError as err:
        raise ToolError(f"cannot list {real}: {err.strerror}") from err
    return "\n".join(names) or "(empty)"


def _ws_write(workspace: str, path: str, content: str) -> str:
    real = _real_path(workspace, path)
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
    real = _real_path(workspace, path)
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


# ── Exact-replace edit ────────────────────────────────────────────────

def _miss_hint(text: str, old: str) -> str:
    """Numbered lines closest to the first line of *old*, so the model need not re-read the file."""
    from difflib import get_close_matches
    wanted = next((ln.strip() for ln in old.splitlines() if ln.strip()), "")
    lines = text.splitlines()
    stripped = [ln.strip() for ln in lines]
    if not wanted or not lines:
        return ""
    close = get_close_matches(wanted, stripped, n=3, cutoff=0.6)
    if not close:
        return ""
    found = []
    for hit in close:
        at = stripped.index(hit)
        found.append(f"{at + 1}: {lines[at]}")
    return "\nClosest lines:\n" + "\n".join(found)


def replace_once(text: str, old: str, new: str, replace_all: bool = False) -> str:
    """Return *text* with *old* replaced by *new*. *old* must match exactly and, unless
    *replace_all*, exactly once; otherwise ToolError says why."""
    if not old:
        raise ToolError("old_string is empty; use write_file to create or replace a whole file")
    if old == new:
        raise ToolError("old_string and new_string are identical; nothing to change")
    count = text.count(old)
    if count == 0:
        raise ToolError("old_string was not found in the file (it must match exactly, including "
                        "whitespace)." + _miss_hint(text, old))
    if count > 1 and not replace_all:
        raise ToolError(f"old_string matches {count} places; add surrounding lines so it matches once, "
                        "or set replace_all")
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def compute_edit(workspace: str, path: str, old: str, new: str, replace_all: bool = False) -> tuple[str, str, str]:
    """Check an edit and return ``(real_path, before_text, after_text)`` without writing."""
    real = _real_path(workspace, path)
    if _is_secret_path(real):
        raise ToolError("that path is private and is not edited")
    try:
        with open(real, errors="replace") as fh:
            before = fh.read()
    except OSError as err:
        raise ToolError(f"cannot read {real}: {err.strerror}") from err
    return real, before, replace_once(before, old, new, replace_all)


def _diff_text(path: str, before: str, after: str) -> str:
    diff = unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                        fromfile=path, tofile=path, lineterm="")
    return "\n".join(diff) or "(no diff)"


def _ws_edit(workspace: str, path: str, old: str, new: str, replace_all: bool = False) -> str:
    real, before, after = compute_edit(workspace, path, old, new, replace_all)
    try:
        with open(real, "w") as fh:
            fh.write(after)
    except OSError as err:
        raise ToolError(f"cannot write {real}: {err.strerror}") from err
    return f"Edited {real}.\n" + _diff_text(path, before, after)


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
    return (proc.stdout or "").strip()[:MAX_READ_CHARS]  # a long answer is spilled to a file by the agent


# ── Read-only shell commands and saved prefixes ───────────────────────

# Commands that only read. Anything else asks, unless a saved prefix covers it.
READONLY_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "rg", "grep", "find", "tree", "stat", "file",
    "which", "diff", "du", "df", "date", "whoami", "uname", "basename", "dirname", "realpath",
    "readlink", "nl", "true",
})
READONLY_GIT = frozenset({
    "status", "log", "diff", "show", "ls-files", "rev-parse", "blame", "shortlog", "describe",
    "grep", "ls-tree", "cat-file",
})
_FIND_WRITES = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0",
                          "-fprintf", "-fls"})
_NEVER_SAVED = frozenset({"sudo", "su", "sh", "bash", "zsh", "env", "xargs", "eval", "exec", "ssh",
                          "curl", "wget", "rm", "dd", "chmod", "chown", "mv", "cp", "python", "python3",
                          "node", "perl", "ruby", "nohup", "time", "watch"})
_OPERATORS = frozenset({"&&", "||", ";", "|"})


def shell_segments(command: str) -> list[list[str]] | None:
    """Split *command* into simple commands at && || ; |. None when it holds anything that could do more
    than it says: a redirect, a background &, a substitution, a newline or an unbalanced quote."""
    import shlex

    text = command or ""
    if not text.strip() or "\n" in text or "\r" in text or "`" in text or "$(" in text:
        return None
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _OPERATORS:
            if not segments[-1]:
                return None
            segments.append([])
        elif token and set(token) <= set("&|;<>()"):
            return None  # redirects, background, subshell
        else:
            segments[-1].append(token)
    if not segments[-1]:
        return None
    return segments


def _args_not_private(workspace: str, args: list[str]) -> bool:
    for arg in args:
        if "$" in arg:
            return False
        if arg.startswith("-") and "/" not in arg and "~" not in arg:
            continue
        base = os.path.basename(arg.rstrip("/"))
        if any(ch in base for ch in "*?[") and base.startswith("."):
            return False
        if _is_secret_name(base) and base not in ("", ".", ".."):
            return False
        if any(_is_secret_dir(part) for part in arg.replace("\\", "/").split("/")):
            return False
        if arg.startswith(("/", "~")) or ".." in arg.split("/"):
            # Relative paths resolve against the workspace, not the process cwd.
            target = arg if arg.startswith(("/", "~")) else os.path.join(workspace, arg)
            if _is_secret_path(_resolve(target)):
                return False
    return True


def _segment_read_only(workspace: str, tokens: list[str]) -> bool:
    name, args = tokens[0], tokens[1:]
    if name == "git":
        if not args or args[0] not in READONLY_GIT:
            return False
        if any(a == "-c" or a.startswith(("--output", "--ext-diff", "--exec-path", "--open-files")) for a in args):
            return False
        return _args_not_private(workspace, args[1:])
    if name not in READONLY_COMMANDS:
        return False
    if name == "find" and any(a in _FIND_WRITES for a in args):
        return False
    if name in ("rg", "grep") and any(a.startswith(("--pre", "--hostname-bin")) for a in args):
        return False
    return _args_not_private(workspace, args)


def is_read_only_command(workspace: str, command: str) -> bool:
    """True when every part of *command* is a known read-only command that stays inside the workspace."""
    segments = shell_segments(command)
    if not segments or shell_refused(command):
        return False
    return all(_segment_read_only(workspace, seg) for seg in segments)


def suggest_prefix(command: str) -> str:
    """The prefix an 'always allow' would save for *command*, or '' when it should not be offered."""
    segments = shell_segments(command)
    if not segments or len(segments) != 1 or shell_refused(command):
        return ""
    tokens = segments[0]
    if tokens[0] in _NEVER_SAVED or "/" in tokens[0]:
        return ""
    if len(tokens) >= 2 and not tokens[1].startswith("-") and not any(c in tokens[1] for c in "$*?/~"):
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]


def prefix_matches(prefix: str, tokens: list[str]) -> bool:
    parts = prefix.split()
    return bool(parts) and tokens[:len(parts)] == parts


class ShellAllow:
    """Saved 'always allow this prefix' choices, one JSON file per bot, keyed by workspace.

    The key ``*`` holds prefixes that count in every workspace of the bot. HARNESS_SHELL_ALLOW
    (comma list) adds fixed prefixes without touching the file.
    """

    def __init__(self, path: str, fixed: tuple[str, ...] = ()):
        self.path = path
        self.fixed = tuple(p.strip() for p in fixed if p.strip())

    def _load(self) -> dict:
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def prefixes(self, workspace: str) -> list[str]:
        data = self._load()
        found = list(self.fixed)
        for key in ("*", workspace):
            found += [p for p in data.get(key) or [] if isinstance(p, str)]
        return found

    def add(self, workspace: str, prefix: str, everywhere: bool = False) -> bool:
        prefix = " ".join((prefix or "").split())
        if not prefix or prefix.split()[0] in _NEVER_SAVED:
            return False
        data = self._load()
        key = "*" if everywhere else workspace
        known = [p for p in data.get(key) or [] if isinstance(p, str)]
        if prefix not in known:
            known.append(prefix)
        data[key] = known
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w") as fh:
                json.dump(data, fh, indent=2)
        except OSError:
            return False
        return True

    def allows(self, workspace: str, command: str, read_only: bool = True) -> bool:
        """Every part of *command* is read-only (when *read_only*) or starts with a saved prefix."""
        segments = shell_segments(command)
        if not segments or shell_refused(command):
            return False
        saved = self.prefixes(workspace)
        for seg in segments:
            if read_only and _segment_read_only(workspace, seg):
                continue
            if not any(prefix_matches(p, seg) for p in saved):
                return False
        return True


# ── Approval rules ────────────────────────────────────────────────────

_REGEX_KEY = re.compile(r"^/(.+)/(i?)$")


def rule_matches(pattern: str, text: str) -> bool:
    """A key of /regex/ or /regex/i is searched in *text*; any other key matches the start of it, up to a
    word end (so ``shell git status`` covers ``shell git status -s`` but ``mkdir`` not ``mkdirx``)."""
    regex = _REGEX_KEY.match(pattern)
    if regex:
        try:
            return bool(re.search(regex.group(1), text, re.IGNORECASE if regex.group(2) else 0))
        except re.error:
            return False
    return text == pattern or (text.startswith(pattern) and (pattern.endswith("/") or text[len(pattern)] in " /"))


def check_rules(rules) -> str:
    """Why *rules* is not a usable {pattern: true|false} map, or ''."""
    if not isinstance(rules, dict):
        return "approve has to be an object."
    for pattern, allowed in rules.items():
        if not isinstance(allowed, bool):
            return f"approve: {pattern!r} has to be true or false."
        regex = _REGEX_KEY.match(pattern)
        if regex:
            try:
                re.compile(regex.group(1))
            except re.error as error:
                return f"approve: {pattern!r} is not a valid regular expression ({error})."
    return ""


class ApproveRules:
    """What a tool call may do without asking, in the style of Copilot's autoApprove.

    A call is described as text: ``shell git status``, ``write_file /home/me/proj/a.py`` or just the tool's
    name. *config* maps keys (see rule_matches) to true (no question) or false (always ask, which wins).
    What a user accepted is remembered as a prefix rule on top of that, for the session or for good.
    """

    def __init__(self, path: str, config: dict | None = None):
        self.path = path
        self.config = config or {}
        self.session: list[str] = []
        try:
            with open(path) as fh:
                data = json.load(fh)
            self.saved = [p for p in data if isinstance(p, str)] if isinstance(data, list) else []
        except (OSError, ValueError):
            self.saved = []

    def decide(self, texts: list[str], session: bool, saved: bool) -> bool | None:
        """False when a rule says ask, True when every part is covered, else None (the user decides)."""
        if not texts:
            return None
        if any(allowed is False and rule_matches(pattern, text)
               for pattern, allowed in self.config.items() for text in texts):
            return False
        covering = [p for p, allowed in self.config.items() if allowed is True]
        covering += (self.session if session else []) + (self.saved if saved else [])
        return True if all(any(rule_matches(p, text) for p in covering) for text in texts) else None

    def remember(self, prefix: str, persist: bool) -> None:
        if not prefix:
            return
        if not persist:
            self.session.append(prefix)
            return
        if prefix not in self.saved:
            self.saved.append(prefix)
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w") as fh:
                json.dump(self.saved, fh, indent=2)
        except OSError:
            self.session.append(prefix)  # still remembered until the agent stops


# ── Context rules ─────────────────────────────────────────────────────

_RULE_FILES = ("AGENTS.md", "CLAUDE.md", ".clinerules")


def default_workspace(configured: str = "", cwd: str = "") -> str:
    """Which folder a session works in. HARNESS_WORKSPACE wins ("off" turns the workspace off),
    then the folder the ACP client started the session in, then the home folder."""
    configured = (configured or "").strip()
    if configured.lower() in ("off", "none", "(none)") and configured:
        return ""
    for candidate in (configured, cwd, "~"):
        resolved = resolve_workspace(candidate) if candidate and candidate != "/" else None
        if resolved and resolved != os.path.sep:
            return resolved
    return ""


def project_root(cwd: str) -> str:
    """The nearest folder at or above *cwd* with a .git; *cwd* itself when there is none."""
    here = cwd
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            return cwd
        here = parent


def _rules_in(folder: str) -> tuple[str, str] | None:
    for name in _RULE_FILES:
        path = os.path.join(folder, name)
        if os.path.isfile(path) and not _is_secret_path(path):
            return name, path
    return None


def load_workspace_rules(workspace: str) -> str:
    """Rules files from the project root down to *workspace*, root first, so the nearest folder
    reads last and wins. One file per folder (AGENTS.md, else CLAUDE.md, else .clinerules). The total is
    capped at HARNESS_RULES_MAX_CHARS (default MAX_RULE_CHARS); when it does not fit, the files nearest
    the workspace are kept."""
    try:
        limit = int(os.environ.get("HARNESS_RULES_MAX_CHARS") or MAX_RULE_CHARS)
    except ValueError:
        limit = MAX_RULE_CHARS
    folders = []
    here = workspace
    root = project_root(workspace)
    while True:
        folders.append(here)
        if here == root or os.path.dirname(here) == here:
            break
        here = os.path.dirname(here)
    parts: list[str] = []
    left = limit
    for folder in folders:  # nearest first, so the cap cuts the far end
        found = _rules_in(folder)
        if not found or left <= 0:
            continue
        name, path = found
        try:
            with open(path, errors="replace") as fh:
                text = fh.read(left)
        except OSError:
            continue
        left -= len(text)
        where = "" if folder == workspace else f" in {os.path.relpath(folder, workspace)}"
        parts.append(f"\n# Project guidance ({name}{where}):\n{text}")
    return "".join(reversed(parts))


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
             "Read a text file inside the workspace. Read-only. offset and limit are line numbers, for "
             "reading part of a large file or of a saved tool output.",
             {"type": "object",
              "properties": {"path": {"type": "string"},
                             "offset": {"type": "integer", "description": "First line to read, from 1."},
                             "limit": {"type": "integer", "description": "How many lines."}},
              "required": ["path"]},
             lambda a: _ws_read(workspace, a["path"], int(a.get("offset") or 0), int(a.get("limit") or 0))),
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
        Tool("edit",
             "Replace one exact piece of text in a file inside the workspace. old_string must match the "
             "file exactly and once (add surrounding lines to make it unique), or set replace_all. "
             "Returns the diff. Needs user permission. Prefer this over write_file for changes to an existing file.",
             {"type": "object",
              "properties": {
                  "path": {"type": "string"},
                  "old_string": {"type": "string"},
                  "new_string": {"type": "string"},
                  "replace_all": {"type": "boolean"},
              },
              "required": ["path", "old_string", "new_string"]},
             lambda a: _ws_edit(workspace, a["path"], a["old_string"], a["new_string"],
                                bool(a.get("replace_all"))),
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
             lambda a: edit.undo(_real_path(workspace, a["path"]))),
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
    real = _real_path(workspace, path)
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
