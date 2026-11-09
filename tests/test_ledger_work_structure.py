"""Source hierarchy and labelled labour budgets survive KS intake."""
from __future__ import annotations

import io
import copy
import json

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


@pytest.mark.parametrize('unit', [None, 'X', '4'])
def test_work_row_with_unverified_unit_is_kept_and_coverage_is_incomplete(unit):
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    wb.active['D12'] = unit
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    assert len(ledger['items']) == 2
    assert ledger['items'][0]['plan_quantity'] == 10 and ledger['items'][0]['unit'] == ''
    assert ledger['source_complete'] is False and ledger['incomplete_rows_count'] == 1


def test_reparse_appends_recovered_rows_without_retargeting_old_source_indices(context):
    import developaid_schedule_physical as physical
    ledgers.store_archive('Example', archive([('Example.xlsx', structured_book())]), '2026-11-06', 'KS.zip')
    path, = ledgers._root('Example').glob('*.json')
    saved = json.loads(path.read_text())
    saved['parser_schema'] = 1
    saved['ledgers'][0]['items'].pop(0)  # Older parser had omitted the first work.
    path.write_text(json.dumps(saved))
    original = path.read_bytes()
    refreshed = ledgers.read_snapshot('Example', saved['snapshot_id'])
    items = physical._items(refreshed)
    assert items['0:0']['source']['row'] == saved['ledgers'][0]['items'][0]['source']['row']
    assert items['0:0']['plan_quantity'] == 20  # Existing binding still means the second work.
    assert items['0:1']['plan_quantity'] == 10  # Recovered work receives a new id.
    assert path.read_bytes() == original


def test_reparse_refuses_to_retarget_an_old_position_with_no_source_counterpart():
    parsed = parsed_book()
    old = copy.deepcopy(parsed)
    old['ledgers'][0]['items'][0]['source']['row'] = 999
    with pytest.raises(ledgers.LedgerProblem, match='прежняя позиция не найдена'):
        ledgers._preserve_source_indices(old, parsed)


def test_zero_cost_parent_with_independent_execution_is_not_a_heading():
    parent = {'planned_amount': 0, 'plan_quantity': 100,
              'completed_quantity': 50, 'completed_amount': 500}
    child = {'planned_amount': 1000, 'completed_amount': 200}
    assert ledgers.group_basis(parent, [child]) == ''


@pytest.mark.parametrize('parts', [
    {'material_quantity': 25},
    {'completed_work_amount': -500, 'completed_material_amount': 500},
    {'reported_material_quantity': 25},
])
def test_a_net_zero_group_cannot_hide_delivery_or_monetary_corrections(parts):
    parent = {'planned_amount': 0, 'plan_quantity': 100,
              'completed_quantity': 0, 'completed_amount': 0, **parts}
    child = {'planned_amount': 1000, 'completed_amount': 0}
    assert ledgers.group_basis(parent, [child]) == ''


@pytest.mark.parametrize('changes', [{'plan_quantity': 200}, {'completed_quantity': 50}])
def test_matching_money_subtotal_cannot_hide_a_different_natural_plan_or_fact(changes):
    parent = {'unit': 'м²', 'planned_amount': 1000, 'completed_amount': 500,
              'plan_quantity': 100, 'completed_quantity': 20, **changes}
    child = {'unit': 'м²', 'planned_amount': 1000, 'completed_amount': 500,
             'plan_quantity': 100, 'completed_quantity': 20}
    assert ledgers.group_basis(parent, [child]) == ''


@pytest.mark.parametrize('label', ['По разделу Корпус 1', 'В т. ч. НДС (22%)', 'В том числе НДС'])
def test_explicit_summary_labels_do_not_become_unitless_work_positions(label):
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    wb.active.append([7, None, label, None, None, None, None, None, None, None, 300])
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    assert len(ledger['items']) == 2 and ledger['source_complete']


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


@pytest.mark.parametrize('position', [None, 3])
def test_source_bold_empty_heading_scopes_following_flat_or_misnumbered_rows(position):
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    ws = wb.active
    ws['B10'], ws['C10'] = position, 'Монтаж узла'
    ws['C10'].font = openpyxl.styles.Font(bold=True)
    ws['O10'], ws['P10'] = 0, 0
    ws['B12'], ws['B14'] = '1.11', '1.12'
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    heading = next(item for item in ledger['items'] if item['source']['row'] == 10)
    assert heading['is_group'] and heading['group_basis'] == 'empty_structured_heading'
    assert ledger['source_complete']
    assert all(any(node['source']['row'] == 10 for node in item['section_path'])
               for item in ledger['items'] if item['source']['row'] in {12, 14})


def test_integer_numeric_position_is_not_a_fictitious_decimal_child_code():
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    ws = wb.active
    ws['B10'], ws['C10'], ws['O10'], ws['P10'] = 2.0, 'Установка механизмов', 0, 0
    ws['B11'], ws['B12'], ws['B13'], ws['B14'] = '2.1', '2.1.1', '2.2', '2.2.1'
    out = io.BytesIO()
    wb.save(out)
    # BIFF readers expose integer position cells as floats, unlike openpyxl.
    sheet, rows = ledgers._read_workbook('Example.xlsx', out.getvalue())[0]
    rows[9][1] = 2.0
    ledger = ledgers._ledger('Example.xlsx', sheet, rows)
    parent = next(item for item in ledger['items'] if item['source']['row'] == 10)
    assert parent['position'] == '2' and parent['is_group']


def test_bold_monetary_line_with_no_unit_keeps_its_independent_execution():
    wb = openpyxl.load_workbook(io.BytesIO(structured_book()))
    ws = wb.active
    ws['B10'], ws['C10'] = None, 'Основные материалы'
    ws['C10'].font = openpyxl.styles.Font(bold=True)
    ws['K10'], ws['O10'], ws['P10'] = 1000, 0, 500
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    item = next(item for item in ledger['items'] if item['source']['row'] == 10)
    assert not item['is_group'] and item['completed_amount'] == 500
    assert ledger['source_complete'] is False


def test_bad_explicit_subtotal_cannot_be_hidden_by_a_matching_unit_rate():
    ledger, = parsed_book(bad_parts=True)['ledgers']
    item = ledger['items'][0]
    assert item['planned_work_amount'] is None
    assert item['planned_material_amount'] is None
    assert any('не сходятся' in warning for warning in item['warnings'])


def test_reconciled_blank_price_half_is_labelled_as_a_residual_not_a_raw_cell():
    wb = openpyxl.load_workbook(io.BytesIO(structured_book(direct=False)))
    wb.active['F12'], wb.active['G12'] = None, 10
    out = io.BytesIO()
    wb.save(out)
    ledger, = ledgers.parse_archive(archive([('Example.xlsx', out.getvalue())]))['ledgers']
    item = ledger['items'][0]
    assert item['planned_work_amount'] == 100 and item['planned_material_amount'] == 0
    assert item['planned_cost_method'] == 'reconciled_residual'
    assert item['source']['planned_material_amount_cell'] == 'K12 − E12 × G12'


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


def test_register_unions_annual_facts_and_exposes_the_exact_history_percentage(context):
    snapshot = parsed_book()
    old = copy.deepcopy(snapshot['ledgers'][0])
    old['source']['filename'] = 'Previous-year.xlsx'
    old['period_year'] = 2025
    for item in old['items']:
        item['source']['filename'] = 'Previous-year.xlsx'
        item['completed_quantity'] = 1
        item['completed_amount'] = 10
    snapshot['ledgers'].append(old)
    provide(context, snapshot)
    row, = contracts.build('Example', '2026-11-06')['rows']
    union = row['statement_progress']
    assert union['state'] == 'known' and union['source_years'] == [2025, 2026]
    assert union['planned'] == 300 and union['completed'] == 160
    assert union['ratio'] == row['progress']['ratio'] == pytest.approx(160/300)
    assert row['progress']['basis'] == 'statement_union'


@pytest.mark.parametrize('width', [390, 1440])
def test_canonical_source_percentage_and_history_are_visible_in_real_page(context, width):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    snapshot = parsed_book()
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    row, = view['rows']
    assert row['statement_progress']['ratio'] == row['progress']['ratio'] == pytest.approx(140/300)
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        cell = page.locator('#contractsRows td[data-label="Выполнено по накопительным"]')
        expect(cell).to_contain_text('46,7%')
        expect(cell).to_contain_text('По накопительным')
        page.locator('.contract-history summary').click()
        expect(page.locator('.contract-history tbody')).to_contain_text('46,7%')
        assert not errors


def test_proven_source_groups_render_as_headings_without_a_false_zero(context):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    snapshot = parsed_book()
    ledger = snapshot['ledgers'][0]
    child = ledger['items'][0]
    heading = copy.deepcopy(child)
    heading.update(name='Раздел ведомости', is_group=True, group_basis='zero_cost_structured_heading',
                   planned_amount=0, completed_amount=0, completed_quantity=0,
                   source=dict(child['source'], row=11))
    ledger['items'].append(heading)
    provide(context, snapshot)
    view = contracts.build('Example', '2026-11-06')
    with browser_page(390) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        page.locator('.contract-open').click()
        expect(page.locator('.physical-main')).to_have_count(2)
        expect(page.locator('.physical-group')).to_have_count(1)
        expect(page.locator('.physical-group')).to_contain_text('Раздел ведомости')
        assert '%' not in page.locator('.physical-group').inner_text()
        assert not errors


def test_source_cost_forecast_is_labelled_with_its_scope_in_history(context):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    provide(context, parsed_book())
    view = contracts.build('Example', '2026-11-06')
    view['rows'][0]['observation_forecast'] = {
        'eligible': True, 'scope': 'uploaded_statements', 'forecast_finish': '2026-12-01'}
    with browser_page(1440) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        page.locator('.contract-history summary').click()
        expect(page.locator('.contract-history')).to_contain_text('01.12.2026')
        expect(page.locator('.contract-history')).to_contain_text('стоимости позиций ведомостей')
        assert not errors
