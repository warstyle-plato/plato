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
    return contracts._source_identity(ledger) or ('', '', '', None)


def position_identity(ledger, item):
    """A bounded fingerprint, not a fuzzy work-name or row-number match."""
    customer, contractor, number, contract_date = contract_identity(ledger)
    plan = contracts._number(item.get('plan_quantity'))
    year = ledger.get('period_year')
    unit = ''.join(str(item.get('unit') or '').casefold().replace('²', '2').replace('³', '3').split())
    name, scope = contracts._norm(item.get('name')), contracts._norm(item.get('scope'))
    position = contracts._norm(item.get('position'))
    if (not all((customer, contractor, number, contract_date, name, scope, unit, position))
            or type(year) is not int or year <= 0 or plan is None or plan <= 0):
        return None
    declared_scope = {field: item.get(field) or ledger.get(field) for field in
                      ('object_scope', 'system_scope', 'site_scope')}
    sections = [(row.get('position'), row.get('name')) if isinstance(row, dict) else row
                for row in item.get('section_path') or []]
    payload = (customer, contractor, number, contract_date, year, position, name, scope, unit, plan,
               declared_scope, sections)
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def position_view(ledger, item, cut, observation_date):
    """Canonical quantity plus explicit source metadata, with no new formula."""
    view = contracts._physical(item, dict(ledger, source_date=observation_date), cut)
    return dict(view, contract=ledger.get('contract') or '',
                contract_date=ledger.get('contract_date') or '', contractor=ledger.get('contractor') or '',
                customer=ledger.get('customer') or '', position_key=position_identity(ledger, item),
                source_date_key=contracts._source_date_key(ledger),
                contract_date_evidence=ledger.get('contract_date_evidence') or ledger.get('date_evidence') or [],
                file_sha256=ledger.get('file_sha256'), ledger_source=ledger.get('source') or {},
                planned_work_amount=item.get('planned_work_amount'),
                planned_material_amount=item.get('planned_material_amount'),
                planned_cost_split=item.get('planned_cost_split') is True,
                planned_work_amount_basis=item.get('planned_work_amount_basis'),
                valuation_key=((item.get('source') or {}).get('filename'),
                               (item.get('source') or {}).get('sheet'), ledger.get('period_year')),
                is_group=item.get('is_group') is True, section_path=item.get('section_path') or [],
                context_headings=item.get('context_headings') or [], parent_row=item.get('parent_row'),
                object_scope=item.get('object_scope') or ledger.get('object_scope'),
                system_scope=item.get('system_scope') or ledger.get('system_scope'),
                site_scope=item.get('site_scope') or ledger.get('site_scope'),
                scope_evidence=ledger.get('scope_evidence') or {}, planned_cost_method=item.get('planned_cost_method'))


def quantity_views(snapshot, cut):
    """Use the same position calculation as the contract table."""
    day = snapshot_date(snapshot)
    return {f'{li}:{ii}': position_view(ledger, item, cut, day)
            for li, ledger in enumerate((snapshot or {}).get('ledgers') or [])
            for ii, item in enumerate(ledger.get('items') or [])}


def aggregate_quantities(members):
    """One owner of heterogeneous natural progress, weighted only by explicit SMR.

    A monetary completion percentage is a different metric. Materials never
    weight these already calculated quantity fractions; a zero-price real leaf
    remains part of coverage and of the all-complete decision.
    """
    leaves = [member for member in members if member.get('is_group') is not True]
    result = {'ratio': None, 'basis': 'smr_cost_weighted_quantities',
              'label': 'По объёмам работ с весом стоимости СМР', 'complete_coverage': False,
              'member_keys': [member.get('member_key') for member in leaves],
              'members': len(leaves), 'excluded_groups': len(members)-len(leaves),
              'all_complete': False, 'requires_reconciliation': False, 'reason': ''}
    if not leaves:
        return dict(result, reason='Нет отдельных позиций работ для расчёта процента.')
    ratios = [contracts._number(member.get('progress')) for member in leaves]
    if any(ratio is None or ratio < 0 for ratio in ratios):
        return dict(result, reason='В одной из позиций не подтверждён выполненный объём.')
    units = [str(member.get('unit') or '').strip() for member in leaves]
    if any(not unit for unit in units):
        return dict(result, reason='В одной из позиций не указана единица измерения.')
    result['all_complete'] = all(abs(ratio-1.0) <= 1e-7 for ratio in ratios)
    result['requires_reconciliation'] = any(ratio > 1.0+1e-7 for ratio in ratios)
    if len(leaves) == 1:
        return dict(result, ratio=ratios[0], basis='natural_quantity', label='По объёму работы', complete_coverage=True)
    weights = [contracts._number(member.get('planned_work_amount')) for member in leaves]
    if any(member.get('planned_cost_split') is not True or weight is None or weight < 0
           for member, weight in zip(leaves, weights)):
        return dict(result, reason='Для общего процента не хватает явно выделенной полной стоимости СМР по каждой позиции.')
    bases = {member.get('planned_work_amount_basis') for member in leaves} - {None, '', 'unspecified'}
    if 'conflicting' in bases or len(bases) > 1:
        return dict(result, reason='Позиции имеют разные основания НДС стоимости СМР; общий процент не рассчитан.')
    positive = [member for member, weight in zip(leaves, weights) if weight > 0]
    valuations = {tuple(member.get('valuation_key') or ()) for member in positive}
    if len(valuations) > 1 and any(member.get('planned_work_amount_basis') not in
                                  {'with_vat', 'without_vat'} for member in positive):
        return dict(result, reason='Для стоимостных весов разных ведомостей не подтверждена общая база.')
    total = math.fsum(weights)
    if total <= 0:
        return dict(result, reason='Нет положительной полной стоимости СМР для весов общего процента.')
    if any(weight == 0 and abs(ratio-1.0) > 1e-7 for weight, ratio in zip(weights, ratios)):
        result['requires_reconciliation'] = True
        result['reason'] = 'Есть незавершённые работы с нулевой стоимостью СМР; 100% стоимостного веса не подтверждают завершение всех работ.'
    fingerprint = hashlib.sha256(json.dumps(sorted([(member.get('member_key'), weight,
        member.get('planned_work_amount_basis'), member.get('valuation_key'))
        for member, weight in zip(leaves, weights)], key=lambda value: str(value[0])),
        ensure_ascii=False, sort_keys=True, default=list).encode()).hexdigest()
    return dict(result, ratio=math.fsum(ratio*weight for ratio, weight in zip(ratios, weights))/total,
                complete_coverage=True, planned_work_amount=total, weight_fingerprint=fingerprint)


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
    if plan is None or plan <= 0 or done is None or done < 0:
        return None
    return {'plan': plan, 'done': done, 'ratio': done / plan, 'unit': view.get('unit') or '',
            'requires_reconciliation': done > plan + max(1e-6, plan * 1e-7),
            **{field: view.get(field) for field in ('period_year', 'planned_work_amount', 'planned_cost_split',
                                                  'planned_work_amount_basis', 'valuation_key')}}


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
            sources.append({'snapshot_id': None, 'taken_at': day, 'source_unavailable': True,
                            'source_ambiguous': True, 'ledgers': []})
            continue
        manifest = by_day[day][0]
        if manifest.get('snapshot_id') == current_id:
            source = snapshot
        else:
            try:
                source = ledgers.effective_snapshot(project, day,
                    snapshot=ledgers.read_snapshot(project, manifest['snapshot_id']))
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
            for item in ledger.get('items') or []:
                key = position_identity(ledger, item)
                if key not in keys:
                    continue
                if key in positions:
                    duplicates.add(key)
                    continue
                view = position_view(ledger, item, day, day)
                positions[key] = _observation(view)
        for key in duplicates:
            positions[key] = None
        out.append({'date': day, 'snapshot_id': source.get('snapshot_id'), 'positions': positions,
                    'source_unavailable': source.get('source_unavailable') is True,
                    'source_ambiguous': source.get('source_ambiguous') is True})
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
        points.append({'date': record['date'], 'snapshot_id': record['snapshot_id'],
                       'completed_quantity': done, 'plan_quantity': current['plan_quantity'],
                       'progress': done / current['plan_quantity'], 'date_basis': 'snapshot',
                       'requires_reconciliation': done > current['plan_quantity'] + max(1e-6, current['plan_quantity'] * 1e-7)})
    result['points'] = points
    current_day = current.get('observation_date')
    if not points or points[-1]['date'] != current_day:
        return dict(result, state='not_comparable',
                    reason='Текущий объём известен; позиции снимков не сопоставлены однозначно.')
    if len(points) < 2:
        if points[-1].get('requires_reconciliation'):
            return dict(result, state='requires_reconciliation', requires_reconciliation=True,
                        reason='Ведомость показывает превышение полного объёма; требуется сверка.')
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
    if latest.get('requires_reconciliation'):
        return dict(result, state='requires_reconciliation', requires_reconciliation=True,
                    reason='Ведомость показывает превышение полного объёма; требуется сверка.')
    if delta < -1e-7:
        return dict(result, state='correction', reason='Объём в последнем снимке уменьшился; нужна сверка корректировки.')
    if abs(delta) <= 1e-7:
        return dict(result, state='unchanged', rate_per_day=0.0,
                    reason='Между сопоставимыми снимками прироста объёма нет.')
    day = dt.date.fromisoformat(cut)
    window = [p for p in points if dt.date.fromisoformat(p['date']) >= day - dt.timedelta(days=WINDOW_DAYS)]
    if len(window) >= 2 and any(window[0]['date'] <= record['date'] <= window[-1]['date']
            and any(record['positions'].get(key) is None for key in keys) for record in index):
        return dict(result, state='comparison_gap',
                    reason='Промежуточный снимок не сопоставлен по полному составу; темп для прогноза не подтверждён.')
    if any(point.get('requires_reconciliation') for point in window):
        return dict(result, state='requires_reconciliation', requires_reconciliation=True,
                    reason='В истории ведомостей есть превышение полного объёма; темп для прогноза не подтверждён.')
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


def weighted_history(components, index, current_metric, observation_date):
    """Read the same aggregate at every snapshot; changed weights are explicit."""
    result = {'basis': 'smr_cost_weighted_quantities', 'date_basis': 'snapshot', 'points': [],
              'state': 'single_snapshot', 'delta_progress': None, 'delta_quantity': None,
              'reason': 'Для динамики нужен предыдущий сопоставимый снимок ведомостей.'}
    series = []
    lookups = [{(point['date'], point.get('snapshot_id')): point
                for point in (component.get('statement_history') or component.get('observation_history') or {}).get('points') or []}
               for component in components]
    for record in index:
        members, invalid = [], False
        for component, lookup in zip(components, lookups):
            member = component.get('quantity_member') or {}
            point = lookup.get((record['date'], record.get('snapshot_id')))
            values = [record['positions'].get(key) for key in member.get('item_keys') or []]
            if point is None or not values or any(value is None for value in values):
                invalid = True
                break
            latest = max(values, key=lambda value: value.get('period_year') or 0)
            members.append(dict(member, progress=point['progress'], **{field: latest.get(field) for field in
                ('planned_work_amount', 'planned_cost_split', 'planned_work_amount_basis', 'valuation_key')}))
        metric = aggregate_quantities(members) if not invalid else {'ratio': None, 'reason': 'Состав снимка не сопоставлен.'}
        series.append({'date': record['date'], 'snapshot_id': record.get('snapshot_id'),
                       'progress': metric['ratio'], 'basis_fingerprint': metric.get('weight_fingerprint'),
                       'requires_reconciliation': metric.get('requires_reconciliation', False),
                       'reason': metric.get('reason', ''), 'date_basis': 'snapshot'})
    result['points'] = series
    if len(series) < 2 or series[-1]['date'] != observation_date:
        return result
    previous, current = series[-2:]
    if (previous['progress'] is None or current['progress'] is None
            or current_metric.get('ratio') is None
            or abs(current['progress']-current_metric['ratio']) > 1e-7):
        return dict(result, state='comparison_gap', reason='Не подтверждён состав или полный вес одного из снимков.')
    if any(point['requires_reconciliation'] for point in (previous, current)):
        return dict(result, state='requires_reconciliation', reason='Объёмы требуют сверки; изменение общего процента не оценено.')
    if (not previous['basis_fingerprint'] or not current['basis_fingerprint']
            or previous['basis_fingerprint'] != current['basis_fingerprint']):
        return dict(result, state='basis_changed', reason='Стоимостные веса СМР в снимках различаются; проценты не сравнены.')
    days = (dt.date.fromisoformat(current['date'])-dt.date.fromisoformat(previous['date'])).days
    if days <= 0:
        return dict(result, state='comparison_gap', reason='Для динамики нужны снимки на разные даты.')
    delta = current['progress']-previous['progress']
    state = 'correction' if delta < -1e-7 else 'unchanged' if abs(delta) <= 1e-7 else 'growing'
    return dict(result, state=state, delta_progress=delta, previous_date=previous['date'], date=current['date'],
                reason='Изменение того же натурального показателя с неизменными весами СМР.')
