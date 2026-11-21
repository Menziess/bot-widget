"""Demo ticks follow a verifier, not a sentence."""

import os
import tempfile
import unittest

from botwidget.demo_check import Board, evidence_ticks, file_readback


class DemoTicks(unittest.TestCase):
    def test_a_false_claim_stays_unticked(self):
        board = Board()
        board.consider("files", {"model_claim": "wrote note.txt", "ok": True})
        self.assertFalse(board.ticked("files"))
        self.assertFalse(evidence_ticks({"model_claim": "done", "ok": True, "checked": True}))

    def test_a_read_back_ticks_only_when_the_bytes_match(self):
        board = Board()
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "note.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("demo-note\n")
            board.consider("files", file_readback(path, "other\n"))
            self.assertFalse(board.ticked("files"))
            board.consider("files", file_readback(path, "demo-note\n"))
            self.assertTrue(board.ticked("files"))

    def test_a_missing_browser_is_blocked_and_unticked(self):
        from botwidget.demo_check import browser_tab
        board = Board()
        board.consider("browser", browser_tab(False, "", False, False, "CDP not reachable"))
        self.assertFalse(board.ticked("browser"))
        self.assertIn("CDP", board.rows["browser"]["blocked"])
