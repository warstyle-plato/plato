"""A selected reference cannot disappear from the report calendar silently."""
import copy
import html
import re

import pytest

import developaid_management_report as report
import developaid_report_gantt as gantt
import developaid_schedule_plan_scenario as scenario
from test_gpr_why_page import why_view
from test_schedule_summary_identity import full_state, record, DAY


def _render(view):
    block=report.gantt(view,{})
    return block,report._gantt_html({'gantt':block,'end':view['cut']})


def _closed(view):
    before=copy.deepcopy(view);block,body=_render(view)
    model=block['calendar']
    assert model['qualified'] is False and model['issues']
    assert len(model['rows'])==len(view['schedule']['rows'])+len(view['schedule']['undated_works'])
    assert body.count('<article class="cg-work"')==0
    assert body.count('data-gpr-block=')==3
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert 'class="readiness-project-forecast"'not in body and block['readiness']['project']['forecast']=={}
    assert 'Подробные работы и источники — в Мониторе' in body
    assert view==before
    return model,body


@pytest.mark.parametrize('mutation',['missing_translation_and_point','null_translation_and_point','reference_count','duplicate_reference','mapping_collision'])
def test_selected_membership_gaps_never_turn_into_outside_work(mutation):
    view=why_view();state=view['schedule']['readiness'];display=state['project']['forecast']['display']
    first,second,third=copy.deepcopy(display['rows'])
    if mutation.startswith('missing'):
        display['rows'].pop(0);state['forecast_identity']['remaining_ids'].pop(first['reference_work_id'])
    elif mutation.startswith('null'):
        display['rows'].pop(0);state['forecast_identity']['remaining_ids'][first['reference_work_id']]=None
    elif mutation=='reference_count':state['project']['total']+=1
    elif mutation=='duplicate_reference':state['project']['work_ids'].append(first['reference_work_id'])
    else:state['forecast_identity']['remaining_ids'][second['reference_work_id']]=first['work_id']
    model,body=_closed(view)
    # An invalid owned DTO cannot retain points from the earlier population.
    assert model['points']=={}
    assert third['work_id'] in {row['task']['id'] for row in model['rows']}
    assert 'class="rg-forecast"' not in body
    if mutation in {'missing_translation_and_point','null_translation_and_point'}:
        assert first['reference_work_id']in state['project']['work_ids']



def _native_scoped_view(classification=False, separate=False):
    full={'build':record('build'),'other':record('other',construction=classification,obj='Корпус 2'if separate else'Корпус 1')}
    state=full_state(full,full,{key:key for key in full},
        assignments={'build':dict(element_id='frame',share=100)},
        objects={'Корпус 1':'residential','Корпус 2':'separate'}if separate else None)
    rows=[dict(row,level='task',plan_start='2026-10-01',plan_finish='2027-01-01'if key=='build'else'2038-01-01',
        plan_pace_scenario=dict(finish='2027-03-01'if key=='build'else'2038-01-01',source_date='2026-11-06'),
        gpr_progress=.5,gpr_progress_date='2026-11-06')for key,row in full.items()]
    scenario.decorate_readiness(state,rows)
    tree=[dict(level='control',name='Исходный раздел',children=[dict(level='detail',name='Исходный этап',children=copy.deepcopy(rows))])]
    view=dict(cut=DAY,schedule=dict(cut=DAY,
        approved_plan=dict(source_sha256=state['source_sha256']),
        rows=rows,undated_works=[],management=tree,readiness=state))
    from developaid_gpr_work_forecast import for_schedule
    view['schedule']['work_forecast_applicable']=True
    view['schedule']['work_forecast']=for_schedule(view['schedule'],DAY)
    return view


@pytest.mark.parametrize('separate',[False,True])
def test_native_source_attested_exclusion_keeps_the_valid_selected_projection(separate,monkeypatch):
    view=_native_scoped_view(separate=separate);state=view['schedule']['readiness']
    expected='separate_scope'if separate else'nonconstruction_scope'
    assert state['forecast_scope']['other']==dict(status='excluded',reason=expected)
    assert state['project']['forecast']['excluded']==[dict(work_id='other',kind=expected)]
    assert state['project']['work_ids']==['build','other']
    assert state['project']['forecast']['reference_total']==2 and state['project']['forecast']['total']==1
    before=copy.deepcopy(view)
    def forbidden(*a,**kw):raise AssertionError('presentation recalculated membership or forecast')
    monkeypatch.setattr(scenario,'work',forbidden);monkeypatch.setattr(scenario,'group',forbidden)
    block,body=_render(view);model=block['calendar']
    assert model['qualified'] is True and not model['issues']
    assert set(model['points'])=={'build'}and len(model['rows'])==2
    assert 'class="rg-project-line"'in body and body.count('data-gpr-block=')==3
    assert 'Вне выбранного состава'in body or 'вне выбранного состава'in body
    assert '2038'not in body and view==before


def test_native_unclassified_scope_remains_a_named_unresolved_reference():
    view=_native_scoped_view(classification=None);state=view['schedule']['readiness']
    assert state['forecast_scope']['other']==dict(status='gap',reason='unclassified_scope')
    assert state['project']['forecast']['gaps']==[dict(work_id='other',remaining_id=None,kind='unclassified_scope')]
    before=copy.deepcopy(view);block,body=_render(view);model=block['calendar']
    assert model['qualified'] and not model['issues'] and len(model['rows'])==2
    assert set(model['points'])=={'build'}
    assert {row['task']['id'] for row in model['rows']}=={'build','other'}
    owner=view['schedule']['work_forecast']
    assert owner['state']=='partial'
    assert owner['missing_members']==[dict(reference_work_id='other',work_id='other',reason='unclassified_scope')]
    assert owner['outside_members']==[]
    compact=report._report_gpr_compact(dict(gantt=block,end=DAY))
    assert compact['total']==2 and compact['covered']==1
    assert sum(group.get('outside',0) for group in compact['groups'])==0
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    assert block['readiness']==state and view==before


@pytest.mark.parametrize('mutation',['missing_attestation','contradicting_scope','duplicate_exclusion','malformed_kind','malformed_reason'])
def test_an_unattested_or_contradictory_exclusion_cannot_shrink_the_selected_denominator(mutation):
    view=_native_scoped_view();state=view['schedule']['readiness'];forecast=state['project']['forecast']
    if mutation=='missing_attestation':forecast['excluded']=[]
    elif mutation=='contradicting_scope':state['forecast_scope'].pop('other')
    elif mutation=='duplicate_exclusion':forecast['excluded'].append(copy.deepcopy(forecast['excluded'][0]))
    elif mutation=='malformed_kind':forecast['excluded'][0]['kind']=[]
    else:state['forecast_scope']['other']['reason']=[]
    model,_=_closed(view)
    assert model['points']=={}
    assert 'build' in {row['task']['id'] for row in model['rows']}
