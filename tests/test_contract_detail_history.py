"""Incremental KS detail preserves periods, revisions and their source proof."""
from __future__ import annotations

import calendar
import copy

import pytest

from developaid_contract_detail_history import compose

CUT = '2026-12-31'


def period(month, amount=100, *, quantity=1, year=2026, label=None):
    return {'label': label or f'Месяц {month}',
            'date_start': f'{year}-{month:02d}-01',
            'date_end': f'{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}',
            'quantity': quantity, 'amount': amount, 'amount_basis': 'with_vat',
            'source': {'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 9}}


def view(*periods, **changes):
    result = {'position': '1.1', 'name': 'Монтаж стены', 'scope': 'Этаж 2',
              'unit': 'м2', 'period_year': 2026, 'plan_quantity': 10,
              'planned_amount': 1000, 'planned_amount_basis': 'with_vat',
              'completed_amount_basis': 'with_vat',
              'completed_quantity': sum(item.get('quantity') or 0 for item in periods),
              'completed_amount': sum(item.get('amount') or 0 for item in periods),
              'periods': list(periods), 'undated_periods': [],
              'section_path': [{'position': '1', 'name': 'Корпус 1', 'source': {'row': 8}}],
              'context_headings': ['Система А'], 'warnings': [],
              'source': {'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 9}}
    result.update(changes)
    return result


def source(day, *views, snapshot=None, sha='a', **changes):
    ledger = {'archive_snapshot_id': snapshot or day+'-'+sha*64, 'source_date': day,
              'file_sha256': sha*64, 'period_year': 2026,
              'object_scope': 'Корпус 1', 'system_scope': 'Система А',
              'site_scope': 'Площадка', 'items': copy.deepcopy(list(views))}
    ledger.update(changes)
    return ledger, list(views)


def only(result):
    item, = result['items']
    return item


def test_incremental_march_keeps_january_february_and_original_source_views():
    old = source('2026-04-01', view(period(1), period(2)))
    new = source('2026-05-01', view(period(3, 200)), sha='b')
    sources = [new, old]
    before = copy.deepcopy(sources)
    result = compose(sources, CUT)
    item = only(result)
    assert item['detail_history_state'] == 'known' and not result['warnings']
    assert item['completed_amount'] == 400 and item['completed_quantity'] == 3
    assert item['planned_amount'] == 1000  # The full plan is not added per archive.
    assert [p['date_start'] for p in item['periods']] == ['2026-01-01', '2026-02-01', '2026-03-01']
    assert [p['selected_source']['snapshot_id'] for p in item['periods']] == [
        old[0]['archive_snapshot_id'], old[0]['archive_snapshot_id'], new[0]['archive_snapshot_id']]
    assert item['periods'][2]['selected_source']['file_sha256'] == 'b'*64
    assert item['history_sources'][0]['view'] == old[1][0]
    assert sources == before
    item['history_sources'][0]['view']['name'] = 'Изменена только проекция'
    item['periods'][0]['history_sources'][0]['period']['amount'] = -1
    assert sources == before


def test_corrected_january_replaces_its_previous_observation_but_keeps_february():
    old = source('2026-04-01', view(period(1), period(2, 200)))
    new = source('2026-05-01', view(period(1, 150, quantity=1.5)), sha='b')
    item = only(compose([old, new], CUT))
    assert item['completed_amount'] == 350 and item['completed_quantity'] == 2.5
    january, february = item['periods']
    assert january['amount'] == 150 and january['selected_source']['source_date'] == '2026-05-01'
    assert [p['period']['amount'] for p in january['history_sources']] == [100, 150]
    assert february['amount'] == 200 and february['selected_source']['source_date'] == '2026-04-01'
    assert only(compose([new, old], CUT)) == item


def test_identical_cumulative_reupload_and_renamed_file_do_not_double_money():
    old = source('2026-04-01', view(period(1), period(2)))
    renamed = copy.deepcopy(old[1][0])
    renamed['source']['filename'] = 'Совсем другое имя.xlsx'
    new = source('2026-05-01', renamed, sha='b')
    item = only(compose([old, new], CUT))
    assert item['completed_amount'] == 200 and len(item['periods']) == 2
    assert len(item['history_sources']) == 2
    assert item['detail_history_key'] == only(compose([old], CUT))['detail_history_key']
    assert all(len(p['history_sources']) == 2 for p in item['periods'])


@pytest.mark.parametrize('change', [
    {'object_scope': 'Корпус 2'}, {'system_scope': 'Система Б'}, {'site_scope': 'Другая площадка'},
])
def test_same_file_sheet_row_and_work_in_different_header_scopes_stay_distinct(change):
    first = source('2026-04-01', view(period(1)))
    second = source('2026-05-01', view(period(1)), sha='b', **change)
    result = compose([first, second], CUT)
    assert len(result['items']) == 2
    assert len({item['detail_history_key'] for item in result['items']}) == 2
    assert sum(item['completed_amount'] for item in result['items']) == 200
    for field, value in change.items():
        assert any(item['ledger_'+field] == value for item in result['items'])


@pytest.mark.parametrize('old_scopes,new_scopes', [
    ({'object_scope': ''}, {'object_scope': 'Корпус 1'}),
    ({'system_scope': 'Система А'}, {'system_scope': ''}),
    ({'site_scope': ''}, {'site_scope': 'Площадка'}),
    ({'object_scope': 'Корпус 1', 'system_scope': ''},
     {'object_scope': '', 'system_scope': 'Система А'}),
])
@pytest.mark.parametrize('new_month', [1, 2])
@pytest.mark.parametrize('old_year', [2025, 2026])
def test_compatible_incomplete_header_scopes_do_not_prove_independent_work(old_scopes, new_scopes, new_month, old_year):
    old = source('2026-04-01', view(period(1, year=old_year), period_year=old_year),
                 period_year=old_year, **old_scopes)
    new = source('2026-05-01', view(period(new_month)), sha='b', **new_scopes)
    result = compose([old, new], CUT)
    assert len(result['items']) == 2
    assert all(item['detail_history_state'] == 'unknown' for item in result['items'])
    assert all(item['completed_amount'] is None for item in result['items'])
    assert all(item['history_sources'] and item['periods'] for item in result['items'])
    assert any('Область работ' in note for note in result['warnings'])


def test_a_known_different_scope_proves_separate_work_even_with_other_missing_fields():
    result = compose([
        source('2026-04-01', view(period(1)), object_scope='Корпус 1', system_scope=''),
        source('2026-05-01', view(period(1)), sha='b', object_scope='Корпус 2')], CUT)
    assert len(result['items']) == 2
    assert all(item['detail_history_state'] == 'known' for item in result['items'])
    assert sum(item['completed_amount'] for item in result['items']) == 200


@pytest.mark.parametrize('changes', [
    {'unit': 'м3'}, {'scope': 'Этаж 3'}, {'section_path': [{'position': '1', 'name': 'Корпус 2'}]},
    {'context_headings': ['Система Б']},
])
def test_different_units_and_item_contexts_do_not_replace_one_another(changes):
    result = compose([source('2026-04-01', view(period(1))),
                      source('2026-05-01', view(period(1), **changes), sha='b')], CUT)
    assert len(result['items']) == 2
    assert all(item['detail_history_state'] == 'known' for item in result['items'])


def test_year_and_source_coordinates_have_different_roles_in_work_identity():
    original = view(period(1))
    moved = copy.deepcopy(original)
    moved['source']['row'] = 100
    moved['section_path'][0]['source']['row'] = 99
    first = only(compose([source('2026-04-01', original)], CUT))
    other_row = only(compose([source('2026-04-01', moved)], CUT))
    assert first['detail_history_key'] == other_row['detail_history_key']
    last_year = source('2026-04-01', view(period(1, year=2025), period_year=2025), period_year=2025)
    assert len(compose([source('2026-04-01', original), last_year], CUT)['items']) == 2
    previous = only(compose([last_year], CUT))
    assert previous['detail_history_key'] != first['detail_history_key']
    assert previous['detail_history_work_key'] == first['detail_history_work_key']


def test_simultaneous_conflicting_versions_have_no_selected_money_or_source():
    result = compose([source('2026-04-01', view(period(1, 100)), snapshot='same'),
                      source('2026-04-01', view(period(1, 200)), snapshot='same', sha='b')], CUT)
    item = only(result)
    assert item['detail_history_state'] == 'unknown' and result['warnings']
    assert item['completed_amount'] is None and item['completion_ratio'] is None
    assert item['periods'][0]['amount'] is None and item['periods'][0]['selected_source'] is None
    assert len(item['periods'][0]['history_sources']) == 2
    assert 'conflict' in item['detail_history_problems']


def test_different_period_dates_are_preserved_as_an_overlap_instead_of_replaced():
    changed = period(1, 150)
    changed['date_end'] = '2026-01-30'
    item = only(compose([source('2026-04-01', view(period(1))),
                         source('2026-05-01', view(changed), sha='b')], CUT))
    assert item['detail_history_state'] == 'unknown' and item['completed_amount'] is None
    assert len(item['periods']) == 2 and 'overlap' in item['detail_history_problems']


def test_different_act_labels_for_the_same_month_are_not_assumed_to_be_a_revision():
    item = only(compose([source('2026-04-01', view(period(1, label='КС-2 № 1'))),
                         source('2026-05-01', view(period(1, label='КС-2 № 2')), sha='b')], CUT))
    assert item['detail_history_state'] == 'unknown' and len(item['periods']) == 2


@pytest.mark.parametrize('changes,code', [
    ({'completed_amount': None, 'reported_completed_amount': 100}, 'incomplete'),
    ({'completed_quantity': None, 'reported_completed_quantity': 1}, 'incomplete'),
    ({'plan_quantity': None}, 'plan'), ({'planned_amount': None}, 'plan'),
    ({'unit': ''}, 'identity'), ({'position': ''}, 'identity'),
])
def test_an_incomplete_row_is_not_upgraded_to_known_from_its_dated_cells(changes, code):
    raw = view(period(1), **changes)
    item = only(compose([source('2026-04-01', raw)], CUT))
    assert item['detail_history_state'] == 'unknown'
    assert item['completed_amount'] is None and item['completed_quantity'] is None
    assert code in item['detail_history_problems']
    assert item['history_sources'][0]['view'] == raw


def test_undated_totals_remain_original_reference_values_without_dates_or_zero():
    raw = view(completed_amount=None, completed_quantity=None,
               reported_completed_amount=500, reported_completed_quantity=5,
               undated_periods=[{'label': 'КС-2 № 1', 'amount': 500, 'quantity': 5}])
    item = only(compose([source('2026-04-01', raw)], CUT))
    assert item['detail_history_state'] == 'unknown'
    assert item['periods'] == [] and item['completed_amount'] is None
    assert item['undated_periods'][0]['amount'] == 500
    assert item['history_sources'][0]['view']['reported_completed_amount'] == 500


@pytest.mark.parametrize('metadata', [{'source_date': None}, {'file_sha256': ''}])
def test_unknown_observation_provenance_does_not_select_a_latest_version(metadata):
    bad = source('2026-05-01', view(period(1, 200)), sha='b', **metadata)
    item = only(compose([source('2026-04-01', view(period(1))), bad], CUT))
    assert item['detail_history_state'] == 'unknown' and item['completed_amount'] is None
    assert 'provenance' in item['detail_history_problems']


def test_conflicting_header_scope_evidence_is_not_reduced_to_an_empty_shared_scope():
    item = only(compose([source('2026-04-01', view(period(1)), object_scope='',
        scope_evidence={'object_scope': [{'raw': 'Корпус 1'}, {'raw': 'Корпус 2'}]})], CUT))
    assert item['detail_history_key'] is None and item['detail_history_state'] == 'unknown'


@pytest.mark.parametrize('changes', [
    {'unit': '', 'is_group': True}, {'unit': ''}, {'position': ''},
    {'position': '', 'unit': '', 'is_group': True, 'plan_quantity': None},
])
def test_repeated_incomplete_rows_keep_one_projection_and_all_archive_observations(changes):
    sources = [source(day, view(period(1), **changes))
               for day in ['2026-11-06', '2026-11-12', '2026-11-16', '2026-11-17']]
    before = copy.deepcopy(sources)
    item = only(compose(sources, CUT))
    assert len(item['history_sources']) == 4
    assert item['snapshot_date'] == '2026-11-17'
    assert item['detail_history_state'] == ('group' if changes.get('is_group') else 'unknown')
    if not changes.get('is_group'):
        assert item['completed_amount'] is None and item['completed_quantity'] is None
    assert sources == before
    assert only(compose(list(reversed(sources)), CUT)) == item


def test_incomplete_named_row_can_move_and_rename_without_becoming_another_work():
    old = source('2026-11-06', view(period(1), unit=''))
    moved = view(period(1), unit='')
    moved['source'].update(filename='Renamed.xlsx', row=100)
    new = source('2026-11-16', moved, sha='b')
    item = only(compose([old, new], CUT))
    assert len(item['history_sources']) == 2 and item['detail_history_state'] == 'unknown'
    assert item['source']['row'] == 100 and item['completed_amount'] is None


def test_repeated_scope_conflict_keeps_one_unknown_row_but_different_evidence_stays_separate():
    evidence = {'object_scope': [{'raw': 'Корпус 1'}, {'raw': 'Корпус 2'}]}
    old = source('2026-11-06', view(period(1)), object_scope='', scope_evidence=evidence)
    new = source('2026-11-16', view(period(1)), sha='b', object_scope='', scope_evidence=evidence)
    item = only(compose([old, new], CUT))
    assert item['detail_history_state'] == 'unknown' and item['completed_amount'] is None
    assert len(item['history_sources']) == 2
    other = source('2026-11-17', view(period(1)), sha='c', object_scope='',
                   scope_evidence={'object_scope': [{'raw': 'Корпус 1'}, {'raw': 'Корпус 3'}]})
    assert len(compose([old, new, other], CUT)['items']) == 2


def test_indistinguishable_incomplete_rows_are_not_merged_by_their_names():
    first, second = view(period(1), unit=''), view(period(1), unit='')
    second['source']['row'] = 10
    old = source('2026-11-06', first, second)
    again = source('2026-11-17', first, second)
    result = compose([old, again], CUT)
    assert len(result['items']) == 2
    assert all(len(item['history_sources']) == 2 for item in result['items'])
    assert all(item['detail_history_state'] == 'unknown' for item in result['items'])
    changed_file = source('2026-11-18', first, second, sha='b')
    assert len(compose([old, again, changed_file], CUT)['items']) == 4


def test_incomplete_rows_in_different_buildings_or_with_different_unnumbered_volumes_stay_separate():
    old = source('2026-11-06', view(period(1), position='', unit=''))
    other_building = source('2026-11-16', view(period(1), position='', unit=''), object_scope='Корпус 2')
    other_volume = source('2026-11-17', view(period(1), position='', unit='', plan_quantity=20))
    assert len(compose([old, other_building, other_volume], CUT)['items']) == 3


def test_changed_plan_is_kept_for_reconciliation_without_adding_or_choosing_it():
    item = only(compose([source('2026-04-01', view(period(1))),
                         source('2026-05-01', view(period(2), planned_amount=1200), sha='b')], CUT))
    assert item['detail_history_state'] == 'unknown' and item['planned_amount'] is None
    assert [entry['view']['planned_amount'] for entry in item['history_sources']] == [1000, 1200]


def test_future_periods_and_future_archives_are_never_restored_as_facts():
    old = source('2026-02-01', view(period(1), period(3)),
                 items=[view(period(1), period(2), period(3))])
    future = source('2026-04-01', view(period(2)), sha='b')
    result = compose([old, future], '2026-02-15')
    item = only(result)
    assert [p['date_start'] for p in item['periods']] == ['2026-01-01']
    assert all(p['date_end'] <= '2026-02-15' for p in item['periods'])
    assert len(item['history_sources']) == 1 and result['warnings']


def test_real_physical_views_keep_old_february_after_corrected_january():
    import io
    import openpyxl
    import developaid_monitor_contracts as contracts
    import developaid_monitor_ledgers as ledgers
    from test_contracts_from_cumulative_headers import ks
    from test_monitor_cumulative_ledgers import archive

    wb = openpyxl.load_workbook(io.BytesIO(ks(period='jan')))
    wb.active['H9'], wb.active['I9'], wb.active['K9'], wb.active['L9'] = 3, 300, 3, 300
    output = io.BytesIO()
    wb.save(output)
    archives = [archive([('Jan.xlsx', ks(period='jan')), ('Feb.xlsx', ks(period='feb'))]),
                archive([('Renamed.xlsx', output.getvalue())])]
    sources = []
    for payload, day in zip(archives, ['2026-06-01', '2026-07-01']):
        for ledger in ledgers.parse_archive(payload)['ledgers']:
            ledger.update(source_date=day, archive_snapshot_id=day+'-'+'f'*64)
            sources.append((ledger, [contracts._physical(item, ledger, CUT) for item in ledger['items']]))
    result = compose(sources, CUT)
    wall = next(item for item in result['items'] if item['position'] == '1.1')
    assert wall['detail_history_state'] == 'known'
    assert wall['completed_amount'] == 500 and wall['completed_quantity'] == 5
    assert [p['selected_source']['source_date'] for p in wall['periods']] == ['2026-07-01', '2026-06-01']


def test_real_verified_duplicate_rows_remain_only_in_provenance():
    import developaid_monitor_contracts as contracts
    import developaid_monitor_ledgers as ledgers
    from test_cumulative_proven_duplicates import snapshot

    ledger, = snapshot()['ledgers']
    ledger.update(source_date='2026-11-06', archive_snapshot_id='2026-11-06-'+'f'*64)
    duplicates = ledgers.verified_duplicate_sources(ledger['items'])
    views = [contracts._physical(item, ledger, CUT, _duplicates=duplicates) for item in ledger['items']]
    assert sum(item.get('is_duplicate') is True for item in views) == 2
    result = compose([(ledger, views)], CUT)
    assert len(result['items']) == 2 and not result['warnings']
    assert sum(item['completed_amount'] for item in result['items']) == 400
    assert all(item['detail_history_state'] == 'known' for item in result['items'])
    assert all(len(item['history_sources']) == 2 for item in result['items'])
    assert sorted(entry['view']['source']['row'] for item in result['items']
                  for entry in item['history_sources']) == [9, 10, 11, 12]


def test_detached_duplicate_proof_is_not_silently_discarded():
    raw = view(period(1), is_duplicate=True,
               duplicate_of={'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 8, 'period_year': 2026})
    item = only(compose([source('2026-04-01', raw)], CUT))
    assert item['detail_history_state'] == 'unknown' and 'duplicate' in item['detail_history_problems']
    assert item['history_sources'][0]['view'] == raw


def test_changed_duplicate_values_do_not_inherit_the_earlier_verified_flag():
    canonical = view(period(1))
    changed = view(period(1, 200), is_duplicate=True,
                   duplicate_of={'filename': 'KS.xlsx', 'sheet': 'Работы', 'row': 9, 'period_year': 2026})
    changed['source']['row'] = 10
    item = only(compose([source('2026-04-01', canonical, changed)], CUT))
    assert item['detail_history_state'] == 'unknown' and 'duplicate' in item['detail_history_problems']
    assert len(item['history_sources']) == 2


@pytest.mark.parametrize('empty_periods', [[], [dict(period(1), quantity=None, amount=None)]])
def test_already_reconciled_zero_is_not_unknown_because_its_period_cells_are_empty(empty_periods):
    raw = view(*empty_periods, completed_amount=0, completed_quantity=0)
    item = only(compose([source('2026-04-01', raw)], CUT))
    assert item['detail_history_state'] == 'known' and item['periods'] == []
    assert item['completed_amount'] == item['completed_quantity'] == 0
    assert item['completion_ratio'] == 0


def test_equal_unverified_rows_are_not_inferred_to_be_copies():
    first, second = view(period(1)), view(period(1))
    second['source']['row'] = 10
    item = only(compose([source('2026-04-01', first, second)], CUT))
    assert item['detail_history_state'] == 'unknown' and item['completed_amount'] is None
    assert len(item['history_sources']) == 2 and 'duplicate' in item['detail_history_problems']


def test_mixed_tax_bases_of_selected_periods_are_not_summed():
    second = period(2)
    second['amount_basis'] = 'without_vat'
    item = only(compose([source('2026-04-01', view(period(1))),
                         source('2026-05-01', view(second), sha='b')], CUT))
    assert item['detail_history_state'] == 'unknown' and 'basis' in item['detail_history_problems']
    assert item['completed_amount'] is None


def test_derived_projection_does_not_reuse_the_latest_source_reported_total():
    item = only(compose([source('2026-04-01', view(period(1), reported_completed_amount=100)),
                         source('2026-05-01', view(period(2), reported_completed_amount=100), sha='b')], CUT))
    assert item['completed_amount'] == 200 and item['reported_completed_amount'] is None
    assert 'датированным периодам' in item['quantity_basis']
    assert all(entry['view']['reported_completed_amount'] == 100 for entry in item['history_sources'])


def test_invalid_cut_is_explicit():
    with pytest.raises(ValueError, match='дату среза'):
        compose([], '2026-02-30')
