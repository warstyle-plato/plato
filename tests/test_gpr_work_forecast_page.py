"""Native Monitor reads the same bound work date with and without weights."""
import copy
import re

import pytest
from playwright.sync_api import expect

import developaid_gpr_work_forecast as work_dates
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as readiness
from test_gpr_work_forecast import fallback, profiled, task
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


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('change', ['revision', 'hash', 'state', 'effective', 'readiness_cut', 'readiness_source', 'schedule_cut', 'summary_progress', 'summary_plan', 'unavailable'])
def test_a_rejected_owner_cannot_revive_project_aggregates_from_readiness_html(monkeypatch, width, change):
    value = view('profile')
    schedule = value['schedule']
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_count(1)
        if change == 'revision':
            schedule['readiness']['profile_revision'] = (schedule['readiness'].get('profile_revision') or 0) + 1
        elif change == 'hash':
            schedule['readiness']['profile_sha256'] = 'e'*64
        elif change == 'state':
            schedule['readiness']['profile_state'] = 'invalid'
        elif change == 'effective':
            schedule['readiness']['profile_effective_from'] = '2049-01-01'
        elif change == 'readiness_cut':
            schedule['readiness']['cut'] = '2049-01-01'
        elif change == 'readiness_source':
            schedule['readiness']['source_sha256'] = 'e'*64
        elif change == 'schedule_cut':
            schedule['cut'] = '2049-01-01'
        elif change == 'summary_progress':
            schedule['work_forecast']['summary'].update(progress=.99, value='99%')
        elif change == 'summary_plan':
            schedule['work_forecast']['summary'].update(plan_finish='2099-01-01', plan_text='План 01.01.2099')
        else:
            schedule['work_forecast'] = work_dates.unavailable(schedule, value['cut'], 'Обновите срез.', 'dto_binding')
        show(page, value)
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_count(0)
        expect(page.locator('#readinessSummary .gpr-legacy-fallback')).to_have_count(0)
        expect(page.locator('#gprCalendarOverview .gpr-forecast-strip')).to_have_count(0)
        expect(page.locator('#gprProjectAssessment .n')).to_have_text('Не определена')
        # Invalid project composition does not erase the source readings of
        # individual works, which retain their own dates and qualifications.
        assert page.locator('#gprFactMatrix [data-work-id]').count() > 0
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('invalid_owner', [False, True])
def test_stage_headers_read_owner_aggregates_and_ignore_old_group_dates(monkeypatch, width, invalid_owner):
    value = view('profile')
    schedule = value['schedule']
    owner = copy.deepcopy(schedule['work_forecast'])
    stage = next(iter(schedule['display_groups']['by_id'].values()))
    schedule['display_groups'].setdefault('summaries', {})[stage] = dict(
        finish='2099-01-01', total=99, covered=99, all_complete=False)
    schedule['plan_pace_scenarios'] = [dict(finish='2099-01-01', covered=999, total=999)]
    if invalid_owner:
        schedule['readiness']['profile_revision'] = 98
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        header = page.locator('#gprFactMatrix .gpr-matrix-stage').filter(
            has=page.locator('summary').filter(has_text=re.compile('^'+re.escape(stage)+' '))).locator(':scope > summary')
        expect(header).not_to_contain_text('2099')
        if invalid_owner:
            expect(header).to_contain_text('Срок не определён')
        else:
            expect(header).to_contain_text('.'.join(reversed(owner['summary']['finish'].split('-'))))
        expect(page.locator('#gprFactMatrix')).not_to_contain_text('2099')
        expect(page.locator('#gprFactMatrix')).not_to_contain_text('999')
        assert schedule['work_forecast'] == owner
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
        page.locator('#gprCalendar > summary').click()
        page.locator('#ganttExpand').click()
        missing = page.locator('#gantt [data-work-id="other"]')
        expect(missing).to_have_attribute('data-forecast-scope', 'selected')
        expect(missing).to_contain_text('Окончание неизвестно')
        expect(missing).not_to_contain_text('Вне состава')
        assert missing.locator('.gpr-forecast-strip').count() == 0
        missing.locator('.g-label').click()
        expect(page.locator('#detailWhy')).not_to_contain_text('вне учтённого состава')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_native_summary_renders_missing_work_markup_and_financial_ampersand_as_text(monkeypatch, width):
    from developaid_monitor_dashboard import refresh_schedule_summary
    imported = '<img src=x onerror="window.gprSummaryUnsafe=true">'
    value = why_view()
    schedule = fallback([task('missing', name=imported,
                              display_progress=dict(value=None, date='2035-04-09'))])
    schedule['work_forecast'] = work_dates.build(schedule, schedule['cut'])
    schedule['readiness_html'] = readiness.render(schedule['readiness'], show_forecast=False)
    value.update(cut=schedule['cut'], schedule=schedule)
    money = 'Бюджет. A&B — учтено 12 млн ₽.'
    imported_head = '<img src=x onerror="window.gprSummaryHeadUnsafe=true">'
    value['dashboard']['summary'] = ['Срок. Прежняя оценка.', money, imported_head+'. Обычный текст.']
    refresh_schedule_summary(value)
    assert imported in value['dashboard']['summary'][0]
    assert value['dashboard']['summary'][1] == money
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        page.locator('#moneyTab').click()
        summary = page.locator('#summaryBody')
        expect(summary).to_contain_text(imported)
        expect(summary).to_contain_text(imported_head)
        expect(summary).to_contain_text(money)
        assert summary.locator('img').count() == 0
        assert page.evaluate('window.gprSummaryUnsafe===true') is False
        assert page.evaluate('window.gprSummaryHeadUnsafe===true') is False
        assert summary.inner_text().count('A&B') == 1
        assert 'A&amp;amp;B' not in summary.inner_html()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_missing_owner_never_uses_old_assessment_or_readiness_dates(monkeypatch, width):
    value = view('profile')
    schedule = value['schedule']
    schedule.pop('work_forecast')
    schedule['gpr_assessment'] = dict(finish='2099-01-01', progress=.99)
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        expect(page.locator('#readinessSummary .canonical-work-forecast')).to_contain_text('Обновите срез')
        expect(page.locator('#readinessSummary .readiness-project-value')).to_have_count(0)
        expect(page.locator('#gprCalendarOverview .gpr-forecast-strip')).to_have_count(0)
        expect(page.locator('#gprFactMatrix')).not_to_contain_text('2099')
        assert page.locator('#gprFactMatrix [data-work-id]').count() > 0
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_cached_conditional_date_cannot_cross_the_construction_method_boundary(monkeypatch, width):
    value = view('fallback')
    schedule = value['schedule']
    building = next(row for row in schedule['rows'] if row['id'] == 'building')
    old = copy.deepcopy(schedule['work_forecast'])
    building['construction_work'] = False
    assert building['plan_pace_scenario']['finish']
    assert work_dates.for_schedule(schedule, value['cut'])['state'] == 'unavailable'
    serve(monkeypatch, value)
    with browser_page(width) as (page, _, errors):
        show(page, value)
        expect(page.locator('#gprProjectAssessment .n')).to_have_text('Не определена')
        expect(page.locator('#gprCalendarOverview .gpr-forecast-strip')).to_have_count(0)
        page.locator('#gprMatrixExpand').click()
        cell = page.locator('#gprFactMatrix [data-work-id="building"]')
        expect(cell.locator('.gpr-cell-plan')).to_contain_text('01.08.2035')
        expect(cell.locator('b')).to_have_text('0%')
        expect(cell.locator('.gpr-cell-forecast')).to_have_text('Расчётная дата не определена')
        assert schedule['work_forecast'] == old
        assert not errors
