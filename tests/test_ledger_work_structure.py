"""Source hierarchy and labelled labour budgets survive KS intake."""
from __future__ import annotations

import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import context, provide
from test_monitor_cumulative_ledgers import archive


def structured_book(*, direct=True, missing_plan=False, bad_parts=False, bad_date=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Заказчик', None, 'ООО Учебный заказчик'])
    ws.append(['Подрядчик', None, 'ООО Учебный исполнитель'])
    ws.append(['Договор', 'A-12'])
    ws.append(['Дата', '02.06.125' if bad_date else '2025-06-02'])
    ws.append(['Объект', 'Технический объект'])
    ws.append(['№', 'Позиция', 'Наименование работ', 'Ед. изм.', 'Кол-во',
               'Цена за единицу работ', 'Цена за единицу работ', 'Цена за единицу работ (ВСЕГО)',
               None, None, 'Сметная (договорная) стоимость', 'Выполнено работ'])
    ws['F7'], ws['I7'], ws['L7'], ws['O7'] = ('Стоимость за единицу с учетом НДС',
        'Стоимость итого, с НДС', 'КС-2 №1', '2026 год')
    for col, text in {6:'Материалы',7:'СМР',12:'Количество',13:'Стоимость',
                      15:'Количество',16:'Стоимость'}.items():
        ws.cell(8, col, text)
    if direct:
        ws['I8'], ws['J8'] = 'Материалы и оборудование', 'Работа (СМР/ПНР)'
    ws.append([1, '1', 'Корпус 1'])
    ws.append([2, '1.1', 'Монтаж оболочки'])
    ws.append([3, '1.1.1', 'Этаж 2'])
    ws.append([4,'1.1.1.1','Монтаж элемента','м2',None if missing_plan else 10,
               7,3,10,70,31 if bad_parts else 30,100,4,40,40,4,40])
    ws.append([5,'1.1.2','Этаж 3'])
    ws.append([6,'1.1.2.1','Монтаж элемента','м2',20,5,5,10,100,100,200,10,100,100,10,100])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def parsed_book(**options):
    result = ledgers.parse_archive(archive([('Structured.xlsx', structured_book(**options))]))
    result.update(taken_at='2026-11-06', snapshot_id='test')
    return result


@pytest.mark.parametrize('label', ['Стоимость', 'Общая стоимость работ, с НДС'])
def test_planned_total_label_in_lower_header_is_not_lost(label):
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    ws = wb.active
    ws['I7'] = None
    ws['K6'] = None
    ws['K7'] = label
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    assert [item['planned_amount'] for item in ledger['items']] == [100, 200]
    assert ledger['items'][0]['source']['planned_amount_cell'] == 'K12'


def test_unit_price_never_becomes_planned_position_cost():
    wb = openpyxl.load_workbook(io.BytesIO(structured_book(direct=False)))
    ws = wb.active
    ws['I7'] = None
    ws['K6'] = 'Стоимость за единицу измерения'
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    assert ledger['items'][0]['planned_amount'] is None
    assert ledger['source_complete'] is False


@pytest.mark.parametrize('direct,method', [(True,'labelled_subtotals'),
                                         (False,'quantity_times_labelled_unit_price')])
def test_complete_source_hierarchy_and_explicit_labour_weights(direct, method):
    ledger, = parsed_book(direct=direct)['ledgers']
    first, second = ledger['items']
    assert first['scope'] == 'Корпус 1 · Этаж 2'
    assert second['scope'] == 'Корпус 1 · Этаж 3'
    assert [x['name'] for x in first['section_path']] == ['Корпус 1','Монтаж оболочки','Этаж 2']
    assert [x['source']['row'] for x in first['section_path']] == [9,10,11]
    assert first['parent_row'] == 11
    assert first['planned_work_amount'] == 30 and first['planned_material_amount'] == 70
    assert first['planned_cost_method'] == method
    assert first['planned_work_amount_basis'] == 'with_vat'
    assert first['planned_amount_basis'] == 'with_vat'  # Lower, multi-row cost caption.
    assert ledger['source_complete'] and ledger['unread_rows_count'] == 0
    assert ledger['object_scope'] == 'Технический объект'
    assert ledger['scope_evidence']['object_scope'][0]['source']['cell'] == 'B5'


def test_missing_plan_row_is_kept_and_does_not_gain_zero_or_percentage():
    ledger, = parsed_book(missing_plan=True)['ledgers']
    assert len(ledger['items']) == 2
    first = ledger['items'][0]
    assert first['plan_quantity'] is None and first['completed_quantity'] == 4
    assert ledger['source_complete'] is False and ledger['incomplete_rows_count'] == 1
    physical = contracts._physical(first, ledger, '2026-11-06')
    assert physical['reported_completion_ratio'] is None


def test_bad_explicit_subtotal_cannot_be_hidden_by_a_matching_unit_rate():
    ledger, = parsed_book(bad_parts=True)['ledgers']
    item = ledger['items'][0]
    assert item['planned_work_amount'] is None
    assert item['planned_material_amount'] is None
    assert any('не сходятся' in warning for warning in item['warnings'])


def test_known_contract_and_quantities_are_not_dropped_for_unparsed_date(context):
    snapshot = parsed_book(bad_date=True)
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    row, = view['rows']
    assert row['contract_date'] is None  # No guessed replacement for the source year.
    assert row['contract_identity_kind'] == 'source_header_date_unverified'
    assert row['reported_performance_sources'][0]['completion_ratio'] == pytest.approx(140/300)
    assert len(row['physical_items']) == 2
    assert view['unresolved_sources'][0]['included_in_register'] is True
    assert contracts._identity(row) is None and contracts._source_identity(row)


@pytest.mark.parametrize('annual', [0, 5])
def test_future_year_never_becomes_current_zero_or_percentage(annual):
    ledger, = parsed_book()['ledgers']
    ledger['period_year'] = 2027
    item = dict(ledger['items'][0], completed_quantity=annual)
    view = contracts._physical(item, ledger, '2026-11-06')
    assert view['future_periods_excluded'] is True
    assert view['completed_quantity'] is None and view['reported_completed_quantity'] is None
    assert view['completion_ratio'] is None and view['reported_completion_ratio'] is None
