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


class BodyMemoryPersistenceTests(unittest.TestCase):
    def test_dump_and_restore_keep_fresh_references_and_drop_expired_or_broken_ones(self):
        import json
        memory=BodyMemory()
        memory.learn('a',np.eye(4,dtype=np.float32)[0],100)
        memory.learn('a',np.eye(4,dtype=np.float32)[1],100.5,anchored_at=90)
        memory.learn('old',np.eye(4,dtype=np.float32)[2],1)
        data=json.loads(json.dumps(memory.dump()))
        data['bad']=[{'feature':'x'}]
        restored=BodyMemory()
        self.assertEqual(restored.restore(data,200,300),3)
        self.assertEqual(restored.restore(data,200,150),2)   # 'old' (seen at 1) is past the lifetime.
        self.assertNotIn('bad',restored.references)
        self.assertFalse(restored.dirty)
        score=float(restored.references['a'][0]['feature']@normalized(np.eye(4,dtype=np.float32)[0]))
        self.assertAlmostEqual(score,1,places=5)


class BodySoloGuardTests(unittest.TestCase):
    def test_a_lone_reference_needs_a_higher_score_than_a_pair(self):
        def vec(angle):   # unit vector at a given angle from the reference.
            return np.array([np.cos(angle),np.sin(angle),0,0],dtype=np.float32)
        near=vec(np.arccos(.72))   # score .72: above .70, below .70+.05
        alone=BodyMemory();alone.learn('pai',vec(0),0)
        for i in range(3):
            result=alone.match('k',near,i*.3,.70,.08)
        self.assertEqual(result,(None,result[1]))
        pair=BodyMemory();pair.learn('pai',vec(0),0);pair.learn('outra',np.array([0,0,1,0],dtype=np.float32),0)
        for i in range(3):
            result=pair.match('k',near,i*.3,.70,.08)
        self.assertEqual(result[0],'pai')
        strong=vec(np.arccos(.9))
        for i in range(3):
            result=alone.match('s',strong,i*.3,.70,.08)
        self.assertEqual(result[0],'pai')
