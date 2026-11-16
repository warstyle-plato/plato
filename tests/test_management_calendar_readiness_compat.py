"""An unavailable calendar is distinct from a contradicted native forecast."""
import copy
import pytest
import developaid_management_report as report
from test_management_calendar_membership import _native_scoped_view
from test_schedule_executive_readability import dense_schedule,executive_html


def render(view):
    block=report.gantt(view,{})
    return block,report._gantt_html({'gantt':block,'end':view['cut']})


@pytest.mark.parametrize('fault',[None,'missing_gap','remaining','kind','counts','bad_point'])
def test_attested_partial_readiness_never_excuses_other_projection_corruption(fault):
    view=_native_scoped_view(classification=None);state=view['schedule']['readiness'];forecast=state['project']['forecast']
    if fault=='missing_gap':forecast['gaps']=[]
    elif fault=='remaining':forecast['gaps'][0]['remaining_id']='foreign'
    elif fault=='kind':forecast['gaps'][0]['kind']='missing_identity_translation'
    elif fault=='counts':forecast['covered']=forecast['display']['covered']=2
    elif fault=='bad_point':forecast['display']['rows'][0]['finish']='2044-01-01'
    before=copy.deepcopy(view);block,body=render(view)
    assert not block['calendar']['qualified'] and len(block['calendar']['rows'])==2
    assert 'gpr-scoped-finish"'not in body and 'gpr-analysis-paragraph'not in body
    if fault is None:assert block['readiness']==state
    else:assert block['readiness']['project']['forecast']=={}
    assert view==before


def test_absent_display_does_not_erase_an_independently_source_bound_forecast():
    view=_native_scoped_view(classification=None);state=view['schedule']['readiness']
    state['project']['forecast'].pop('display');before=copy.deepcopy(view)
    block,body=render(view)
    assert block['readiness']==state and not block['calendar']['qualified']
    assert 'gpr-scoped-finish"'not in body and view==before


@pytest.mark.parametrize('present',[{},None])
def test_only_absent_calendar_key_can_use_archival_corpus_compatibility(present):
    timeline,_,legacy=dense_schedule()
    old=executive_html(timeline,legacy)
    assert 'Архивная сводка по корпусам'in old and 'Корпус 4'in old
    assert 'class="schedule-lane"'in old
    modern=copy.deepcopy(legacy);modern['calendar']=present
    body=executive_html(timeline,modern)
    assert 'Архивная сводка по корпусам'not in body and 'class="schedule-lane"'not in body
    assert 'нет полного перечня работ'in body and '16.02.2027'in body


def test_unavailable_full_roster_does_not_erase_independently_source_bound_readiness():
    view=_native_scoped_view(classification=None);state=copy.deepcopy(view['schedule']['readiness'])
    view['schedule'].update(rows=[],management=[],undated_works=[])
    block,body=render(view)
    assert block['readiness']==state and not block['calendar']['qualified']
    assert not block['calendar']['rows'] and 'gpr-scoped-finish"'not in body
    assert 'class="schedule-lane"'not in body and 'Архивная сводка'not in body
