import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name

from app.db import Database
from app.pacing import Greeter, birthday_today, first_name, kiosk_night, vigia_state
from app.config import Settings
from app.recognition import Recognition
from app.messages import MessagePlanner, PersonMessages
from app.reminders import Reminders

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'notebook'))
import monitor


class VigiaTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(vigia_state(False, 22, 6, 23, True), 'off')
        self.assertEqual(vigia_state(True, 22, 6, 23, True), 'resting')
        self.assertEqual(vigia_state(True, 22, 6, 23, False), 'analysing')
        self.assertEqual(vigia_state(True, 22, 6, 12, False), 'scheduled')

    def test_kiosk_night_uses_its_own_hours_and_mode(self):
        settings = Settings(kiosk_night_start_hour=21, kiosk_night_end_hour=6)
        self.assertTrue(kiosk_night(settings, 23) and kiosk_night(settings, 3) and not kiosk_night(settings, 12))
        self.assertFalse(kiosk_night(Settings(kiosk_night_mode='normal'), 23))   # "Same as day": never night.
        self.assertTrue(kiosk_night(Settings(kiosk_night_mode='red'), 23))


class GreetingTests(unittest.TestCase):
    def test_first_name_skips_possessives(self):
        self.assertEqual(first_name('Waldemar Patrique Flores Silva'), 'Waldemar')
        self.assertEqual(first_name('Meu pai'), 'pai')
        self.assertEqual(first_name('  '), '')

    def test_greets_a_recognised_person_once_per_cooldown(self):
        greeter = Greeter()
        track = {'person_id': 'a', 'name': 'Ana Souza'}
        self.assertEqual(greeter.update([track], 1000)['name'], 'Ana')
        self.assertEqual(greeter.update([track], 1005)['name'], 'Ana')    # Still inside the 10 s window.
        self.assertIsNone(greeter.update([track], 1011))
        self.assertIsNone(greeter.update([track], 1500))                  # Cooldown not over: no new greeting.
        self.assertIsNotNone(greeter.update([track], 1000 + 1800))
        self.assertIsNone(greeter.update([{'person_id': None, 'name': 'x'}], 9000))

    def test_birthday_greeting_is_longer_and_carries_the_age(self):
        greeter = Greeter()
        today = date(2026, 10, 12)
        greeting = greeter.update([{'person_id': 'a', 'name': 'Ana'}], 1000, {'a': '1956-10-12'}, today)
        self.assertEqual((greeting['birthday'], greeting['age']), (True, 70))
        self.assertIsNotNone(greeter.update([], 1020))     # 25 s window.
        self.assertIsNone(greeter.update([], 1030))
        self.assertEqual(birthday_today('2000-02-29', date(2027, 3, 1)), 27)   # Leap-day birthday in a common year.
        self.assertIsNone(birthday_today('1956-10-13', today))
        self.assertIsNone(birthday_today('bad', today))


class BirthdayStorageTests(unittest.TestCase):
    def test_set_validate_and_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Database(Path(folder) / 'h.sqlite3')
            recognition = Recognition(db, Path(folder))
            person = recognition.create_person('Ana')
            recognition.set_birthday(person, '1950-03-04')
            self.assertEqual(db.rows('SELECT birthday FROM people WHERE id=?', (person,))[0]['birthday'], '1950-03-04')
            for bad in ('2999-01-01', '1800-01-01', 'ontem'):
                with self.assertRaises(ValueError):
                    recognition.set_birthday(person, bad)
            recognition.set_birthday(person, None)
            self.assertIsNone(db.rows('SELECT birthday FROM people WHERE id=?', (person,))[0]['birthday'])
            with self.assertRaises(KeyError):
                recognition.set_birthday('missing', None)


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reminders = Reminders(Database(Path(self.tmp.name) / 'h.sqlite3'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_expire_and_cycle_order(self):
        self.reminders.add('Ana', 'u1', 'Tomar o remédio', 1, now=1000)
        self.reminders.add('Beto', 'u2', 'Comprar pão', 24, now=1100)
        self.assertEqual([r['text'] for r in self.reminders.active(1200)], ['Tomar o remédio', 'Comprar pão'])
        self.assertEqual([r['text'] for r in self.reminders.active(1000 + 3601)], ['Comprar pão'])   # The first one expired.

    def test_validation_and_permissions(self):
        with self.assertRaises(ValueError):
            self.reminders.add('Ana', 'u1', '   ', 1)
        with self.assertRaises(ValueError):
            self.reminders.add('Ana', 'u1', 'x', 0)
        reminder = self.reminders.add('Ana', 'u1', 'x' * 500, 1)
        self.assertEqual(len(self.reminders.active()[0]['text']), 200)
        with self.assertRaises(PermissionError):
            self.reminders.delete(reminder, 'u2', False)
        self.reminders.delete(reminder, 'u1', False)
        self.assertEqual(self.reminders.active(), [])
        with self.assertRaises(KeyError):
            self.reminders.delete('nope', 'u1', True)


class PersonMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.messages = PersonMessages(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_once_messages_stay_until_the_person_confirms(self):
        once = self.messages.add('Waldemar', 'u1', 'father', 'Te amo, pai.', 24, True, now=1000)
        every = self.messages.add('Lorena', 'u2', 'father', 'Boa tarde!', 24, False, now=1001)
        self.assertEqual([m['id'] for m in self.messages.for_person('father', 1100)], [once, every])
        self.messages.mark_shown([once, every], 1100)
        self.assertEqual(len(self.messages.for_person('father', 1200)), 2)         # Shown is not read: both come back.
        self.messages.mark_read([once], 1300)
        self.assertEqual([m['id'] for m in self.messages.for_person('father', 1400)], [every])   # "Once" is spent only when read.
        self.messages.mark_read([every], 1301)
        self.assertEqual([m['id'] for m in self.messages.for_person('father', 1500)], [every])   # "Every time" keeps coming back.
        self.assertEqual(self.messages.for_person('father', 1000 + 25 * 3600), [])                # Expired.

    def test_validation_permissions_and_listing(self):
        with self.assertRaises(ValueError):
            self.messages.add('Ana', 'u1', 'father', '  ', 24)
        with self.assertRaises(ValueError):
            self.messages.add('Ana', 'u1', 'father', 'x', 0)
        with self.assertRaises(KeyError):
            self.messages.add('Ana', 'u1', 'nobody', 'oi', 24)
        message = self.messages.add('Ana', 'u1', 'father', 'x' * 500, 24)
        listed = self.messages.active()
        self.assertEqual((len(listed[0]['text']), listed[0]['to_name']), (240, 'Meu pai'))
        with self.assertRaises(PermissionError):
            self.messages.delete(message, 'u2', False)
        self.messages.delete(message, 'u1', False)
        self.assertEqual(self.messages.active(), [])

    def test_view_once_message_is_consumed_when_the_screen_shows_it(self):
        single = self.messages.add('Waldemar', 'u1', 'father', 'Só para você', 24, True, now=1000, single=True)
        rows = self.messages.for_person('father', 1100)
        self.assertEqual([(r['id'], r['single']) for r in rows], [(single, 1)])
        self.messages.mark_read([single], 1105)                               # The screen confirms it started showing it.
        self.assertEqual(self.messages.for_person('father', 1200), [])         # Gone for good, even though nobody tapped "Li".
        listed = self.messages.active(1200, only_user='u1')[0]
        self.assertEqual((listed['single'], listed['read_at']), (1, 1105))     # The sender still sees it was viewed.

    def test_each_account_only_lists_its_own_messages(self):
        mine = self.messages.add('Waldemar', 'u1', 'father', 'Segredo meu', 24)
        self.messages.add('Lorena', 'u2', 'father', 'Segredo dela', 24)
        self.assertEqual([m['id'] for m in self.messages.active(only_user='u1')], [mine])
        self.assertEqual(len(self.messages.active(only_user='u3')), 0)
        self.assertEqual(len(self.messages.active()), 2)                      # The screen logic still sees all of them.
        with self.assertRaises(PermissionError):
            self.messages.delete(mine, 'u2', False)

    def test_read_messages_leave_the_list_after_a_week(self):
        message = self.messages.add('Ana', 'u1', 'father', 'oi', 24 * 30, True, now=1000)
        self.messages.mark_read([message], 1000)
        self.assertEqual(len(self.messages.active(1000 + 6 * 86400)), 1)
        self.assertEqual(self.messages.active(1000 + 8 * 86400), [])


class MessagePlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.store = PersonMessages(self.db)
        self.planner = MessagePlanner(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_waiting_messages_are_not_held_back_by_the_greeting_cooldown(self):
        self.store.add('Waldemar', 'u1', 'father', 'Te amo, pai', 24, True, now=1000)
        track = {'person_id': 'father', 'name': 'Meu pai'}
        self.assertIsNone(self.planner.pick([{'person_id': None}], 1010))          # Nobody recognised.
        self.assertIsNone(self.planner.pick([{'person_id': 'someone-else'}], 1010))
        person, _, waiting = self.planner.pick([track], 1010)
        self.assertEqual((person, [m['text'] for m in waiting]), ('father', ['Te amo, pai']))
        self.planner.delivered('father', 1010)
        self.assertIsNone(self.planner.pick([track], 1100))                       # Just shown: wait before retrying.
        self.assertIsNotNone(self.planner.pick([track], 1010 + 181))               # Unread: comes back after 3 minutes.
        self.store.mark_read([waiting[0]['id']], 1200)
        self.assertIsNone(self.planner.pick([track], 1010 + 400))                 # Read: never again.

    def test_every_time_messages_use_the_long_cooldown(self):
        self.store.add('Lorena', 'u2', 'father', 'Boa tarde!', 24, False, now=1000)
        track = {'person_id': 'father', 'name': 'Meu pai'}
        self.assertIsNotNone(self.planner.pick([track], 1010))
        self.planner.delivered('father', 1010)
        self.assertIsNone(self.planner.pick([track], 1010 + 600))                 # Not again while they stay around.
        self.assertIsNotNone(self.planner.pick([track], 1010 + 1801))


class MonitorDisplayTests(unittest.TestCase):
    def test_display_carries_state_and_expires_with_the_link(self):
        clock = [1000.0]
        desk = monitor.Desk(clock=lambda: clock[0])
        desk.configure(True, True, 'resting', True, 'Ana', '77', 'birthday', '70',
                       '[{"n":"Beto","d":"10-12"},{"n":"","d":"x"}]', '[{"i":"a","a":"Ana","t":"Leite","e":1500},{"i":"b","a":"X","t":"velho","e":900}]')
        shown = desk.display()
        self.assertEqual((shown['vigia'], shown['night']), ('resting', True))
        self.assertEqual(shown['greet'], {'name': 'Ana', 'id': '77', 'birthday': True, 'age': 70, 'msgs': [], 'quiet': False})
        self.assertEqual(shown['bdays'], [{'n': 'Beto', 'd': '10-12'}])
        self.assertEqual([r['t'] for r in shown['reminders']], ['Leite'])          # The expired one is dropped.
        clock[0] += 26
        self.assertIsNone(desk.display()['greet'])                                   # 25 s birthday window over.
        clock[0] += 10
        self.assertEqual(desk.display()['vigia'], None)                              # No poll for over 30 s: stale.
        self.assertEqual(desk.display()['reminders'], [])

    def test_greeting_carries_messages_for_the_person(self):
        desk = monitor.Desk(clock=lambda: 1000.0)
        desk.configure(True, True, 'resting', False, 'Ana', '5', '', '', '', '', False, '', '[{"t":"Te amo","a":"Waldemar"},{"t":"","a":"x"}]', False)
        greet = desk.display()['greet']
        self.assertEqual(greet['msgs'], [{'s': False, 'i': '', 't': 'Te amo', 'a': 'Waldemar'}])
        self.assertFalse(greet['quiet'])
        self.assertEqual(monitor.parse_quotes('[{"t":"x","s":1,"i":"a"}]'), [{'s': True, 'i': 'a', 't': 'x', 'a': ''}])
        self.assertEqual(monitor.parse_quotes('not json'), [])

    def test_acks_wait_until_the_dashboard_confirms_them(self):
        desk = monitor.Desk()
        good, other = 'a' * 32, 'b' * 32
        for message_id in (good, good, 'not-an-id', other):
            desk.ack(message_id)
        self.assertEqual(desk.acks, [good, other])                       # Deduplicated, malformed ids dropped.
        desk.configure(True, True, 'resting', False, acked=good)        # The dashboard stored the first one.
        self.assertEqual(desk.acks, [other])

    def test_sound_tests_reach_the_screen_and_expire(self):
        clock = [1000.0]
        desk = monitor.Desk(clock=lambda: clock[0])
        desk.configure(True, True, 'resting', False)
        first = desk.queue_test({'sound': 'message', 'volume': 250, 'text': 'Oi'})
        shown = desk.display()['tests']
        self.assertEqual(shown, [{'id': first, 'sound': 'message', 'volume': 100, 'text': 'Oi'}])
        for bad in ({'sound': 'siren', 'volume': 50}, {'sound': 'press', 'volume': 'loud'}, {'sound': 'press'}):
            with self.assertRaises(ValueError):
                desk.queue_test(bad)
        clock[0] += 16
        desk.configure(True, True, 'resting', False)
        self.assertEqual(desk.display()['tests'], [])

    def test_screen_settings_are_validated_and_clamped(self):
        self.assertEqual(monitor.parse_cfg(''), monitor.DEFAULT_CFG)
        cfg = monitor.parse_cfg('{"slide":9999,"awake":1,"sound":false,"vol":{"button":250,"call":-5,"help":"loud"},"calendar":false,"black":"yes","hints":["Oi","","x"]}')
        self.assertEqual((cfg['slide'], cfg['awake'], cfg['sound'], cfg['calendar'], cfg['black'], cfg['hints']), (120, 10, False, False, True, ['Oi', 'x']))
        self.assertEqual(cfg['vol'], {'button': 100, 'call': 0, 'help': 100, 'message': 80})    # Clamped; bad values fall back to the default.
        self.assertEqual(monitor.parse_cfg('[1]'), monitor.DEFAULT_CFG)

    def test_rejects_unknown_states_and_bad_json(self):
        desk = monitor.Desk()
        desk.configure(False, False, 'hacked', False, '<b>x</b>', '1', '', '', 'not json', '{"a":1}')
        shown = desk.display()
        self.assertIsNone(shown['vigia'])
        self.assertEqual((shown['bdays'], shown['reminders']), ([], []))


if __name__ == '__main__':
    unittest.main()
