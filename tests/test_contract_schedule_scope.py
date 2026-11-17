"""A matched remainder is not a whole-contract forecast or completion claim."""
import copy

import pytest

import developaid_contract_control as control
import developaid_contract_files as files


CUT = '2026-02-01'
SHA = 'b' * 64


def listed(source_works=3, *, source_known=True, outside=0):
    line = {'code': '1', 'name': 'Учебная работа', 'start': '2026-01-01',
            'finish': '2026-01-30', 'amount': 1000, 'planned': 1000,
            'volume': {'unit': 'м3', 'quantity': 100}}
    current = {'in_force': True, 'start': '2026-01-15', 'lines': [line],
               'total': 1000, 'planned': 1000, 'date': '2026-01-15',
               'title': 'Учебная редакция', 'schedule_sha256': SHA,
               'outside': {'review': {'count': outside, 'amount': outside * 100}},
               'without_amount': 0, 'accepted_without_amount': 0}
    fact = {'note': '', 'source': 'ks2', 'review': [], 'unread': [],
            'before': {'start': '2026-01-15', 'count': 2, 'amount': 200, 'unpriced': 0},
            'lines': [{'code': '1', 'fact': 100, 'volumes': [{'unit': 'м3', 'quantity': 10}],
                       'last': '2026-01-20', 'complete': False}]}
    source = {'sha256': SHA, 'title': 'Учебный ГПР', 'contract': {'number': 'Т-1', 'date': '2026-01-01'},
              'schedule': {'lines': [{'code': str(i + 1), 'name': 'Учебная работа', 'parent': None,
                                       'start': '2026-01-01', 'finish': '2026-01-30'}
                                      for i in range(source_works)]}}
    return {'contract_id': 'c' * 64, 'documents': [source] if source_known else [],
            'plan': {'editions': [current]}, 'fact': fact}


def test_source_coverage_reaches_control_without_changing_the_measured_amounts():
    value = listed()
    before = control.build(value['plan'], value['fact'], None, '', CUT)
    got = files._with_control(value, None, CUT)
    c = got['control']
    assert {k: v for k, v in c['total'].items() if k != 'incomplete'} == {
        k: v for k, v in before['total'].items() if k != 'incomplete'}
    assert not before['total']['incomplete'] and c['total']['incomplete']
    assert c['coverage'] == got['comparison']['coverage']
    assert c['coverage']['calculated'] == 1 and c['coverage']['source_works'] == 3
    assert c['coverage']['unknown'] == 2 and c['coverage']['partial']
    assert c['coverage']['calculation_start'] == '2026-01-15'
    assert c['coverage']['prior_periods'] == 2
    assert c['forecast']['finish'] == before['forecast']['finish']
    assert c['forecast']['scope'] == 'matched_works'
    assert c['forecast']['whole_contract_finish'] is None


def test_register_uses_the_card_coverage_and_keeps_financial_unknowns(monkeypatch):
    value = files._with_control(listed(), None, CUT)
    monkeypatch.setattr(files, 'listing', lambda *a, **k: copy.deepcopy(value))
    row = {'id': 'c' * 64, 'physical_items': [], 'amount': 5000, 'completed': 4500,
           'amount_basis': 'with_vat', 'completed_basis': 'unspecified',
           'completion_ratio': None, 'monetary_comparable': False}
    before = copy.deepcopy(row)
    got = files._register_control_raw('Учебный', {'rows': [row]}, CUT)['rows'][0]
    assert {k: v for k, v in got.items() if k != 'schedule_control'} == before
    c = got['schedule_control']
    assert c['coverage'] == value['comparison']['coverage']
    assert c['incomplete'] and c['forecast_scope'] == 'matched_works'
    assert c['whole_contract_finish'] is None
    assert c['fact'] == value['control']['total']['fact']
    assert c['finish'] == value['control']['forecast']['finish']


def test_complete_known_scope_can_supply_the_whole_contract_finish():
    got = files._with_control(listed(source_works=1), None, CUT)
    assert not got['comparison']['coverage']['partial']
    assert not got['control']['total']['incomplete']
    assert got['control']['forecast']['whole_contract_finish'] == got['control']['forecast']['finish']


@pytest.mark.parametrize('missing', ['source', 'unmatched_positions', 'unknown_amount'])
def test_absent_source_or_unmatched_estimate_positions_do_not_prove_full_scope(missing):
    value = listed(source_works=1, source_known=missing != 'source', outside=int(missing == 'unmatched_positions'))
    if missing == 'unknown_amount':
        value['plan']['editions'][0]['without_amount'] = 1
    got = files._with_control(value, None, CUT)
    assert got['control']['forecast']['finish'] is not None
    assert got['control']['forecast']['whole_contract_finish'] is None
