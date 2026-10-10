import tempfile
import unittest
from pathlib import Path

from app.resources import Monitor, Reader


def tree(root, cpu, jiffies=0):
    proc, sys = Path(root) / 'proc', Path(root) / 'sys'
    for folder in (proc / '42', proc / '7', sys / 'class/thermal/thermal_zone0', sys / 'class/thermal/thermal_zone1', sys / 'class/power_supply/BAT0'):
        folder.mkdir(parents=True, exist_ok=True)
    (proc / 'stat').write_text(f'cpu {cpu[0]} 0 {cpu[1]} {cpu[2]} 0 0 0 0 0 0\ncpu0 1 1 1 1\n')
    (proc / 'meminfo').write_text('MemTotal: 8000000 kB\nMemFree: 1000000 kB\nMemAvailable: 2000000 kB\nSwapTotal: 4000000 kB\nSwapFree: 3000000 kB\n')
    (proc / '42/stat').write_text(f'42 (python (app)) S 1 42 42 0 -1 0 0 0 0 0 {jiffies} 0 0 0 20 0 5 0 100 1000 1000 0\n')
    (proc / '7/stat').write_text('7 (idle) S 1 7 7 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 100 1000 10 0\n')
    (sys / 'class/thermal/thermal_zone0/temp').write_text('61000\n')
    (sys / 'class/thermal/thermal_zone1/temp').write_text('73500\n')
    (sys / 'class/power_supply/BAT0/capacity').write_text('88\n')
    (sys / 'class/power_supply/BAT0/status').write_text('Charging\n')
    return proc, sys


class ResourceTests(unittest.TestCase):
    def test_reader_parses_counters(self):
        with tempfile.TemporaryDirectory() as root:
            reader = Reader(*tree(root, (100, 50, 850)))
            self.assertEqual(reader.cpu_times(), (150, 1000))
            memory = reader.memory()
            self.assertEqual((memory['mem_total'], memory['mem_used'], memory['swap_used']), (8000000 * 1024, 6000000 * 1024, 1000000 * 1024))
            self.assertEqual(reader.temperature(), 73.5)
            self.assertEqual(reader.battery(), {'percent': 88, 'status': 'Charging'})
            self.assertEqual(reader.processes()[42][:3], ('python (app)', 1, 0))

    def test_sampler_computes_cpu_and_names_the_busiest_process(self):
        with tempfile.TemporaryDirectory() as root:
            reader = Reader(*tree(root, (100, 50, 850), jiffies=0))
            reader.tick = 100
            clock = iter([1000.0, 1005.0]).__next__
            monitor = Monitor(reader, clock=clock, own_pid=42)
            monitor.gpu_at = 10 ** 12   # No nvidia-smi in tests.
            first = monitor.sample()
            self.assertNotIn('cpu', first)
            tree(root, (300, 50, 1150), jiffies=250)    # 200 busy of 500 total jiffies; 2.5 s of CPU in 5 s.
            second = monitor.sample()
            self.assertEqual(second['cpu'], 40.0)
            self.assertEqual(second['top'][0]['name'], 'Casa Presente (app)')
            self.assertEqual(second['top'][0]['cpu'], 50.0)

    def test_history_is_trimmed_by_period(self):
        with tempfile.TemporaryDirectory() as root:
            reader = Reader(*tree(root, (100, 50, 850)))
            times = iter([100.0, 4000.0, 4001.0])
            monitor = Monitor(reader, clock=lambda: next(times), own_pid=42)
            monitor.gpu_at = 10 ** 12
            monitor.sample()
            monitor.sample()
            snapshot = monitor.snapshot(10)   # now = 4001: only the second point is within 10 minutes.
            self.assertEqual(len(snapshot['history']), 1)
            self.assertEqual(snapshot['history'][0]['mem'], 75.0)


if __name__ == '__main__':
    unittest.main()
