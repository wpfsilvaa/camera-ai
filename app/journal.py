"""Family logbook: short dated notes the whole family can read ("complained about his knee"), kept for the doctor's visit."""
import time
import uuid

MAX_TEXT = 500
TAGS = ('geral', 'saude', 'humor', 'remedio')
PAGE = 50


class Journal:
    def __init__(self, db):
        self.db = db

    def add(self, author, user_id, text, tag='geral', now=None):
        now = now or time.time()
        text = ' '.join(''.join(ch for ch in str(text) if ch.isprintable() or ch in '\n ').split())[:MAX_TEXT]
        if not text:
            raise ValueError('Escreva a anotação.')
        if tag not in TAGS:
            tag = 'geral'
        note_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO journal(id,author,user_id,text,tag,created) VALUES(?,?,?,?,?,?)',
                        (note_id, str(author)[:60] or 'Alguém', user_id, text, tag, now))
        return note_id

    def list(self, before=None, limit=PAGE):
        """Newest first; `before` (a created timestamp) continues an earlier page."""
        limit = max(1, min(int(limit), 200))
        if before:
            return self.db.rows('SELECT * FROM journal WHERE created<? ORDER BY created DESC LIMIT ?', (before, limit))
        return self.db.rows('SELECT * FROM journal ORDER BY created DESC LIMIT ?', (limit,))

    def delete(self, note_id, user_id, is_admin):
        rows = self.db.rows('SELECT user_id FROM journal WHERE id=?', (note_id,))
        if not rows:
            raise KeyError('Anotação não encontrada.')
        if not is_admin and rows[0]['user_id'] != user_id:
            raise PermissionError('Só quem escreveu a anotação pode removê-la.')
        self.db.execute('DELETE FROM journal WHERE id=?', (note_id,))
