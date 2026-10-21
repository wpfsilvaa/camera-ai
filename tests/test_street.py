import tempfile
import unittest
from pathlib import Path

from app.street import GAP, REPEAT, StreetMode


class StreetModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'street.json'
        self.mode = StreetMode(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_silent_while_off(self):
        self.assertFalse(any(self.mode.update('door', True, t, 10) for t in range(0, 100)))

    def test_alert_only_after_the_stranger_stays_for_the_delay(self):
        self.mode.set(True, 0)
        due = [t for t in range(0, 30) if self.mode.update('door', True, t, 10)]
        self.assertEqual(due, [10])   # Once; then REPEAT keeps it quiet.

    def test_leaving_or_being_recognised_resets_the_wait(self):
        self.mode.set(True, 0)
        for t in range(0, 8):
            self.mode.update('door', True, t, 10)
        self.mode.update('door', False, 8 + GAP + 1, 10)   # Gone for a while.
        self.assertFalse(self.mode.update('door', True, 8 + GAP + 2, 10))
        self.assertTrue(self.mode.update('door', True, 8 + GAP + 12, 10))

    def test_cameras_are_independent_and_alerts_repeat_after_a_pause(self):
        self.mode.set(True, 0)
        self.assertTrue(self.mode.update('a', True, 0, 0))
        self.assertTrue(self.mode.update('b', True, 0, 0))
        self.assertFalse(self.mode.update('a', True, REPEAT - 1, 0))
        self.assertTrue(self.mode.update('a', True, REPEAT, 0))

    def test_turning_off_cancels_the_wait_and_state_survives_restart(self):
        self.mode.set(True, 5)
        self.mode.update('a', True, 6, 10)
        self.mode.set(False)
        self.assertFalse(self.mode.update('a', True, 30, 10))
        self.mode.set(True, 50)
        self.assertEqual(StreetMode(self.path).state(), {'armed': True, 'since': 50})


class CameraReportTests(unittest.TestCase):
    def test_only_unrecognised_people_count_as_strangers(self):
        import numpy as np
        from app.camera import CameraWorker
        from app.config import CameraSettings
        worker = CameraWorker.__new__(CameraWorker)
        worker.camera_id, seen = 'door', []
        worker.on_street = lambda camera, name, stranger, now, jpeg: seen.append(stranger)
        frame, settings = np.zeros((100, 100, 3), np.uint8), CameraSettings(street_guard=True)
        boxes = [[0, 0, 10, 10], [20, 20, 40, 40]]
        worker.check_street(boxes, [1, 2], {'1': {'person_id': 'father'}}, frame, 1.0, settings)   # 2 is unknown.
        worker.check_street(boxes[:1], [1], {'1': {'person_id': 'father'}}, frame, 2.0, settings)
        worker.check_street([], [], {}, frame, 3.0, settings)
        self.assertEqual(seen, [True, False, False])


class ViewersTests(unittest.TestCase):
    def test_counts_open_streams(self):
        from app.viewers import Viewers
        viewers = Viewers()
        self.assertEqual(viewers.total(), 0)
        with viewers.watch('main'):
            with viewers.watch('main'), viewers.watch('door'):
                self.assertEqual(viewers.total(), 3)
            self.assertEqual(viewers.total(), 1)
        self.assertEqual(viewers.total(), 0)
        with viewers.watch('main'):
            self.assertEqual((viewers.count('main'), viewers.count('door')), (1, 0))


if __name__ == '__main__':
    unittest.main()
