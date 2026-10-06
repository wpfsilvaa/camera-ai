import json
import os
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

from app.db import Database
from app.push import PHOTOS, PRESENCE_COOLDOWN, Push

KEYS = {'p256dh': 'BPUBLIC', 'auth': 'SECRET'}


class Gone(Exception):
    response = type('Response', (), {'status_code': 410})()


class PushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'history.sqlite3')
        self.sent, self.gone = [], set()
        self.push = Push(self.db, sender=self.fake_send)

    def tearDown(self):
        self.tmp.cleanup()

    def fake_send(self, subscription_info, data, vapid_private_key, vapid_claims, ttl, headers, timeout):
        if subscription_info['endpoint'] in self.gone:
            raise Gone()
        self.sent.append((subscription_info['endpoint'], json.loads(data), headers['Urgency']))

    def test_keys_are_created_once(self):
        again = Push(self.db, sender=self.fake_send)
        self.assertEqual(again.public_key, self.push.public_key)
        self.assertEqual(len(self.push.public_key), 87)  # Uncompressed P-256 point, base64url.

    def test_rejects_invalid_subscriptions(self):
        for bad in ({'endpoint': 'http://insecure', 'keys': KEYS}, {'endpoint': 'https://push', 'keys': {}}):
            with self.assertRaises(ValueError):
                self.push.subscribe('u1', bad)

    def test_sends_to_every_device_and_drops_expired_ones(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.subscribe('u2', {'endpoint': 'https://push/b', 'keys': KEYS})
        self.push.subscribe('u2', {'endpoint': 'https://push/b', 'keys': KEYS})  # Re-subscribing is idempotent.
        self.gone.add('https://push/b')
        sent = self.push.send_all({'id': 'fall-main-1', 'kind': 'fall', 'message': 'Possível queda na Cozinha'})
        self.assertEqual(sent, 1)
        endpoint, payload, urgency = self.sent[0]
        self.assertEqual((endpoint, payload['title'], payload['urgent'], urgency), ('https://push/a', 'Possível queda', True, 'high'))
        self.assertEqual([d['endpoint'] for d in self.push.devices('u2')], [])
        self.assertIsNotNone(self.push.devices('u1')[0]['last_ok'])

    def test_topics_can_be_turned_off_per_device(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.subscribe('u1', {'endpoint': 'https://push/b', 'keys': KEYS})
        self.assertTrue(all(t['enabled'] for t in self.push.topic_settings('https://push/a')['topics']))
        self.push.set_topics('https://push/a', ['emergency', 'restricted', 'camera', 'backup'])  # No daily summary.
        self.assertEqual(self.push.send_all({'id': 's1', 'kind': 'summary', 'message': 'Resumo'}), 1)
        self.assertEqual(self.sent[-1][0], 'https://push/b')
        self.assertEqual(self.push.send_all({'id': 'f1', 'kind': 'fall', 'message': 'Queda'}), 2)
        self.assertEqual(self.push.send_all({'id': 'push-test', 'kind': 'test', 'message': 'Teste'}), 2)
        self.push.set_topics('https://push/a', [])
        self.assertEqual(self.push.send_all({'id': 'test', 'kind': 'test', 'message': 'Teste'}), 2)  # The test is never muted.
        with self.assertRaises(ValueError):
            self.push.set_topics('https://push/a', ['nope'])
        with self.assertRaises(KeyError):
            self.push.set_topics('https://push/none', [])

    def test_summary_is_not_urgent(self):
        self.push.subscribe(None, {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.send_all({'id': 'summary-x', 'kind': 'summary', 'message': 'Resumo'})
        self.assertEqual(self.sent[0][2], 'normal')

    def test_presence_goes_only_to_devices_that_opted_in_and_opens_the_camera(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.subscribe('u2', {'endpoint': 'https://push/b', 'keys': KEYS})
        self.assertEqual(self.push.presence_settings('https://push/b'), {'enabled': True, 'audience': 'all', 'quiet': False})
        self.push.set_presence('https://push/b', False)
        self.assertFalse(self.push.presence_settings('https://push/b')['enabled'])
        self.push.notify = self.push.send_all  # Send inline instead of in the background pool.
        self.assertTrue(self.push.presence('sala', 'Sala', now=1_000_000))
        self.assertEqual(len(self.sent), 1)
        endpoint, payload, urgency = self.sent[0]
        self.assertEqual((endpoint, payload['title'], payload['url'], payload['tag'], urgency),
                         ('https://push/a', 'Presença detectada', '/?camera=sala#overview', 'presence-sala', 'high'))
        self.assertFalse(payload['urgent'])
        self.assertIn('Sala', payload['body'])
        # Alerts still reach every device.
        self.push.send_all({'id': 'fall-main-2', 'kind': 'fall', 'message': 'Queda'})
        self.assertEqual(len(self.sent), 3)
        with self.assertRaises(KeyError):
            self.push.set_presence('https://push/unknown', True)

    def test_presence_waits_a_minute_per_camera(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.notify = self.push.send_all
        self.assertTrue(self.push.presence('main', 'Cozinha', now=1000))
        self.assertFalse(self.push.presence('main', 'Cozinha', now=1030))
        self.assertTrue(self.push.presence('sala', 'Sala', now=1030))
        self.assertTrue(self.push.presence('main', 'Cozinha', now=1061))
        self.assertEqual(len(self.sent), 3)

    def test_presence_and_fall_notifications_carry_a_photo(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.notify = self.push.send_all
        self.push.frame = lambda camera_id: b'JPEG-' + camera_id.encode()
        self.push.presence('main', 'Cozinha', now=2_000_000)
        photo = self.sent[-1][1]['image']
        self.assertEqual(photo, '/alert-media/presence-main-2000000.jpg')
        self.assertEqual((PHOTOS / 'presence-main-2000000.jpg').read_bytes(), b'JPEG-main')
        # Photos older than a day are removed when a new one is saved.
        self.push.frame = lambda camera_id: b'JPEG'
        os.utime(PHOTOS / 'presence-main-2000000.jpg', (2_000_000, 2_000_000))
        self.push.presence('main', 'Cozinha', now=2_000_000 + 2 * 86400)
        self.assertFalse((PHOTOS / 'presence-main-2000000.jpg').exists())
        # No image yet (camera starting): the notification goes without a photo.
        self.push.frame = lambda camera_id: None
        self.push.presence('sala', 'Sala', now=2_000_000)
        self.assertIsNone(self.sent[-1][1]['image'])
        self.push.send_all({'id': 'fall-main-9', 'kind': 'fall', 'message': 'Queda', 'image': 1, 'camera_id': 'main'})
        self.assertEqual(self.sent[-1][1]['image'], '/alert-media/fall-main-9.jpg')

    def test_camera_alerts_offer_live_view_and_call_buttons(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/a', 'keys': KEYS})
        self.push.send_all({'id': 'fall-sala-1', 'kind': 'fall', 'message': 'Queda', 'image': 1, 'camera_id': 'sala'})
        self.push.send_all({'id': 'summary-x', 'kind': 'summary', 'message': 'Resumo'})
        fall, summary = self.sent[0][1], self.sent[1][1]
        # The service worker adds "Ver ao vivo" and "Conversar" when the payload names a camera.
        self.assertEqual((fall['camera'], fall['url']), ('sala', '/?camera=sala#overview'))
        self.assertEqual((summary['camera'], summary['url']), (None, '/#overview'))

    def watch(self, frames):
        """Run the identity watch inline over a scripted sequence of visible tracks, one per second."""
        clock = {'now': 5_000_000}
        script = iter(frames)
        last = []

        def people(camera_id):
            nonlocal last
            last = next(script, last)
            return last
        self.push.people = people
        self.push.notify = self.push.send_all
        self.push.spawn = lambda fn: fn()
        self.push.clock = lambda: clock['now']
        self.push.sleep = lambda seconds: clock.__setitem__('now', clock['now'] + seconds)
        return clock['now']

    def test_presence_filter_father_and_unknown(self):
        for endpoint, audience in (('https://push/all', 'all'), ('https://push/dad', 'father'), ('https://push/unk', 'unknown')):
            self.push.subscribe('u1', {'endpoint': endpoint, 'keys': KEYS})
            self.push.set_presence(endpoint, True, audience)
        unknown = {'id': 1, 'person_id': None, 'name': None}
        father = {'id': 1, 'person_id': 'father', 'name': 'Seu Zé'}
        # Face recognized after 3 s: "all" hears at once, "father" when recognized, "unknown" never.
        start = self.watch([[unknown], [unknown], [unknown], [father]])
        self.push.presence('main', 'Cozinha', now=start)
        heard = [(endpoint, payload['body']) for endpoint, payload, _ in self.sent]
        self.assertEqual([e for e, _ in heard], ['https://push/all', 'https://push/dad'])
        self.assertIn('Seu Zé apareceu na câmera Cozinha', heard[1][1])
        # Nobody recognized during the window: only "all" and "unknown".
        self.sent.clear()
        start = self.watch([[unknown]] * 20)
        self.push.presence('main', 'Cozinha', now=start + PRESENCE_COOLDOWN)
        self.assertEqual([e for e, _, _ in self.sent], ['https://push/all', 'https://push/unk'])
        self.assertIn('Pessoa não reconhecida', self.sent[1][1]['body'])
        with self.assertRaises(ValueError):
            self.push.set_presence('https://push/all', True, 'vizinho')

    def test_presence_quiet_hours_are_per_device(self):
        self.push.subscribe('u1', {'endpoint': 'https://push/quiet', 'keys': KEYS})
        self.push.subscribe('u2', {'endpoint': 'https://push/always', 'keys': KEYS})
        self.push.set_presence('https://push/quiet', True, 'all', quiet=True)
        self.push.notify = self.push.send_all
        self.push.quiet = lambda now: True
        self.push.presence('main', 'Cozinha', now=6_000_000)
        self.assertEqual([e for e, _, _ in self.sent], ['https://push/always'])
        # Other alerts (falls, absence) ignore this per-device preference.
        self.push.send_all({'id': 'fall-main-3', 'kind': 'fall', 'message': 'Queda'})
        self.assertEqual(len(self.sent), 3)


if __name__ == '__main__':
    unittest.main()
