"""Daily copy of what cannot be recovered: history, settings, faces and alert photos.

Videos are not included (they expire anyway and would fill the destination). The WhatsApp
session is left out on purpose: it grants access to the account; pairing again takes a minute.
Each backup is one .tar.gz written under a temporary name and renamed when complete, so a
full disk or an unplugged drive never leaves a file that looks valid.
"""
import json
import logging
import sqlite3
import tarfile
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import DATA, PEOPLE
from .db import TZ

log = logging.getLogger(__name__)

PREFIX = 'casa-presente-'
STATUS = DATA / 'backup.json'
RETRY_SECONDS = 3600


class Backups:
    def __init__(self, db, config, alerts=None):
        self.db, self.config, self.alerts = db, config, alerts
        self.lock = threading.Lock()

    def status(self):
        try:
            return json.loads(STATUS.read_text())
        except (OSError, ValueError):
            return {}

    def save_status(self, **values):
        STATUS.write_text(json.dumps({**self.status(), **values}))

    def files(self, directory=None):
        folder = Path(directory or self.config.get().backup_dir)
        if not folder.is_dir():
            return []
        return sorted(folder.glob(f'{PREFIX}*.tar.gz'), reverse=True)

    def due(self, now=None):
        settings = self.config.get()
        if not settings.backup_enabled or not settings.backup_dir:
            return False
        now = now or time.time()
        local = datetime.fromtimestamp(now, TZ)
        status = self.status()
        done_today = status.get('last_ok') and datetime.fromtimestamp(status['last_ok'], TZ).date() == local.date()
        recently_tried = now - status.get('last_attempt', 0) < RETRY_SECONDS
        return local.hour >= settings.backup_hour and not done_today and not recently_tried

    def run(self, now=None):
        """Create one backup now; returns its path. Raises ValueError with a readable reason."""
        now = now or time.time()
        settings = self.config.get()
        with self.lock:
            self.save_status(last_attempt=now)
            try:
                path = self.create(Path(settings.backup_dir), now)
                self.rotate(Path(settings.backup_dir), settings.backup_keep)
            except (OSError, sqlite3.Error, tarfile.TarError, ValueError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else f'Falha ao gravar o backup: {exc}'
                self.save_status(last_error=reason, last_error_at=now)
                log.error('Backup: %s', reason)
                if self.alerts:
                    day = datetime.fromtimestamp(now, TZ).date().isoformat()
                    self.alerts.raise_alert(f'backup-{day}', 'backup', f'⚠️ O backup diário falhou: {reason}', now)
                raise ValueError(reason) from exc
            size = path.stat().st_size
            self.save_status(last_ok=now, last_file=path.name, last_size=size, last_error=None)
            log.info('Backup criado: %s (%.1f MB)', path, size / 1024**2)
            return path

    def create(self, folder, now):
        if not folder.is_absolute():
            raise ValueError('Informe o caminho completo da pasta de backup.')
        if not folder.is_dir():
            raise ValueError(f'Pasta de backup indisponível: {folder}. O HD externo está conectado?')
        name = f'{PREFIX}{datetime.fromtimestamp(now, TZ).strftime("%Y%m%d-%H%M%S")}.tar.gz'
        target, partial = folder / name, folder / f'{name}.part'
        with tempfile.TemporaryDirectory(dir=DATA) as work:
            # The SQLite online backup API gives a consistent copy while the cameras keep writing.
            snapshot = Path(work) / 'history.sqlite3'
            source, copy = sqlite3.connect(self.db.path, timeout=15), sqlite3.connect(snapshot)
            try:
                source.backup(copy)
            finally:
                source.close(); copy.close()
            try:
                with tarfile.open(partial, 'w:gz') as archive:
                    archive.add(snapshot, 'history.sqlite3')
                    for path, arcname in ((self.config.path, 'settings.json'), (PEOPLE, 'people'), (DATA / 'alerts', 'alerts')):
                        if path.exists():
                            archive.add(path, arcname)
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
        return target

    def rotate(self, folder, keep):
        for old in self.files(folder)[keep:]:
            old.unlink(missing_ok=True)

    def summary(self):
        settings = self.config.get()
        files = self.files()
        return {**self.status(), 'enabled': settings.backup_enabled, 'directory': settings.backup_dir,
                'files': [{'name': f.name, 'size': f.stat().st_size, 'created': f.stat().st_mtime} for f in files[:5]],
                'count': len(files)}
