"""Optional second opinion on a suspected fall: a small local vision model looks at the person's crop.

The detector can mistake an object (a bin bag, a pile of clothes) for a lying person. Before the alert goes out, the
crop of each flagged box is shown to LFM2.5-VL-450M (llama.cpp, CPU) with a closed question. The alert is dropped only
when the model clearly answers "no person"; any doubt, error or timeout lets the alert through exactly as it would
without this check. Everything stays on this computer.
"""
import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import cv2

log = logging.getLogger('camera-ai.fall-verify')

PROMPT = 'Há uma pessoa nesta imagem? Responda apenas sim ou não.'
PADDING = .08
MIN_SIDE = 64
MAX_SIDE = 512
TIMEOUT = 90


def crop_person(frame, box):
    """JPEG bytes of the box (with a little margin), or None when it is too small to judge."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = map(float, box)
    pad_x, pad_y = (x2 - x1) * PADDING, (y2 - y1) * PADDING
    x1, y1 = max(0, int(x1 - pad_x)), max(0, int(y1 - pad_y))
    x2, y2 = min(width, int(x2 + pad_x)), min(height, int(y2 + pad_y))
    crop = frame[y1:y2, x1:x2]
    if crop.shape[0] < MIN_SIDE or crop.shape[1] < MIN_SIDE:
        return None
    scale = MAX_SIDE / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    encoded, jpeg = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return jpeg.tobytes() if encoded else None


def parse_answer(text):
    """True for "sim", False for "não", None for anything else (never guess)."""
    words = (text or '').strip().lower().replace('ã', 'a').split()
    word = words[0].strip('.,!?;:') if words else ''
    return {'sim': True, 'nao': False}.get(word)


class FallVerifier:
    """Runs the model one crop at a time (a lock keeps two alerts from competing for the CPU)."""

    def __init__(self, directory, threads=2):
        self.directory, self.threads = directory, threads
        self.lock = threading.Lock()
        self.files = None       # (cli, model, mmproj) once found; False when missing.
        self.warned = False

    def find_files(self):
        if self.files is None:
            base = Path(self.directory) if self.directory else None
            found = None
            if base and base.is_dir():
                pick = lambda pattern: next(iter(sorted(base.glob(pattern))), None)
                found = (pick('**/llama-mtmd-cli'), pick('**/LFM2.5-VL-450M-*.gguf'), pick('**/mmproj-LFM2.5-VL-450m-*.gguf'))
            self.files = found if found and all(found) else False
        return self.files

    def available(self):
        if self.find_files():
            return True
        if not self.warned:
            self.warned = True
            log.warning('Confirmação de queda por IA ligada, mas LFM_DIR não tem o llama-mtmd-cli e os arquivos do modelo; avisos seguem sem filtro.')
        return False

    def has_person(self, jpeg):
        """True / False when the model answered clearly; None when it could not or did not."""
        files = self.find_files()
        if not files:
            return None
        cli, model, mmproj = map(str, files)
        with self.lock, tempfile.NamedTemporaryFile(suffix='.jpg') as handle:
            handle.write(jpeg)
            handle.flush()
            try:
                run = subprocess.run(
                    [cli, '-m', model, '--mmproj', mmproj, '--image', handle.name, '-t', str(self.threads),
                     '--temp', '0', '-n', '10', '-p', PROMPT],
                    capture_output=True, text=True, timeout=TIMEOUT, cwd=str(Path(cli).parent),
                    env={'LD_LIBRARY_PATH': str(Path(cli).parent), 'PATH': '/usr/bin:/bin'})
            except (OSError, subprocess.SubprocessError):
                log.exception('Falha ao consultar o modelo de confirmação de queda')
                return None
        return parse_answer(run.stdout)
