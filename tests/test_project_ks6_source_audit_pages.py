"""Bounded pages of synthetic retained sources; no real source identifiers."""
from __future__ import annotations

import hashlib
import io
import json
import os

import openpyxl
import pytest

import developaid_contract_source_review as review
import developaid_management_report_jobs as jobs
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_api import api, post, poll, KEY, core  # noqa: F401
from test_monitor_cumulative_ledgers import archive
from test_project_ks6_source_audit import PROJECT, CUT, ks, retain, all_records, snapshot_bytes


def proof():
    initial = review.project_audit(PROJECT, CUT)
    return initial, review.corpus_token(PROJECT, CUT, initial['archives'])


def page(token, selected):
    return review.project_audit_page(PROJECT, CUT, selected, token)


def test_token_uses_only_reproducible_v1_inventory_fields(api):
    retain(archive([('Old.xlsx', ks()), ('Companion.pdf', b'unsupported')]), '2036-07-01')
    initial, token = proof()
    expected = dict(schema='ks6-retained-corpus-v1', project=PROJECT, cut=CUT, archives=[{
        **{k: a[k] for k in ('snapshot_id', 'taken_at', 'archive_sha256', 'manifest_present', 'size_bytes')},
        'files': [{k: f[k] for k in ('filename', 'file_sha256', 'size_bytes') if k in f} for f in a['files']]}
        for a in initial['archives']])
    assert token == hashlib.sha256(json.dumps(expected, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
    initial['archives'][0].update(state='changed', source_stable_verified=False)
    initial['archives'][0]['files'][0].update(read_state='changed', status='changed')
    assert review.corpus_token(PROJECT, CUT, initial['archives']) == token
    initial['archives'][0]['files'][0]['filename'] = 'Other.xlsx'
    assert review.corpus_token(PROJECT, CUT, initial['archives']) != token


def test_only_selected_sha_decodes_with_all_provenance_and_raw_unknowns(api, monkeypatch):
    old = ks('OLD', missing_header=True, formula=True, unknown_unit=True)
    new = ks('NEW')
    retain(archive([('Same.xlsx', old), ('Other.xlsx', new), ('Note.pdf', b'unopened')]), '2036-06-01')
    retain(archive([('Renamed.xls', old)]), '2036-07-01')
    initial, token = proof(); before = snapshot_bytes()
    selected = hashlib.sha256(old).hexdigest()
    original = ledgers._read_workbook; calls = []
    def decode(name, data, *args, **kwargs):
        calls.append(hashlib.sha256(data).hexdigest()); return original(name, data, *args, **kwargs)
    monkeypatch.setattr(ledgers, '_read_workbook', decode)
    result = page(token, [selected, selected])
    assert calls == [selected] and result['selected_read_complete']
    assert result['corpus_read_complete'] is result['financial_complete'] is result['binding_verified'] is None
    assert result['counts_scope'] == 'retained_selected_books_only_not_the_whole_corpus'
    assert result['counts']['unique_book_fingerprints'] == 1
    assert result['inventory_counts']['unique_book_fingerprints'] == 2
    assert len(result['archives']) == 2 and len(result['archives'][0]['files']) == 3
    assert result['archives'][1]['files'][0]['duplicate_proof'] == 'same_sha256_and_size'
    assert all(a['source_stable_verified'] and a['original_sha_verified'] for a in result['archives'])
    record = all_records(result)[0]
    assert record['identity_state'] == 'unresolved_header'
    item = record['items'][0]
    assert item['completed_quantity'] is None and not item['unit']
    assert item['raw_quantity_cells']['unit_cell']['kind'] == 'blank'
    assert any(c['kind'] == 'formula_without_cached_value' for c in item['raw_quantity_cells'].values())
    assert any(p['quantity'] == 0 for i in record['items'] for p in i['periods'])
    assert record['periods_scope'] == 'raw_source_periods_not_filtered_as_fact'
    assert snapshot_bytes() == before
    assert '=SUM(' not in json.dumps(result)


@pytest.mark.parametrize('selection', [[], ['a'*64]*9, ['UPPER'*13], [42], 'a'*64])
def test_invalid_selection_is_rejected_before_source_read(api, monkeypatch, selection):
    monkeypatch.setattr(review, '_audit_root', lambda *a: pytest.fail('invalid selector opened sources'))
    with pytest.raises(review.SourceReviewProblem):
        page('b'*64, selection)


@pytest.mark.parametrize('fault', ['token', 'foreign', 'removed', 'added', 'bytes', 'manifest'])
def test_changed_or_foreign_corpus_fails_before_any_selected_decode(api, monkeypatch, fault):
    raw = ks(); sid = retain(archive([('Old.xlsx', raw)]), '2036-07-01')
    _, token = proof(); selected = hashlib.sha256(raw).hexdigest(); root = ledgers._root(PROJECT)
    if fault == 'token': token = 'a'*64
    if fault == 'foreign': selected = 'b'*64
    if fault == 'removed':
        (root/(sid+'.zip')).unlink(); (root/(sid+'.json')).unlink()
    if fault == 'added': retain(archive([('New.xlsx', ks('NEW'))]), '2036-08-01')
    if fault == 'bytes': (root/(sid+'.zip')).write_bytes(b'changed')
    if fault == 'manifest': (root/(sid+'.json')).unlink()
    monkeypatch.setattr(ledgers, '_read_workbook', lambda *a, **k: pytest.fail('decode before corpus proof'))
    with pytest.raises(review.SourceReviewProblem): page(token, [selected])


def test_future_addition_does_not_change_eligible_token_or_open_future(api, monkeypatch):
    raw = ks(); retain(archive([('Old.xlsx', raw)]), '2036-07-01'); _, token = proof()
    future = retain(archive([('Future.xlsx', ks('LATER'))]), '2036-12-01')
    original = review._original
    def read(project, sid, **kwargs):
        assert sid != future; return original(project, sid, **kwargs)
    monkeypatch.setattr(review, '_original', read)
    result = page(token, [hashlib.sha256(raw).hexdigest()])
    assert result['corpus_token'] == token and result['selected_read_complete']
    assert result['future_archives'][0]['snapshot_id'] == future


@pytest.mark.parametrize('fault', ['bytes', 'added', 'removed', 'alias', 'root'])
def test_drift_during_selected_decode_rejects_the_entire_page(api, monkeypatch, fault):
    import developaid_monitor as monitor
    raw = ks(); sid = retain(archive([('Old.xlsx', raw)]), '2036-07-01'); _, token = proof()
    original = ledgers._read_workbook; root = ledgers._root(PROJECT)
    def decode(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'bytes': (root/(sid+'.zip')).write_bytes(b'changed')
        if fault == 'added': retain(archive([('New.xlsx', ks('NEW'))]), '2036-08-01')
        if fault == 'removed':
            (root/(sid+'.zip')).unlink(); (root/(sid+'.json')).unlink()
        if fault == 'alias': monkeypatch.setattr(monitor, '_resolved_slug', lambda *a: 'other-project')
        if fault == 'root': root.rename(root.with_name('removed-cumulative')); root.mkdir()
        return result
    monkeypatch.setattr(ledgers, '_read_workbook', decode)
    with pytest.raises(review.SourceReviewProblem): page(token, [hashlib.sha256(raw).hexdigest()])


def test_fifo_is_rejected_without_source_open(api, monkeypatch):
    raw = ks(); sid = retain(archive([('Old.xlsx', raw)]), '2036-07-01'); _, token = proof()
    path = ledgers._root(PROJECT)/(sid+'.zip'); path.unlink(); os.mkfifo(path)
    monkeypatch.setattr(review, '_original', lambda *a, **k: pytest.fail('FIFO opened'))
    with pytest.raises(review.SourceReviewProblem): page(token, [hashlib.sha256(raw).hexdigest()])


def test_page_wide_header_uses_native_first_work_row_and_keeps_v1_unchanged(api):
    wb = openpyxl.load_workbook(io.BytesIO(ks())); ws = wb.active
    ws['CM5'] = 'Учебное свидетельство справа'; ws['CN5'] = 0
    out = io.BytesIO(); wb.save(out); wb.close(); raw = out.getvalue()
    retain(archive([('Wide.xlsx', raw)]), '2036-07-01')
    initial, token = proof(); legacy = all_records(initial)[0]
    assert legacy['headers_truncated'] and not any(c['cell'] == 'CM5' for c in legacy['header_cells'])
    result = page(token, [hashlib.sha256(raw).hexdigest()]); record = all_records(result)[0]
    assert result['selected_read_complete'] and not record['headers_truncated']
    assert next(c['value'] for c in record['header_cells'] if c['cell'] == 'CN5') == 0
    for key in legacy.keys()-{'header_cells', 'headers_truncated'}:
        assert record[key] == legacy[key]
    assert review.project_audit(PROJECT, CUT) == initial


def test_wide_header_keeps_row_and_long_text_truncation_explicit():
    rows = [[None]*160 for _ in range(70)]; rows[0][159] = 'x'*1001
    record = {'items': [{'source': {'row': 65}}]}
    result = review._audit_record(record, rows, [], 'a'*64, CUT, page_headers=True)
    assert result['headers_truncated'] and result['header_cells'][0]['truncated']


def test_detail_budget_is_explicit_and_continuation_does_not_claim_corpus_complete(api, monkeypatch):
    raws = [ks('ONE'), ks('TWO')]; retain(archive([(f'{i}.xlsx', b) for i, b in enumerate(raws)]), '2036-07-01')
    _, token = proof(); monkeypatch.setattr(review, 'PROJECT_MAX_DETAIL_BYTES', 1)
    result = page(token, [hashlib.sha256(b).hexdigest() for b in raws])
    assert result['state'] == 'partial_selected' and not result['selected_read_complete']
    assert not result['counts_complete'] and result['corpus_read_complete'] is None
    assert len(result['continuation']['incomplete_selected_book_sha256']) == 2
    assert all(b['state'] == 'not_read_budget' and not b['sheets'] for b in result['books'])


def test_result_byte_cap_refuses_an_unreturnable_page(api, monkeypatch):
    raw = ks(); retain(archive([('Old.xlsx', raw)]), '2036-07-01'); _, token = proof()
    monkeypatch.setattr(review, 'PROJECT_MAX_RESULT_BYTES', 1024)
    with pytest.raises(review.SourceReviewProblem, match='размера страницы'):
        page(token, [hashlib.sha256(raw).hexdigest()])


def test_all_originals_are_stable_before_decode_and_unselected_drift_is_rejected(api, monkeypatch):
    selected = ks('SELECTED'); other = ks('OTHER')
    first = retain(archive([('Selected.xlsx', selected)]), '2036-06-01')
    second = retain(archive([('Other.xlsx', other)]), '2036-07-01'); _, token = proof()
    original_read = review._original; original_decode = ledgers._read_workbook; calls = []
    def read(project, sid, **kwargs):
        calls.append(sid); return original_read(project, sid, **kwargs)
    def decode(*args, **kwargs):
        assert calls.count(first) == calls.count(second) == 2
        result = original_decode(*args, **kwargs)
        (ledgers._root(PROJECT)/(second+'.zip')).write_bytes(b'changed unselected archive')
        return result
    monkeypatch.setattr(review, '_original', read)
    monkeypatch.setattr(ledgers, '_read_workbook', decode)
    with pytest.raises(review.SourceReviewProblem):
        page(token, [hashlib.sha256(selected).hexdigest()])


def test_finite_pages_cover_every_book_once_without_redecoding_other_books(api, monkeypatch):
    raws = [ks(f'S-{i}') for i in range(11)]
    retain(archive([(f'{i}.xlsx', b) for i, b in enumerate(raws)]), '2036-07-01')
    initial, token = proof(); pending = {b['file_sha256'] for b in initial['books']}
    original = ledgers._read_workbook; calls = []
    def decode(name, raw, *args, **kwargs):
        calls.append(hashlib.sha256(raw).hexdigest()); return original(name, raw, *args, **kwargs)
    monkeypatch.setattr(ledgers, '_read_workbook', decode)
    pages = []
    while pending:
        selected = sorted(pending)[:review.PAGE_MAX_BOOKS]; result = page(token, selected); pages.append(result)
        assert result['selected_read_complete']; pending.difference_update(result['selected_book_sha256'])
    assert len(pages) == 2 and len(calls) == len(set(calls)) == 11
    assert all(p['corpus_token'] == token and p['corpus_read_complete'] is None for p in pages)


def test_partial_v1_continues_only_missing_books_and_keeps_saved_details(api, monkeypatch):
    raws = [ks(f'S-{i}') for i in range(4)]
    retain(archive([(f'{i}.xlsx', b) for i, b in enumerate(raws)]), '2036-07-01')
    full, _ = proof()
    with monkeypatch.context() as limited:
        limited.setattr(review, 'PROJECT_MAX_DETAIL_BYTES', len(json.dumps(full['books'][0], ensure_ascii=False).encode())+1)
        initial, token = proof()
    saved = {b['file_sha256']: b for b in initial['books'] if b['state'] == 'read'}
    pending = [b['file_sha256'] for b in initial['books'] if b['state'] == 'not_read_budget']
    assert saved and pending and not initial['read_complete']
    original = ledgers._read_workbook; calls = []
    def decode(name, raw, *args, **kwargs):
        calls.append(hashlib.sha256(raw).hexdigest()); return original(name, raw, *args, **kwargs)
    monkeypatch.setattr(ledgers, '_read_workbook', decode)
    result = page(token, pending)
    assert result['selected_read_complete'] and set(calls) == set(pending) and not saved.keys() & set(calls)
    merged = {**saved, **{b['file_sha256']: b for b in result['books']}}
    assert merged == {b['file_sha256']: b for b in full['books']}


@pytest.mark.parametrize('selection', [[], ['a'*64]*9, ['A'*64], ['a'*63], [0], 'a'*64])
def test_page_route_bounds_and_strict_sha(api, selection):
    client, _ = api
    response = post(client, 'contracts/source-audit-page', project=PROJECT, cut=CUT,
        book_sha256=selection, corpus_token='b'*64)
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('extra', [{'path': '/tmp/no'}, {'filename': 'A.xlsx'}, {'url': 'https://example.invalid'},
    {'sheet': 'KS'}, {'range': 'A1:ZZ99'}, {'contract_id': 'a'*64}, {'snapshot_id': 'b'*64}])
def test_page_strict_route_forbids_source_guesses(api, extra):
    client, _ = api
    response = client.post('/monitor/contracts/source-audit-page', json=dict(key=KEY, project=PROJECT, cut=CUT,
        book_sha256=['a'*64], corpus_token='b'*64, **extra))
    assert response.status_code == 422 and response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('key,session', [('', ''), ('wrong', ''), ('market-key', ''), ('', 'claimed-team'), ('', 'demo')])
def test_page_auth_precedes_source_and_store(api, monkeypatch, key, session):
    client, tmp = api
    monkeypatch.setattr(review, 'project_audit_page', lambda *a, **k: pytest.fail('source before admin'))
    monkeypatch.setattr(jobs.Store, 'start', lambda *a, **k: pytest.fail('store before admin'))
    response = post(client, 'contracts/source-audit-page', project=PROJECT, cut=CUT,
        book_sha256=['a'*64], corpus_token='b'*64, key=key, session=session)
    assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'
    assert not (tmp/'monitor'/'.cumulative_jobs').exists()


def test_page_uses_native_store_result_and_exact_owner_token_sha_set_binding(api, monkeypatch):
    client, tmp = api
    raws = [ks('ONE'), ks('TWO')]; retain(archive([(f'{i}.xlsx', b) for i, b in enumerate(raws)]), '2036-07-01')
    _, token = proof(); selected = [hashlib.sha256(b).hexdigest() for b in raws]
    before = snapshot_bytes(); ticket = '7'*32
    data = dict(project=PROJECT, cut=CUT, book_sha256=selected, corpus_token=token, ticket=ticket)
    started = post(client, 'contracts/source-audit-page', session='owner-A', **data)
    assert started.status_code in (200, 202)
    result = started if started.status_code == 200 else poll(client, ticket, session='owner-A')
    assert result.json()['source_audit_page']['selected_read_complete']
    assert result.json()['runtime'] == dict(version=core.VERSION, commit=core.COMMIT)
    assert post(client, 'contracts/source-audit-page', session='owner-A', **dict(data, book_sha256=selected[::-1])).status_code == 200
    for change in [dict(corpus_token='a'*64), dict(book_sha256=selected[:1]), dict(cut='2036-08-18'), dict(project='Other')]:
        assert post(client, 'contracts/source-audit-page', session='owner-A', **dict(data, **change)).status_code == 409
    assert post(client, 'contracts/result', session='owner-B', ticket=ticket).status_code == 404
    assert post(client, 'contracts/source-audit', session='owner-A', project=PROJECT, cut=CUT, ticket=ticket).status_code == 409
    stored = jobs.Store(tmp/'monitor'/'.cumulative_jobs').poll(ticket,
        jobs.owner_binding(KEY, 'owner-A', 'monitor-cumulative-v1:contracts'), 'monitor-cumulative-v1:contracts')
    assert stored['source_audit_page'] == result.json()['source_audit_page'] and snapshot_bytes() == before
