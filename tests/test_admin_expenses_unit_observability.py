"""Saved-cell unit hints never normalize money or weaken the old raw reader."""
import hashlib
import json

import pytest
from openpyxl.cell.read_only import ReadOnlyCell
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

import developaid_admin_expenses_source as proof
import developaid_admin_expenses_unit_observability as hints
from test_admin_expenses_source_proof import source, changed, PROJECT, RUNTIME  # noqa: F401


def raw():
    return proof.capture_saved_snapshot(PROJECT, runtime=RUNTIME)


def edit_book(source, *, formats=('0.00"руб."',) * 3, unit_header=None, units=('тыс. руб.',) * 4, count=4):
    def edit(sheet):
        sheet['C14'] = None
        sheet['E6'] = unit_header
        for i in range(count):
            row = 56 + i
            #2.4.5 is the excluded tax branch; extra diagnostic-limit leaves
            #must remain actual AHR leaves under the unchanged source policy.
            sheet.cell(row, 3, f'2.4.{i + 1 if i < 4 else i + 2}')
            sheet.cell(row, 4, 'PRIVATE-ARTICLE-MUST-NOT-LEAVE')
            sheet.cell(row, 5, units[i % len(units)])
            for j, fmt in enumerate(formats):
                sheet.cell(row, 9 + j, 10 * i + j + 1).number_format = fmt
    changed(source, edit)


def assert_unknown(diag):
    assert diag['raw_unit_state'] == 'unknown'
    assert diag['raw_storage_unit'] is None and diag['money_factor'] is None
    assert not diag.get('financial_acceptance', False)


def test_headerless_ruble_format_is_only_a_hint_and_cached_cells_are_identical(source):
    edit_book(source)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source[0].iterdir() if p.is_file()}
    data = (source[0] / 'finance.xlsx').read_bytes()
    legacy_rows, legacy_headers, legacy_units = proof._cells(data)
    got = raw()
    assert got['rows'] == legacy_rows and got['header_cells'] == legacy_headers
    assert got['unit_evidence'] == legacy_units
    diag = got['unit_observability']; assert_unknown(diag)
    assert diag['unit_header']['state'] == 'missing'
    assert diag['row_unit_samples'] == []
    assert diag['sampled_leaf_count'] == 4 and len(diag['cell_samples']) == 12
    group, = diag['format_groups']
    assert group['cell_count'] == 12 and group['hints'] == [{'kind': 'currency', 'token': 'руб.'}]
    assert not group['display_scaling_syntax']
    assert diag['source_sha256'] == got['source']['sha256'] == hashlib.sha256(data).hexdigest()
    assert diag['metadata_sha256'] == got['source']['metadata_sha256']
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source[0].iterdir() if p.is_file()}


def test_display_million_scaling_does_not_mean_stored_millions(source):
    edit_book(source, formats=('0,,"млн руб"',) * 3, unit_header='Ед. изм.')
    got = raw(); diag = got['unit_observability']; assert_unknown(diag)
    group, = diag['format_groups']
    assert group['display_scaling_syntax'] and group['display_scale_ambiguous']
    assert group['hints'] == [{'kind': 'currency', 'token': 'млн руб.'}]
    assert {s['token'] for s in diag['row_unit_samples']} == {'тыс. руб.'}
    assert all(s['state'] == 'row_label_hint_only' and s['formula'] is False for s in diag['row_unit_samples'])
    assert [c['cached_value'] for r in got['rows'] for c in r['cells'].values()] == [1, 2, 3, 11, 12, 13, 21, 22, 23, 31, 32, 33]


@pytest.mark.parametrize('fmt,unit,kind', [('0"м²"', 'м²', 'physical'), ('0.0%', '%', 'percent')])
def test_physical_and_percent_hints_stay_unknown(source, fmt, unit, kind):
    edit_book(source, formats=(fmt,) * 3, unit_header='Единица измерения', units=(unit,) * 4)
    diag = raw()['unit_observability']; assert_unknown(diag)
    assert 'nonmonetary_format_hint' in diag['gaps'] and 'nonmonetary_row_unit' in diag['gaps']
    assert diag['format_groups'][0]['hints'][0]['kind'] == kind


def test_mixed_formats_and_row_labels_are_not_a_shared_money_unit(source):
    edit_book(source, formats=('0"руб."', '0"тыс. руб."', '0"руб."'), unit_header='Ед.изм.',
              units=('руб.', 'тыс. руб.', 'руб.', 'тыс. руб.'))
    diag = raw()['unit_observability']; assert_unknown(diag)
    assert len(diag['format_groups']) == 2
    assert 'mixed_format_groups' in diag['gaps'] and 'mixed_row_unit_tokens' in diag['gaps']


def test_unknown_format_and_row_literals_are_hash_only(source):
    fmt = '0"PRIVATE-FORMAT-SECRET-DO-NOT-EXPORT"'
    edit_book(source, formats=(fmt,) * 3, unit_header='Ед.изм.', units=('PRIVATE-ROW-UNIT-SECRET',) * 4)
    got = raw(); text = json.dumps(got, ensure_ascii=False)
    assert 'PRIVATE-' not in text
    group, = got['unit_observability']['format_groups']
    assert group['format_sha256'] == hashlib.sha256(fmt.encode()).hexdigest()
    assert group['state'] == 'unknown' and group['code'] == 'unknown_format_literal'
    assert group['hints'] == []
    assert all(s['state'] == 'unknown' and s['value_sha256'] for s in got['unit_observability']['row_unit_samples'])


def test_ambiguous_unit_headers_do_not_export_row_values(source):
    def edit(sheet):
        sheet['E6'] = sheet['F6'] = 'Ед.изм.'
        sheet['E14'] = 'PRIVATE-AMBIGUOUS-UNIT'
    changed(source, edit)
    diag = raw()['unit_observability']; assert_unknown(diag)
    assert diag['unit_header']['state'] == 'ambiguous' and diag['row_unit_samples'] == []
    assert 'PRIVATE-' not in json.dumps(diag)


def test_more_than_four_leaves_preserve_full_raw_source_without_diagnostic_samples(source):
    edit_book(source, count=5)
    got = raw(); diag = got['unit_observability']; assert_unknown(diag)
    assert len(got['rows']) == 5
    assert diag['state'] == 'bounded_incomplete' and diag['available_leaf_count'] == 5
    assert diag['sampled_leaf_count'] == 0 and diag['omitted_leaf_count'] == 5
    assert diag['format_groups'] == [] and diag['cell_samples'] == []


def test_non_ijk_money_columns_preserve_old_rows_and_skip_format_access(source, monkeypatch):
    def edit(sheet):
        for col in (9, 10, 11): sheet.cell(6, col).value = None
        for col, name, value in ((12, 'ИТОГО', 40), (13, 'ФАКТ', 20), (14, 'ПЛАН', 20)):
            sheet.cell(6, col, name); sheet.cell(14, col, value)
    changed(source, edit)
    monkeypatch.setattr(ReadOnlyCell, 'number_format', property(lambda cell: pytest.fail('out-of-scope format access')))
    got = raw(); diag = got['unit_observability']
    assert got['rows'][0]['cells']['total']['cell'] == 'L14'
    assert diag['gaps'] == ['money_columns_outside_diagnostic_scope']
    assert diag['cell_samples'] == []


def test_wide_non_ijk_rows_are_not_retained_for_a_skipped_diagnostic(source, monkeypatch):
    def edit(sheet):
        for column in (9, 10, 11):
            sheet.cell(6, column).value = None
        for column, name, value in ((998, 'ИТОГО', 40), (999, 'ФАКТ', 20), (1000, 'ПЛАН', 20)):
            sheet.cell(6, column, name); sheet.cell(14, column, value)
    changed(source, edit)
    data = (source[0] / 'finance.xlsx').read_bytes()
    legacy_rows, legacy_headers, legacy_units = proof._cells(data)
    original, calls = hints.observe, []
    def observed(leaves, row_cells, header_cells, columns, currency):
        calls.append(True)
        assert columns == {'total': 997, 'fact': 998, 'plan': 999}
        assert row_cells == {}
        return original(leaves, row_cells, header_cells, columns, currency)
    monkeypatch.setattr(hints, 'observe', observed)
    monkeypatch.setattr(ReadOnlyCell, 'number_format', property(lambda cell: pytest.fail('out-of-scope style access')))
    rows, headers, units = proof._cells(data, observe_units=True)
    diag = units.pop('_observability')
    assert calls == [True]
    assert (rows, headers, units) == (legacy_rows, legacy_headers, legacy_units)
    assert rows[0]['cells']['total']['cell'] == 'ALJ14'
    assert diag['gaps'] == ['money_columns_outside_diagnostic_scope'] and diag['cell_samples'] == []


def test_bad_number_format_property_is_per_cell_unknown_not_workbook_failure(source, monkeypatch):
    edit_book(source)
    def fail(cell):
        raise ValueError('PRIVATE-PROPERTY-EXCEPTION')
    monkeypatch.setattr(ReadOnlyCell, 'number_format', property(fail))
    got = raw(); diag = got['unit_observability']; assert_unknown(diag)
    assert len(got['rows']) == 4 and len(diag['cell_samples']) == 12
    assert diag['format_groups'] == [] and 'number_format_unavailable' in diag['gaps']
    assert 'PRIVATE-' not in json.dumps(got)


def test_diagnostic_group_limit_is_typed_without_changing_cached_cells(source, monkeypatch):
    edit_book(source, formats=('0"руб."', '0.0"руб."', '0"руб."'))
    monkeypatch.setattr(hints, 'MAX_FORMAT_GROUPS', 1)
    got = raw(); diag = got['unit_observability']
    assert len(got['rows']) == 4 and diag['state'] == 'bounded_incomplete'
    assert diag['gaps'] == ['format_group_limit'] and diag['sampled_leaf_count'] == 0


def test_long_format_is_hash_only_with_an_explicit_format_bound(source):
    fmt = '0"' + 'PRIVATE-LONG-LITERAL-' * 30 + '"'
    edit_book(source, formats=(fmt,) * 3)
    got = raw(); diag = got['unit_observability']; assert_unknown(diag)
    assert diag['state'] == 'bounded_incomplete' and 'format_character_limit' in diag['gaps']
    assert len(got['rows']) == 4 and 'PRIVATE-' not in json.dumps(got)


def test_conditional_format_remains_a_display_ambiguity(source):
    edit_book(source, formats=('[>=1000]0.0"руб.";0.0"руб."',) * 3)
    diag = raw()['unit_observability']; assert_unknown(diag)
    assert diag['format_groups'][0]['display_scale_ambiguous']


def test_observability_reads_no_additional_workbook_rows_or_columns(source, monkeypatch):
    edit_book(source, unit_header='Ед.изм.')
    data = (source[0] / 'finance.xlsx').read_bytes()
    original, calls = ReadOnlyWorksheet.iter_rows, []
    def seen(sheet, *args, **kwargs):
        calls.append((sheet.title, args, dict(kwargs)))
        return original(sheet, *args, **kwargs)
    monkeypatch.setattr(ReadOnlyWorksheet, 'iter_rows', seen)
    legacy = proof._cells(data)
    old_calls = list(calls); calls.clear()
    observed = proof._cells(data, observe_units=True)
    observed[2].pop('_observability')
    assert calls == old_calls and observed == legacy


def test_near_existing_output_budget_omits_diagnostics_and_keeps_old_raw_success(source, monkeypatch):
    edit_book(source)
    first = raw()
    base = {k: v for k, v in first.items() if k != 'unit_observability'}
    old_size = len(json.dumps(base, ensure_ascii=False, allow_nan=False).encode())
    monkeypatch.setattr(proof, 'MAX_OUTPUT', old_size + 16)
    second = raw()
    assert 'unit_observability' not in second
    assert second['rows'] == base['rows'] and second['source'] == base['source']
    assert second['unit_evidence'] == base['unit_evidence'] and second['state'] == base['state']
    assert len(json.dumps(second, ensure_ascii=False, allow_nan=False).encode()) <= proof.MAX_OUTPUT


def test_diagnostic_byte_limit_never_rejects_an_old_valid_raw_projection(source, monkeypatch):
    edit_book(source)
    monkeypatch.setattr(hints, 'MAX_DIAGNOSTIC_BYTES', 1)
    got = raw()
    assert len(got['rows']) == 4 and 'unit_observability' not in got


def test_only_saved_scope_opts_into_observability(source):
    data = (source[0] / 'finance.xlsx').read_bytes()
    legacy_rows, legacy_headers, legacy_units = proof._cells(data)
    observed_rows, observed_headers, observed_units = proof._cells(data, observe_units=True)
    assert observed_units.pop('_observability')
    assert (legacy_rows, legacy_headers, legacy_units) == (observed_rows, observed_headers, observed_units)
    historical = proof.capture(PROJECT, '2026-11-13', runtime=RUNTIME)
    assert 'unit_observability' not in historical and '_observability' not in historical['unit_evidence']
