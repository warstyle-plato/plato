"""One selected-project assessment, with independent RNV and contract bases."""
import copy

import pytest
from playwright.sync_api import expect

import developaid_gpr_summary as summary
import developaid_management_report as report
import developaid_monitor_dashboard as dashboard
import developaid_report_schedule as schedule_report
from test_report_compact_gpr import block, CUT
from test_gpr_why_page import why_view, serve, show
from test_monitor_cumulative_controls import browser_page
from test_schedule_physical_print_summary import gpr_sources


def report_value():
    rnv = dict(state='partial', basis='gpr', forecast=None,
               indicative_forecast='2027-09-30', approved='2027-09-30',
               driving_chain=[dict(name='Other population', method='plan')], reasons=[])
    gantt = block()
    gantt['dependency_timeline'] = dict(rnv=rnv)
    return dict(end=CUT, gantt=gantt,
                schedule=dict(qualification=copy.deepcopy(rnv), forecast=None, known=False),
                construction_summary=schedule_report.model(dict(rnv=rnv)))


def test_project_date_replaces_legacy_partial_date_but_never_the_rnv_or_money_inputs():
    value = report_value()
    original = copy.deepcopy(value)
    assessment = summary.project_assessment(value['gantt'], CUT)
    result = report._executive_schedule(value)
    assert result['forecast'] == assessment['finish'] == '2028-05-31'
    assert result['forecast_label'] == assessment['finish_label']
    assert result['gpr_assessment']['progress'] == .4
    assert result['rnv_forecast'] is None
    assert result['state'] == 'selected_gpr' and result['rnv_state'] == 'partial'
    assert result['rnv_context'] == original['gantt']['dependency_timeline']['rnv']
    assert result['driver'] is result['driver_reason'] is result['driver_method'] is None
    assert result['delay_days'] is None
    assert value == original
    before = dict(schedule=dict(qualified_rnv=original['gantt']['dependency_timeline']['rnv']))
    after = dict(schedule=dict(qualified_rnv=value['gantt']['dependency_timeline']['rnv']))
    commissioning = report._commissioning(before)
    assert report._forecast_shift(before, commissioning) == report._forecast_shift(after, commissioning) is None
    assert report._commissioning(before) == report._commissioning(after)
    sentence = dashboard._schedule_summary({'qualified_rnv': value['schedule']['qualification']},
                                          assessment, readiness_present=True)
    assert '31.05.2028' in sentence and '30.09.2027' not in sentence
    assert 'Прогноз РНВ не определён' in sentence


def test_text_uses_the_same_project_readiness_instead_of_the_old_duration_weighted_percentage():
    value = report_value()
    value.update(project='Учебный проект', kind='week', start='2026-11-09',
                 physical=dict(state='ok', fact=.9, plan=.8))
    text = report.render_text(value)
    assert 'Готовность по ГПР: 40,0%' in text
    assert 'Выполнено по графику работ 90' not in text


@pytest.mark.parametrize('fault', ['unknown_finish', 'cut', 'source', 'selected_future_profile'])
def test_missing_or_foreign_assessment_never_falls_back_to_the_legacy_plan(fault):
    value = report_value()
    state = value['gantt']['readiness']
    if fault == 'unknown_finish':
        state['project']['forecast'] = {}
    elif fault == 'cut':
        value['end'] = '2026-11-16'
    elif fault == 'source':
        value['gantt']['approved_plan'] = dict(source_sha256='b'*64)
    else:
        state['profile_effective_from'] = '2026-11-16'
    before = copy.deepcopy(value)
    result = report._executive_schedule(value)
    assert result['forecast'] is None and result['rnv_forecast'] is None
    assert value == before
    assessment = summary.project_assessment(value['gantt'], value['end'])
    sentence = dashboard._schedule_summary({'qualified_rnv': value['schedule']['qualification']},
                                          assessment, readiness_present=True)
    assert '30.09.2027' not in sentence


def test_legacy_only_summary_still_has_its_original_qualified_scope():
    value = report_value()
    del value['gantt']['readiness']
    assert report._executive_schedule(value) == value['construction_summary']


@pytest.mark.parametrize('width', [390, 1440])
def test_unconfirmed_quantities_do_not_gain_a_forecast_from_the_separate_gpr_display(
        gpr_sources, monkeypatch, width):
    """Keep the physical unknown, but show the dated original GPR consistently."""
    import fitz
    import developaid_monitor as monitor
    from test_schedule_physical_print_summary import PROJECT, CUT as cut
    payload = gpr_sources('unconfirmed')
    frozen = copy.deepcopy(payload)
    physical = payload['construction_summary']
    assert physical['source_status']['state'] == 'unconfirmed'
    assert physical['facts'] == [] and physical['forecast'] is None
    selected = report._executive_schedule(payload)
    assert selected['forecast'] == '2026-11-18'
    assert selected['gpr_assessment']['method'] == 'conditional'
    assert selected['rnv_forecast'] is None
    view = monitor.build(PROJECT, cut)
    assert view['schedule']['gpr_assessment']['finish'] == selected['forecast']
    assert view['schedule']['gpr_assessment']['progress'] is None
    assert view['schedule']['work_fact']['works']['1']['primary']['basis'] == 'gpr_percent'
    assert view['schedule']['physical_progress']['tasks'][0]['scope_confirmed'] is False
    assert next(t for t in report.tiles(payload) if t['label'] == selected['forecast_label'])['value'] == '18.11.2026'
    assert '18.11.2026' in report.render_text(payload)
    serve(monkeypatch, view)
    with browser_page(width) as (page, _, errors):
        show(page, view)
        expect(page.locator('#gprCalendarOverview')).to_contain_text('18.11.2026')
        expect(page.locator('#readinessSummary .gpr-legacy-fallback')).to_have_count(0)
        page.evaluate('(v)=>renderDash(v)', view)
        page.locator('#moneyTab').click()
        primary = page.locator('#gprProjectAssessment')
        expect(primary).to_be_visible()
        expect(primary.locator('.n')).to_have_text('18.11.2026')
        expect(primary).to_contain_text('При плановом темпе')
        rnv = page.locator('#kpis .kpi').filter(has=page.locator('.l', has_text='Прогноз РНВ'))
        expect(rnv.locator('.n')).to_have_text('—')
        page.set_content(report.render_html(payload))
        expect(page.locator('[data-gpr-block=forecast]>.rg-project-date')).to_have_text('18.11.2026')
        assert '50 из 100 м²' not in page.locator('.report-gpr-compact').inner_text()
        raw = page.pdf(format='A4')
        with fitz.open(stream=raw, filetype='pdf') as pdf:
            text = ' '.join(' '.join(p.get_text() for p in pdf).split())
        assert '18.11.2026' in text and 'При плановом темпе' in text
        assert not errors
    assert payload == frozen


def test_a_confirmed_rnv_and_credit_shift_are_not_replaced_by_the_selected_assessment():
    value = report_value()
    rnv = value['gantt']['dependency_timeline']['rnv']
    rnv.update(state='complete', forecast='2029-01-01')
    dashboard_value = dict(schedule=dict(qualified_rnv=copy.deepcopy(rnv)))
    commissioning = report._commissioning(dashboard_value)
    before = report._forecast_shift(dashboard_value, commissioning)
    frozen = copy.deepcopy(dashboard_value)
    result = report._executive_schedule(value)
    assert result['forecast'] == '2028-05-31' and result['rnv_forecast'] == '2029-01-01'
    assert before == report._forecast_shift(dashboard_value, commissioning)
    assert before['date'] == '2029-01-01' and dashboard_value == frozen


@pytest.mark.parametrize('counts,method,label', [
    ({'conditional': 2}, 'conditional', 'При плановом темпе'),
    ({'measured': 2}, 'measured', 'По измеренному темпу'),
    ({'conditional': 1, 'measured': 1}, 'mixed', 'Измеренный и плановый темп'),
    ({'complete': 2}, 'complete', 'Завершено по источникам'),
    ({'conditional': True}, 'unknown', 'Основание срока не определено'),
    ([], 'unknown', 'Основание срока не определено')])
def test_method_is_copied_from_source_evidence_not_inferred_from_the_date(counts, method, label):
    value = block()
    value['readiness']['project']['forecast']['explanation'] = dict(counts=counts)
    result = summary.project_assessment(value, CUT)
    assert result['method'] == method and result['method_label'] == label
    assert label in result['forecast_text']
    assert result['finish'] == '2028-05-31'


@pytest.mark.parametrize('field,bad', [('approved_plan', ['bad']), ('forecast', ['bad']),
                                     ('source_dates', None), ('profile_effective_from', 123)])
def test_malformed_metadata_cannot_raise_or_import_another_snapshot(field, bad):
    value = block()
    if field == 'approved_plan': value[field] = bad
    elif field == 'forecast': value['readiness']['project'][field] = bad
    elif field == 'source_dates': value['readiness']['project'][field] = bad
    else: value['readiness'][field] = bad
    assert summary.project_assessment(value, CUT) is None


def test_future_latest_profile_does_not_invalidate_the_selected_historical_profile():
    value = block()
    value['readiness'].update(profile_effective_from=CUT, latest_profile_effective_from='2038-01-01')
    assert summary.project_assessment(value, CUT)['finish'] == '2028-05-31'


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('old_ticket', [False, True])
def test_native_monitor_primary_date_and_clear_follow_the_same_scoped_assessment(monkeypatch, width, old_ticket):
    view = why_view()
    schedule = view['schedule']
    schedule['gpr_assessment'] = summary.project_assessment(schedule, view['cut'])
    if old_ticket:
        del schedule['gpr_assessment']
    view['dashboard'] = dict(schedule=dict(qualified_rnv=schedule['dependency_timeline']['rnv']))
    serve(monkeypatch, view)
    with browser_page(width) as (page, _, errors):
        show(page, view)
        page.evaluate('(v)=>renderDash(v)', view)
        primary = page.locator('#gprProjectAssessment')
        expect(primary.locator('.n')).to_have_text(summary.date_text(schedule['readiness']['project']['forecast']['finish']))
        expect(primary).to_contain_text('Учтённый состав: 3 работ')
        rnv = page.locator('#kpis .kpi').filter(has=page.locator('.l', has_text='Прогноз РНВ'))
        expect(rnv.locator('.n')).to_have_text('—')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.evaluate('clearReadiness()')
        expect(primary).to_have_count(0)
        assert page.evaluate('currentView.schedule.gpr_assessment==null')
        assert not errors


def test_an_invalid_explicit_new_assessment_does_not_use_the_old_ticket_fallback(monkeypatch):
    view = why_view()
    schedule = view['schedule']
    schedule['gpr_assessment'] = summary.project_assessment(schedule, view['cut'])
    schedule['gpr_assessment']['source_sha256'] = 'b'*64
    view['dashboard'] = dict(schedule=dict(qualified_rnv=schedule['dependency_timeline']['rnv']))
    serve(monkeypatch, view)
    with browser_page(390) as (page, _, errors):
        show(page, view)
        page.evaluate('(v)=>renderDash(v)', view)
        expect(page.locator('#gprProjectAssessment .n')).to_have_text('—')
        expect(page.locator('#gprProjectAssessment')).to_contain_text('не подтверждена')
        assert not errors
