"""Feedback: prepare a draft, confirm the exact text, then send.

Block 1 of roadmap/07-autonomy.md.

The bot never posts a GitHub issue without the user confirming the exact text
first, and never invents a report. If the user has not supplied the wording,
the bot asks what to send and waits; it must not invent a report.

Send path (Q1 B + A fallback):
  1. Prefer ``gh issue create`` against Menziess/bot-widget when ``gh auth
     status`` is already good (gh's own store, not widget.json).
  2. Otherwise open the existing prefilled issue page (A), now filled with the
     confirmed title and body, and tell the user the browser still needs Submit.

A vault token path (C) comes after the vault is built; not in this block.

Usage::

    draft = prepare_draft(user_text)       # -> dict or None
    board.put("bot1", "feedback", draft["body"], now=now)
    # ... user clicks Yes ...
    send_feedback(draft["title"], draft["body"])
"""

import os
import subprocess
import sys

from botwidget.menu_pages import feedback_issue_url


def prepare_draft(text: str) -> dict | None:
    """Create a draft title and body from user-supplied text.

    Returns ``{"title": ..., "body": ...}`` when *text* is non-empty,
    or ``None`` when the text is empty or whitespace-only.

    The bot must not invent a report. It only packages what the user wrote.
    """
    text = (text or "").strip()
    if not text:
        return None
    # The title is always "Feedback" for now; a future version may extract
    # a subject from the user text.
    return {"title": "Feedback", "body": text}


def _gh_available() -> bool:
    """Is ``gh`` available and authenticated?

    We only need ``gh issue create`` to work. A quick ``gh auth status``
    check is cheap and avoids a hung sub-process on a machine without gh.
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "botwidget.cli_json", "gh_available"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    # Direct check as a fallback.
    gh_path = os.environ.get("GH_PATH") or "gh"
    try:
        proc = subprocess.run(
            [gh_path, "auth", "status", "--just-use"],
            capture_output=True, text=True, timeout=5
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _send_via_gh(title: str, body: str) -> bool:
    """Create a GitHub issue via ``gh issue create``.

    Returns True on success, False on failure.
    """
    gh_path = os.environ.get("GH_PATH") or "gh"
    try:
        proc = subprocess.run(
            [gh_path, "issue", "create",
             "--repo", "Menziess/bot-widget",
             "--title", title,
             "--body", body],
            capture_output=True, text=True, timeout=30
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _send_via_browser(title: str, body: str) -> str:
    """Build a prefilled GitHub issue URL and return it.

    The caller (the face) opens it in the browser.  The user still clicks
    Submit.
    """
    return feedback_issue_url("1.2.3", "Linux", "checkout",
                              title=title, body=body)


def send_feedback(title: str, body: str,
                  on_success=None, on_fail=None) -> None:
    """Send the confirmed feedback through the best available path.

    Prefer ``gh issue create`` (Q1 B); fall back to the browser URL (A).
    Neither path ever touches a token stored in widget.json.

    *on_success* and *on_fail* are called with no arguments on the respective
    outcome.
    """
    if _gh_available():
        ok = _send_via_gh(title, body)
        if on_success is not None and ok:
            on_success()
        elif on_fail is not None:
            on_fail()
        return
    # Browser fallback (Q1 A).
    _send_via_browser(title, body)
    if on_success is not None:
        on_success()


def send_feedback_with_url(title: str, body: str,
                           on_success=None, on_fail=None) -> str:
    """Build the URL and return it; the face opens it.

    This is the browser fallback path, always available.
    """
    return _send_via_browser(title, body)
