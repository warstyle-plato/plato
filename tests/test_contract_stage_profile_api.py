"""Opt-in diagnostics use the ordinary authenticated full-register lifecycle."""
import base64
import gzip
import json
import threading

import pytest

import developaid_contract_stage_profile as profile
import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_api import api, post, poll, core, KEY
from test_monitor_cumulative_ledgers import archive, book
from test_monitor_keeps_every_snapshot import _rss_book

PROJECT = 'Synthetic full stage profile'
CUT = '2026-11-06'


def admit(client, ticket, **extra):
    return post(client, 'contracts/build', project=PROJECT, cut=CUT, ticket=ticket, **extra)


@pytest.mark.parametrize('invalid', ['true', 1, None, {}, []])
def test_stage_flag_requires_a_boolean_before_any_admission(api, invalid):
    client, root = api
    assert admit(client, 'a'*32, profile_stages=invalid).status_code == 422
    assert not (root/'monitor'/'.cumulative_jobs').exists()


@pytest.mark.parametrize('key', ['', 'wrong-key'])
def test_profiling_has_the_same_strict_admin_gate(api, monkeypatch, key):
    client, root = api
    monkeypatch.setattr(core, '_monitor_cumulative_execute', lambda *a: pytest.fail('unauthenticated worker'))
    response = admit(client, 'a'*32, key=key, session='claimed-demo-team', profile_stages=True)
    assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'
    assert not (root/'monitor'/'.cumulative_jobs').exists()


def test_full_ordinary_register_is_identical_and_chunks_keep_their_policies(api):
    client, root = api
    monitor.store_estimate(PROJECT, _rss_book(payments=[(CUT, 100)]), CUT)
    for date in ('2026-11-01', CUT):
        saved = ledgers.store_archive(PROJECT, archive([('Works.xlsx', book())]), date, 'Works.zip')
        path = ledgers._root(PROJECT)/(saved['snapshot_id']+'.json')
        manifest = json.loads(path.read_text())
        manifest.pop('parser_schema')
        path.write_text(json.dumps(manifest))
    assert admit(client, 'a'*32).status_code == 202
    normal = poll(client, 'a'*32).json()
    assert normal['ok'] is True and 'diagnostics' not in normal
    assert admit(client, 'b'*32, profile_stages=True, chunked=True).status_code == 202
    traced_response = poll(client, 'b'*32)
    assert traced_response.status_code == 200
    traced = traced_response.json()
    assert traced['register'] == normal['register']
    assert set(traced) == set(normal) | {'diagnostics'}
    measured = traced['diagnostics']
    assert measured['purpose'] == profile.PURPOSE
    assert len(json.dumps(measured).encode()) <= profile.MAX_BYTES
    stages = {item['stage'] for item in measured['stages']}
    assert {'execute_total', 'contracts_build', 'manifest_list', 'manifest_read',
            'manifest_decode', 'rss_projection', 'history_enrich', 'daily_enrich',
            'card_controls', 'card_listing', 'card_acts', 'jsonable_encoder',
            'zip_verify', 'source_cache'} <= stages
    assert measured['counters']['ram_hit'] > 0
    assert measured['counters']['manifest_bytes'] > 0
    store = jobs.Store(root/'monitor'/'.cumulative_jobs')
    meta = store._meta('b'*32)
    assert meta['result_limit_bytes'] == jobs.MAX_EXTENDED_RESULT_BYTES
    assert meta['compress_result'] is True
    assert set(meta) <= {'ticket','owner','profile','request','created','state',
                         'result_limit_bytes','compress_result','gzip_result','result_bytes','context','result_revision'}
    import developaid_contract_control as control
    assert meta['result_revision'] == control.CALCULATION_REVISION
    assert meta['context'] == ledgers.snapshot_job_context(PROJECT)
    for accept_gzip in (False, True):
        parts = []; offset = 0
        while True:
            response = post(client, 'contracts/result-part', ticket='b'*32, offset=offset, accept_gzip=accept_gzip)
            assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
            part = response.json()['result_part']
            data = base64.b64decode(part['content_base64'], validate=True)
            assert len(data) == min(jobs.RESULT_PART_BYTES, part['total_bytes']-offset)
            parts.append(data); offset += len(data)
            if offset == part['total_bytes']:
                break
        raw = b''.join(parts)
        decoded = gzip.decompress(raw) if part['encoding'] == 'gzip' else raw
        assert len(decoded) == part['json_bytes'] <= jobs.MAX_EXTENDED_RESULT_BYTES
        assert json.loads(decoded) == {k:v for k,v in traced.items() if k not in {'ticket','pending'}}
    assert not profile._ACTIVE.get()


def test_mode_is_bound_to_ticket_and_key_owner_ttl_still_gate_reads(api, monkeypatch):
    client, root = api
    calls = []
    def execute(*args):
        calls.append(1)
        profile.count('ram_hit')
        return {'ok': True, 'register': {'rows': [], 'unknown': None, 'zero': 0}}
    monkeypatch.setattr(core, '_monitor_cumulative_execute', execute)
    assert admit(client, 'a'*32, profile_stages=True, session='owner').status_code == 202
    result = poll(client, 'a'*32, session='owner')
    assert result.status_code == 200
    assert admit(client, 'a'*32, profile_stages=False, session='owner').status_code == 409
    assert admit(client, 'a'*32, profile_stages=True, session='owner').json() == result.json()
    assert calls == [1]
    assert post(client,'contracts/result',ticket='a'*32,session='another').status_code == 404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','rotated-synthetic-key')
    assert post(client,'contracts/result',ticket='a'*32,session='owner').status_code == 403
    assert post(client,'contracts/result',ticket='a'*32,session='owner',key='rotated-synthetic-key').status_code == 404
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',KEY)
    store = jobs.Store(root/'monitor'/'.cumulative_jobs')
    with store._locked():
        meta = store._meta('a'*32); meta['created'] -= jobs.TTL_SECONDS+1; store._save(meta)
    assert post(client,'contracts/result',ticket='a'*32,session='owner').status_code == 404


def test_current_calculation_fingerprint_accepts_omitted_and_false_flag_unchanged(api, monkeypatch):
    client, root = api
    store = jobs.Store(root/'monitor'/'.cumulative_jobs')
    purpose = 'monitor-cumulative-v1:contracts'
    owner = jobs.owner_binding(KEY, '', purpose)
    import developaid_contract_control as control
    context = ledgers.snapshot_job_context(PROJECT)
    legacy_payload = {'operation': 'view', 'click': 'a'*32, 'project': PROJECT, 'cut': CUT,
                      'contract_calculation_revision':control.CALCULATION_REVISION,'source_context':context}
    # The calculation is current; only omitted/false diagnostic flags are old.
    legacy_result = {'ok': True, 'register': {'rows': [], 'unknown': None, 'zero': 0},
                     'contract_calculation_revision':control.CALCULATION_REVISION}
    store.start(owner, purpose, legacy_payload, lambda: legacy_result, 'a'*32,
                result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES, context=context,
                result_revision=control.CALCULATION_REVISION)
    response = poll(client,'a'*32)
    assert response.status_code == 200 and 'diagnostics' not in response.json()
    before = store._meta('a'*32)
    monkeypatch.setattr(core, '_monitor_cumulative_execute', lambda *args: pytest.fail('Old ticket rebuilt'))
    assert admit(client,'a'*32).json() == response.json()
    assert admit(client,'a'*32,profile_stages=False).json() == response.json()
    assert admit(client,'a'*32,profile_stages=True).status_code == 409
    assert store._meta('a'*32) == before


def test_source_cache_reports_cold_disk_ram_and_uncacheable_without_changing_evidence(api, monkeypatch):
    imported = ledgers.store_archive(PROJECT, archive([('Works.xlsx', book())]), CUT, 'Works.zip')
    monkeypatch.setattr(ledgers, '_PARSE_CACHE', type(ledgers._PARSE_CACHE)())
    def read():
        return ledgers.verified_archive(PROJECT, imported['snapshot_id'], 'Works.zip')
    with profile.collect() as cold:
        expected = read()
    assert cold.export()['counters']['disk_miss'] == 1
    assert 'archive_parse' in {s['stage'] for s in cold.export()['stages']}
    ledgers._PARSE_CACHE.clear()
    with profile.collect() as disk_hit:
        assert read() == expected
    assert disk_hit.export()['counters']['disk_hit'] == 1
    assert 'archive_parse' not in {s['stage'] for s in disk_hit.export()['stages']}
    with profile.collect() as ram_hit:
        assert read() == expected
    assert ram_hit.export()['counters']['ram_hit'] == 1
    ledgers._PARSE_CACHE.clear()
    monkeypatch.setattr(ledgers, '_PARSE_CACHE_BYTES', 10)
    with profile.collect() as limited:
        assert read() == expected
    assert limited.export()['counters']['not_cached_compressed_limit'] == 1
    assert not ledgers._PARSE_CACHE


def test_default_and_traced_concurrent_workers_cannot_share_metrics(api, monkeypatch):
    client, _ = api
    entered = threading.Barrier(2)
    def execute(operation, payload, archive):
        entered.wait(timeout=10)
        profile.count('ram_hit', 1 if payload['project'] == PROJECT else 999)
        return {'ok':True,'register':{'rows':[]}}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',execute)
    assert admit(client,'a'*32,profile_stages=True).status_code == 202
    assert post(client,'contracts/build',project='Synthetic default worker',cut=CUT,ticket='b'*32).status_code == 202
    traced = poll(client,'a'*32).json(); normal = poll(client,'b'*32).json()
    assert traced['diagnostics']['counters'] == {'ram_hit':1}
    assert 'diagnostics' not in normal


def test_diagnostics_do_not_capture_inputs_or_private_exceptions(api, monkeypatch, caplog):
    client, root = api
    private = 'SYNTHETIC_PRIVATE_PATH_SOURCE_HASH_MONEY_CELL'
    def fail(*args):
        with profile.measure('archive_parse'):
            raise ValueError(private)
    monkeypatch.setattr(core,'_monitor_cumulative_execute',fail)
    admit(client,'a'*32,profile_stages=True)
    response = poll(client,'a'*32)
    assert response.status_code == 500
    store = jobs.Store(root/'monitor'/'.cumulative_jobs')
    assert private not in response.text + caplog.text + json.dumps(store._meta('a'*32))
    assert profile._ACTIVE.get() is None
