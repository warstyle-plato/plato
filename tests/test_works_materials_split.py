"""Works (СМР) and materials supply stay separate in cumulative money (synthetic data)."""
from __future__ import annotations

import io
import re
import zipfile

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_ledgers import archive, book
from test_monitor_contract_register import project, primary_ledger  # noqa: F401  (fixture)


def parsed_ledger(data):
    return ledgers._ledger('Учебная.xlsx', 'Работы',
                           [list(r) for r in openpyxl.load_workbook(io.BytesIO(data)).active.iter_rows(values_only=True)])


def test_split_book_keeps_works_and_materials_money_apart_by_labels():
    ledger = parsed_ledger(book(split=True))
    item = ledger['items'][0]
    # Columns: «Стоимость материалы» 500, «Стоимость СМР» 200; total stays 700.
    assert item['completed_amount'] == 700
    assert (item['completed_work_amount'], item['completed_material_amount']) == (200, 500)
    period = item['periods'][0]
    assert (period['amount'], period['work_amount'], period['material_amount']) == (700, 200, 500)
    assert period['amount_split'] and item['amount_split']


def test_swapped_labels_follow_the_labels_not_the_position():
    wb = openpyxl.load_workbook(io.BytesIO(book(split=True)))
    ws = wb.active
    ws.cell(8, 10, 'Стоимость СМР')
    ws.cell(8, 11, 'Стоимость материалы')
    ws.cell(8, 16, 'Стоимость СМР')
    ws.cell(8, 17, 'Стоимость материалы')
    out = io.BytesIO()
    wb.save(out)
    item = parsed_ledger(out.getvalue())['items'][0]
    assert (item['completed_work_amount'], item['completed_material_amount']) == (500, 200)


def dated_split_book(**cells):
    wb = openpyxl.load_workbook(io.BytesIO(book(split=True)))
    ws = wb.active
    ws['H7'] = 'Выполнение (01.01.2026 - 31.01.2026)'
    for address, value in cells.items():
        ws[address] = value
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def source_row(project, data):
    ledger = parsed_ledger(data)
    project.snapshots.append({'taken_at': '2026-05-01', 'ledgers': [ledger], 'summary_contracts': []})
    row, = contracts.build(project, '2026-05-01')['rows']
    return ledger, row


def test_swapped_labelled_money_reaches_register_without_losing_split(project):
    ledger, row = source_row(project, dated_split_book(
        J8='Стоимость СМР', K8='Стоимость материалы',
        P8='Стоимость СМР', Q8='Стоимость материалы'))
    assert ledger['items'][0]['amount_split']
    assert ledger['items'][0]['periods'][0]['amount_split']
    assert row['completed'] == 700
    assert row['works_materials_split']
    assert (row['completed_works'], row['completed_materials']) == (500, 200)


def test_each_period_uses_its_own_labels_when_annual_pair_is_unlabelled(project):
    ledger, row = source_row(project, dated_split_book(P8='Стоимость', Q8='Стоимость'))
    assert not ledger['items'][0]['amount_split']
    assert ledger['items'][0]['periods'][0]['amount_split']
    assert row['completed'] == 700 and row['works_materials_split']
    assert (row['completed_works'], row['completed_materials']) == (200, 500)


@pytest.mark.parametrize('cells', [
    {'J9': 'не рассчитано', 'P9': 'не рассчитано'},
    {'J9': 'не рассчитано'},
    {'P9': 'не рассчитано'},
    {'K9': '#VALUE!', 'Q9': '#VALUE!'},
])
def test_nonempty_unreadable_half_cannot_become_zero_or_partial_total(project, cells):
    ledger, row = source_row(project, dated_split_book(**cells))
    item = ledger['items'][0]
    assert row['completed'] is None
    assert row['completed_works'] is None and row['completed_materials'] is None
    assert not row['works_materials_split']
    assert row['completion_ratio'] is None and row['remaining'] is None
    assert any('не прочитано как число' in warning for warning in item['warnings'])
    if 'P9' in cells or 'Q9' in cells:
        assert item['completed_amount'] is None and not item['amount_split']
    if 'J9' in cells or 'K9' in cells:
        assert item['periods'][0]['amount'] is None
        assert not item['periods'][0]['amount_split']


def test_truly_empty_half_with_known_other_half_still_has_a_known_total(project):
    _, row = source_row(project, dated_split_book(J9=None, P9=None))
    assert row['completed'] == 200
    assert row['works_materials_split']
    assert (row['completed_works'], row['completed_materials']) == (200, 0)


def zip_source_row(project, data):
    parsed = ledgers.parse_archive(archive([('Учебная.xlsx', data)]))
    ledger, = parsed['ledgers']
    project.snapshots.append({'taken_at': '2026-05-01', 'ledgers': [ledger], 'summary_contracts': []})
    row, = contracts.build(project, '2026-05-01')['rows']
    return ledger, row


def test_uncached_formula_is_not_a_truly_empty_money_half(project):
    ledger, row = zip_source_row(project, dated_split_book(J9='=1+2', P9='=1+2'))
    assert row['completed'] is None
    assert row['completed_works'] is None and row['completed_materials'] is None
    assert not row['works_materials_split']
    assert any('Пересчитайте и сохраните книгу' in warning for warning in ledger['items'][0]['warnings'])


@pytest.mark.parametrize('kind', ['empty', 'numeric_zero', 'cached_formula_zero'])
def test_real_zip_reader_keeps_known_zero_and_empty_controls(project, kind):
    value = {'empty': None, 'numeric_zero': 0, 'cached_formula_zero': '=0'}[kind]
    data = dated_split_book(J9=value, P9=value)
    if kind == 'cached_formula_zero':
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(out, 'w') as rebuilt:
            for item in original.infolist():
                payload = original.read(item.filename)
                if item.filename == 'xl/worksheets/sheet1.xml':
                    text = payload.decode()
                    for cell in ('J9', 'P9'):
                        pattern = r'(<c\b[^>]*\br="'+cell+r'"[^>]*>.*?<v>)(.*?)(</v>.*?</c>)'
                        text, count = re.subn(pattern, lambda match: match[1]+'0'+match[3], text, flags=re.S)
                        assert count == 1
                    payload = text.encode()
                rebuilt.writestr(item, payload)
        data = out.getvalue()
    _, row = zip_source_row(project, data)
    assert row['completed'] == 200 and row['works_materials_split']
    assert (row['completed_works'], row['completed_materials']) == (200, 0)


def test_unlabelled_money_pair_is_not_split_by_position():
    wb = openpyxl.load_workbook(io.BytesIO(book(split=True)))
    ws = wb.active
    for column in (10, 11, 16, 17):
        ws.cell(8, column, 'Стоимость')
    out = io.BytesIO()
    wb.save(out)
    ledger = parsed_ledger(out.getvalue())
    item = ledger['items'][0]
    assert item['completed_amount'] == 700
    assert item['completed_work_amount'] is None and not item['amount_split']
    assert any('не разделены' in w for w in ledger['warnings'])


def test_plain_book_has_no_invented_split():
    item = parsed_ledger(book())['items'][0]
    assert item['completed_work_amount'] is None and not item['amount_split']


def split_ledger(periods):
    ledger = primary_ledger({"completed": sum(p[1] + p[2] for p in periods)},
                            acts=[{"date": day, "amount": work + material} for day, work, material in periods])
    for period, (_, work, material) in zip(ledger["items"][0]["periods"], periods):
        period.update(work_amount=work, material_amount=material, amount_split=True)
    return ledger


def test_register_shows_works_and_materials_separately(project):
    ledger = split_ledger([("2026-03-12", 100, 400), ("2026-04-12", 150, 0)])
    project.snapshots.append({"taken_at": "2026-05-01", "ledgers": [ledger], "summary_contracts": []})
    row, = contracts.build(project, "2026-05-01")["rows"]
    assert row["completed"] == 650
    assert (row["completed_works"], row["completed_materials"]) == (250, 400)
    assert row["works_materials_split"] and not row["works_materials_note"]


def test_register_names_books_without_a_split(project):
    ledger = primary_ledger({"completed": 300}, acts=[{"date": "2026-03-12", "amount": 300}])
    project.snapshots.append({"taken_at": "2026-05-01", "ledgers": [ledger], "summary_contracts": []})
    row, = contracts.build(project, "2026-05-01")["rows"]
    assert row["completed"] == 300 and row["completed_works"] is None
    assert "не разделены" in row["works_materials_note"]


@pytest.mark.parametrize("width", [390, 1440])
def test_real_page_shows_works_and_materials_lines(project, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    ledger = split_ledger([("2026-03-12", 100, 400)])
    project.snapshots.append({"taken_at": "2026-05-01", "ledgers": [ledger], "summary_contracts": []})
    view = contracts.build(project, "2026-05-01")
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        from contract_rows import opened
        cell = opened(page).locator('[data-label="Выполнено по накопительным"]')
        expect(cell).to_contain_text('Работы (СМР): 100 ₽')
        expect(cell).to_contain_text('Поставлено материалов: 400 ₽')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
