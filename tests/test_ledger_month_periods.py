"""Monthly source headings must survive intake and old saved imports.

These workbooks are synthetic; they exercise the actual parser and register,
not acceptance of the private production documents.
"""
from __future__ import annotations

import io
import json

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import (
    ARCHIVE_READER, context, parsed, provide, rss_contract,
)
from test_monitor_cumulative_ledgers import archive, biff_book, book


def monthly_book(first='Январь', second='Февраль'):
    wb = openpyxl.load_workbook(io.BytesIO(book()))
    ws = wb.active
    ws['B3'] = 'A-12'
    ws['H7'], ws['K7'] = first, second
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.mark.parametrize('first,second', [
    ('Январь', 'Февраль'),
    ('за январь 2026 года', 'за февраль 2026 г.'),
    ('01.2026', '02.2026'),
    ('2026-01-01 — 2026-01-31', '2026-02-01 — 2026-02-28'),
])
def test_month_headings_feed_real_contract_and_physical_percentages(context, first, second):
    provide(context, parsed(('Monthly.xlsx', monthly_book(first, second))), [rss_contract()])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['completed'] == 400
    assert row['completion_ratio'] == .4
    work = row['physical_items'][0]
    assert work['completed_quantity'] == 4
    assert work['completion_ratio'] == .4
    assert [(p['date_start'], p['date_end']) for p in work['periods']] == [
        ('2026-01-01', '2026-01-31'), ('2026-02-01', '2026-02-28'),
    ]


def test_month_does_not_turn_a_partial_month_cut_into_complete_execution(context):
    ledger, = parsed(('Monthly.xlsx', monthly_book()))['ledgers']
    work = contracts._physical(ledger['items'][0], ledger, '2026-02-15')
    assert contracts._cumulative_money([work], [])[0] is None
    assert work['completed_quantity'] is None
    assert work['dated_completed_quantity'] == 2  # January remains known separately.
    assert work['reported_completed_quantity'] is None  # No February total at the cut.


def test_legacy_xls_month_heading_is_a_real_period():
    ledger, = ledgers.parse_archive(archive([('Old.xls', biff_book())]))['ledgers']
    work = contracts._physical(ledger['items'][0], ledger, '2026-02-01')
    assert work['completed_quantity'] == 3 and work['completion_ratio'] == .3
    assert work['periods'][0]['date_end'] == '2026-01-31'


def test_existing_uploaded_monthly_archive_changes_without_reupload_or_disk_mutation(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    context.setattr(contracts, '_read_rss', lambda *_: ([rss_contract()], '2026-11-06', []))
    imported = ledgers.store_archive('Example', archive([('Monthly.xlsx', monthly_book())]),
                                    '2026-03-01', 'Existing.zip')
    root = ledgers._root('Example')
    path = root / (imported['snapshot_id'] + '.json')
    saved = json.loads(path.read_text())
    for ledger in saved['ledgers']:
        ledger['period_dates_known'] = False
        for item in ledger['items']:
            for period in item['periods']:
                period['date_start'] = period['date_end'] = None
    path.write_text(json.dumps(saved, ensure_ascii=False))
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    snapshot = ledgers.latest_snapshot('Example', '2026-03-01')
    assert snapshot['ledgers'][0]['items'][0]['periods'][0]['date_end'] == '2026-01-31'
    row, = contracts.build('Example', '2026-03-01')['rows']
    assert row['completed'] == 400 and row['completion_ratio'] == .4
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    assert snapshot['snapshot_id'] == imported['snapshot_id']


@pytest.mark.parametrize('label,year', [
    ('КС-2 № 1', 2026), ('Количество', 2026), ('Январь', None),
    ('Январь — февраль', 2026), ('Январь 2025 / 2026', 2026),
    ('13.2026', 2026), ('31.02.2026', 2026),
    ('15 января 2026', 2026), ('31.02.2026 февраль', 2026),
    ('январь: 01.02.2026 — 28.02.2026', 2026),
])
def test_ambiguous_or_missing_dates_stay_unknown(label, year):
    assert ledgers._period_dates(label, year=year) == (None, None)


def test_month_heading_uses_calendar_boundaries_in_leap_year():
    assert ledgers._period_dates('февраль', year=2024) == ('2024-02-01', '2024-02-29')


def test_old_import_cache_does_not_share_mutations_or_skip_original_hash(context):
    imported = ledgers.store_archive('Example', archive([('Monthly.xlsx', monthly_book())]),
                                    '2026-03-01', 'Cache-check.zip')
    root = ledgers._root('Example')
    path = root / (imported['snapshot_id'] + '.json')
    saved = json.loads(path.read_text())
    saved.pop('parser_schema')
    path.write_text(json.dumps(saved, ensure_ascii=False))
    original_json = path.read_bytes()
    with ledgers._PARSE_CACHE_LOCK:
        ledgers._PARSE_CACHE.clear()
    calls = []
    parser = ledgers.parse_archive

    def count_parse(*args, **kwargs):
        calls.append(1)
        return parser(*args, **kwargs)

    context.setattr(ledgers, 'parse_archive', count_parse)
    first = ledgers.latest_snapshot('Example', '2026-03-01')
    first['ledgers'][0]['items'][0]['plan_quantity'] = -999
    second = ledgers.latest_snapshot('Example', '2026-03-01')
    assert second['ledgers'][0]['items'][0]['plan_quantity'] == 10
    assert len(calls) == 1 and path.read_bytes() == original_json
    raw = root / (imported['snapshot_id'] + '.zip')
    raw.write_bytes(raw.read_bytes() + b'changed')
    with pytest.raises(ledgers.LedgerProblem, match='отпечатком'):
        ledgers.latest_snapshot('Example', '2026-03-01')
