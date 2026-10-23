"""Ctrl+C quits the widget instead of printing a traceback."""

import os
import signal
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botwidget.qt_ui.app import install_quit_signals


class QuitSignalTests(unittest.TestCase):
    def test_sigint_and_sigterm_quit_without_raising(self):
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)

        class App:
            def __init__(self):
                self.quit_called = 0

            def quit(self):
                self.quit_called += 1

        class Wake:
            def start(self, ms):
                self.ms = ms

        app = App()
        wake = Wake()
        try:
            stop = install_quit_signals(app, wake)
            stop(signal.SIGINT, None)
            stop(signal.SIGTERM, None)
            self.assertEqual(app.quit_called, 2)
            self.assertEqual(wake.ms, 500)
            self.assertIs(signal.getsignal(signal.SIGINT), stop)
            self.assertIs(signal.getsignal(signal.SIGTERM), stop)
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    unittest.main()
