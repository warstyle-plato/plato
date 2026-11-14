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
