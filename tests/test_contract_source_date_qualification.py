"""Computed full and partial plans retain the precision of their accepted source chart."""
import copy
import io

from openpyxl import load_workbook
import pytest

import developaid_contract_comparison_export as export
import developaid_contract_documents as documents
import developaid_contract_files as files
from tests.test_contract_material_plan import work
from tests.test_contract_full_value_readiness import actual
from tests.test_monitor_cumulative_controls import CONTRACT, browser_page


def card(partial=False, precision='chart_intervals', assumption=documents.CHART_INTERVALS_ASSUMPTION):
    rows = [work('1', 100, 0)]
    source_rows = copy.deepcopy(rows)
    if partial:
        source_rows.append({'code': '2', 'name': 'Без срока', 'start': None, 'finish': None})
    for row in source_rows:
        row.update(parent=None, date_precision=precision)
    document = {'sha256': 'a'*64, 'contract': {'number': '8-ТСТ', 'date': '2026-03-01'},
                'title': 'Учебный график', 'schedule': {'lines': source_rows, 'assumption': assumption}}
    current = {'in_force': True, 'start': None, 'lines': rows, 'total': 100, 'planned': 100,
               'title': 'Учебная редакция', 'date': '2026-03-01', 'schedule': document['title'],
               'schedule_sha256': document['sha256']}
    listed = {'contract_id': CONTRACT, 'documents': [document], 'plan': {'editions': [current]},
              'fact': {'lines': [actual(installed=50)], 'note': ''}}
    return files._with_control(listed, None, '2026-03-10')


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('precision,assumption', [
    ('chart_intervals', documents.CHART_INTERVALS_ASSUMPTION),
    ('chart_marks', documents.CHART_DATES_ASSUMPTION),
    (None, documents.WEEKS_ASSUMPTION),
])
def test_computed_plan_card_register_and_xlsx_share_source_qualification(monkeypatch, partial, precision, assumption):
    listed = card(partial, precision, assumption)
    control, comparison = listed['control'], listed['comparison']
    assert control['total'] is not None and control['total']['readiness'] == .5
    assert comparison['coverage']['partial'] is partial
    source = control['schedule_source']
    assert source == comparison['schedule_source']
    assert (source['sha256'], source['title'], source['assumption'], source['date_precision']) == (
        'a'*64, 'Учебный график', assumption, precision)
    assert source['undated'] == int(partial)
    assert 'deadline' not in source and 'forecast' not in source
    monkeypatch.setattr(files, 'listing', lambda *args, **kwargs: listed)
    row = files.register_control('Учебный', {'rows': [{'id': CONTRACT, 'physical_items': []}]},
                                 '2026-03-10')['rows'][0]
    assert row['schedule_control']['schedule_source'] == source
    cached = {'ok': True, 'contract_id': CONTRACT, 'comparison': comparison}
    meta = export.bind_snapshot('Учебный', '2026-03-10', CONTRACT, cached, {})
    sheet = load_workbook(io.BytesIO(export.workbook(meta, comparison, comparison['lines'])), data_only=True).active
    texts = [str(value) for values in sheet.values for value in values if value is not None]
    assert assumption in texts
    assert any('a'*64 in text for text in texts)
    assert any('Учебный график' in text for text in texts)


def test_source_qualification_uses_the_calculated_plans_accepted_sha():
    listed = card()
    source = listed['documents'][0]
    newer = copy.deepcopy(source)
    newer.update(sha256='b'*64, agreement={'number': '2', 'date': '2026-03-09'}, title='Другой график')
    newer['schedule']['assumption'] = 'Не выбран для этого плана'
    listed['documents'].append(newer)
    got = files._with_control(listed, None, '2026-03-10')
    assert got['control']['schedule_source']['sha256'] == 'a'*64
    assert got['comparison']['schedule_source']['assumption'] == documents.CHART_INTERVALS_ASSUMPTION


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('partial', [False, True])
def test_native_page_exposes_interval_estimate_in_methodology_with_computed_metrics(width, partial):
    from playwright.sync_api import expect
    from tests.test_contract_card_shows_its_documents import _serve
    listed = card(partial)
    with browser_page(width) as (page, responses, errors):
        _serve(page, listed, [])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        methodology = page.locator('#contractComparisonMethodology')
        expect(methodology).to_contain_text(documents.CHART_INTERVALS_ASSUMPTION)
        methodology.locator('summary').first.click()
        expect(methodology.get_by_text(documents.CHART_INTERVALS_ASSUMPTION, exact=True)).to_be_visible()
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
