"""Acceptance test for how long a bubble stays after the pointer leaves."""

import unittest

import inspect

from botwidget.bubble import LEAVE_GRACE_S, LEAVE_MAX_S, LEAVE_MOVING_PX_S, leave_open
import botwidget.qt_ui.bubble_window as bubble_window


class LeaveOpen(unittest.TestCase):
    """Should match the bubble rule: 0.4s, longer while moving faster than 300px/s, never past 1.5s."""

    def test_a_short_leave_stays_open(self):
        self.assertTrue(leave_open(0.2, 0))

    def test_a_still_pointer_closes_after_the_grace(self):
        self.assertFalse(leave_open(0.4, 0))
        self.assertFalse(leave_open(0.5, 300))

    def test_a_fast_pointer_keeps_it_until_the_cap(self):
        self.assertTrue(leave_open(1.0, 301))
        self.assertFalse(leave_open(1.5, 900))

    def test_the_window_uses_the_shared_limits(self):
        self.assertEqual((LEAVE_GRACE_S, LEAVE_MOVING_PX_S, LEAVE_MAX_S), (0.4, 300, 1.5))
        source = inspect.getsource(bubble_window)
        self.assertNotIn("LEAVE_GRACE_S =", source)
        self.assertIn("leave_open", source)


if __name__ == "__main__":
    unittest.main()
