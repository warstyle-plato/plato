"""A native statement zero is a report value, not dated physical evidence."""
import copy
import io

import pytest
from openpyxl import load_workbook

import developaid_contract_comparison_export as export
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_plan as plan
import developaid_contract_rds as rds
from tests.contract_rds_fixtures import native_card, CUT, PROJECT, CONTRACT


ZERO_BASIS = 'Нулевой объём подтверждён нулевой суммой при положительной цене компонента.'


def statement_card(*, accounted=False, source_quantity=0, source_change=None, cash_zero=False):
    base = native_card()
    documents = base['documents']
    estimate = documents[0]['estimates'][0]
    schedule = documents[1]['schedule']
    edition = {'sha256': 'a'*64, 'estimate_sha256': 'a'*64, 'title': 'Учебная редакция',
        'date': '2026-02-01', 'estimates': [estimate], 'schedule': schedule,
        'schedule_sha256': 'b'*64, 'start': None}
    source = {'filename': 'Учебная КС-6а.xlsx', 'sheet': 'КС', 'row': 31,
        'snapshot_id': 'synthetic-snapshot', 'file_sha256': 'd'*64, 'source_date': '2026-03-04',
        'completed_quantity_cell': 'AV31', 'completed_amount_cell': 'AW31 + AX31'}
    physical = []
    for index, position in enumerate(estimate['positions']):
        quantity = source_quantity if index == 0 else 2
        item = {'position': position['number'], 'name': position['name'], 'unit': position['unit'],
            'plan_quantity': position['quantity'], 'completed_quantity': quantity,
            'reported_completed_quantity': None, 'completed_amount': (0 if cash_zero else None) if index == 0 else 200,
            'reported_completed_amount': None, 'completed_amount_derivation': None,
            'period_year': 2026, 'quantity_cut': CUT, 'future_periods_excluded': False,
            'quantity_basis': 'Итог ведомости', 'snapshot_date': '2026-03-04',
            'source': {**source, 'row': 31+index, 'completed_quantity_cell': f'AV{31+index}'},
            'periods': []}
        if index or accounted:
            item['periods'] = [{'quantity': 2 if index else 0, 'material_quantity': 0 if index else 2,
                'work_amount': 200 if index else 0, 'material_amount': 0 if index else 100,
                'amount': 200 if index else 100, 'amount_split': True,
                'quantity_basis': 'explicit_quantity' if index else ZERO_BASIS,
                'date_start': '2026-03-01', 'date_end': '2026-03-04', 'label': 'КС-2 № 1'}]
            if not index:
                item['completed_amount'] = 100
        physical.append(item)
    if source_change:
        source_change(physical[0])
    row = {'physical_items': physical, 'reported_performance_sources': [{
        'source': {**source, 'row': 26}, 'source_date': '2026-03-04', 'period_year': 2026,
        'financial_complete': True, 'completed': 300 if accounted else 200,
        'completed_works': 200, 'completed_materials': 100 if accounted else 0,
        'planned': 2000, 'planned_works': 2000, 'planned_materials': 0}]}
    found = fact.acts(row)
    planned = plan.build([edition], CUT)
    actual = fact.build([edition], planned['in_force'], found, CUT)
    cached = {'ok': True, 'pending': False, **files._with_control({
        'contract_id': CONTRACT, 'documents': documents, 'plan': planned, 'fact': actual}, found, CUT)}
    cached['rds_comparison'] = rds.build(cached)
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    return cached, row


def first(cached):
    return cached['rds_comparison']['rows'][0]


def rebuild(cached):
    return rds.build(cached)['rows'][0]


def test_known_native_source_zero_is_quantity_only_without_physical_or_date_promotion():
    cached, source = statement_card()
    before = copy.deepcopy(cached)
    row = first(cached)
    assert row['fact_quantity'] is row['fact_quantity_ratio'] is row['day_deviation'] is None
    assert row['forecast_finish'] is row['forecast_delay_days'] is None
    assert row['physical_audit']['state'] == 'known_source_value_unaccepted'
    view = rds.reporting_row(row)
    assert [view[key] for key in ('fact_quantity', 'fact_quantity_ratio', 'quantity_deviation')] == [0, 0, -10]
    assert view['fact'] is row['fact'] is None and view['deviation'] is row['deviation'] is None
    assert row['ks_reporting']['basis'] == 'ks6_cumulative_source_zero'
    assert row['ks_reporting']['physical_quantity_confirmed'] is False
    assert 'физический ноль' in view['comments']['fact_quantity']
    assert row['schedule_reporting']['credited_zero'] is True
    assert 'нет подтверждённого темпа' in row['schedule_reporting']['finish']['text']
    assert cached == before
    retained = cached['fact']['physical_source_rows'][0]
    for key in ('period_year', 'quantity_cut', 'future_periods_excluded', 'quantity_basis',
                'reported_completed_amount', 'completed_amount', 'completed_amount_derivation'):
        assert retained[key] == source['physical_items'][0][key]


def test_accounted_work_zero_does_not_zero_material_cash_or_change_raw_physical_history():
    cached, _ = statement_card(accounted=True)
    row = first(cached)
    assert row['physical_audit']['state'] == 'accounted_zero_physical_unknown'
    assert row['accounted_work_quantity'] == 0 and row['fact_quantity'] is None
    assert row['ks_reporting']['basis'] == 'ks6_accounted_work_zero'
    view = rds.reporting_row(row)
    assert view['fact_quantity'] == view['fact_quantity_ratio'] == 0
    assert view['fact'] == row['fact'] and view['deviation'] == row['deviation']
    assert 'fact' not in row['ks_reporting'] and 'deviation' not in row['ks_reporting']
    assert cached['fact']['statement_components']['cash']['source']['material'] == 100


def test_independent_native_cash_zero_can_fill_reported_money_without_repricing_raw_history():
    cached, _ = statement_card(cash_zero=True)
    before = copy.deepcopy(cached)
    row = first(cached)
    view = rds.reporting_row(row)
    assert row['fact'] is row['deviation'] is None
    assert view['fact'] == 0 and view['deviation'] == -500
    assert row['ks_reporting']['cash_zero']['schema'] == 'ks6-source-cash-zero-v1'
    assert 'не выведен из объёма' in row['ks_reporting']['cash_zero']['note']
    table = cached['rds_comparison']
    raw = export.workbook(cached['comparison_export'], table, table['rows'])
    sheet = load_workbook(io.BytesIO(raw), data_only=True).active
    assert sheet['L7'].value == 0 and sheet['M7'].value == -500
    assert cached == before


@pytest.mark.parametrize('change', [
    lambda c: c['fact']['physical_source_rows'][0].update(completed_amount=None),
    lambda c: c['fact']['physical_source_rows'][0].update(completed_amount=100),
    lambda c: c['fact']['physical_source_rows'][0].update(completed_amount_derivation={'method': 'zero_quantity_times_labelled_unit_price'}),
    lambda c: c['fact']['physical_source_rows'][0].pop('completed_amount_derivation'),
    lambda c: c['fact']['physical_source_rows'][0]['source'].update(completed_amount_cell='AW999 + AX999'),
    lambda c: c['fact']['statement_components']['sources'][0].update(financial_complete=False),
    lambda c: c['fact']['physical_source_rows'][0].update(periods=[{'quantity': 0, 'amount': 100}]),
])
def test_source_cash_unknown_derived_conflicting_or_incomplete_cannot_be_zeroed(change):
    cached, _ = statement_card(cash_zero=True)
    change(cached)
    row = rebuild(cached)
    view = rds.reporting_row(row)
    assert view['fact_quantity'] == 0
    assert row['fact'] is view['fact'] is None and view['deviation'] is None
    assert 'cash_zero' not in row['ks_reporting'] and 'fact' not in row['ks_reporting']


@pytest.mark.parametrize('amount,known', [(7, 7), (None, 100)])
def test_source_cash_zero_never_overrides_observed_or_partial_historical_value(amount, known):
    cached, _ = statement_card(cash_zero=True)
    cached['fact']['rds_positions'].append({'estimate': 0, 'index': 0, 'estimate_sha256': 'a'*64,
        'work_observed': False, 'amount': amount, 'known_amount': known, 'priced_editions': [], 'reasons': []})
    row = rebuild(cached)
    view = rds.reporting_row(row)
    assert row['fact'] == view['fact'] == amount
    assert 'cash_zero' not in row['ks_reporting'] and 'fact' not in row['ks_reporting']


@pytest.mark.parametrize('change', [
    lambda item: item.update(completed_quantity=None, reported_completed_quantity=None),
    lambda item: item.update(completed_quantity=1, reported_completed_quantity=1),
    lambda item: item.update(completed_quantity=False, reported_completed_quantity=False),
    lambda item: item.update(snapshot_date='2027-01-01'),
    lambda item: item.update(snapshot_date=None),
    lambda item: item['source'].update(file_sha256='e'*64),
    lambda item: item['source'].update(completed_quantity_cell=None),
    lambda item: item['source'].update(completed_quantity_cell='AV999'),
    lambda item: item.update(period_year=2027),
    lambda item: item.update(quantity_cut='2026-02-01'),
    lambda item: item.update(future_periods_excluded=True),
    lambda item: item.update(future_periods_excluded=None),
    lambda item: item.update(periods=[{'quantity': 1, 'date_end': '2026-03-04'}]),
    lambda item: item.update(periods=[{'quantity': 0, 'date_end': '2027-01-01'}]),
    lambda item: item.update(periods=[{'quantity': 0, 'date_start': '2026-03-04', 'date_end': '2026-03-01'}]),
    lambda item: item.update(periods=[{'quantity': 'unread', 'date_end': '2026-03-04'}]),
])
def test_unknown_future_foreign_or_conflicting_source_does_not_become_reporting_zero(change):
    cached, _ = statement_card()
    change(cached['fact']['physical_source_rows'][0])
    row = rebuild(cached)
    assert 'ks_reporting' not in row and rds.reporting_row(row)['fact_quantity'] is None
    assert row['forecast_finish'] is None


def test_duplicate_source_and_exact_unread_do_not_create_a_reporting_zero():
    cached, _ = statement_card()
    cached['fact']['physical_source_rows'].append(copy.deepcopy(cached['fact']['physical_source_rows'][0]))
    assert 'ks_reporting' not in rebuild(cached)


def test_explicit_source_group_or_unqualified_statement_hash_cannot_be_a_reported_work_zero():
    cached, _ = statement_card()
    cached['fact']['physical_source_rows'][0]['is_group'] = True
    assert 'ks_reporting' not in rebuild(cached)
    cached, _ = statement_card()
    cached['fact']['statement_components']['source_hashes'] = []
    assert 'ks_reporting' not in rebuild(cached)


def test_retained_source_provenance_uses_qualified_reference_without_guessing_a_year():
    cached, _ = statement_card()
    for key in ('period_year', 'quantity_cut', 'future_periods_excluded', 'quantity_basis'):
        cached['fact']['physical_source_rows'][0].pop(key)
    assert rds.reporting_row(rebuild(cached))['fact_quantity'] == 0
    cached['fact']['statement_components']['sources'][0]['period_year'] = None
    assert 'ks_reporting' not in rebuild(cached)
    cached, _ = statement_card()
    cached['fact']['rds_unread'].append({'estimate': 0, 'index': 0, 'estimate_sha256': 'a'*64, 'reason': 'Строка не прочитана.'})
    assert 'ks_reporting' not in rebuild(cached)


def test_missing_plan_is_unknown_but_exact_source_zero_is_still_reportable():
    cached, _ = statement_card()
    for edition in cached['plan']['editions']:
        edition['position_links'][0].update(status='review', lines=[])
    row = rebuild(cached)
    assert row['plan_quantity'] is None
    assert rds.reporting_row(row)['fact_quantity'] == 0
    assert rds.reporting_row(row)['quantity_deviation'] is None


def test_cached_excel_writes_numeric_quantity_zero_and_negative_plan_variance_without_zeroing_money():
    cached, _ = statement_card()
    table = cached['rds_comparison']
    raw = export.workbook(cached['comparison_export'], table, table['rows'])
    sheet = load_workbook(io.BytesIO(raw), data_only=True).active
    assert [sheet.cell(7, col).value for col in (6, 7, 8, 9, 10)] == [10, .5, 0, 0, -10]
    assert sheet['H7'].data_type == 'n' and sheet['I7'].number_format.startswith('0.0%')
    assert sheet['L7'].value is sheet['M7'].value is None
    assert 'КС-6а' in sheet['H7'].comment.text
    assert not any(cell.data_type == 'e' for row in sheet for cell in row)


def test_legacy_quantity_projection_fails_visible_zero_assertion(monkeypatch):
    cached, _ = statement_card()
    monkeypatch.setattr(rds, '_ks6_reporting', lambda *args, **kwargs: None)
    with pytest.raises(AssertionError):
        assert rds.reporting_row(rebuild(cached))['fact_quantity'] == 0
