"""Saved payment values explain incomplete rows without changing any cash."""
import copy
import datetime as dt
import io
import json
import re
import zipfile

import openpyxl
import pytest
from fastapi.encoders import jsonable_encoder

import developaid_actuals as actuals
import developaid_funding_reconciliation as reconciliation
import developaid_management_report as report
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_management_report_model import _rss_book


DAY = dt.date(2026, 10, 31)
ESTIMATE = {'rows': [dict(code='2', parent=''), dict(code='2.6', parent='2'),
                     dict(code='4', parent=''), dict(code='4.1', parent='4')]}


def payment(amount, **changes):
    result = {'B': 'Учебный подрядчик', 'C': 'Д-1', 'D': dt.date(2024, 1, 2),
              'E': 'Корпус 1', 'F': 'Оплата работ', 'G': '2.6',
              'I': DAY, 'J': amount, 'K': 'Заемные средства'}
    result.update(changes)
    return result


def native_book(path, rows, cached=None):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = actuals._PAYMENTS_SHEET
    for number, values in rows.items():
        sheet.cell(number, 1, number - 9)
        for col, value in values.items():
            sheet[f'{col}{number}'] = value
    data = io.BytesIO()
    book.save(data)
    book.close()
    if cached:
        output = io.BytesIO()
        with zipfile.ZipFile(data) as source, zipfile.ZipFile(output, 'w') as target:
            for item in source.infolist():
                raw = source.read(item.filename)
                if item.filename == 'xl/worksheets/sheet1.xml':
                    text = raw.decode()
                    for cell, value in cached.items():
                        text, count = re.subn(r'(<c r="'+cell+r'"[^>]*><f>[^<]+</f><v>)</v>',
                                              lambda m: m[1]+str(value)+'</v>', text)
                        assert count == 1
                    raw = text.encode()
                target.writestr(item, raw)
        data = output
    path.write_bytes(data.getvalue())
    return path


def bounds():
    return {'start': DAY.replace(day=1), 'end': DAY}


def test_native_saved_values_keep_zero_refund_unknown_and_formula_observations(tmp_path):
    path = native_book(tmp_path/'payments.xlsx', {
        10: payment(100), 11: payment(0), 12: payment(-25),
        13: payment('не проведено'), 14: payment(None), 15: payment(True),
        16: payment('=SUM(40,2)'), 17: payment('=SUM(100,-25)'),
        18: {'H': '=IFERROR(VLOOKUP(G18,A1:B2,2,FALSE),0)'},
        19: {'H': 0, 'K': 'Заемные средства'},
        20: payment(None, I=DAY+dt.timedelta(days=1)),
        21: payment(None, G='4.1'),
        22: payment(dt.datetime(2026, 10, 31, 12, 30)),
    }, cached={'J17': 75, 'H18': 0})
    strict = actuals.read_payments(path, include_incomplete=True, include_cell_metadata=True)
    rows = {row['source_row']: row for row in strict['rows']}
    assert 18 not in rows  # Existing1192 template filter is preserved.
    assert [rows[n]['amount'] for n in [10, 11, 12, 17]] == [100, 0, -25, 75]
    assert all(rows[n]['amount'] is None for n in [13, 14, 15, 16, 19, 20, 21, 22])
    assert strict['total'] is None
    assert rows[13]['amount_cell']['raw_value'] == 'не проведено'
    assert rows[15]['amount_cell']['raw_type'] == 'bool'
    assert rows[15]['amount_cell']['raw_value'] is True
    assert rows[14]['amount_cell']['state'] == rows[16]['amount_cell']['state'] == 'missing_saved_value'
    assert rows[14]['amount_cell']['raw_type'] == rows[16]['amount_cell']['raw_type'] == 'NoneType'
    assert rows[17]['amount_cell']['raw_value'] == 75
    assert rows[22]['amount_cell']['raw_type'] == 'datetime'
    assert rows[22]['amount_cell']['raw_value'] == '2026-10-31T12:30:00'
    assert actuals.read_payments(path)['total'] == 150
    paid = dashboard._paid_in_chapters(path, ESTIMATE, ('2',), cut=DAY)
    sums = report._sums(strict['rows'], bounds(), dashboard.payment_in_chapters(ESTIMATE, ('2',)))
    assert paid['total'] is sums['total'] is None
    assert paid['observed_total'] == sums['known_part']['total'] == 150
    assert paid['observed_count'] == 4
    assert [row['source_row'] for row in paid['incomplete_rows']] == [13, 14, 15, 16, 19, 22]
    assert [row['source_row'] for row in sums['incomplete_rows']] == [13, 14, 15, 16, 19, 22]
    for issue in paid['incomplete_rows'] + sums['incomplete_rows']:
        assert issue['sheet'] == actuals._PAYMENTS_SHEET
        assert issue['amount_cell']['coordinate'] == 'J'+str(issue['source_row'])
    first = paid['incomplete_rows'][0]
    assert first['fields'] == ['amount']
    assert first['payment_context'] == dict(contractor='Учебный подрядчик', contract='Д-1',
        contract_date='2024-01-02', object='Корпус 1', purpose='Оплата работ',
        estimate_code='2.6', date='2026-10-31', source='Заемные средства', truncated_fields=[])
    json.dumps(jsonable_encoder(paid), allow_nan=False)
    json.dumps(jsonable_encoder(sums), allow_nan=False)


def test_reader_default_shapes_and_one_cached_read_are_unchanged(tmp_path, monkeypatch):
    path = native_book(tmp_path/'cache.xlsx', {10: payment(100), 11: payment(None), 12: payment(-25)})
    original = actuals._sheet
    reads = []
    def source(*args, **kwargs):
        reads.append(args[1])
        yield from original(*args, **kwargs)
    monkeypatch.setattr(actuals, '_sheet', source)
    legacy = actuals.read_payments(path)
    strict = actuals.read_payments(path, include_incomplete=True)
    rich = actuals.read_payments(path, include_incomplete=True, include_cell_metadata=True)
    assert reads == [actuals._PAYMENTS_SHEET]
    expected = {'contractor', 'contract', 'contract_date', 'object', 'purpose', 'estimate_code',
                'article_name', 'date', 'amount', 'source', 'own_funds'}
    assert all(set(row) == expected for row in legacy['rows'])
    assert all(set(row) == expected | {'source_row'} for row in strict['rows'])
    plain = copy.deepcopy(rich)
    for row in plain['rows']:
        row.pop('amount_cell')
    assert plain == strict
    rich['rows'][1]['amount_cell']['raw_value'] = 'changed consumer copy'
    fresh = actuals.read_payments(path, include_incomplete=True, include_cell_metadata=True)
    assert fresh['rows'][1]['amount_cell']['raw_value'] is None
    assert fresh['rows'][1]['amount_cell']['state'] == 'missing_saved_value'
    assert actuals.read_payments(path) == legacy
    assert reads == [actuals._PAYMENTS_SHEET]


@pytest.mark.parametrize('value,raw_type,raw,state', [
    (None, 'NoneType', None, 'missing_saved_value'),
    ('', 'str', '', 'empty_saved_string'),
    (True, 'bool', True, 'saved_value'),
    (dt.date(2026, 10, 31), 'date', '2026-10-31', 'saved_value'),
    (dt.datetime(2026, 10, 31, 12, 30), 'datetime', '2026-10-31T12:30:00', 'saved_value'),
    (float('nan'), 'float', 'NaN', 'non_finite_saved_value'),
    (float('inf'), 'float', 'Infinity', 'non_finite_saved_value'),
    (-float('inf'), 'float', '-Infinity', 'non_finite_saved_value'),
])
def test_raw_saved_scalar_metadata_is_strict_json(value, raw_type, raw, state):
    observed = actuals._payment_amount_cell(value, 953)
    assert observed == dict(coordinate='J953', raw_type=raw_type, state=state, raw_value=raw, truncated=False)
    assert json.loads(json.dumps(observed, allow_nan=False)) == observed


def test_large_integer_observation_is_bounded_without_stringifying_the_entire_integer():
    observed = actuals._payment_amount_cell(10**10_000, 953)
    assert observed['raw_type'] == 'int' and observed['truncated'] is True
    assert isinstance(observed['raw_value'], str) and len(observed['raw_value']) <= 256
    json.dumps(observed, allow_nan=False)


def test_context_is_bounded_literal_json_and_old_rows_do_not_invent_raw_cells(tmp_path):
    imported = '<img src=x onerror="alert(1)">'
    path = native_book(tmp_path/'bounded.xlsx', {10: payment(imported*50, B=imported*50)})
    row = actuals.read_payments(path, include_incomplete=True, include_cell_metadata=True)['rows'][0]
    issue = actuals.payment_issue_context(row)
    assert issue['amount_cell']['raw_value'] == (imported*50)[:256]
    assert issue['amount_cell']['truncated'] is True
    assert issue['payment_context']['contractor'] == (imported*50)[:512]
    assert issue['payment_context']['truncated_fields'] == ['contractor']
    assert json.loads(json.dumps(issue, allow_nan=False)) == issue
    old = actuals.payment_issue_context(dict(source_row=953, amount=None))
    assert old['amount_cell']['state'] == 'not_captured'
    assert old['amount_cell']['raw_type'] is None


def test_gap_dedup_preserves_context_when_another_chapter_has_an_old_projection(tmp_path):
    path = native_book(tmp_path/'dedup.xlsx', {10: payment('не проведено')})
    issue = dashboard._paid_in_chapters(path, ESTIMATE, ('2',), cut=DAY)['incomplete_rows'][0]
    source = {'payments': {'1': [issue], '2': [dict(source_row=10, fields=['amount'])]}}
    before = copy.deepcopy(source)
    gaps = reconciliation._payment_gaps(source)
    assert len(gaps) == 1 and gaps[0] == issue
    assert source == before
    gaps[0]['amount_cell']['raw_value'] = 'changed output'
    assert source == before


def test_existing_funding_response_keeps_payment_context_through_bank_calculation(tmp_path, monkeypatch):
    project = 'Synthetic payment provenance'
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    book = openpyxl.load_workbook(io.BytesIO(_rss_book([(DAY, 100, '2.2.1.4'), (DAY, None, '2.2.1.4')])))
    estimate = book[actuals._ESTIMATE_SHEET]
    estimate.delete_rows(10, estimate.max_row - 9)
    for line, code in enumerate(['1', '2', '2.2', '2.2.1', '2.2.1.4', '3'], 10):
        estimate.cell(line, 1, code)
        estimate.cell(line, 4, 'Учебная статья '+code)
        estimate.cell(line, 5, 1_000_000 if code.startswith('2') else 0)
    estimate.cell(17, 4, 'Всего инвестиционные расходы')
    estimate.cell(17, 5, 1_000_000)
    sheet = book[actuals._PAYMENTS_SHEET]
    for number in [10, 11]:
        for column, value in [(2, 'Учебный подрядчик'), (3, 'Д-1'), (4, dt.date(2024, 1, 2)),
                              (5, 'Корпус 1'), (6, 'Оплата работ'), (11, 'Заемные средства')]:
            sheet.cell(number, column, value)
    data = io.BytesIO(); book.save(data)
    monitor.store_estimate(project, data.getvalue(), DAY.isoformat())
    got = report.funding(project, 'week', DAY, dashboard={'funding': {'known': False, 'reason': 'No synthetic finance'}})
    issue = got['draws']['incomplete_rows'][0]
    assert issue['source_row'] == 11 and issue['fields'] == ['amount']
    assert issue['payment_context']['contract'] == 'Д-1'
    assert issue['amount_cell']['coordinate'] == 'J11'
    assert issue['amount_cell']['state'] == 'missing_saved_value'
    assert got['draws']['total'] is None and got['draws']['known_part']['total'] == 100
    bank = got['limit']['bank_observations']['calculation']
    assert bank['paid_at_cut'] == 100 and bank['partial']
    assert bank['missing_payment_rows'][0]['amount_cell'] == issue['amount_cell']
    assert bank['missing_payment_rows'][0]['payment_context'] == issue['payment_context']
    json.dumps(jsonable_encoder(got), allow_nan=False)
