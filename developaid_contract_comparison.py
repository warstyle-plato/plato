"""Read-only presentation of the canonical contract plan/fact comparison.

No independent forecast or fact calculation. Existing control rows own known
values. When fact is unavailable, the current plan still supplies its plan
values through the same plan/volume helpers, while actuals remain unknown.
"""
from __future__ import annotations

import datetime as dt
import re

import developaid_contract_control as control
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links


def _building_section(headings):
    """Only a single explicit building from the unique ancestor chain.

    Use the same object reader as schedule matching. Mark ranges as plural
    too: the endpoints suffice to reject a multi-building heading.
    """
    places = set()
    for heading in headings:
        expanded = re.sub(r'(?<=\d)\s*[-–—/]\s*(?=\d)', ' и ', heading)
        places.update(links.buildings(expanded))
    return next(iter(places)).capitalize() if len(places) == 1 else ''


def _row(line, volume, *, unknown=False, reason=''):
    natural = volume is not None
    split = 'work_amount' in line
    share = line.get('plan_share')
    if share is None and line.get('planned') is not None and line.get('amount'):
        share = line['planned']/line['amount']
    work_planned = (line['work_amount'] * share
                    if line.get('work_amount') is not None and share is not None else None)
    money_plan = work_planned if split else line.get('planned')
    money_fact = line.get('work_fact') if split else line.get('fact')
    money_deviation = money_fact-money_plan if money_plan is not None and money_fact is not None else None
    return {'code': line['code'], 'name': line['name'], 'basis': 'volume' if natural else 'money',
            **{key: line[key] for key in ('display_code', 'parent_code', 'position_key', 'source') if key in line},
            **({'physical_scope': line['operations']['group']} if line.get('operations') else {}),
            'unit': volume['unit'] if natural else '₽',
            'planned': volume['planned'] if natural else money_plan,
            'fact': None if unknown else volume['fact'] if natural else money_fact,
            'deviation': None if unknown else volume['deviation'] if natural else money_deviation,
            **{key: None if unknown else line.get(key) for key in
               ('plan_done','readiness','percent','lag_days','ahead_days','overdue_days','forecast_finish','finished','late_days')},
            'due': line.get('due') or line.get('finish'),
            'state': 'unknown' if unknown else line.get('state'), 'reason': reason,
            'money_fallback': '' if natural else ('Стоимость работ без материалов: сопоставимый объём в одной единице не определён.'
                                                  if split else 'Денежно: сопоставимый объём в одной единице не определён.')}


def build(listed: dict, cut: str, source_sha256: str | None = None) -> dict:
    canonical = listed['control']
    current = next((e for e in listed['plan'].get('editions') or [] if e.get('in_force')), None)
    reason = (current or {}).get('note') or canonical.get('note') or listed['fact'].get('note') or ''
    result = {'cut': cut, 'lines': [], 'total': canonical.get('total'), 'forecast': canonical.get('forecast'),
              'reason': reason, 'source': canonical.get('source'), 'source_note': canonical.get('source_note') or '',
              'edition': current and {key: current.get(key) for key in ('title','date','estimate','schedule','start','start_source')},
              'plan_summary': current and {key: current.get(key) for key in ('planned','total','auto','overdue','outside','start','accepted','accepted_without_amount','without_amount')},
              'plan_assumption': listed['plan'].get('assumption') or '',
              'plan_editions': [{key:e.get(key) for key in ('title','date','until','in_force','total','note')} for e in listed['plan'].get('editions') or []],
              'data_gaps': canonical.get('data_gaps') or [],
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
    supplies = {r['code'] for r in (current or {}).get('lines') or [] if r.get('supply_only')}
    source_works = [r for r in source_lines if r['code'] not in parents and r['code'] not in supplies]
    result['coverage'] = {'calculated': len(canonical.get('lines') or []), 'source_works': len(source_works),
                          'source_rows': len(source_lines), 'source_known': bool(schedule),
                          'schedule_title': document and document.get('title'), 'schedule_sha256': source_sha}
    if canonical.get('lines'):
        for native in canonical['lines']:
            row = _row(native, native.get('volume'))
            if native.get('operations'):
                row['money_fallback'] = ('Общая готовность операций — по стоимости работ без материалов. '
                                         'Объёмы отдельных операций показаны ниже и не складываются в площадь конструкции.')
            result['lines'].append(row)
            result['lines'].extend(_row(part, part.get('volume'))
                                   for part in (native.get('operations') or {}).get('lines') or [])
    elif current and current.get('lines'):
        start = dt.date.fromisoformat(current['start']) if current.get('start') else None
        day = dt.date.fromisoformat(cut)
        for row in current['lines']:
            if row.get('supply_only'):
                continue
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
    result['coverage']['unknown'] = sum(r['state'] == 'unknown' for r in result['lines'] if not r.get('parent_code'))
    result['coverage']['partial'] = bool(result['coverage']['unknown'] or (canonical.get('left_out') or {}).get('count') or result['data_gaps'])
    # A current estimate can describe only the remaining scope of an agreement.
    # Keep its calendar projection, but never promote it to the whole contract
    # while source works are unknown or absent from the comparison.
    result['coverage']['calculation_start'] = (current or {}).get('start')
    result['coverage']['prior_periods'] = ((listed.get('fact') or {}).get('before') or {}).get('count', 0)
    if result['forecast'] is not None:
        complete = (result['coverage']['source_known'] and not result['coverage']['partial']
                    and result['coverage']['calculated'] > 0
                    and result['coverage']['calculated'] == result['coverage']['source_works']
                    and not any(item.get('count') for item in ((current or {}).get('outside') or {}).values())
                    and not (current or {}).get('without_amount')
                    and not (current or {}).get('accepted_without_amount'))
        result['forecast'] = dict(result['forecast'], scope='matched_works',
                                  whole_contract_finish=result['forecast'].get('finish') if complete else None)
    by_code = {}
    for source_row in source_lines:
        by_code.setdefault(source_row['code'],[]).append(source_row)
    for row in result['lines']:
        contexts,seen = [],set()
        own = by_code.get(row.get('parent_code') or row['code']) or []
        section = (own[0].get('section') or '').strip() if len(own) == 1 else ''
        unambiguous = len(own) == 1
        parent = own[0].get('parent') if len(own) == 1 else None
        while parent and parent not in seen:
            candidates = by_code.get(parent) or []
            if len(candidates) != 1:
                unambiguous = unambiguous and not candidates
                break
            seen.add(parent)
            contexts.insert(0,candidates[0]['name'])
            if not section:
                section = (candidates[0].get('section') or '').strip()
            parent = candidates[0].get('parent')
        if not section and unambiguous and parent not in seen:
            section = _building_section(contexts)
        row['section'] = section
        if section and section not in contexts:
            contexts.insert(0, section)
        row['context'] = ' · '.join(contexts)
    # Keep every work separate, including identical names in different buildings.
    # The same ordered projection supplies the card, search and XLSX export.
    if any(row['section'] for row in result['lines']):
        order = {row['code']: index for index, row in enumerate(source_lines)
                 if len(by_code[row['code']]) == 1}
        groups = {}
        for row in sorted(result['lines'], key=lambda row: order.get(row.get('parent_code') or row['code'], len(source_lines))):
            groups.setdefault(row['section'], []).append(row)
        result['lines'] = [row for rows in groups.values() for row in rows]
    return result
