"""Ticks for the --dev demo. A tick needs a checked outcome, never the model's sentence."""

import os


def evidence_ticks(evidence: dict) -> bool:
    """True only when code checked a real success. A block and a bare claim stay unticked."""
    if not evidence.get("checked") or evidence.get("blocked") or evidence.get("model_claim"):
        return False
    return bool(evidence.get("ok"))


def file_readback(path: str, expect: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            got = fh.read()
    except OSError as error:
        return {"checked": True, "ok": False, "detail": type(error).__name__}
    return {"checked": True, "ok": got == expect, "detail": "match" if got == expect else "mismatch"}


def script_exit(code: int) -> dict:
    return {"checked": True, "ok": code == 0, "detail": f"exit {code}"}


def process_cycle(started: bool, running_after_start: bool, running_after_stop: bool) -> dict:
    ok = started and running_after_start and not running_after_stop
    return {"checked": True, "ok": ok,
            "detail": f"started={started} up={running_after_start} stopped={not running_after_stop}"}


def a11y_read(text: str) -> dict:
    ok = "available:" in text and "applications:" in text
    return {"checked": True, "ok": ok, "detail": "listed" if ok else "missing"}


def repair_result(returncode: int) -> dict:
    return {"checked": True, "ok": returncode == 0, "detail": f"unittest {returncode}"}


def browser_tab(cdp_up: bool, url: str, new_window: bool, ours: bool, reason: str = "") -> dict:
    """A tab this demo opened in the existing window. Down CDP is blocked, not a failed tick to retry."""
    if not cdp_up:
        return {"checked": True, "ok": False, "blocked": reason or "CDP not reachable"}
    ok = ours and not new_window and bool(url)
    return {"checked": True, "ok": ok, "detail": url, "blocked": ""}


class Board:
    def __init__(self):
        self.rows = {}

    def consider(self, task: str, evidence: dict) -> None:
        row = dict(evidence)
        if evidence.get("model_claim") and not evidence.get("checked"):
            row["ticked"] = False
        else:
            row["ticked"] = evidence_ticks(evidence)
        self.rows[task] = row

    def ticked(self, task: str) -> bool:
        return bool(self.rows.get(task, {}).get("ticked"))


def write_board(path: str, rows: list) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        import json
        json.dump({"tasks": rows}, fh, indent=2)
