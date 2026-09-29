import shutil
import subprocess
import time
import uuid

import cv2

from .config import CLIPS


class Recorder:
    def __init__(self, db, directory=CLIPS):
        self.db = db
        self.directory = directory
        self.writer = None
        self.clip_id = None
        self.frames = 0
        self.last_frame = None
        self.size = None
        self.start_time = 0

    def start(self, event_id, frame, timestamp, fps):
        if shutil.disk_usage(self.directory).free < 512 * 1024 * 1024:
            raise RuntimeError('Menos de 512 MB livres. Libere espaço para gravar.')
        self.clip_id = uuid.uuid4().hex
        self.fps = fps
        self.start_time = timestamp
        self.frames = 0
        height, width = frame.shape[:2]
        self.size = (width - width % 2, height - height % 2)
        path = self.directory / f'{self.clip_id}.avi'
        self.writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, self.size)
        if not self.writer.isOpened():
            self.writer = None
            raise RuntimeError('Não foi possível abrir o arquivo de gravação.')
        self.db.execute('INSERT INTO clips(id,event_id,started) VALUES(?,?,?)', (self.clip_id, event_id, timestamp))
        cv2.imwrite(str(self.directory / f'{self.clip_id}.jpg'), frame)
        self.write(frame, timestamp)

    def write(self, frame, timestamp):
        if self.writer is None:
            return
        frame = cv2.resize(frame, self.size)
        target = max(1, round((timestamp - self.start_time) * self.fps) + 1)
        # Repeat the last frame between inferences, preserving actual elapsed time.
        while self.frames < target - 1:
            self.writer.write(self.last_frame if self.last_frame is not None else frame)
            self.frames += 1
        if self.frames < target:
            self.writer.write(frame)
            self.frames += 1
        self.last_frame = frame

    def finish(self, timestamp):
        if self.writer is None:
            return
        self.writer.release()
        self.writer = None
        self.db.execute("UPDATE clips SET ended=?,duration=?,state='processing' WHERE id=?", (timestamp, self.frames / self.fps, self.clip_id))
        self.clip_id = None
        self.last_frame = None


def transcode(db, row, directory=CLIPS):
    clip_id = row['id']
    source = directory / f'{clip_id}.avi'
    output = directory / f'{clip_id}.mp4'
    temporary = directory / f'{clip_id}.tmp.mp4'
    try:
        if not source.exists():
            raise RuntimeError('Gravação temporária não encontrada após interrupção.')
        result = subprocess.run([
            'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(source), '-an', '-c:v', 'libx264', '-preset', 'veryfast',
            '-threads', '2', '-crf', '23', '-maxrate', '4000k', '-bufsize', '8000k',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(temporary),
        ], capture_output=True, timeout=180)
        if result.returncode or not temporary.exists() or temporary.stat().st_size < 100:
            raise RuntimeError('Falha ao converter o vídeo. Verifique FFmpeg e espaço em disco.')
        temporary.replace(output)
        duration = row['duration']
        if not duration:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(output)], capture_output=True, text=True, timeout=10)
            duration = float(probe.stdout.strip())
        db.execute("UPDATE clips SET state='ready',error=NULL,duration=?,ended=COALESCE(ended,started+?) WHERE id=?", (duration, duration, clip_id))
        source.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        db.execute("UPDATE clips SET state='failed',error=? WHERE id=?", (str(exc)[:250], clip_id))
        temporary.unlink(missing_ok=True)


def cleanup(db, retention_days, directory=CLIPS):
    cutoff = time.time() - retention_days * 86400
    # Preserve active visits, even when they span the retention cutoff.
    old = db.rows('''SELECT clips.id FROM clips JOIN events ON events.id=clips.event_id
        WHERE events.ended IS NOT NULL AND events.analysis_state!='running' AND clips.started<?
        AND clips.state IN ('ready','failed') AND clips.delivery!='sending' ''', (cutoff,))
    for row in old:
        for extension in ('mp4', 'avi', 'jpg', 'tmp.mp4', 'analyzed.mp4', 'analysis.avi', 'analysis.tmp.mp4'):
            (directory / f"{row['id']}.{extension}").unlink(missing_ok=True)
        db.execute("UPDATE clips SET state='expired',error=NULL WHERE id=?", (row['id'],))
