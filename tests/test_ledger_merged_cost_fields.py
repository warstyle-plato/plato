"""A merged money caption is not a pointer to its first component column."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest
import developaid_monitor_ledgers as ledgers
from test_ledger_work_structure import structured_book
from test_monitor_cumulative_ledgers import archive


def cached_book(*, merged_price=True, single_value=False, unrelated=False):
    wb = openpyxl.load_workbook(io.BytesIO(structured_book(direct=False)))
    ws = wb.active
    for row in ws.iter_rows(min_row=6, max_row=8, min_col=9, max_col=11):
        for cell in row:
            cell.value = None
    ws['I6'] = 'Сметная (договорная) стоимость, с НДС'
    ws.merge_cells('I6:K8')
    if merged_price:
        ws['F6'] = 'Цена за единицу измерения, с НДС'
        ws.merge_cells('F6:H8')
    else:
        ws['F7'] = 'Цена за единицу с НДС'
        ws.merge_cells('F7:G7')
    caches = {}
    for row, plan, work, material in [(12, 10, 3, 7), (14, 20, 5, 5)]:
        ws[f'H{row}'] = f'=ROUND(F{row}+G{row},2)'
        ws[f'K{row}'] = f'=ROUND(E{row}*H{row},2)'
        caches[f'H{row}'] = work+material
        caches[f'K{row}'] = plan*(work+material)
        if single_value:
            ws[f'I{row}'] = ws[f'J{row}'] = None
        if unrelated:
            ws[f'K{row}'] = 93
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), caches)


def add_caches(data, values):
    out = io.BytesIO()
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, 'w') as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                xml = ET.fromstring(raw)
                for cell in xml.findall('.//s:c', ns):
                    if cell.get('r') in values and cell.find('s:f', ns) is not None:
                        cell.find('s:v', ns).text = str(values[cell.get('r')])
                raw = ET.tostring(xml)
            target.writestr(name, raw)
    return out.getvalue()


def parse(data):
    return ledgers.parse_archive(archive([('Example.xlsx', data)]))['ledgers'][0]


def test_merged_cost_field_uses_full_formula_total_not_material_component():
    ledger = parse(cached_book())
    assert [item['planned_amount'] for item in ledger['items']] == [100, 200]
    assert [item['source']['planned_amount_cell'] for item in ledger['items']] == ['K12', 'K14']
    assert ledger['source_complete']
    # The unlabelled components do not become labelled work/material prices.
    assert not any(item['planned_cost_split'] for item in ledger['items'])


def test_one_value_in_merged_cost_field_keeps_labelled_unit_price_parts():
    ledger = parse(cached_book(merged_price=False, single_value=True))
    first = ledger['items'][0]
    assert first['planned_amount'] == 100
    assert first['planned_work_amount'] == 30
    assert first['planned_material_amount'] == 70
    assert first['planned_cost_method'] == 'quantity_times_labelled_unit_price'


def test_merged_cost_caption_without_a_total_proof_stays_unknown():
    ledger = parse(cached_book(unrelated=True))
    assert all(item['planned_amount'] is None for item in ledger['items'])
    assert not ledger['source_complete']


def test_explicit_cost_subtotals_before_total_are_not_multiplied_by_quantity():
    data = structured_book(direct=True)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    ws['I7'] = 'Стоимость, руб. с НДС'
    out = io.BytesIO()
    wb.save(out)
    first = parse(out.getvalue())['items'][0]
    assert first['planned_work_amount'] == 30
    assert first['planned_material_amount'] == 70
    assert first['planned_cost_method'] == 'labelled_subtotals'
    assert first['source']['planned_work_amount_cell'] == 'J12'


def test_cross_row_or_external_formula_is_not_a_total_proof():
    assert not ledgers._formula_columns('=E12*H13', 12, '*')
    assert not ledgers._formula_columns("=E12*'Other'!H12", 12, '*')
    assert ledgers._formula_columns('=ROUND(SUM($F12:$G12),2)', 12, '+') == {5, 6}


@pytest.mark.parametrize('reference', ['I6:M8', 'I6:ZZZ8', 'I6:K50'])
def test_invalid_cost_merge_cannot_fall_back_to_its_first_component(reference):
    data = cached_book()
    out = io.BytesIO()
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, 'w') as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == 'xl/worksheets/sheet1.xml':
                xml = ET.fromstring(raw)
                for cell in xml.findall('.//s:mergeCell', ns):
                    if cell.get('ref') == 'I6:K8':
                        cell.set('ref', reference)
                raw = ET.tostring(xml)
            target.writestr(name, raw)
    ledger = parse(out.getvalue())
    assert all(item['planned_amount'] is None for item in ledger['items'])
    assert not ledger['source_complete']


@pytest.mark.parametrize('formula,operator', [
    ('=I12+I12+J12', '+'), ('=SUM(I12,I12,J12)', '+'), ('=E12*E12*H12', '*'),
])
def test_repeated_formula_operands_are_not_deduplicated_into_a_total(formula, operator):
    assert not ledgers._formula_columns(formula, 12, operator)


def test_single_explicit_zero_in_merged_cost_field_remains_a_known_zero():
    ledger = parse(add_caches(cached_book(single_value=True), {'K12': 0, 'K14': 0}))
    assert [item['planned_amount'] for item in ledger['items']] == [0, 0]


def zero_quantity_book(*, actual=0, amount=None, rate_label=True, bad_price=False, other_period=False):
    from test_monitor_cumulative_ledgers import book
    wb = openpyxl.load_workbook(io.BytesIO(book(actual=0 if actual is None else actual)))
    ws = wb.active
    ws['N9'] = actual
    ws['F6'] = 'Цена за единицу работ, руб.' if rate_label else 'Справочное число'
    ws['G9'] = '=E9*F9'
    ws['O9'] = amount
    if not other_period:
        for cell in ('H9', 'I9', 'J9', 'K9', 'L9', 'M9'):
            ws[cell] = 0
    out = io.BytesIO()
    wb.save(out)
    return add_caches(out.getvalue(), {'G9': 999 if bad_price else 1000})


def test_explicit_zero_quantity_and_reconciled_rate_establish_zero_money_with_provenance():
    item = parse(zero_quantity_book())['items'][0]
    assert item['completed_amount'] == 0
    assert item['source']['completed_amount_cell'] == 'O9'
    assert item['completed_amount_derivation'] == {
        'method': 'zero_quantity_times_labelled_unit_price', 'quantity_cell': 'N9', 'quantity': 0,
        'unit_price_cell': 'F9', 'unit_price': 100, 'planned_amount_cell': 'G9'}


@pytest.mark.parametrize('options', [
    {'actual': None}, {'actual': 1}, {'amount': '=1-1'}, {'rate_label': False},
    {'bad_price': True}, {'other_period': True},
])
def test_missing_money_stays_unknown_without_a_zero_quantity_price_proof(options):
    item = parse(zero_quantity_book(**options))['items'][0]
    assert item['completed_amount'] is None
    assert item['completed_amount_derivation'] is None
