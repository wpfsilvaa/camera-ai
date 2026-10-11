import tempfile
import unittest
from pathlib import Path

from app.db import Database
from app.journal import Journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Database(Path(self.tmp.name) / 'j.sqlite3'))

    def tearDown(self):
        self.tmp.cleanup()

    def test_lists_newest_first_and_pages(self):
        for index in range(5):
            self.journal.add('Ana', 'u1', f'nota {index}', now=1000 + index)
        notes = self.journal.list(limit=3)
        self.assertEqual([n['text'] for n in notes], ['nota 4', 'nota 3', 'nota 2'])
        older = self.journal.list(before=notes[-1]['created'], limit=3)
        self.assertEqual([n['text'] for n in older], ['nota 1', 'nota 0'])

    def test_validation_tag_and_permissions(self):
        with self.assertRaises(ValueError):
            self.journal.add('Ana', 'u1', '   ')
        note = self.journal.add('Ana', 'u1', 'x' * 900, tag='inventada')
        row = self.journal.list()[0]
        self.assertEqual((len(row['text']), row['tag']), (500, 'geral'))
        with self.assertRaises(PermissionError):
            self.journal.delete(note, 'u2', False)
        self.journal.delete(note, 'u2', True)   # An administrator may remove anything.
        self.assertEqual(self.journal.list(), [])
        with self.assertRaises(KeyError):
            self.journal.delete('nope', 'u1', True)


if __name__ == '__main__':
    unittest.main()
