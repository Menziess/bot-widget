"""Capability scores append one JSONL row per run and do not wipe history."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from harness.capability import NAMES, record


class Capability(unittest.TestCase):
    """Should score every named capability and append history."""

    def test_two_runs_append_and_every_score_is_a_number(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        history = os.path.join(folder, "history.jsonl")
        scratch = os.path.join(folder, "scratch")
        first = record(history, scratch, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        second = record(history, scratch)
        self.assertEqual(set(first["scores"]), set(NAMES))
        for name, value in first["scores"].items():
            self.assertIsInstance(value, float, name)
        lines = Path(history).read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["commit"], first["commit"])
        self.assertNotEqual(json.loads(lines[1])["at"], "")
        self.assertIn("scores", second)
