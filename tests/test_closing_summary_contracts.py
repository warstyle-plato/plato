"""Closing-summary contracts retain explicit identities and monetary source scope."""
from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_ledger_merged_cost_fields import add_caches
from test_monitor_cumulative_ledgers import archive
from test_contracts_from_cumulative_headers import context, provide
from test_contracts_from_cumulative_headers import ks


def closing_book(*, reference='Дог. № 04/01.26-Т от 05.03.26', zero=False,
                 split_date=False, repeat=False, done=300):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Закрытие'
    ws.append(['ООО «Учебный заказчик»'])
    ws.append([])
    # A reference in a party heading does not start a contract or keep the prior party.
    ws.append(['ООО «Учебный исполнитель»', reference])
    ws.append(['Вид работ', '№ договора/ доп.соглашения, дата', 'Сумма договора, с НДС',
               '№ КС', 'Дата КС', 'Сумма по КС, с НДС'])
    if split_date:
        reference = 'Дог. № 04/01.26-Т'
    ws.append(['Работы', reference, 1000, None if zero else 1,
               None if zero else dt.date(2026, 3, 31), 0 if zero else done-50])
    ws.append(['Продолжение', 'от 05.03.26' if split_date else 'ДС № 1 от 06.03.26',
               200, None if zero else 2, None if zero else dt.date(2026, 4, 30), 0 if zero else 50])
    ws.append(['Дополнительные работы', 'Договор № 04/01.26-Т от 05.03.26' if repeat else None,
               300])
    ws.append([None, None, '=SUM(C5:C7)', None, None, '=SUM(F5:F7)'])
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), {'C8': 1500, 'F8': 0 if zero else done})


def parse_closing(**options):
    result = ledgers.parse_archive(archive([('Closing.xlsx', closing_book(**options))]))
    return result['summary_contracts']


@pytest.mark.parametrize('label', [
    'Договор № 04/01.26-Т от 05.03.26',
    'Дог. № 04/01.26-Т от 05.03.26',
    '№ 04/01.26-Т от 05.03.26',
    '04/01.26-Т от 05.03.26',
])
def test_summary_reference_date_is_after_ot_not_inside_contract_number(label):
    row, = parse_closing(reference=label)
    assert row['contract'] == '04/01.26-Т'
    assert row['contract_date'] == '2026-03-05'
    assert row['contractor'] == 'ООО «Учебный исполнитель»'
    assert len(row['acts']) == 2


def test_explicit_date_continuation_does_not_become_a_second_contract():
    row, = parse_closing(split_date=True)
    assert row['contract_date'] == '2026-03-05'
    assert len(row['contract_date_evidence']) == 2


def test_repeated_reference_inside_section_does_not_split_acts_between_copies():
    row, = parse_closing(repeat=True)
    assert len(row['acts']) == 2
    assert row['reported_total']['completed'] == 300


def test_final_declared_total_is_full_contract_price_not_last_added_component():
    row, = parse_closing()
    assert row['reported_total']['planned'] == row['amount'] == 1500
    assert row['amount_versions'][0]['scope'] == 'full_contract'
    assert len(row['reported_amount_versions']) == 2
    assert row['reported_total']['source']['planned_amount_cell'] == 'C8'
    assert row['reported_total']['source']['completed_amount_cell'] == 'F8'


def test_zero_closing_total_is_known_even_without_act_rows():
    row, = parse_closing(zero=True)
    assert row['reported_total']['completed'] == 0
    assert row['acts'] == []


def test_compound_header_date_cannot_be_taken_from_its_number():
    meta = ledgers._metadata([
        ['Заказчик', 'ООО «Заказчик»'], ['Подрядчик', 'ООО «Подрядчик»'],
        ['Договор', 'Договор № 04/01.26-Т от 05.03.26'],
    ])
    assert meta['contract_date'] == '2026-03-05'


def test_contract_number_without_an_explicit_date_stays_undated():
    assert ledgers._contract_day('Договор № 04/01.26-Т') is None


def source_snapshot(**options):
    parsed = ledgers.parse_archive(archive([('Closing.xlsx', closing_book(**options))]))
    return dict(parsed, taken_at='2026-11-06', snapshot_id='current')


def test_summary_only_contract_is_visible_with_its_own_canonical_money_basis(context):
    provide(context, source_snapshot())
    result = contracts.build('Example', '2026-11-06')
    row, = result['rows']
    assert row['source_kind'] == 'closing_summary'
    assert row['amount'] == 1500
    assert row['summary_progress']['ratio'] == row['progress']['ratio'] == .2
    assert row['progress']['basis'] == 'closing_summary_contract'
    assert row['progress']['origin'] == 'closing_summary_statement'
    assert row['progress']['basis_label'] == 'суммы КС-2 по сводной'
    assert row['physical_items'] == [] and row['reported_performance_sources'] == []
    assert row['completed'] is None and row['completion_ratio'] is None
    assert row['risk']['forecast_finish'] is None
    assert result['counts']['contracts_from_cumulative'] == 0
    assert result['counts']['contracts_from_closing_summary_only'] == 1


def test_zero_money_closure_stays_known_without_becoming_zero_natural_volume(context):
    provide(context, source_snapshot(zero=True))
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['progress']['state'] == 'known'
    assert row['progress']['ratio'] == 0
    assert row['progress']['completed'] == 0
    assert row['physical_items'] == []


def test_zero_contract_price_does_not_become_zero_percent(context):
    snapshot = source_snapshot(zero=True)
    source = snapshot['summary_contracts'][0]
    source['reported_total']['planned'] = source['amount'] = 0
    source['amount_versions'][0]['amount'] = 0
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['progress']['ratio'] is None
    assert row['progress']['completed'] == 0
    assert 'положительная' in row['progress']['reason']


def test_summary_percent_dynamics_compares_only_the_same_contract_price(context):
    earlier = source_snapshot(done=150)
    earlier.update(taken_at='2026-10-06', snapshot_id='previous')
    current = source_snapshot()
    context.setattr(contracts, '_archive', lambda project, cut: earlier if cut < '2026-11-06' else current)
    context.setattr(ledgers, 'list_snapshots', lambda _: [{'snapshot_id': 'previous', 'taken_at': '2026-10-06'},
                                                      {'snapshot_id': 'current', 'taken_at': '2026-11-06'}])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['progress']['comparison_state'] == 'comparable'
    assert row['progress']['delta_percent_points'] == pytest.approx(10)
    assert 'денежного закрытия КС-2' in row['progress']['comparison_reason']
    assert not row['observation_forecast']['eligible']
    current['summary_contracts'][0]['reported_total']['planned'] = 1800
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['progress']['comparison_state'] == 'basis_changed'
    assert row['progress']['delta_percent_points'] is None


def test_future_act_in_printed_total_is_not_current_closure(context):
    snapshot = source_snapshot()
    snapshot['summary_contracts'][0]['acts'][0]['date'] = '2027-01-01'
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['progress']['ratio'] is None
    assert 'позже' in row['progress']['reason']


def mixed_snapshot(date='01.01.2026'):
    data = closing_book(reference='Договор № A-12' + (' от '+date if date else ''))
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    ws['A1'], ws['A3'] = 'ООО «Заказчик»', 'ООО «Подрядчик»'
    out = io.BytesIO()
    wb.save(out)
    data = add_caches(out.getvalue(), {'C8': 1500, 'F8': 300})
    parsed = ledgers.parse_archive(archive([('KS.xlsx', ks()), ('Closing.xlsx', data)]))
    return dict(parsed, taken_at='2026-11-06', snapshot_id='current')


def test_exact_summary_enriches_cumulative_row_without_changing_saved_contract_id(context):
    snapshot = mixed_snapshot()
    without_summary = dict(snapshot, summary_contracts=[])
    provide(context, without_summary)
    original, = contracts.build('Example', '2026-11-06')['rows']
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['id'] == original['id']
    assert row['source_kind'] == 'cumulative'
    assert row['amount'] == 1500
    assert row['physical_items']


@pytest.mark.parametrize('date', ['02.01.2026', ''])
def test_different_or_unknown_summary_date_never_rekeys_or_enriches_ks_identity(context, date):
    snapshot = mixed_snapshot(date)
    without_summary = dict(snapshot, summary_contracts=[])
    provide(context, without_summary)
    original, = contracts.build('Example', '2026-11-06')['rows']
    provide(context, snapshot)
    rows = contracts.build('Example', '2026-11-06')['rows']
    assert len(rows) == 2
    row, = [row for row in rows if row['source_kind'] == 'cumulative']
    assert row['id'] == original['id'] and row['amount'] is None
    closing, = [row for row in rows if row['source_kind'] == 'closing_summary']
    assert closing['progress']['ratio'] == .2


@pytest.mark.parametrize('width', [390, 1440])
def test_summary_money_percentage_and_scope_are_visible_in_real_page(context, width):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    provide(context, source_snapshot())
    data = contracts.build('Example', '2026-11-06')
    with browser_page(width) as (page, responses, errors):
        responses.data = data
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRows')).to_contain_text('20%')
        expect(page.locator('#contractsRows')).to_contain_text('КС-2 по сводной')
        expect(page.locator('#contractsRows')).to_contain_text('не физическая готовность')
        expect(page.locator('#contractsMsg')).to_contain_text('Источников договоров: 1')
        page.locator('.contract-open').click()
        expect(page.locator('#contractsDetails')).to_contain_text('Объёмы КС-6а к ней не привязаны')
        assert not errors

