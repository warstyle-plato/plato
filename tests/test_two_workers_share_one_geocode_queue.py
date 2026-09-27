"""Очередь к геокодеру общая для двух воркеров, а не у каждого своя.

Прод работает двумя воркерами с раздельной памятью; `threading.Lock` в каждом
свой, и вместе они давали около двух запросов в секунду к Nominatim при
публичном лимите в один. Здесь два настоящих процесса встают в очередь
одновременно — их ходы обязаны разойтись на интервал.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = """
import sys, time
import main_registry
start = float(sys.argv[1])
while time.time() < start:
    time.sleep(0.005)
for _ in range(2):
    main_registry._market_geocode_turn()
    print(f"{time.time():.3f}", flush=True)
"""


def test_two_processes_keep_the_spacing(tmp_path):
    env = dict(os.environ, DATA_DIR=str(tmp_path))
    import time

    start = time.time() + 4.0
    procs = [
        subprocess.Popen([sys.executable, "-c", SCRIPT, str(start)], cwd=ROOT, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for _ in range(2)
    ]
    stamps = []
    for proc in procs:
        out, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0
        stamps += [float(line) for line in out.split()]
    stamps.sort()
    assert len(stamps) == 4
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 1.0, f"воркеры ходят к геокодеру вплотную: {gaps}"
