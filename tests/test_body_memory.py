import unittest
import numpy as np
# Set the isolated data directory before importing application modules.
import test_system
from app.body import BodyMemory,BodyAnchors
from app.faces import normalized


class BodyMemoryTests(unittest.TestCase):
    def test_temporal_average_reduces_noise_and_resets_after_loss_or_gap(self):
        memory=BodyMemory()
        for i in range(5):
            a=np.zeros(6,dtype=np.float32);a[0]=1;a[i+1]=.6
            b=a.copy();b[i+1]=-.6
            reference=memory.smooth('a',a,i*.3)
            query=memory.smooth('b',b,i*.3)
        self.assertLess(float(normalized(a)@normalized(b)),.85)
        self.assertGreater(float(reference@query),.85)
        memory.retain(set())
        np.testing.assert_allclose(memory.smooth('a',b,2),normalized(b))
        np.testing.assert_allclose(memory.smooth('a',a,5),normalized(a))
        np.testing.assert_allclose(memory.smooth('a',b,1),normalized(b))

    def test_reference_limits_preserve_face_views_and_anchor_expiry(self):
        memory=BodyMemory()
        for i in range(40):
            v=np.eye(40,dtype=np.float32)[i]
            memory.learn('a',v,i)
            memory.learn('a',v,i+.4,anchored_at=0)
        refs=memory.references['a']
        self.assertEqual(len(refs),24)
        self.assertEqual(sum(r['source']=='face' for r in refs),12)
        memory.prune(61,60)
        self.assertTrue(all(r['source']=='face' for r in memory.references['a']))

    def test_continuous_track_does_not_extend_ten_second_learning_window(self):
        anchors=BodyAnchors();boxes=[[0,0,100,200]]
        anchors.observe([1],boxes,{'1':{}},{'1':{'source':'face','seen':100,'person_id':'a'}},100)
        for t in range(101,111):
            self.assertEqual(anchors.observe([1],boxes,{}, {},t)['1'],('a',100))
        self.assertEqual(anchors.observe([1],boxes,{}, {},111),{})
