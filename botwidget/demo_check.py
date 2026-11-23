"""Ticks for the --dev demo. A tick needs a checked outcome, never the model's sentence."""

import os
import shutil


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


def a11y_read(text: str) -> dict:
    ok = "available:" in text and "applications:" in text
    return {"checked": True, "ok": ok, "detail": "listed" if ok else "missing"}


def repair_result(returncode: int) -> dict:
    return {"checked": True, "ok": returncode == 0, "detail": f"unittest {returncode}"}


def control_outcome(moved: bool, typed: str, expect: str) -> dict:
    """The window is where it was sent and the field holds the text that was typed."""
    ok = bool(moved) and typed == expect
    return {"checked": True, "ok": ok, "detail": "landed" if ok else "mismatch"}


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


def plant_seed(folder: str, passes: bool) -> None:
    """The one-test file of the repair task, failing or fixed. Its bytecode goes first: a rewrite within the same
    second would keep the first one, so the fixed file would still fail."""
    os.makedirs(folder, exist_ok=True)
    shutil.rmtree(os.path.join(folder, "__pycache__"), ignore_errors=True)
    with open(os.path.join(folder, "test_seed.py"), "w", encoding="utf-8") as fh:
        fh.write("import unittest\n\nclass T(unittest.TestCase):\n    def test_seed(self):\n"
                 f"        self.assertEqual(1, {1 if passes else 0})\n")
