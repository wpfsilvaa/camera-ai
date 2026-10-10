"""Family photos shown on the kitchen screen's photo frame: uploaded by any account, stored resized."""
import io
import time
import uuid

import cv2
import numpy as np
from PIL import Image

from .config import DATA

PHOTOS = DATA / 'photos'
PHOTOS.mkdir(exist_ok=True)
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_PHOTOS = 300
LONG_SIDE = 1920
THUMB_SIDE = 360


def prepare(content):
    """(full JPEG bytes, thumbnail JPEG bytes) from an uploaded image, validated and resized."""
    with Image.open(io.BytesIO(content)) as photo:
        if photo.width * photo.height > MAX_PIXELS:
            raise ValueError('Imagem muito grande.')
        photo.verify()
    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)   # EXIF rotation is applied.
    if image is None:
        raise ValueError('Imagem inválida.')

    def encode(side, quality):
        height, width = image.shape[:2]
        scale = min(1.0, side / max(height, width))
        resized = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
        ok, data = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            raise ValueError('Não foi possível processar a imagem.')
        return data.tobytes()

    return encode(LONG_SIDE, 85), encode(THUMB_SIDE, 80)


class Photos:
    def __init__(self, db, directory=PHOTOS):
        self.db, self.directory = db, directory
        directory.mkdir(exist_ok=True)

    def path(self, photo_id, thumb=False):
        return self.directory / f'{photo_id}{".thumb" if thumb else ""}.jpg'

    def list(self):
        return self.db.rows('SELECT id,author,user_id,created FROM photos ORDER BY created')

    def add(self, author, user_id, content, now=None):
        if len(self.list()) >= MAX_PHOTOS:
            raise ValueError(f'O limite de {MAX_PHOTOS} fotos foi atingido. Remova algumas antes de enviar outras.')
        full, thumb = prepare(content)
        photo_id = uuid.uuid4().hex
        self.path(photo_id).write_bytes(full)
        self.path(photo_id, True).write_bytes(thumb)
        self.db.execute('INSERT INTO photos(id,author,user_id,created) VALUES(?,?,?,?)', (photo_id, str(author)[:60] or 'Alguém', user_id, now or time.time()))
        return photo_id

    def delete(self, photo_id, user_id, is_admin):
        rows = self.db.rows('SELECT user_id FROM photos WHERE id=?', (photo_id,))
        if not rows:
            raise KeyError('Foto não encontrada.')
        if not is_admin and rows[0]['user_id'] != user_id:
            raise PermissionError('Só quem enviou a foto (ou um administrador) pode removê-la.')
        self.db.execute('DELETE FROM photos WHERE id=?', (photo_id,))
        for thumb in (False, True):
            self.path(photo_id, thumb).unlink(missing_ok=True)
