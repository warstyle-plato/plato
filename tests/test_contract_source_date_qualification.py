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
    from tests.contract_rds_fixtures import native_card
    import developaid_contract_rds as rds
    listed=native_card()
    listed['contract_id']=CONTRACT
    source=listed['documents'][1]
    source['title']='Учебный график'
    source['schedule']['assumption']=assumption
    for row in source['schedule']['lines']: row['date_precision']=precision
    if partial:
        source['schedule']['lines'].append({'code':'99','name':'Без срока','start':None,'finish':None,'parent':None})
    listed=files._with_control(listed,None,'2026-03-05')
    listed['rds_comparison']=rds.build(listed)
    listed['comparison_export']=export.bind_snapshot('Учебный проект','2026-03-05',CONTRACT,listed,{})
    return listed


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('precision,assumption', [
    ('chart_intervals', documents.CHART_INTERVALS_ASSUMPTION),
    ('chart_marks', documents.CHART_DATES_ASSUMPTION),
    (None, documents.WEEKS_ASSUMPTION),
])
def test_computed_plan_card_register_and_xlsx_share_source_qualification(monkeypatch, partial, precision, assumption):
    listed = card(partial, precision, assumption)
    control, comparison = listed['control'], listed['comparison']
    assert control['total'] is not None and control['total']['readiness'] == .15
    assert comparison['coverage']['partial'] is partial
    source = control['schedule_source']
    assert source == comparison['schedule_source']
    assert (source['sha256'], source['title'], source['assumption'], source['date_precision']) == (
        'b'*64, 'Учебный график', assumption, precision)
    assert source['undated'] == int(partial)
    assert 'deadline' not in source and 'forecast' not in source
    monkeypatch.setattr(files, 'listing', lambda *args, **kwargs: listed)
    row = files.register_control('Учебный', {'rows': [{'id': CONTRACT, 'physical_items': []}]},
                                 '2026-03-05')['rows'][0]
    assert row['schedule_control']['schedule_source'] == source
    cached = {'ok': True, **listed}
    meta = export.bind_snapshot('Учебный', '2026-03-05', CONTRACT, cached, {})
    sheet = load_workbook(io.BytesIO(export.workbook(meta, listed['rds_comparison'], listed['rds_comparison']['rows'])), data_only=True).active
    texts = [str(value) for values in sheet.values for value in values if value is not None]
    assert any(cell.comment and assumption in cell.comment.text for row in sheet for cell in row)
    assert not any('b'*64 in text for text in texts)


def test_source_qualification_uses_the_calculated_plans_accepted_sha():
    listed = card()
    source = listed['documents'][1]
    newer = copy.deepcopy(source)
    newer.update(sha256='d'*64, agreement={'number': '2', 'date': '2026-03-09'}, title='Другой график')
    newer['schedule']['assumption'] = 'Не выбран для этого плана'
    listed['documents'].append(newer)
    got = files._with_control(listed, None, '2026-03-10')
    assert got['control']['schedule_source']['sha256'] == 'b'*64
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
        page.locator('#contractExecution > summary').click()
        methodology = page.locator('#contractComparisonMethodology')
        expect(methodology).to_contain_text(documents.CHART_INTERVALS_ASSUMPTION)
        methodology.locator('summary').first.click()
        expect(methodology.get_by_text(documents.CHART_INTERVALS_ASSUMPTION, exact=True)).to_be_visible()
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
