import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from uuid import uuid4

COOKIE = 'casa_session'
ROLES = ('admin', 'family')
SESSION_SECONDS = 12 * 3600
REMEMBER_SECONDS = 30 * 24 * 3600
MAX_FAILURES, FAILURE_WINDOW = 5, 15 * 60
USERNAME = re.compile(r'[a-z0-9._-]{3,32}')
# scrypt with ~16 MB of memory: slow enough for guessing, fast enough for a login.
SCRYPT = {'n': 2**14, 'r': 8, 'p': 1}


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, n, r, p, salt, digest = stored.split('$')
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


# Compared when the user does not exist, so both paths take the same time.
DUMMY_HASH = hash_password(secrets.token_hex(16))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.failures = {}
        with db.connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'family', created REAL NOT NULL, last_login REAL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created REAL NOT NULL, expires REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
            ''')
        # Keep the password from the old Basic Auth setup as the first administrator.
        password = os.environ.get('DASHBOARD_PASSWORD', '')
        if password and not self.enabled():
            self.create_user('admin', 'Administrador', password, 'admin', validate=False)

    def enabled(self):
        return bool(self.db.rows('SELECT 1 FROM users LIMIT 1'))

    def users(self):
        return self.db.rows('SELECT id,username,name,role,created,last_login FROM users ORDER BY created')

    def create_user(self, username, name, password, role, validate=True):
        username = username.strip().lower()
        if not USERNAME.fullmatch(username):
            raise ValueError('Usuário deve ter de 3 a 32 letras minúsculas, números, ponto, hífen ou sublinhado.')
        if role not in ROLES:
            raise ValueError('Perfil inválido.')
        if validate:
            check_password(password)
        if self.db.rows('SELECT 1 FROM users WHERE username=?', (username,)):
            raise ValueError('Já existe um usuário com esse nome.')
        user_id = uuid4().hex
        self.db.execute('INSERT INTO users(id,username,name,password_hash,role,created) VALUES(?,?,?,?,?,?)',
                        (user_id, username, name.strip() or username, hash_password(password), role, time.time()))
        return user_id

    def update_user(self, user_id, name=None, role=None, password=None, keep_session=None):
        with self.lock, self.db.connect() as connection:
            row = connection.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise KeyError('Usuário não encontrado.')
            if role is not None:
                if role not in ROLES:
                    raise ValueError('Perfil inválido.')
                if row['role'] == 'admin' and role != 'admin' and self._admins(connection) == 1:
                    raise ValueError('Mantenha pelo menos um administrador.')
                connection.execute('UPDATE users SET role=? WHERE id=?', (role, user_id))
            if name is not None:
                connection.execute('UPDATE users SET name=? WHERE id=?', (name.strip() or 'Usuário', user_id))
            if password is not None:
                check_password(password)
                connection.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(password), user_id))
            if password is not None or role is not None:
                # Credential or permission changes sign the account out elsewhere.
                connection.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',
                                   (user_id, token_hash(keep_session) if keep_session else ''))

    def delete_user(self, user_id):
        with self.lock, self.db.connect() as connection:
            row = connection.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise KeyError('Usuário não encontrado.')
            if row['role'] == 'admin' and self._admins(connection) == 1:
                raise ValueError('Mantenha pelo menos um administrador.')
            connection.execute('DELETE FROM users WHERE id=?', (user_id,))

    @staticmethod
    def _admins(connection):
        return connection.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]

    def blocked_for(self, client):
        now = time.time()
        with self.lock:
            recent = [t for t in self.failures.pop(client, []) if now - t < FAILURE_WINDOW]
            if recent:  # Keep only clients with recent failures, so the map cannot grow forever.
                self.failures[client] = recent
            return int(recent[0] + FAILURE_WINDOW - now) + 1 if len(recent) >= MAX_FAILURES else 0

    def login(self, client, username, password, remember):
        rows = self.db.rows('SELECT * FROM users WHERE username=?', (username.strip().lower(),))
        valid = verify_password(password, rows[0]['password_hash'] if rows else DUMMY_HASH) and bool(rows)
        if not valid:
            with self.lock:
                self.failures.setdefault(client, []).append(time.time())
            return None, 0
        with self.lock:
            self.failures.pop(client, None)
        now, token = time.time(), secrets.token_urlsafe(32)
        lifetime = REMEMBER_SECONDS if remember else SESSION_SECONDS
        with self.db.connect() as connection:
            connection.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash(token), rows[0]['id'], now, now + lifetime))
            connection.execute('UPDATE users SET last_login=? WHERE id=?', (now, rows[0]['id']))
        return token, lifetime

    def session_user(self, token):
        return self.current(token)[1]

    def current(self, token):
        """(login required, signed-in user) with a single database connection per request."""
        with self.db.connect() as connection:
            if not connection.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                return False, None
            if not token:
                return True, None
            row = connection.execute('''SELECT u.id,u.username,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires>?''', (token_hash(token), time.time())).fetchone()
            return True, dict(row) if row else None

    def prune_sessions(self):
        self.db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))

    def logout(self, token):
        if token:
            self.db.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))

    def change_own_password(self, user_id, current, new, token):
        rows = self.db.rows('SELECT password_hash FROM users WHERE id=?', (user_id,))
        if not rows or not verify_password(current, rows[0]['password_hash']):
            raise ValueError('Senha atual incorreta.')
        self.update_user(user_id, password=new, keep_session=token)


def check_password(password):
    if len(password) < 8 or len(password) > 128:
        raise ValueError('A senha deve ter de 8 a 128 caracteres.')
