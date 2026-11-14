"""A rejected-size receipt identifies the bound and captured source, not money."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

import developaid_budget_funding_source as proof
import developaid_monitor as monitor
import main as wrapper
from test_budget_funding_source_proof import (source, capture, fm_bytes, rss_bytes,
    replace_rss, call, poll, PROJECT, CUT)  # noqa: F401


def failing_book(source, stage):
    if stage == 'fm_cf':
        raw = fm_bytes(lambda sheet: setattr(sheet.cell(20001, 1), 'number_format', '0'))
        monitor.replace_finance_baseline(PROJECT, raw, '2026-11-01', 'PRIVATE-FM-PATH-CANARY')
        return raw, 'cf_1_new', {'rows': True, 'columns': False, 'rectangle_cells': False}
    if stage == 'rss_estimate':
        raw = rss_bytes(lambda estimate, payments: setattr(estimate.cell(1, 1001), 'number_format', '0'))
        flags = {'rows': False, 'columns': True, 'rectangle_cells': False}
        name = proof.ESTIMATE
    else:
        raw = rss_bytes(lambda estimate, payments: setattr(payments.cell(2001, 1000), 'number_format', '0'))
        flags = {'rows': False, 'columns': False, 'rectangle_cells': True}
        name = proof.PAYMENTS
    replace_rss(source, raw)
    return raw, name, flags


@pytest.mark.parametrize('stage', ['fm_cf', 'rss_estimate', 'rss_payments'])
def test_each_rejected_stage_binds_exact_captured_bytes_without_reading_its_cells(source, monkeypatch, stage):
    raw, rejected_name, flags = failing_book(source, stage)
    original = ReadOnlyWorksheet.iter_rows
    def seen(sheet, *args, **kwargs):
        if sheet.title == rejected_name:
            pytest.fail('rejected worksheet cells were read')
        return original(sheet, *args, **kwargs)
    monkeypatch.setattr(ReadOnlyWorksheet, 'iter_rows', seen)
    with pytest.raises(proof.SourceProblem, match='worksheet_size_limit') as raised:
        capture()
    diag = proof.failure_diagnostic(raised.value)
    assert diag['stage'] == stage and diag['failed_bounds'] == flags
    assert diag['source_identity'] == {'kind': 'fm' if stage == 'fm_cf' else 'rss',
        'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert diag['declared_rectangle_cells'] == diag['declared_max_row'] * diag['declared_max_column']
    assert diag['limits'] == {'rows': 20000, 'columns': 1000, 'rectangle_cells': 2000000}
    assert diag['identity_captured_before_failure_not_pair_confirmation']
    assert not diag['complete_projection'] and not diag['financial_acceptance']
    assert len(json.dumps(diag).encode()) <= 2048
    assert 'PRIVATE' not in json.dumps(diag)


@pytest.mark.parametrize('stage', ['fm_cf', 'rss_estimate', 'rss_payments'])
def test_native_job_keeps_200_okfalse_and_old_code_with_only_bounded_diagnostic(source, stage):
    raw, _, flags = failing_book(source, stage)
    client = TestClient(wrapper.core.app)
    started = call(client, project=PROJECT, cut=CUT, ticket='d' * 32)
    assert started.status_code == 202
    response = poll(client, 'd' * 32)
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    result = response.json()
    assert result['ok'] is False and result['code'] == 'worksheet_size_limit'
    assert 'source_projection' not in result
    assert result['diagnostic']['stage'] == stage and result['diagnostic']['failed_bounds'] == flags
    assert result['diagnostic']['source_identity']['sha256'] == hashlib.sha256(raw).hexdigest()
    for forbidden in ('PRIVATE', 'cf_1_new', proof.ESTIMATE, proof.PAYMENTS,
                      'raw_cached_sum', 'rubles', 'filename', 'formula'):
        assert forbidden not in response.text


def test_failure_stops_before_pair_postverification_without_an_extra_source_read(source, monkeypatch):
    failing_book(source, 'fm_cf')
    originals = proof.ahr._copy, proof._rss_copy
    calls = [0, 0]
    def fm(*args, **kwargs):
        calls[0] += 1
        return originals[0](*args, **kwargs)
    def rss(*args, **kwargs):
        calls[1] += 1
        return originals[1](*args, **kwargs)
    monkeypatch.setattr(proof.ahr, '_copy', fm)
    monkeypatch.setattr(proof, '_rss_copy', rss)
    with pytest.raises(proof.SourceProblem) as raised:
        capture()
    assert calls == [1, 1]
    assert proof.failure_diagnostic(raised.value)['identity_captured_before_failure_not_pair_confirmation']


def test_unknown_or_oversized_diagnostic_leaves_the_existing_failure_shape(source, monkeypatch):
    failing_book(source, 'fm_cf')
    monkeypatch.setattr(proof, 'MAX_FAILURE_DIAGNOSTIC', 1)
    client = TestClient(wrapper.core.app)
    assert call(client, project=PROJECT, cut=CUT, ticket='e' * 32).status_code == 202
    response = poll(client, 'e' * 32)
    assert response.status_code == 200
    result = response.json()
    assert result['ok'] is False and result['code'] == 'worksheet_size_limit'
    assert 'diagnostic' not in result and 'source_projection' not in result
    assert proof.failure_diagnostic(proof.SourceProblem('worksheet_size_limit')) is None


@pytest.mark.parametrize('rows,columns', [(None, 1000), (True, 1000), (10 ** 5000, 1000), (20001, 10 ** 5000)],
                         ids=['missing', 'boolean', 'oversized_rows', 'oversized_columns'])
def test_unknown_or_illegal_dimensions_are_not_zero_or_unbounded_integer_text(rows, columns):
    exc = proof._WorksheetSizeProblem('cf_1_new', rows, columns)
    exc.captured_source = {'sha256': 'a' * 64, 'bytes': 1234, 'path': 'PRIVATE-PATH-CANARY'}
    diag = proof.failure_diagnostic(exc)
    assert diag['dimension_state'] == 'partial_or_outside_excel_range'
    assert diag['declared_max_row'] is None or diag['declared_max_column'] is None
    assert diag['declared_rectangle_cells'] is None
    assert len(json.dumps(diag).encode()) <= 2048 and 'PRIVATE' not in json.dumps(diag)


@pytest.mark.parametrize('source_identity', [None, {'sha256': 'PRIVATE-HASH', 'bytes': 12},
    {'sha256': 'a' * 64, 'bytes': True}, {'sha256': 'a' * 64, 'bytes': 10 ** 5000}])
def test_invalid_source_identity_is_not_guessed_or_echoed(source_identity):
    exc = proof._WorksheetSizeProblem('cf_1_new', 20001, 11)
    exc.captured_source = source_identity
    assert proof.failure_diagnostic(exc) is None


def test_unknown_stage_is_not_an_arbitrary_sheet_label_export():
    exc = proof._WorksheetSizeProblem('PRIVATE-UNKNOWN-SHEET', 20001, 11)
    exc.captured_source = {'sha256': 'a' * 64, 'bytes': 1234}
    assert proof.failure_diagnostic(exc) is None and str(exc) == 'worksheet_size_limit'


def test_successful_raw_projection_is_not_decorated_with_failure_metadata(source):
    result = capture()
    assert 'diagnostic' not in result and 'failed_bounds' not in result
    assert result['finance']['observations']['total']['rubles'] == 645000
    assert not result['financial_acceptance']
