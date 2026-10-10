import os
import tempfile
import unittest
from pathlib import Path

TEMP = tempfile.TemporaryDirectory()
os.environ['CAMERA_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = ''

from app.auth import Auth
from app.db import Database


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'h.sqlite3')
        self.auth = Auth(self.db)
        self.admin = self.auth.create_user('admin', 'Administrador', 'senha-longa-123', 'admin')
        self.other = self.auth.create_user('ana', 'Ana', 'senha-longa-456', 'family')

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, user_id):
        return self.db.rows('SELECT name,username FROM users WHERE id=?', (user_id,))[0]

    def test_changes_name_and_login(self):
        result = self.auth.update_profile(self.admin, '  Waldemar   Silva ', ' Waldemar ')
        self.assertEqual(result, {'id': self.admin, 'name': 'Waldemar Silva', 'username': 'waldemar'})
        self.assertEqual(self.row(self.admin), {'name': 'Waldemar Silva', 'username': 'waldemar'})
        self.assertIsNotNone(self.auth.login('127.0.0.1', 'waldemar', 'senha-longa-123', False)[0])   # The new login works.

    def test_rejects_taken_or_invalid_values(self):
        with self.assertRaises(ValueError):
            self.auth.update_profile(self.admin, 'Admin', 'ana')          # Someone else's login.
        for bad in ('ab', 'Com Espaço', 'x' * 40, 'maiúscula'):
            with self.assertRaises(ValueError):
                self.auth.update_profile(self.admin, 'Nome', bad)
        with self.assertRaises(ValueError):
            self.auth.update_profile(self.admin, '   ', 'admin2')
        with self.assertRaises(KeyError):
            self.auth.update_profile('missing', 'Nome', 'valido')
        self.assertEqual(self.row(self.admin)['username'], 'admin')        # Nothing changed by the failures.

    def test_keeping_your_own_login_is_allowed(self):
        self.auth.update_profile(self.admin, 'Novo Nome', 'admin')
        self.assertEqual(self.row(self.admin), {'name': 'Novo Nome', 'username': 'admin'})


if __name__ == '__main__':
    unittest.main()
