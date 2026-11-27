"""Source-qualified display of completion and finish in the contract register.

This projection adds no accepted financial evidence and changes no legal date.
Provisional ratios are presentation-only and never feed readiness or cashflows.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re

SCHEMA = 'contract-register-display-v1'
_BASES = {'with_vat', 'without_vat', 'unspecified'}
_UNSAFE = {'annual_evidence_conflict', 'source_qualification_conflict',
           'position_source_unverified', 'source_positions_missing',
           'source_identity_unknown', 'future_or_unverified_periods',
           'partial_source', 'tax_basis_mismatch', 'tax_basis_changed'}


def _number(value):
    try:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
    except OverflowError:
        return None


def _compatible(first, second):
    return isinstance(first, str) and isinstance(second, str) and first in _BASES and second in _BASES and (first == second or 'unspecified' in (first, second))


def _basis(value):
    if value is None or value == '':
        return 'unspecified'
    return value if isinstance(value, str) and value in _BASES else 'conflicting'


def _prior_choice_proven(row):
    choice = row.get('source_correction') or {}
    execution = (choice.get('provenance') or {}).get('execution') or {}
    return all(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value)
               for value in (choice.get('decision_id'), execution.get('raw_id'), execution.get('token')))


def _day(value):
    try:
        return dt.date.fromisoformat(value).isoformat() if isinstance(value, str) else None
    except ValueError:
        return None


def _ratio(value, completed, planned, *, nonnegative=True):
    return (_number(value) is not None and _number(completed) is not None
            and _number(planned) is not None and planned > 0 and (not nonnegative or completed >= 0)
            and math.isclose(value, completed/planned, rel_tol=1e-9, abs_tol=1e-9))


def qualified_statements(row, cut):
    """Preserve separate qualified file/sheet/year observations, never sum them."""
    if (row.get('logical_ownership') and not row.get('source_correction')
            or (row.get('source_correction') or {}).get('warning') and not _prior_choice_proven(row)):
        return []
    groups = {}
    for value in row.get('reported_performance_sources') or []:
        source = value.get('source') or {}
        sha, sheet, year = source.get('file_sha256') or source.get('sha256'), source.get('sheet'), value.get('period_year')
        if (value.get('amount_scope') != 'statement' or value.get('future_periods_excluded') is not False
                or value.get('monetary_comparable') is not True
                or not _compatible(_basis(value.get('planned_amount_basis')),
                                   _basis(value.get('completed_amount_basis')))
                or not (value.get('financial_complete') is True
                        or value.get('financial_complete') is None and value.get('source_complete') is True)
                or not _ratio(value.get('completion_ratio'), value.get('completed'), value.get('planned'))
                or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha)
                or not isinstance(sheet, str) or not sheet or type(year) is not int or not 2000 <= year <= 2099):
            continue
        observed = _day(value.get('source_date')) or _day(source.get('source_date'))
        if cut and ((observed and observed > cut) or year > int(cut[:4])):
            continue
        key = (sha, sheet, year)
        fingerprint = (value['planned'], value['completed'], value['completion_ratio'],
                       value.get('planned_amount_basis'), value.get('completed_amount_basis'))
        found = groups.setdefault(key, {'value': value, 'dates': [], 'fingerprint': fingerprint, 'conflict': False})
        found['conflict'] |= found['fingerprint'] != fingerprint
        if observed and observed not in found['dates']:
            found['dates'].append(observed)
    return [{'key': json.dumps(key, separators=(',', ':')), 'value': g['value'],
             'dates': sorted(g['dates']), 'conflict': g['conflict']}
            for key, g in groups.items()]


def completion(row, cut):
    """Use accepted ratios first; label an unspecified-tax quotient explicitly."""
    empty = {'state': 'unknown', 'ratio': None, 'scope': None,
             'why': 'Нет сопоставимых суммы выполнения и базы процента.', 'caveat': ''}
    if row.get('logical_ownership') and not row.get('source_correction'):
        return {**empty, 'why': 'Принадлежность источников договору требует уточнения.'}
    stale = bool((row.get('source_correction') or {}).get('warning'))
    if stale and not _prior_choice_proven(row):
        return {**empty, 'why': 'Выбранные источники изменились. Подтвердите актуальный выбор источников.'}
    first, second = _basis(row.get('amount_basis')), _basis(row.get('completed_basis'))
    direct = row.get('completion_ratio')
    if not stale and row.get('monetary_comparable') is True and _compatible(first, second) and _ratio(direct, row.get('completed'), row.get('amount'), nonnegative=False):
        negative = direct < 0
        provisional = not negative and 'unspecified' in (first, second)
        return {'state': 'provisional' if provisional else 'known', 'ratio': direct, 'scope': 'contract',
                'planned': row['amount'], 'completed': row['completed'],
                'basis_label': 'денежное закрытие от полной цены договора',
                'reference_label': ('Корректировка по КС: отрицательное закрытие; требуется сверка.'
                    + (' НДС не сверён.' if 'unspecified' in (first, second) else '')) if negative else '',
                'caveat': 'Отрицательный подтверждённый итог сохранён как корректировка; это не отрицательная физическая готовность.' if negative else
                    'Предварительно: НДС не сверён. Показатель не используется в финансовых расчётах.' if provisional else '', 'why': ''}
    for key, scope, label in (('progress', 'contract', 'по сводной КС-2'),
                              ('summary_progress', 'contract', 'по сводной КС-2'),
                              ('statement_progress', 'statement', 'по сопоставленным ведомостям')):
        value = row.get(key) or {}
        if (not stale and value.get('state') == 'known'
                and _compatible(_basis(value.get('planned_amount_basis')),
                                _basis(value.get('completed_amount_basis')))
                and _ratio(value.get('ratio'), value.get('completed'), value.get('planned'))):
            value_scope = 'statement' if value.get('basis') in {'statement', 'statement_union'} else scope
            if value_scope == 'contract':
                if not _compatible(first, second):
                    continue
                same = all(_number(row.get(field)) is not None and math.isclose(
                    row[field], value[source_field], rel_tol=1e-9, abs_tol=1e-9)
                    for field, source_field in (('amount', 'planned'), ('completed', 'completed')))
                if not same:
                    return {'state': 'reference', 'ratio': value['ratio'], 'scope': 'source',
                            'planned': value['planned'], 'completed': value['completed'],
                            'basis_label': 'денежное закрытие по суммам источника',
                            'reference_label': 'Справочно по источнику; общая база текущего договора не подтверждена.',
                            'caveat': 'Числитель или знаменатель показателя источника отличается от текущих значений карточки.',
                            'why': value.get('basis_label') or label}
                provisional = 'unspecified' in (first, second)
                return {'state': 'provisional' if provisional else 'known', 'ratio': value['ratio'],
                        'scope': 'contract', 'planned': value['planned'], 'completed': value['completed'],
                        'basis_label': 'денежное закрытие от полной цены договора',
                        'caveat': 'Предварительно: НДС не сверён. Показатель не используется в финансовых расчётах.' if provisional else '',
                        'why': ''}
            return {'state': 'known', 'ratio': value['ratio'], 'scope': value_scope,
                    'planned': value['planned'], 'completed': value['completed'],
                    'basis_label': value.get('basis_label') or label,
                    'caveat': 'Доля полной цены договора не подтверждена.' if value_scope == 'statement' else '', 'why': ''}
    amount, actual = _number(row.get('amount')), _number(row.get('completed'))
    problems = {v.get('code') for v in (row.get('statement_progress') or {}).get('problems') or []}
    history = row.get('detail_history') or {}
    price = row.get('amount_documents') or {}
    if (not stale and amount is not None and amount > 0 and actual is not None and actual >= 0
            and _compatible(first, second) and 'unspecified' in (first, second)
            and (not price or price.get('state') == 'known')
            and history.get('state') != 'unknown' and not (problems & _UNSAFE)
            and _number(actual/amount) is not None):
        return {'state': 'provisional', 'ratio': actual/amount, 'scope': 'contract',
                'planned': amount, 'completed': actual,
                'basis_label': 'денежное закрытие от полной цены договора',
                'caveat': 'Предварительно: НДС не сверён. Показатель не используется в финансовых расчётах.',
                'why': 'Числитель — известный итог датированных неповторяющихся периодов КС; знаменатель — известная полная цена. '
                       'У одного из них основание НДС не указано.'}
    groups = qualified_statements(row, cut)
    values = [g['value'] for g in groups if not g['conflict']]
    if values:
        ratios = [v['completion_ratio'] for v in values]
        single = len(values) == 1
        previous = ((row.get('source_correction') or {}).get('role_freshness') or {}).get('execution') is not True
        reference_label = ('Справочно по прежним ведомостям; выбор источников изменился.' if previous else
                           'Справочно по выбранным ведомостям; выбор источников изменился.') if stale else ''
        return {'state': ('reference' if single else 'reference_range') if stale else ('known' if single else 'source_range'),
                'ratio': ratios[0] if single else None,
                'minimum': min(ratios), 'maximum': max(ratios), 'scope': 'statement',
                'planned': values[0]['planned'] if single else None,
                'completed': values[0]['completed'] if single else None,
                'source_count': len(values), 'source_years': sorted({v['period_year'] for v in values}),
                'basis_label': 'денежное закрытие по ведомости' if single else 'диапазон денежного закрытия по ведомостям',
                'reference_label': reference_label,
                'caveat': 'Доля полной цены договора не подтверждена. Проценты разных ведомостей не складываются.'
                          + (' Есть конфликтующие наблюдения источников.' if len(values) != len(groups) else ''), 'why': ''}
    reason = next((str((row.get(k) or {}).get('why') or (row.get(k) or {}).get('reason'))
                   for k in ('progress', 'statement_progress', 'summary_progress')
                   if (row.get(k) or {}).get('why') or (row.get(k) or {}).get('reason')), None)
    return {**empty, 'why': reason or empty['why']}


def schedule_reference(state):
    """Summarize the same active graph or preview already shown by the card."""
    if not isinstance(state, dict):
        return None
    preview = state.get('preview') if not state.get('source') else None
    schedule = (preview or {}).get('schedule') if preview else state.get('schedule')
    if not isinstance(schedule, dict):
        return None
    source = (preview or {}).get('source') if preview else state.get('source')
    dated = [line for line in schedule.get('lines') or [] if _day(line.get('start'))
             and _day(line.get('finish')) and line['start'] <= line['finish']]
    sha = (source or {}).get('sha256')
    provenance = isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha) is not None
    relative_missing = schedule.get('calendar_basis') == 'relative' and not _day((schedule.get('anchor') or {}).get('handover_date'))
    result = {'kind': 'preview' if preview else 'gpr', 'source_sha256': sha,
              'pending_count': len(state.get('pending') or []),
              'date': max(line['finish'] for line in dated) if dated and provenance and not relative_missing else None,
              'start': min(line['start'] for line in dated) if dated and provenance and not relative_missing else None,
              'dated': len(dated), 'undated': len(schedule.get('lines') or [])-len(dated),
              'relative': schedule.get('calendar_basis') == 'relative',
              'anchor_missing': relative_missing,
              'conditions': state.get('conditions') or [], 'assumption': schedule.get('assumption') or ''}
    return result


def finish(row):
    empty = {'state': 'unknown', 'date': None, 'label': 'Не определён', 'source_label': '',
             'caveat': 'Нет подтверждённой даты или условия завершения.'}
    if row.get('logical_ownership') and not row.get('source_correction'):
        return {**empty, 'caveat': 'Принадлежность источника срока требует уточнения.'}
    if (row.get('source_correction') or {}).get('warning'):
        return {**empty, 'caveat': 'Выбранные источники изменились. Подтвердите актуальный выбор источников.'}
    control = row.get('schedule_control') or {}
    legal = _day(row.get('deadline')) or (_day(control.get('deadline')) if control.get('from_register') is True else None)
    if legal:
        return {'state': 'known', 'date': legal, 'source_label': 'По договору', 'caveat': '', 'kind': 'contract'}
    source = control.get('schedule_source') or {}
    reference = control.get('gpr_reference') or {}
    sha = source.get('sha256') or ((control.get('gpr_binding') or {}).get('source') or {}).get('sha256')
    proven = isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha) is not None
    active = (_day(control.get('deadline')) or _day(source.get('finish'))) if proven and not reference.get('anchor_missing') else None
    if active:
        return {'state': 'known', 'date': active, 'source_label': 'По ГПР', 'kind': 'gpr',
                'caveat': 'Дата из графика; юридический срок договора отдельно не подтверждён.'}
    ref_sha = reference.get('source_sha256')
    if (_day(reference.get('date')) and not reference.get('anchor_missing')
            and isinstance(ref_sha, str) and re.fullmatch(r'[a-f0-9]{64}', ref_sha)):
        preview = reference.get('kind') == 'preview'
        return {'state': 'provisional' if preview else 'known', 'date': reference['date'],
                'source_label': 'Предпросмотр ГПР' if preview else 'По ГПР', 'kind': 'preview' if preview else 'gpr',
                'caveat': ('Редакция ГПР не принята для расчёта. ' if preview else '')
                    + ('Показан конец датированных строк; часть строк без дат. ' if reference.get('undated') else '')
                    + 'Это дата графика, не подмена договорного срока.'}
    conditions = reference.get('conditions') or []
    if not conditions:
        history = (row.get('deadline_documents') or {}).get('history') or []
        latest = max((str((h.get('source') or {}).get('edition_date') or '') for h in history), default='')
        conditions = [h.get('source') or {} for h in history
                      if str((h.get('source') or {}).get('edition_date') or '') == latest]
    durations = {(c.get('duration_days'), c.get('days_kind') or 'unspecified') for c in conditions
                 if type(c.get('duration_days')) is int and c['duration_days'] > 0}
    if len(durations) == 1:
        days, kind = next(iter(durations))
        unit = 'рабочих дней' if kind == 'working' else 'календарных дней' if kind == 'calendar' else 'дней'
        return {'state': 'conditional', 'date': None, 'kind': 'condition',
                'label': str(days)+' '+unit+' от начала работ', 'source_label': 'Условие договора',
                'caveat': 'Для календарной даты нужно подтвердить основания начала работ.'}
    if reference.get('anchor_missing'):
        return {'state': 'conditional', 'date': None, 'kind': 'relative_gpr',
                'label': 'От даты передачи площадки', 'source_label': 'Относительный ГПР',
                'caveat': 'Дата передачи площадки не указана; календарное окончание не рассчитано.'}
    return empty


def attach(register, cut):
    """Add presentation DTOs only; keep every original financial/legal field."""
    for row in register.get('rows') or []:
        row['register_display'] = {'schema': SCHEMA, 'completion': completion(row, cut), 'finish': finish(row),
                                   'statements': qualified_statements(row, cut)}
    register['display_schema'] = SCHEMA
    return register
