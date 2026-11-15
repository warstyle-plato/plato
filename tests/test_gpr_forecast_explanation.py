"""Bounded explanations share the canonical forecast's exact member scope."""
import copy
import json

import developaid_schedule_plan_scenario as scenario

CUT = '2033-04-20'
SOURCE = 'a'*64
FULL = 'b'*64


def work(key, finish, *, plan='2033-06-01', measured=False, done=False):
    return dict(id=key, name='Учебная работа '+key, object='Учебный корпус',
                plan_start='2033-01-01', plan_finish=plan, construction_work=True,
                forecast_known=measured, forecast_finish=finish if measured else None,
                work_done=done, observed_complete_by='2033-04-18' if done else None,
                plan_pace_scenario=dict(finish=None if done else finish, complete=done,
                                        source_date='2033-04-18'))


def state(mapping, *, scope=None):
    return dict(source_sha256=SOURCE, cut=CUT, scope_label='Учебный состав',
        project=dict(work_ids=list(mapping), total=len(mapping), progress=None), corpora=[], matrix=[],
        forecast_identity=dict(id_scope='full_source', source_sha256=SOURCE,
                               full_source_sha256=FULL, remaining_ids=mapping),
        forecast_scope=scope or {})


def test_later_work_outside_selected_scope_cannot_explain_the_upper_date():
    rows = [work('selected', '2033-08-01'), work('outside', '2038-08-01')]
    value = state({'full-selected': 'selected'})
    before = copy.deepcopy(rows)
    scenario.decorate_readiness(value, rows)
    forecast = value['project']['forecast']
    assert forecast['finish'] == '2033-08-01'
    assert forecast['explanation']['rows'] == [dict(work_id='selected', reference_work_id='full-selected',
        finish='2033-08-01', plan_finish='2033-06-01', basis='conditional', delta_days=61, latest=True)]
    assert rows == before and value['project']['progress'] is None


def test_full_identity_is_translated_and_never_looked_up_as_a_current_id():
    value = state({'collision': 'current'})
    scenario.decorate_readiness(value, [work('collision', '2038-08-01'), work('current', '2033-07-01')])
    explanation = value['project']['forecast']['explanation']
    assert explanation['rows'][0]['work_id'] == 'current'
    assert explanation['rows'][0]['reference_work_id'] == 'collision'


def test_missing_ambiguous_and_excluded_members_remain_gaps_or_exclusions():
    value = state({'selected': 'selected', 'missing': None, 'separate': 'separate'},
                  scope={'separate': {'status': 'excluded', 'reason': 'separate_scope'}})
    scenario.decorate_readiness(value, [work('selected', '2033-07-01'), work('separate', '2038-08-01')])
    forecast = value['project']['forecast']
    assert (forecast['total'], forecast['covered'], forecast['reference_total']) == (2, 1, 3)
    assert forecast['explanation']['gap_count'] == forecast['explanation']['excluded_count'] == 1
    assert [r['work_id'] for r in forecast['explanation']['rows']] == ['selected']
    assert forecast['explanation']['counts']['unknown'] == 1
    ambiguous = state({'x': 'same', 'y': 'same'})
    scenario.decorate_readiness(ambiguous, [work('same', '2033-07-01')])
    assert not ambiguous['project']['forecast']['explanation']['rows']
    assert ambiguous['project']['forecast']['total'] == 2


def test_measured_priority_and_completed_observations_keep_native_semantics():
    current = work('measured', '2033-07-01', measured=True)
    current['plan_pace_scenario']['finish'] = '2038-01-01'
    completed = work('completed', '2039-01-01', done=True)
    completed['forecast_finish'] = '2039-01-01'
    completed['finished_late_days'] = 200
    value = state({'a': 'measured', 'b': 'completed'})
    scenario.decorate_readiness(value, [current, completed])
    forecast = value['project']['forecast']
    assert forecast['finish'] == '2033-07-01'
    assert [r['work_id'] for r in forecast['explanation']['rows']] == ['measured']
    assert forecast['explanation']['rows'][0]['basis'] == 'measured'
    assert forecast['explanation']['counts'] == dict(measured=1, conditional=0, complete=1, observation_only=1, unknown=0)


def test_many_latest_ties_and_large_shifts_have_a_fixed_five_row_budget():
    rows = [work(str(i), '2033-08-01') for i in range(12)]
    rows += [work('shifted', '2033-07-01', plan='2033-01-01')]
    value = state({r['id']: r['id'] for r in rows})
    scenario.decorate_readiness(value, rows)
    explanation = value['project']['forecast']['explanation']
    assert len(explanation['rows']) <= explanation['limit'] == 5
    assert explanation['latest_count'] == 12
    assert any(r['work_id'] == 'shifted' for r in explanation['rows'])
    assert sum(explanation['counts'][k] for k in ('measured','conditional','complete','unknown')) == 13


def test_stale_or_undated_progress_cannot_gain_a_date_from_its_plan():
    rows = [work('stale', None), work('undated', None)]
    value = state({r['id']: r['id'] for r in rows})
    scenario.decorate_readiness(value, rows)
    forecast = value['project']['forecast']
    assert forecast['finish'] is None and forecast['covered'] == 0
    assert not forecast['explanation']['rows']
    assert forecast['explanation']['counts']['unknown'] == 2


def test_explanation_does_not_export_unbounded_names_or_reference_ids():
    value = state({'r'*4096: 'current'})
    row = work('current', '2033-08-01')
    row['name'] = 'x'*100_000
    scenario.decorate_readiness(value, [row])
    forecast = value['project']['forecast']
    assert forecast['finish'] == '2033-08-01'
    assert not forecast['explanation']['rows'] and forecast['explanation']['unlinked_count'] == 1
    assert len(json.dumps(forecast['explanation'])) < 16_384
