"""A native draft download references the exact visible GPR without adopting it."""
import copy
import io
import json
import os

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import developaid_contract_files as files
import developaid_contract_gpr as gpr
import developaid_contract_gpr_export as export
import developaid_contract_rds as rds
import developaid_contract_workforce as workforce
import developaid_monitor_contracts as contracts
import developaid_monitor_daily as daily
from tests.test_contract_relative_gpr_calendar import card, record, ROW, PROJECT, CUT, KEY, finished


def pending_card(card):
    folder, sha, _ = card
    value = files._stored(folder/(sha+'.json'))
    value['gpr_pending'] = True
    files._json(folder/(sha+'.json'), value)
    return folder, sha


def snapshot(card):
    pending_card(card)
    result = {'ok': True, **files.listing(PROJECT, ROW['id'], CUT)}
    result['rds_comparison'] = rds.build(result)
    register = {'rows': [ROW], workforce.REGISTER_GUARD: workforce.cohort_sources(PROJECT, CUT)}
    result['gpr']['workforce'] = workforce.from_cached(PROJECT, ROW, register, CUT, result['gpr'])
    result['gpr_export'] = export.bind_snapshot(PROJECT, CUT, ROW['id'], result, ROW)
    assert result['gpr_export']['available'], result['gpr_export']
    return result


def download(client, base, opened, **extra):
    return client.post('/monitor/contracts/gpr.xlsx', json={**base, 'ticket': opened['ticket'],
        'revision': opened['gpr_export']['revision'], **extra})


def test_exact_preview_draft_preserves_sources_flags_and_three_native_sheets(card):
    result = snapshot(card)
    before = copy.deepcopy(result)
    native = {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()}
    meta = export.select_snapshot(result, PROJECT, CUT, ROW['id'], result['gpr_export']['revision'])
    assert meta['schema'] == 'contract-gpr-performance-xlsx-v13'
    assert meta['mode'] == 'preview' and meta['draft'] is True
    assert meta['gpr_binding']['source'] == result['gpr']['preview']['source']
    assert 'ЧЕРНОВИК' in meta['filename'] and 'contract-gpr-draft-' in export.disposition(meta)
    book = load_workbook(io.BytesIO(export.workbook(meta, result)))
    assert book.sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
    for sheet in book:
        assert sheet['A1'].value.startswith(export.DRAFT_NOTICE)
        assert sheet.row_dimensions[1].height >= 105
        assert sheet['A1'].fill.fgColor.rgb == '00FFF2CC'
        assert '"view_only": true' in sheet['A1'].comment.text
        assert sheet.freeze_panes is None
    assert result == before
    assert result['gpr']['source'] is None and result['gpr']['schedule'] is None
    assert gpr.events(card[0]) == []
    assert {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()} == native


@pytest.mark.parametrize('defect', ['source', 'schedule', 'candidate', 'pending', 'document', 'guard',
                                  'plan', 'price', 'workforce', 'roles'])
def test_cached_preview_context_change_cannot_reuse_bound_revision(card, defect):
    result = snapshot(card)
    old_revision = result['gpr_export']['revision']
    if defect == 'source':
        result['gpr']['preview']['source']['sha256'] = 'f'*64
    elif defect == 'schedule':
        result['gpr']['preview']['schedule']['lines'][0]['name'] = 'Changed graph'
    elif defect == 'candidate':
        result['gpr']['activation_candidate_set'][0]['schedule_sha256'] = 'f'*64
    elif defect == 'pending':
        result['gpr']['pending'][0]['state'] = 'accepted'
    elif defect == 'document':
        result['documents'][0]['price'] = {'unsupported': 'changed price source'}
    elif defect == 'guard':
        result['gpr']['guard'] = 'f'*64
    elif defect == 'plan':
        result['plan']['new_plan'] = True
    elif defect == 'price':
        result['price'] = {'changed': True}
    elif defect == 'workforce':
        result['gpr']['workforce']['reason'] = 'Changed workforce source'
    else:
        result['gpr']['documents_raw_id'] = 'f'*64
    with pytest.raises(export.rds_export.ExportProblem, match='изменилась'):
        export.select_snapshot(result, PROJECT, CUT, ROW['id'], old_revision)


@pytest.mark.parametrize('defect', ['missing_preview', 'missing_document', 'unsupported_candidate',
                                  'hidden_active_schedule', 'wrong_cut'])
def test_unexportable_preview_reports_specific_saved_context_reason(card, defect):
    result = snapshot(card)
    if defect == 'missing_preview':
        result['gpr']['preview'] = None
    elif defect == 'missing_document':
        result['documents'] = []
    elif defect == 'unsupported_candidate':
        result['gpr']['activation_candidate_set'] = []
    elif defect == 'hidden_active_schedule':
        result['gpr']['schedule'] = result['gpr']['preview']['schedule']
    else:
        result['gpr']['cut'] = '2026-02-11'
    meta = export.bind_snapshot(PROJECT, CUT, ROW['id'], result, ROW)
    assert not meta['available'] and meta['detail']
    assert 'предпросмотр' in meta['detail'].lower()
    assert result['gpr']['source'] is None


def test_preview_does_not_rebind_rds_positions_even_when_codes_match(card):
    from tests.test_contract_relative_gpr_calendar import operation_projection_case
    result = snapshot(card)
    links, comparison, _ = operation_projection_case()
    for binding in links['plan']['editions'][0]['position_links']:
        binding['lines'][0]['code'] = result['gpr']['preview']['schedule']['lines'][0]['code']
    result['plan']['editions'] = links['plan']['editions']
    comparison.update(layout=export.LAYOUT, cut=CUT)
    comparison['rows'] = [{**{field: None for field in rds.FIELDS}, **row} for row in comparison['rows']]
    result['rds_comparison'] = comparison
    meta = export.bind_snapshot(PROJECT, CUT, ROW['id'], result, ROW)
    book = load_workbook(io.BytesIO(export.workbook(meta, result)))
    fact_rows = [row for row in book['ГПР'] if row[1].value and 'Исходный план · Факт:' in str(row[1].value)]
    assert len(fact_rows) == 2
    assert sorted(row[4].value for row in fact_rows) == [0, .4]
    assert all(row[2].value is None and row[3].value is None for row in fact_rows)
    for row in fact_rows:
        identity = json.loads(row[1].comment.text.splitlines()[0])
        assert identity['gpr_sha256'] is None and identity['source_gpr_code'] is None
        assert all(cell.fill.patternType is None for cell in row[6:])
    assert result['gpr']['source'] is None and result['gpr']['schedule'] is None
    assert result['rds_comparison'] == comparison


@pytest.mark.parametrize('old_meta', [{'schema': 'contract-gpr-performance-xlsx-v12'},
                                    {'available': False, 'detail': 'Previous card had no active GPR.'}])
def test_old_export_metadata_is_not_readmitted_as_a_preview(card, old_meta):
    result = snapshot(card)
    revision = result['gpr_export']['revision']
    result['gpr_export'].update(old_meta)
    with pytest.raises(export.rds_export.ExportProblem):
        export.select_snapshot(result, PROJECT, CUT, ROW['id'], revision)


def test_native_preview_download_owner_context_and_source_changes(card, monkeypatch):
    import main
    pending_card(card)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(contracts, 'build', lambda *args, **kwargs: {'rows': [copy.deepcopy(ROW)], 'cut': CUT})
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    opened = finished(client, client.post('/monitor/contracts/documents', json=base))
    assert opened['gpr_export']['mode'] == 'preview' and opened['gpr_export']['draft'] is True
    assert opened['gpr']['source'] is None
    before = {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()}
    response = download(client, base, opened)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert 'contract-gpr-draft-' in response.headers['content-disposition']
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ['ГПР', 'Выполнение', 'Численность подрядчика']
    assert all(sheet['A1'].value.startswith(export.DRAFT_NOTICE) for sheet in book)
    assert {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()} == before
    for wrong in ({'key': 'wrong'}, {'session': 'other-owner'}, {'project': 'Other project'},
                  {'cut': '2026-02-11'}, {'contract_id': 'f'*64}, {'revision': 'f'*64}):
        assert download(client, base, opened, **wrong).status_code in (403, 409)
    record(card[0], 'new-pending-preview', {'number': '1', 'date': '2026-02-05'}, pending=True)
    assert download(client, base, opened).status_code == 409
    fresh = finished(client, client.post('/monitor/contracts/documents', json=base))
    assert fresh['gpr_export']['revision'] != opened['gpr_export']['revision']
    assert fresh['gpr']['preview']['source'] != opened['gpr']['preview']['source']
    assert download(client, base, fresh).status_code == 200
    assert download(client, base, opened).status_code == 409
    assert gpr.events(card[0]) == []
    selected = fresh['gpr']['preview']['source']['sha256']
    source_path = card[0]/(selected+'.pdf')
    info = source_path.stat()
    raw = source_path.read_bytes()
    source_path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
    os.utime(source_path, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert gpr.guard([card[0]]) == fresh['gpr']['guard'], 'The selected PDF also needs a content hash check.'
    assert download(client, base, fresh).status_code == 409


@pytest.mark.parametrize('change', ['source', 'workforce'])
def test_native_preview_rechecks_sources_after_book_generation(card, monkeypatch, change):
    import main
    pending_card(card)
    reports = []
    monkeypatch.setattr(daily, '_load_reports', lambda _: copy.deepcopy(reports))
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(contracts, 'build', lambda *args, **kwargs: {'rows': [copy.deepcopy(ROW)], 'cut': CUT})
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    opened = finished(client, client.post('/monitor/contracts/documents', json=base))
    original = export.workbook
    generated = []
    def changing_workbook(*args):
        raw = original(*args)
        generated.append(True)
        if change == 'source':
            path = card[0]/(card[1]+'.json')
            source = files._stored(path)
            source['warnings'].append('Source changed while the draft was generated')
            files._json(path, source)
        else:
            reports.append({'date': CUT, 'text': 'Новая сводка без распределения по договорам'})
        return raw
    monkeypatch.setattr(export, 'workbook', changing_workbook)
    response = download(client, base, opened)
    assert generated == [True] and response.status_code == 409
    if change == 'workforce':
        assert 'численности' in response.json()['detail']
    assert gpr.events(card[0]) == []


@pytest.mark.parametrize('legacy_revision', ['contract-gpr-source-material-components-v5',
                                          'contract-gpr-source-material-components-v6'])
def test_native_old_completed_preview_cache_cannot_reenter_and_fresh_v7_nonce_builds_once(card, monkeypatch, legacy_revision):
    import main
    import developaid_contract_control as control
    import developaid_management_report_jobs as jobs
    import developaid_monitor as monitor
    current_revision = control.CALCULATION_REVISION
    assert current_revision == 'contract-gpr-source-material-components-v7'
    pending_card(card)
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(contracts, 'build', lambda *args, **kwargs: {'rows': [copy.deepcopy(ROW)], 'cut': CUT})
    client = TestClient(main.app)
    base = {'key': KEY, 'session': 'synthetic-owner', 'project': PROJECT, 'cut': CUT, 'contract_id': ROW['id']}
    old_ticket, new_ticket = 'a'*32, 'b'*32
    # v5 had a visible preview but no download; v6 admitted preview downloads
    # while lacking the source-backed KS-6a reporting-zero projection.
    with monkeypatch.context() as legacy:
        legacy.setattr(control, 'CALCULATION_REVISION', legacy_revision)
        if legacy_revision.endswith('-v5'):
            legacy.setattr(export, 'bind_snapshot', lambda *args, **kwargs: {
                'available': False, 'detail': 'Действующий ГПР не определён. Проверьте документы договора.'})
        old = finished(client, client.post('/monitor/contracts/documents', json={**base, 'ticket': old_ticket}))
    assert old['ok'] and not old['pending']
    assert old['contract_calculation_revision'] == legacy_revision
    assert old['gpr']['preview']
    assert old['gpr_export']['available'] is legacy_revision.endswith('-v6')
    store = jobs.Store(monitor._SNAPSHOT_DIR/'.cumulative_jobs')
    old_bytes = {suffix: store._path(old_ticket, suffix).read_bytes() for suffix in ('json', 'result')}
    source_bytes = {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()}
    assert store._meta(old_ticket)['result_revision'] == legacy_revision
    assert json.loads(old_bytes['result'])['gpr_export'] == old['gpr_export']
    native_producer = main.core._monitor_cumulative_execute
    calls = []
    def calculate(*args):
        calls.append(args[0])
        return native_producer(*args)
    monkeypatch.setattr(main.core, '_monitor_cumulative_execute', calculate)
    auth = {'key': KEY, 'session': base['session'], 'ticket': old_ticket}
    for route, extra in [('result', {}), ('result-part', {'offset': 0})]:
        refused = client.post('/monitor/contracts/'+route, json={**auth, **extra})
        assert refused.status_code == 409
        assert refused.headers['x-monitor-job-error'] == 'calculation_changed'
    assert download(client, base, {**old, 'gpr_export': {
        'revision': old['gpr_export'].get('revision') or '0'*64}}).status_code == 409
    # A retained nonce is immutable, even when its method fingerprint is old.
    assert client.post('/monitor/contracts/documents', json={**base, 'ticket': old_ticket}).status_code == 409
    assert calls == []
    fresh = finished(client, client.post('/monitor/contracts/documents', json={**base, 'ticket': new_ticket}))
    assert calls == ['documents']
    assert fresh['contract_calculation_revision'] == current_revision
    assert store._meta(new_ticket)['result_revision'] == current_revision
    assert fresh['gpr_export']['schema'] == export.SCHEMA
    assert fresh['gpr_export']['available'] and fresh['gpr_export']['mode'] == 'preview'
    assert fresh['gpr_export']['draft'] is True
    assert fresh['gpr']['source'] is None and fresh['gpr']['schedule'] is None
    assert fresh['gpr']['preview']['source'] == old['gpr']['preview']['source']
    assert fresh['gpr']['guard'] == old['gpr']['guard']
    assert fresh['rds_comparison'] == old['rds_comparison']
    assert download(client, base, fresh).status_code == 200
    retried = finished(client, client.post('/monitor/contracts/documents', json={**base, 'ticket': new_ticket}))
    assert retried == fresh and calls == ['documents']
    assert {suffix: store._path(old_ticket, suffix).read_bytes() for suffix in old_bytes} == old_bytes
    assert {p.name: p.read_bytes() for p in card[0].iterdir() if p.is_file()} == source_bytes
    assert gpr.events(card[0]) == []
