"""Teacher, supervisor, and judge for a short student loop.

The running widget is the student. This module does not start a widget.
"""

import json
import os
import subprocess

MAX_RETRIES = 2
TURN_LIMIT = 30
TIME_LIMIT_S = 480

# shortcut: character/4 is a stand-in until the widget exposes usage, switch when a usage line is available
CHARS_PER_TOKEN = 4


def task_prompt(worktree: str, title: str, test_module: str, hint: str = "") -> str:
    """The message the visible widget receives. The test already exists."""
    lines = [
        f"Taak: {title}",
        f"Werk alleen in {worktree}.",
        f"De acceptatietest staat al in tests/{test_module}.py. Laat die test staan.",
        f"Draai: QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.{test_module}",
        "Gebruik de venv van ~/Projects/bot-widget. Commit in deze worktree als de test slaagt.",
        "Geen push. Geen andere bestanden.",
    ]
    if hint:
        lines.append(f"Hint: {hint}")
    return "\n".join(lines)


def tokens_estimate(text: str) -> int:
    """Rough teacher-side token count. Exact usage is not on the remote API."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def judge(*, tests_ok: bool, health_ok: bool, turns: int, elapsed_s: float,
          error_tail: str = "", failing_test: str = "",
          turn_limit: int = TURN_LIMIT, time_limit_s: float = TIME_LIMIT_S) -> dict:
    """One failure type. Tests win over health, then limits."""
    if not tests_ok:
        kind = "tests"
    elif not health_ok:
        kind = "health"
    elif turns > turn_limit:
        kind = "turns"
    elif elapsed_s > time_limit_s:
        kind = "time"
    else:
        kind = ""
    return {"ok": kind == "", "failure": kind, "failing_test": failing_test,
            "error_tail": "\n".join(error_tail.strip().splitlines()[-8:])}


def summary(row: dict) -> str:
    """A few lines a later teacher turn can read without the log."""
    if row.get("ok"):
        return "ok"
    lines = [row.get("failure") or "failed"]
    if row.get("failing_test"):
        lines.append(row["failing_test"])
    tail = (row.get("error_tail") or "").strip()
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def next_action(retries_used: int, max_retries: int = MAX_RETRIES) -> str:
    """hint while retries remain, otherwise the teacher takes the edit."""
    return "hint" if retries_used < max_retries else "teacher_fix"


def decide_promote(tests_ok: bool, health_ok: bool) -> str:
    """merge only when both gates pass. Otherwise the live checkout stays."""
    return "merge" if tests_ok and health_ok else "rollback"


def approve_student(title: str, worktree: str) -> bool:
    """Allow a tool only when it names the student worktree or the shared venv python."""
    text = title or ""
    root = os.path.realpath(worktree)
    if root and root in text:
        return True
    return "unittest" in text and "bot-widget" in text


def self_check(directory: str) -> str:
    """Write a marker and read it back. The dry check after a restart."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "selfcheck.txt")
    token = "teacher-selfcheck"
    with open(path, "w") as fh:
        fh.write(token)
    with open(path) as fh:
        got = fh.read()
    if got != token:
        raise RuntimeError("selfcheck mismatch")
    return path


def failing_test_name(output: str) -> str:
    """The first unittest FAIL or ERROR line, if any."""
    for line in output.splitlines():
        if line.startswith(("FAIL:", "ERROR:")):
            return line.split(":", 1)[-1].strip()
    return ""


def score_row(task: str, student_ok: bool, student_turns: int, teacher_tokens: int,
              failure: str) -> dict:
    return {"task": task, "student_ok": student_ok, "student_turns": student_turns,
            "teacher_tokens": teacher_tokens, "failure": failure}


def write_scoreboard(directory: str, rows: list, notes: list | None = None) -> tuple[str, str]:
    """JSON plus a short markdown table."""
    os.makedirs(directory, exist_ok=True)
    json_path = os.path.join(directory, "scoreboard.json")
    md_path = os.path.join(directory, "scoreboard.md")
    with open(json_path, "w") as fh:
        json.dump({"rows": rows, "notes": notes or []}, fh, indent=2)
    header = "| Taak | Student | Beurten | Teacher tokens | Fout |\n| --- | --- | --- | --- | --- |"
    body = [header]
    for row in rows:
        body.append("| {task} | {ok} | {student_turns} | {teacher_tokens} | {failure} |".format(
            task=row["task"], ok="ja" if row["student_ok"] else "nee",
            student_turns=row["student_turns"], teacher_tokens=row["teacher_tokens"],
            failure=row["failure"] or ""))
    for note in notes or []:
        body.append("")
        body.append(note)
    with open(md_path, "w") as fh:
        fh.write("\n".join(body) + "\n")
    return json_path, md_path


def _git(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def promote_or_rollback(live: str, student_sha: str, good_sha: str, tests_ok: bool,
                        health_ok: bool) -> str:
    """Cherry-pick into live when the gates pass. Reset to good_sha when they do not.

    A dirty live tree is left untouched and reported as 'dirty'.
    """
    if _git(live, "status", "--porcelain").stdout.strip():
        return "dirty"
    if decide_promote(tests_ok, health_ok) == "merge":
        done = _git(live, "cherry-pick", "--ff", student_sha)
        return "merge" if done.returncode == 0 else "rollback"
    done = _git(live, "reset", "--hard", good_sha)
    return "rollback" if done.returncode == 0 else "reset_failed"
