"""Server resource monitor: CPU, memory, temperature, battery, GPU and the busiest processes.

A background sampler reads /proc and /sys every few seconds (no extra dependency) and keeps the
last hour in memory, so the dashboard can chart it. Linux only; anything missing is just omitted.
"""
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .config import DATA

SAMPLE_SECONDS = 5
KEEP = 3600 // SAMPLE_SECONDS
TOP = 6
LABELS = {'ffmpeg': 'FFmpeg (gravação/vídeo)', 'mediamtx': 'MediaMTX (câmera)', 'tailscaled': 'Tailscale'}


class Reader:
    """Reads the kernel's counters; the roots can be swapped for tests."""

    def __init__(self, proc='/proc', sys='/sys'):
        self.proc, self.sys = Path(proc), Path(sys)
        self.tick = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100

    def cpu_times(self):
        """(busy, total) jiffies of the whole machine."""
        fields = [int(v) for v in (self.proc / 'stat').read_text().splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return sum(fields) - idle, sum(fields)

    def memory(self):
        values = {}
        for line in (self.proc / 'meminfo').read_text().splitlines():
            key, _, rest = line.partition(':')
            values[key] = int(rest.split()[0]) * 1024
        total = values['MemTotal']
        used = total - values.get('MemAvailable', values.get('MemFree', 0))
        swap_total = values.get('SwapTotal', 0)
        return {'mem_total': total, 'mem_used': used, 'swap_total': swap_total, 'swap_used': swap_total - values.get('SwapFree', 0)}

    def temperature(self):
        """Hottest sensor in °C (CPU package/cores on most machines)."""
        found = []
        for pattern in ('class/thermal/thermal_zone*/temp', 'class/hwmon/hwmon*/temp*_input'):
            for path in self.sys.glob(pattern):
                try:
                    value = int(path.read_text()) / 1000
                except (OSError, ValueError):
                    continue
                if 0 < value < 150:
                    found.append(value)
        return round(max(found), 1) if found else None

    def battery(self):
        for path in sorted(self.sys.glob('class/power_supply/BAT*')):
            try:
                percent = int((path / 'capacity').read_text())
                status = (path / 'status').read_text().strip()
            except (OSError, ValueError):
                continue
            return {'percent': percent, 'status': status}
        return None

    def processes(self):
        """{pid: (name, ppid, jiffies, rss_bytes)} for every process we may read."""
        found = {}
        page = os.sysconf('SC_PAGE_SIZE') if hasattr(os, 'sysconf') else 4096
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                text = (entry / 'stat').read_text()
            except OSError:
                continue
            head, _, tail = text.rpartition(')')
            fields = tail.split()
            try:
                found[int(entry.name)] = (head.partition('(')[2], int(fields[1]), int(fields[11]) + int(fields[12]), int(fields[21]) * page)
            except (IndexError, ValueError):
                continue
        return found


def gpu_reading():
    """NVIDIA GPU use through nvidia-smi, or None."""
    if not shutil.which('nvidia-smi'):
        return None
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw',
                              '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3).stdout.splitlines()[0]
        name, util, used, total, temp, power = [v.strip() for v in out.split(',')]
        return {'name': name, 'util': float(util), 'mem_used': float(used) * 1048576, 'mem_total': float(total) * 1048576,
                'temp': float(temp), 'power': float(power) if power.replace('.', '').isdigit() else None}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class Monitor:
    def __init__(self, reader=None, clock=time.time, own_pid=None):
        self.reader = reader or Reader()
        self.clock = clock
        self.own_pid = own_pid or os.getpid()
        self.history = deque(maxlen=KEEP)
        self.lock = threading.Lock()
        self.previous = None
        self.gpu = None
        self.gpu_at = 0
        self.stop_event = threading.Event()
        self.thread = None

    def label(self, pid, name, processes):
        if pid == self.own_pid:
            return 'Casa Presente (app)'
        if processes.get(pid, ('', 0))[1] == self.own_pid and name == 'ffmpeg':
            return LABELS['ffmpeg']
        if name in LABELS:
            return LABELS[name]
        if name.startswith('node'):
            try:
                if 'whatsapp' in (self.reader.proc / str(pid) / 'cmdline').read_text():
                    return 'WhatsApp'
            except OSError:
                pass
        return name

    def sample(self):
        """One reading; CPU figures need the previous one, so the very first has none."""
        now = self.clock()
        busy, total = self.reader.cpu_times()
        processes = self.reader.processes()
        point = {'t': round(now, 1), **self.reader.memory(), 'temp': self.reader.temperature(),
                 'load': round(os.getloadavg()[0], 2) if hasattr(os, 'getloadavg') else None}
        battery = self.reader.battery()
        if battery:
            point['battery'] = battery
        if now - self.gpu_at >= 2 * SAMPLE_SECONDS:
            self.gpu, self.gpu_at = gpu_reading(), now
        if self.gpu:
            point['gpu'] = self.gpu
        if self.previous:
            before_busy, before_total, before_time, before = self.previous
            elapsed = max(now - before_time, 0.001)
            point['cpu'] = round(100 * (busy - before_busy) / max(total - before_total, 1), 1)
            rows = {}
            for pid, (name, _, jiffies, rss) in processes.items():
                if pid in before:
                    use = 100 * (jiffies - before[pid]) / self.reader.tick / elapsed
                    if use >= 0.5:
                        rows[pid] = (name, use, rss)
            top = sorted(rows.items(), key=lambda kv: -kv[1][1])[:TOP]
            point['top'] = [{'name': self.label(pid, name, processes), 'cpu': round(use, 1), 'rss': rss} for pid, (name, use, rss) in top]
        self.previous = (busy, total, now, {pid: v[2] for pid, v in processes.items()})
        with self.lock:
            self.history.append(point)
        return point

    def snapshot(self, minutes=30):
        with self.lock:
            points = list(self.history)
        cutoff = self.clock() - minutes * 60
        recent = [p for p in points if p['t'] >= cutoff]
        disk = shutil.disk_usage(DATA)
        return {'cores': os.cpu_count(), 'sample_seconds': SAMPLE_SECONDS, 'disk_free': disk.free, 'disk_total': disk.total,
                'now': points[-1] if points else None,
                # The chart only needs the three headline series.
                'history': [{k: p.get(k) for k in ('t', 'cpu', 'temp', 'load')} | {'mem': round(100 * p['mem_used'] / p['mem_total'], 1)}
                            | ({'gpu': p['gpu']['util']} if 'gpu' in p else {}) for p in recent]}

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.sample()
            except Exception:
                pass
            self.stop_event.wait(SAMPLE_SECONDS)

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name='resources')
        self.thread.start()

    def stop(self):
        self.stop_event.set()


monitor = Monitor()
