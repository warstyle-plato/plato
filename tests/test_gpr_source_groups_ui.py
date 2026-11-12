"""Shared KS facts stay visible once without becoming percentages per floor."""
import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader
from browser import expand_gantt, open_ks_calculation
from test_monitor_cumulative_controls import browser_page, MARKER


def view(known=True, conflict=False):
    cohort = {'cohort_id': 'shared-1', 'source_name': 'Монтаж',
              'source_scope': 'Корпус 1, этажи 3–4', 'task_ids': ['3', '4'],
              'model': {'progress': .4 if known else None, 'progress_date': '2026-11-06',
                  'reason': 'Для общего процента не подтверждены веса СМР.',
                  'components': [{'name': 'Монтаж элемента', 'progress': .4, 'unit': 'м²',
                                  'completed_quantity': 4, 'plan_quantity': 10}]}}
    if conflict:
        cohort['source_conflict'] = {'reason': 'ГПР показывает завершение, общий объём КС требует сверки.'}
    tasks = [{'level': 'task', 'id': str(i), 'key': f'task:{i}', 'wbs': str(i),
              'name': f'Монтаж этажа {i}', 'object': 'Корпус 1',
              'plan_start': '2026-09-01', 'plan_finish': '2026-12-01',
              'actual_progress': 1 if conflict else None, 'progress_kind': 'gpr_percent',
              'pace_forecast_method': 'source_conflict' if conflict else 'unknown',
              'pace_forecast_known': False, 'forecast_finish': None,
              'pace_forecast_reason': 'Общий объём КС требует сверки.'} for i in (3, 4)]
    return {'cut': '2026-11-06', 'schedule': {'management': tasks,
             'physical_progress': {'tasks': [], 'source_cohorts': [cohort]}}}


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('known,conflict', [(True, False), (False, False), (True, True)])
def test_shared_fact_scope_and_individual_readings_remain_distinct(width, known, conflict):
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', view(known, conflict))
        expand_gantt(page)
        open_ks_calculation(page)
        groups = page.locator('#ksSharedGroups')
        expect(groups.locator('.ks-source-group')).to_have_count(1)
        expect(groups).to_contain_text('Общий объём для 2 работ; отдельные проценты не выделены.')
        expect(groups.locator('.contract-main-money')).to_have_text('40%' if known else '—')
        assert '40%' not in page.locator('#gantt').inner_text()
        groups.locator('summary').click()
        expect(groups).to_contain_text('40%')
        if not known:
            expect(groups).to_contain_text('не подтверждены веса СМР')
        if conflict:
            expect(groups).to_contain_text('требует сверки')
            expect(page.locator('#gantt')).to_contain_text('100%')
            assert 'Завершено по ГПР' not in page.locator('#gantt').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if width == 1440:
            text = ' '.join((s.extract_text() or '') for s in PdfReader(io.BytesIO(page.pdf())).pages)
            assert 'отдельные проценты не выделены' in text
        assert not errors


def test_untrusted_source_text_is_escaped_and_replacing_project_clears_groups():
    with browser_page(390) as (page, responses, errors):
        value = view()
        value['schedule']['physical_progress']['source_cohorts'][0]['source_name'] = MARKER
        page.evaluate('(v)=>renderGantt(v)', value)
        expect(page.locator('#ksSharedGroups')).to_contain_text(MARKER)
        assert page.locator('#ksSharedGroups img').count() == 0
        assert not page.evaluate('window.untrustedRan===true')
        next_view = copy.deepcopy(value)
        next_view['schedule']['physical_progress'] = {}
        page.evaluate('(v)=>renderGantt(v)', next_view)
        expect(page.locator('#ksSharedGroups')).to_be_hidden()
        assert page.locator('#ksSharedGroups').inner_text() == ''
        assert not errors


def test_selecting_project_from_group_access_invalidates_previous_gpr_and_ks_facts():
    with browser_page(390) as (page, responses, errors):
        page.evaluate('(v)=>renderGantt(v)', view())
        expand_gantt(page)
        page.locator('#dataTab').click()
        page.locator('#siteAccessCard > summary').click()
        page.evaluate('drawSiteAccess({chats:[{project:"Следующий проект",title:"Учебная группа",chat_id:-100123,authorized:true}]})')
        page.locator('#siteAccessList button').click()
        expect(page.locator('#project')).to_have_value('Следующий проект')
        page.locator('#monitorTab').click()
        assert page.locator('#ksSharedGroups').inner_text() == ''
        expect(page.locator('#ganttCard')).to_be_hidden()
        assert not errors
