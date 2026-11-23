"""The pre-push hook rejects a push of main when the unit tests fail."""

import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".githooks", "pre-push")
ZERO = "0000000000000000000000000000000000000000"
COMMAND = "QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -t ."


class PrePush(unittest.TestCase):
    """Should run the unit tests for a push of main and reject that push when they fail."""

    def test_the_hook_runs_the_unit_test_command_for_main(self):
        with open(HOOK) as fh:
            text = fh.read()
        self.assertIn(COMMAND, text)
        self.assertIn("refs/heads/main", text)

    def _run_copy(self, stdin: str) -> int:
        with open(HOOK) as fh:
            text = fh.read()
        text = text.replace(COMMAND, "false")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "pre-push")
        with open(path, "w") as fh:
            fh.write(text)
        os.chmod(path, 0o755)
        done = subprocess.run(["sh", path, "origin", "unused"], input=stdin, text=True, cwd=ROOT)
        return done.returncode

    def test_a_failing_test_command_rejects_a_push_of_main(self):
        code = self._run_copy("refs/heads/main abc refs/heads/main def\n")
        self.assertNotEqual(code, 0)

    def test_another_branch_and_a_delete_are_not_gated(self):
        self.assertEqual(self._run_copy("refs/heads/feature abc refs/heads/feature def\n"), 0)
        self.assertEqual(self._run_copy(f"refs/heads/main {ZERO} refs/heads/main def\n"), 0)
