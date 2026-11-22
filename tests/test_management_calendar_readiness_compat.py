"""An unavailable calendar is distinct from a contradicted native forecast."""
import copy
import pytest
import developaid_gpr_work_forecast as work_dates
import developaid_management_report as report
from test_gpr_work_forecast import fallback
from test_management_calendar_membership import _native_scoped_view
from test_monitor_gpr_sections import monitor_view
from test_schedule_executive_readability import dense_schedule,executive_html


def render(view):
    block=report.gantt(view,{})
    return block,report._gantt_html({'gantt':block,'end':view['cut']})


@pytest.mark.parametrize('fault',[None,'missing_gap','remaining','kind','counts','bad_point',
                                 'wrong_mapping','unattested_exclusion','shrunk_denominator'])
def test_attested_partial_readiness_never_excuses_other_projection_corruption(fault):
    view=_native_scoped_view(classification=None);state=view['schedule']['readiness'];forecast=state['project']['forecast']
    if fault=='missing_gap':forecast['gaps']=[]
    elif fault=='remaining':forecast['gaps'][0]['remaining_id']='foreign'
    elif fault=='kind':forecast['gaps'][0]['kind']='missing_identity_translation'
    elif fault=='counts':forecast['covered']=forecast['display']['covered']=2
    elif fault=='bad_point':forecast['display']['rows'][0]['finish']='2044-01-01'
    elif fault=='wrong_mapping':state['forecast_identity']['remaining_ids']['other']='build'
    elif fault=='unattested_exclusion':forecast['excluded']=[dict(work_id='other',kind='nonconstruction_scope')]
    elif fault=='shrunk_denominator':forecast['total']=forecast['display']['total']=1
    if fault:
        _assert_rejected_owner(view)
        return
    before=copy.deepcopy(view);block,body=render(view)
    owner=block['work_forecast'];calendar=block['calendar']
    assert owner==work_dates.for_schedule(view['schedule'],view['cut'])
    assert owner['state']=='partial' and owner['project']['forecast']['total']==2
    assert owner['project']['forecast']['covered']==1 and owner['project']['forecast']['missing']==1
    assert owner['missing_members']==[dict(reference_work_id='other',work_id='other',reason='unclassified_scope')]
    assert owner['outside_members']==[] and owner['project']['forecast']['excluded']==[]
    assert calendar['qualified'] and not calendar['issues'] and set(calendar['points'])=={'build'}
    assert [row['task'] for row in calendar['rows']]==view['schedule']['rows']
    value=dict(gantt=block,end=view['cut'])
    compact=report._report_gpr_compact(value)
    assert compact['qualified'] and compact['total']==2 and compact['covered']==1
    assert sum(group.get('outside',0) for group in compact['groups'])==0
    assert report._executive_schedule(value)['rnv_forecast'] is None
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert block['readiness']==state and view==before


def _assert_rejected_owner(view):
    before=copy.deepcopy(view);schedule=view['schedule']
    assert work_dates.build(schedule,view['cut'])['state']=='unavailable'
    rejected=work_dates.for_schedule(schedule,view['cut'])
    assert rejected['state']=='unavailable' and rejected['reason_code']=='dto_binding'
    block,body=render(view);calendar=block['calendar']
    assert not calendar['qualified'] and calendar['issues']
    assert calendar['points']=={} and calendar['display'] is None
    assert [row['task'] for row in calendar['rows']]==schedule['rows']+schedule['undated_works']
    state=copy.deepcopy(schedule['readiness']);state['project']['forecast']={}
    assert block['readiness']==state
    assert state['source_sha256']==schedule['approved_plan']['source_sha256']
    value=dict(gantt=block,end=view['cut']);compact=report._report_gpr_compact(value)
    assert not compact['qualified'] and not compact['assessment_qualified']
    assert compact['finish'] is None and compact['summary']['progress'] is None
    assert compact['matrix']==[]
    assert all(group['finish'] is None and group['progress'] is None for group in compact['groups'])
    assert report._report_gpr_summary(value) is None
    assert body.count('data-gpr-block=')==body.count('data-project-forecast=""')==3
    assert 'class="rg-forecast"'not in body and 'class="rg-plan"'not in body
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert view==before
    return block


@pytest.mark.parametrize('fault',['missing_display','missing_roster'])
def test_postcompile_native_transport_loss_rejects_the_owned_forecast(fault):
    view=_native_scoped_view(classification=None)
    if fault=='missing_display':
        view['schedule']['readiness']['project']['forecast'].pop('display')
    else:
        view['schedule'].update(rows=[],management=[],undated_works=[])
    _assert_rejected_owner(view)


def test_rejected_native_owner_keeps_a_known_zero_as_a_raw_source_fact():
    schedule=fallback();view=dict(cut=schedule['cut'],schedule=schedule)
    schedule['work_forecast_applicable']=True
    schedule['work_forecast']=work_dates.for_schedule(schedule,view['cut'])
    assert schedule['work_forecast']['state']!='unavailable'
    schedule['cut']='2035-04-09'
    block=_assert_rejected_owner(view)
    row=next(item['task'] for item in block['calendar']['rows'] if item['task']['id']=='building')
    assert row['display_progress']['value']==0
    assert row['display_progress']['date']=='2035-04-09'
    assert row['plan_start']=='2035-01-01' and row['plan_finish']=='2035-08-01'


def _legacy_source_view():
    view=monitor_view('estimate');schedule=view['schedule']
    assert schedule['work_forecast_applicable'] is False and 'work_forecast'not in schedule
    assert not work_dates.applies_to(schedule) and not work_dates.owns_response(schedule)
    assert all(row['source_format']=='legacy-gpr' for row in schedule['rows'])
    assert schedule['readiness']['project']['forecast']['finish']=='2026-12-20'
    assert schedule['rows'][1]['actual_progress']==0
    return view


def test_absent_display_does_not_erase_an_independently_source_bound_forecast():
    view=_legacy_source_view();state=view['schedule']['readiness']
    expected=copy.deepcopy(view['schedule']['legacy_work_forecast'])
    state['project']['forecast'].pop('display');before=copy.deepcopy(view)
    block,body=render(view)
    assert block['readiness']==state and not block['calendar']['qualified']
    assert not block['calendar']['readiness_forecast_invalid'] and block['calendar']['points']=={}
    assert [row['task'] for row in block['calendar']['rows']]==view['schedule']['rows']
    assert block['calendar']['rows'][1]['task']['actual_progress']==0
    summary=report._report_gpr_summary(dict(gantt=block,end=view['cut']))
    assert summary['finish']==expected['finish']=='2026-12-20' and summary['progress'] is None
    assert summary['cut']==view['cut'] and summary['source_sha256']==state['source_sha256']
    assert 'gpr-scoped-finish"'not in body and view==before


@pytest.mark.parametrize('present',[{},None])
def test_only_absent_calendar_key_can_use_archival_corpus_compatibility(present):
    timeline,_,legacy=dense_schedule()
    old=report._gantt_html({'gantt':legacy,'end':'2026-11-06'})
    assert 'Архивная сводка по корпусам'not in old and 'class="schedule-lane"'not in old
    assert old.count('data-gpr-block=')==3 and 'Пока не определён'in old
    modern=copy.deepcopy(legacy);modern['calendar']=present
    body=report._gantt_html({'gantt':modern,'end':'2026-11-06'})
    assert 'Архивная сводка по корпусам'not in body and 'class="schedule-lane"'not in body
    assert body.count('data-gpr-block=')==3 and 'Пока не определён'in body


def test_unavailable_full_roster_does_not_erase_independently_source_bound_readiness():
    view=_legacy_source_view();state=copy.deepcopy(view['schedule']['readiness'])
    expected=copy.deepcopy(view['schedule']['legacy_work_forecast'])
    view['schedule'].update(rows=[],management=[],undated_works=[])
    before=copy.deepcopy(view)
    block,body=render(view)
    assert block['readiness']==state and not block['calendar']['qualified']
    assert not block['calendar']['readiness_forecast_invalid'] and block['calendar']['points']=={}
    assert not block['calendar']['rows'] and 'gpr-scoped-finish"'not in body
    assert 'class="schedule-lane"'not in body and 'Архивная сводка'not in body
    summary=report._report_gpr_summary(dict(gantt=block,end=view['cut']))
    assert summary['finish']==expected['finish']=='2026-12-20' and summary['progress'] is None
    assert summary['cut']==view['cut'] and summary['source_sha256']==state['source_sha256']
    assert view==before
