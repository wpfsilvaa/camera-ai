import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['MONITOR_PHOTOS_DIR'] = str(Path(TEMP.name) / 'screen-photos')

from app.db import Database
from app.photos import MAX_PHOTOS, Photos, prepare

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'notebook'))
import monitor


def jpeg(width, height, color=(40, 120, 200)):
    ok, data = cv2.imencode('.jpg', np.full((height, width, 3), color, np.uint8))
    return data.tobytes()


class PhotoStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.photos = Photos(Database(Path(self.tmp.name) / 'h.sqlite3'), Path(self.tmp.name) / 'p')

    def tearDown(self):
        self.tmp.cleanup()

    def test_big_images_are_resized_and_get_a_thumbnail(self):
        full, thumb = prepare(jpeg(4000, 3000))
        height, width = cv2.imdecode(np.frombuffer(full, np.uint8), 1).shape[:2]
        self.assertEqual((width, height), (1920, 1440))
        self.assertEqual(max(cv2.imdecode(np.frombuffer(thumb, np.uint8), 1).shape[:2]), 360)
        small, _ = prepare(jpeg(640, 480))
        self.assertEqual(cv2.imdecode(np.frombuffer(small, np.uint8), 1).shape[1], 640)   # Never enlarged.

    def test_rejects_things_that_are_not_images(self):
        with self.assertRaises(Exception):
            prepare(b'not an image at all')

    def test_add_list_and_permissions(self):
        photo = self.photos.add('Ana', 'u1', jpeg(800, 600), now=100)
        self.assertTrue(self.photos.path(photo).is_file() and self.photos.path(photo, True).is_file())
        self.assertEqual([r['author'] for r in self.photos.list()], ['Ana'])
        with self.assertRaises(PermissionError):
            self.photos.delete(photo, 'u2', False)
        self.photos.delete(photo, 'u1', False)
        self.assertEqual(self.photos.list(), [])
        self.assertFalse(self.photos.path(photo).exists() or self.photos.path(photo, True).exists())
        other = self.photos.add('Ana', 'u1', jpeg(100, 100))
        self.photos.delete(other, 'someone-else', True)    # An admin removes anything.
        with self.assertRaises(KeyError):
            self.photos.delete('missing', 'u1', True)

    def test_album_limit(self):
        data = jpeg(64, 64)
        for _ in range(MAX_PHOTOS):
            self.photos.db.execute('INSERT INTO photos(id,author,user_id,created) VALUES(?,?,?,?)', (os.urandom(16).hex(), 'x', 'u', 1))
        with self.assertRaises(ValueError):
            self.photos.add('Ana', 'u1', data)


class MonitorPhotoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        monitor.Handler.token = 't' * 40
        monitor.Handler.desk = monitor.Desk()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), monitor.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def request(self, method, path, body=None, token=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        merged = {'Authorization': 'Bearer ' + 't' * 40} if token else {}
        connection.request(method, path, body=body, headers={**merged, **(headers or {})})
        response = connection.getresponse()
        return response.status, response.read()

    def test_upload_list_serve_and_delete(self):
        photo_id = 'a' * 32
        self.assertEqual(self.request('PUT', f'/photos/{photo_id}', jpeg(64, 48), token=False)[0], 404)       # Needs the token.
        self.assertEqual(self.request('PUT', f'/photos/{photo_id}', b'GIF89a-not-jpeg')[0], 415)
        self.assertEqual(self.request('PUT', f'/photos/{photo_id}', jpeg(64, 48), headers={'X-Photo-Author': 'Ana%20Souza'})[0], 200)
        self.assertEqual([p for p in monitor.photo_list() if p['id'] == photo_id][0]['a'], 'Ana Souza')
        self.assertIn(photo_id, self.request('GET', '/photos')[1].decode())
        status, body = self.request('GET', f'/photo/{photo_id}.jpg', token=False)
        self.assertEqual((status, body[:2]), (200, b'\xff\xd8'))
        self.assertEqual(self.request('PUT', '/photos/../../etc/passwd', jpeg(8, 8))[0], 404)                 # Only 32-hex ids.
        self.assertEqual(self.request('DELETE', f'/photos/{photo_id}')[0], 200)
        self.assertEqual(self.request('GET', f'/photo/{photo_id}.jpg', token=False)[0], 404)

    def test_state_lists_photos_only_when_the_frame_is_on(self):
        photo_id = 'b' * 32
        self.request('PUT', f'/photos/{photo_id}', jpeg(32, 32))
        monitor.Handler.desk.configure(True, True, 'resting', False, frame=False)
        self.assertEqual(monitor.Handler.desk.display()['photos'], [])
        monitor.Handler.desk.configure(True, True, 'resting', False, frame=True)
        self.assertIn(photo_id, [p['id'] for p in monitor.Handler.desk.display()['photos']])
        self.request('DELETE', f'/photos/{photo_id}')


class LongPollTests(MonitorPhotoTests):
    def test_state_waits_for_a_change_and_returns_at_once_when_it_comes(self):
        import json
        import time
        version = json.loads(self.request('GET', '/state', token=False)[1])['v']
        started = time.time()
        threading.Timer(0.3, monitor.Handler.desk.bump).start()
        body = json.loads(self.request('GET', f'/state?v={version}&wait=4', token=False)[1])
        self.assertGreater(body['v'], version)
        self.assertLess(time.time() - started, 2)            # Woken by the change, not by the timeout.

    def test_state_returns_after_the_wait_when_nothing_changes(self):
        import json
        import time
        version = json.loads(self.request('GET', '/state', token=False)[1])['v']
        started = time.time()
        self.request('GET', f'/state?v={version}&wait=1', token=False)
        self.assertGreaterEqual(time.time() - started, 0.9)

    def test_touch_only_bumps_when_the_screen_would_change(self):
        desk = monitor.Handler.desk
        desk.configure(True, True, 'resting', False)
        desk.touch()
        before = desk.version
        desk.configure(True, True, 'resting', False)     # Same state again.
        desk.touch()
        self.assertEqual(desk.version, before)
        desk.configure(True, True, 'analysing', False)   # The watch mode changed.
        desk.touch()
        self.assertGreater(desk.version, before)


if __name__ == '__main__':
    unittest.main()
