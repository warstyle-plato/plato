"""Completion discrepancies qualify forecasts without choosing a source winner."""
import copy
import datetime as dt
import io

import pytest

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_schedule_gpr_forecast as gpr
import developaid_schedule_gpr_physical as physical
import developaid_report_schedule as executive
from test_monitor_management_gantt import _gpr_book
from test_schedule_physical_print_summary import gpr_sources, PROJECT, CUT

DAY = dt.date.fromisoformat


def quantities(progress=.5, date='2026-10-31'):
    return {'task_id': '1', 'name': 'Монтаж', 'mode': 'quantities', 'scope_confirmed': True,
            'known': True, 'progress': progress, 'progress_date': date,
            'forecast_finish': '2027-01-06', 'reason': '', 'components': [{
                'component_id': 'Монтаж', 'progress': progress, 'period_end': date,
                'known': True, 'forecast_finish': '2027-01-06', 'reason': ''}]}


@pytest.mark.parametrize('progress', [0., .5])
@pytest.mark.parametrize('date', ['2026-10-21', '2026-10-31', '2026-11-01'])
def test_completed_gpr_and_unfinished_natural_quantity_keep_both_dated_readings(progress, date):
    got = gpr.work({}, [(DAY(date), 1., 'weekly_gpr')], DAY(CUT), quantities(progress))
    assert got['method'] == 'source_conflict' and got['forecast_finish'] is None
    assert got['progress'] == progress and got['progress_date'] == '2026-10-31'
    assert got['progress_origin'] == 'cumulative_quantities'
    assert got['source_conflict']['gpr']['date'] == date
    assert got['source_conflict']['quantities'][0]['progress'] == progress
    assert '31.10.2026' in got['reason'] and DAY(date).strftime('%d.%m.%Y') in got['reason']
    assert ('Даты и показания' in got['reason']) == (date != '2026-10-31')
    assert 'противореч' not in got['reason'] and 'не хватает данных' not in got['reason']
    assert gpr.SOURCE_CONFLICT_ACTION in got['reason']


def test_completed_quantities_and_future_gpr_facts_do_not_create_a_conflict():
    points = [(DAY('2026-10-31'), 1., 'weekly_gpr')]
    completed = quantities(1.)
    completed['forecast_finish'] = '2026-10-31'
    got = gpr.work({}, points, DAY(CUT), completed)
    assert got['method'] == 'cumulative_quantities' and got['forecast_finish'] == '2026-10-31'
    future = [(DAY('2026-11-10'), 1., 'weekly_gpr')]
    got = gpr.work({}, future, DAY(CUT), quantities())
    assert got['method'] == 'cumulative_quantities' and got['forecast_finish'] == '2027-01-06'
    zero = quantities(0.)
    zero.update(known=False, forecast_finish=None)
    got = gpr.work({}, [(DAY('2026-10-31'), 0., 'weekly_gpr')], DAY(CUT), zero)
    assert got['method'] == 'cumulative_unknown' and got['progress'] == 0.


def test_manual_completion_is_a_separate_explicit_basis_and_no_binding_is_restored():
    task = quantities()
    task.update(mode='completed', progress=1., components=[], actual_finish='2026-10-31',
                forecast_finish='2026-10-31')
    model = {'tasks': [task], 'seeds': {'1': '2026-10-31'}, 'reasons': []}
    before = copy.deepcopy(model)
    points = {'1': [(DAY('2026-10-31'), 1., 'weekly_gpr')]}
    assert gpr.qualify_quantities(model, points, DAY(CUT)) == before == model
    assert gpr.work({}, points['1'], DAY(CUT), task)['method'] == 'confirmed_completion'


def test_components_are_not_averaged_and_all_view_forecasts_are_qualified():
    task = quantities()
    task['progress'] = None
    unfinished = task['components'][0]
    task['components'] = [dict(unfinished, component_id='Завершённый компонент '+str(i), progress=1.)
                          for i in range(3)] + [unfinished]
    model = {'tasks': [task], 'seeds': {'1': '2027-01-06'}, 'actual_finishes': {}, 'reasons': []}
    before = copy.deepcopy(model)
    got = gpr.qualify_quantities(model, {'1': [(DAY('2026-10-31'), 1., 'weekly_gpr')]}, DAY(CUT))
    assert model == before and got['state'] == 'source_conflict' and got['seeds'] == {}
    task = got['tasks'][0]
    assert task['progress'] is None and [c['progress'] for c in task['components']] == [1., 1., 1., .5]
    assert '50%' in task['reason']  # a fourth component cannot lose its actual cause
    assert not task['known'] and task['forecast_finish'] is None
    assert all(not c['known'] and c['forecast_finish'] is None for c in task['components'])
    assert gpr.qualify_quantities(got, {}, DAY(CUT)) == got  # already qualified: no second priority
    got = gpr.work({}, [], DAY(CUT), task)
    assert got['method'] == 'source_conflict' and got['forecast_finish'] is None


def conflict_sources(gpr_sources, date='2026-10-31'):
    gpr_sources('confirmed')
    monitor.store_schedule_fact(PROJECT, _gpr_book([
        (1, 'Монтаж корпуса 1', 1., DAY('2026-09-01'), DAY('2026-10-31'),
         'Завершено', '2.2.1.1')]), date)


@pytest.mark.parametrize('date', ['2026-10-31', '2026-11-01'])
def test_real_catalog_build_monitor_and_report_agree_without_editing_evidence(gpr_sources, date):
    conflict_sources(gpr_sources, date)
    folder = monitor._project_dir(PROJECT)
    events = {str(p): p.read_bytes() for p in folder.glob('gpr_physical_links/*.json')}
    assert events
    catalog, model = physical.catalog(PROJECT, CUT), physical.build(PROJECT, CUT)
    assert catalog['model']['tasks'] == model['tasks']
    task = model['tasks'][0]
    component = task['components'][0]
    assert model['state'] == model['evidence_status']['state'] == 'source_conflict'
    assert model['evidence_status']['mapping'] == 'confirmed'
    assert task['progress'] == .5 and task['progress_date'] == '2026-10-31'
    assert component['completed_quantity'] == 50 and component['plan_quantity'] == 100
    assert not task['known'] and task['forecast_finish'] is None and model['seeds'] == {}
    assert not component['known'] and component['forecast_finish'] is None
    view = monitor.build(PROJECT, CUT)
    row = view['schedule']['rows'][0]
    assert row['actual_progress'] == .5 and row['gpr_progress'] == 1.
    assert row['forecast_source'] == 'source_conflict' and row['forecast_finish'] is None
    assert row['source_conflict']['gpr']['date'] == date
    built = report.build(PROJECT, 'week', CUT)
    summary = built['construction_summary']
    assert summary['forecast'] is None and summary['state'] == 'unknown'
    assert summary['facts'][0]['done'] == 50 and summary['facts'][0]['date'] == '2026-10-31'
    assert summary['source_status']['state'] == 'source_conflict'
    assert summary['source_status']['archive'] == 'available'
    assert 'Сверьте' in summary['source_status']['action']
    assert not any('стоят или нет данных' in r for r in built['schedule']['qualification']['reasons'])
    assert {str(p): p.read_bytes() for p in folder.glob('gpr_physical_links/*.json')} == events
    assert catalog['configuration']['components'][0]['item_ids'] == ['0:0']


@pytest.mark.parametrize('width', [390, 1440])
def test_real_conflict_reason_quantities_and_action_are_visible_in_monitor_report_and_pdf(gpr_sources, width):
    from playwright.sync_api import expect
    from pypdf import PdfReader
    from test_monitor_cumulative_controls import browser_page
    conflict_sources(gpr_sources, '2026-11-01')
    view, built = monitor.build(PROJECT, CUT), report.build(PROJECT, 'week', CUT)
    with browser_page(width) as (page, responses, errors):
        page.evaluate('(view)=>renderGantt(view)', view)
        body = page.locator('#dependencyTimelineBody .schedule-physical-summary')
        expect(body).to_be_visible()
        visible = body.inner_text()
        assert '50 / 100 м²' in visible and '31.10.2026' in visible and '01.11.2026' in visible
        assert 'Сверьте' in visible and '06.01.2027' not in visible
        page.set_content(report.render_html(built))
        main = page.locator('.executive-schedule')
        visible = main.inner_text()
        assert '50 из 100 м²' in visible and '31.10.2026' in visible and '01.11.2026' in visible
        assert 'Сверьте' in visible and 'Не определена' in visible
        assert main.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        text = ' '.join(' '.join(p.extract_text() or '' for p in
                                PdfReader(io.BytesIO(page.pdf(format='A4'))).pages).split())
        assert '50 из 100 м² на 31.10.2026' in text
        assert '01.11.2026' in text and 'Сверьте' in text and '06.01.2027' not in text
        assert not errors


def test_driver_method_and_escaped_reason_are_preserved_only_in_details():
    reason = 'По росту процента <img src=x onerror=alert(1)>.'
    block = executive.model({'rnv': {'state': 'estimate', 'basis': 'gpr', 'forecast': '2027-01-06',
        'driving_chain': [{'name': 'Монтаж', 'method': 'gpr_pace', 'reason': reason}]}})
    assert block['driver_method'] == 'gpr_pace' and block['driver_reason'] == reason
    assert reason not in executive.render(block) and reason not in executive.conclusion(block)
    details = executive.details(block)
    assert '&lt;img' in details and '<img' not in details and 'По росту процента' in details


def test_real_driver_reason_is_printed_once_in_the_source_appendix(gpr_sources):
    from playwright.sync_api import expect
    from pypdf import PdfReader
    from test_monitor_cumulative_controls import browser_page
    built = gpr_sources('confirmed')
    summary = built['construction_summary']
    driver = built['schedule']['qualification']['driving_chain'][0]
    assert summary['driver_method'] == driver['method'] == 'cumulative_quantities'
    reason = summary['driver_reason']
    assert reason == driver['reason'] and reason
    with browser_page(1440) as (page, responses, errors):
        page.set_content(report.render_html(built))
        assert reason not in page.locator('.executive-schedule').inner_text()
        detail = page.locator('details.report-source-screen').filter(has_text='Источники и ограничения оценки')
        assert not detail.get_attribute('open')
        detail.locator('summary').click()
        expect(detail).to_contain_text(reason)
        text = ' '.join(' '.join(p.extract_text() or '' for p in
                                PdfReader(io.BytesIO(page.pdf(format='A4'))).pages).split())
        assert text.count(reason) == 1
        assert text.index(reason) > text.index('Приложение. Источники и ограничения оценки')
        assert not errors
