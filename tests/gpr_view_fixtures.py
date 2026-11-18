"""Source-bound synthetic fixtures for the native work-date presentation.

Readiness HTML alone is not a producer response. Build the same dated roster,
profile projection and owner DTO used by the application before rendering it.
"""
import copy

import developaid_gpr_work_forecast as work_dates
import developaid_schedule_elements as elements
import developaid_schedule_groups as groups
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as readiness


def legacy_response(view):
    """Retained WBS fixtures use the actual owner selected by their source rows."""
    view = copy.deepcopy(view)
    schedule = view['schedule']
    if 'work_forecast' in schedule or not view.get('cut'):
        return view
    def leaves(items):
        for item in items:
            if item.get('children'):
                yield from leaves(item['children'])
            elif item.get('level') == 'task':
                yield item
    rows = list(leaves(schedule.get('management') or []))
    rows += schedule.get('undated_works') or []
    if not rows or any('id' not in row for row in rows):
        return view
    trusted = {'done', 'gpr_pace', 'gpr_done', 'cumulative_quantities',
               'cumulative_statement_pace', 'confirmed_completion'}
    for row in rows:
        row.setdefault('source_format', 'legacy-gpr')
        row['forecast_known'] = bool(row.get('pace_forecast_known')
                                     and row.get('pace_forecast_method') in trusted)
        if row['source_format'] == 'corpus-gpr-v1':
            row.setdefault('display_progress', dict(value=row.get('actual_progress'),
                                                    **(row.get('progress_source') or {})))
            row['plan_pace_scenario'] = scenario.work(row, view['cut'])
    source = (schedule.get('approved_plan') or {}).get('source_sha256') or 'a'*64
    state = readiness.model(dict(works={row['id']: dict(row,
        primary=copy.deepcopy(row.get('display_progress') or dict(
            value=row.get('actual_progress'), **(row.get('progress_source') or {}))))
        for row in rows}), cut=view['cut'], baseline_scope='remaining_work', source_sha256=source)
    scenario.decorate_readiness(state, rows)
    schedule.update(cut=view['cut'], approved_plan=dict(source_sha256=source),
        rows=[row for row in rows if row not in (schedule.get('undated_works') or [])],
        readiness=state)
    schedule.setdefault('dependency_timeline', dict(rnv=dict(basis='gpr', state='unknown',
        forecast=None, indicative_forecast=None, reasons=['Нет датированного темпа работ.'])))
    canonical = work_dates.applies_to(schedule)
    schedule['work_forecast_applicable'] = canonical
    if canonical:
        schedule['display_groups'] = groups.metadata(rows)
        schedule['work_forecast'] = work_dates.for_schedule(schedule, view['cut'])
        schedule.pop('legacy_work_forecast', None)
        display = schedule['work_forecast']
        if display['scope_kind'] != 'readiness_profile':
            display = copy.deepcopy(state)
            for group in [display['project'], *display['corpora'],
                          *(cell for stage in display.get('matrix', []) for cell in stage['cells'])]:
                group.pop('forecast', None)
        schedule['readiness_html'] = readiness.render(display, show_forecast=False)
    else:
        model = work_dates.legacy_model(schedule, view['cut'])
        schedule['legacy_work_forecast'] = model.get('summary')
    return view


def projected_readiness(rows, config, cut, *, confirmed=True, included_ids=None):
    facts = {row['id']: copy.deepcopy(row) for row in rows}
    included = list(facts) if included_ids is None else list(included_ids)
    profile = dict(scope_kind='construction', basis='estimated_elements',
        full_scope_confirmed=True, full_source_sha256='a'*64,
        remaining_source_sha256='a'*64, effective_from=cut,
        crosswalk=[dict(full_id=key, remaining_id=key) for key in facts],
        outside_completed_ids=[], included_ids=included,
        excluded_ids=[key for key in facts if key not in included],
        weights=[], element_profile=copy.deepcopy(config), label='Synthetic profile',
        source_reference='Synthetic complete roster')
    state = readiness.model(dict(works=facts), cut=cut,
        baseline_scope='remaining_work', source_sha256='a'*64,
        profile=profile if confirmed else None, full_rows=facts)
    if confirmed:
        state.update(profile_revision=1, profile_sha256=readiness._digest(profile),
                     profile_effective_from=cut)
    if not confirmed:
        state.update(elements.projection(rows, config, cut=cut, confirmed=False))
    return state


def readiness_view(rows, state, *, milestone=None):
    state = copy.deepcopy(state)
    cut = state['cut']
    tasks = copy.deepcopy(rows)
    for task in tasks:
        reading = task.get('primary') or task.get('display_progress') or dict(
            value=task.get('actual_progress'), **(task.get('progress_source') or {}))
        task.update(level='task', source_format='corpus-gpr-v1')
        task.setdefault('construction_work', True)
        task.setdefault('plan_start', cut[:4]+'-01-01')
        task.setdefault('plan_finish', cut[:4]+'-12-31')
        task.setdefault('display_progress', copy.deepcopy(reading))
        task.setdefault('actual_progress', reading.get('value'))
        task.setdefault('progress_kind', 'gpr_percent')
        task.setdefault('progress_source', copy.deepcopy(reading))
        task.setdefault('plan_pace_scenario', scenario.work(task, cut))
    scenario.decorate_readiness(state, tasks, milestone)
    schedule = dict(cut=cut, approved_plan=dict(source_sha256=state['source_sha256']),
        source_format='corpus-gpr-v1', work_forecast_applicable=True, rows=tasks, undated_works=[],
        management=copy.deepcopy(tasks), readiness=state,
        display_groups=groups.metadata(tasks))
    schedule['work_forecast'] = work_dates.for_schedule(schedule, cut)
    assert schedule['work_forecast']['state'] != 'unavailable', schedule['work_forecast']
    display = schedule['work_forecast']
    if display['scope_kind'] != 'readiness_profile':
        display = copy.deepcopy(state)
        for group in [display['project'], *display['corpora'],
                      *(cell for stage in display.get('matrix', []) for cell in stage['cells'])]:
            group.pop('forecast', None)
    schedule['readiness_html'] = readiness.render(display, show_forecast=False)
    return dict(cut=cut, schedule=schedule)
