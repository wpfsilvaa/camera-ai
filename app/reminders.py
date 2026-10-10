"""Reminders and messages left for the kitchen screen: short text with an expiry, cycled on the notebook."""
import time
import uuid

MAX_ACTIVE = 20
MAX_TEXT = 200
MAX_HOURS = 24 * 14


class Reminders:
    def __init__(self, db):
        self.db = db

    def purge(self, now):
        self.db.execute('DELETE FROM reminders WHERE expires<=?', (now,))

    def active(self, now=None):
        now = now or time.time()
        self.purge(now)
        return self.db.rows('SELECT id,author,user_id,text,created,expires FROM reminders ORDER BY created')

    def add(self, author, user_id, text, hours, now=None):
        now = now or time.time()
        text = ' '.join(''.join(ch for ch in str(text) if ch.isprintable() or ch in '\n ').split())[:MAX_TEXT]
        if not text:
            raise ValueError('Escreva o lembrete.')
        if not 0 < hours <= MAX_HOURS:
            raise ValueError('Escolha por quanto tempo o lembrete fica na tela.')
        if len(self.active(now)) >= MAX_ACTIVE:
            raise ValueError(f'Há {MAX_ACTIVE} lembretes ativos. Remova algum antes de adicionar outro.')
        reminder_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO reminders(id,author,user_id,text,created,expires) VALUES(?,?,?,?,?,?)',
                        (reminder_id, str(author)[:60] or 'Alguém', user_id, text, now, now + hours * 3600))
        return reminder_id

    def delete(self, reminder_id, user_id, is_admin):
        rows = self.db.rows('SELECT user_id FROM reminders WHERE id=?', (reminder_id,))
        if not rows:
            raise KeyError('Lembrete não encontrado.')
        if not is_admin and rows[0]['user_id'] != user_id:
            raise PermissionError('Só quem escreveu o lembrete (ou um administrador) pode removê-lo.')
        self.db.execute('DELETE FROM reminders WHERE id=?', (reminder_id,))
