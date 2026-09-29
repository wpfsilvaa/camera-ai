import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import httpx
import numpy as np

# Share the isolated environment established by the main test suite.
if 'test_system' not in sys.modules:
    spec = importlib.util.spec_from_file_location('test_system', Path(__file__).with_name('test_system.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['test_system'] = module
    spec.loader.exec_module(module)

from app.config import Config, Settings
from app.db import Database
from app.jobs import Jobs
from app.recognition import Recognition, match_person, normalized


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name)
        self.db = Database(self.path / 'history.sqlite3')
        self.recognition = Recognition(self.db, self.path / 'people')

    def tearDown(self):
        self.temporary.cleanup()

    def sample(self, event_id, key='1', vector=(1.,0.,0.), timestamp=100):
        track = self.db.execute('INSERT INTO person_tracks(event_id,track_key,started,last_seen) VALUES(?,?,?,?)', (event_id,key,timestamp,timestamp+2))
        sample = f'{track:032x}'
        self.db.execute('INSERT INTO person_samples(id,track_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)', (sample,track,timestamp,normalized(vector).tobytes(),'sface-test',100))
        self.db.execute("UPDATE person_tracks SET recognition_kind='face' WHERE id=?",(track,))
        return track,sample

    def event(self):
        event = self.db.start_event(100,2)
        self.db.end_event(event,110,'absence')
        return event

    def test_diagnostics_explain_missing_face_and_matching(self):
        from types import SimpleNamespace
        self.recognition.encoder=SimpleNamespace(version='sface-test')
        reference,sample=self.sample(self.event())
        self.recognition.confirm(reference,'father',sample)
        event=self.event();boxes=[[0,0,100,200]]
        self.recognition.observe_faces(event,boxes,[1],{},200,Settings(),diagnostics={'1':{'reason':'blurred_face','sharpness':12}})
        detail=self.db.track_details(event)[0]['diagnostic']
        self.assertEqual(detail['reason'],'blurred_face')
        for now in (201,201.4,201.8):
            self.recognition.observe_faces(event,boxes,[1],{'1':self.face()},now,Settings())
        detail=self.db.track_details(event)[0]['diagnostic']
        self.assertEqual(detail['reason'],'matched')
        self.assertEqual(detail['agreement'],3)

    def test_better_late_samples_replace_unconfirmed_and_protect_confirmed(self):
        from types import SimpleNamespace
        self.recognition.encoder=SimpleNamespace(version='sface-test')
        event=self.event();track,_=self.sample(event)
        self.db.execute('DELETE FROM person_samples WHERE track_id=?',(track,))
        # Twelve distinct vectors fill the review buffer.
        for i in range(12):
            face=self.face();face['feature']=np.eye(13,dtype=np.float32)[i];face['quality']=40+i
            self.recognition.save_best_sample(track,face,100+i)
        self.assertEqual(len(self.db.track_details(event)[0]['samples']),12)
        first=self.db.rows('SELECT id FROM person_samples WHERE track_id=? ORDER BY quality',(track,))[0]['id']
        self.db.execute("UPDATE person_samples SET person_id='father' WHERE id=?",(first,))
        better=self.face();better['feature']=np.eye(13,dtype=np.float32)[12];better['quality']=150
        self.recognition.save_best_sample(track,better,200)
        samples=self.db.track_details(event)[0]['samples']
        self.assertEqual(len(samples),12)
        self.assertEqual(samples[0]['quality'],150)
        self.assertTrue(any(s['id']==first and s['person_id']=='father' for s in samples))
        self.recognition.save_best_sample(track,better,202)
        self.assertEqual(len(self.db.track_details(event)[0]['samples']),12)

    def test_rejects_ambiguous_or_distant_faces(self):
        gallery = [{'person_id':'father','event_id':1,'feature':normalized([1,0,0])}]
        self.assertEqual(match_person([1,0,0],gallery)[0],'father')
        gallery.append({**gallery[0],'event_id':2})
        self.assertEqual(match_person([1,.01,0],gallery)[0],'father')
        self.assertIsNone(match_person([0,1,0],gallery)[0])
        # Even an alternative profile with only one confirmed event prevents an ambiguous match.
        gallery.append({'person_id':'other','event_id':3,'feature':normalized([1,.01,0])})
        self.assertIsNone(match_person([1,0,0],gallery)[0])

    def test_multiple_people_separate_and_correction_removes_wrong_examples(self):
        event = self.event()
        maria = self.recognition.create_person('Maria')
        track1,sample1 = self.sample(event,'1')
        track2,sample2 = self.sample(event,'2',(0,1,0))
        self.recognition.confirm(track1,'father',sample1)
        self.recognition.confirm(track2,maria,sample2)
        people = self.db.track_details(event)
        self.assertEqual({p['name'] for p in people},{'Meu pai','Maria'})
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'father')
        self.recognition.confirm(track1,maria,sample1)
        self.assertEqual(self.db.rows('SELECT COUNT(*) AS n FROM person_samples WHERE person_id=\'father\'')[0]['n'],0)
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'other')
        self.recognition.confirm(track1,None)
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'unknown')

    def test_cannot_teach_sample_of_another_person_or_unfinished_event(self):
        event = self.event()
        track1,sample1 = self.sample(event,'1')
        track2,sample2 = self.sample(event,'2')
        with self.assertRaises(ValueError): self.recognition.confirm(track1,'father',sample2)
        self.db.execute('UPDATE events SET ended=NULL WHERE id=?',(event,))
        with self.assertRaises(ValueError): self.recognition.confirm(track1,'father',sample1)

    def test_predictions_never_train_and_forgetting_invalidates_suggestions(self):
        event = self.event()
        track,sample = self.sample(event)
        self.db.execute("UPDATE person_tracks SET suggested_id='father',similarity=.99 WHERE id=?",(track,))
        self.assertEqual(self.recognition.profiles()[0]['examples'],0)
        self.recognition.confirm(track,'father',sample)
        self.assertEqual(self.recognition.profiles()[0]['examples'],1)
        self.recognition.forget('father')
        self.assertEqual(self.recognition.profiles()[0]['examples'],0)
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'father')
        with self.assertRaises(ValueError): self.recognition.forget('father',True)

    def test_model_versions_are_not_mixed(self):
        event = self.event()
        track,sample = self.sample(event)
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder = type('Encoder',(),{'version':'different-model'})()
        self.recognition.load_gallery()
        self.assertEqual(self.recognition.gallery,[])

    def face(self, vector=(1,0,0)):
        return {'feature':normalized(vector),'crop':np.zeros((112,112,3),dtype=np.uint8),'quality':100}

    def test_simultaneous_people_cannot_receive_same_suggested_name(self):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        event=self.db.start_event(200,2)
        boxes=[[10,10,90,160],[130,10,210,160]]
        for now in (200,200.4,200.8):
            self.recognition.observe_faces(event,boxes,[1,2],{'1':self.face(),'2':self.face()},now,Settings())
        tracks=self.db.track_details(event)
        self.assertEqual(len(tracks),2)
        self.assertTrue(all(t['suggested_id'] is None for t in tracks))
        self.assertEqual(self.recognition.labels([1,2],boxes,200.9,3),{})
        self.assertEqual(self.recognition.profiles()[0]['examples'],1)

    def test_temporal_agreement_hold_expiry_and_lost_track(self):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        event=self.db.start_event(200,1)
        boxes=[[10,10,90,160]]
        for now in (200,200.4):
            self.recognition.observe_faces(event,boxes,[1],{'1':self.face()},now,Settings())
            self.assertEqual(self.recognition.labels([1],boxes,now,3),{})
        self.recognition.observe_faces(event,boxes,[1],{'1':self.face()},200.8,Settings())
        self.assertEqual(self.recognition.labels([1],boxes,200.9,3)['1']['name'],'Meu pai')
        self.assertTrue(self.recognition.labels([1],boxes,202,3)['1']['held'])
        self.assertEqual(self.recognition.labels([1],boxes,204,3),{})
        self.recognition.labels([],[],201,3)
        self.assertEqual(self.recognition.labels([1],boxes,201.1,3),{})

    def test_visible_person_keeps_name_when_turning_away_until_hold_expires(self):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        boxes=[[10,10,90,160]]
        settings=Settings()
        for now in (200,200.4,200.8):
            self.recognition.observe_faces(None,boxes,[1],{'1':self.face()},now,settings)
        for now in (202,205,210,215):
            self.recognition.observe_faces(None,boxes,[1],{},now,settings)
            label=self.recognition.labels([1],boxes,now,settings.face_hold_seconds)['1']
            self.assertEqual(label['name'],'Meu pai')
            self.assertTrue(label['held'])
        self.assertEqual(self.recognition.labels([1],boxes,216,settings.face_hold_seconds),{})

    def test_conflicting_face_clears_previous_identity(self):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        boxes=[[10,10,90,160]]
        for now in (200,200.4,200.8):
            self.recognition.observe_faces(None,boxes,[1],{'1':self.face()},now,Settings())
        self.recognition.observe_faces(None,boxes,[1],{'1':self.face((0,1,0))},201.2,Settings())
        self.assertEqual(self.recognition.labels([1],boxes,201.2,3),{})

    def test_widely_spaced_matches_do_not_accumulate_votes(self):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        boxes=[[10,10,90,160]]
        for now in (200,205,210):
            self.recognition.observe_faces(None,boxes,[1],{'1':self.face()},now,Settings())
            self.assertEqual(self.recognition.labels([1],boxes,now,3),{})

    def seed_body(self, settings=None):
        track,sample=self.sample(self.event())
        self.recognition.confirm(track,'father',sample)
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        cfg=settings or Settings()
        boxes=[[10,10,90,180]]
        for now in (200,200.4,200.8):
            self.recognition.observe_faces(None,boxes,[1],{'1':self.face()},now,cfg,{'1':normalized([1,0,0])})
        return cfg,boxes

    def test_face_seeds_body_and_new_track_reentry_restores_name(self):
        cfg,boxes=self.seed_body()
        self.assertIn('father',self.recognition.body_memory.references)
        self.recognition.observe_faces(None,[],[],{},202,cfg)
        event=self.db.start_event(210,1)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(event,boxes,[92],{},now,cfg,{'92':normalized([1,0,0])})
        label=self.recognition.labels([92],boxes,210.9,3)['92']
        self.assertEqual((label['name'],label['source']),('Meu pai','body'))
        track=self.db.track_details(event)[0]
        self.assertEqual((track['suggested_id'],track['recognition_kind']),('father','body'))
        self.assertEqual(len(self.recognition.body_memory.references['father']),1)
        self.assertEqual(self.recognition.profiles()[0]['examples'],1)

    def test_two_face_anchored_people_reenter_with_distinct_names(self):
        cfg,boxes=self.seed_body()
        other=self.recognition.create_person('Outra pessoa')
        track,sample=self.sample(self.event(),vector=(0,1,0))
        self.recognition.confirm(track,other,sample)
        boxes=[[10,10,90,180],[200,10,290,180]]
        faces={'1':self.face(),'2':self.face((0,1,0))}
        bodies={'1':normalized([1,0,0]),'2':normalized([0,1,0])}
        for now in (220,220.4,220.8):
            self.recognition.observe_faces(None,boxes,[1,2],faces,now,cfg,bodies)
        self.recognition.observe_faces(None,[],[],{},222,cfg)
        for now in (225,225.4,225.8):
            self.recognition.observe_faces(None,boxes,[8,9],{},now,cfg,{'8':bodies['2'],'9':bodies['1']})
        labels=self.recognition.labels([8,9],boxes,226,3)
        self.assertEqual(labels['8']['name'],'Outra pessoa')
        self.assertEqual(labels['9']['name'],'Meu pai')
        self.assertTrue(all(v['source']=='body' for v in labels.values()))

    def test_turning_view_is_learned_then_matches_after_disappearance(self):
        cfg,boxes=self.seed_body()
        for i in range(1,13):
            angle=min(i/8,1)*np.pi/2
            self.recognition.observe_faces(None,boxes,[1],{},201+i*.4,cfg,
                {'1':normalized([np.cos(angle),np.sin(angle),0])})
        refs=self.recognition.body_memory.references['father']
        self.assertTrue(any(r['source']=='track' for r in refs))
        self.assertTrue(all(r['seen']==200.8 for r in refs if r['source']=='track'))
        self.recognition.labels([],[],207,15)  # even a loss between recognition jobs invalidates the anchor
        count=len(refs)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(None,boxes,[99],{},now,cfg,{'99':normalized([0,1,0])})
        self.assertEqual(self.recognition.labels([99],boxes,211,15)['99']['source'],'body')
        self.assertEqual(len(refs),count)  # body matches never teach themselves

    def test_body_view_learning_stops_on_overlap_conflict_jump_or_timeout(self):
        for scenario in ('overlap','conflict','jump','timeout','loss'):
            with self.subTest(scenario=scenario):
                self.recognition.reset_tracks()
                cfg,boxes=self.seed_body()
                if scenario=='overlap':
                    self.recognition.labels([1,2],[boxes[0],boxes[0]],201,15)
                elif scenario=='conflict':
                    self.recognition.observe_faces(None,boxes,[1],{'1':self.face((0,1,0))},201,cfg)
                elif scenario=='jump':
                    boxes=[[400,10,480,180]]
                elif scenario=='loss':
                    self.recognition.labels([],[],201,15)
                timestamp=212 if scenario=='timeout' else 201.2
                self.recognition.observe_faces(None,boxes,[1],{},timestamp,cfg,{'1':normalized([0,1,0])})
                self.assertFalse(any(r.get('source')=='track' for r in self.recognition.body_memory.references['father']))

    def test_body_name_tolerates_small_noise_but_not_conflict_or_loss(self):
        cfg,boxes=self.seed_body()
        self.recognition.labels([],[],202,15)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(None,boxes,[2],{},now,cfg,{'2':normalized([1,0,0])})
        # Test a measured comparison below admission but above continuation floor.
        self.recognition.body_memory.features.clear()
        noisy=normalized([.82,np.sqrt(1-.82**2),0])
        self.recognition.observe_faces(None,boxes,[2],{},211.8,cfg,{'2':noisy})
        self.assertTrue(self.recognition.labels([2],boxes,211.8,15)['2']['held'])
        self.assertEqual(self.recognition.labels([2],boxes,214,15),{})
        self.recognition.body_memory.features.clear()
        self.recognition.observe_faces(None,boxes,[2],{},212,cfg,{'2':normalized([0,1,0])})
        self.assertEqual(self.recognition.labels([2],boxes,212,15),{})
        self.recognition.labels([],[],213,15)
        self.assertNotIn('2',self.recognition.body_memory.features)

    def test_body_diagnostic_records_why_return_did_not_match(self):
        cfg,boxes=self.seed_body()
        self.recognition.labels([],[],202,15)
        event=self.db.start_event(210,1)
        self.recognition.observe_faces(event,boxes,[2],{},210,cfg,{'2':normalized([0,1,0])})
        detail=self.db.track_details(event)[0]['diagnostic']['body']
        self.assertEqual(detail['reason'],'below_threshold')
        self.assertEqual(detail['threshold'],.85)
        self.assertEqual(detail['agreement'],0)

    def test_body_without_face_anchor_never_learns(self):
        self.recognition.encoder=type('Encoder',(),{'version':'sface-test'})()
        boxes=[[10,10,90,180]]
        for now in (200,200.4,200.8,201.2):
            self.recognition.observe_faces(None,boxes,[1],{},now,Settings(),{'1':normalized([1,0,0])})
        self.assertEqual(self.recognition.body_memory.references,{})
        self.assertEqual(self.recognition.labels([1],boxes,201.2,3),{})

    def test_body_memory_expiry_and_disabled_mode_require_new_face(self):
        cfg,boxes=self.seed_body(Settings(body_memory_minutes=1))
        self.recognition.observe_faces(None,[],[],{},202,cfg)
        for now in (260,260.4,260.8,261.2,261.6,262):
            self.recognition.observe_faces(None,boxes,[2],{},now,cfg,{'2':normalized([1,0,0])})
        self.assertEqual(self.recognition.labels([2],boxes,262,3),{})
        self.assertEqual(self.recognition.body_memory.references,{})
        cfg,boxes=self.seed_body()
        cfg.body_reid_enabled=False
        self.recognition.observe_faces(None,boxes,[3],{},220,cfg,{'3':normalized([1,0,0])})
        self.assertEqual(self.recognition.body_memory.references,{})
        self.assertEqual(self.recognition.labels([3],boxes,220,3),{})

    def test_conflicting_face_overrides_body_and_duplicates_are_suppressed(self):
        cfg,boxes=self.seed_body()
        self.recognition.observe_faces(None,[],[],{},202,cfg)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(None,boxes,[2],{'2':self.face((0,1,0))},now,cfg,{'2':normalized([1,0,0])})
        self.assertEqual(self.recognition.labels([2],boxes,210.8,3),{})
        boxes=[[10,10,90,180],[200,10,290,180]]
        for now in (212,212.4,212.8):
            self.recognition.observe_faces(None,boxes,[3,4],{},now,cfg,{k:normalized([1,0,0]) for k in ['3','4']})
        self.assertEqual(self.recognition.labels([3,4],boxes,212.8,3),{})

    def test_ambiguous_and_different_clothes_are_rejected(self):
        cfg,boxes=self.seed_body()
        self.recognition.observe_faces(None,[],[],{},202,cfg)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(None,boxes,[2],{},now,cfg,{'2':normalized([0,1,0])})
        self.assertEqual(self.recognition.labels([2],boxes,210.8,3),{})
        self.recognition.body_memory.learn('other',normalized([1,.01,0]),211)
        for now in (212,212.4,212.8):
            self.recognition.observe_faces(None,boxes,[2],{},now,cfg,{'2':normalized([1,0,0])})
        self.assertEqual(self.recognition.labels([2],boxes,212.8,3),{})

    def test_forgetting_and_camera_reset_clear_body_memory(self):
        self.seed_body()
        self.recognition.forget('father')
        self.assertEqual(self.recognition.body_memory.references,{})
        self.seed_body()
        self.recognition.reset_tracks()
        self.assertEqual(self.recognition.body_memory.references,{})

    def test_remove_one_history_example_preserves_record_and_other_examples(self):
        self.seed_body()
        sample=self.db.rows('SELECT * FROM person_samples')[0]
        self.recognition.load_gallery()
        self.assertEqual(len(self.recognition.gallery),1)
        with self.assertRaises(KeyError):
            self.recognition.remove_example('another-person','history',sample['id'])
        self.assertEqual(len(self.recognition.examples('father')['examples']),1)
        self.recognition.remove_example('father','history',sample['id'])
        self.recognition.load_gallery()
        self.assertEqual(self.recognition.gallery,[])
        self.assertEqual(self.recognition.body_memory.references,{})
        self.assertEqual(self.recognition.examples('father')['examples'],[])
        stored=self.db.rows('SELECT * FROM person_samples')[0]
        self.assertIsNone(stored['person_id'])
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'father')
        self.assertEqual(self.db.rows('SELECT person_id,reviewed FROM person_tracks')[0],{'person_id':'father','reviewed':1})
        with self.assertRaises(KeyError):self.recognition.remove_example('father','history',sample['id'])
        self.recognition.confirm(sample['track_id'],'father',sample['id'])
        self.assertEqual(len(self.recognition.examples('father')['examples']),1)

    def test_examples_lists_all_100_history_references_and_uploaded_photos(self):
        event=self.event()
        track,sample=self.sample(event)
        self.recognition.confirm(track,'father',sample)
        with self.db.connect() as db:
            for i in range(1,100):
                db.execute("INSERT INTO person_samples(id,track_id,created,feature,model,quality,person_id) VALUES(?,?,?,?,?,?,?)",
                    (f'reference-{i}',track,100+i,normalized([1,0,0]).tobytes(),'sface-test',i,'father'))
            db.execute("INSERT INTO face_enrollments(id,person_id,created,feature,model,quality) VALUES(?,?,?,?,?,?)",
                ('uploaded','father',300,normalized([1,0,0]).tobytes(),'sface-test',200))
        examples=self.recognition.examples('father')
        self.assertEqual(len(examples['examples']),101)
        self.assertEqual(examples['examples'][0]['source'],'upload')
        self.assertTrue(all('feature' not in item for item in examples['examples']))
        self.recognition.remove_example('father','upload','uploaded')
        self.assertEqual(len(self.recognition.examples('father')['examples']),100)
        with self.assertRaises(KeyError):self.recognition.examples('does-not-exist')

    def test_manual_recording_requires_review_even_when_all_people_delivery_enabled(self):
        event=self.db.start_event(100,0,'manual')
        self.db.end_event(event,110,'manual_stopped')
        self.db.execute("INSERT INTO clips(id,event_id,started,ended,state) VALUES('manual',?,100,110,'ready')",(event,))
        config=Config(self.path/'settings.json')
        config.save(Settings(whatsapp_enabled=True,recipient='5511999999999',father_only=False))
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200,json={'state':'connected','message_id':'mock'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            jobs=Jobs(self.db,config);jobs.deliver_one(client)
            self.assertEqual(calls,[])
            self.db.execute("UPDATE events SET identity='other' WHERE id=?",(event,))
            jobs.deliver_one(client)
        self.assertIn('/send',calls)

    def test_body_examples_cannot_train_face_gallery(self):
        track,sample=self.sample(self.event())
        self.db.execute("UPDATE person_samples SET model='rgb448-body' WHERE id=?",(sample,))
        with self.assertRaises(ValueError): self.recognition.confirm(track,'father',sample)

    def test_probable_whatsapp_requires_option_and_uses_honest_caption(self):
        event = self.event()
        track,sample = self.sample(event)
        self.db.execute("UPDATE person_tracks SET suggested_id='father',similarity=.98 WHERE id=?",(track,))
        self.db.execute("INSERT INTO clips(id,event_id,started,ended,state) VALUES('clip',?,100,110,'ready')",(event,))
        cfg = Config(self.path/'settings.json')
        cfg.save(Settings(whatsapp_enabled=True,recipient='5511999999999'))
        sent=[]
        def handler(request):
            if request.url.path=='/status':return httpx.Response(200,json={'state':'connected'})
            sent.append(request.content.decode())
            return httpx.Response(200,json={'message_id':'mock'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            jobs=Jobs(self.db,cfg)
            jobs.deliver_one(client)
            self.assertEqual(sent,[])
            settings=cfg.get();settings.send_probable_father=True;cfg.save(settings)
            jobs.deliver_one(client)
        self.assertEqual(len(sent),1)
        self.assertIn('reconhecimento facial automático',sent[0])

    def test_body_only_estimate_does_not_pass_facial_delivery_filter(self):
        cfg,boxes=self.seed_body()
        self.recognition.observe_faces(None,[],[],{},202,cfg)
        event=self.db.start_event(210,1)
        for now in (210,210.4,210.8):
            self.recognition.observe_faces(event,boxes,[2],{},now,cfg,{'2':normalized([1,0,0])})
        self.db.end_event(event,212,'absence')
        self.db.execute("INSERT INTO clips(id,event_id,started,ended,state) VALUES('bodyclip',?,210,212,'ready')",(event,))
        config=Config(self.path/'settings.json')
        config.save(Settings(whatsapp_enabled=True,recipient='5511999999999',send_probable_father=True))
        calls=[]
        def handler(request):
            calls.append(request.url.path)
            return httpx.Response(200,json={'state':'connected'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            Jobs(self.db,config).deliver_one(client)
        self.assertEqual(calls,[])

    def test_deleting_profile_removes_examples_and_recalculates_history(self):
        event=self.event()
        maria=self.recognition.create_person('Maria')
        track,sample=self.sample(event)
        self.recognition.confirm(track,maria,sample)
        self.recognition.forget(maria,True)
        self.assertEqual(self.db.rows('SELECT identity FROM events')[0]['identity'],'unknown')
        self.assertIsNone(self.db.rows('SELECT person_id FROM person_samples')[0]['person_id'])


if __name__ == '__main__':
    unittest.main()
