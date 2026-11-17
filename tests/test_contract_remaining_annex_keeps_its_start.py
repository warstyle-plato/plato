"""Updating an explicitly identified remaining annex must not discard its earlier KS volumes."""
import copy

import pytest

import developaid_contract_files as files
import developaid_contract_fact as fact
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links


def record(letter, day, *scopes, annex='1.2', explicit=True):
    agreement = {'number': str(ord(letter)-ord('a')+1), 'date': day}
    return {'sha256': letter*64, 'title': f'Учебное соглашение {letter}',
            'contract': {'number': 'ТЕСТ', 'date': '2026-01-01'}, 'agreement': agreement,
            'estimates': [{'scope': scope, 'annex': '1.1' if scope == 'accepted' else annex,
                           'edition': agreement if explicit else None,
                           'links': {'schedule_sha256': '', 'positions': []}}
                          for scope in scopes]}


def test_new_edition_of_remaining_annex_retains_earlier_work_and_its_source():
    first = record('a', '2026-02-01', 'accepted', 'remaining')
    later = record('b', '2026-04-01', 'remaining')
    before = copy.deepcopy([first, later])
    editions = files._editions([first, later], {})
    assert [e['start'] for e in editions] == ['2026-02-01', '2026-02-01']
    assert editions[-1]['date'] == '2026-04-01'
    assert editions[-1]['start_source'] == {'date': '2026-02-01', 'sha256': 'a'*64,
                                           'title': 'Учебное соглашение a'}
    assert [first, later] == before


@pytest.mark.parametrize('change', ['accepted', 'annex', 'missing_edition', 'full', 'mixed'])
def test_new_accepted_snapshot_or_unproven_continuity_starts_a_new_remaining_plan(change):
    first = record('a', '2026-02-01', 'accepted', 'remaining')
    middle = record('b', '2026-03-01', 'full') if change == 'full' else None
    later = record('c', '2026-04-01', *(['accepted', 'remaining'] if change == 'accepted' else
                                     ['full', 'remaining'] if change == 'mixed' else ['remaining']),
                   annex='2.2' if change == 'annex' else '1.2', explicit=change != 'missing_edition')
    editions = files._editions([first, *([middle] if middle else []), later], {})
    assert editions[-1]['start'] == '2026-04-01'
    assert editions[-1]['start_source']['sha256'] == later['sha256']


def test_separate_accepted_snapshot_of_the_same_agreement_resets_the_start():
    first = record('a', '2026-02-01', 'accepted', 'remaining')
    later = record('b', '2026-04-01', 'remaining')
    accepted = {**record('b', '2026-04-01', 'accepted'), 'sha256': 'c'*64}
    assert files._editions([first, later, accepted], {})[-1]['start'] == '2026-04-01'


def test_a_schedule_update_keeps_the_remaining_estimate_start():
    first = record('a', '2026-02-01', 'accepted', 'remaining')
    schedule = record('b', '2026-04-01')
    schedule['schedule'] = {'lines': [{'code': '1', 'start': '2026-02-01', 'finish': '2026-05-01'}]}
    # A schedule-only edition carries links separately; this assertion isolates the start provenance.
    starts = files._remaining_starts([first, schedule])
    assert starts[first['sha256']]['date'] == '2026-02-01'
    assert schedule['sha256'] not in starts


def test_ks_volume_between_remaining_editions_still_counts_after_the_later_agreement():
    first = record('a', '2026-02-01', 'accepted', 'remaining')
    later = record('b', '2026-04-01', 'remaining')
    first['schedule'] = {'lines': [{'code': '1', 'name': 'Стены', 'start': '2026-02-01',
                                    'finish': '2026-04-30', 'parent': None}]}
    p = {'number': '1', 'name': 'Стены', 'unit': 'м3', 'quantity': 20,
         'unit_price': {'total': 100}, 'amount': {'total': 2000}}
    linked = {'key': links.position_key(p), 'number': '1', 'name': 'Стены', 'unit': 'м3',
              'quantity': 20, 'amount': 2000, 'status': 'confirmed', 'lines': [{'code': '1', 'share': 1}]}
    for doc in (first, later):
        for estimate in doc['estimates']:
            estimate['positions'] = [] if estimate['scope'] == 'accepted' else [p]
            estimate['links'] = {'schedule_sha256': first['sha256'],
                                 'positions': [] if estimate['scope'] == 'accepted' else [linked]}
    editions = files._editions([first, later], {})
    planned = plan.build(editions, '2026-04-15')
    performed = {'positions': [{'number': '1', 'name': 'Стены', 'unit': 'м3', 'parts': [
        {'quantity': 5, 'amount': 500, 'day': '2026-03-15', 'act': '1', 'name': 'Стены',
         'preliminary': False}]}]}
    result = fact.build(editions, planned['in_force'], None, '2026-04-15', performed)
    assert result['total'] == 500
    assert result['lines'][0]['volumes'] == [{'unit': 'м3', 'quantity': 5}]
    assert result['before']['start'] == '2026-02-01' and result['before']['count'] == 0


def test_missing_acts_are_explicit_dated_summary_entries_with_full_numbers():
    performed = {'acts': [{'number': '№ 02'}, {'number': '1/2026'}]}
    found = {'summary_acts': [{'number': '1', 'date': '2026-03-01'},
                              {'number': '02', 'date': '2026-04-01'},
                              {'number': '1/2025', 'date': '2026-01-01'},
                              {'number': '1/2026', 'date': '2026-04-01'},
                              {'number': '5', 'date': '2026-05-01'},
                              {'number': '9', 'date': '2026-12-01'},
                              {'number': '7', 'date': None}]}
    assert fact._missing_acts(performed, found, '2026-06-01') == ['1', '1/2025', '5']
