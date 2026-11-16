"""Incomplete physical location never proves a second additive work budget."""
import copy

import pytest

from developaid_contract_detail_history import compose, _compatible_scope
from test_contract_detail_history import CUT, period, source, view


@pytest.mark.parametrize('missing', [
    {'scope': ''}, {'section_path': []}, {'context_headings': []},
    {'scope': '', 'section_path': [], 'context_headings': []},
])
@pytest.mark.parametrize('reverse', [False, True])
def test_missing_then_supplied_row_context_is_unknown_without_merging_raw_groups(missing, reverse):
    a, b = view(period(1), **missing), view(period(1))
    if reverse:
        a, b = b, a
    inputs = [source('2026-04-01', a), source('2026-05-01', b, sha='b')]
    before = copy.deepcopy(inputs)
    result = compose(inputs, CUT)
    assert len(result['items']) == 2
    for item in result['items']:
        assert item['detail_history_state'] == 'unknown' and 'scope' in item['detail_history_problems']
        assert all(item[field] is None for field in ('completed_amount', 'completed_quantity',
            'plan_quantity', 'planned_amount', 'planned_work_amount', 'planned_material_amount'))
        assert item['completion_ratio'] is None and item['planned_cost_split'] is False
        assert item['history_sources'] and item['periods']
        assert item['history_sources'][0]['view'] in (a, b)
    assert inputs == before and any('Область работ' in note for note in result['warnings'])


@pytest.mark.parametrize('reverse', [False, True])
def test_exact_partial_section_and_retained_context_are_ambiguous_not_an_extra_plan(reverse):
    a = view(period(1), scope='', section_path=[{'name': 'Корпус 1'}],
             context_headings=['Корпус 1', 'Система А'])
    b = view(period(2), section_path=[{'name': 'Корпус 1'}, {'name': 'Этаж 2'}],
             context_headings=['Корпус 1', 'Этаж 2', 'Система А'])
    if reverse:
        a, b = b, a
    result = compose([source('2026-04-01', a), source('2026-05-01', b, sha='b')], CUT)
    assert len(result['items']) == 2
    assert all(item['detail_history_state'] == 'unknown' for item in result['items'])
    assert all(item['planned_amount'] is None and item['completed_amount'] is None for item in result['items'])
    assert all(item['history_sources'] and item['periods'] for item in result['items'])


@pytest.mark.parametrize('changes', [
    {'scope': 'Этаж 3'},
    {'section_path': [{'name': 'Корпус 2'}, {'name': 'Этаж 2'}]},
    {'context_headings': ['Система Б']},
])
def test_contradictory_nonempty_locations_remain_independent_even_with_other_gaps(changes):
    a = view(period(1))
    b = view(period(1), **changes)
    inputs = [source('2026-04-01', a, system_scope=''), source('2026-05-01', b, sha='b')]
    result = compose(inputs, CUT)
    assert len(result['items']) == 2
    assert all(item['detail_history_state'] == 'known' for item in result['items'])
    assert sum(item['planned_amount'] for item in result['items']) == a['planned_amount'] + b['planned_amount']
    assert sum(item['completed_amount'] for item in result['items']) == a['completed_amount'] + b['completed_amount']


@pytest.mark.parametrize('changes', [{'position': '2.1'}, {'name': 'Монтаж другой стены'}, {'unit': 'м3'}])
def test_same_name_or_missing_location_does_not_merge_unrelated_work(changes):
    a = view(period(1), scope='', section_path=[], context_headings=[])
    b = view(period(1), **changes)
    result = compose([source('2026-04-01', a), source('2026-05-01', b, sha='b')], CUT)
    assert len(result['items']) == 2 and all(item['detail_history_state'] == 'known' for item in result['items'])


def test_ambiguous_zero_stays_unknown_while_original_zero_observations_survive():
    a = view(period(1, amount=0, quantity=0), scope='', section_path=[], context_headings=[])
    b = view(period(1, amount=0, quantity=0))
    result = compose([source('2026-04-01', a), source('2026-05-01', b, sha='b')], CUT)
    assert all(item['completed_amount'] is None and item['completed_quantity'] is None for item in result['items'])
    assert all(item['history_sources'][0]['view']['completed_amount'] == 0 for item in result['items'])


def test_context_compatibility_retains_exact_canonical_order_and_never_guesses_a_caption():
    first = ('', 'Корпус 1')
    second = ('', 'Этаж 2')
    third = ('', 'Система А')
    scope = ('Объект', 'Система', 'Участок', '', (first,))
    assert _compatible_scope((*scope, (first, third)), (*scope, (first, second, third)))
    assert not _compatible_scope((*scope, (third, first)), (*scope, (first, second, third)))
    assert not _compatible_scope((*scope, (first, ('', 'Система Б'))), (*scope, (first, second, third)))
