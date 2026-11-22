import unittest
import numpy as np
from ultralytics.engine.results import Boxes
from app.tracking import PersonTracker


class TrackingTests(unittest.TestCase):
    def update(self, tracker, timestamp, scores=(.9,)):
        rows = [[20+i*150, 20, 100+i*150, 180, score, 0] for i, score in enumerate(scores)]
        return tracker.update(Boxes(np.asarray(rows, dtype=np.float32).reshape(-1,6), (240,640)),
                              np.zeros((240,640,3),dtype=np.uint8), timestamp)[1]

    def test_weak_detection_continues_but_does_not_start_track(self):
        tracker=PersonTracker()
        self.assertEqual(self.update(tracker,0,(.2,)),[])
        self.update(tracker,.1)
        ids=self.update(tracker,.2)
        self.assertEqual(len(ids),1)
        for t in range(3,20):
            self.assertEqual(self.update(tracker,t/10,(.2,)),ids)

    def test_lost_expiry_uses_seconds_at_different_frame_rates(self):
        for fps in (5,24,25,30):
            with self.subTest(fps=fps):
                tracker=PersonTracker()
                initial=self.update(tracker,0)
                for n in range(1,fps): self.update(tracker,n/fps,())
                self.assertEqual(self.update(tracker,1),initial)
                for n in range(1,3*fps): self.update(tracker,1+n/fps,())
                self.update(tracker,4)
                new=self.update(tracker,4+1/fps)
                self.assertEqual(len(new),1)
                self.assertNotEqual(initial,new)

    def test_camera_ids_are_independent_and_rollback_does_not_reuse_id(self):
        tracker=PersonTracker()
        first=self.update(tracker,10)
        self.update(PersonTracker(),0)
        self.update(tracker,10.1,(.9,.9))
        two=self.update(tracker,10.2,(.9,.9))
        self.assertEqual(len(set(two)),2)
        self.assertIn(first[0],two)
        rolled=self.update(tracker,1)
        self.assertTrue(set(rolled).isdisjoint(two))


class AppearanceTrackerTests(unittest.TestCase):
    class FakeEncoder:
        def __init__(self):
            self.calls = []

        def embed(self, frame, box):
            self.calls.append(tuple(int(v) for v in box))
            vector = np.zeros(8, dtype=np.float32)
            vector[int(box[0] // 150) % 8] = 1   # People standing in different places look different.
            return vector

    def tracker(self, encoder):
        from unittest.mock import patch
        with patch('app.body.shared_encoder', return_value=encoder):
            return PersonTracker(appearance=True)

    def update(self, tracker, timestamp, people=1, scores=None):
        rows = [[20 + i * 150, 20, 100 + i * 150, 180, (scores or [.9] * people)[i], 0] for i in range(people)]
        return tracker.update(Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), (240, 640)),
                              np.zeros((240, 640, 3), dtype=np.uint8), timestamp)[1]

    def test_the_network_runs_only_for_new_people_not_for_those_already_followed(self):
        encoder = self.FakeEncoder()
        tracker = self.tracker(encoder)
        self.assertTrue(tracker.appearance)
        ids = []
        for n in range(12):
            ids = self.update(tracker, n / 5)
        self.assertEqual(len(encoder.calls), 1, 'a pessoa parada só deveria ser codificada na primeira vez')
        for n in range(12, 20):
            ids2 = self.update(tracker, n / 5, people=2)
        self.assertEqual(len(encoder.calls), 2, 'só a pessoa nova deveria ser codificada')
        self.assertIn(ids[0], ids2)
        cost = tracker.cost()
        self.assertEqual((cost['appearance'], cost['frames']), (True, 20))
        self.assertLessEqual(cost['encodes_per_100'], 10)

    def test_low_confidence_detections_never_run_the_network(self):
        encoder = self.FakeEncoder()
        tracker = self.tracker(encoder)
        for n in range(5):
            self.update(tracker, n / 5, scores=[.2])
        self.assertEqual(encoder.calls, [])

    def test_at_most_one_new_person_is_encoded_per_frame_and_the_next_frames_catch_up(self):
        encoder = self.FakeEncoder()
        tracker = self.tracker(encoder)
        self.update(tracker, 0, people=4)
        self.assertEqual(len(encoder.calls), 1)
        for n in range(1, 8):
            self.update(tracker, n / 5, people=4)
        self.assertEqual(len(encoder.calls), 4, 'as outras pessoas deveriam ser codificadas nos quadros seguintes, uma por vez')

    def test_a_missing_model_falls_back_to_the_plain_tracker(self):
        from unittest.mock import patch
        with patch('app.body.shared_encoder', side_effect=RuntimeError('Modelo corporal ausente')):
            tracker = PersonTracker(appearance=True)
        self.assertFalse(tracker.appearance)
        self.assertIn('indisponível', tracker.cost()['error'])
        ids = []
        for n in range(4):
            ids = self.update(tracker, n / 5)
        self.assertEqual(len(ids), 1)

    def test_plain_tracker_reports_zero_encodes(self):
        tracker = PersonTracker()
        for n in range(3):
            self.update(tracker, n / 5)
        self.assertEqual((tracker.cost()['appearance'], tracker.cost()['encodes_per_100']), (False, 0))
