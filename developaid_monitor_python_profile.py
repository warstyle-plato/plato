"""Opt-in worker-local Python timings; never serialize profiler internals."""
from __future__ import annotations

import cProfile
import json
import math
from pathlib import Path
import re
import sys
import time
import types

PURPOSE = 'monitor-view-python-v1'
MAX_ROWS = 40
MAX_BYTES = 12 * 1024
MAX_COUNT = 2**53 - 1
MAX_SECONDS = 86400.0
_ROOT = Path(__file__).resolve().parent
_FILE = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,70}\.py')
_FUNCTION = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]{0,63}|<(?:lambda|genexpr|listcomp|dictcomp|setcomp|module)>)')


class ProfileMetricsProblem(ValueError):
    pass


def _milliseconds(value):
    if type(value) not in (int, float) or not 0 <= value <= MAX_SECONDS or not math.isfinite(value):
        raise ProfileMetricsProblem('invalid profile metrics')
    return round(value*1000, 3)


def _count(value):
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise ProfileMetricsProblem('invalid profile metrics')
    return value


def _location(code):
    if not isinstance(code, types.CodeType) or not _FUNCTION.fullmatch(code.co_name):
        return None
    filename = code.co_filename
    if filename.startswith('<'):
        return None
    path = Path(filename)
    if not path.is_absolute():
        path = _ROOT/path
    try:
        path = path.resolve()
        relative = path.relative_to(_ROOT)
        real_file = path.is_file()
    except (OSError, ValueError):
        return None
    # Application Python only; tests, dependencies and generated code stay out.
    if (relative.parent not in {Path('.'), Path('engine')} or not real_file or not _FILE.fullmatch(path.name)
            or not 1 <= code.co_firstlineno <= 10_000_000):
        return None
    return path.name, code.co_name, code.co_firstlineno


def _export(entries, elapsed):
    try:
        return _export_valid(entries, elapsed)
    except ProfileMetricsProblem:
        return {'purpose': PURPOSE, 'unavailable': 'invalid_profile_metrics'}


def _export_valid(entries, elapsed):
    elapsed_ms = _milliseconds(elapsed)
    rows = []
    for entry in entries:
        location = _location(entry.code)
        if location is None:
            continue
        filename, function, line = location
        rows.append({'file': filename, 'function': function, 'line': line,
                     'calls': _count(entry.callcount),
                     'recursive_calls': _count(entry.reccallcount),
                     'self_ms': _milliseconds(entry.inlinetime),
                     'cumulative_ms': _milliseconds(entry.totaltime)})
    rows.sort(key=lambda row: (-row['cumulative_ms'], -row['self_ms'], row['file'], row['function'], row['line']))
    result = {'purpose': PURPOSE, 'rows': rows[:MAX_ROWS], 'limit': MAX_ROWS,
              'truncated': len(rows) > MAX_ROWS, 'ordering': 'cumulative_desc',
              'worker_elapsed_ms': elapsed_ms, 'includes_profiler_overhead': True,
              'unmeasured': ['queue', 'child_threads', 'profile_export', 'job_serialization', 'job_gzip', 'job_storage', 'transfer']}
    while len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
        result['rows'].pop()
        result['truncated'] = True
    return result


def run(function, *args, **kwargs):
    """Profile exactly one existing calculation in its current worker thread."""
    if sys.getprofile() is not None:
        # Do not replace an unrelated pre-existing thread profiler.
        return function(*args, **kwargs), {'purpose': PURPOSE, 'unavailable': 'profile_already_active'}
    profiler = cProfile.Profile()
    started = time.perf_counter()
    try:
        result = profiler.runcall(function, *args, **kwargs)
        elapsed = time.perf_counter()-started
        return result, _export(profiler.getstats(), elapsed)
    finally:
        profiler.disable()
        profiler.clear()
