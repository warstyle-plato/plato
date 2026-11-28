"""Calendar exposure of an unclosed KS position is not physical earned-plan lag."""
import copy
import io

import pytest
from openpyxl import load_workbook

import developaid_contract_acts as acts
import developaid_contract_comparison_export as export
import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_plan as plan
import developaid_contract_rds as rds
from tests.contract_rds_fixtures import native_card
from tests.test_contract_loaded_ks_reporting import record


def source_card(*, cut='2026-11-28', quantity=None, finish='2026-10-31', source='read',
                share=1, duplicate=False, disjoint=False):
    documents = native_card()['documents']
    positions = documents[0]['estimates'][0]['positions']
    positions[0]['quantity'] = 179.45
    positions[0]['amount'] = {'work': 8972.5, 'material': 0, 'total': 8972.5}
    schedule = documents[1]['schedule']
    for line in schedule['lines']:
        line.update(start='2026-10-11', finish=finish)
        if disjoint:
            line['segments'] = [{'start': '2026-10-11', 'finish': '2026-10-15'},
                                {'start': '2026-10-25', 'finish': finish}]
    estimate = documents[0]['estimates'][0]
    estimate['links'] = plan.links.propose(estimate, schedule)
    estimate['links']['positions'][0]['lines'][0]['share'] = share
    edition = {'sha256': 'a'*64, 'estimate_sha256': 'a'*64, 'title': 'Учебная редакция',
        'date': '2026-02-01', 'estimates': [estimate], 'schedule': schedule,
        'schedule_sha256': 'b'*64, 'start': None}
    records = [record(positions[1], day='2026-10-26', quantity=1)]
    if quantity is not None:
        records.append(record(positions[0], sha='e', number='2', day='2026-10-26', quantity=quantity))
    for item in records:
        item['act']['start'] = '2026-10-11'
    if source == 'unread':
        records[0]['warnings'] = ['В акте не прочитана строка с единицей, но без количества.']
    elif source == 'undated':
        records[0]['act'].update(date=None, start=None, finish=None)
    elif source == 'absent':
        records = []
    performed = acts.accumulated(records, cut)
    planned = plan.build([edition], cut)
    actual = fact.build([edition], planned['in_force'], None, cut, performed)
    cached = {'ok': True, 'pending': False, **files._with_control({
        'contract_id': 'c'*64, 'documents': documents, 'plan': planned, 'fact': actual}, None, cut)}
    if duplicate:
        schedule['lines'].append(copy.deepcopy(schedule['lines'][0]))
    cached['rds_comparison'] = rds.build(cached)
    cached['comparison_export'] = export.bind_snapshot('Учебный проект', cut, 'c'*64, cached, {})
    return cached


def first(cached):
    return cached['rds_comparison']['rows'][0]


def workbook(cached, *, data_only):
    table = cached['rds_comparison']
    return load_workbook(io.BytesIO(export.workbook(cached['comparison_export'], table, table['rows'])),
                         data_only=data_only).active


def test_unreported_zero_has_calendar_exposure_and_ks_bound_without_invented_lag_or_finish():
    cached = source_card()
    before = copy.deepcopy(cached)
    row = first(cached)
    view = rds.reporting_row(row)
    report = row['schedule_reporting']
    assert row['fact_quantity'] is None and row['day_deviation'] is None
    assert view['fact_quantity'] == 0 and view['quantity_deviation'] == -179.45
    assert report['gpr_deadline_elapsed_days'] == 28
    assert report['earned_plan_day_deviation'] is None
    assert report['completion_state'] == 'unconfirmed'
    assert report['current']['kind'] == 'gpr_deadline_elapsed_unconfirmed'
    assert report['current']['value'] == 28 and 'не подтверждено' in report['current']['text']
    assert report['finish']['value'] is row['forecast_finish'] is row['forecast_delay_days'] is None
    assert 'нет подтверждённого темпа' in report['finish']['text']
    assert report['delay']['kind'] == 'ks_closure_lower_bound' and report['delay']['value'] == 28
    assert 'Не менее 28' in report['delay']['text']
    assert 'не доказывает физическую просрочку' in report['delay']['basis']
    assert cached == before


def test_explicit_zero_retains_distinct_earned_plan_lag_but_no_point_forecast():
    row = first(source_card(quantity=0))
    report = row['schedule_reporting']
    assert row['fact_quantity'] == 0 and 'ks_reporting' not in row
    assert row['day_deviation'] == report['earned_plan_day_deviation'] == 49
    assert report['gpr_deadline_elapsed_days'] == 28
    assert report['current']['kind'] == 'physical_plan_day_deviation'
    assert report['current']['value'] == 49
    assert report['delay']['kind'] == 'ks_quantity_lower_bound' and report['delay']['value'] == 28
    assert 'не доказанная физическая просрочка' in report['delay']['basis']
    assert row['forecast_finish'] is row['forecast_delay_days'] is None


@pytest.mark.parametrize('cut,finish', [('2026-10-01', '2026-10-31'),
    ('2026-10-31', '2026-10-31'), ('2026-11-28', '2026-11-30')])
def test_before_start_future_and_equal_deadline_have_no_overdue_bound(cut, finish):
    row = first(source_card(cut=cut, finish=finish, quantity=0))
    report = row['schedule_reporting']
    assert report['gpr_deadline_elapsed_days'] == 0
    assert report['delay']['kind'] == 'unknown' and report['delay']['value'] is None
    assert row['forecast_finish'] is row['forecast_delay_days'] is None
    if cut == '2026-10-01':
        assert row['fact_quantity'] is None and 'ks_reporting' not in row
        assert 'ещё не наступил' in report['current']['text']


@pytest.mark.parametrize('source', ['unread', 'undated', 'absent'])
def test_unknown_source_stays_unknown_with_qualified_elapsed_calendar(source):
    row = first(source_card(source=source))
    assert row['fact_quantity'] is None and 'ks_reporting' not in row
    report = row['schedule_reporting']
    assert report['credited_zero'] is False and report['earned_plan_day_deviation'] is None
    assert report['gpr_deadline_elapsed_days'] == 28
    assert report['current']['kind'] == 'gpr_deadline_elapsed_unconfirmed'
    assert report['delay']['kind'] == 'ks_closure_lower_bound'
    assert report['finish']['value'] is None


def test_positive_dated_quantity_keeps_native_remaining_forecast_and_finished_keeps_actual():
    partial = first(source_card(quantity=50))
    assert partial['forecast_finish'] and partial['forecast_kind'] == 'physical_remaining_forecast'
    assert partial['schedule_reporting']['finish']['kind'] == 'forecast'
    assert partial['schedule_reporting']['delay']['kind'] == 'forecast'
    complete = first(source_card(quantity=179.45))
    report = complete['schedule_reporting']
    assert complete['forecast_finish'] == '2026-10-26'
    assert report['completion_state'] == 'ks_quantity_complete'
    assert report['finish']['kind'] == report['delay']['kind'] == 'actual'
    assert report['delay']['value'] == -5 and report['current']['value'] == 0


@pytest.mark.parametrize('kwargs', [{'share': .5}, {'duplicate': True}])
def test_partial_or_ambiguous_schedule_link_cannot_establish_position_deadline_bound(kwargs):
    row = first(source_card(**kwargs))
    report = row['schedule_reporting']
    assert report['gpr_finish'] is report['gpr_deadline_elapsed_days'] is None
    assert report['current']['value'] is report['delay']['value'] is None


def test_source_schedule_gaps_do_not_change_elapsed_deadline_or_create_zero_rate():
    report = first(source_card(disjoint=True))['schedule_reporting']
    assert report['gpr_deadline_elapsed_days'] == 28
    assert report['earned_plan_day_deviation'] is None and report['finish']['value'] is None


@pytest.mark.parametrize('finish', [None, '', 'not-a-date', '2026-02-30'])
def test_invalid_or_missing_schedule_dates_cannot_create_numeric_exposure(finish):
    row = first(source_card())
    row['finish'] = finish
    report = rds._schedule_reporting(row, '2026-11-28', full_schedule_link=True)
    assert report['gpr_finish'] is report['gpr_deadline_elapsed_days'] is None
    assert report['current']['value'] is report['delay']['value'] is None


def test_excel_cached_values_and_formats_preserve_qualified_bound_and_unknown_date():
    cached = source_card()
    before = copy.deepcopy(cached)
    cached_sheet = workbook(cached, data_only=True)
    formulas = workbook(cached, data_only=False)
    assert [cached_sheet.cell(7, col).value for col in (6, 8, 10, 14, 16)] == [179.45, 0, -179.45, 28, 28]
    assert 'не подтверждено' in cached_sheet['N7'].number_format
    assert 'не менее' in cached_sheet['P7'].number_format and 'по КС' in cached_sheet['P7'].number_format
    assert 'нет подтверждённого темпа' in cached_sheet['O7'].value
    assert formulas['P7'].data_type == 'n'  # A bound is not a fake date-minus-deadline formula.
    assert 'не доказывает физическую просрочку' in formulas['P7'].comment.text
    assert formulas['J7'].data_type == formulas['M7'].data_type == 'f'
    assert not any(cell.data_type == 'e' for row in cached_sheet for cell in row)
    assert cached == before


def test_excel_explicit_zero_and_completed_row_keep_physical_lag_and_point_delay_separate():
    zero = workbook(source_card(quantity=0), data_only=True)
    assert zero['N7'].value == 49 and zero['P7'].value == 28
    done = workbook(source_card(quantity=179.45), data_only=True)
    assert done['N7'].value == 0 and done['P7'].value == -5
    assert done['O7'].value.date().isoformat() == '2026-10-26'


def test_old_v9_snapshot_is_rejected_instead_of_exporting_blank_overdue_columns(monkeypatch):
    cached = source_card()
    with monkeypatch.context() as old:
        old.setattr(export, 'SCHEMA', 'contract-rds-plan-fact-export-v9')
        cached['comparison_export'] = export.bind_snapshot('Учебный проект', '2026-11-28', 'c'*64, cached, {})
    meta = cached['comparison_export']
    with pytest.raises(export.ExportProblem, match='Версия таблицы изменилась'):
        export.select_snapshot(cached, 'Учебный проект', '2026-11-28', 'c'*64, meta['revision'], meta['row_tokens'])


def test_old_projection_fails_visible_calendar_bound_assertion(monkeypatch):
    cached = source_card()
    monkeypatch.setattr(export, 'SCHEDULE_REPORTING_SCHEMA', 'old-schema-without-calendar-exposure')
    sheet = workbook(cached, data_only=True)
    with pytest.raises(AssertionError):
        assert sheet['N7'].value == 28 and sheet['P7'].value == 28
