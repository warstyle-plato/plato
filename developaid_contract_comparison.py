"""Read-only presentation of the canonical contract plan/fact comparison.

No independent forecast or fact calculation. Existing control rows own known
values. When fact is unavailable, the current plan still supplies its plan
values through the same plan/volume helpers, while actuals remain unknown.
"""
from __future__ import annotations

import datetime as dt

import developaid_contract_control as control
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links


def _row(line, volume, *, unknown=False, reason=''):
    natural = volume is not None
    return {'code': line['code'], 'name': line['name'], 'basis': 'volume' if natural else 'money',
            'unit': volume['unit'] if natural else '₽',
            'planned': volume['planned'] if natural else line.get('planned'),
            'fact': None if unknown else volume['fact'] if natural else line.get('fact'),
            'deviation': None if unknown else volume['deviation'] if natural else line.get('deviation'),
            **{key: None if unknown else line.get(key) for key in
               ('plan_done','readiness','percent','lag_days','ahead_days','overdue_days','forecast_finish','finished','late_days')},
            'due': line.get('due') or line.get('finish'),
            'state': 'unknown' if unknown else line.get('state'), 'reason': reason,
            'money_fallback': '' if natural else 'Денежно: сопоставимый объём в одной единице не определён.'}


def build(listed: dict, cut: str, source_sha256: str | None = None) -> dict:
    canonical = listed['control']
    current = next((e for e in listed['plan'].get('editions') or [] if e.get('in_force')), None)
    reason = (current or {}).get('note') or canonical.get('note') or listed['fact'].get('note') or ''
    result = {'cut': cut, 'lines': [], 'total': canonical.get('total'), 'forecast': canonical.get('forecast'),
              'reason': reason, 'source': canonical.get('source'), 'source_note': canonical.get('source_note') or '',
              'edition': current and {key: current.get(key) for key in ('title','date','estimate','schedule','start')},
              'plan_summary': current and {key: current.get(key) for key in ('planned','total','auto','overdue','outside','start','accepted','accepted_without_amount','without_amount')},
              'plan_assumption': listed['plan'].get('assumption') or '',
              'plan_editions': [{key:e.get(key) for key in ('title','date','until','in_force','total','note')} for e in listed['plan'].get('editions') or []],
              'left_out': canonical.get('left_out'), 'preliminary': canonical.get('preliminary',False),
              'schedule_source': canonical.get('schedule_source'),
              'assumption': canonical.get('assumption') or '', 'weights': canonical.get('weights') or ''}
    source_sha = ((current or {}).get('schedule_sha256') or
                  (canonical.get('schedule_source') or {}).get('sha256') or
                  (source_sha256 if current is None else None))
    document = next((d for d in listed.get('documents') or [] if d['sha256'] == source_sha), None)
    schedule = document and document.get('schedule')
    source_lines = (schedule or {}).get('lines') or []
    parents = {r.get('parent') for r in source_lines}
    source_works = [r for r in source_lines if r['code'] not in parents]
    result['coverage'] = {'calculated': len(canonical.get('lines') or []), 'source_works': len(source_works),
                          'source_rows': len(source_lines), 'source_known': bool(schedule),
                          'schedule_title': document and document.get('title'), 'schedule_sha256': source_sha}
    if canonical.get('lines'):
        result['lines'] = [_row(r, r.get('volume')) for r in canonical['lines']]
    elif current and current.get('lines'):
        start = dt.date.fromisoformat(current['start']) if current.get('start') else None
        day = dt.date.fromisoformat(cut)
        for row in current['lines']:
            due = control._span(row,start)[1].isoformat()
            volume = control._volume(row,plan.done(row,day,start),[],0.0)
            result['lines'].append(_row({**row,'due':due},volume,unknown=True,reason=reason))
    shown = {r['code'] for r in result['lines']}
    if schedule:
        unfit = links.unfit(schedule)
        for row in source_works:
            if row['code'] in shown:
                continue
            result['lines'].append({'code':row['code'],'name':row['name'],'basis':'unknown','unit':row.get('unit') or '',
                'planned':None,'fact':None,'deviation':None,'plan_done':None,'readiness':None,
                'lag_days':None,'ahead_days':None,'overdue_days':None,'forecast_finish':None,'finished':None,
                'due':row.get('finish'),'state':'unknown','reason':unfit.get(row['code']) or
                'Работа есть в ГПР, но объём из расчёта и выполнение КС с ней не сопоставлены.', 'money_fallback':''})
    result['coverage']['unknown'] = sum(r['state'] == 'unknown' for r in result['lines'])
    result['coverage']['partial'] = bool(result['coverage']['unknown'] or (canonical.get('left_out') or {}).get('count'))
    by_code = {}
    for source_row in source_lines:
        by_code.setdefault(source_row['code'],[]).append(source_row)
    for row in result['lines']:
        contexts,seen = [],set()
        own = by_code.get(row['code']) or []
        parent = own[0].get('parent') if len(own) == 1 else None
        while parent and parent not in seen:
            seen.add(parent)
            candidates = by_code.get(parent) or []
            if len(candidates) != 1:
                break
            contexts.insert(0,candidates[0]['name'])
            parent = candidates[0].get('parent')
        row['context'] = ' · '.join(contexts)
    return result
