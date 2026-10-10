import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import intercom

SESSION = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'


class FakeConfig:
    def __init__(self, source='rtsp://user:secret@192.168.1.103:8554/cam'):
        self.source = source

    def for_camera(self, camera_id):
        if camera_id != 'main':
            raise KeyError('Câmera não encontrada.')
        return SimpleNamespace(camera_source=self.source)


def client_for(handler, source=None):
    app = FastAPI()
    app.include_router(intercom.build(FakeConfig(source) if source else FakeConfig()))
    fake = lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout)
    patcher = patch.object(intercom, 'http_client', fake)
    patcher.start()
    return TestClient(app), patcher


class IntercomTests(unittest.TestCase):
    def test_camera_host_comes_from_the_rtsp_address_without_credentials(self):
        self.assertEqual(intercom.camera_host('rtsp://user:secret@192.168.1.103:8554/cam'), '192.168.1.103')
        self.assertEqual(intercom.camera_host('rtsp://[fd00::5]:8554/cam'), '[fd00::5]')
        for source in ('/videos/teste.mp4', 'http://192.168.1.103/cam'):
            with self.assertRaises(ValueError):
                intercom.camera_host(source)

    def test_a_usb_camera_means_the_intercom_is_on_this_computer(self):
        for source in ('0', 'usb:/dev/video0?1280x720@30', '/dev/v4l/by-id/usb-cam-video-index0'):
            self.assertEqual(intercom.camera_host(source), '127.0.0.1')

    def test_listen_forwards_the_offer_to_the_microphone(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(201, text='v=0 answer', headers={'Location': f'/mic/whep/{SESSION}'})

        client, patcher = client_for(handler)
        self.addCleanup(patcher.stop)
        response = client.post('/api/intercom/listen', json={'sdp': 'v=0 offer'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'sdp': 'v=0 answer', 'session': SESSION})
        self.assertEqual(str(seen[0].url), 'http://192.168.1.103:8889/mic/whep')
        self.assertEqual(seen[0].headers['content-type'], 'application/sdp')
        self.assertEqual(seen[0].content, b'v=0 offer')

    def test_light_video_reads_the_lite_camera_path(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.method == 'DELETE':
                return httpx.Response(200)
            return httpx.Response(201, text='v=0 video', headers={'Location': f'/cam-lite/whep/{SESSION}'})

        client, patcher = client_for(handler)
        self.addCleanup(patcher.stop)
        self.assertEqual(client.post('/api/intercom/video', json={'sdp': 'v=0'}).json(), {'sdp': 'v=0 video', 'session': SESSION})
        self.assertEqual(str(seen[0].url), 'http://192.168.1.103:8889/cam-lite/whep')
        client.post('/api/intercom/hangup', json={'kind': 'video', 'session': SESSION})
        self.assertEqual(str(seen[1].url), f'http://192.168.1.103:8889/cam-lite/whep/{SESSION}')

    def test_busy_speaker_and_offline_computer_have_clear_errors(self):
        client, patcher = client_for(lambda request: httpx.Response(400, text='path busy'))
        self.addCleanup(patcher.stop)
        self.assertEqual(client.post('/api/intercom/talk', json={'sdp': 'v=0'}).status_code, 409)

        def offline(request):
            raise httpx.ConnectError('refused')
        client, patcher = client_for(offline)
        self.addCleanup(patcher.stop)
        self.assertEqual(client.post('/api/intercom/listen', json={'sdp': 'v=0'}).status_code, 502)

    def test_video_file_and_unknown_camera_are_rejected(self):
        client, patcher = client_for(lambda request: httpx.Response(201), source='/videos/teste.mp4')
        self.addCleanup(patcher.stop)
        self.assertEqual(client.post('/api/intercom/listen', json={'sdp': 'v=0'}).status_code, 409)
        self.assertEqual(client.post('/api/intercom/listen', json={'sdp': 'v=0', 'camera_id': 'sala'}).status_code, 404)

    def test_hangup_only_accepts_session_ids(self):
        seen = []
        client, patcher = client_for(lambda request: seen.append(request) or httpx.Response(200))
        self.addCleanup(patcher.stop)
        self.assertEqual(client.post('/api/intercom/hangup', json={'kind': 'talk', 'session': SESSION}).json(), {'ok': True})
        self.assertEqual((seen[0].method, str(seen[0].url)), ('DELETE', f'http://192.168.1.103:8889/talk/whip/{SESSION}'))
        self.assertEqual(client.post('/api/intercom/hangup', json={'kind': 'talk', 'session': '../cam'}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
