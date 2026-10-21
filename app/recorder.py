import logging
import queue
import shutil
import signal
import os
import subprocess
import threading
import time
import uuid

import cv2

from .config import CLIPS

log = logging.getLogger(__name__)


class AudioTap:
    """Records the camera computer's microphone (MediaMTX "mic" path) next to a clip.

    Packets keep wall-clock timestamps (-copyts), so the mux step can line the sound up with the video
    even though the microphone takes a moment to connect. Failing to get sound never loses the video.
    """

    def __init__(self, url, path):
        self.url, self.path, self.process = url, path, None

    def start(self):
        try:
            self.process = subprocess.Popen([
                'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-rtsp_transport', 'tcp', '-use_wallclock_as_timestamps', '1',
                '-i', self.url, '-vn', '-ac', '1', '-c:a', 'aac', '-b:a', '64k', '-copyts', '-f', 'matroska', str(self.path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            self.process = None

    def stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            process.send_signal(signal.SIGINT)   # Lets ffmpeg write the end of the file.
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def audio_url(source):
    """The camera computer's microphone stream for an RTSP source, or the local MediaMTX for a USB camera."""
    from urllib.parse import urlsplit
    from .sources import local_device
    if local_device(source):
        return 'rtsp://127.0.0.1:8554/mic'
    parts = urlsplit(source)
    if parts.scheme in ('rtsp', 'rtsps') and parts.hostname:
        return parts._replace(path='/mic', query='', fragment='').geturl()
    return None


class Recorder:
    """Writes a clip at a constant frame rate on its own thread.

    The camera loop only queues frames. Gaps (slower analysis) are filled by repeating the last
    frame, and each repeat is a full MJPEG encode: done inline, those repeats slowed the loop,
    which created more gaps, until the live view dropped to ~10 fps whenever someone appeared.
    """
    QUEUE = 4  # Frames waiting to be written; when full the oldest is dropped (repeats keep the timing).

    def __init__(self, db, directory=CLIPS):
        self.db = db
        self.directory = directory
        self.writer = None
        self.clip_id = None
        self.frames = 0
        self.last_frame = None
        self.size = None
        self.start_time = 0
        self.queue = None
        self.thread = None
        self.audio_url = None   # Set by the camera loop when sound should be recorded with the clips.
        self.audio = None

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
        if self.audio_url:
            self.audio = AudioTap(self.audio_url, self.directory / f'{self.clip_id}.mka')
            self.audio.start()
        self.queue = queue.Queue(self.QUEUE)
        self.thread = threading.Thread(target=self.run, args=(self.writer, self.queue), daemon=True, name='recorder')
        self.thread.start()
        self.write(frame, timestamp)

    def write(self, frame, timestamp):
        if self.writer is None:
            return
        while True:
            try:
                self.queue.put_nowait((frame, timestamp))
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass

    def run(self, writer, frames):
        failed = False
        while (item := frames.get()) is not None:
            if failed:
                continue  # Keep draining so finish() never waits on a full queue.
            try:
                frame, timestamp = item
                if (frame.shape[1], frame.shape[0]) != self.size:
                    frame = cv2.resize(frame, self.size)
                target = max(1, round((timestamp - self.start_time) * self.fps) + 1)
                # Repeat the last frame between inferences, preserving actual elapsed time.
                while self.frames < target - 1:
                    writer.write(self.last_frame if self.last_frame is not None else frame)
                    self.frames += 1
                if self.frames < target:
                    writer.write(frame)
                    self.frames += 1
                self.last_frame = frame
            except Exception:
                failed = True
                log.exception('Falha ao gravar o vídeo %s', self.clip_id)

    def finish(self, timestamp):
        if self.writer is None:
            return
        self.queue.put(None)  # After the frames already queued.
        self.thread.join()
        self.writer.release()
        self.writer = None
        if self.audio:
            self.audio.stop()
            self.audio = None
        self.db.execute("UPDATE clips SET ended=?,duration=?,state='processing' WHERE id=?", (timestamp, self.frames / self.fps, self.clip_id))
        self.clip_id = None
        self.last_frame = None
        self.queue = self.thread = None


def audio_offset(sound, video_start):
    """Seconds the sound starts after the video (wall-clock timestamps), or None when there is no usable sound."""
    try:
        if not sound.is_file() or sound.stat().st_size < 2000:
            return None
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=start_time', '-of', 'default=nw=1:nk=1', str(sound)],
                               capture_output=True, text=True, timeout=10)
        start = float(probe.stdout.strip().splitlines()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
    offset = start - video_start if start > 1e9 else 0.0
    return min(max(offset, 0.0), 30.0)


def lower_priority():
    """Runs in the child before ffmpeg starts: converting a clip must never slow down the detection."""
    try:
        os.nice(19)
    except OSError:
        pass


def transcode(db, row, directory=CLIPS):
    clip_id = row['id']
    source = directory / f'{clip_id}.avi'
    output = directory / f'{clip_id}.mp4'
    temporary = directory / f'{clip_id}.tmp.mp4'
    try:
        if not source.exists():
            raise RuntimeError('Gravação temporária não encontrada após interrupção.')
        sound = directory / f'{clip_id}.mka'
        offset = audio_offset(sound, row['started'])
        command = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source)]
        if offset is not None:
            command += ['-itsoffset', f'{offset:.3f}', '-i', str(sound), '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '64k']
        else:
            command += ['-an']
        command += ['-c:v', 'libx264', '-preset', 'veryfast', '-threads', '2', '-crf', '23', '-maxrate', '4000k', '-bufsize', '8000k',
                    '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(temporary)]
        result = subprocess.run(command, capture_output=True, timeout=600, preexec_fn=lower_priority)
        if (result.returncode or not temporary.exists()) and offset is not None:
            # The sound file was unusable: keep the video without it.
            result = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source), '-an', '-c:v', 'libx264',
                                     '-preset', 'veryfast', '-threads', '2', '-crf', '23', '-maxrate', '4000k', '-bufsize', '8000k',
                                     '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(temporary)], capture_output=True, timeout=600, preexec_fn=lower_priority)
        if result.returncode or not temporary.exists() or temporary.stat().st_size < 100:
            raise RuntimeError('Falha ao converter o vídeo. Verifique FFmpeg e espaço em disco.')
        temporary.replace(output)
        duration = row['duration']
        if not duration:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(output)], capture_output=True, text=True, timeout=10)
            duration = float(probe.stdout.strip())
        db.execute("UPDATE clips SET state='ready',error=NULL,duration=?,ended=COALESCE(ended,started+?) WHERE id=?", (duration, duration, clip_id))
        source.unlink(missing_ok=True)
        sound.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        db.execute("UPDATE clips SET state='failed',error=? WHERE id=?", (str(exc)[:250], clip_id))
        temporary.unlink(missing_ok=True)


CLIP_FILES = ('mp4', 'avi', 'mka', 'jpg', 'tmp.mp4', 'analyzed.mp4', 'analysis.avi', 'analysis.tmp.mp4')
# Only finished clips of closed, idle events may be removed.
REMOVABLE = """SELECT clips.id FROM clips JOIN events ON events.id=clips.event_id
    WHERE events.ended IS NOT NULL AND events.analysis_state!='running'
    AND clips.state IN ('ready','failed') AND clips.delivery!='sending'"""


def free_space(directory=CLIPS):
    return shutil.disk_usage(directory).free / 1024**3


def expire(db, clip_id, directory=CLIPS):
    for extension in CLIP_FILES:
        (directory / f'{clip_id}.{extension}').unlink(missing_ok=True)
    db.execute("UPDATE clips SET state='expired',error=NULL WHERE id=?", (clip_id,))


def cleanup(db, retention_days, directory=CLIPS, min_free_gb=0):
    cutoff = time.time() - retention_days * 86400
    # Preserve active visits, even when they span the retention cutoff.
    for row in db.rows(REMOVABLE + ' AND clips.started<?', (cutoff,)):
        expire(db, row['id'], directory)
    # Photos of records without video (restricted mode) follow the same retention.
    for row in db.rows('''SELECT p.id FROM event_photos p JOIN events e ON e.id=p.event_id
            WHERE e.ended IS NOT NULL AND p.created<?''', (cutoff,)):
        (directory / f"{row['id']}.jpg").unlink(missing_ok=True)
        db.execute('DELETE FROM event_photos WHERE id=?', (row['id'],))
    # A full disk stops every recording: drop the oldest videos before that happens.
    while min_free_gb and free_space(directory) < min_free_gb:
        oldest = db.rows(REMOVABLE + ' ORDER BY clips.started LIMIT 20')
        if not oldest:
            log.warning('Pouco espaço em disco e nenhum vídeo antigo para remover.')
            return
        log.warning('Pouco espaço em disco: removendo %d vídeo(s) mais antigo(s).', len(oldest))
        for row in oldest:
            expire(db, row['id'], directory)
