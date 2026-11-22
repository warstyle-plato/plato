"""The parcel of the whole object is not a plot scope; landscape keeps its own matrix section."""
import datetime as dt

import pytest

import developaid_gpr_cumulative_matching as matching
import developaid_schedule_elements as elements
import developaid_schedule_work_fact as work_fact

WORK = 'Вырубка бетона из арматурного каркаса свай'
SECTION = ['Раздел № 2. Монолитные железобетонные конструкции Корпуса 1']


def ambiguous(label):
    return matching._descriptor(WORK, SECTION, [label, ''])['ambiguous']


@pytest.mark.parametrize('label', [
    'Строительство жилого комплекса на земельном участке с кадастровым номером 00:00:0000000:0',
    'Земельный участок с кадастровым номером 00:00:0000000:0',
    'Благоустройство земельных участков жилого комплекса',
])
def test_parcel_of_the_whole_object_is_not_a_plot_scope(label):
    assert not ambiguous(label)


@pytest.mark.parametrize('label', [
    'Работы на земельном участке, участок 2',
    'Строительство на участке 2',
    'Участок 3',
    'Строительство жилого дома, секция 3',
])
def test_a_named_plot_or_section_inside_the_object_stays_ambiguous(label):
    assert ambiguous(label)


def projection(rows, config):
    works = work_fact.model(rows, None)['works']
    entries = [dict(value, id=key, primary=value.get('primary') or {}) for key, value in works.items()]
    return elements.projection(entries, config, cut=dt.date(2026, 11, 1), confirmed=True)


ROWS = [
    dict(id='1', name='Благоустройство территории', object='Корпус 1', section='Наружные сети',
         construction_work=True, gpr_progress=40),
    dict(id='2', name='Наружные сети водопровода', object='Корпус 1', section='Наружные сети',
         construction_work=True, gpr_progress=10),
    dict(id='3', name='Согласование проекта', object='Корпус 1', section='Наружные сети',
         construction_work=False, gpr_progress=0),
    dict(id='4', name='Прочие работы', object='Корпус 1', section='Наружные сети', gpr_progress=0),
]


def test_work_fact_keeps_the_construction_flag_and_leaves_an_absent_flag_absent():
    works = work_fact.model(ROWS, None)['works']
    assert {key: value['construction_work'] for key, value in works.items()} == {
        '1': True, '2': True, '3': False, '4': None}


def test_landscape_from_the_corpus_gpr_has_its_own_matrix_section():
    state = projection(ROWS, dict(id='x', overrides={}, assignments={}, objects={}))
    stages = {stage['stage']: [name for cell in stage['cells'] for name in cell.get('work_ids') or []]
              for stage in state['matrix']}
    assert 'Благоустройство' in stages
    # Only the declared landscape work moves; the networks stay in their section.
    assert stages['Благоустройство'] == ['1']
    assert '2' in stages['Наружные сети']


def test_calendar_scope_reads_the_flag_instead_of_calling_every_work_unclassified():
    scope = projection(ROWS, dict(id='x', overrides={}, assignments={}, objects={}))['forecast_scope']
    assert scope == {'3': dict(status='excluded', reason='nonconstruction_scope'),
                     '4': dict(status='gap', reason='unclassified_scope')}
