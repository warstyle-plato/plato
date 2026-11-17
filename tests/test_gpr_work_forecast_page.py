"""Native Monitor reads the same bound work date with and without weights."""
import copy
import re

import pytest
from playwright.sync_api import expect

import developaid_gpr_work_forecast as work_dates
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as readiness
from test_gpr_work_forecast import fallback, profiled
from test_gpr_why_page import serve, why_view
from test_management_calendar_membership import _native_scoped_view
from test_monitor_cumulative_controls import browser_page


def view(kind):
    result = why_view()
    schedule = profiled() if kind == 'profile' else fallback()
    result.update(cut=schedule['cut'], schedule=schedule)
    schedule['work_forecast'] = work_dates.build(schedule, schedule['cut'])
    schedule['readiness_html'] = readiness.render(schedule['readiness'], show_forecast=False)
    return result


def show(page, value):
    page.wait_for_function('currentView!==null&&!$("refresh").disabled')
    page.evaluate('(v)=>{$("cut").value=v.cut;currentView=v;renderDash(v);renderGantt(v)}', value)


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('kind', ['profile', 'fallback'])
def test_native_headline_calendar_and_group_detail_share_the_dto(monkeypatch, width, kind):
    value = view(kind)
    state = value['schedule']['work_forecast']
    expected = '.'.join(reversed(state['summary']['finish'].split('-')))
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        heading = page.locator('#readinessSummary .canonical-work-forecast')
        expect(heading).to_have_attribute('data-work-forecast', state['summary']['finish'])
        expect(heading).to_contain_text(expected)
        tile = page.locator('#kpis .kpi').filter(has=page.locator('.l').filter(has_text=re.compile('^'+re.escape(state['summary']['forecast_label'])+'$')))
        expect(tile.locator('.n')).to_have_text(expected)
        expect(page.locator('#gprWhy')).not_to_contain_text('Общая оценка срока по ГПР неполная')
        assert page.locator('.gpr-legacy-fallback').count() == 0
        expect(page.locator('#gprCalendarOverview .gpr-forecast-strip')).to_have_attribute('data-finish', state['summary']['finish'])
        page.locator('#gprCalendar > summary').click()
        page.locator('#ganttCollapse').click()
        name = state['corpora'][0]['name']
        group = page.locator('#gantt .lvl-corpus').filter(has=page.locator('.g-label .title').filter(has_text=re.compile('^'+re.escape(name)+'$')))
        finish = state['corpora'][0]['forecast']['finish']
        expect(group.locator('.gpr-forecast-strip')).to_have_attribute('data-finish', finish)
        group.locator('.g-label .title').click()
        expect(page.locator('#detailTitle')).to_have_text(name)
        field = page.locator('#detailGrid .mini').filter(has=page.locator('.l').filter(has_text='Условное окончание работ'))
        expect(field.locator('.v')).to_have_text('.'.join(reversed(finish.split('-'))))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_native_method_limit_preserves_plan_fact_and_explains_the_limit(monkeypatch, width):
    value = view('fallback')
    schedule = value['schedule']
    administrative = next(row for row in schedule['rows'] if row['id'] == 'admin')
    before = copy.deepcopy(administrative)
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        page.locator('#gprMatrixExpand').click()
        cell = page.locator('#gprFactMatrix [data-work-id="admin"]')
        expect(cell.locator('b')).to_have_text('0%')
        expect(cell.locator('.gpr-cell-plan')).to_contain_text('01.08.2035')
        expect(cell.locator('.gpr-cell-forecast')).to_have_text('Расчётная дата не определена')
        cell.click()
        expect(page.locator('#detailWhy')).to_contain_text('Процент из ГПР не позволяет рассчитать новую дату')
        assert administrative == before
        assert not errors


def test_native_stale_dto_shows_one_reason_and_does_not_use_legacy_date(monkeypatch):
    value = view('profile')
    value['schedule']['work_forecast']['source_sha256'] = 'f'*64
    serve(monkeypatch, value)
    with browser_page() as (page, _, errors):
        show(page, value)
        expect(page.locator('#readinessSummary .canonical-work-forecast')).to_contain_text('Обновите срез')
        assert page.locator('#gprCalendarOverview .gpr-forecast-strip').count() == 0
        assert page.locator('.gpr-legacy-fallback').count() == 0
        assert not errors


def test_native_source_invalidation_drops_the_work_date_and_its_cards(monkeypatch):
    value = view('profile')
    serve(monkeypatch, value)
    with browser_page() as (page, _, errors):
        show(page, value)
        assert page.locator('[data-work-forecast-kpi]').count() == 2
        page.evaluate('invalidatePhysicalForecast()')
        assert page.locator('[data-work-forecast-kpi]').count() == 0
        assert page.locator('#gprCalendarOverview .gpr-forecast-strip').count() == 0
        assert page.evaluate('Object.hasOwn(currentView.schedule,"work_forecast")') is False
        assert not errors


def test_native_group_keeps_an_attested_member_without_a_calendar_point(monkeypatch):
    value = why_view()
    scoped = _native_scoped_view(classification=None)
    schedule = scoped['schedule']
    schedule.update(cut=scoped['cut'], approved_plan=dict(source_sha256=schedule['readiness']['source_sha256']))
    schedule['work_forecast'] = work_dates.build(schedule, scoped['cut'])
    value.update(cut=scoped['cut'], schedule=schedule)
    serve(monkeypatch, value)
    with browser_page() as (page, _, errors):
        show(page, value)
        group = page.evaluate('''()=>gprGroupCalendarPoint(
          {children:currentView.schedule.rows.map(row=>({...row,level:'task'}))},
          gprCalendarProjection(currentView))''')
        assert group['total'] == 2 and group['covered'] == 1 and group['missing'] == 1
        assert group['work_ids'] == ['build', 'other']
        assert not errors
