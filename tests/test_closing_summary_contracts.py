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


def closing_book(*, reference='Дог. № 04/01.26-Т от 05.03.26', zero=False,
                 split_date=False, repeat=False):
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
               None if zero else dt.date(2026, 3, 31), 0 if zero else 250])
    ws.append(['Продолжение', 'от 05.03.26' if split_date else 'ДС № 1 от 06.03.26',
               200, None if zero else 2, None if zero else dt.date(2026, 4, 30), 0 if zero else 50])
    ws.append(['Дополнительные работы', 'Договор № 04/01.26-Т от 05.03.26' if repeat else None,
               300])
    ws.append([None, None, '=SUM(C5:C7)', None, None, '=SUM(F5:F7)'])
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), {'C8': 1500, 'F8': 0 if zero else 300})


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

