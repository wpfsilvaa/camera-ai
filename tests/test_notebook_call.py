import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

import httpx

from app.alerts import Alerts
from app.config import Config, Settings
from app.db import Database
from app.notebook import NotebookMonitor

spec = importlib.util.spec_from_file_location('agent', Path(__file__).resolve().parent.parent / 'notebook/monitor.py')
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class ScreenConfigTests(unittest.TestCase):
    def test_night_light_flag_is_accepted_only_as_a_boolean(self):
        self.assertIs(agent.parse_cfg('{"light": true}')['light'], True)
        self.assertNotIn('light', agent.parse_cfg('{"light": "sim"}'))


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.desk = agent.Desk(self.clock)
        self.desk.configure(True, True)

    def test_press_needs_link_and_enabled_button(self):
        self.desk.configure(True, False)
        with self.assertRaises(ValueError):
            self.desk.press('panic')
        self.clock.now += agent.LINK_SECONDS + 1
        with self.assertRaises(ValueError):
            self.desk.press('call')

    def test_flow_ring_answer_end_then_idle(self):
        call = self.desk.press('call')
        self.assertEqual(self.desk.press('call')['id'], call['id'])  # A second tap does not start another call.
        self.assertEqual(self.desk.answer('Ana')['state'], 'answered')
        with self.assertRaises(ValueError):
            self.desk.answer('Bia')
        self.assertEqual(self.desk.end()['state'], 'ended')
        self.clock.now += agent.RESULT_SECONDS + 1
        self.assertEqual(self.desk.snapshot()['state'], 'idle')

    def test_call_to_one_person_needs_them_on_the_list(self):
        uid = 'a' * 32
        self.desk.configure(True, True, callto=json.dumps([{'i': uid, 'n': 'Lorena'}, {'i': 'nao-e-id', 'n': 'X'}]))
        self.assertEqual(self.desk.callto, [{'i': uid, 'n': 'Lorena'}])
        with self.assertRaises(ValueError):
            self.desk.press('call', 'b' * 32)
        call = self.desk.press('call', uid)
        self.assertEqual((call['to'], call['to_name']), (uid, 'Lorena'))

    def test_call_goes_missed_but_panic_keeps_ringing(self):
        self.desk.press('call')
        self.clock.now += agent.MISSED_AFTER + 1
        self.desk.configure(True, True)
        self.assertEqual(self.desk.snapshot()['state'], 'missed')
        self.clock.now += agent.RESULT_SECONDS + 1
        self.desk.press('panic')
        self.clock.now += agent.MISSED_AFTER * 3
        self.assertEqual(self.desk.snapshot()['state'], 'ringing')

    def test_father_can_cancel_while_ringing(self):
        self.desk.press('call')
        self.assertEqual(self.desk.end()['state'], 'ended')


class CallAlertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name)
        self.db = Database(path / 'history.sqlite3')
        self.config = Config(path / 'settings.json')
        self.config.save(Settings(recipient='5511999999999', notebook_call_enabled=True))
        self.alerts = Alerts(self.db, self.config, None)
        self.monitor = NotebookMonitor(self.alerts, self.config, token=lambda: 'x' * 32)
        self.monitor.frame = lambda: b'jpeg'
        self.heard = []
        self.alerts.listeners.append(self.heard.append)
        self.rang = []
        self.alerts.ringers.append(self.rang.append)
        self.reading = {'plugged': True, 'battery': 90, 'call': {'state': 'idle'}}
        self.requests = []

    def tearDown(self):
        self.tmp.cleanup()

    def poll(self, now):
        def handler(request):
            self.requests.append(request)
            return httpx.Response(200, json=self.reading)
        self.monitor.poll(httpx.Client(transport=httpx.MockTransport(handler)), now)

    def ring(self, kind='call'):
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': kind, 'state': 'ringing', 'since': 1000.0}}

    def test_ringing_alerts_once_with_photo_and_reminds_later(self):
        self.ring()
        self.poll(1001)
        self.poll(1005)
        self.assertEqual([a['kind'] for a in self.heard], ['call'])
        self.assertTrue(self.heard[0]['image'])
        self.poll(1000 + 125)
        self.poll(1000 + 600)  # A plain call is reminded only once.
        self.assertEqual([a['kind'] for a in self.heard], ['call', 'call'])
        self.assertIn('Ainda sem resposta', self.heard[1]['message'])

    def test_a_call_to_one_person_also_sends_them_their_own_whatsapp(self):
        self.monitor.callee_phone = lambda person: '5511988887777' if person == 'p1' else None
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': 'call', 'state': 'ringing', 'since': 1000.0, 'to': 'p1', 'to_name': 'Lorena'}}
        self.poll(1001)
        self.poll(1005)
        general, personal = self.heard[0], None
        self.assertIn('chamando Lorena', general['message'])
        self.assertEqual(len([a for a in self.alerts.recent(10) if a['id'] == 'call-abc-to']), 1)   # Once.
        rows = self.db.rows('SELECT alert_id,recipient FROM alert_deliveries ORDER BY alert_id')
        self.assertIn(('call-abc-to', '5511988887777'), [(r['alert_id'], r['recipient']) for r in rows])
        self.assertEqual([r['recipient'] for r in rows if r['alert_id'] == 'call-abc-to'], ['5511988887777'])
        self.assertEqual(len(self.heard), 1)   # The personal message does not push to everyone.

    def test_the_family_list_does_not_repeat_the_person_called(self):
        self.config.save(Settings(recipient='5511999999999', additional_recipients=['5511988887777'], notebook_call_enabled=True))
        self.monitor.callee_phone = lambda person: '5511988887777'
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': 'call', 'state': 'ringing', 'since': 1000.0, 'to': 'p1', 'to_name': 'Lorena'}}
        self.poll(1001)
        general = [r['recipient'] for r in self.db.rows("SELECT recipient FROM alert_deliveries WHERE alert_id='call-abc'")]
        self.assertEqual(general, ['5511999999999'])

    def test_panic_is_urgent_and_reminds_up_to_five_times(self):
        self.ring('panic')
        for step in range(0, 1500, 30):
            self.poll(1000 + step)
        self.assertEqual(len(self.heard), 6)
        self.assertIn('PEDIDO DE AJUDA', self.heard[0]['message'])

    def test_the_phones_keep_getting_nudged_while_a_help_call_rings(self):
        self.ring('panic')
        for step in range(0, 700, 5):
            self.poll(1000 + step)
        self.assertGreaterEqual(len(self.rang), 28)                      # About every 20 s for 10 minutes.
        self.assertLessEqual(len(self.rang), 30)
        self.assertTrue(all(r['ring'] and r['id'] == 'panic-abc' for r in self.rang))     # Same tag: each replaces the last.
        self.assertIn('sem resposta', self.rang[0]['message'])
        self.assertEqual(len(self.heard), 6)                              # WhatsApp keeps its slower reminders.

    def test_a_plain_call_nudges_for_three_minutes(self):
        self.ring('call')
        for step in range(0, 400, 5):
            self.poll(1000 + step)
        self.assertGreaterEqual(len(self.rang), 8)
        self.assertLessEqual(len(self.rang), 9)

    def test_answering_replaces_the_ringing_notification_and_stops_the_nudges(self):
        self.ring('panic')
        for step in (0, 5, 25, 45):
            self.poll(1000 + step)
        before = len(self.rang)
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': 'panic', 'state': 'answered', 'since': 1000.0, 'answered_by': 'Ana'}}
        self.poll(1050)
        self.poll(1100)
        self.assertEqual(len(self.rang), before + 1)                      # One calm notice, nothing more.
        notice = self.rang[-1]
        self.assertTrue(notice['notice'] and notice['id'] == 'panic-abc' and 'Ana atendeu' in notice['message'])
        self.assertNotIn('ring', notice)

    def test_a_cancelled_call_also_ends_the_nudges(self):
        self.ring('call')
        self.poll(1001)
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': 'call', 'state': 'ended', 'since': 1000.0}}
        self.poll(1010)
        self.assertEqual(self.rang[-1]['title'], 'Chamada encerrada')

    def test_answered_call_does_not_alert_again(self):
        self.reading = {**self.reading, 'call': {'id': 'abc', 'kind': 'call', 'state': 'answered', 'since': 1000.0}}
        self.poll(1010)
        self.assertEqual(self.heard, [])
        self.assertEqual(self.monitor.status(1010)['call']['state'], 'answered')

    def test_poll_tells_the_agent_which_buttons_exist(self):
        self.poll(1000)
        self.assertEqual(dict(self.requests[0].url.params), {'call': '1', 'panic': '1'})
        self.config.save(self.config.get().model_copy(update={'notebook_panic_enabled': False}))
        self.poll(1010)
        self.assertEqual(dict(self.requests[1].url.params), {'call': '1', 'panic': '0'})

    def test_call_disabled_ignores_ringing(self):
        self.config.save(self.config.get().model_copy(update={'notebook_call_enabled': False, 'notebook_alerts_enabled': True}))
        self.ring()
        self.poll(1000)
        self.assertEqual(self.heard, [])

    def test_answer_goes_to_the_agent(self):
        def handler(request):
            self.assertTrue(str(request.url).endswith('/call/answer'))
            return httpx.Response(200, json={'state': 'answered', 'answered_by': 'Ana'})
        original = httpx.post
        httpx.post = lambda url, **kw: httpx.Client(transport=httpx.MockTransport(handler)).post(url, **kw)
        try:
            self.assertEqual(self.monitor.answer('Ana')['answered_by'], 'Ana')
        finally:
            httpx.post = original


if __name__ == '__main__':
    unittest.main()
