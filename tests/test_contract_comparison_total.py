"""The full position scope is distinct from the accumulated plan on the cut."""
import copy

import pytest

import developaid_contract_comparison as comparison
import developaid_contract_comparison_export as export
from tests.test_contract_comparison_export import CUT, PROJECT, native_card, table, xlsx
from tests.test_contract_indexed_operations import projected


def test_total_reuses_the_native_measure_and_survives_unknown_actuals():
    for unknown in (False, True):
        natural, money = native_card(unknown=unknown)['comparison']['lines']
        assert (natural['contract_total'], natural['unit']) == (20.0, 'м3')
        assert (money['contract_total'], money['unit']) == (1000.0, '₽')
        assert natural['planned'] == 10.0 and money['planned'] == 500.0
        if unknown:
            assert natural['fact'] is None and money['fact'] is None


def test_parent_total_uses_work_cost_while_each_operation_keeps_its_own_area():
    view, listed = projected()
    parent, *operations = view['lines']
    assert parent['contract_total'] == listed['control']['lines'][0]['work_amount'] == 10000.0
    assert parent['unit'] == '₽' and parent['physical_scope']['quantity'] == 100.0
    assert parent['physical_scope']['physical_fact'] is None
    assert all((row['contract_total'], row['unit']) == (100.0, 'м2') for row in operations)
    assert all(row['planned'] == 50.0 for row in operations)


@pytest.mark.parametrize('value', [None, 0.0, 1234.0])
def test_missing_and_zero_totals_stay_distinct_and_materials_are_not_added(value):
    line = {'code': '1', 'name': 'Учебная работа', 'amount': 99999.0,
            'work_amount': value, 'material_amount': 99999.0, 'planned': None, 'fact': 10.0}
    before = copy.deepcopy(line)
    row = comparison._row(line, None)
    assert row['contract_total'] == value and row['unit'] == '₽'
    assert line == before
    cached = native_card()
    cached['comparison']['lines'] = [row]
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, cached['contract_id'], cached, {})
    sheet, header = table(xlsx(cached))
    assert sheet.cell(header, 2).value == 'Всего по договору'
    assert sheet.cell(header + 1, 2).value == value
    assert '₽' in sheet.cell(header + 1, 2).number_format
    assert sheet.cell(header + 1, 3).value is None  # Unknown plan share is never inferred.


@pytest.mark.parametrize('width', [390, 1440])
def test_full_scope_column_is_visible_in_the_real_page_and_selected_excel(width, tmp_path):
    from playwright.sync_api import expect
    from tests.test_contract_comparison_export_ui import _browser_export
    from tests.test_monitor_cumulative_controls import CONTRACT, KEY, browser_page

    cached = native_card()
    natural, money = cached['comparison']['lines']
    missing = dict(natural, code='unknown-total', name='Неизвестный полный объём', contract_total=None)
    zero = dict(money, code='zero-total', name='Нулевой полный объём', contract_total=0.0)
    cached['comparison']['lines'].extend([missing, zero])
    with browser_page(width) as (page, _, errors):
        _browser_export(page, cached, CONTRACT, KEY, [])
        expect(page.locator('.contract-comparison thead th')).to_have_text([
            'Работа или поставка / единица', 'Всего по договору', 'План на дату', 'Факт',
            'Отклонение', 'Срок строки', 'Прогноз окончания'])
        cell = lambda code: page.locator(f'tr[data-comparison-code="{code}"] [data-label="Всего по договору"]')
        expect(cell(natural['code'])).to_have_text('20 м3')
        expect(cell(money['code'])).to_have_text('1 000 ₽')
        expect(cell('unknown-total')).to_have_text('Неизвестно')
        expect(cell('zero-total')).to_have_text('0 ₽')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#contractComparisonSearch').fill('нулевой полный')
        with page.expect_download() as got:
            page.locator('#contractComparisonExport').click()
        target = tmp_path / 'selected-total.xlsx'
        got.value.save_as(target)
        sheet, header = table(target.read_bytes())
        assert sheet.cell(header + 1, 2).value == 0.0
        assert '₽' in sheet.cell(header + 1, 2).number_format
        assert not errors
