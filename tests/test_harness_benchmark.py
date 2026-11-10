"""Tests for the H2 harness benchmark (harness.benchmark).

No live network, no llama.cpp, no secrets. Every task either uses ScriptModel
or builds context from a seeded SessionStore directly.
"""

import json
import os
import sys
import tempfile
import unittest

# Make sure the benchmark module is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import benchmark


class TestAsyncTasks(unittest.IsolatedAsyncioTestCase):
    """Async tasks (A, B, C) return the expected ok values."""

    async def test_a_short_answer_passes(self):
        result = await benchmark._run_async_task("short_answer",
                                                  benchmark.task_short_answer)
        self.assertTrue(result["ok"],
                        "short_answer should find 'Paris' in the scripted reply")
        self.assertEqual(result["id"], "short_answer")
        self.assertGreater(result["total_ms"], 0)
        self.assertEqual(result["path_steps"], 1)

    async def test_b_tool_read_passes(self):
        result = await benchmark._run_async_task("tool_read",
                                                  benchmark.task_tool_read)
        self.assertTrue(result["ok"],
                        "tool_read should contain 'CORAL-TREE-19' after reading the file")
        self.assertGreater(result["path_steps"], 0,
                           "a tool call should add to path_steps")

    async def test_c_topic_switch_recall_passes(self):
        result = await benchmark._run_async_task(
            "topic_switch_recall", benchmark.task_topic_switch_recall)
        self.assertTrue(result["ok"],
                        "topic_switch_recall should have 'Coral' in both answer and context")


class TestSyncTasks(unittest.TestCase):
    """Sync tasks (D, E) return the expected ok values."""

    def test_d_compact_without_summary_passes(self):
        """D: without a summary, older turns are kept via BACKGROUND extract — ok must be True."""
        result = benchmark._run_sync_task("compact_without_summary",
                                          benchmark.task_compact_without_summary)
        self.assertTrue(result["ok"],
                        "compact_without_summary should keep older turns via BACKGROUND")
        self.assertIn("id", result)
        self.assertIn("reason", result)

    def test_e_compact_with_summary_passes(self):
        """E: with a summary that preserves the fact, ok should be True."""
        result = benchmark._run_sync_task("compact_with_summary",
                                          benchmark.task_compact_with_summary)
        self.assertTrue(result["ok"],
                        "compact_with_summary should keep 'SILVER-ORCHID-7' "
                        "via the summary")


class TestSummary(unittest.TestCase):
    """The summary dict counts passed / failed correctly."""

    def test_summary_counts(self):
        tasks = [
            {"ok": True, "first_ms": 100, "total_ms": 200,
             "input_tokens": 10, "output_tokens": 5, "path_steps": 1},
            {"ok": False, "first_ms": 0, "total_ms": 0,
             "input_tokens": 0, "output_tokens": 0, "path_steps": 0},
            {"ok": True, "first_ms": 150, "total_ms": 300,
             "input_tokens": 20, "output_tokens": 8, "path_steps": 2},
        ]
        summary = benchmark._summary(tasks)
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["cost"], 0)
        self.assertEqual(summary["median_path_steps"], 1)

    def test_summary_empty(self):
        summary = benchmark._summary([])
        self.assertEqual(summary["n"], 0)
        self.assertEqual(summary["passed"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["median_first_ms"], 0)


class TestRunAll(unittest.IsolatedAsyncioTestCase):
    """The full suite returns suite name, mode, tasks, and summary."""

    async def test_run_all_structure(self):
        report = await benchmark.run_all()
        self.assertEqual(report["suite"], "h2")
        self.assertEqual(report["mode"], "scripted")
        self.assertEqual(len(report["tasks"]), 5)
        self.assertIn("summary", report)
        summary = report["summary"]
        self.assertIsInstance(summary["passed"], int)
        self.assertIsInstance(summary["failed"], int)

    async def test_run_all_expected_ok_values(self):
        """A, B, C, D, E all pass — H4 fixed compact_without_summary."""
        report = await benchmark.run_all()
        by_id = {t["id"]: t["ok"] for t in report["tasks"]}
        self.assertTrue(by_id["short_answer"])
        self.assertTrue(by_id["tool_read"])
        self.assertTrue(by_id["topic_switch_recall"])
        self.assertTrue(by_id["compact_without_summary"])
        self.assertTrue(by_id["compact_with_summary"])

    async def test_run_all_summary_matches_tasks(self):
        report = await benchmark.run_all()
        tasks = report["tasks"]
        passed = sum(1 for t in tasks if t["ok"])
        failed = sum(1 for t in tasks if not t["ok"])
        self.assertEqual(report["summary"]["passed"], passed)
        self.assertEqual(report["summary"]["failed"], failed)
        self.assertEqual(report["summary"]["n"], len(tasks))


class TestCLI(unittest.TestCase):
    """The CLI writes a JSON file and prints when asked."""

    def test_cli_writes_file_and_json(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            benchmark.main(["--out", path, "--json"])
            self.assertTrue(os.path.exists(path))
            with open(path) as fh:
                report = json.load(fh)
            self.assertEqual(report["suite"], "h2")
            self.assertEqual(len(report["tasks"]), 5)
            self.assertIn("summary", report)
        finally:
            os.unlink(path)

    def test_cli_live_is_stub(self):
        """--live prints a stub message to stderr but does not fail."""
        import io
        original_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            benchmark.main(["--live"])
        finally:
            stderr_output = sys.stderr.getvalue()
            sys.stderr = original_stderr
        self.assertIn("stub", stderr_output.lower())


class TestNoNetworkAndNoKeys(unittest.TestCase):
    """No test in this file connects to the local agent port or reads any key file."""

    def test_no_hardcoded_localhost_port(self):
        # Check the benchmark module (not this test file) for forbidden patterns.
        source = open(os.path.join(os.path.dirname(__file__),
                                   "..", "harness", "benchmark.py")).read()
        self.assertNotIn("8080", source,
                         "benchmark must not connect to 127.0.0.1:8080")

    def test_no_key_file_access(self):
        source = open(os.path.join(os.path.dirname(__file__),
                                   "..", "harness", "benchmark.py")).read()
        self.assertNotIn("/key", source,
                         "benchmark must not reference LLM key files")


if __name__ == "__main__":
    unittest.main()
