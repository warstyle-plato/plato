"""A continuous elapsed-overdue period and a separately identified future remainder."""
import datetime as dt
import pytest
from tests.test_contract_gpr_earned_plan_equivalent import event,view


def test_calendar_overdue_is_continuous_from_deadline_to_cut_with_separate_evidence_date():
    value=view(53,[event(53,'2026-11-15')],finish='2026-11-10')['reporting']
    red=[b for b in value['bars'] if b['state']=='overdue']
    assert {d for b in red for d in range(b['start'],b['end'])}==set(range(10,24))
    assert [b['range_kind'] for b in red]==['retrospective_overdue_assessment','overdue_extension']
    assert red[0]['comparison_date']=='2026-11-15' and not red[0]['carried_forward']
    assert len(value['checkpoints'])==1
    assert max(b['end'] for b in red)==24
    forecast=value['forecast']
    assert forecast['start']=='2026-11-25'
    assert forecast['remaining_fraction']==pytest.approx(.47)
    assert forecast['basis']=='planned_start_average'
    assert forecast['rate_calendar_days']==24  # plan start to cut; no act-date work start
    assert forecast['days']==22  # ceil(24*47/53)
    assert forecast['finish']=='2026-12-16'


def test_dated_act_history_supplies_confirmation_without_a_dated_snapshot():
    row=view(53,[event(53,'2026-11-15')],finish='2026-11-10',source_dates=[])
    assert row['progress']['last_confirmed_at']=='2026-11-15'
    assert row['progress']['age_days']==9
    assert row['progress']['source_dates']==[]  # no source snapshot date invented
    assert row['deadline_status']['observed_at']=='2026-11-15'
    assert 'дата не подтверждена' not in row['deadline_status']['text']


def test_confirmed_period_pace_is_preferred_to_an_assumed_plan_start():
    value=view(53,[event(53,'2026-11-15','2026-11-06')],finish='2026-11-10')['reporting']
    forecast=value['forecast']
    assert forecast['basis']=='reported_period_rate'
    assert forecast['rate_calendar_days']==10
    assert forecast['days']==9  # ceil(10*47/53)
    assert forecast['finish']=='2026-12-03'
    assert forecast['is_forecast'] and forecast['not_actual_dates']


def test_zero_unknown_complete_or_unconfirmed_overdue_cannot_invent_a_future_finish():
    assert view(0,[event(0,'2026-11-15')],finish='2026-11-10')['reporting']['forecast'] is None
    assert view(100,[event(100,'2026-11-15')],finish='2026-11-10')['reporting']['forecast'] is None
    assert view(53,source_dates=['2026-11-09'],finish='2026-11-10')['reporting']['forecast']['basis']=='planned_start_average'


def test_later_catchup_closes_the_elapsed_red_segment_without_repainting_it():
    history=[event(53,'2026-11-15')]
    before=view(53,history,cut='2026-11-19',finish='2026-11-10')['reporting']
    after=view(100,history+[event(47,'2026-11-20',label='done')],finish='2026-11-10')['reporting']
    a={day for bar in before['bars'] if bar['state']=='overdue' for day in range(bar['start'],bar['end'])}
    b={day for bar in after['bars'] if bar['state']=='overdue' for day in range(bar['start'],bar['end'])}
    assert a==b==set(range(10,19))
    assert after['forecast'] is None


def test_missing_ks_after_deadline_is_red_calendar_delay_without_invented_fact():
    import developaid_contract_gpr_export as export
    value=export.presentation({'lines':[{'code':'G','name':'Работа','start':'2026-11-01','finish':'2026-11-10'}]}, {},'2026-11-24')['rows'][0]
    model=value['reporting']
    assert value['progress'] is None and model['current'] is None and model['forecast'] is None
    assert model['checkpoints']==[]
    bar,=model['bars']
    assert bar['state']=='overdue_unclosed' and bar['start']==10 and bar['end']==24
    assert bar['fact_quantity'] is None and bar['report_date'] is None
    assert value['deadline_status']['state']=='overdue_unclosed'


def test_overlapping_periods_cannot_be_called_a_measured_rate():
    value=view(53,[event(20,'2026-11-10','2026-11-01'),event(33,'2026-11-15','2026-11-05',label='overlap')],finish='2026-11-10')['reporting']
    assert value['forecast']['basis']=='planned_start_average'


def test_rds_and_page_refuse_rate_forecast_without_the_same_physical_gate():
    from tests.contract_rds_fixtures import native_card
    import developaid_contract_rds as rds
    import developaid_contract_gpr as gpr
    import developaid_contract_gpr_export as export
    dto=native_card()
    dto['plan']['cut']='2026-03-15'
    for line in dto['control']['lines']:
        line['lag_days']=line['ahead_days']=None
    comparison=rds.build(dto)
    row=comparison['rows'][0]
    assert row['fact_quantity']==6 and row['day_deviation'] is None
    assert row['forecast_finish'] is None
    schedule=next(d['schedule'] for d in dto['documents'] if d.get('schedule'))
    positions=gpr.position_projections(dto,comparison,schedule)
    shown=export.presentation(schedule,{},comparison['cut'],positions)
    assert shown['positions'][0]['reporting']['forecast'] is None


def test_source_gpr_and_its_only_rds_operation_share_period_rate_and_source_date():
    from tests.contract_rds_fixtures import native_card
    import developaid_contract_rds as rds
    import developaid_contract_gpr as gpr
    import developaid_contract_gpr_export as export
    dto=native_card();dto['plan']['cut']='2026-03-15'
    comparison=rds.build(dto)
    schedule=next(d['schedule'] for d in dto['documents'] if d.get('schedule'))
    positions=gpr.position_projections(dto,comparison,schedule)
    overlays=gpr.physical_overlays(dto,comparison)
    model=export.presentation(schedule,overlays,comparison['cut'],positions)
    source=next(r for r in model['rows'] if r['code']=='3.1')['reporting']
    operation=next(r for r in model['positions'] if r['number']=='3.1')['reporting']
    assert source['forecast']==operation['forecast']
    assert source['forecast']['basis']=='reported_period_rate'
    assert source['forecast']['finish']==comparison['rows'][0]['forecast_finish']
    assert source['last_confirmed_at']==operation['last_confirmed_at']
