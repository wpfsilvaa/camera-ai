"""Photos of family members for the kitchen screen's "call this person" buttons: square, small, one file per person."""
import io
import re

import cv2
import numpy as np
from PIL import Image

from .config import DATA

AVATARS = DATA / 'avatars'
AVATARS.mkdir(exist_ok=True)
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
SIDE = 192
OWNER_ID = re.compile(r'^[a-f0-9]{32}$')


def square(content):
    """Centre-cropped SIDE x SIDE JPEG from an uploaded picture."""
    with Image.open(io.BytesIO(content)) as picture:
        if picture.width * picture.height > MAX_PIXELS:
            raise ValueError('Imagem muito grande.')
        picture.verify()
    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)   # EXIF rotation is applied.
    if image is None:
        raise ValueError('Imagem inválida.')
    height, width = image.shape[:2]
    edge = min(height, width)
    top, left = (height - edge) // 2, (width - edge) // 2
    crop = cv2.resize(image[top:top + edge, left:left + edge], (SIDE, SIDE), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError('Não foi possível processar a imagem.')
    return data.tobytes()


class Avatars:
    def __init__(self, directory=AVATARS):
        self.directory = directory
        directory.mkdir(exist_ok=True)

    def path(self, owner_id):
        if not OWNER_ID.match(str(owner_id)):
            raise KeyError('Usuário inválido.')
        return self.directory / f'{owner_id}.jpg'

    def has(self, owner_id):
        try:
            return self.path(owner_id).is_file()
        except KeyError:
            return False

    def rev(self, owner_id):
        """Changes whenever the picture does (the screen compares it to know what to download again)."""
        return str(int(self.path(owner_id).stat().st_mtime)) if self.has(owner_id) else ''

    def save(self, owner_id, content):
        self.path(owner_id).write_bytes(square(content))

    def delete(self, owner_id):
        try:
            self.path(owner_id).unlink(missing_ok=True)
        except KeyError:
            pass
