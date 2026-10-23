"""Picture controls of a USB camera (exposure, gain, sharpness, focus…) as named profiles, applied with v4l2-ctl.

The values live in the camera, not in the program: they are lost when it is unplugged or the computer restarts, so the chosen
profile is applied again every time the camera is opened.
"""
import logging
import re
import shutil
import subprocess
from pathlib import Path

from .sources import local_device

log = logging.getLogger(__name__)

# name -> (minimum, maximum). The ranges of a Logitech C922; others are clamped by the camera itself.
RANGES = {'brightness': (0, 255), 'contrast': (0, 255), 'saturation': (0, 255), 'sharpness': (0, 255), 'gain': (0, 255),
          'backlight_compensation': (0, 1), 'power_line_frequency': (0, 2), 'white_balance_automatic': (0, 1),
          'white_balance_temperature': (2000, 6500), 'auto_exposure': (0, 3), 'exposure_time_absolute': (3, 2047),
          'exposure_dynamic_framerate': (0, 1), 'focus_automatic_continuous': (0, 1), 'focus_absolute': (0, 250)}
FIRST = ('auto_exposure', 'focus_automatic_continuous', 'white_balance_automatic', 'exposure_dynamic_framerate')   # Modes first, then the values they unlock.
CUSTOM_KEYS = ('exposure_time_absolute', 'gain', 'sharpness', 'brightness', 'contrast', 'focus_absolute')

AUTO = {'auto_exposure': 3, 'exposure_dynamic_framerate': 0, 'white_balance_automatic': 1, 'focus_automatic_continuous': 1, 'gain': 0,
        'sharpness': 128, 'brightness': 128, 'contrast': 128, 'saturation': 128, 'backlight_compensation': 0, 'power_line_frequency': 2}
MANUAL = {'auto_exposure': 1, 'exposure_dynamic_framerate': 0, 'white_balance_automatic': 1, 'focus_automatic_continuous': 0,
          'power_line_frequency': 2, 'saturation': 128, 'backlight_compensation': 0, 'brightness': 128, 'contrast': 128}

PROFILES = {
    'keep': {'label': 'Não mexer (como a câmera está)', 'description': 'O programa não altera nenhum ajuste da câmera.', 'controls': {}},
    'auto': {'label': 'Automático (padrão da câmera)', 'description': 'Exposição, foco e balanço de branco automáticos. Em pouca luz a câmera reduz os quadros por segundo.', 'controls': AUTO},
    'balanced': {'label': 'Manual equilibrado', 'description': 'Exposição fixa média, ganho moderado, foco fixo para 1 a 3 m. Bom ponto de partida para a cozinha.',
                 'controls': {**MANUAL, 'exposure_time_absolute': 200, 'gain': 140, 'sharpness': 110, 'focus_absolute': 30}},
    'low_light': {'label': 'Pouca luz (o seu teste)', 'description': 'Exposição longa e ganho no máximo: clareia bastante, mas tem ruído e borra quem anda. Foco no infinito.',
                  'controls': {**MANUAL, 'exposure_time_absolute': 333, 'gain': 255, 'sharpness': 100, 'focus_absolute': 0}},
    'motion': {'label': 'Anti-borrão (quem anda)', 'description': 'Exposição curta para congelar o movimento, com ganho alto para compensar. Pede um ambiente razoavelmente iluminado.',
               'controls': {**MANUAL, 'exposure_time_absolute': 120, 'gain': 200, 'sharpness': 120, 'focus_absolute': 30}},
    'bright_day': {'label': 'Dia claro', 'description': 'Exposição bem curta e ganho baixo: imagem limpa e sem ruído quando há muita luz.',
                   'controls': {**MANUAL, 'exposure_time_absolute': 60, 'gain': 40, 'sharpness': 128, 'focus_absolute': 30}},
    'close_faces': {'label': 'Rostos próximos (exposição automática)', 'description': 'A câmera decide a exposição; o foco fica fixo para perto (cerca de 1 m), sem “caçar” foco.',
                    'controls': {**AUTO, 'focus_automatic_continuous': 0, 'focus_absolute': 50, 'sharpness': 115}},
    'custom': {'label': 'Personalizado', 'description': 'Os valores dos controles deslizantes abaixo.', 'controls': {}},
}


def clean(values):
    """Only known controls, as integers inside their range."""
    out = {}
    for name, value in (values or {}).items():
        if name in RANGES and isinstance(value, (int, float)) and not isinstance(value, bool):
            low, high = RANGES[name]
            out[name] = min(max(int(value), low), high)
    return out


def controls_for(profile, custom=None):
    if profile == 'custom':
        return {**MANUAL, **clean(custom)}
    return dict(PROFILES.get(profile, PROFILES['keep'])['controls'])


def device_of(source):
    """The /dev path of a local USB camera, or None."""
    try:
        found = local_device(source)
    except ValueError:
        return None
    if not found:
        return None
    device = found[0]
    return f'/dev/video{device}' if isinstance(device, int) else device


def available():
    return shutil.which('v4l2-ctl') is not None


def commands(device, controls):
    """The v4l2-ctl calls that set `controls`: modes first (so exposure and focus values are accepted), then the rest."""
    controls = clean(controls)
    first = [f'{name}={controls[name]}' for name in FIRST if name in controls]
    rest = [f'{name}={value}' for name, value in controls.items() if name not in FIRST]
    return [['v4l2-ctl', '-d', device, f'--set-ctrl={",".join(group)}'] for group in (first, rest) if group]


def apply(source, controls):
    """Set the controls on the camera of `source`. Returns how many controls were set (0 when nothing to do)."""
    device = device_of(source)
    if not device or not controls or not available():
        return 0
    done = 0
    for command in commands(device, controls):
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if result.returncode:
            log.warning('v4l2-ctl falhou (%s): %s', ' '.join(command[3:]), (result.stderr or result.stdout).strip()[:200])
        else:
            done += command[3].count(',') + 1   # "--set-ctrl=a=1,b=2" sets two.
    return done


LINE = re.compile(r'^\s*(\w+)\s+(?:0x[0-9a-f]+\s+)?\(\w+\)\s*:\s*(.*)$')


def read(source):
    """Current values of the camera: {control: value}, or None when it cannot be read."""
    device = device_of(source)
    if not device or not available():
        return None
    try:
        output = subprocess.run(['v4l2-ctl', '-d', device, '--list-ctrls'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    values = {}
    for line in output.splitlines():
        found = LINE.match(line)
        if found and found[1] in RANGES:
            value = re.search(r'value=(-?\d+)', found[2])
            if value:
                values[found[1]] = int(value[1])
    return values or None
