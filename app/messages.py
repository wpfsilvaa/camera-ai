"""Messages left for a specific person: shown on the kitchen screen when that person is recognised."""
import time
import uuid

MAX_TEXT = 240
MAX_ACTIVE = 40
KEEP_READ_DAYS = 7   # Read "once" messages stay in the list a while so the sender sees they were read.


class PersonMessages:
    def __init__(self, db):
        self.db = db

    def purge(self, now):
        self.db.execute('DELETE FROM person_messages WHERE expires<=? OR (once=1 AND read_at IS NOT NULL AND read_at<?)', (now, now - KEEP_READ_DAYS * 86400))

    def active(self, now=None):
        now = now or time.time()
        self.purge(now)
        return self.db.rows('''SELECT m.*,p.name AS to_name FROM person_messages m LEFT JOIN people p ON p.id=m.to_person ORDER BY m.created DESC''')

    def add(self, author, user_id, to_person, text, hours, once=True, now=None):
        now = now or time.time()
        text = ' '.join(''.join(ch for ch in str(text) if ch.isprintable() or ch in '\n ').split())[:MAX_TEXT]
        if not text:
            raise ValueError('Escreva o recado.')
        if not 0 < hours <= 24 * 90:
            raise ValueError('Escolha por quanto tempo o recado vale.')
        if not self.db.rows('SELECT 1 FROM people WHERE id=?', (to_person,)):
            raise KeyError('Escolha uma pessoa cadastrada.')
        if len(self.active(now)) >= MAX_ACTIVE:
            raise ValueError(f'Há {MAX_ACTIVE} recados ativos. Remova alguns antes de escrever outro.')
        message_id = uuid.uuid4().hex
        self.db.execute('INSERT INTO person_messages(id,to_person,author,user_id,text,created,expires,once) VALUES(?,?,?,?,?,?,?,?)',
                        (message_id, to_person, str(author)[:60] or 'Alguém', user_id, text, now, now + hours * 3600, int(once)))
        return message_id

    def for_person(self, person_id, now=None):
        """Messages to show now to this person: valid, and for "once" messages only until the person taps "Li"."""
        now = now or time.time()
        return self.db.rows('SELECT id,author,text,once FROM person_messages WHERE to_person=? AND expires>? AND (once=0 OR read_at IS NULL) ORDER BY created',
                            (person_id, now))

    def mark_shown(self, message_ids, now=None):
        now = now or time.time()
        for message_id in message_ids:
            self.db.execute('UPDATE person_messages SET shown=shown+1,last_shown=? WHERE id=?', (now, message_id))

    def mark_read(self, message_ids, now=None):
        """The person confirmed on the screen that they read it."""
        now = now or time.time()
        for message_id in message_ids:
            self.db.execute('UPDATE person_messages SET read_at=? WHERE id=?', (now, message_id))

    def delete(self, message_id, user_id, is_admin):
        rows = self.db.rows('SELECT user_id FROM person_messages WHERE id=?', (message_id,))
        if not rows:
            raise KeyError('Recado não encontrado.')
        if not is_admin and rows[0]['user_id'] != user_id:
            raise PermissionError('Só quem escreveu o recado (ou um administrador) pode removê-lo.')
        self.db.execute('DELETE FROM person_messages WHERE id=?', (message_id,))


class MessagePlanner:
    """Decides when a recognised person's unread messages go on the kitchen screen without a greeting.

    The greeting has its own 30-minute cooldown; waiting messages must not be held back by it. Unread
    "until read" messages come back every `retry` seconds; "every time" messages respect the longer
    `cooldown`, so they do not repeat while the person stays in front of the camera.
    """

    def __init__(self, store, retry=180, cooldown=1800):
        self.store, self.retry, self.cooldown = store, retry, cooldown
        self.shown = {}

    def pick(self, tracks, now):
        """(person_id, [message rows]) for the first recognised person with something to show, or None."""
        for track in tracks:
            person = track.get('person_id')
            if not person or now - self.shown.get(person, -self.cooldown) < self.retry:
                continue
            waiting = [m for m in self.store.for_person(person, now) if m['once'] or now - self.shown.get(person, -self.cooldown) >= self.cooldown]
            if waiting:
                return person, track, waiting
        return None

    def delivered(self, person, now):
        self.shown[person] = now
