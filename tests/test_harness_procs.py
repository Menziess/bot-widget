"""Stopping a command stops what it started, whether the caller holds the Popen or only a pid."""

import os
import subprocess
import tempfile
import time
import unittest

from harness.agent.procs import group_kwargs, stop


def start(marker: str) -> subprocess.Popen:
    return subprocess.Popen(f"(sleep 2; echo late > {marker}) & sleep 30", shell=True, **group_kwargs())


class Stop(unittest.TestCase):
    def setUp(self):
        self.marker = tempfile.mktemp(prefix="bw-procs-")
        self.addCleanup(lambda: os.path.exists(self.marker) and os.remove(self.marker))

    def check(self):
        time.sleep(2.5)
        self.assertFalse(os.path.exists(self.marker), "the child went with the shell")

    def test_a_popen_is_stopped_with_its_children(self):
        proc = start(self.marker)
        stop(proc)
        self.assertIsNotNone(proc.poll())
        self.check()

    def test_a_pid_alone_is_enough(self):
        proc = start(self.marker)
        stop(proc.pid)
        proc.wait(5)
        self.check()

    def test_a_process_that_is_gone_is_left_alone(self):
        proc = subprocess.Popen("true", shell=True, **group_kwargs())
        proc.wait(5)
        stop(proc)
        stop(proc.pid)
