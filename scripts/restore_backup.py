"""Restore a Casa Presente backup into the data folder (history, settings, faces, alert photos).

    systemctl --user stop camera-ai.service
    .venv/bin/python scripts/restore_backup.py /media/hd/casa-presente-20260930-030000.tar.gz
    systemctl --user start camera-ai.service

The current files are moved aside to data/before-restore-<time>/ instead of being deleted.
Pair WhatsApp again afterwards: its session is not part of backups.
"""
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('CAMERA_DATA_DIR', ROOT / 'data')).resolve()
ITEMS = ('history.sqlite3', 'settings.json', 'people', 'alerts')


def restore(archive, data=DATA):
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data) as work, tarfile.open(archive) as bundle:
        bundle.extractall(work, filter='data')  # Rejects absolute paths and links outside the folder.
        extracted = Path(work)
        if not (extracted / 'history.sqlite3').is_file():
            raise SystemExit('Arquivo inválido: history.sqlite3 não encontrado.')
        with sqlite3.connect(extracted / 'history.sqlite3') as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise SystemExit('Banco do backup corrompido; nada foi alterado.')
        aside = data / f'before-restore-{time.strftime("%Y%m%d-%H%M%S")}'
        aside.mkdir()
        for name in ITEMS:
            for suffix in ('', '-wal', '-shm') if name == 'history.sqlite3' else ('',):
                if (data / f'{name}{suffix}').exists():
                    shutil.move(data / f'{name}{suffix}', aside / f'{name}{suffix}')
            if (extracted / name).exists():
                shutil.move(extracted / name, data / name)
    return aside


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    previous = restore(Path(sys.argv[1]))
    print(f'Backup restaurado em {DATA}. Arquivos anteriores guardados em {previous}.')
