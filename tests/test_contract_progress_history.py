"""Dynamics must reuse source percentages and compare equivalent observations."""
from __future__ import annotations

import copy
import datetime as dt

import pytest

import developaid_monitor_contract_history as history
import developaid_monitor_ledgers as ledgers


def sid(day, letter='a'):
    return day + '-' + letter * 64


def row(*, ratio=.4, planned=1000, completed=400, source='A.xlsx', year=2026, **changes):
    result = {'id': 'source-contract-id', 'contractor': 'НУР ООО', 'customer': 'ООО Заказчик',
        'contract': 'A-12', 'contract_date': '2026-01-01',
        'amount': None, 'completed': None, 'completion_ratio': None,
        'monetary_comparable': True, 'amount_basis': 'unspecified', 'completed_basis': 'unspecified',
        'physical_items': [{'position': '1.1', 'name': 'Монтаж', 'scope': 'Корпус 1', 'unit': 'м2',
            'plan_quantity': 10, 'planned_amount': planned, 'period_year': year,
            'source': {'filename': source, 'sheet': 'Работы'}}],
        'reported_performance_sources': [{'source': {'filename': source, 'sheet': 'Работы'},
            'amount_scope': 'statement', 'planned': planned, 'completed': completed,
            'completion_ratio': ratio, 'future_periods_excluded': False,
            'monetary_comparable': True, 'period_year': year,
            'planned_amount_basis': 'with_vat', 'completed_amount_basis': 'with_vat'}]}
    result.update(changes)
    return result


def register(day='2026-11-06', rows=None, letter='a'):
    return {'cut': day, 'source_date': day, 'snapshots': {'cumulative': day,
             'cumulative_id': sid(day, letter)}, 'rows': [row()] if rows is None else rows}


def calculate(monkeypatch, current=None, previous=None, *, snapshots=None, cut='2026-11-08'):
    current = current or register()
    previous = previous or {}
    if snapshots is None:
        snapshots = [{'taken_at': day, 'snapshot_id': value['snapshots']['cumulative_id']}
                     for day, value in previous.items()]
        snapshots.append({'taken_at': current['source_date'],
                          'snapshot_id': current['snapshots']['cumulative_id']})
    monkeypatch.setattr(ledgers, 'list_snapshots', lambda _: copy.deepcopy(snapshots))
    calls = []

    def build(day):
        calls.append(day)
        return previous[day]

    before = copy.deepcopy((current, previous))
    result = history.enrich('Example', cut, current, build_register=build)
    assert (current, previous) == before
    return result, calls


def test_one_snapshot_keeps_known_percentage_without_inventing_dynamics(monkeypatch):
    result, calls = calculate(monkeypatch)
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .4 and progress['basis'] == 'statement'
    assert progress['origin'] == 'cumulative_statement'
    assert progress['observation_date'] == '2026-11-06' and progress['date_basis'] == 'snapshot'
    assert progress['delta_percent_points'] is None and progress['period_days'] is None
    assert progress['comparison_state'] == 'no_previous_snapshot'
    assert calls == [] and result['progress_summary']['known'] == 1


def test_same_canonical_percentage_is_used_without_another_division(monkeypatch):
    current = register(rows=[row(ratio=.375, planned=1000, completed=400)])
    result, _ = calculate(monkeypatch, current)
    assert result['rows'][0]['progress']['ratio'] == .375  # Backend owns this value.


def test_comparable_growth_and_legal_form_order_do_not_depend_on_old_source_id(monkeypatch):
    previous = register('2026-10-06', [row(ratio=.2, completed=200,
                       contractor='ООО «НУР»', id='old-source-id')], 'b')
    result, calls = calculate(monkeypatch, previous={'2026-10-06': previous})
    progress = result['rows'][0]['progress']
    assert progress['previous_ratio'] == .2
    assert progress['delta_percent_points'] == pytest.approx(20)
    assert progress['period_days'] == 31 and progress['change_kind'] == 'growth'
    assert progress['comparison_state'] == 'comparable'
    assert calls == ['2026-10-06']


@pytest.mark.parametrize('value,kind,expected', [(0, 'correction', -20), (.2, 'unchanged', 0), (1.2, 'growth', 100)])
def test_zero_overrun_and_negative_change_are_never_clamped_or_missing(monkeypatch, value, kind, expected):
    current = register(rows=[row(ratio=value, completed=value*1000)])
    previous = register('2026-10-06', [row(ratio=.2, completed=200)], 'b')
    result, _ = calculate(monkeypatch, current, {'2026-10-06': previous})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == value and progress['change_kind'] == kind
    assert progress['delta_percent_points'] == pytest.approx(expected)
    assert progress['requires_reconciliation'] is (value > 1)


@pytest.mark.parametrize('mutation,state', [
    (lambda x: x['physical_items'][0].update(plan_quantity=20), 'scope_changed'),
    (lambda x: x['physical_items'][0].update(unit='шт'), 'scope_changed'),
    (lambda x: x['physical_items'][0].update(period_year=2025), 'scope_changed'),
    (lambda x: x['reported_performance_sources'][0].update(planned=2000), 'basis_changed'),
    (lambda x: x['reported_performance_sources'][0].update(planned_amount_basis='without_vat',
                                                        completed_amount_basis='without_vat'), 'basis_changed'),
])
def test_scope_price_and_tax_changes_do_not_masquerade_as_work_progress(monkeypatch, mutation, state):
    prior = row(ratio=.2, completed=200)
    mutation(prior)
    result, _ = calculate(monkeypatch, previous={'2026-10-06': register('2026-10-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .4 and progress['delta_percent_points'] is None
    assert progress['comparison_state'] == state


def test_full_contract_price_change_blocks_dated_contract_delta(monkeypatch):
    current, prior = row(), row()
    current.update(amount=1000, completed=400, completion_ratio=.4)
    prior.update(amount=2000, completed=400, completion_ratio=.2)
    result, _ = calculate(monkeypatch, register(rows=[current]),
                          {'2026-10-06': register('2026-10-06', [prior], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['basis'] == 'contract_amount' and progress['ratio'] == .4
    assert progress['comparison_state'] == 'basis_changed'


def test_missing_old_tax_metadata_keeps_current_percentage_but_blocks_a_false_comparison(monkeypatch):
    previous_row = row(ratio=.2, completed=200)
    previous_row['reported_performance_sources'][0].pop('planned_amount_basis')
    result, _ = calculate(monkeypatch, previous={
        '2026-10-06': register('2026-10-06', [previous_row], 'b')})
    progress = result['rows'][0]['progress']
    assert progress['ratio'] == .4 and progress['series'][0]['ratio'] == .2
    assert progress['delta_percent_points'] is None
    assert progress['comparison_state'] == 'basis_unverified'


def test_absent_prior_contract_is_unknown_not_zero_and_does_not_skip_to_an_older_value(monkeypatch):
    prior = {'2026-09-06': register('2026-09-06', [row(ratio=.1)], 'c'),
             '2026-10-06': register('2026-10-06', [], 'b')}
    result, _ = calculate(monkeypatch, previous=prior)
    progress = result['rows'][0]['progress']
    assert progress['comparison_state'] == 'previous_contract_missing'
    assert progress['delta_percent_points'] is None and len(progress['series']) == 3


def test_other_legal_entity_and_duplicate_prior_identity_are_not_chosen(monkeypatch):
    prior = row(contractor='ИП НУР')
    result, _ = calculate(monkeypatch, previous={'2026-10-06': register('2026-10-06', [prior], 'b')})
    assert result['rows'][0]['progress']['comparison_state'] == 'previous_contract_missing'
    result, _ = calculate(monkeypatch, previous={'2026-10-06': register('2026-10-06', [row(), row()], 'b')})
    assert result['rows'][0]['progress']['comparison_state'] == 'ambiguous_contract'


def test_identical_source_copies_are_one_metric_but_incompatible_statement_scopes_are_not(monkeypatch):
    current = row()
    second = copy.deepcopy(current['reported_performance_sources'][0])
    second['source']['filename'] = 'Copy.xlsx'
    current['reported_performance_sources'].append(second)
    duplicate = copy.deepcopy(current['physical_items'][0])
    duplicate['source']['filename'] = 'Copy.xlsx'
    current['physical_items'].append(duplicate)
    result, _ = calculate(monkeypatch, register(rows=[current]))
    assert result['rows'][0]['progress']['ratio'] == .4
    current['physical_items'][1]['scope'] = 'Корпус 2'
    result, _ = calculate(monkeypatch, register(rows=[current]))
    assert result['rows'][0]['progress']['state'] == 'ambiguous_sources'
    assert result['rows'][0]['progress']['ratio'] is None


@pytest.mark.parametrize('field,value', [('completion_ratio', None), ('future_periods_excluded', True),
                                       ('monetary_comparable', False), ('planned', 0)])
def test_unqualified_source_ratio_never_becomes_known_or_zero(monkeypatch, field, value):
    current = row()
    current['reported_performance_sources'][0][field] = value
    result, _ = calculate(monkeypatch, register(rows=[current]))
    assert result['rows'][0]['progress']['ratio'] is None
    assert result['progress_summary']['unknown'] == 1


def test_history_is_bounded_and_builds_each_selected_snapshot_only_once_for_all_contracts(monkeypatch):
    dates = [(dt.date(2026, 11, 6)-dt.timedelta(days=day)).isoformat() for day in range(1, 121)]
    previous = {day: register(day, [row(), row(contract='B-24')], str(index % 10))
                for index, day in enumerate(dates)}
    current = register(rows=[row(), row(contract='B-24')])
    result, calls = calculate(monkeypatch, current, previous)
    assert len(calls) == history.MAX_RECENT_SNAPSHOTS + 1
    assert len(calls) == len(set(calls))
    assert calls[0] == '2026-08-07'  # Last observation before the ninety-day window.
    assert result['progress_summary']['history_truncated']
    assert result['progress_summary']['comparable'] == 2


def test_duplicate_date_sources_and_history_errors_are_visible_not_silently_skipped(monkeypatch):
    previous = register('2026-10-06', letter='b')
    snapshots = [{'taken_at': '2026-10-06', 'snapshot_id': sid('2026-10-06', 'b')},
                 {'taken_at': '2026-10-06', 'snapshot_id': sid('2026-10-06', 'c')}]
    result, calls = calculate(monkeypatch, previous={'2026-10-06': previous}, snapshots=snapshots)
    assert calls == []
    assert result['rows'][0]['progress']['comparison_state'] == 'ambiguous_snapshot_date'
    monkeypatch.setattr(ledgers, 'list_snapshots', lambda _: (_ for _ in ()).throw(ledgers.LedgerProblem('private path')))
    result = history.enrich('Example', '2026-11-08', register(), build_register=lambda _: None)
    assert result['rows'][0]['progress']['ratio'] == .4
    assert result['rows'][0]['progress']['comparison_state'] == 'history_unavailable'
    assert 'private path' not in str(result)


def test_snapshot_read_error_and_wrong_history_binding_do_not_erase_current_value(monkeypatch):
    monkeypatch.setattr(ledgers, 'list_snapshots', lambda _: [{'taken_at': '2026-10-06',
                        'snapshot_id': sid('2026-10-06', 'b')}])
    def broken(_):
        raise ledgers.LedgerProblem('source unavailable')
    result = history.enrich('Example', '2026-11-08', register(), build_register=broken)
    assert result['rows'][0]['progress']['comparison_state'] == 'history_unavailable'
    result = history.enrich('Example', '2026-11-08', register(), build_register=lambda _: register('2026-09-06'))
    assert result['rows'][0]['progress']['comparison_state'] == 'history_source_changed'


def test_future_source_does_not_trigger_history_reads_or_expose_its_percentage(monkeypatch):
    monkeypatch.setattr(ledgers, 'list_snapshots', lambda _: pytest.fail('future source must not read history'))
    result = history.enrich('Example', '2026-11-08', register('2026-12-01'),
                            build_register=lambda _: pytest.fail('unexpected build'))
    assert result['rows'][0]['progress']['ratio'] is None
    assert result['rows'][0]['progress']['state'] == 'future_source'
