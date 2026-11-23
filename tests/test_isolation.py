"""What keeps a test run from reaching the machine it runs on. The CI runners have no OpenBot, no Grok Bot and a
home that is empty; every run here gets the same, so a test that needs more fails on the first run, not on CI."""

import os
import tempfile
import unittest

import tests


class Isolation(unittest.TestCase):
    def test_the_home_of_a_test_run_is_a_temporary_folder_and_not_the_real_one(self):
        home = os.path.realpath(os.path.expanduser("~"))
        self.assertTrue(home.startswith(os.path.realpath(tempfile.gettempdir())), home)
        self.assertEqual(home, os.path.realpath(tests._HOME))

    @unittest.skipIf(os.name == "nt", "the real home comes from pwd")
    def test_none_of_the_places_that_hold_state_is_in_the_real_home(self):
        import pwd
        real = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)
        from botwidget.openbot import OPENBOT_DIR
        from harness import approvals
        from harness.agent.tools import TRASH
        for path in (OPENBOT_DIR, approvals.PATH, TRASH):
            self.assertFalse(os.path.realpath(path).startswith(real + os.sep), path)

    def test_no_app_is_installed_in_that_home(self):
        from botwidget.openbot import gbot_installed, openbot_installed
        self.assertFalse(openbot_installed() or gbot_installed(), "the same as a CI runner")
