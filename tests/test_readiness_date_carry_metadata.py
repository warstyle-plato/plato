"""Missing proof metadata is not an unexpected exception or permission to carry."""
import copy
import datetime as dt

import pytest

import developaid_monitor as monitor
import developaid_readiness_date_carry as carry
import developaid_schedule_versions as versions

PARENT='1'*64
CHILD='2'*64
EVENT=dict(revision=1,source_sha256=PARENT,previous_source_sha256='0'*64,
    baseline_scope='remaining_work',effective_from='2034-01-01',approved_at='2034-01-01T12:00:00+00:00')
STATE=dict(revision=2,source_sha256=CHILD,baseline_scope='remaining_work',versions=[EVENT,
    dict(EVENT,revision=2,source_sha256=CHILD,previous_source_sha256=PARENT)])


def rejected(monkeypatch,state):
    monkeypatch.setattr(monitor,'_working_baseline_state',lambda project:state)
    monkeypatch.setattr(versions,'_read',lambda *args:pytest.fail('Unproven source was read'))
    with pytest.raises(carry.DateCarryProblem) as problem:carry.verified_transition('Synthetic metadata',CHILD)
    assert problem.value.code=='lineage'


@pytest.mark.parametrize('state',[None,False,[],{},
    {'path':'unused','source_sha256':CHILD,'baseline_scope':'remaining_work','taken_at':'2034-01-02'}])
def test_absent_journal_state_rejects_before_source_reads(monkeypatch,state):
    rejected(monkeypatch,state)


@pytest.mark.parametrize('field,value',[
    ('versions',None),('versions',{}),('versions',()),('versions',[]),
    ('versions',[None]),('versions',['invalid']),('versions',[{}]),
    ('versions',[EVENT,dict(EVENT,revision=True)]),
    ('versions',[EVENT,dict(STATE['versions'][1]),dict(STATE['versions'][1])]),
    ('versions',[STATE['versions'][1],EVENT]),
    ('versions',[EVENT,dict(STATE['versions'][1],revision=3)]),
    ('versions',[dict(EVENT,revision=2),dict(STATE['versions'][1],revision=3)]),
    ('versions',[EVENT]*(versions.MAX_VERSIONS+1)),
    ('revision',None),('revision',True),('revision',False),('revision',2.0),('revision','2'),
    ('revision',0),('revision',-1),('revision',3),('source_sha256',None),
    ('source_sha256','../outside'),('source_sha256','3'*64),('baseline_scope','full_schedule'),
])
def test_malformed_state_and_revision_sequence_reject_before_source_reads(monkeypatch,field,value):
    rejected(monkeypatch,{**copy.deepcopy(STATE),field:value})


@pytest.mark.parametrize('path',[(field,) for field in ('versions','revision','source_sha256','baseline_scope')]+[
    ('versions',index,field) for index in (0,1) for field in (
        'revision','source_sha256','previous_source_sha256','baseline_scope','effective_from','approved_at')])
def test_missing_adjacent_required_fields_have_a_typed_lineage_reason(monkeypatch,path):
    state=copy.deepcopy(STATE);parent=state
    for key in path[:-1]:parent=parent[key]
    del parent[path[-1]]
    rejected(monkeypatch,state)


@pytest.mark.parametrize('index',[0,1])
@pytest.mark.parametrize('field,value',[
    ('revision',True),('revision',1.0),('source_sha256',None),('source_sha256','invalid'),
    ('previous_source_sha256',None),('previous_source_sha256','../outside'),
    ('baseline_scope',None),('baseline_scope','full_schedule'),
    ('effective_from',None),('effective_from',True),('effective_from',dt.date(2034,1,1)),
    ('effective_from','invalid'),('effective_from',' 2034-01-01'),
    ('approved_at',None),('approved_at',True),('approved_at',123),('approved_at','invalid'),
    ('approved_at','2034-01-01'),('approved_at','2034-01-01T12:00:00+01:00'),
])
def test_malformed_adjacent_values_have_a_typed_lineage_reason(monkeypatch,index,field,value):
    state=copy.deepcopy(STATE);state['versions'][index][field]=value
    rejected(monkeypatch,state)
