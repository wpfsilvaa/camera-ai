import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

import cv2
import httpx
import numpy as np
from fastapi.testclient import TestClient

from app.config import Settings, Config
from app.db import Database
from app.jobs import Jobs
from app.presence import Presence
from app.recorder import Recorder, transcode, cleanup


class PresenceTests(unittest.TestCase):
    def test_brief_detection_is_ignored_and_gap_does_not_split_visit(self):
        state = Presence(minimum=1, absence=3)
        self.assertIsNone(state.update(0, 1))
        self.assertIsNone(state.update(.4, 0))
        self.assertIsNone(state.update(1, 1))
        self.assertEqual(state.update(2, 1), 'start')
        self.assertIsNone(state.update(3, 0))
        self.assertIsNone(state.update(4, 2))
        self.assertIsNone(state.update(6, 0))
        self.assertEqual(state.update(7, 0), 'end')
        self.assertIsNone(state.update(8, 1))
        self.assertEqual(state.update(9, 1), 'start')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.db = Database(self.directory / 'db.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_segments_keep_one_visit_and_video_duration(self):
        event = self.db.start_event(100, 1)
        recorder = Recorder(self.db, self.directory)
        frame = np.full((120,160,3), 90, dtype=np.uint8)
        recorder.start(event, frame, 100, 8)
        recorder.write(frame, 101)  # slow inference: frames are repeated to preserve duration
        recorder.finish(101)
        recorder.start(event, frame, 102, 8)
        recorder.write(frame, 103)
        recorder.finish(103)
        self.db.end_event(event, 103, 'absence')
        rows = self.db.rows('SELECT * FROM clips')
        self.assertEqual(len(self.db.history()['events']), 1)
        self.assertEqual(len(rows), 2)
        for row in rows:
            transcode(self.db, row, self.directory)
            out = self.directory / f"{row['id']}.mp4"
            self.assertTrue(out.is_file())
            cap = cv2.VideoCapture(str(out))
            self.assertTrue(cap.read()[0])
            self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS), 1.125, places=2)
            cap.release()
        self.assertTrue(all(c['state'] == 'ready' for c in self.db.rows('SELECT * FROM clips')))
        cleanup(self.db, 7, self.directory)
        self.assertTrue(all(c['state'] == 'expired' for c in self.db.rows('SELECT * FROM clips')))
        self.assertEqual(len(self.db.history()['events']), 1)
        self.assertFalse(list(self.directory.glob('*.mp4')))

    def test_variable_camera_fps_preserves_recorded_duration(self):
        event=self.db.start_event(100,1)
        recorder=Recorder(self.db,self.directory)
        frame=np.full((120,160,3),90,dtype=np.uint8)
        recorder.start(event,frame,100,30)
        for second,fps in enumerate((30,24,25,24)):
            for n in range(1,fps+1):
                recorder.write(frame,100+second+n/fps)
        recorder.finish(104)
        row=self.db.rows('SELECT * FROM clips')[0]
        transcode(self.db,row,self.directory)
        cap=cv2.VideoCapture(str(self.directory/f"{row['id']}.mp4"))
        self.assertAlmostEqual(cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS),4+1/30,places=2)
        cap.release()

    def test_restart_closes_visits_and_marks_uploads_uncertain(self):
        event = self.db.start_event(100, 1)
        self.db.execute("INSERT INTO clips(id,event_id,started,delivery) VALUES('clip',?,100,'sending')", (event,))
        self.db.recover()
        record = self.db.history()['events'][0]
        self.assertEqual(record['ended'],100)
        self.assertEqual(record['clips'][0]['state'],'processing')
        self.assertEqual(record['clips'][0]['delivery'],'uncertain')

    def test_whatsapp_only_sends_father_and_does_not_resend(self):
        config = Config(self.directory / 'settings.json')
        config.save(Settings(whatsapp_enabled=True, recipient='5511999999999', father_only=True))
        father = self.db.start_event(100,1)
        other = self.db.start_event(200,1)
        self.db.execute("UPDATE events SET identity='father',ended=110 WHERE id=?", (father,))
        for clip, event in [('a'*32,father),('b'*32,other)]:
            self.db.execute("INSERT INTO clips(id,event_id,started,state) VALUES(?,?,100,'ready')",(clip,event))
        sent = []
        def handler(request):
            if request.url.path == '/status': return httpx.Response(200,json={'state':'connected'})
            sent.append(request.content)
            return httpx.Response(200,json={'message_id':'test-message'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            jobs = Jobs(self.db, config)
            jobs.deliver_one(client)
            jobs.deliver_one(client)
        self.assertEqual(len(sent),1)
        self.assertEqual(self.db.rows("SELECT delivery FROM clips WHERE id=?",('a'*32,))[0]['delivery'],'sent')
        self.assertEqual(self.db.rows("SELECT delivery FROM clips WHERE id=?",('b'*32,))[0]['delivery'],'pending')

    def test_timeout_is_not_retried_automatically(self):
        config = Config(self.directory / 'settings.json')
        config.save(Settings(whatsapp_enabled=True, recipient='5511999999999', father_only=False))
        event = self.db.start_event(100,1)
        self.db.execute("INSERT INTO clips(id,event_id,started,state) VALUES('clip',?,100,'ready')",(event,))
        def handler(request):
            if request.url.path == '/status': return httpx.Response(200,json={'state':'connected'})
            raise httpx.ReadTimeout('timeout')
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            jobs = Jobs(self.db,config)
            jobs.deliver_one(client)
        self.assertEqual(self.db.rows('SELECT delivery FROM clips')[0]['delivery'],'uncertain')


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import main
        cls.main = main
        cls.client = TestClient(main.app)  # Do not start camera or jobs in API tests.

    def test_config_validation_and_cross_site_write_rejection(self):
        response = self.client.put('/api/settings',json={})
        self.assertEqual(response.status_code,403)
        headers = {'X-Casa-Request':'1'}
        self.assertEqual(self.client.put('/api/settings',headers=headers,json={'fps':0}).status_code,422)
        self.assertEqual(self.client.put('/api/settings',headers=headers,json={'recipient':'123'}).status_code,422)
        self.assertEqual(self.client.put('/api/settings',headers=headers,json={'whatsapp_enabled':True}).status_code,422)
        self.assertEqual(self.client.put('/api/settings',headers={**headers,'Origin':'https://evil.example'},json={}).status_code,403)

    def test_unknown_people_cannot_be_confirmed_mid_recording(self):
        event = self.main.db.start_event(100,1)
        headers = {'X-Casa-Request':'1'}
        self.assertEqual(self.client.patch(f'/api/events/{event}',headers=headers,json={'identity':'father'}).status_code,409)
        self.main.db.end_event(event,110,'absence')
        self.assertEqual(self.client.patch(f'/api/events/{event}',headers=headers,json={'identity':'father'}).status_code,200)

    def test_analysis_pause_preserves_camera_and_manual_recording_request(self):
        headers={'X-Casa-Request':'1'}
        settings=self.main.config.get()
        settings.enabled=True;settings.analysis_enabled=True
        self.main.config.save(settings)
        camera=self.main.camera
        camera.update(state='online',last_frame=__import__('time').time())
        try:
            self.assertEqual(self.client.post('/api/recording/start',headers=headers).status_code,200)
            with patch.object(self.main.offline,'cancel') as cancel:
                response=self.client.post('/api/analysis/pause',headers=headers)
                self.assertEqual(response.status_code,200)
                cancel.assert_called_once()
            self.assertTrue(self.main.config.get().enabled)
            self.assertFalse(self.main.config.get().analysis_enabled)
            self.assertTrue(camera.snapshot()['manual_requested'])
            self.assertEqual(self.client.post('/api/recording/stop',headers=headers).status_code,200)
            self.assertFalse(camera.snapshot()['manual_requested'])
            self.assertEqual(self.client.post('/api/analysis/resume',headers=headers).status_code,200)
            self.assertTrue(self.main.config.get().analysis_enabled)
            camera.update(state='paused')
            self.assertEqual(self.client.post('/api/recording/start',headers=headers).status_code,409)
        finally:
            camera.request_recording(False)
            settings.enabled=False;self.main.config.save(settings)

    def test_media_traversal_and_all_routes_require_password(self):
        self.assertEqual(self.client.get('/media/gateway.token').status_code,404)
        self.assertEqual(self.client.get('/').status_code,200)
        with patch.dict(os.environ,{'DASHBOARD_PASSWORD':'test-secret'}):
            for route in ['/', '/api/settings', '/api/events', '/api/snapshot', '/api/stream.mjpeg', '/api/people', '/people-media/'+'a'*32+'.jpg', '/media/'+'a'*32+'.mp4', '/static/app.js']:
                self.assertEqual(self.client.get(route).status_code,401)
            self.assertEqual(self.client.get('/api/settings',auth=('admin','test-secret')).status_code,200)


if __name__ == '__main__':
    unittest.main()
