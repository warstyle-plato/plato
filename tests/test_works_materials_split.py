"""Works (СМР) and materials supply stay separate in cumulative money (synthetic data)."""
from __future__ import annotations

import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_monitor_cumulative_ledgers import book
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
        cell = page.locator('#contractsRows td[data-label="Выполнено по накопительным"]').first
        expect(cell).to_contain_text('Работы (СМР): 100 ₽')
        expect(cell).to_contain_text('Поставлено материалов: 400 ₽')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
