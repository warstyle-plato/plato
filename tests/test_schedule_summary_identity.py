"""Readiness deadlines share the declared source identity and calendar scope."""
import copy

import pytest

import developaid_schedule_elements as elements
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as ready

DAY='2026-11-14'


def record(key, *, construction=True, obj='Корпус 1'):
    return dict(id=key,name='Synthetic '+key,object=obj,section='Конструктив',
                construction_work=construction,
                primary=dict(value=.5,date='2026-11-06',label='ГПР'))


def deadline(key, finish='2027-02-01'):
    return dict(id=key,forecast_known=False,forecast_finish='2039-01-01',
                plan_pace_scenario=dict(finish=finish,source_date='2026-11-06'))


def full_state(full, current, links, *, outside=(), assignments=None, objects=None):
    assignments=assignments or {key:dict(element_id='frame',share=100/len(full)) for key in full}
    config=dict(id=elements.PROFILE_ID,
        overrides={key:100 if key=='frame' else 0 for key,_,_ in elements.ELEMENTS},
        objects=objects or {'Корпус 1':'residential'},assignments=assignments)
    profile=dict(scope_kind='construction',basis='estimated_elements',full_scope_confirmed=True,
        full_source_sha256='b'*64,remaining_source_sha256='a'*64,effective_from='2026-11-01',
        crosswalk=[dict(full_id=f,remaining_id=r)for f,r in links.items()],
        outside_completed_ids=list(outside),included_ids=list(full),excluded_ids=[],
        weights=[dict(full_id=k,value=100/len(full))for k in full],element_profile=config,
        label='Synthetic source',source_reference='Synthetic reference')
    return ready.model(dict(works=current),cut=DAY,baseline_scope='remaining_work',
        source_sha256='a'*64,profile=profile,full_rows=full)


def test_colliding_full_and_current_ids_follow_crosswalk_without_mutating_facts():
    full={key:record(key)for key in ('1','2')}
    current={key:record(key)for key in ('2','3')}
    state=full_state(full,current,{'1':'2','2':'3'})
    rows=[deadline('2','2027-02-01'),deadline('3','2027-08-01')]
    before=copy.deepcopy(rows)
    scenario.decorate_readiness(state,rows)
    assert state['forecast_identity']['remaining_ids']=={'1':'2','2':'3'}
    assert state['project']['forecast']['finish']=='2027-08-01'
    assert state['project']['forecast']['covered']==2
    assert state['project']['forecast']['total']==2
    assert state['project']['forecast']['full_source_sha256']=='b'*64
    assert rows==before


@pytest.mark.parametrize('problem,kind',[
    ('missing_row','missing_current_work'),('duplicate_row','ambiguous_current_identity'),
    ('missing_translation','missing_identity_translation'),
    ('duplicate_translation','ambiguous_identity_translation')])
def test_incomplete_or_ambiguous_membership_stays_in_the_denominator(problem,kind):
    full={key:record(key)for key in ('f1','f2')}
    state=full_state(full,{key:record(key)for key in ('r1','r2')},{'f1':'r1','f2':'r2'})
    rows=[deadline('r1'),deadline('r2','2027-08-01')]
    if problem=='missing_row':rows.pop()
    elif problem=='duplicate_row':rows.append(deadline('r2','2035-01-01'))
    elif problem=='missing_translation':state['forecast_identity']['remaining_ids'].pop('f2')
    else:state['forecast_identity']['remaining_ids']['f2']='r1'
    scenario.decorate_readiness(state,rows)
    result=state['project']['forecast']
    assert result['total']==2 and result['covered']<2
    assert any(g['kind']==kind for g in result['gaps'])
    assert not result['all_complete']
    assert result['finish'] in (None,'2027-02-01')


def test_confirmed_outside_primary100_is_a_calendar_gap_without_an_actual_finish():
    full={key:record(key)for key in ('outside','remain')}
    state=full_state(full,{'r':record('r')},{'remain':'r'},outside=['outside'])
    scenario.decorate_readiness(state,[deadline('r')])
    result=state['project']['forecast']
    assert result['total']==2 and result['covered']==1
    assert result['gaps']==[dict(work_id='outside',remaining_id=None,kind='outside_current_source')]
    assert not result['all_complete']
    assert 'actual_finish' not in result


@pytest.mark.parametrize('classification,expected_total,expected_finish,kind',[
    (False,1,'2027-02-01','nonconstruction_scope'),
    (None,2,'2027-02-01','unclassified_scope'),
    (True,2,'2035-01-01',None)])
def test_scope_does_not_infer_calendar_membership_from_a_weight(classification,expected_total,expected_finish,kind):
    full={'build':record('build'),'other':record('other',construction=classification)}
    state=full_state(full,full,{key:key for key in full},
        assignments={'build':dict(element_id='frame',share=100)})
    scenario.decorate_readiness(state,[deadline('build'),deadline('other','2035-01-01')])
    result=state['project']['forecast']
    assert result['total']==expected_total and result['finish']==expected_finish
    if classification is False:assert result['excluded']==[dict(work_id='other',kind=kind)]
    elif classification is None:assert any(g['kind']==kind for g in result['gaps'])
    else:assert result['covered']==2 and result['partial']


def test_plan_only_and_100_observation_never_become_an_actual_finish():
    rows=[record('plan'),record('done')]
    state=ready.model(dict(works={r['id']:r for r in rows}),cut=DAY,
        baseline_scope='remaining_work',source_sha256='a'*64)
    values=[dict(id='plan',forecast_known=False,forecast_finish='2039-01-01'),
            dict(id='done',work_done=True,observed_complete_by='2026-11-06',
                 forecast_known=True,forecast_finish='2026-11-06')]
    before=copy.deepcopy(values)
    scenario.decorate_readiness(state,values)
    result=state['project']['forecast']
    assert result['total']==2 and result['covered']==1 and result['finish'] is None
    assert result['gaps']==[dict(work_id='plan',remaining_id='plan',kind='unknown_time')]
    assert state['project']['progress'] is None and values==before
