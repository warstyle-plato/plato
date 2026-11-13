"""Prospective audit cannot run a model or rewrite the inputs it observes."""
import copy
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

import developaid_cached_source_audit as audit
import developaid_krt_weekly_trace as trace
from auction_search.krt_ranking import KrtRanking

PERIOD = 1794096000
RUNTIME = {'commit': 'a'*40, 'version': '0.29.26'}
PROJECT = {'slug': 'running', 'name': 'PRIVATE-NAME', 'status': 'В реализации',
           'last_known_status_kind': 'running'}


def begin(root, *args, **kwargs):
    kwargs.setdefault('source_before', trace.source_revision(root))
    return trace.begin(root, *args, **kwargs)


def put(root, name, value):
    path = root/name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def stored(tmp_path):
    root = tmp_path/'krt'
    root.mkdir()
    put(root, 'catalogue.json', {'schema_version': 3, 'retrieved_at': int(time.time()),
                               'complete': True, 'projects': [PROJECT]})
    put(root, 'decisions.json', {'schema_version': 3, 'retrieved_at': int(time.time()),
                               'complete': True, 'all': []})
    put(root, 'schedule.json', {'period': PERIOD, 'attempted': []})
    put(root, 'ranking.json', {'schema_version': 1, 'rows': [{
        **PROJECT, 'computed_at': 100, 'investment_rating': {'score': 71},
        'investment_rating_computed_at': 101, 'entry_capacity_mln': 999}]})
    put(root, 'reports/running.json', {'schema_version': 1, 'slug': 'running',
        'computed_at': 100, 'project': PROJECT,
        'screening': {'model_inputs': {'secret': 'PRIVATE-MODEL'}, 'metrics': {'money': 999}}})
    return root


def test_header_and_excluded_before_after_are_metadata_only_and_preserve_inputs(stored):
    before = {p.relative_to(stored): p.read_bytes() for p in stored.rglob('*.json')}
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    old = trace.observe(stored, 'running')
    trace.visit(stored, PERIOD, PROJECT, old, trace.observe(stored, 'running'))
    trace.end(stored, PERIOD, True)
    result = trace.read(stored, PERIOD)
    assert result['header']['period'] == PERIOD and result['completed'] is True
    assert result['gaps'] == [] and len(result['visits']) == 1
    visit, = result['visits'].values()
    assert visit['unchanged'] is True and visit['before']['model_at'] == 100
    assert visit['before']['rating_at'] == 101
    assert visit['before']['report_sha256'] == hashlib.sha256(before[Path('reports/running.json')]).hexdigest()
    assert all(p.read_bytes() == raw for relative, raw in before.items() for p in [stored/relative])
    text = json.dumps(result, ensure_ascii=False)
    assert all(token not in text for token in ['PRIVATE-NAME', 'PRIVATE-MODEL', 'money', 'entry_capacity_mln'])
    assert (stored/'.weekly-trace'/f'{PERIOD}.json').stat().st_mode & 0o777 == 0o600


def test_resume_keeps_the_initial_header_and_names_changed_inputs(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    initial = trace.read(stored, PERIOD)
    trace.end(stored, PERIOD, False)
    changed = {**PROJECT, 'status': 'Планируемый'}
    begin(stored, PERIOD, [changed], {**RUNTIME, 'commit': 'b'*40})
    resumed = trace.read(stored, PERIOD)
    assert resumed['header'] == initial['header']
    assert resumed['header_sha256'] == initial['header_sha256']
    assert 'input_revision_changed' in resumed['gaps'] and 'interrupted' in resumed['gaps']


def test_before_after_missing_or_changed_cannot_claim_preservation(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    before = trace.observe(stored, 'running')
    put(stored, 'reports/running.json', {'schema_version': 1, 'slug': 'running', 'computed_at': 200})
    trace.visit(stored, PERIOD, PROJECT, before, trace.observe(stored, 'running'))
    result = trace.read(stored, PERIOD)
    assert next(iter(result['visits'].values()))['unchanged'] is False
    assert 'financial_state_changed_or_concurrent_writer' in result['gaps']
    trace.visit(stored, PERIOD, PROJECT, {'state': 'unavailable'}, {'state': 'unavailable'})
    assert 'observation_missing' in trace.read(stored, PERIOD)['gaps']


def test_known_absence_is_not_zero_and_market_only_fields_do_not_change_finance_hash(stored):
    for path in [stored/'ranking.json', stored/'reports/running.json']:
        path.unlink()
    before = trace.observe(stored, 'running', ('market_computed_at',))
    assert before['model_at'] is None and before['report_sha256'] is None
    put(stored, 'ranking.json', {'schema_version': 1, 'rows': [
        {'slug': 'running', 'market_computed_at': 333}]})
    after = trace.observe(stored, 'running', ('market_computed_at',))
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    trace.visit(stored, PERIOD, PROJECT, before, after)
    assert next(iter(trace.read(stored, PERIOD)['visits'].values()))['unchanged'] is True


def test_stale_missing_sources_and_missing_visits_are_explicit_gaps(stored):
    put(stored, 'catalogue.json', {'retrieved_at': 100, 'complete': True, 'projects': [PROJECT]})
    (stored/'decisions.json').unlink()
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    trace.end(stored, PERIOD, True)
    assert {'source_stale', 'source_missing', 'excluded_visits_missing'} <= set(trace.read(stored, PERIOD)['gaps'])


def test_limit_and_symlink_are_rejected_without_touching_other_files(stored, tmp_path, monkeypatch):
    monkeypatch.setattr(trace, 'MAX_SITES', 1)
    with pytest.raises(trace.TraceProblem, match='trace_limit'):
        begin(stored, PERIOD, [PROJECT, PROJECT], RUNTIME)
    target = tmp_path/'outside'
    target.mkdir()
    (stored/'.weekly-trace').symlink_to(target, target_is_directory=True)
    with pytest.raises(trace.TraceProblem):
        begin(stored, PERIOD, [PROJECT], RUNTIME)
    assert list(target.iterdir()) == []


def test_different_report_identity_is_not_used_as_this_sites_before_state(stored):
    put(stored, 'reports/running.json', {'schema_version': 1, 'slug': 'another', 'computed_at': 100})
    with pytest.raises(trace.TraceProblem, match='source_identity_unknown'):
        trace.observe(stored, 'running')


def test_native_schedule_does_not_fail_or_change_the_model_path_when_audit_fails(stored, monkeypatch):
    ranking = KrtRanking(stored.parent)
    monkeypatch.setattr(ranking, 'last_scheduled_moment', lambda *a: PERIOD)
    monkeypatch.setattr(trace, 'begin', lambda *a, **kw: (_ for _ in ()).throw(trace.TraceProblem('trace_limit')))
    selected = ranking._schedule_begin([PROJECT])
    assert selected == [PROJECT]
    state = json.loads((stored/'schedule.json').read_text())
    assert state['total'] == 1
    result = audit.capture_krt(stored, runtime=RUNTIME)
    assert 'prospective_trace_missing_or_unavailable' in result['gaps']


def test_cached_metadata_reads_only_a_fixed_period_trace_and_never_claims_old_sunday_pass(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    old = trace.observe(stored, 'running')
    trace.visit(stored, PERIOD, PROJECT, old, old)
    trace.end(stored, PERIOD, True)
    before = {p:p.read_bytes() for p in stored.rglob('*') if p.is_file()}
    result = audit.capture_krt(stored, runtime=RUNTIME,
        process={'catalogue_refreshing': False, 'decisions_refreshing': False})
    assert result['prospective_weekly_trace']['header']['period'] == PERIOD
    assert result['production_acceptance'] is False and result['evidence_complete'] is False
    assert 'sunday_input_revision_not_proven' in result['gaps']
    assert all(path.read_bytes() == raw for path,raw in before.items())


def _concurrent_visit(root, project):
    state = trace.observe(root, project['slug'])
    try:
        trace.visit(root, PERIOD, project, state, state)
    except trace.TraceProblem:
        # Contention may leave incomplete evidence; it must not wait on or
        # change the existing weekly calculation.
        pass


def test_two_processes_cannot_silently_claim_missing_visits_complete(stored):
    other = {**PROJECT, 'slug': 'other'}
    begin(stored, PERIOD, [PROJECT, other], RUNTIME)
    context = multiprocessing.get_context('fork')
    processes = [context.Process(target=_concurrent_visit, args=(stored,p)) for p in (PROJECT, other)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    result = trace.read(stored, PERIOD)
    assert 1 <= len(result['visits']) <= 2
    trace.end(stored, PERIOD, True)
    result = trace.read(stored, PERIOD)
    assert ('excluded_visits_missing' in result['gaps']) == (len(result['visits']) < 2)


def test_corrupt_trace_cannot_export_arbitrary_text(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    path = stored/'.weekly-trace'/f'{PERIOD}.json'
    value = json.loads(path.read_text())
    value['visits']['private'] = {'system_prompt': 'TRACE-SECRET-CANARY'}
    path.write_text(json.dumps(value))
    with pytest.raises(trace.TraceProblem):
        trace.read(stored, PERIOD)
    result = audit.capture_krt(stored, runtime=RUNTIME)
    assert result['prospective_weekly_trace'] == {'state': 'unavailable'}
    assert 'TRACE-SECRET-CANARY' not in json.dumps(result)


def test_partial_sources_and_foreign_financial_schema_are_unknown(stored):
    put(stored, 'catalogue.json', {'retrieved_at': int(time.time()), 'complete': False})
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    assert 'source_incomplete' in trace.read(stored, PERIOD)['gaps']
    put(stored, 'ranking.json', {'schema_version': 999, 'rows': []})
    with pytest.raises(trace.TraceProblem, match='source_schema_unknown'):
        trace.observe(stored, 'running')


@pytest.mark.parametrize('slot', ['.lock', f'{PERIOD}.json'])
def test_trace_files_never_follow_a_symlink(stored, tmp_path, slot):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    target = tmp_path/'private.json'
    target.write_text('{"secret":"OUTSIDE"}')
    path = stored/'.weekly-trace'/slot
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(trace.TraceProblem):
        trace.read(stored, PERIOD)
    assert target.read_text() == '{"secret":"OUTSIDE"}'


def test_failed_atomic_replacement_preserves_the_existing_header(stored, monkeypatch):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    path = stored/'.weekly-trace'/f'{PERIOD}.json'
    before = path.read_bytes()
    observation = trace.observe(stored, 'running')
    monkeypatch.setattr(trace.os, 'replace', lambda *a, **kw: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(trace.TraceProblem):
        trace.visit(stored, PERIOD, PROJECT, observation, observation)
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.tmp-*'))


def test_trace_change_during_cached_capture_is_a_conflict(stored, monkeypatch):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    real = trace.read
    count = [0]
    def changing(*args):
        value = real(*args)
        count[0] += 1
        if count[0] > 1:
            value = copy.deepcopy(value)
            value['finished_at'] = 1000
        return value
    monkeypatch.setattr(trace, 'read', changing)
    with pytest.raises(audit.AuditError, match='snapshot_changed'):
        audit.capture_krt(stored, runtime=RUNTIME)


@pytest.mark.parametrize('field,value', [
    ('report_sha256', 123456789), ('rating_sha256', ['a'*64]),
    ('row_present', 1), ('model_at', True), ('model_version', 12345),
    ('rating_version', 'PRIVATE-CONTENT'), ('rating_inner_at', 1e100),
])
def test_mistyped_observation_is_not_an_export_channel(stored, field, value):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    observation = trace.observe(stored, 'running')
    observation[field] = value
    with pytest.raises(trace.TraceProblem):
        trace.visit(stored, PERIOD, PROJECT, observation, observation)
    assert trace.read(stored, PERIOD)['visits'] == {}


@pytest.mark.parametrize('slot', ['.lock', f'{PERIOD}.json'])
def test_fifo_trace_files_never_block_the_existing_runner(stored, slot):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    path = stored/'.weekly-trace'/slot
    path.unlink()
    os.mkfifo(path)
    started = time.monotonic()
    with pytest.raises(trace.TraceProblem):
        trace.read(stored, PERIOD)
    assert time.monotonic()-started < 0.5


def test_busy_trace_lock_does_not_wait_or_modify_the_existing_header(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    path = stored/'.weekly-trace'/f'{PERIOD}.json'
    before = path.read_bytes()
    with (path.parent/'.lock').open('r+') as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        with pytest.raises(trace.TraceProblem):
            trace.end(stored, PERIOD, True)
        assert time.monotonic()-started < 0.5
    assert path.read_bytes() == before


def test_existing_scheduled_loop_records_only_excluded_visit_and_keeps_finance(stored, monkeypatch):
    import auction_search.krt_ranking as ranking_module
    ranking = KrtRanking(stored.parent)
    monkeypatch.setattr(ranking, 'last_scheduled_moment', lambda *a: PERIOD)
    monkeypatch.setattr(ranking_module, '_trim_process_memory', lambda: None)
    monkeypatch.setitem(__import__('sys').modules, 'developaid_core', SimpleNamespace(
        COMMIT=RUNTIME['commit'], VERSION=RUNTIME['version']))
    original_report = (stored/'reports/running.json').read_bytes()
    original_financial = {key: ranking.rows()[0][key] for key in
                          ('entry_capacity_mln', 'investment_rating', 'computed_at', 'investment_rating_computed_at')}
    calls = []
    def offline_existing_screen(project):
        calls.append(project['slug'])
        return {'model_excluded': True, 'market_problem': 'offline observation unavailable'}
    assert ranking.start([PROJECT, {**PROJECT, 'status': 'Планируемый'}],
                         offline_existing_screen, scheduled=True,
                         trace_sources_before=ranking._weekly_trace('sources'))
    ranking._thread.join(5)
    assert not ranking._thread.is_alive() and calls == ['running']
    result = trace.read(stored, PERIOD)
    assert result['completed'] is True and result['gaps'] == []
    assert result['header']['selection']['raw_count'] == 2
    assert result['header']['selection']['unique_count'] == 1
    site, = result['header']['cohort']
    assert site['model_status_conflict'] is True and site['exclusion_reason'] == 'status_conflict'
    visit, = result['visits'].values()
    assert visit['unchanged'] is True
    assert (stored/'reports/running.json').read_bytes() == original_report
    assert {key: ranking.rows()[0][key] for key in original_financial} == original_financial


def test_manual_existing_run_does_not_create_a_weekly_trace(stored, monkeypatch):
    import auction_search.krt_ranking as ranking_module
    ranking = KrtRanking(stored.parent)
    monkeypatch.setattr(ranking_module, '_trim_process_memory', lambda: None)
    ranking._run([PROJECT], lambda p: {'model_excluded': True}, catalogue_run=False)
    assert not (stored/'.weekly-trace').exists()


def test_missing_or_changed_preselection_witness_is_never_a_coherent_source_claim(stored):
    trace.begin(stored, PERIOD, [PROJECT], RUNTIME)
    assert 'source_input_binding_missing' in trace.read(stored, PERIOD)['gaps']
    witness = trace.source_revision(stored)
    put(stored, 'catalogue.json', {'schema_version': 3, 'retrieved_at': int(time.time()),
                                'complete': True, 'projects': []})
    trace.begin(stored, PERIOD+7*86400, [PROJECT], RUNTIME, source_before=witness)
    assert 'input_revision_changed' in trace.read(stored, PERIOD+7*86400)['gaps']


def test_source_changed_during_run_and_resume_keeps_original_header(stored):
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    original = trace.read(stored, PERIOD)['header']
    put(stored, 'decisions.json', {'schema_version': 3, 'retrieved_at': int(time.time()),
                                'complete': True, 'all': [{'document_id': 'new'}]})
    observation = trace.observe(stored, 'running')
    trace.visit(stored, PERIOD, PROJECT, observation, observation)
    trace.end(stored, PERIOD, True)
    assert 'input_revision_changed' in trace.read(stored, PERIOD)['gaps']
    begin(stored, PERIOD, [PROJECT], RUNTIME)
    resumed = trace.read(stored, PERIOD)
    assert resumed['header'] == original
    assert resumed['completed'] is False and resumed['finished_at'] is None


@pytest.mark.parametrize('rows', ['foreign schema', [{'slug': 'running'}, {'slug': 'running'}]])
def test_ambiguous_saved_ranking_does_not_supply_a_preservation_claim(stored, rows):
    put(stored, 'ranking.json', {'schema_version': 1, 'rows': rows})
    with pytest.raises(trace.TraceProblem):
        trace.observe(stored, 'running')
