"""Native partial uncertainty requires an explicit source translation boundary."""
import copy
import pytest
import developaid_management_report as report
import developaid_schedule_plan_scenario as scenario
from test_management_calendar_membership import _native_scoped_view
from test_schedule_summary_identity import full_state, record, DAY


def _outside_view():
    full={key:record(key) for key in ('outside','remaining')}
    current={'live':record('live')}
    state=full_state(full,current,{'remaining':'live'},outside=['outside'])
    rows=[dict(current['live'],level='task',plan_start='2026-10-01',plan_finish='2027-01-01',
        plan_pace_scenario=dict(finish='2027-04-01',source_date='2026-11-06'))]
    scenario.decorate_readiness(state,rows)
    assert state['forecast_identity']['remaining_ids']['outside'] is None
    assert state['project']['forecast']['id_scope']=='full_source'
    return dict(cut=DAY,schedule=dict(rows=rows,undated_works=[],readiness=state,
        management=[dict(level='control',name='Full source',children=copy.deepcopy(rows))]))


@pytest.mark.parametrize('fault',[None,'missing_mapping'])
def test_unclassified_native_gap_requires_present_translation_key(fault):
    view=_native_scoped_view(classification=None)
    if fault:view['schedule']['readiness']['forecast_identity']['remaining_ids'].pop('other')
    _assert_boundary(view,fault is None)


@pytest.mark.parametrize('fault',[None,'current_source'])
def test_outside_native_gap_requires_full_source_namespace(fault):
    view=_outside_view();state=view['schedule']['readiness'];forecast=state['project']['forecast']
    if fault:
        for dto in [state['forecast_identity'],forecast,forecast['display']]:dto['id_scope']='current_source'
    _assert_boundary(view,fault is None)


def _assert_boundary(view,valid):
    before=copy.deepcopy(view);block=report.gantt(view,{})
    body=report._gantt_html(dict(gantt=block,end=view['cut']))
    assert not block['calendar']['qualified'] and block['calendar']['issues']
    assert block['calendar']['points'] and len(block['calendar']['rows'])==len(view['schedule']['rows'])
    assert body.count('<article class="cg-work"')==0
    assert body.count('data-gpr-block=')==3
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    if valid:assert block['readiness']==view['schedule']['readiness']
    else:assert block['readiness']['project']['forecast']=={}
    assert view==before
