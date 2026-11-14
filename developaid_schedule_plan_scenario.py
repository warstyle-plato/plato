"""A conditional calendar scenario; it never certifies measured work pace."""
from __future__ import annotations

import datetime as dt
import math

LABEL = 'При плановом темпе'
NOTE = ('Оставшаяся доля работы выполняется с календарной скоростью её планового интервала. '
        'Использован последний датированный процент; новых изменений после него не предполагается. '
        'Это условный сценарий, а не подтверждённый прогноз РНВ.')


def _day(value):
    try:
        return dt.date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def work(row, cut):
    fact = row.get('display_progress') or {}
    progress = fact.get('value')
    observed, day = _day(fact.get('date')), _day(cut)
    result = dict(finish=None, label=LABEL, note=NOTE, source_date=fact.get('date'), complete=False)
    if (day is None or observed is None or observed > day or fact.get('requires_reconciliation')
            or row.get('requires_reconciliation') or isinstance(progress, bool)
            or not isinstance(progress, (int,float)) or not math.isfinite(progress) or progress < 0):
        return dict(result, reason='Нет пригодного датированного процента для сценария.')
    if progress >= 1:
        return dict(result, complete=True, reason='100% по источнику не задают фактическую дату окончания.')
    from developaid_schedule_gpr_forecast import STALE_DAYS
    if (day-observed).days > STALE_DAYS:
        return dict(result, reason='Последнее показание устарело; сценарий не рассчитан.')
    start, finish = _day(row.get('plan_start')), _day(row.get('plan_finish'))
    if start is None or finish is None or finish < start:
        return dict(result, reason='Нет корректного планового интервала для сценария.')
    remaining = max(1, math.ceil(((finish-start).days+1)*(1-progress)))
    try:
        end = max(day,start)+dt.timedelta(days=remaining-1)
    except OverflowError:
        return dict(result, reason='Плановый интервал превышает допустимый календарь.')
    return dict(result, finish=end.isoformat(), reason=NOTE)


def summary(rows):
    groups = {}
    for row in rows:
        if row.get('construction_work') is not True:
            continue
        group = groups.setdefault(row.get('object') or 'Общие работы', [])
        group.append(row)
    result = []
    for name, members in sorted(groups.items()):
        covered, ends, sources = 0, [], []
        for row in members:
            scenario = row.get('plan_pace_scenario') or {}
            # A source-qualified measured forecast always has priority.
            measured = row.get('forecast_finish') if row.get('forecast_known') and not row.get('observed_complete_by') else None
            end = measured or scenario.get('finish')
            covered += bool(end or scenario.get('complete'))
            if end: ends.append(end)
            source = _day(scenario.get('source_date'))
            if source and (end or scenario.get('complete')):
                sources.append(source.isoformat())
        result.append(dict(name=name, finish=max(ends,default=None), covered=covered,
                           total=len(members), partial=True,
                           oldest_source_date=min(sources,default=None),
                           all_complete=all((r.get('plan_pace_scenario') or {}).get('complete') for r in members)))
    return result


def group(rows):
    """Latest known finish is bounded by coverage; it never certifies an RNV."""
    ends, covered, completed, sources, plans = [], 0, 0, [], []
    for row in rows:
        if _day(row.get('plan_finish')):
            plans.append(row['plan_finish'])
        scenario = row.get('plan_pace_scenario') or {}
        measured = row.get('forecast_finish') if row.get('forecast_known') and not row.get('observed_complete_by') else None
        done = bool(scenario.get('complete') or row.get('work_done'))
        finish = (measured or scenario.get('finish')) if not done else None
        covered += bool(done or finish)
        completed += done
        if finish:
            ends.append(finish)
        if (done or finish) and _day(scenario.get('source_date')):
            sources.append(scenario['source_date'])
    return dict(finish=max(ends, default=None), covered=covered, total=len(rows),
                plan_finish=max(plans, default=None), plan_covered=len(plans),
                all_complete=bool(rows) and completed == len(rows), partial=True,
                oldest_source_date=min(sources, default=None), label=LABEL,
                note='Условная оценка по известным работам; не подтверждённый прогноз РНВ.')


def decorate_readiness(state, rows, milestone_plan=None):
    from collections import Counter, defaultdict
    plan = milestone_plan or {}
    state['milestone_plan'] = (dict(date=plan['plan_date'], label=plan.get('plan_label') or 'План окончания работ')
                               if _day(plan.get('plan_date')) else None)
    by_id = defaultdict(list)
    for row in rows:
        if row.get('id') is not None:
            by_id[str(row['id'])].append(row)
    identity = state.get('forecast_identity') or {}
    mapping = identity.get('remaining_ids') or {}
    translations = Counter(str(value) for value in mapping.values() if value is not None)
    valid_identity = (identity.get('id_scope') in {'current_source', 'full_source'}
                      and identity.get('source_sha256') == state.get('source_sha256')
                      and (identity.get('id_scope') != 'full_source'
                           or bool(identity.get('full_source_sha256'))))
    scope = state.get('forecast_scope') or {}
    groups = [state['project'], *state['corpora'], *(cell for stage in state.get('matrix', []) for cell in stage['cells'])]
    for item in groups:
        ids = [str(key) for key in item.get('work_ids', [])]
        counts = Counter(ids)
        members, gaps, excluded = [], [], []

        def gap(key, reason, remaining_id=None):
            gaps.append(dict(work_id=key, remaining_id=remaining_id, kind=reason))
            members.append({})  # Retain every unresolved expected member.

        for key in ids:
            qualification = scope.get(key) or {}
            if qualification.get('status') == 'excluded':
                excluded.append(dict(work_id=key, kind=qualification['reason']))
            elif qualification.get('status') == 'gap':
                gap(key, qualification['reason'])
            elif counts[key] != 1:
                gap(key, 'ambiguous_reference_identity')
            elif not valid_identity or key not in mapping:
                gap(key, 'missing_identity_translation')
            elif mapping[key] is None:
                gap(key, 'outside_current_source')
            elif translations[str(mapping[key])] != 1:
                gap(key, 'ambiguous_identity_translation', str(mapping[key]))
            else:
                current = str(mapping[key])
                candidates = by_id.get(current, [])
                if not candidates:
                    gap(key, 'missing_current_work', current)
                elif len(candidates) != 1:
                    gap(key, 'ambiguous_current_identity', current)
                else:
                    members.append(candidates[0])
                    if not group(candidates)['covered']:
                        gaps.append(dict(work_id=key, remaining_id=current,
                                         kind='unknown_time'))
        # Older/incomplete projections cannot turn omitted membership into0/0.
        for _ in range(max(0, item.get('total', 0)-len(ids))):
            gap(None, 'missing_reference_membership')
        forecast = group(members)
        forecast.update(gaps=gaps, excluded=excluded,
                        reference_total=item.get('total', len(ids)),
                        reference_scope=state.get('scope_label'),
                        id_scope=identity.get('id_scope'),
                        source_sha256=state.get('source_sha256'),
                        full_source_sha256=identity.get('full_source_sha256'))
        item['forecast'] = forecast
