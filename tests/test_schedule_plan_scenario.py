"""Conditional remaining calendar duration is never an actual-pace forecast."""
import copy

import pytest
from playwright.sync_api import expect
from browser import expand_gantt

import developaid_schedule_plan_scenario as scenario
from test_monitor_cumulative_controls import browser_page
from test_monitor_gpr_sections import monitor_view


def row(progress=.5):
    return dict(plan_start='2026-01-01',plan_finish='2026-01-10',construction_work=True,
                object='Корпус 1',display_progress=dict(value=progress,date='2026-01-05'))


def test_remaining_duration_uses_planned_rate_and_retains_actual_unknowns():
    value=row()
    result=scenario.work(value,'2026-01-06')
    assert result['finish']=='2026-01-10'  # Five calendar days from the cut, inclusive.
    assert not result['complete']
    assert 'условный сценарий' in result['note']
    assert 'forecast_known' not in value and 'actual_finish' not in value
    value.update(plan_start='2026-01-20',plan_finish='2026-01-29')
    assert scenario.work(value,'2026-01-06')['finish']=='2026-01-24'


@pytest.mark.parametrize('mutation',[
    lambda r:r['display_progress'].update(value=None),
    lambda r:r['display_progress'].update(value=True),
    lambda r:r['display_progress'].update(value=float('nan')),
    lambda r:r['display_progress'].update(date='2026-01-07'),
    lambda r:r['display_progress'].update(date='2026-01-05invalid'),
    lambda r:r['display_progress'].update(date='2025-01-05'),
    lambda r:r.update(plan_start=None),
    lambda r:r.update(plan_finish='2025-01-01'),
    lambda r:r.update(requires_reconciliation=True),
])
def test_unknown_stale_future_or_conflicting_evidence_never_gets_a_scenario(mutation):
    value=row();mutation(value)
    assert scenario.work(value,'2026-01-06')['finish'] is None


def test_completed_reading_does_not_create_an_actual_completion_date():
    value=row(1)
    result=scenario.work(value,'2026-01-06')
    assert result['complete'] and result['finish'] is None
    assert 'actual_finish' not in result


def test_summary_is_partial_and_preserves_a_measured_forecast():
    a=row();a['plan_pace_scenario']=scenario.work(a,'2026-01-06')
    b=row();b.update(forecast_known=True,forecast_finish='2026-02-02')
    c=row();c.update(plan_start=None);c['plan_pace_scenario']=scenario.work(c,'2026-01-06')
    result=scenario.summary([a,b,c])[0]
    assert result['finish']=='2026-02-02'
    assert result['covered']==2 and result['total']==3 and result['partial']
    assert result['oldest_source_date']=='2026-01-05'
    assert 'rnv_forecast' not in result


@pytest.mark.parametrize('width',[390,1440])
def test_actual_page_displays_a_scenario_label_beside_unknown_pace(width):
    view=copy.deepcopy(monitor_view())
    tasks=view['schedule']['management'][0]['children'][0]['children'][0]['children']
    target=tasks[1]
    target['display_progress']={'value':0,'date':'2026-11-06','label':'ГПР','source':'Учебный ГПР'}
    target['construction_work']=True
    target['plan_pace_scenario']=scenario.work(target,view['cut'])
    assert target['plan_pace_scenario']['finish']=='2027-01-08'
    view['schedule']['plan_pace_scenarios']=scenario.summary([target])
    with browser_page(width) as (page,responses,errors):
        page.evaluate('(v)=>{currentView=v;renderDash(v);renderGantt(v)}',view)
        expect(page.locator('.plan-scenario-summary')).to_be_visible()
        expect(page.locator('.plan-scenario-summary')).to_contain_text('условная оценка')
        cell=page.locator('#gprFactMatrix [data-work-id="2"]')
        expect(cell.locator('.gpr-cell-forecast')).to_have_text('При плановом темпе: 08.01.2027')
        expect(cell.locator('.gpr-cell-scenario')).to_have_text('При плановом темпе: 08.01.2027')
        expand_gantt(page)
        line=page.locator('.g-row.lvl-task').filter(has_text='Внутренние работы')
        expect(line.locator('.plan-scenario>summary')).to_contain_text('При плановом темпе: 08.01.2027')
        expect(line).not_to_contain_text('2031')
        assert not target['pace_forecast_known']
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
