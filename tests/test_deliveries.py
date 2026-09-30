import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
import httpx
import test_system
from app.config import Config, Settings
from app.db import Database
from app.jobs import Jobs

PRIMARY='5511999999999'
SISTER='5511888888888'
OTHER='5511777777777'


class DeliveriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.db=Database(self.path/'history.sqlite3');self.config=Config(self.path/'settings.json')
        self.config.save(Settings(recipient=PRIMARY,additional_recipients=[SISTER,OTHER],whatsapp_enabled=True,father_only=False))
        self.jobs=Jobs(self.db,self.config);self.sent=[];self.fail={}
        self.client=httpx.Client(transport=httpx.MockTransport(self.handler))

    def tearDown(self):
        self.client.close();self.tmp.cleanup()

    def handler(self,request):
        if request.url.path=='/status':return httpx.Response(200,json={'state':'connected'})
        body=json.loads(request.content);self.sent.append((body['clip_id'],body['recipient']))
        code=self.fail.get(body['recipient'],200)
        if code=='timeout':raise httpx.ReadTimeout('timeout')
        return httpx.Response(code,json={'message_id':'test-'+body['recipient']})

    def clip(self,key='a',identity='father',started=100):
        event=self.db.start_event(started,1);self.db.end_event(event,started+5,'absence')
        self.db.execute('UPDATE events SET identity=? WHERE id=?',(identity,event))
        self.db.execute("INSERT INTO clips(id,event_id,started,ended,state) VALUES(?,?,?,?,'ready')",(key*32,event,started,started+5))
        return event,key*32

    def drain(self,n=8):
        for _ in range(n):self.jobs.deliver_one(self.client)

    def test_family_only_gets_father_and_waiting_family_does_not_block_next_clip(self):
        first,a=self.clip(identity='other')
        _,b=self.clip('b','unknown',200)
        self.drain()
        self.assertCountEqual(self.sent,[(a,PRIMARY),(b,PRIMARY)])
        self.db.execute("UPDATE events SET identity='father' WHERE id=?",(first,))
        self.drain()
        self.assertCountEqual(self.sent,[(a,PRIMARY),(b,PRIMARY),(a,SISTER),(a,OTHER)])
        self.assertEqual(self.db.rows('SELECT delivery FROM clips WHERE id=?',(a,))[0]['delivery'],'sent')

    def test_failure_and_selective_retry_do_not_repeat_successful_deliveries(self):
        _,clip=self.clip();self.fail[SISTER]=500;self.drain()
        self.assertEqual(len(self.sent),3)
        self.assertEqual(self.db.rows('SELECT delivery FROM clips')[0]['delivery'],'partial')
        from fastapi.testclient import TestClient
        from app import main
        fake=AsyncMock(return_value={'ok':True})
        with patch.object(main,'db',self.db),patch.object(main,'gateway',fake):
            r=TestClient(main.app).post(f'/api/clips/{clip}/retry',params={'recipient':SISTER},headers={'X-Casa-Request':'1'})
            self.assertEqual(r.status_code,200,r.text)
        fake.assert_awaited_once_with('POST','/retry',{'clip_id':clip,'recipient':SISTER})
        del self.fail[SISTER];self.drain()
        self.assertEqual(self.sent.count((clip,SISTER)),2)
        self.assertEqual(self.sent.count((clip,PRIMARY)),1)
        self.assertEqual(self.sent.count((clip,OTHER)),1)
        self.assertEqual(self.db.stats()['pending'],0)

    def test_timeout_does_not_block_other_numbers_or_retry_automatically(self):
        self.clip();self.fail[OTHER]='timeout';self.drain(12)
        self.assertEqual(len(self.sent),3)
        states={r['recipient']:r['delivery'] for r in self.db.rows('SELECT * FROM clip_deliveries')}
        self.assertEqual(states,{PRIMARY:'sent',SISTER:'sent',OTHER:'uncertain'})

    def test_new_contact_gets_only_new_clips_even_if_old_clip_was_not_planned(self):
        initial=self.config.get();initial.additional_recipients=[];self.config.save(initial)
        _,old=self.clip(started=100)
        new=self.config.get();new.additional_recipients=[SISTER]
        with patch('app.config.time.time',return_value=200):self.config.save(new)
        _,fresh=self.clip('b',started=300)
        self.drain()
        self.assertCountEqual(self.sent,[(old,PRIMARY),(fresh,PRIMARY),(fresh,SISTER)])
        # Adding another person later does not backfill already completed clips.
        new=self.config.get();new.additional_recipients.append(OTHER);self.config.save(new)
        self.drain();self.assertEqual(len(self.sent),3)

    def test_removing_contact_cancels_only_its_unsent_deliveries(self):
        self.clip();self.jobs.prepare_deliveries(self.config.get())
        new=self.config.get();new.additional_recipients=[SISTER];self.config.save(new)
        self.drain()
        self.assertEqual({p for _,p in self.sent},{PRIMARY,SISTER})
        self.assertEqual(self.db.rows('SELECT delivery FROM clip_deliveries WHERE recipient=?',(OTHER,))[0]['delivery'],'cancelled')

    def test_remove_and_readd_contact_does_not_release_old_pending_videos(self):
        self.clip();self.jobs.prepare_deliveries(self.config.get())
        new=self.config.get();new.additional_recipients=[];self.config.save(new)
        new=self.config.get();new.additional_recipients=[SISTER]
        with patch('app.config.time.time',return_value=200):self.config.save(new)
        self.drain()
        self.assertEqual({p for _,p in self.sent},{PRIMARY})

    def test_recipient_readded_during_connection_check_cannot_receive_old_clip(self):
        self.clip()
        def handler(request):
            if request.url.path=='/status':
                value=self.config.get();value.additional_recipients=[SISTER];self.config.save(value)
                value=self.config.get();value.additional_recipients=[SISTER,OTHER]
                with patch('app.config.time.time',return_value=200):self.config.save(value)
                return httpx.Response(200,json={'state':'connected'})
            self.fail('Old video was sent to a newly readded contact')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:self.jobs.deliver_one(client)
        self.assertEqual(self.sent,[])

    def test_legacy_sent_clip_migrates_without_sending_to_new_contacts(self):
        _,clip=self.clip()
        self.db.execute("UPDATE clips SET delivery='sent',recipient=?,message_id='legacy',sent_at=120 WHERE id=?",(PRIMARY,clip))
        migrated=Database(self.path/'history.sqlite3')
        self.assertEqual(migrated.rows('SELECT message_id FROM clip_deliveries')[0]['message_id'],'legacy')
        self.drain();self.assertEqual(self.sent,[])
        Database(self.path/'history.sqlite3')
        self.assertEqual(len(self.db.rows('SELECT * FROM clip_deliveries')),1)

    def test_restart_preserves_sent_recipient_and_quarantines_interrupted_one(self):
        _,clip=self.clip();self.jobs.prepare_deliveries(self.config.get())
        self.db.execute("UPDATE clip_deliveries SET delivery='sent',message_id='ok' WHERE recipient=?",(PRIMARY,))
        self.db.execute("UPDATE clip_deliveries SET delivery='sending' WHERE recipient=?",(SISTER,))
        self.db.recover();self.drain()
        self.assertEqual(self.sent,[(clip,OTHER)])
        self.assertEqual(self.db.rows('SELECT delivery FROM clip_deliveries WHERE recipient=?',(SISTER,))[0]['delivery'],'uncertain')

    def test_family_probable_requires_enabled_option_and_face_evidence(self):
        event,clip=self.clip(identity='unknown')
        self.db.execute("INSERT INTO person_tracks(event_id,track_key,started,last_seen,suggested_id,similarity,recognition_kind) VALUES(?,'1',100,105,'father',.9,'body')",(event,))
        new=self.config.get();new.send_probable_father=True;self.config.save(new)
        self.drain();self.assertEqual(self.sent,[(clip,PRIMARY)])
        self.db.execute("UPDATE person_tracks SET recognition_kind='face' WHERE event_id=?",(event,))
        self.drain();self.assertEqual(len(self.sent),3)

    def test_numbers_are_validated_normalized_and_deduplicated(self):
        value=Settings(recipient=PRIMARY,father_only=False,additional_recipients=['+55 (11) 88888-8888',SISTER,PRIMARY])
        self.assertEqual(value.delivery_targets(),{PRIMARY:False,SISTER:True})
        for values in (['123'],[''],[OTHER]*10):
            with self.assertRaises(ValueError):Settings(additional_recipients=values)
