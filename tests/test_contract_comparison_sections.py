"""Contract plan/fact preserves printed building sections in every presentation."""
import copy
import io

from openpyxl import load_workbook
import pytest

import developaid_contract_comparison as comparison
import developaid_contract_comparison_export as export
from tests.test_contract_comparison_export import native_card, PROJECT, CUT, CONTRACT


def section_card():
    cached = native_card()
    known = cached['comparison']['lines']
    # Same work names in different buildings must remain independent. Include
    # unknown source works and a line without a section, not just matched rows.
    known[1]['name'] = known[0]['name']
    schedule = [
        {'code': '1', 'name': 'Фасады', 'parent': None, 'section': 'Корпус 1'},
        {'code': known[0]['code'], 'name': known[0]['name'], 'parent': '1'},
        {'code': '1.2', 'name': 'Другая работа', 'parent': '1'},
        {'code': '2', 'name': 'Фасады', 'parent': None, 'section': 'Корпус 2'},
        {'code': known[1]['code'], 'name': known[1]['name'], 'parent': '2'},
        {'code': 'P.1', 'name': 'Работа паркинга', 'parent': None, 'section': 'Паркинг'},
        {'code': '0', 'name': 'Общая работа', 'parent': None},
    ]
    for row in schedule:
        row.update(start='2026-03-01', finish='2026-03-10')
    listed = {'control': {'lines': known, 'total': cached['comparison']['total']},
              'plan': {'editions': []}, 'fact': {},
              'documents': [{'sha256': 'source', 'title': 'Учебный ГПР', 'schedule': {'lines': schedule}}]}
    return cached, listed


def projected():
    cached, listed = section_card()
    before = copy.deepcopy(listed)
    cached['comparison'] = comparison.build(listed, CUT, 'source')
    assert listed == before
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    return cached


def test_printed_section_is_inherited_without_merging_works_or_changing_numbers():
    cached, listed = section_card()
    view = comparison.build(listed, CUT, 'source')
    assert [(r['code'], r['section']) for r in view['lines']] == [
        ('3.1', 'Корпус 1'), ('1.2', 'Корпус 1'), ('3.2', 'Корпус 2'),
        ('P.1', 'Паркинг'), ('0', '')]
    by_code = {r['code']: r for r in view['lines']}
    for native in listed['control']['lines']:
        shown = by_code[native['code']]
        assert [shown[k] for k in ('planned', 'fact', 'deviation')] == [native[k] for k in ('planned', 'fact', 'deviation')]
    assert view['total'] == listed['control']['total']
    assert len(view['lines']) == 5


@pytest.mark.parametrize('missing', ['absent', 'ambiguous'])
def test_a_missing_or_ambiguous_source_section_is_not_guessed(missing):
    _, listed = section_card()
    source = listed['documents'][0]['schedule']['lines']
    if missing == 'absent':
        for row in source:
            row.pop('section', None)
    else:
        duplicate = copy.deepcopy(source[1])
        duplicate['section'] = 'Другой корпус'
        source.append(duplicate)
    rows = comparison.build(listed, CUT, 'source')['lines']
    assert next(r for r in rows if r['code'] == '3.1')['section'] == ''


def test_unambiguous_printed_sections_and_unknown_works_reach_excel():
    cached = projected()
    rows = cached['comparison']['lines']
    assert rows[0]['context'].startswith('Корпус 1 · ')
    assert [r['section'] for r in rows] == ['Корпус 1', 'Корпус 1', 'Корпус 2', 'Паркинг', '']
    assert rows[1]['state'] == 'unknown' and rows[1]['fact'] is None
    meta = cached['comparison_export']
    raw = export.workbook(meta, cached['comparison'], rows)
    sheet = load_workbook(io.BytesIO(raw)).active
    labels = [row[0] for row in sheet.values]
    for label in ['Корпус 1', 'Корпус 2', 'Паркинг', 'Раздел в ГПР не указан']:
        assert labels.count(label) == 1
    assert labels.index('Корпус 1') < labels.index('Корпус 2') < labels.index('Паркинг')


@pytest.mark.parametrize('width', [390, 1440])
def test_real_page_groups_and_searches_by_printed_building_and_keeps_print_headers(width):
    from playwright.sync_api import expect
    from tests.test_contract_comparison_export_ui import _browser_export
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT as BROWSER_CONTRACT, KEY
    cached = projected()
    with browser_page(width) as (page, _, errors):
        _browser_export(page, cached, BROWSER_CONTRACT, KEY, [])
        headers = page.locator('#contractComparisonRows .contract-comparison-section')
        expect(headers).to_have_text(['Корпус 1', 'Корпус 2', 'Паркинг', 'Раздел в ГПР не указан'])
        expect(page.locator('#contractComparisonRows [data-comparison-code]')).to_have_count(5)
        page.locator('#contractComparisonSearch').fill('Корпус 2')
        expect(headers).to_have_text(['Корпус 2'])
        expect(page.locator('#contractComparisonRows [data-comparison-code]')).to_have_count(1)
        page.locator('#contractComparisonSearch').fill('Корпус 1')
        expect(page.locator('#contractComparisonRows [data-comparison-code]')).to_have_count(2)
        page.locator('#contractComparisonFilter').select_option('unknown')
        expect(page.locator('#contractComparisonRows [data-comparison-code]')).to_have_count(1)
        expect(headers).to_have_text(['Корпус 1'])
        page.emulate_media(media='print')
        expect(headers.first).to_be_visible()
        assert headers.first.evaluate('e=>getComputedStyle(e).display') == 'table-row'
        page.emulate_media(media='screen')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth') and not errors
