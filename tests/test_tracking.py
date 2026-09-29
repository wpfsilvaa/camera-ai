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
