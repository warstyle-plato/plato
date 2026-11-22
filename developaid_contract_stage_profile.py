"""Opt-in, bounded numeric stage diagnostics for one Contracts worker.

No function arguments, source identifiers, exception text or business values
are retained. Default-off calls only consult a ContextVar. Nested durations
include exclusive time so history rebuilds are not added twice.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import json
import math
import time

PURPOSE = 'contract-stages-v1'
MAX_BYTES = 8192
MAX_COUNT = 2**53 - 1
MAX_SECONDS = 86400.0
STAGES = frozenset({
    'execute_total', 'contracts_build', 'register_build', 'archive_composition',
    'archive_select', 'manifest_list', 'snapshot_read', 'manifest_read', 'manifest_decode',
    'zip_read', 'zip_verify', 'source_cache', 'cache_lock_wait', 'cache_decode',
    'cache_encode', 'disk_read', 'disk_write', 'archive_parse', 'workbook_parse',
    'rss_projection', 'physical_projection', 'detail_history', 'history_enrich',
    'daily_enrich', 'daily_scope', 'card_controls', 'card_acts', 'card_listing',
    'jsonable_encoder',
})
COUNTERS = frozenset({
    'manifest_bytes', 'zip_bytes', 'cache_packed_bytes', 'cache_decoded_bytes',
    'ram_hit', 'ram_miss', 'ram_corrupt', 'ram_eviction', 'ram_hit_after_wait',
    'disk_hit', 'disk_miss', 'disk_corrupt', 'disk_unavailable', 'disk_eviction',
    'not_cached_decoded_limit', 'not_cached_compressed_limit',
})
_ACTIVE = contextvars.ContextVar('contract_stage_profile', default=None)


def _finite(value, maximum):
    return min(maximum, max(0.0, value)) if math.isfinite(value) else 0.0


class Profile:
    def __init__(self):
        self.stages = {}
        self.counters = {}
        self.stack = []

    @contextlib.contextmanager
    def measure(self, label):
        if label not in STAGES:
            raise ValueError('unknown diagnostic stage')
        frame = [time.perf_counter(), 0.0]
        self.stack.append(frame)
        try:
            yield
        finally:
            elapsed = _finite(time.perf_counter() - frame[0], MAX_SECONDS)
            self.stack.pop()
            if self.stack:
                self.stack[-1][1] += elapsed
            value = self.stages.setdefault(label, [0, 0.0, 0.0])
            value[0] = min(MAX_COUNT, value[0] + 1)
            value[1] = min(MAX_SECONDS, value[1] + elapsed)
            value[2] = min(MAX_SECONDS, value[2] + max(0.0, elapsed - frame[1]))

    def add(self, label, value):
        if label not in COUNTERS:
            raise ValueError('unknown diagnostic counter')
        if type(value) is not int or value < 0:
            raise ValueError('invalid diagnostic counter')
        self.counters[label] = min(MAX_COUNT, self.counters.get(label, 0) + value)

    def export(self):
        result = {'purpose': PURPOSE, 'stages': [
            {'stage': name, 'calls': value[0], 'inclusive_ms': round(value[1] * 1000, 3),
             'exclusive_ms': round(value[2] * 1000, 3)}
            for name in sorted(STAGES) if (value := self.stages.get(name)) is not None],
            'counters': {name: self.counters[name] for name in sorted(COUNTERS) if name in self.counters},
            'unmeasured': ['job_serialization', 'job_gzip', 'job_storage', 'transfer']}
        if len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
            return {'purpose': PURPOSE, 'unavailable': 'diagnostic_size_limit'}
        return result


@contextlib.contextmanager
def collect():
    profile = Profile()
    token = _ACTIVE.set(profile)
    try:
        yield profile
    finally:
        _ACTIVE.reset(token)


def call(label, function, *args, **kwargs):
    profile = _ACTIVE.get()
    if profile is None:
        return function(*args, **kwargs)
    with profile.measure(label):
        return function(*args, **kwargs)


def stage(label):
    if label not in STAGES:
        raise ValueError('unknown diagnostic stage')
    def decorate(function):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            return call(label, function, *args, **kwargs)
        return measured
    return decorate


@contextlib.contextmanager
def measure(label):
    profile = _ACTIVE.get()
    if profile is None:
        yield
    else:
        with profile.measure(label):
            yield


def count(label, value=1):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.add(label, value)


def byte_count(label, value):
    profile = _ACTIVE.get()
    if profile is not None:
        profile.add(label, len(value.encode('utf-8')) if isinstance(value, str) else len(value))
