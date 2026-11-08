"""Read-only dynamics of the same qualified percentages shown by contracts.

Snapshot dates describe observations of source totals. They never become KS
execution dates, and changes of price, scope or tax basis are not work progress.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from typing import Callable

import developaid_monitor_ledgers as ledgers

MAX_RECENT_SNAPSHOTS = 12
WINDOW_DAYS = 90
_BASES = {'with_vat', 'without_vat', 'unspecified'}


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _basis_fingerprint(metric, denominator, first, second, year=None):
    if first not in _BASES or second not in _BASES:
        return None
    return _digest([metric, denominator, first, second, year])


def contract_identity(row):
    """Comparison identity only; existing contract ids and bindings stay intact."""
    from developaid_monitor_contracts import _source_identity
    return _source_identity(row)


def _source_key(source):
    return tuple(str((source or {}).get(field) or '') for field in ('filename', 'sheet'))


def _scope(row, reference=None):
    from developaid_monitor_contracts import _norm
    items = row.get('physical_items') or []
    if reference is not None:
        key = _source_key(reference.get('source'))
        if not key[0]:
            return None
        selected = [item for item in items if _source_key(item.get('source')) == key]
        # A single source can omit file labels in an older saved projection.
        if not selected and len(row.get('reported_performance_sources') or []) == 1:
            selected = items
        items = selected
    if not items:
        return None
    positions = {}
    for item in items:
        key = tuple(_norm(item.get(field)) for field in ('position', 'name', 'scope', 'unit'))
        plan = _number(item.get('plan_quantity'))
        year = item.get('period_year')
        if not key[1] or not key[3] or plan is None or not isinstance(year, int) or isinstance(year, bool):
            return None
        identity = (*key, year)
        definition = (plan, _number(item.get('planned_amount')))
        if identity in positions and positions[identity] != definition:
            return None
        positions[identity] = definition
    return _digest(sorted((identity, definition) for identity, definition in positions.items()))


def _observation(row, register):
    day = _day(register.get('source_date') or (register.get('snapshots') or {}).get('cumulative'))
    result = {'ratio': None, 'basis': None, 'basis_label': '', 'origin': None,
              'observation_date': day.isoformat() if day else None,
              'date_basis': 'snapshot',
              'snapshot_id': (register.get('snapshots') or {}).get('cumulative_id'),
              'scope_fingerprint': None, 'basis_fingerprint': None,
              'state': 'unknown', 'reason': 'Общий процент по ведомости не рассчитан.'}
    ratio = _number(row.get('completion_ratio'))
    amount = _number(row.get('amount'))
    completed = _number(row.get('completed'))
    if (ratio is not None and amount is not None and amount > 0 and completed is not None
            and row.get('monetary_comparable') is True):
        scope = _scope(row)
        result.update(ratio=ratio, basis='contract_amount', basis_label='суммы договора',
                      origin='dated_cumulative', planned=amount, completed=completed,
                      scope_fingerprint=scope,
                      basis_fingerprint=_basis_fingerprint('contract_amount', amount,
                                                  row.get('amount_basis'), row.get('completed_basis')), state='known',
                      reason='Выполнение по датированным накопительным.')
    else:
        from developaid_monitor_statement_union import statement_union
        supplied_union = isinstance(row.get('statement_progress'), dict)
        union = row['statement_progress'] if supplied_union else statement_union(row)
        union_ratio = _number(union.get('ratio'))
        if union.get('state') == 'known' and union_ratio is not None:
            result.update(ratio=union_ratio, basis='statement_union',
                basis_label=union.get('basis_label') or 'стоимости работ по ведомостям',
                origin='cumulative_statement', planned=union.get('planned'),
                completed=union.get('completed'), remaining=union.get('remaining'),
                scope_fingerprint=union.get('scope_fingerprint'),
                basis_fingerprint=union.get('basis_signature'),
                coverage=union.get('coverage'), source_years=union.get('source_years'),
                coverage_basis=union.get('coverage_basis'), source_count=union.get('source_count'),
                state='known', reason=union.get('why') or '',
                requires_reconciliation=bool(union.get('requires_reconciliation'))
                    or union_ratio < 0 or union_ratio > 1)
            return result
        if supplied_union:
            result.update(state=union.get('state') or 'unknown',
                          reason=union.get('why') or 'Общий процент по ведомостям не подтверждён.')
            return result
        candidates = {}
        qualified = 0
        references = row.get('reported_performance_sources') or []
        for reference in references:
            value = _number(reference.get('completion_ratio'))
            planned = _number(reference.get('planned'))
            done = _number(reference.get('completed'))
            if (reference.get('amount_scope') != 'statement'
                    or reference.get('future_periods_excluded') is not False
                    or reference.get('monetary_comparable') is not True
                    or value is None or planned is None or planned <= 0 or done is None):
                continue
            qualified += 1
            scope = _scope(row, reference)
            basis = _basis_fingerprint('statement', planned, reference.get('planned_amount_basis'),
                                       reference.get('completed_amount_basis'), reference.get('period_year'))
            # Equal values alone do not prove that two source scopes are copies.
            source = scope if scope else (_source_key(reference.get('source')),
                                          (reference.get('source') or {}).get('row'))
            candidates[(source, basis, value, done)] = (reference, value, scope, basis)
        if qualified != len(references) and len(references) > 1:
            result.update(state='partial_sources', reason=
                'Проценты отдельных ведомостей известны, но не все источники квалифицированы для общего итога.')
        elif len(candidates) == 1:
            reference, ratio, scope, basis = next(iter(candidates.values()))
            result.update(ratio=ratio, basis='statement', basis_label='стоимости ведомости',
                          origin='cumulative_statement', planned=reference['planned'],
                          completed=reference['completed'], scope_fingerprint=scope,
                          basis_fingerprint=basis, state='known',
                          source=dict(reference.get('source') or {}),
                          reason='По загруженной ведомости; дата наблюдения — дата снимка.')
        elif len(candidates) > 1:
            result.update(state='ambiguous_sources', reason=
                'Проценты отдельных ведомостей известны; их состав или итоги различаются. Общий процент не выбран.')
        elif any(reference.get('monetary_comparable') is False for reference in references):
            result.update(state='incomparable_basis', reason=
                'Итоги ведомости есть; основания стоимостей требуют сверки перед расчётом общего процента.')
        elif any(reference.get('future_periods_excluded') is True for reference in references):
            result.update(state='future_periods', reason=
                'Итог содержит периоды после выбранной даты; процент этого итога не использован.')
        elif any(reference.get('future_periods_excluded') is not False for reference in references):
            result.update(state='qualification_unverified', reason=
                'Итог ведомости есть; актуальная проверка периодов для этого показателя не получена.')
        elif references:
            if any(_number(reference.get('planned')) is None or _number(reference.get('planned')) <= 0
                   for reference in references):
                result.update(state='missing_statement_price', reason=
                    'Итоги ведомости есть; для общего процента не подтверждена положительная полная стоимость её позиций.')
            elif any(_number(reference.get('completed')) is None for reference in references):
                result.update(state='missing_statement_total', reason=
                    'Плановая стоимость известна; общий выполненный итог ведомости не подтверждён.')
            else:
                result.update(state='source_percentage_unknown', reason=
                    'Итоги ведомости известны; общий процент не получен из текущего разбора источника.')
    if result['ratio'] is not None:
        result['requires_reconciliation'] = result['ratio'] < 0 or result['ratio'] > 1
    return result


def _point(observation):
    return {key: observation.get(key) for key in (
        'ratio', 'basis', 'basis_label', 'origin', 'observation_date', 'date_basis',
        'snapshot_id', 'scope_fingerprint', 'basis_fingerprint', 'coverage', 'source_years',
        'coverage_basis', 'state', 'reason')}


def _selected_snapshots(project, current_day):
    by_day = defaultdict(dict)
    for snapshot in ledgers.list_snapshots(project):
        day = _day(snapshot.get('taken_at'))
        identifier = snapshot.get('snapshot_id')
        if day and day < current_day and identifier:
            by_day[day][identifier] = snapshot
    days = sorted(by_day)
    first = current_day - dt.timedelta(days=WINDOW_DAYS)
    recent = [day for day in days if day >= first][-MAX_RECENT_SNAPSHOTS:]
    older = [day for day in days if day < first]
    selected = ([older[-1]] if older else []) + recent
    return [(day, list(by_day[day])) for day in selected], len(selected) < len(days)


def _compare(progress):
    progress.update(delta_percent_points=None, period_days=None, previous_ratio=None,
                    comparison_state='no_previous_snapshot', change_kind=None, coverage_change=None,
                    comparison_reason='Предыдущего снимка для сравнения нет; текущий процент показан по источнику.')
    if progress['ratio'] is None:
        progress.update(comparison_state='current_unknown', comparison_reason=progress['reason'])
        return
    if not _day(progress['observation_date']):
        progress.update(comparison_state='observation_date_unknown', comparison_reason=
                        'Текущий процент известен, но дата снимка для динамики не подтверждена.')
        return
    if len(progress['series']) < 2:
        return
    previous = progress['series'][-2]
    if previous['ratio'] is None:
        progress.update(comparison_state=previous['state'], comparison_reason=previous['reason'])
        return
    if (not progress['scope_fingerprint'] or not previous['scope_fingerprint']):
        progress.update(comparison_state='scope_unverified', comparison_reason=
                        'Текущий и предыдущий проценты известны, но совпадение состава работ не подтверждено.')
        return
    if progress['scope_fingerprint'] != previous['scope_fingerprint']:
        progress.update(comparison_state='scope_changed', comparison_reason=
                        'Состав, единицы, год или плановые объёмы ведомости изменились; проценты напрямую не сравниваются.')
        return
    if not progress['basis_fingerprint'] or not previous['basis_fingerprint']:
        progress.update(comparison_state='basis_unverified', comparison_reason=
                        'Текущий и предыдущий проценты известны; основания их сравнения не подтверждены.')
        return
    if progress['basis_fingerprint'] != previous['basis_fingerprint']:
        progress.update(comparison_state='basis_changed', comparison_reason=
                        'Цена или основание процента изменились; изменение не выдано за выполнение работ.')
        return
    if progress['basis'] == 'statement_union':
        previous_coverage, current_coverage = (_coverage(previous.get('coverage')),
                                               _coverage(progress.get('coverage')))
        if previous_coverage is None or current_coverage is None:
            progress.update(comparison_state='coverage_unverified', comparison_reason=
                            'Годовое покрытие работ для сравнения не подтверждено.')
            return
        if not previous_coverage <= current_coverage:
            progress.update(comparison_state='coverage_changed', comparison_reason=
                            'Охват годовых ведомостей изменился; сброс годового итога не считается изменением выполнения.')
            return
        progress['coverage_change'] = 'extended' if previous_coverage < current_coverage else 'unchanged'
    current_day, previous_day = _day(progress['observation_date']), _day(previous['observation_date'])
    if not current_day or not previous_day or current_day <= previous_day:
        progress.update(comparison_state='observation_date_unknown', comparison_reason=
                        'Для динамики нужны разные подтверждённые даты снимков.')
        return
    delta = (progress['ratio'] - previous['ratio']) * 100
    kind = 'growth' if delta > 0 else 'correction' if delta < 0 else 'unchanged'
    reasons = {'growth': 'Рост выполнения между сопоставимыми снимками ведомостей.',
               'correction': 'Итог ведомости уменьшен; проверьте корректировку объёмов.',
               'unchanged': 'В сопоставимых снимках ведомостей выполнение не изменилось.'}
    progress.update(delta_percent_points=delta, period_days=(current_day-previous_day).days,
                    previous_ratio=previous['ratio'], comparison_state='comparable',
                    change_kind=kind, comparison_reason=(
                        'С учётом добавленных годовых ведомостей. ' if progress['coverage_change'] == 'extended' else '') + reasons[kind])


def _coverage(value):
    if not isinstance(value, (list, tuple)) or not value:
        return None
    result = set()
    for entry in value:
        if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                or not isinstance(entry[0], str) or not isinstance(entry[1], int)
                or isinstance(entry[1], bool)):
            return None
        result.add(tuple(entry))
    return result


def enrich(project: str, cut: str, register: dict, *, build_register: Callable[[str], dict]) -> dict:
    """Attach canonical observations and deltas without mutating source registers.

    ``build_register(day)`` must build the ordinary register with history disabled.
    At most twelve recent snapshots and one ninety-day anchor are read once for
    all contracts. No source snapshots, manual decisions or contract ids change.
    """
    from developaid_monitor_contracts import ContractProblem
    rows = [dict(row) for row in register.get('rows') or []]
    result = dict(register, rows=rows)
    current_day = _day(register.get('source_date') or (register.get('snapshots') or {}).get('cumulative'))
    cutoff = _day(cut)
    for row in rows:
        row['progress'] = _observation(row, register)
        row['progress']['series'] = []
        if current_day and cutoff and current_day > cutoff:
            row['progress'].update(ratio=None, state='future_source', reason=
                                   'Дата источника позже выбранного среза; процент не использован.')
    errors, truncated = 0, False
    try:
        selected, truncated = (_selected_snapshots(project, current_day)
                               if current_day and cutoff and current_day <= cutoff else ([], False))
    except ledgers.LedgerProblem:
        selected, errors = [], 1
    for day, identifiers in selected:
        date = day.isoformat()
        failure = None
        by_identity = defaultdict(list)
        if len(identifiers) != 1:
            failure = ('ambiguous_snapshot_date', 'На предыдущую дату найдены разные снимки; динамика требует сверки.')
        else:
            try:
                previous = build_register(date)
                if ((previous.get('snapshots') or {}).get('cumulative_id') != identifiers[0]
                        or previous.get('source_date') != date):
                    failure = ('history_source_changed', 'Предыдущий снимок не совпал с выбранным источником истории.')
                else:
                    for previous_row in previous.get('rows') or []:
                        identity = contract_identity(previous_row)
                        if identity:
                            by_identity[identity].append(previous_row)
            except (ledgers.LedgerProblem, ContractProblem, OSError):
                failure = ('history_unavailable', 'Предыдущий снимок не прочитан; текущий процент остаётся доступен.')
        errors += int(failure is not None)
        for row in rows:
            identity = contract_identity(row)
            candidates = by_identity.get(identity, []) if identity else []
            if failure:
                state, reason = failure
            elif len(candidates) > 1:
                state, reason = 'ambiguous_contract', 'В предыдущем снимке несколько записей этой договорной идентичности.'
            elif not candidates:
                state, reason = 'previous_contract_missing', 'В предыдущем снимке этот договор не представлен; отсутствие не считается нулём.'
            else:
                row['progress']['series'].append(_point(_observation(candidates[0], previous)))
                continue
            row['progress']['series'].append({'ratio': None, 'observation_date': date,
                'snapshot_id': identifiers[0] if len(identifiers) == 1 else None,
                'basis': None, 'basis_label': '', 'origin': None, 'date_basis': 'snapshot',
                'scope_fingerprint': None, 'basis_fingerprint': None, 'state': state, 'reason': reason})
    for row in rows:
        progress = row['progress']
        progress['series'].append(_point(progress))
        _compare(progress)
        if errors and not selected:
            progress.update(comparison_state='history_unavailable', comparison_reason=
                            'История снимков не прочитана; текущий процент остаётся доступен.')
        progress['history_truncated'] = truncated
    result['progress_summary'] = {'known': sum(row['progress']['ratio'] is not None for row in rows),
        'unknown': sum(row['progress']['ratio'] is None for row in rows),
        'comparable': sum(row['progress']['comparison_state'] == 'comparable' for row in rows),
        'history_snapshots': len(selected), 'history_errors': errors,
        'history_truncated': truncated, 'date_basis': 'snapshot', 'window_days': WINDOW_DAYS}
    return result
