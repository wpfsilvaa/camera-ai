import tempfile
import unittest
from pathlib import Path

from app.config import CameraSettings
from app.db import Database
from app.pacing import DetectionPacing, TouchThrottle


class DetectionPacingTests(unittest.TestCase):
    def setUp(self):
        self.settings = CameraSettings(detection_fps=30, idle_detection_fps=15)
        self.pacing = DetectionPacing(hold=3)

    def test_idle_house_uses_the_lower_rate(self):
        self.assertEqual(self.pacing.fps(self.settings, False, 100), 15)

    def test_someone_present_uses_the_full_rate(self):
        self.assertEqual(self.pacing.fps(self.settings, True, 100), 30)

    def test_full_rate_holds_briefly_after_the_person_leaves(self):
        self.pacing.fps(self.settings, True, 100)
        self.assertEqual(self.pacing.fps(self.settings, False, 102.9), 30)
        self.assertEqual(self.pacing.fps(self.settings, False, 103.1), 15)

    def test_idle_rate_never_exceeds_the_detection_rate(self):
        settings = CameraSettings(detection_fps=5, idle_detection_fps=15)
        self.assertEqual(self.pacing.fps(settings, False, 100), 5)

    def test_reset_forgets_recent_activity(self):
        self.pacing.fps(self.settings, True, 100)
        self.pacing.reset()
        self.assertEqual(self.pacing.fps(self.settings, False, 100.5), 15)

    def test_default_is_half_rate(self):
        self.assertEqual(CameraSettings().idle_detection_fps, 15)


class TouchThrottleTests(unittest.TestCase):
    def test_writes_at_most_once_per_interval(self):
        touch = TouchThrottle(5)
        self.assertTrue(touch.due(100, 1))
        self.assertFalse(touch.due(100.5, 1))
        self.assertFalse(touch.due(104.9, 1))
        self.assertTrue(touch.due(105.1, 1))

    def test_a_new_peak_of_people_is_written_immediately(self):
        touch = TouchThrottle(5)
        touch.due(100, 1)
        self.assertTrue(touch.due(101, 2))
        self.assertFalse(touch.due(102, 2))

    def test_reset_starts_a_new_event_from_scratch(self):
        touch = TouchThrottle(5)
        touch.due(100, 3)
        touch.reset()
        self.assertTrue(touch.due(100.1, 1))


class DatabaseTests(unittest.TestCase):
    def test_connections_use_normal_synchronous_with_wal(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'h.sqlite3')
            with db.connect() as conn:
                self.assertEqual(conn.execute('PRAGMA synchronous').fetchone()[0], 1)
                self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')



class MotionGateTests(unittest.TestCase):
    def frame(self, box=None):
        import numpy as np
        image = np.full((360, 640, 3), 80, dtype=np.uint8)
        if box:
            x, y, w, h = box
            image[y:y + h, x:x + w] = 220
        return image

    def test_first_frame_is_always_analysed(self):
        from app.pacing import MotionGate
        self.assertFalse(MotionGate().skip(self.frame(), 100))

    def test_still_room_skips_until_the_forced_check(self):
        from app.pacing import MotionGate
        gate = MotionGate(force_seconds=2)
        gate.skip(self.frame(), 100)
        self.assertTrue(gate.skip(self.frame(), 100.5))
        self.assertTrue(gate.skip(self.frame(), 101.9))
        self.assertFalse(gate.skip(self.frame(), 102.1))
        self.assertTrue(gate.skip(self.frame(), 102.3))

    def test_motion_runs_the_model(self):
        from app.pacing import MotionGate
        gate = MotionGate(force_seconds=60)
        gate.skip(self.frame(), 100)
        self.assertTrue(gate.skip(self.frame(), 100.2))
        self.assertFalse(gate.skip(self.frame((200, 100, 120, 200)), 100.4))

    def test_sensor_noise_is_not_motion(self):
        import numpy as np
        from app.pacing import MotionGate
        gate = MotionGate(force_seconds=60)
        rng = np.random.default_rng(1)
        base = self.frame().astype(np.int16)
        gate.skip(base.astype(np.uint8), 100)
        noisy = np.clip(base + rng.integers(-4, 5, base.shape), 0, 255).astype(np.uint8)
        self.assertTrue(gate.skip(noisy, 100.2))

    def test_reset_analyses_the_next_frame(self):
        from app.pacing import MotionGate
        gate = MotionGate(force_seconds=60)
        gate.skip(self.frame(), 100)
        gate.reset()
        self.assertFalse(gate.skip(self.frame(), 100.1))

    def test_pacing_idle_only_after_the_hold(self):
        pacing = DetectionPacing(hold=3)
        self.assertTrue(pacing.idle(100))
        pacing.fps(CameraSettings(), True, 100)
        self.assertFalse(pacing.idle(102))
        self.assertTrue(pacing.idle(103.5))

if __name__ == '__main__':
    unittest.main()
