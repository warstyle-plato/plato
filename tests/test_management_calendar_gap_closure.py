"""Native partial uncertainty requires an explicit source translation boundary."""
import copy
import pytest
import developaid_gpr_work_forecast as work_dates
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


@pytest.mark.parametrize('fault',[None,'missing_mapping','wrong_mapping'])
def test_unclassified_native_gap_requires_present_translation_key(fault):
    view=_native_scoped_view(classification=None)
    state=view['schedule']['readiness']
    assert state['forecast_identity']['remaining_ids']['other']=='other'
    if fault=='missing_mapping':
        state['forecast_identity']['remaining_ids'].pop('other')
    elif fault=='wrong_mapping':
        state['forecast_identity']['remaining_ids']['other']='build'
    if fault:
        _assert_rejected_native_owner(view)
        return
    before=copy.deepcopy(view);block=report.gantt(view,{})
    body=report._gantt_html(dict(gantt=block,end=view['cut']))
    owner=block['work_forecast'];calendar=block['calendar']
    assert owner==work_dates.for_schedule(view['schedule'],view['cut'])
    assert owner['state']=='partial' and owner['scope_kind']=='readiness_profile'
    assert owner['missing_members']==[dict(reference_work_id='other',work_id='other',reason='unclassified_scope')]
    assert owner['outside_members']==[] and 'other' not in owner['outside_points']
    forecast=owner['project']['forecast']
    assert forecast['reference_total']==forecast['total']==2
    assert forecast['covered']==1 and forecast['missing']==1 and forecast['excluded']==[]
    assert calendar['qualified'] and not calendar['issues'] and set(calendar['points'])=={'build'}
    assert [row['task'] for row in calendar['rows']]==view['schedule']['rows']
    compact=report._report_gpr_compact(dict(gantt=block,end=view['cut']))
    assert compact['qualified'] and compact['total']==2 and compact['covered']==1
    assert sum(group.get('outside',0) for group in compact['groups'])==0
    assert sum(group['total'] for group in compact['groups'])==2
    assert report._executive_schedule(dict(gantt=block,end=view['cut']))['rnv_forecast'] is None
    assert body.count('<article class="cg-work"')==0 and body.count('data-gpr-block=')==3
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert block['readiness']==state and view==before


@pytest.mark.parametrize('fault',['unattested_exclusion','shrunk_denominator'])
def test_unclassified_native_gap_cannot_be_excluded_or_removed_from_the_denominator(fault):
    view=_native_scoped_view(classification=None)
    forecast=view['schedule']['readiness']['project']['forecast']
    if fault=='unattested_exclusion':
        forecast['excluded']=[dict(work_id='other',kind='nonconstruction_scope')]
    else:
        forecast['total']=forecast['display']['total']=1
    _assert_rejected_native_owner(view)


def _assert_rejected_native_owner(view):
    before=copy.deepcopy(view);schedule=view['schedule']
    # Reject the invalid membership itself, as well as the stale compiled DTO.
    assert work_dates.build(schedule,view['cut'])['state']=='unavailable'
    rejected=work_dates.for_schedule(schedule,view['cut'])
    assert rejected['state']=='unavailable' and rejected['reason_code']=='dto_binding'
    block=report.gantt(view,{})
    calendar=block['calendar']
    assert not calendar['qualified'] and calendar['issues']
    assert calendar['points']=={} and calendar['display'] is None
    assert [row['task'] for row in calendar['rows']]==schedule['rows']
    assert [row['task']['id'] for row in calendar['rows']]==['build','other']
    assert block['readiness']['source_sha256']==schedule['approved_plan']['source_sha256']
    assert block['readiness']['project']['work_ids']==['build','other']
    assert block['readiness']['project']['forecast']=={}
    value=dict(gantt=block,end=view['cut'])
    compact=report._report_gpr_compact(value)
    assert not compact['qualified'] and not compact['assessment_qualified']
    assert compact['finish'] is None and compact['summary']['progress'] is None
    assert compact['matrix']==[]
    assert all(group['progress'] is None and group['finish'] is None for group in compact['groups'])
    assert report._report_gpr_summary(value) is None
    body=report._gantt_html(value)
    assert body.count('<article class="cg-work"')==0 and body.count('data-gpr-block=')==3
    assert 'class="rg-forecast"'not in body and 'class="rg-plan"'not in body
    assert body.count('data-project-forecast=""')==3
    assert 'class="readiness-project-value"'not in body
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert view==before


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
