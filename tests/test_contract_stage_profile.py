"""Fixed numeric diagnostics never retain source data or cross job contexts."""
import concurrent.futures
import json
import math
import inspect
import threading

import pytest

import developaid_contract_stage_profile as profile


def test_default_off_and_exception_cleanup_never_collect_or_change_values():
    secret = 'PRIVATE_PATH_PROJECT_SHA_CELL_AND_MONEY'
    assert profile.call('rss_projection', lambda value: value, secret) == secret
    assert profile._ACTIVE.get() is None
    with profile.collect() as measured:
        with pytest.raises(ValueError, match='PRIVATE'):
            with profile.measure('archive_parse'):
                raise ValueError(secret)
        profile.byte_count('manifest_bytes', secret)
    value = measured.export()
    assert profile._ACTIVE.get() is None
    assert secret not in json.dumps(value) + repr(measured.__dict__)
    assert value['counters'] == {'manifest_bytes': len(secret.encode())}
    assert value['stages'][0]['calls'] == 1


def test_decorators_preserve_function_metadata_signatures_and_source():
    def original(value: int, *, enabled: bool = False) -> dict:
        """Synthetic producer documentation."""
        return {'value': value, 'enabled': enabled}
    wrapped = profile.stage('archive_parse')(original)
    assert wrapped.__name__ == original.__name__
    assert wrapped.__doc__ == original.__doc__
    assert wrapped.__annotations__ == original.__annotations__
    assert inspect.signature(wrapped) == inspect.signature(original)
    assert inspect.unwrap(wrapped) is original
    assert inspect.getsource(wrapped) == inspect.getsource(original)
    assert wrapped(3, enabled=True) == original(3, enabled=True)


def test_nested_times_are_finite_and_exclusive_and_labels_are_closed(monkeypatch):
    ticks = iter([0., 1., 3., 5.])
    monkeypatch.setattr(profile.time, 'perf_counter', lambda: next(ticks))
    with profile.collect() as measured:
        with profile.measure('contracts_build'):
            with profile.measure('archive_parse'):
                pass
        with pytest.raises(ValueError, match='unknown diagnostic'):
            profile.count('PRIVATE_DYNAMIC_LABEL')
    stages = {s['stage']: s for s in measured.export()['stages']}
    assert stages['archive_parse'] == {'stage': 'archive_parse', 'calls': 1,
                                     'inclusive_ms': 2000., 'exclusive_ms': 2000.}
    assert stages['contracts_build']['inclusive_ms'] == 5000.
    assert stages['contracts_build']['exclusive_ms'] == 3000.
    monkeypatch.setattr(profile.time, 'perf_counter', lambda: float('nan'))
    with profile.collect() as invalid_clock:
        with profile.measure('rss_projection'):
            pass
    assert invalid_clock.export()['stages'][0]['inclusive_ms'] == 0


def test_worst_case_diagnostics_are_bounded_fixed_finite_numbers():
    measured = profile.Profile()
    for name in profile.STAGES:
        measured.stages[name] = [profile.MAX_COUNT, profile.MAX_SECONDS, profile.MAX_SECONDS]
    for name in profile.COUNTERS:
        measured.add(name, profile.MAX_COUNT + 1)
    measured.stages['PRIVATE_UNREGISTERED_LABEL'] = [1, 1., 1.]
    measured.counters['PRIVATE_UNREGISTERED_COUNTER'] = 1
    result = measured.export()
    assert len(json.dumps(result, allow_nan=False).encode()) <= profile.MAX_BYTES
    assert {s['stage'] for s in result['stages']} == profile.STAGES
    assert set(result['counters']) == profile.COUNTERS
    assert 'PRIVATE' not in json.dumps(result)
    assert all(type(v) is int and 0 <= v <= profile.MAX_COUNT for v in result['counters'].values())
    assert all(math.isfinite(s[k]) and s[k] >= 0 for s in result['stages']
               for k in ('inclusive_ms', 'exclusive_ms'))


def test_two_collectors_and_default_thread_are_isolated():
    barrier = threading.Barrier(3)
    def run(value):
        if not value:
            barrier.wait(timeout=10)
            profile.count('ram_hit', 999)
            return profile._ACTIVE.get()
        with profile.collect() as measured:
            barrier.wait(timeout=10)
            with profile.measure('execute_total'):
                profile.count('ram_hit', value)
        assert profile._ACTIVE.get() is None
        return measured.export()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        first, second, disabled = list(pool.map(run, [1, 2, 0]))
    assert first['counters'] == {'ram_hit': 1}
    assert second['counters'] == {'ram_hit': 2}
    assert disabled is None
