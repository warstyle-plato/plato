"""Incremental KS uploads retain detail independently of the latest summary."""
from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_closing_summary_contracts import closing_book
from test_ledger_merged_cost_fields import add_caches
from test_contracts_archive_union import FIRST, MIDDLE, SECOND, PROJECT, by_number, grown
from test_contracts_from_cumulative_headers import ARCHIVE_READER, archive, context, ks  # noqa: F401


def summary(number, completed=400):
    wb = openpyxl.load_workbook(io.BytesIO(closing_book(
        reference=f'Договор № {number} от 01.01.2026', done=completed)))
    ws = wb.active
    ws['A1'], ws['A3'] = 'ООО «Заказчик»', 'ООО «Подрядчик»'
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), {'C8': 1500, 'F8': completed})


def save(day, *files):
    return ledgers.store_archive(PROJECT, archive(list(files)), day)


def test_new_summary_keeps_historical_detail_and_updates_only_its_money_source(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    old = save(FIRST, ('A.xlsx', ks()), ('B.xlsx', ks(number='B-24')))
    before = by_number(contracts.build(PROJECT, FIRST, include_history=False))
    new = save(SECOND, ('A.xlsx', grown()), ('Summary-A.xlsx', summary('A-12', 500)),
               ('Summary-B.xlsx', summary('B-24', 400)))
    rows = by_number(contracts.build(PROJECT, SECOND))
    assert set(rows) == {'A-12', 'B-24'}
    assert {k: row['id'] for k, row in rows.items()} == {k: row['id'] for k, row in before.items()}
    assert rows['A-12']['completed'] == 500  # Never old400 + new500 + summary500.
    row = rows['B-24']
    assert row['source_kind'] == 'cumulative' and row['physical_items']
    assert row['completed'] == 400
    assert row['source_date'] == FIRST and row['source_snapshot_id'] == old['snapshot_id']
    assert row['summary_source_date'] == SECOND
    assert row['summary_source_snapshot_id'] == new['snapshot_id']
    assert row['progress']['observation_date'] == SECOND  # New denominator is not an old observation.
    assert row['amount'] == 1500 and row['progress']['ratio'] == pytest.approx(400/1500)
    assert row['financial_sources'][0]['source_date'] == SECOND
    assert all(item['snapshot_date'] == FIRST for item in row['physical_items'])


def test_a_new_month_does_not_cancel_the_preceding_month(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Same-name.xlsx', ks(period='jan')))
    old, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    save(SECOND, ('Same-name.xlsx', ks(period='feb')))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['id'] == old['id']
    assert row['completed'] == 400
    assert len(row['physical_items']) == len(old['physical_items'])
    item = next(x for x in row['physical_items'] if x['position'] == '1.1')
    assert item['completed_quantity'] == 4
    assert {p['date_end'] for p in item['periods']} == {'2026-01-31', '2026-02-28'}
    assert {p['selected_source']['source_date'] for p in item['periods']} == {FIRST, SECOND}
    assert len(item['history_sources']) == 2
    earlier, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    assert earlier['completed'] == 200


def test_a_summary_only_upload_does_not_refresh_dates_of_physical_work(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Detail.xlsx', ks()))
    save(SECOND, ('Summary.xlsx', summary('A-12')))
    row, = contracts.build(PROJECT, SECOND)['rows']
    assert row['physical_items'][0]['snapshot_date'] == FIRST
    assert row['physical_items'][0]['quantity_date'] == '2026-02-28'
    assert row['summary_source_date'] == SECOND
    assert 'сводн' in row['carried_from_archive']['text'].lower()
    assert 'этого договора нет' not in row['carried_from_archive']['text'].lower()


def test_historical_periods_survive_a_later_partial_revision(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Full.xlsx', ks()))
    save(SECOND, ('Only-January.xlsx', ks(period='jan')))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['completed'] == 400
    item = next(x for x in row['physical_items'] if x['position'] == '1.1')
    assert item['completed_quantity'] == 4
    assert len(item['periods']) == 2
    assert not any('прежние листы не добавлены' in note for note in row['warnings'])


@pytest.mark.parametrize('old_date', [None, '03.07.124'])
def test_unknown_contract_date_does_not_duplicate_a_later_dated_contract(context, old_date):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Old.xlsx', ks(date=old_date)))
    save(SECOND, ('New.xlsx', ks()), ('Summary.xlsx', summary('A-12')))
    view = contracts.build(PROJECT, SECOND, include_history=False)
    assert len(view['rows']) == 1
    assert view['rows'][0]['completed'] == 400
    assert any(note.get('source_date') == FIRST and 'не перенесён' in note['reason']
               for note in view['unresolved_sources'])
    retained = next(note for note in view['unresolved_sources'] if note.get('source_date') == FIRST)
    assert len(retained['file_sha256']) == 64
    if old_date:
        assert retained['date_evidence'][0]['binding']['snapshot_id'].startswith(FIRST)


def test_equivalent_unit_spelling_cannot_double_execution(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Old.xlsx', ks()))
    wb = openpyxl.load_workbook(io.BytesIO(ks()))
    wb.active['D9'] = 'м³'
    out = io.BytesIO()
    wb.save(out)
    save(SECOND, ('New.xlsx', out.getvalue()), ('Summary.xlsx', summary('A-12')))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['completed'] == 400
    assert row['completion_ratio'] == pytest.approx(400/1500)


def test_unqualified_summary_cannot_refresh_an_unchanged_statement_percentage(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Old.xlsx', ks()))
    wb = openpyxl.load_workbook(io.BytesIO(summary('A-12')))
    for cell in ['C5', 'C6', 'C7', 'C8']:
        wb.active[cell] = None
    out = io.BytesIO()
    wb.save(out)
    save(SECOND, ('Unpriced-summary.xlsx', add_caches(out.getvalue(), {'F8': 400})))
    row, = contracts.build(PROJECT, SECOND)['rows']
    assert row['amount'] is None
    assert row['progress']['basis'] == 'statement_union'
    assert row['progress']['ratio'] == pytest.approx(400/1020)
    assert row['progress']['observation_date'] == FIRST


def test_a_conflicting_ledger_year_is_not_an_extra_execution(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    wb = openpyxl.load_workbook(io.BytesIO(ks()))
    wb.active['N7'] = '2025 год'  # Its explicit execution periods still name 2026.
    out = io.BytesIO()
    wb.save(out)
    save(FIRST, ('Wrong-year.xlsx', out.getvalue()))
    save(SECOND, ('Current.xlsx', ks()), ('Summary.xlsx', summary('A-12')))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['completed'] is None
    assert any('год' in note for note in row['warnings'])


def test_summary_presence_is_counted_without_hiding_old_detail(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Detail.xlsx', ks()))
    save(SECOND, ('Summary.xlsx', summary('A-12')))
    view = contracts.build(PROJECT, SECOND, include_history=False)
    assert view['counts']['contracts_from_newest_archive'] == 1
    assert view['counts']['contracts_carried'] == 1
    assert contracts.archive_summary(PROJECT, SECOND)['contracts_in_archive'] == 1
    assert contracts.archive_summary(PROJECT, SECOND)['contracts_carried'] == 1


def test_summary_presence_uses_equivalent_legal_form_without_rekeying_the_detailed_card(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    wb = openpyxl.load_workbook(io.BytesIO(ks()))
    wb.active['C2'] = 'Общество с ограниченной ответственностью «Подрядчик», ИНН 1234567890'
    out = io.BytesIO()
    wb.save(out)
    save(FIRST, ('Detail.xlsx', out.getvalue()))
    old, = contracts.build(PROJECT, FIRST, include_history=False)['rows']
    save(SECOND, ('Summary.xlsx', summary('A-12')))
    view = contracts.build(PROJECT, SECOND, include_history=False)
    row, = view['rows']
    assert row['id'] == old['id'] and row['amount'] == 1500
    assert row['summary_source_date'] == SECOND
    assert view['counts']['contracts_from_newest_archive'] == 1
    assert contracts.archive_summary(PROJECT, SECOND)['contracts_in_archive'] == 1


def test_quotes_in_a_work_name_do_not_create_another_execution(context):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    save(FIRST, ('Old.xlsx', ks()))
    wb = openpyxl.load_workbook(io.BytesIO(ks()))
    wb.active['C9'] = '«Устройство стены»'
    out = io.BytesIO()
    wb.save(out)
    save(SECOND, ('New.xlsx', out.getvalue()), ('Summary.xlsx', summary('A-12')))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['completed'] == 400
    assert row['completion_ratio'] == pytest.approx(400/1500)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('disjoint', [False, True])
def test_filling_or_removing_a_header_scope_does_not_prove_an_extra_plan_or_execution(context, reverse, disjoint):
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    files = []
    for index in range(2):
        wb = openpyxl.load_workbook(io.BytesIO(ks(period=('jan' if index == 0 else 'feb'))
                                             if disjoint else ks()))
        if bool(index) != reverse:
            wb.active['A5'], wb.active['B5'] = 'Объект', 'Корпус 1'
        out = io.BytesIO()
        wb.save(out)
        files.append(out.getvalue())
    save(FIRST, ('Old.xlsx', files[0]))
    save(SECOND, ('New.xlsx', files[1]))
    row, = contracts.build(PROJECT, SECOND, include_history=False)['rows']
    assert row['completed'] is None
    assert row['completion_ratio'] is None
    assert all(item['detail_history_state'] == 'unknown' for item in row['physical_items']
               if not item.get('is_group'))
    assert any('Область работ' in note for note in row['warnings'])
