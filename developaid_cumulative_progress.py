"""Source-qualified quantity observations across immutable KS snapshots.

An observation date is the snapshot date, never an invented KS execution date.
Only an exact, unique contract/work/scope/unit/plan identity crosses snapshots.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers

WINDOW_DAYS = 90
STALE_DAYS = 45
MAX_SNAPSHOTS = 180


def _day(value):
    return contracts._date(value)


def snapshot_date(snapshot):
    value = (snapshot or {}).get('taken_at') or str((snapshot or {}).get('snapshot_id') or '')[:10]
    day = _day(value)
    sid = str((snapshot or {}).get('snapshot_id') or '')
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', sid):
        if day != sid[:10] or (snapshot or {}).get('sha256', sid[11:]) != sid[11:]:
            return None
    return day


def contract_identity(ledger):
    return (contracts._party_norm(ledger.get('customer')),
            contracts._party_norm(ledger.get('contractor')),
            contracts._contract_number(ledger.get('contract'), reference=True),
            _day(ledger.get('contract_date')))


def position_identity(ledger, item):
    """A bounded fingerprint, not a fuzzy work-name or row-number match."""
    customer, contractor, number, contract_date = contract_identity(ledger)
    plan = contracts._number(item.get('plan_quantity'))
    year = ledger.get('period_year')
    unit = ''.join(str(item.get('unit') or '').casefold().replace('²', '2').replace('³', '3').split())
    name, scope = contracts._norm(item.get('name')), contracts._norm(item.get('scope'))
    position = contracts._norm(item.get('position'))
    if (not all((customer, contractor, number, contract_date, name, scope, unit, position))
            or type(year) is not int or plan is None or plan <= 0):
        return None
    payload = (customer, contractor, number, contract_date, year, position, name, scope, unit, plan)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def quantity_views(snapshot, cut):
    """Use the same position calculation as the contract table."""
    out = {}
    day = snapshot_date(snapshot)
    for li, ledger in enumerate((snapshot or {}).get('ledgers') or []):
        context = dict(ledger, source_date=day)
        for ii, item in enumerate(ledger.get('items') or []):
            view = contracts._physical(item, context, cut)
            out[f'{li}:{ii}'] = dict(view, contract=ledger.get('contract') or '',
                                    contract_date=ledger.get('contract_date') or '',
                                    contractor=ledger.get('contractor') or '',
                                    customer=ledger.get('customer') or '',
                                    position_key=position_identity(ledger, item))
    return out


def project_configuration(previous, current, configuration):
    """Carry an explicit mapping only through unique exact source positions.

    This is an in-memory projection. It neither creates an assignment by name
    nor records a new manual confirmation on behalf of the operator.
    """
    old, old_seen, old_duplicates = {}, set(), set()
    for li, ledger in enumerate((previous or {}).get('ledgers') or []):
        for ii, item in enumerate(ledger.get('items') or []):
            key = position_identity(ledger, item)
            if key in old_seen:
                old_duplicates.add(key)
            old_seen.add(key)
            old[f'{li}:{ii}'] = key
    new, duplicates = {}, set()
    for li, ledger in enumerate((current or {}).get('ledgers') or []):
        for ii, item in enumerate(ledger.get('items') or []):
            key = position_identity(ledger, item)
            if key in new:
                duplicates.add(key)
            new[key] = f'{li}:{ii}'
    components, unresolved = [], set()
    for component in configuration.get('components') or []:
        keys = [old.get(item_id) for item_id in component['item_ids']]
        if (any(key is None or key in duplicates or key in old_duplicates or key not in new for key in keys)
                or len(set(keys)) != len(keys)):
            unresolved.add(component['task_id'])
            continue
        components.append(dict(component, item_ids=[new[key] for key in keys]))
    components = [component for component in components if component['task_id'] not in unresolved]
    if unresolved and not components and all(task['mode'] == 'quantities' for task in configuration.get('tasks') or []):
        return None
    return dict(configuration, tasks=[dict(task, scope_confirmed=False) if task['task_id'] in unresolved else dict(task)
                                     for task in configuration.get('tasks') or []], components=components)


def _observation(view):
    if view.get('future_periods_excluded') is not False:
        return None
    plan = contracts._number(view.get('plan_quantity'))
    done = contracts._number(view.get('completed_quantity'))
    if done is None:
        done = contracts._number(view.get('reported_completed_quantity'))
    if plan is None or plan <= 0 or done is None or not 0 <= done <= plan + max(1e-6, plan * 1e-7):
        return None
    return {'plan': plan, 'done': done, 'ratio': done / plan, 'unit': view.get('unit') or ''}


def observation_index(project, cut, snapshot, keys):
    """Read each historic source at most once for a bounded set of positions."""
    current_day = snapshot_date(snapshot)
    if not current_day or current_day > cut:
        return []
    keys = {key for key in keys if key}
    if not keys:
        return []
    history_unavailable = False
    try:
        manifests = [m for m in ledgers.list_snapshots(project)
                     if _day(m.get('taken_at')) and m['taken_at'] <= current_day]
    except (OSError, ValueError, KeyError, TypeError):
        manifests, history_unavailable = [], True
    by_day = {}
    for manifest in manifests:
        by_day.setdefault(manifest['taken_at'], []).append(manifest)
    current_id = (snapshot or {}).get('snapshot_id')
    selected = sorted(by_day, reverse=True)[:MAX_SNAPSHOTS]
    sources = []
    for day in reversed(selected):
        if len(by_day[day]) != 1:
            continue
        manifest = by_day[day][0]
        if manifest.get('snapshot_id') == current_id:
            source = snapshot
        else:
            try:
                source = ledgers.read_snapshot(project, manifest['snapshot_id'])
            except (OSError, ValueError, KeyError, TypeError):
                source = {'snapshot_id': manifest['snapshot_id'], 'taken_at': day,
                          'source_unavailable': True, 'ledgers': []}
        sources.append(source)
    if not any(s.get('snapshot_id') == current_id for s in sources) and len(by_day.get(current_day, [])) <= 1:
        sources.append(snapshot)
    out = []
    for source in sources:
        day = snapshot_date(source)
        if not day or day > current_day:
            continue
        positions, duplicates = {}, set()
        for li, ledger in enumerate(source.get('ledgers') or []):
            if type(ledger.get('period_year')) is not int or ledger['period_year'] > int(day[:4]):
                continue
            context = dict(ledger, source_date=day)
            for item in ledger.get('items') or []:
                key = position_identity(ledger, item)
                if key not in keys:
                    continue
                if key in positions:
                    duplicates.add(key)
                    continue
                view = contracts._physical(item, context, day)
                positions[key] = _observation(view)
        for key in duplicates:
            positions[key] = None
        out.append({'date': day, 'snapshot_id': source.get('snapshot_id'), 'positions': positions,
                    'source_unavailable': source.get('source_unavailable') is True})
    if history_unavailable:
        out.append({'date': current_day, 'snapshot_id': None, 'positions': {}, 'source_unavailable': True})
    return sorted(out, key=lambda row: (row['date'], str(row['snapshot_id'])))


def component_history(keys, index, current, cut):
    """Summarize changes of already calculated, comparable position quantities."""
    result = {'state': 'single_snapshot', 'basis': 'snapshot_observations', 'date_basis': 'snapshot',
              'points': [], 'delta_quantity': None, 'delta_progress': None,
              'rate_per_day': None, 'rate_window_start': None, 'rate_window_end': None,
              'forecast_eligible': False,
              'reason': 'Для динамики нужен предыдущий сопоставимый снимок ведомостей.'}
    if not keys or any(key is None for key in keys) or len(set(keys)) != len(keys):
        return dict(result, state='identity_unknown',
                    reason='Текущий объём известен; для сравнения снимков не подтверждена точная идентичность позиции.')
    points = []
    for record in index:
        values = [record['positions'].get(key) for key in keys]
        if any(value is None for value in values):
            continue
        # Multiple annual rows are one component with one full plan.
        plans = [value['plan'] for value in values]
        if any(abs(value - current['plan_quantity']) > max(1e-6, current['plan_quantity'] * 1e-7) for value in plans):
            continue
        done = math.fsum(value['done'] for value in values)
        if done > current['plan_quantity'] + max(1e-6, current['plan_quantity'] * 1e-7):
            continue
        points.append({'date': record['date'], 'snapshot_id': record['snapshot_id'],
                       'completed_quantity': done, 'plan_quantity': current['plan_quantity'],
                       'progress': done / current['plan_quantity'], 'date_basis': 'snapshot'})
    result['points'] = points
    current_day = current.get('observation_date')
    if not points or points[-1]['date'] != current_day:
        return dict(result, state='not_comparable',
                    reason='Текущий объём известен; позиции снимков не сопоставлены однозначно.')
    if len(points) < 2:
        if any(record.get('source_unavailable') for record in index):
            result.update(state='previous_unavailable', reason='Текущий объём известен; предыдущий снимок сейчас не читается.')
        return result
    previous, latest = points[-2:]
    days = (dt.date.fromisoformat(latest['date']) - dt.date.fromisoformat(previous['date'])).days
    if days <= 0:
        return dict(result, state='not_comparable', reason='Для динамики нужны снимки на разные даты.')
    delta = latest['completed_quantity'] - previous['completed_quantity']
    result.update(delta_quantity=delta, delta_progress=latest['progress'] - previous['progress'],
                  previous_date=previous['date'], date=latest['date'])
    if delta < -1e-7:
        return dict(result, state='correction', reason='Объём в последнем снимке уменьшился; нужна сверка корректировки.')
    if abs(delta) <= 1e-7:
        return dict(result, state='unchanged', rate_per_day=0.0,
                    reason='Между сопоставимыми снимками прироста объёма нет.')
    day = dt.date.fromisoformat(cut)
    window = [p for p in points if dt.date.fromisoformat(p['date']) >= day - dt.timedelta(days=WINDOW_DAYS)]
    if (len(window) < 2 or (day - dt.date.fromisoformat(latest['date'])).days > STALE_DAYS
            or any(record.get('source_unavailable') and dt.date.fromisoformat(record['date']) >= day - dt.timedelta(days=WINDOW_DAYS)
                   for record in index)
            or any(b['completed_quantity'] < a['completed_quantity'] - 1e-7 for a, b in zip(window, window[1:]))):
        return dict(result, state='growing', reason='Прирост объёма известен; для прогноза нет свежего сопоставимого темпа без корректировок.')
    elapsed = (dt.date.fromisoformat(window[-1]['date']) - dt.date.fromisoformat(window[0]['date'])).days
    growth = window[-1]['completed_quantity'] - window[0]['completed_quantity']
    if elapsed <= 0 or growth <= 0:
        return result
    return dict(result, state='growing', rate_per_day=growth / elapsed,
                rate_window_start=window[0]['date'], rate_window_end=window[-1]['date'],
                forecast_eligible=True, reason='По изменению объёмов между сопоставимыми снимками ведомостей.')
