import math
import unittest

from botwidget import avatar


class CircleStaysRound(unittest.TestCase):
    def test_the_circle_is_round_however_it_turns(self):
        for pitch, yaw in [(0, 0), (0, 45), (0, 70), (25, 30), (40, 0), (-30, -60)]:
            pts = avatar._openbot_outline("cercle", pitch, yaw)
            radii = [math.hypot(x, y) for x, y in pts]
            self.assertLess(max(radii) - min(radii), 0.01, (pitch, yaw))


if __name__ == "__main__":
    unittest.main()
