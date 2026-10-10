import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name

from app.db import Database
from app.pacing import Greeter, birthday_today, first_name, is_night, vigia_state
from app.config import Settings
from app.recognition import Recognition
from app.reminders import Reminders

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'notebook'))
import monitor


class VigiaTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(vigia_state(False, 22, 6, 23, True), 'off')
        self.assertEqual(vigia_state(True, 22, 6, 23, True), 'resting')
        self.assertEqual(vigia_state(True, 22, 6, 23, False), 'analysing')
        self.assertEqual(vigia_state(True, 22, 6, 12, False), 'scheduled')

    def test_night_follows_watch_mode_then_quiet_hours(self):
        settings = Settings(sentinel_enabled=True, sentinel_start_hour=20, sentinel_end_hour=5)
        self.assertTrue(is_night(settings, 21) and not is_night(settings, 12))
        plain = Settings()   # Watch mode off: the default quiet hours (22h to 7h) apply.
        self.assertTrue(is_night(plain, 23) and not is_night(plain, 15))


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


class MonitorDisplayTests(unittest.TestCase):
    def test_display_carries_state_and_expires_with_the_link(self):
        clock = [1000.0]
        desk = monitor.Desk(clock=lambda: clock[0])
        desk.configure(True, True, 'resting', True, 'Ana', '77', 'birthday', '70',
                       '[{"n":"Beto","d":"10-12"},{"n":"","d":"x"}]', '[{"i":"a","a":"Ana","t":"Leite","e":1500},{"i":"b","a":"X","t":"velho","e":900}]')
        shown = desk.display()
        self.assertEqual((shown['vigia'], shown['night']), ('resting', True))
        self.assertEqual(shown['greet'], {'name': 'Ana', 'id': '77', 'birthday': True, 'age': 70})
        self.assertEqual(shown['bdays'], [{'n': 'Beto', 'd': '10-12'}])
        self.assertEqual([r['t'] for r in shown['reminders']], ['Leite'])          # The expired one is dropped.
        clock[0] += 26
        self.assertIsNone(desk.display()['greet'])                                   # 25 s birthday window over.
        clock[0] += 10
        self.assertEqual(desk.display()['vigia'], None)                              # No poll for over 30 s: stale.
        self.assertEqual(desk.display()['reminders'], [])

    def test_rejects_unknown_states_and_bad_json(self):
        desk = monitor.Desk()
        desk.configure(False, False, 'hacked', False, '<b>x</b>', '1', '', '', 'not json', '{"a":1}')
        shown = desk.display()
        self.assertIsNone(shown['vigia'])
        self.assertEqual((shown['bdays'], shown['reminders']), ([], []))


if __name__ == '__main__':
    unittest.main()
