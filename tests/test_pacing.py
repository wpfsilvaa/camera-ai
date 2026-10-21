import tempfile
import unittest
from pathlib import Path

from app.config import CameraSettings
from app.db import Database
from app.pacing import DetectionPacing, TouchThrottle, analysis_wanted, preview_due


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



class SentinelTests(unittest.TestCase):
    def test_window_wraps_past_midnight(self):
        from app.pacing import in_window
        self.assertTrue(in_window(23, 22, 6) and in_window(2, 22, 6) and in_window(22, 22, 6))
        self.assertFalse(in_window(6, 22, 6) or in_window(12, 22, 6))
        self.assertTrue(in_window(10, 8, 18) and not in_window(18, 8, 18))
        self.assertFalse(in_window(3, 5, 5))   # Same hour: never.

    def test_reader_only_grabs_between_decoded_frames(self):
        import threading
        import time as clock
        from app.camera import LiveFrames

        class Capture:
            def __init__(self):
                self.reads = self.grabs = 0
                self.done = threading.Event()

            def read(self):
                self.reads += 1
                clock.sleep(.002)
                return True, object()

            def grab(self):
                self.grabs += 1
                clock.sleep(.002)
                if self.grabs > 150:
                    self.done.set()
                    return False
                return True

        capture = Capture()
        live = LiveFrames.__new__(LiveFrames)
        live.capture, live.condition, live.stopping = capture, threading.Condition(), threading.Event()
        live.frame, live.timestamp, live.sequence, live.consumed, live.failed = None, 0, 0, 0, False
        from collections import deque
        live.arrivals, live.interval = deque(maxlen=90), .05
        live.run()   # Runs until grab() reports a failure.
        self.assertTrue(live.failed)
        self.assertLess(capture.reads, 12)       # About one decoded frame per 50 ms, not one per frame.
        self.assertGreater(capture.grabs, 100)


class AnalysisPauseTests(unittest.TestCase):
    def test_manual_pause_wins_except_inside_the_watch_hours(self):
        paused = CameraSettings(analysis_enabled=False, sentinel_enabled=True, sentinel_always=True, sentinel_start_hour=22, sentinel_end_hour=6)
        self.assertFalse(analysis_wanted(paused, 14))   # "Watch mode all day" does not undo the pause button.
        self.assertTrue(analysis_wanted(paused, 23))    # The night net stays.
        self.assertTrue(analysis_wanted(CameraSettings(analysis_enabled=True), 14))
        self.assertFalse(analysis_wanted(CameraSettings(analysis_enabled=False), 23))


class PreviewTests(unittest.TestCase):
    def test_drawn_for_every_frame_only_while_somebody_watches(self):
        self.assertTrue(preview_due(True, 100.0, 100.01))        # Watched: every frame.
        self.assertTrue(preview_due(False, None, 100.0))         # First one is always made.
        self.assertFalse(preview_due(False, 100.0, 100.4))       # Nobody: skipped...
        self.assertTrue(preview_due(False, 100.0, 101.0))        # ... but refreshed once a second.


class TranscodeDeferralTests(unittest.TestCase):
    def test_waits_for_a_free_camera_but_not_forever(self):
        from app.jobs import DEFER_SECONDS, transcode_due
        clip = {'ended': 1000.0, 'started': 990.0}
        self.assertTrue(transcode_due(False, clip, 1001))
        self.assertFalse(transcode_due(True, clip, 1001))
        self.assertTrue(transcode_due(True, clip, 1000 + DEFER_SECONDS))


class SkeletonTests(unittest.TestCase):
    def test_draws_limbs_and_the_head_direction_without_touching_the_input(self):
        import numpy as np
        from app.overlay import draw_skeleton
        frame = np.zeros((200, 200, 3), np.uint8)
        points = np.zeros((17, 3), np.float32)
        for index, (x, y) in {0: (100, 40), 3: (90, 40), 4: (95, 40), 5: (80, 70), 6: (120, 70), 9: (60, 110), 11: (85, 120), 12: (115, 120)}.items():
            points[index] = (x, y, .9)
        drawn = draw_skeleton(frame, [points, None], 1.0)
        self.assertEqual(int(frame.sum()), 0)                  # The original is left alone.
        self.assertGreater(int(drawn.sum()), 0)
        self.assertGreater(int(drawn[40, 110:150].sum()), 0)    # The arrow runs on from the nose, away from the ears.
        self.assertEqual(draw_skeleton(frame, [None]).shape, frame.shape)


if __name__ == '__main__':
    unittest.main()
