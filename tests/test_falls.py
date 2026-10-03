import unittest

import numpy as np

from app.falls import FallDetector, is_lying, torso_angle


def person(shoulder, hip, confidence=.9):
    """17 COCO keypoints with only shoulders and hips visible."""
    points = np.zeros((17, 3))
    points[5] = (shoulder[0] - 10, shoulder[1], confidence)
    points[6] = (shoulder[0] + 10, shoulder[1], confidence)
    points[11] = (hip[0] - 8, hip[1], confidence)
    points[12] = (hip[0] + 8, hip[1], confidence)
    return points


STANDING = person((100, 100), (100, 220))
LYING = person((100, 400), (230, 410))
FRAME = (640, 480)


class FallTests(unittest.TestCase):
    def test_torso_direction(self):
        self.assertLess(torso_angle(STANDING), 10)
        self.assertGreater(torso_angle(LYING), 80)
        self.assertIsNone(torso_angle(person((1, 1), (1, 1), confidence=.1)))

    def test_keypoints_win_over_the_box_and_the_box_is_a_fallback(self):
        wide_box = (0, 300, 300, 420)
        self.assertFalse(is_lying(wide_box, STANDING))  # Arms open, still standing.
        self.assertTrue(is_lying(wide_box, None))
        self.assertFalse(is_lying((0, 0, 100, 300), None))

    def run_detector(self, points, seconds, zones=(), limit=30, start=0):
        detector, events = FallDetector(), []
        for step in range(int(seconds * 5)):
            now = start + step / 5
            lying, falls = detector.update(now, [(40, 380, 260, 440)], [1], [points], FRAME, list(zones), limit)
            events += [(key, now) for key in falls]
        return lying, events

    def test_alerts_once_after_the_limit(self):
        lying, events = self.run_detector(LYING, 40)
        self.assertEqual([key for key, _ in events], [1])
        self.assertAlmostEqual(events[0][1], 30, delta=.3)
        self.assertGreater(lying[1], 39)

    def test_standing_or_short_lying_does_not_alert(self):
        self.assertEqual(self.run_detector(STANDING, 60)[1], [])
        self.assertEqual(self.run_detector(LYING, 20)[1], [])

    def test_ignored_zone_by_hip_position(self):
        # Hips at (230, 410) of 640x480: inside a sofa zone on the lower right.
        self.assertEqual(self.run_detector(LYING, 60, zones=[[.3, .7, 1, 1]])[1], [])
        self.assertEqual(len(self.run_detector(LYING, 60, zones=[[0, 0, .2, .2]])[1]), 1)

    def test_short_gaps_keep_counting_and_getting_up_resets(self):
        detector = FallDetector()
        box = (40, 380, 260, 440)
        update = lambda now, points: detector.update(now, [box], [1], [points], FRAME, [], 30)
        update(0, LYING)
        self.assertEqual(update(2, LYING)[0][1], 2)   # A 2 s gap keeps counting.
        self.assertEqual(update(10, LYING)[0][1], 0)  # An 8 s gap starts over.
        for now in range(11, 16):
            self.assertEqual(update(now, STANDING), ({}, []))
        alerts = [now for now in range(16, 80) if update(now, LYING)[1]]
        self.assertEqual(alerts, [46])  # Once per episode, 30 s after lying down again.


if __name__ == '__main__':
    unittest.main()
