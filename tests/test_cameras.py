import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Set isolation before importing app.config, including when discovered first.
TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

import httpx
from fastapi.testclient import TestClient

from app.config import CameraConfigView, Config, ExtraCamera, Settings
from app.db import Database
from app.cameras import CameraManager
from app.recognition import Recognition
from app.jobs import Jobs


class MultiCameraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.config = Config(self.path/'settings.json')
        self.extra = ExtraCamera(camera_name='Sala', camera_source='1', enabled=True)
        self.config.save(Settings(camera_name='Cozinha', enabled=True, cameras=[self.extra]))
        self.db = Database(self.path/'history.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_configuration_and_history_keep_primary_camera(self):
        legacy = self.path/'legacy.json'
        legacy.write_text(json.dumps({'schema_version':2,'camera_source':'rtsp://old/cam','camera_name':'Antiga','fps':15}))
        migrated = Config(legacy)
        self.assertEqual(migrated.for_camera('main').camera_source, 'rtsp://old/cam')
        self.assertEqual(migrated.get().cameras, [])
        event = self.db.start_event(time.time(), 1)
        self.assertEqual(self.db.history()['events'][0]['camera_id'], 'main')
        self.assertEqual(self.db.history(camera_id=self.extra.id)['total'], 0)

    def test_stale_form_and_eof_cannot_overwrite_another_camera(self):
        stale = self.config.for_camera(self.extra.id)
        self.config.update_camera('main', analysis_enabled=False)
        self.config.update_camera(self.extra.id, camera_name='Sala nova')
        eof = stale.model_copy(update={'enabled':False})
        CameraConfigView(self.config, self.extra.id).save(eof)
        self.assertTrue(self.config.get().enabled)
        self.assertEqual(self.config.for_camera(self.extra.id).camera_name,'Sala nova')
        stale.camera_name = 'Sala editada'
        self.config.save_for_camera(stale,self.extra.id)
        self.assertFalse(self.config.for_camera(self.extra.id).enabled)
        self.assertFalse(self.config.get().analysis_enabled)
        self.assertEqual(self.config.get().camera_name,'Cozinha')
        self.assertEqual(Config(self.config.path).for_camera(self.extra.id).camera_name,'Sala editada')

    def test_stats_history_and_whatsapp_keep_source_after_rename(self):
        now = time.time()
        one = self.db.start_event(now, 1, camera_name='Cozinha')
        two = self.db.start_event(now, 1, camera_id=self.extra.id, camera_name='Sala original')
        self.db.start_event(now, 0, 'manual', self.extra.id, 'Sala original')
        self.assertEqual(self.db.stats()['today']['total'],2)
        self.assertEqual(self.db.stats(self.extra.id)['today']['total'],1)
        self.assertEqual(self.db.history(camera_id=self.extra.id)['total'],2)
        self.db.execute("UPDATE events SET identity='father',ended=? WHERE id=?",(now+1,two))
        self.db.execute("INSERT INTO clips(id,event_id,started,state) VALUES('test',?,?,'ready')",(two,now))
        settings=self.config.get();settings.whatsapp_enabled=True;settings.recipient='5511999999999';self.config.save(settings)
        self.config.update_camera(self.extra.id,camera_name='Sala renomeada')
        sent=[]
        def handler(request):
            if request.url.path=='/status': return httpx.Response(200,json={'state':'connected'})
            sent.append(json.loads(request.content));return httpx.Response(200,json={'message_id':'fake'})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            Jobs(self.db,self.config).deliver_one(client)
        self.assertIn('Sala original',sent[0]['caption'])

    def test_controls_are_scoped_and_deleting_preserves_history(self):
        from app import main
        recognition=Recognition(self.db,self.path/'people')
        manager=CameraManager(self.db,self.config,recognition);manager.sync()
        with patch.multiple(main,db=self.db,config=self.config,cameras=manager,recognition=recognition), patch.dict('os.environ',{'DASHBOARD_PASSWORD':''}):
            client=TestClient(main.app)
            headers={'X-Casa-Request':'1'}
            camera_id=self.extra.id
            worker=manager.get(camera_id)
            worker.update(state='online',last_frame=time.time())
            self.assertIsNot(worker.recognition,manager.get().recognition)
            self.assertEqual(client.post(f'/api/recording/start?camera_id={camera_id}',headers=headers).status_code,200)
            self.assertFalse(manager.get().snapshot()['manual_requested'])
            self.assertTrue(worker.snapshot()['manual_requested'])
            client.post(f'/api/analysis/pause?camera_id={camera_id}',headers=headers)
            self.assertTrue(self.config.get().analysis_enabled)
            self.assertFalse(self.config.for_camera(camera_id).analysis_enabled)
            client.post('/api/analysis-all/pause',headers=headers)
            self.assertFalse(self.config.get().analysis_enabled)
            client.post(f'/api/monitor/stop?camera_id={camera_id}',headers=headers)
            self.assertTrue(self.config.get().enabled)
            self.assertFalse(self.config.for_camera(camera_id).enabled)
            event=self.db.start_event(time.time(),1,camera_id=camera_id,camera_name='Sala')
            self.assertEqual(client.delete(f'/api/cameras/{camera_id}',headers=headers).status_code,200)
            self.assertEqual(client.get(f'/api/events/{event}').json()['camera_name'],'Sala')
            self.assertEqual(client.get(f'/api/settings?camera_id={camera_id}').status_code,404)
            self.assertEqual(client.get('/api/snapshot?camera_id=missing').status_code,404)
            self.assertEqual(client.delete('/api/cameras/main',headers=headers).status_code,409)
            added=client.post('/api/cameras',headers=headers,json={'camera_name':'Entrada','camera_source':'2'})
            self.assertEqual(added.status_code,201)
            self.assertFalse(self.config.for_camera(added.json()['id']).enabled)
            self.assertEqual(client.post('/api/cameras',headers=headers,json={'camera_name':' ','detection_fps':0}).status_code,422)
