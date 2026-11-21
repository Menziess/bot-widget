"""Should judge a student run, score it, and promote only a green tree."""

import os
import subprocess
import tempfile
import unittest

from harness.teacher import (
    GIT_COMMIT, VENV_PYTHON, approve_student, decide_promote, failing_test_name, false_claims, judge,
    next_action, promote_or_rollback, score_row, self_check, send_when_idle, student_worktree,
    summary, task_prompt, tokens_estimate, wait_until_idle, write_scoreboard,
)


class TeacherLoop(unittest.TestCase):
    def test_prompt_names_the_worktree_and_keeps_a_hint(self):
        text = task_prompt("/tmp/t-teacher/student", "leave", "test_leave_open", hint="gebruik bubble.py")
        self.assertIn("/tmp/t-teacher/student", text)
        self.assertIn("test_leave_open", text)
        self.assertIn("gebruik bubble.py", text)
        self.assertIn(VENV_PYTHON, text)
        self.assertIn(GIT_COMMIT, text)

    def test_tokens_are_a_quarter_of_the_characters(self):
        self.assertEqual(tokens_estimate("abcd"), 1)
        self.assertEqual(tokens_estimate("a" * 8), 2)

    def test_judge_names_one_failure_and_keeps_the_tail(self):
        row = judge(tests_ok=False, health_ok=False, turns=99, elapsed_s=999,
                    error_tail="noise\nAssertionError: 1 != 0", failing_test="test_a")
        self.assertEqual(row["failure"], "tests")
        self.assertIn("AssertionError", summary(row))
        self.assertEqual(judge(tests_ok=True, health_ok=False, turns=1, elapsed_s=1)["failure"], "health")
        self.assertEqual(judge(tests_ok=True, health_ok=True, turns=99, elapsed_s=1, turn_limit=3)["failure"], "turns")
        self.assertEqual(judge(tests_ok=True, health_ok=True, turns=1, elapsed_s=50, time_limit_s=10)["failure"], "time")
        self.assertTrue(judge(tests_ok=True, health_ok=True, turns=1, elapsed_s=1)["ok"])

    def test_two_hints_then_the_teacher_fixes_it(self):
        self.assertEqual(next_action(0), "hint")
        self.assertEqual(next_action(1), "hint")
        self.assertEqual(next_action(2), "teacher_fix")

    def test_promote_only_when_tests_and_health_pass(self):
        self.assertEqual(decide_promote(True, True), "merge")
        self.assertEqual(decide_promote(True, False), "rollback")

    def test_an_approval_must_name_the_student_worktree(self):
        root = "/tmp/t-teacher/student"
        self.assertTrue(approve_student(f"write_file {root}/botwidget/bubble.py", root))
        self.assertFalse(approve_student("write /home/stefan/.config/botwidget/widget.json", root))
        self.assertFalse(approve_student("unittest ~/Projects/bot-widget", root))
        self.assertFalse(approve_student(f"shell {GIT_COMMIT} && rm /etc/passwd", root))
        git = f"shell git -C {root} add harness/teacher_ping.txt && git -C {root} -c commit.gpgsign=false commit -m x"
        self.assertTrue(approve_student(git, root))
        both = f"write_file {root}/a.py and /home/stefan/.config/botwidget/widget.json"
        self.assertFalse(approve_student(both, root))

    def test_a_task_waits_until_the_widget_is_idle(self):
        states = iter([{"active": True}, {"active": True}, {"active": False}])
        sent = []
        clock = {"t": 0.0}

        def now():
            return clock["t"]

        def sleep(_span):
            clock["t"] += 1

        self.assertTrue(wait_until_idle(lambda: next(states), 5, now=now, sleep=sleep))
        stuck = {"active": True}
        self.assertFalse(wait_until_idle(lambda: stuck, 2, now=now, sleep=sleep))
        self.assertEqual(send_when_idle(lambda: stuck, lambda text: sent.append(text), "hi", 1,
                                         now=now, sleep=sleep),
                         {"ok": False, "error": "still active"})
        self.assertEqual(sent, [])
        idle = {"active": False}
        self.assertEqual(send_when_idle(lambda: idle, lambda text: {"ok": True, "text": text}, "hi", 1,
                                         now=now, sleep=sleep)["text"], "hi")

    def test_home_is_not_a_place_for_the_student_worktree(self):
        self.assertEqual(student_worktree("", "/tmp/t-teacher2/student"),
                         os.path.realpath("/tmp/t-teacher2/student"))
        self.assertEqual(student_worktree(os.path.expanduser("~"), "/tmp/t-teacher2/student"),
                         os.path.realpath("/tmp/t-teacher2/student"))
        with tempfile.TemporaryDirectory() as folder:
            scratch = os.path.join(folder, "scratch")
            self.assertEqual(student_worktree(folder, scratch), os.path.realpath(scratch))
            outside = "/tmp/t-teacher2/student"
            self.assertEqual(student_worktree(folder, outside), os.path.join(os.path.realpath(folder), ".teacher-student"))

    def test_self_check_reads_what_it_wrote(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self_check(folder)
            self.assertTrue(path.endswith("selfcheck.txt"))

    def test_failing_test_name_reads_unittest(self):
        self.assertEqual(failing_test_name("ok\nFAIL: test_a (tests.T)\n"), "test_a (tests.T)")

    def test_a_claimed_file_or_commit_that_is_missing_is_a_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=folder, check=True)
            with open(os.path.join(folder, "ok.txt"), "w") as fh:
                fh.write("ok\n")
            self.assertEqual(false_claims("I wrote ok.txt", folder), [])
            self.assertEqual(false_claims("I wrote missing.txt", folder), ["missing.txt"])
            self.assertEqual(false_claims("committed deadbee", folder), ["deadbee"])
        row = judge(tests_ok=True, health_ok=True, turns=1, elapsed_s=1, claims_ok=False)
        self.assertFalse(row["ok"])
        self.assertEqual(row["failure"], "claim")

    def test_scoreboard_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = [score_row("leave", False, 4, 120, "tests")]
            write_scoreboard(folder, rows, notes=["hint: clamp"])
            with open(os.path.join(folder, "scoreboard.md")) as fh:
                self.assertIn("leave", fh.read())

    def test_a_red_run_resets_and_a_green_run_cherry_picks(self):
        with tempfile.TemporaryDirectory() as folder:
            live = os.path.join(folder, "live")
            other = os.path.join(folder, "other")
            os.makedirs(live)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=live, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=live, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=live, check=True)
            with open(os.path.join(live, "a.txt"), "w") as fh:
                fh.write("a\n")
            subprocess.run(["git", "add", "a.txt"], cwd=live, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=live, check=True)
            good = subprocess.run(["git", "rev-parse", "HEAD"], cwd=live, capture_output=True, text=True, check=True).stdout.strip()
            subprocess.run(["git", "worktree", "add", "--detach", other, "HEAD"], cwd=live, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=other, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=other, check=True)
            with open(os.path.join(other, "b.txt"), "w") as fh:
                fh.write("b\n")
            subprocess.run(["git", "add", "b.txt"], cwd=other, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "student"], cwd=other, check=True)
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=other, capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(promote_or_rollback(live, sha, good, False, True), "rollback")
            self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=live, capture_output=True, text=True).stdout.strip(), good)
            self.assertEqual(promote_or_rollback(live, sha, good, True, True), "merge")
            self.assertTrue(os.path.exists(os.path.join(live, "b.txt")))
            with open(os.path.join(live, "dirty.txt"), "w") as fh:
                fh.write("x")
            self.assertEqual(promote_or_rollback(live, sha, good, True, True), "dirty")


if __name__ == "__main__":
    unittest.main()
