"""One work-date scope; neither readiness weights nor RNV are backfilled."""
import copy

import pytest

import developaid_gpr_work_forecast as work_dates
import developaid_report_gantt as gantt
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as readiness
from test_gpr_why_page import why_view
from test_management_calendar_membership import _native_scoped_view
from test_readiness_date_only_projection import site

CUT = '2035-04-10'
SOURCE = 'd'*64


def task(key, **changes):
    row = dict(id=key, level='task', object='Учебный корпус', section='Учебный этап',
               name='Учебная работа '+key, construction_work=True, source_format='corpus-gpr-v1',
               plan_start='2035-01-01', plan_finish='2035-08-01',
               display_progress=dict(value=0, date='2035-04-09', label='ГПР'),
               forecast_known=False, forecast_finish=None, work_done=False)
    row.update(changes)
    row['plan_pace_scenario'] = scenario.work(row, CUT)
    return row


def fallback(rows=None):
    rows = rows or [task('building'), task('admin', construction_work=False)]
    facts = {r['id']:dict(r, primary=r['display_progress']) for r in rows}
    state = readiness.model(dict(works=facts), cut=CUT, baseline_scope='remaining_work', source_sha256=SOURCE)
    scenario.decorate_readiness(state, rows)
    return dict(cut=CUT, approved_plan=dict(source_sha256=SOURCE), rows=rows, undated_works=[],
                management=copy.deepcopy(rows), readiness=state)


def profiled():
    view = why_view()
    value = view['schedule']
    value['cut'] = view['cut']
    value['approved_plan'] = dict(source_sha256=value['readiness']['source_sha256'])
    return value


def test_no_profile_dates_do_not_invent_weights_or_expand_to_untyped_rows():
    schedule = fallback()
    before = copy.deepcopy(schedule)
    value = work_dates.build(schedule, CUT)
    assert value['scope_kind'] == 'construction_partial'
    assert value['project']['progress'] is None
    assert value['project']['forecast']['total'] == 1
    assert value['project']['forecast']['finish'] == schedule['rows'][0]['plan_pace_scenario']['finish']
    assert [m['work_id'] for m in value['ordered_members']] == ['building']
    assert value['outside_members'] == [dict(work_id='admin', reason='outside_assessment_scope')]
    assert schedule == before


def test_comparable_plan_uses_exactly_the_covered_members_and_names_missing_work():
    missing = task('missing', plan_finish='2041-12-31', display_progress=dict(value=None, date='2035-04-09'))
    schedule = fallback([task('known'), task('complete', display_progress=dict(value=1, date='2035-04-09')),
                         missing])
    value = work_dates.build(schedule, CUT)
    forecast = value['project']['forecast']
    assert forecast['total'] == 3 and forecast['covered'] == 2 and forecast['missing'] == 1
    assert forecast['comparison_members'] == ['known', 'complete']
    assert forecast['comparison_plan_finish'] == '2035-08-01'
    assert value['missing_members'][0]['work_id'] == 'missing'
    assert value['state'] == 'partial'


def test_active_membership_survives_unknown_weights_and_does_not_expand():
    schedule = profiled()
    before = copy.deepcopy(schedule)
    value = work_dates.build(schedule, schedule['cut'])
    assert value['state'] != 'unavailable' and value['scope_kind'] == 'readiness_profile'
    assert value['project']['work_ids'] == schedule['readiness']['project']['work_ids']
    assert value['project']['forecast']['finish'] == schedule['readiness']['project']['forecast']['finish']
    assert schedule == before


def test_intended_missing_observation_is_not_relabelled_as_outside_in_report():
    schedule = profiled()
    target = next(r for r in schedule['rows'] if r['id'] == 'why-2')
    target['display_progress'] = dict(value=None, date='2033-04-18', label='ГПР')
    target['plan_pace_scenario'] = scenario.work(target, schedule['cut'])
    scenario.decorate_readiness(schedule['readiness'], schedule['rows']+schedule['undated_works'])
    value = work_dates.build(schedule, schedule['cut'])
    assert value['project']['forecast']['total'] == 3 and value['project']['forecast']['missing'] == 1
    assert target['id'] in {r['work_id'] for r in value['missing_members']}
    assert target['id'] not in {r['work_id'] for r in value['outside_members']}
    schedule['work_forecast'] = value
    block = dict(calendar=gantt.calendar(schedule, schedule['cut']), readiness=schedule['readiness'],
                 approved_plan=schedule['approved_plan'], work_forecast=value,
                 work_forecast_groups=schedule['display_groups'])
    model = gantt.compact_model(block, schedule['cut'])
    assert model['total'] == 3 and model['covered'] == 2
    assert sum(g.get('outside', 0) for g in model['groups']) == len(schedule['rows'])+len(schedule['undated_works'])-3


def test_attested_missing_point_with_current_identity_stays_inside_the_denominator():
    view = _native_scoped_view(classification=None)
    schedule = view['schedule']
    schedule.update(cut=view['cut'], approved_plan=dict(source_sha256=schedule['readiness']['source_sha256']))
    value = work_dates.build(schedule, view['cut'])
    assert value['state'] == 'partial' and value['scope_kind'] == 'readiness_profile'
    assert value['project']['forecast']['total'] == 2 and value['project']['forecast']['covered'] == 1
    assert value['missing_members'] == [dict(reference_work_id='other', work_id='other', reason='unclassified_scope')]
    assert value['outside_members'] == []
    assert value['project']['forecast']['comparison_plan_finish'] == '2027-01-01'
    aggregate = value['aggregates']['["build","other"]']
    assert aggregate['total'] == 2 and aggregate['covered'] == 1
    assert 'other' not in value['outside_points']
    schedule['work_forecast'] = value
    block = dict(calendar=gantt.calendar(schedule, view['cut']), readiness=schedule['readiness'],
                 approved_plan=schedule['approved_plan'], work_forecast=value)
    model = gantt.compact_model(block, view['cut'])
    assert model['total'] == 2 and model['covered'] == 1
    assert sum(g.get('outside', 0) for g in model['groups']) == 0


@pytest.mark.parametrize('status', ['invalid', 'active'])
def test_invalid_or_mismatched_active_profile_never_switches_to_construction_fallback(status):
    schedule = profiled()
    schedule['readiness']['profile_state'] = status
    schedule['readiness']['reason'] = 'Любая подпись без технических кодов.'
    if status == 'active':
        schedule['readiness']['source_sha256'] = 'e'*64
    value = work_dates.build(schedule, schedule['cut'])
    assert value['state'] == 'unavailable'


def test_future_profile_uses_work_dates_without_applying_future_weights():
    schedule = fallback()
    schedule['readiness'].update(profile_state='future', pending_profile='future',
                                 profile_state_reason='profile_not_yet_effective')
    value = work_dates.build(schedule, CUT)
    assert value['scope_kind'] == 'construction_partial' and value['project']['progress'] is None
    assert value['project']['forecast']['finish']


def test_audited_date_carry_matches_native_owner_event_and_independent_fact_lineage(site):
    import developaid_monitor as monitor
    from test_readiness_date_only_projection import PROJECT, NOW, save_profile, prepared, approve
    save_profile(site)
    approve(prepared(site))
    for cut in ['2026-11-16', NOW]:
        schedule = monitor.build(PROJECT, cut)['schedule']
        state = schedule['readiness']
        value = work_dates.build(schedule, cut)
        assert value['scope_kind'] == 'readiness_profile' and value['state'] != 'unavailable'
        assert value['reference_source_sha256'] == state['profile_reference_source_sha256'] == site['parent']['source_sha256']
        assert value['project']['work_ids'] == state['project']['work_ids']
        for empty in [{}, False, None, []]:
            bad = copy.deepcopy(schedule)
            bad['readiness']['profile_source_carry'] = empty
            assert work_dates.build(bad, cut)['reason_code'] == 'profile_carry_binding'
        missing_carry = copy.deepcopy(schedule)
        missing_carry['readiness'].pop('profile_source_carry')
        assert work_dates.build(missing_carry, cut)['reason_code'] == 'profile_carry_binding'
        block = dict(calendar=gantt.calendar(schedule, cut), readiness=state,
                     approved_plan=schedule['approved_plan'], work_forecast=value,
                     work_forecast_groups=schedule['display_groups'])
        report = gantt.compact_model(block, cut)
        assert report['qualified'] and report['finish'] == value['summary']['finish']
        for branch, key, changed in [
            ('profile_source_carry', 'from_source_sha256', 'f'*64),
            ('profile_source_carry', 'source_revision', 99),
            ('profile_source_carry', 'profile_sha256', 'f'*64),
            ('profile_source_carry', 'profile_effective_from', '2026-11-15'),
        ]:
            bad = copy.deepcopy(schedule)
            bad['readiness'][branch][key] = changed
            assert work_dates.build(bad, cut)['reason_code'] == 'profile_carry_binding'
        legacy = copy.deepcopy(schedule)
        legacy['readiness'].pop('profile_reference_source_sha256')
        result = work_dates.build(legacy, cut)
        assert (result['state'] != 'unavailable') == bool(state.get('fact_source_carry'))
        if state.get('fact_source_carry'):
            legacy['readiness']['fact_source_carry']['from_source_sha256'] = 'f'*64
            assert work_dates.build(legacy, cut)['reason_code'] == 'profile_carry_binding'


@pytest.mark.parametrize('mutate', [
    lambda v:v.update(cut='2034-01-01'),
    lambda v:v.update(source_sha256='e'*64),
    lambda v:v['ordered_members'].reverse(),
    lambda v:v['project']['forecast'].update(finish='2045-01-01'),
])
def test_supplied_stale_or_changed_dto_is_rejected_without_repair(mutate):
    schedule = profiled()
    schedule['work_forecast'] = work_dates.build(schedule, schedule['cut'])
    mutate(schedule['work_forecast'])
    result = work_dates.for_schedule(schedule, schedule['cut'])
    assert result['state'] == 'unavailable' and result['reason_code'] == 'dto_binding'


def test_report_reads_the_same_known_partial_date_and_comparison():
    schedule = fallback([task('known'), task('missing', display_progress=dict(value=None, date='2035-04-09'))])
    schedule['work_forecast'] = work_dates.build(schedule, CUT)
    block = dict(calendar=gantt.calendar(schedule, CUT), readiness=schedule['readiness'],
                 approved_plan=schedule['approved_plan'], work_forecast=schedule['work_forecast'])
    result = gantt.compact_model(block, CUT)
    forecast = schedule['work_forecast']['project']['forecast']
    assert result['qualified'] and result['finish'] == forecast['finish']
    assert result['summary']['plan_finish'] == forecast['comparison_plan_finish']
    assert result['summary']['delta_days'] == forecast['delta_days']
    assert result['covered'] == 1 and result['total'] == 2


def test_dashboard_schedule_sentence_shares_the_dto_and_preserves_money_and_rnv():
    from developaid_monitor_dashboard import refresh_schedule_summary
    schedule = profiled()
    schedule['work_forecast'] = work_dates.build(schedule, schedule['cut'])
    value = dict(cut=schedule['cut'], schedule=schedule, dashboard=dict(
        schedule=dict(qualified_rnv=dict(state='partial', indicative_forecast='2048-01-01')),
        summary=['Срок. Прежняя другая оценка.', 'Бюджет: прежний текст.', 'Продажи: прежний текст.']))
    before = copy.deepcopy(value)
    refresh_schedule_summary(value)
    text = value['dashboard']['summary'][0]
    assert schedule['work_forecast']['summary']['forecast_text'] in text
    assert schedule['work_forecast']['summary']['scope_text'] in text
    assert '2048' not in text
    assert value['dashboard']['summary'][1:] == before['dashboard']['summary'][1:]
    assert value['dashboard']['schedule'] == before['dashboard']['schedule']
    assert schedule == before['schedule']


def test_no_usable_readings_names_the_missing_evidence_instead_of_missing_weights():
    schedule = fallback([task('unread', display_progress=dict(value=None, date='2035-04-09'))])
    value = work_dates.build(schedule, CUT)
    assert value['state'] == 'unavailable' and value['reason_code'] == 'no_usable_work_dates'
    assert value['project']['forecast']['total'] == 1 and value['project']['forecast']['missing'] == 1
    assert 'Учебная работа unread' in value['reason'] and 'профил' not in value['reason']


def test_method_limit_does_not_invent_a_milestone_or_remove_completed_facts():
    open_work = task('administrative', construction_work=False)
    assert open_work['plan_pace_scenario']['finish'] is None
    assert 'Процент из ГПР не позволяет' in open_work['plan_pace_scenario']['reason']
    completed = task('completed', construction_work=False, display_progress=dict(value=1, date='2035-04-09'))
    assert completed['plan_pace_scenario']['complete'] and completed['plan_pace_scenario']['finish'] is None
    measured = task('measured', construction_work=False, forecast_known=True, forecast_finish='2035-07-01')
    assert scenario.group([measured])['finish'] == '2035-07-01'


@pytest.mark.parametrize('source_format', [None, 'legacy-gpr'])
def test_legacy_wbs_keeps_the_existing_plan_pace_policy(source_format):
    row = task('legacy', source_format=source_format, construction_work=None)
    before = copy.deepcopy(row)
    assert scenario.work(row, CUT)['finish']
    assert row == before


@pytest.mark.parametrize('construction', [False, None])
def test_corpus_unknown_type_never_uses_calendar_duration(construction):
    row = task('corpus', construction_work=construction)
    assert row['plan_pace_scenario']['finish'] is None
