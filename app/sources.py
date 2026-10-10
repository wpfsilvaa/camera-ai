"""Camera sources that live on this computer (USB/V4L2) instead of an RTSP address.

Accepted forms: "0" (device index), "/dev/video0", "/dev/v4l/by-id/...", each optionally prefixed with
"usb:" and followed by "?1280x720@30" to ask for a size and frame rate (default 1920x1080 at 30).
A USB camera opens in one program at a time: MediaMTX must not be capturing the same device.
"""
import re
from pathlib import Path

DEFAULT_MODE = (1920, 1080, 30)
MODE = re.compile(r'^(\d{3,4})x(\d{3,4})(?:@(\d{1,3}))?$')


def local_device(source):
    """(device, (width, height, fps)) for a local camera source, or None for RTSP/HTTP addresses and files."""
    text = source.strip()
    if text.startswith('usb:'):
        text = text[4:]
    text, _, query = text.partition('?')
    if not (text.isdigit() or text.startswith('/dev/')):
        return None
    mode = DEFAULT_MODE
    if query:
        found = MODE.match(query)
        if not found:
            raise ValueError('Use o formato ?1280x720@30 depois do dispositivo USB.')
        width, height, fps = int(found[1]), int(found[2]), int(found[3] or DEFAULT_MODE[2])
        if not (160 <= width <= 3840 and 120 <= height <= 2160 and 1 <= fps <= 60):
            raise ValueError('Resolução ou taxa de quadros USB fora do intervalo aceito.')
        mode = (width, height, fps)
    return (int(text) if text.isdigit() else text), mode


def usb_cameras():
    """Capture devices present now, preferring the stable /dev/v4l/by-id names."""
    found = []
    by_id = Path('/dev/v4l/by-id')
    if by_id.is_dir():
        found += [{'source': f'usb:{p}', 'name': p.name.removesuffix('-video-index0')} for p in sorted(by_id.glob('*-video-index0'))]
    if not found:
        found = [{'source': f'usb:{p}', 'name': p.name} for p in sorted(Path('/dev').glob('video*')) if p.name[5:].isdigit()]
    return found
