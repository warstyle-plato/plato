"""Position-ordered RDS presentation of the canonical card, without reading or repricing sources."""
from __future__ import annotations

import datetime as dt
import math
import re
from collections import Counter

import developaid_contract_plan as plan
from developaid_contract_fact import _money
from developaid_monitor_statement_union import _unit

LAYOUT = 'rds-plan-fact-v3'
KS_REPORTING_SCHEMA = 'rds-loaded-ks-reporting-v1'
KS_REPORTING_NOTICE = ('Факт по загруженным и прочитанным КС. Если позиция в этих актах не предъявлена, '
    'учтено 0. В КС-6а известный нулевой итог работ показан как учтённый объём 0, отдельно от стоимости материалов. '
    'Нулевая стоимость требует отдельного подтверждённого денежного итога. Отклонение равно учтённому факту минус план. '
    'Это не утверждение о фактическом отсутствии работ на площадке. '
    'Непрочитанный или неоднозначный источник остаётся неизвестным.')
KS_REPORTING_FIELDS = ('fact_quantity', 'fact_quantity_ratio', 'quantity_deviation', 'fact', 'deviation')
SCHEDULE_REPORTING_SCHEMA = 'rds-schedule-reporting-v1'
SCHEDULE_REPORTING_NOTICE = ('Отставание по объёму — разница с днём, когда план достиг учтённого физического объёма. '
    'Дни после срока ГПР считаются отдельно. Если завершение по КС не подтверждено, это календарный срок без '
    'подтверждения закрытия, а не доказанная физическая просрочка. Минимум не является прогнозом даты окончания.')
FIELDS = ('number', 'name', 'unit', 'start', 'finish', 'plan_quantity', 'plan_quantity_ratio',
          'fact_quantity', 'fact_quantity_ratio', 'quantity_deviation', 'planned', 'fact', 'deviation',
          'day_deviation', 'forecast_finish', 'forecast_delay_days')


def _numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def _loaded_ks2_scope(fact, estimates):
    """Determine reportable absence from native parsed acts, never from an empty fact cell."""
    evidence = fact.get('act_evidence') or {}
    scope = fact.get('ks_reporting_context') or {}
    if (fact.get('source') != 'ks2' or fact.get('note') or fact.get('unread')
            or scope.get('schema') != 'loaded-ks2-reporting-scope-v1'
            or scope.get('reporting_scope_available') is not True
            or not _numeric(evidence.get('count')) or evidence['count'] <= 0
            or evidence.get('unread_count') != 0):
        return None
    acts = evidence.get('acts') or []
    if (len(acts) != evidence['count'] or any(not _numeric(item.get('positions'))
            or item['positions'] <= 0 for item in acts)):
        return None
    from developaid_contract_fact import match, _code, _norm
    reviewed = set()
    for item in [*(fact.get('review') or []), *(scope.get('unread_rows') or [])]:
        if not isinstance(item, dict) or not all(key in item for key in ('number', 'name', 'unit')):
            return None
        identity = match(item, estimates)
        if isinstance(identity, str):
            # This is a conservative exclusion, not a second matcher. Keep every
            # position an unresolved row could refer to unknown; an unrelated
            # extra act row does not hide the reportable absence of all RDS work.
            number, name = _code(item.get('number')), _norm(item.get('name'))
            if not number and not name:
                return None
            reviewed.update((e, i) for e, estimate in enumerate(estimates)
                if estimate.get('scope') != 'accepted'
                for i, position in enumerate(estimate.get('positions') or [])
                if (number and _code(position.get('number')) and
                    (number == _code(position.get('number')) or
                     number.startswith(_code(position.get('number'))+'.') or
                     _code(position.get('number')).startswith(number+'.')))
                or (name and _norm(position.get('name')) == name))
            continue
        reviewed.add(tuple(identity[:2]))
    return reviewed


def _ks_reporting(row, fact, identity, observed, unread, reviewed, leaf):
    if (reviewed is None or observed is not None or unread or identity in reviewed
            or not leaf
            or row['physical_audit']['state'] != 'source_missing'
            or not _numeric(row.get('contract_quantity')) or row['contract_quantity'] <= 0
            or not row.get('unit')):
        return None
    reason = ('По загруженным и прочитанным КС-2 на '+str(fact.get('cut') or '')+
              ' эта позиция не предъявлена: учтённый объём и стоимость равны 0. '
              'Полнота комплекта актов и физическое выполнение на площадке этим не подтверждаются.')
    values = {'schema': KS_REPORTING_SCHEMA, 'basis': 'loaded_ks2', 'state': 'unreported_zero',
              'fact_quantity': 0.0, 'fact_quantity_ratio': 0.0, 'fact': 0.0,
              'quantity_deviation': -row['plan_quantity'] if _numeric(row.get('plan_quantity')) else None,
              'deviation': -row['planned'] if _numeric(row.get('planned')) else None,
              'physical_quantity_confirmed': False,
              'comments': {field: reason for field in KS_REPORTING_FIELDS}}
    for field, plan_field in (('quantity_deviation', 'plan_quantity'), ('deviation', 'planned')):
        if row.get(plan_field) is None:
            values['comments'][field] = 'План не подтверждён; отклонение от него не рассчитано. '+reason
    return values


def _ks6_reporting_sources(fact, estimates):
    """Index exact native statement identities, retaining conflicts as conflicts."""
    if fact.get('source') != 'ks6a' or fact.get('note'):
        return {}
    from developaid_contract_fact import match
    sources = {}
    for item in fact.get('physical_source_rows') or []:
        identity = match({'number': item.get('position'), 'name': item.get('name'), 'unit': item.get('unit')}, estimates)
        if not isinstance(identity, str):
            sources.setdefault(tuple(identity[:2]), []).append(item)
    return sources


def _ks6_reporting(row, fact, identity, sources, *, group, unread, observed):
    """A source/accounting zero is reportable without becoming physical evidence.

    A zero work quantity establishes neither a zero material amount nor a
    complete historical monetary value. A cash zero needs its own native
    amount witness and never replaces an observed historical valuation.
    """
    audit = row.get('physical_audit') or {}
    witnesses = sources.get(identity) or []
    if (group or unread or row.get('fact_quantity') is not None or len(witnesses) != 1
            or audit.get('state') not in ('known_source_value_unaccepted', 'accounted_zero_physical_unknown')
            or not _numeric(row.get('contract_quantity')) or row['contract_quantity'] <= 0 or not row.get('unit')
            or audit.get('rds_position') != list(identity) or audit.get('estimate_sha256') != row.get('source_sha256')
            or audit.get('cut') != fact.get('cut') or len(audit.get('sources') or []) != 1):
        return None
    item, accepted = witnesses[0], audit['sources'][0]
    source = item.get('source') or {}
    components = fact.get('statement_components') or {}
    references = [reference for reference in components.get('sources') or []
        if all((reference.get('source') or {}).get(key) == source.get(key) for key in
               ('filename', 'sheet', 'snapshot_id', 'file_sha256', 'source_date'))]
    if (components.get('available') is not True or components.get('source') != 'ks6a'
            or components.get('cut') != fact.get('cut') or len(references) != 1
            or source.get('file_sha256') not in (components.get('source_hashes') or [])):
        return None
    reference = references[0]
    snapshot, source_day, cut = _day(item.get('snapshot_date')), _day(source.get('source_date')), _day(fact.get('cut'))
    year = reference.get('period_year')
    reported = item.get('reported_completed_quantity')
    quantity = reported if reported is not None else item.get('completed_quantity')
    if (item.get('is_group') is True or item.get('is_duplicate') is True
            or not snapshot or snapshot != source_day or not cut or snapshot > cut
            or ('quantity_cut' in item and item['quantity_cut'] != fact.get('cut'))
            or ('future_periods_excluded' in item and item['future_periods_excluded'] is not False)
            or type(year) is not int or not 2000 <= year <= cut.year
            or ('period_year' in item and item['period_year'] != year)
            or reference.get('source_date') != item.get('snapshot_date')
            or not _numeric(quantity) or quantity != 0
            or _unit(item.get('unit')) != _unit(row['unit'])
            or accepted.get('match_status') != 'linked' or accepted.get('conversion') != '1:1'
            or accepted.get('reported_work_quantity') != 0 or accepted.get('snapshot_date') != item.get('snapshot_date')
            or source != accepted.get('source')
            or not all(isinstance(source.get(key), str) and source[key] for key in
                ('filename', 'sheet', 'snapshot_id', 'file_sha256', 'completed_quantity_cell'))
            or not re.fullmatch('[0-9a-f]{64}', source['file_sha256'])
            or type(source.get('row')) is not int or source['row'] <= 0
            or not re.fullmatch(r'[A-Z]+'+str(source['row']), source['completed_quantity_cell'])):
        return None
    periods = [*(item.get('periods') or []), *(item.get('undated_periods') or [])]
    for period in periods:
        begin, end = _day(period.get('date_start')), _day(period.get('date_end'))
        if ((period.get('date_start') and not begin) or (period.get('date_end') and not end)
                or (begin and end and begin > end) or (end and end > cut)
                or (period.get('quantity') is not None and
                    (not _numeric(period['quantity']) or period['quantity'] != 0))):
            return None
    accounted = audit['state'] == 'accounted_zero_physical_unknown'
    if accounted and (not _numeric(row.get('accounted_work_quantity')) or row['accounted_work_quantity'] != 0
            or not _numeric(audit.get('accounted_work_quantity')) or audit['accounted_work_quantity'] != 0
            or not any('нулевой суммой' in str(value).lower() for value in accepted.get('quantity_bases') or [])):
        return None
    basis = 'ks6_accounted_work_zero' if accounted else 'ks6_cumulative_source_zero'
    reason = ('По прочитанной КС-6а от '+snapshot.isoformat()+' учтённый объём работ равен 0. '+
        ('Ноль учёта выведен из нулевой стоимости работ при положительной цене; физический объём в исходной ячейке не подтверждён. '
         if accounted else 'Накопительный итог работ известен и равен 0; пустые периоды не устанавливают даты производства. ')+
        'Это не подтверждённый физический ноль на площадке. Количество и стоимость материалов учитываются отдельно; '
        'денежный факт по РДС не изменён.')
    values = {'schema': KS_REPORTING_SCHEMA, 'basis': basis, 'state': 'reported_work_zero',
        'fact_quantity': 0.0, 'fact_quantity_ratio': 0.0,
        'quantity_deviation': -row['plan_quantity'] if _numeric(row.get('plan_quantity')) else None,
        'physical_quantity_confirmed': False, 'sources': [source.copy()], 'basis_note': reason,
        'comments': {field: reason for field in ('fact_quantity', 'fact_quantity_ratio', 'quantity_deviation')}}
    if values['quantity_deviation'] is None:
        values['comments']['quantity_deviation'] = 'План не подтверждён; отклонение от него не рассчитано. '+reason
    amount = item.get('reported_completed_amount')
    amount = amount if amount is not None else item.get('completed_amount')
    amount_cell = source.get('completed_amount_cell')
    cash_conflict = any(value.get(field) is not None and
        (not _numeric(value[field]) or value[field] != 0)
        for value in periods for field in ('amount', 'work_amount', 'material_amount'))
    if (observed is None and (row.get('fact') is None or _numeric(row.get('fact')) and row['fact'] == 0)
            and reference.get('financial_complete') is True
            and _numeric(amount) and amount == 0 and 'completed_amount_derivation' in item
            and item['completed_amount_derivation'] in (None, {}) and not cash_conflict
            and isinstance(amount_cell, str) and re.fullmatch(
                r'[A-Z]+'+str(source['row'])+r'(?:\s*\+\s*[A-Z]+'+str(source['row'])+r')*', amount_cell)):
        cash_reason = ('Полная стоимость работ и материалов по этой строке прочитанной КС-6а от '+snapshot.isoformat()+
            ' известна и равна 0; источник: '+source['filename']+', '+source['sheet']+', '+amount_cell+
            '. Ноль подтверждён отдельным денежным итогом, а не выведен из объёма работ. '
            'Это учтённое закрытие по источнику, не оплата и не переоценка исторического факта по РДС.')
        values.update(fact=0.0, deviation=-row['planned'] if _numeric(row.get('planned')) else None,
            cash_zero={'schema': 'ks6-source-cash-zero-v1', 'amount': 0.0, 'source': source.copy(),
                       'basis': 'complete_native_statement_amount', 'note': cash_reason})
        values['comments'].update(fact=cash_reason, deviation=cash_reason)
        values['basis_note'] += ' '+cash_reason
        if values['deviation'] is None:
            values['comments']['deviation'] = 'План не подтверждён; отклонение от него не рассчитано. '+cash_reason
    return values


def reporting_row(row):
    """The page and workbook consume the same server projection; raw physical data stays intact."""
    view = row.get('ks_reporting')
    if not isinstance(view, dict) or view.get('schema') != KS_REPORTING_SCHEMA:
        return row
    return {**row, **{key: view[key] for key in KS_REPORTING_FIELDS if key in view},
            'comments': {**(row.get('comments') or {}), **(view.get('comments') or {})}}


def _day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _schedule_reporting(row, cut, *, full_schedule_link):
    """Qualify calendar exposure separately from physical lag and a dated forecast.

    Absence from read acts may support a credited zero, but never a physical
    completion claim. Its lower bound concerns the elapsed period without KS
    confirmation only; it must not be used as a physical forecast delay.
    """
    day = _day(cut)
    finish = _day(row.get('finish')) if full_schedule_link else None
    elapsed = max(0, (day-finish).days) if day and finish else None
    physical_ratio = row.get('fact_quantity_ratio')
    complete = _numeric(physical_ratio) and physical_ratio >= 1-1e-6
    incomplete = _numeric(physical_ratio) and physical_ratio < 1-1e-6
    completion = 'ks_quantity_complete' if complete else 'ks_quantity_incomplete' if incomplete else 'unconfirmed'
    report = row.get('ks_reporting') or {}
    credited_zero = (report.get('schema') == KS_REPORTING_SCHEMA and report.get('physical_quantity_confirmed') is False
        and report.get('fact_quantity') == 0 and report.get('state') in ('unreported_zero', 'reported_work_zero'))
    audit_reason = (row.get('physical_audit') or {}).get('reason') or 'Физический объём не подтверждён.'
    lag = row.get('day_deviation') if _numeric(row.get('day_deviation')) else None

    def measure(kind, value, text, basis):
        return {'kind': kind, 'value': value, 'text': text, 'basis': basis}

    lag_basis = ('Отставание минус опережение: дни между срезом и днём достижения текущего физического '
        'объёма по плану ГПР. Плюс — отставание, минус — опережение. Это не дни после срока ГПР. '
        'Последний учтённый объём КС сохраняется до среза; это не подтверждение ежедневного производства.')
    calendar_basis = ('От окончания этой позиции по ГПР до среза: '+str(row.get('finish') or '')+' → '+str(cut)+
        '. Юридический срок договора не подставляется. ')
    if lag is not None:
        current = measure('physical_plan_day_deviation', lag,
            ('Отставание по объёму: ' if lag > 0 else 'Опережение по объёму: ' if lag < 0 else 'По объёму: ')+
            format(abs(lag), 'g')+' дн.', lag_basis)
    elif elapsed and not complete:
        current = measure('gpr_deadline_elapsed_incomplete' if incomplete else 'gpr_deadline_elapsed_unconfirmed',
            elapsed, 'Срок прошёл '+str(elapsed)+' дн.; '+
            ('объём по КС не завершён' if incomplete else 'завершение по КС не подтверждено'),
            calendar_basis+('Принятый физический объём меньше полного объёма РДС.' if incomplete else
                'Физическое завершение неизвестно. '+('Учтённый ноль по загруженным КС не означает отсутствие работ.'
                    if credited_zero else audit_reason)))
    else:
        current = measure('unknown', None, 'Отставание по объёму не определено',
            (row.get('comments') or {}).get('day_deviation') or audit_reason)
        if finish and day and not complete:
            current['text'] = ('Срок ГПР сегодня' if day == finish else 'Срок ГПР ещё не наступил')+\
                '; завершение по КС не подтверждено'
            current['basis'] += ' '+calendar_basis

    value = row.get('forecast_finish')
    kind = 'actual' if row.get('forecast_kind') == 'actual' else 'forecast'
    if _day(value):
        date_text = _day(value).strftime('%d.%m.%Y')
        ending = measure(kind, value, ('Факт: ' if kind == 'actual' else 'Прогноз: ')+date_text,
            (row.get('comments') or {}).get('forecast_finish') or '')
    else:
        zero = credited_zero or row.get('fact_quantity') == 0
        reason = ('Нет подтверждённого положительного темпа; при нулевом учтённом объёме дата '
            'завершения из плана не выводится.' if zero else
            (row.get('comments') or {}).get('forecast_finish') or audit_reason)
        if not incomplete and not complete:
            reason += ' '+audit_reason
        ending = measure('unknown', None,
            'Прогноз даты не определён: нет подтверждённого темпа' if zero else
            'Дата завершения не определена', reason)

    point_delay = row.get('forecast_delay_days')
    if ending['value'] and _numeric(point_delay):
        delay = measure('actual' if kind == 'actual' else 'forecast', point_delay,
            ('Задержка факта: ' if kind == 'actual' else 'Задержка прогноза: ')+format(point_delay, 'g')+' дн.',
            (row.get('comments') or {}).get('forecast_delay_days') or '')
    elif elapsed and not complete:
        delay = measure('ks_quantity_lower_bound' if incomplete else 'ks_closure_lower_bound', elapsed,
            'Не менее '+str(elapsed)+' дн.'+(' по незакрытому объёму КС' if incomplete else
                ' без подтверждения завершения по КС'), calendar_basis+
            ('Учтённый по КС объём меньше полного объёма РДС; подтверждения полного завершения по КС нет. '
                'Это нижняя граница периода после срока без полного закрытия по КС, а не доказанная физическая просрочка. '
                'Последний учтённый объём сохраняется до среза без подтверждения новых работ; дата окончания не определена.'
             if incomplete else 'Нижняя граница периода после срока без подтверждения завершения по КС. '
                'Она не доказывает физическую просрочку и не задаёт дату будущего окончания.'))
    else:
        delay = measure('unknown', None, 'Задержка к сроку ГПР не определена',
            'Нет подтверждённой даты завершения или прогноза; будущий плановый срок не является просрочкой.')
    return {'schema': SCHEDULE_REPORTING_SCHEMA, 'cut': cut,
            'gpr_finish': finish.isoformat() if finish else None,
            'gpr_deadline_elapsed_days': elapsed, 'earned_plan_day_deviation': lag,
            'completion_state': completion, 'credited_zero': credited_zero,
            'current': current, 'finish': ending, 'delay': delay}


def build(listed: dict) -> dict:
    current = next((item for item in listed.get('plan', {}).get('editions', []) if item.get('in_force')), None)
    unavailable = {'layout': LAYOUT, 'available': False, 'rows': [],
                   'detail': 'Для выгрузки нужна действующая РДС с подтверждённым источником.'}
    if not current or not current.get('estimate_sha256'):
        return unavailable
    documents = {item['sha256']: item for item in listed.get('documents', [])}
    document = documents.get(current['estimate_sha256'])
    if not document or not document.get('estimates'):
        return unavailable
    cut = listed['plan']['cut']
    day = dt.date.fromisoformat(cut)
    start = dt.date.fromisoformat(current['start']) if current.get('start') else None
    fact = listed.get('fact') or {}
    if 'rds_positions' not in fact or 'position_links' not in current:
        return {**unavailable, 'detail': 'Откройте карточку заново, чтобы подготовить таблицу по позициям РДС.'}
    observations = {(item['estimate'], item['index']): item for item in fact['rds_positions']
                    if item.get('estimate_sha256') == document['sha256']}
    unread = {(item['estimate'], item['index']): item for item in fact.get('rds_unread') or []
              if item.get('estimate_sha256') == document['sha256']}
    bindings = {(item['estimate'], item['index']): item for item in current['position_links']}
    reviewed = _loaded_ks2_scope(fact, document['estimates'])
    ks6_sources = _ks6_reporting_sources(fact, document['estimates'])
    from developaid_contract_fact import _code
    nonleaf = {(e, i) for e, estimate in enumerate(document['estimates'])
               for i, position in enumerate(estimate.get('positions') or [])
               if position.get('is_group') is True or position.get('group_row') is True
               or position.get('kind') in {'group', 'heading', 'section'}
               or (_code(position.get('number')) and any(
                   _code(other.get('number')).startswith(_code(position['number'])+'.')
                   for other in estimate.get('positions') or []))}
    schedule = (documents.get(current.get('schedule_sha256')) or {}).get('schedule') or {}
    source_codes = Counter(line['code'] for line in schedule.get('lines') or [])
    scheduled = {line['code']: line for line in schedule.get('lines') or []}
    usage = Counter(line['code'] for item in current['position_links'] if item['status'] in ('confirmed', 'proposed')
                    for line in item.get('lines') or [] if line.get('share'))
    control_codes = Counter(line['code'] for line in listed.get('control', {}).get('lines') or [])
    controls = {line['code']: line for line in listed.get('control', {}).get('lines') or []}
    rows, headings = [], []
    for estimate_index, estimate in enumerate(document['estimates']):
        if estimate.get('scope') == 'accepted':
            continue
        offset = len(rows)
        headings.extend({**heading, 'before_position': offset+heading['before_position']}
                        for heading in estimate.get('structure') or [])
        for index, position in enumerate(estimate.get('positions') or []):
            identity = (estimate_index, index)
            binding, observed = bindings.get(identity), observations.get(identity)
            comments = {}
            row = {field: None for field in FIELDS}
            row.update(number=position.get('number'), name=position.get('name'), unit=position.get('unit'),
                       estimate=estimate_index, index=index, source_sha256=document['sha256'], comments=comments,
                       contract_quantity=position.get('quantity'))
            targets = binding.get('lines') or [] if binding and binding.get('status') in ('confirmed', 'proposed') else []
            if targets and all(target['code'] in scheduled and scheduled[target['code']].get('start') and
                               scheduled[target['code']].get('finish') for target in targets):
                share = sum(target['share']*plan.done(scheduled[target['code']], day, start) for target in targets)
                row['plan_quantity'] = position['quantity']*share if position.get('quantity') is not None else None
                whole = (position.get('amount') or {}).get('total')
                row['planned'] = whole*share if whole is not None else None
                if len(targets) == 1:
                    source_line = scheduled[targets[0]['code']]
                    row.update(start=source_line['start'], finish=source_line['finish'])
                else:
                    comments['start'] = comments['finish'] = 'Позиция распределена между несколькими строками ГПР: единый срок не указан.'
            else:
                reason = (binding or {}).get('reason') or 'Нет принятой связи этой позиции с датированной строкой ГПР.'
                for field in ('start', 'finish', 'plan_quantity', 'planned'):
                    comments[field] = reason
            if row['plan_quantity'] is None:
                comments.setdefault('plan_quantity', 'Количество этой позиции в РДС не подтверждено; объём из стоимости не выводится.')
            if row['planned'] is None:
                comments.setdefault('planned', 'Стоимость этой позиции в РДС не подтверждена.')
            if observed:
                if observed.get('work_observed'):
                    row['fact_quantity'] = observed.get('work_quantity')
                else:
                    comments['fact_quantity'] = 'Подтверждена поставка материалов; выполненный объём работ не указан.'
                row['fact'] = observed.get('amount')
                pricing = 'Факт по ценам РДС периода выполнения: ' + '; '.join(observed.get('priced_editions') or []) + '.'
                comments['fact'] = pricing
                if row['fact'] is None:
                    comments['fact'] += ' Полная стоимость работ и поставки неизвестна. ' + ' '.join(observed.get('reasons') or [])
                    if observed.get('known_amount') is not None:
                        comments['fact'] += ' Известная часть по РДС: '+_money(observed['known_amount'])+'; это не полный факт.'
                if row['fact_quantity'] is None:
                    comments.setdefault('fact_quantity', 'Объём работ не подтверждён в выбранном источнике. ' +
                                        ' '.join(observed.get('reasons') or []))
            else:
                if fact.get('source') == 'ks2':
                    reason = 'Позиция не найдена в загруженных КС-2; отсутствие не подтверждает нулевое выполнение.'
                elif fact.get('source') == 'ks6a':
                    reason = 'Для этой позиции нет подтверждённого объёма в выбранной КС-6а.'
                else:
                    reason = fact.get('note') or 'Источник выполнения не подтверждён.'
                if unread.get(identity):
                    reason += ' '+unread[identity]['reason']
                    if unread[identity].get('work_zero_proved') is True:
                        row['fact_quantity'] = 0.0
                comments['fact_quantity'] = comments['fact'] = reason
                if row['fact_quantity'] == 0:
                    comments['fact_quantity'] = 'Нулевой объём выполненной работы подтверждён отдельной записью КС-6а; поставка не подтверждает монтаж.'
                    comments['fact'] = 'Полная стоимость работ и поставки не подтверждена. '+unread[identity]['reason']
            from developaid_contract_physical_audit import position_audit
            row['physical_audit'] = position_audit(position, identity,
                {**current, 'estimates':document['estimates']}, fact, observed, binding, cut)
            if row['physical_audit']['state'] == 'accounted_zero_physical_unknown':
                row['accounted_work_quantity'] = row['fact_quantity']
                row['fact_quantity'] = None
                comments['fact_quantity'] = row['physical_audit']['reason']
            for output, actual, planned in (('quantity_deviation', 'fact_quantity', 'plan_quantity'),
                                           ('deviation', 'fact', 'planned')):
                if row[planned] is not None and row[actual] is not None:
                    row[output] = row[actual]-row[planned]
                else:
                    comments[output] = 'Отклонение не рассчитано: план или факт не подтверждены.'
            quantity = row['contract_quantity']
            positive_base = type(quantity) in (int, float) and math.isfinite(quantity) and quantity > 0
            for output, field in (('plan_quantity_ratio', 'plan_quantity'), ('fact_quantity_ratio', 'fact_quantity')):
                value = row[field]
                if positive_base and type(value) in (int, float) and math.isfinite(value):
                    row[output] = value/quantity
                    comments[output] = ('100% — полное количество этой позиции по РДС: '+
                        format(quantity, '.15g').replace('.', ',')+' '+str(row['unit'] or '')+
                        '. Доля рассчитана по физическому объёму работ, без количества поставки и без стоимости.')
                else:
                    comments[output] = (comments.get(field) or 'Физический объём не подтверждён.') if positive_base else \
                        'Процент не рассчитан: полное количество позиции РДС не подтверждено или не положительно.'
            canonical, individual = None, False
            if len(targets) == 1:
                code = targets[0]['code']
                control = controls.get(code) or {}
                operations = [part for part in (control.get('operations') or {}).get('lines', [])
                              if part.get('position_key') == (binding or {}).get('key') and
                              (part.get('source') or {}).get('sha256') == document['sha256']]
                if len(operations) == 1:
                    canonical, individual = operations[0], True
                elif usage[code] == 1:
                    canonical = control
                    individual = not control.get('operations')
                individual = individual and source_codes[code] == control_codes[code] == 1
            # Both individual day measures need attributable physical evidence.
            volume = (canonical or {}).get('volume') or {}
            share = targets[0].get('share') if len(targets) == 1 else None
            physical_known = (individual and canonical and canonical.get('state') not in (None, 'unknown') and positive_base and
                type(row['fact_quantity']) in (int, float) and math.isfinite(row['fact_quantity']) and type(share) in (int, float) and share == 1 and
                type(volume.get('quantity')) in (int, float) and math.isfinite(volume['quantity']) and
                abs(volume['quantity']-quantity) <= 1e-6 and
                _unit(volume.get('unit')) == _unit(row['unit']) and
                type(volume.get('fact')) in (int, float) and math.isfinite(volume['fact']) and
                abs(volume['fact']-row['fact_quantity']) <= 1e-6)
            if physical_known and canonical.get('lag_days') is not None and canonical.get('ahead_days') is not None:
                row['day_deviation'] = canonical['lag_days']-canonical['ahead_days']
            else:
                comments['day_deviation'] = 'Нет отдельного физического показателя для этой позиции с единственной полной связью ГПР и подтверждённым объёмом выполнения.'
            finish = (canonical.get('finished') if canonical.get('state') == 'done' else
                      canonical.get('forecast_finish')) if physical_known else None
            if finish and row['finish']:
                row['forecast_finish'] = finish
                row['forecast_delay_days'] = (dt.date.fromisoformat(finish)-dt.date.fromisoformat(row['finish'])).days
                row['forecast_kind'] = 'actual' if canonical.get('state') == 'done' else 'forecast'
                reason = ('Фактическое завершение по концу последнего принятого периода КС.' if row['forecast_kind'] == 'actual' else
                          'Условный прогноз действующего расчёта ГПР: текущее отставание сохраняется до конца; '
                          'работа на плане или впереди заканчивается по графику. Это допущение, не обещанная дата.')
                if schedule.get('assumption'):
                    reason += ' '+schedule['assumption']
                comments['forecast_finish'] = reason
                comments['forecast_delay_days'] = reason+' Разница с окончанием этой строки ГПР: плюс — позже, минус — раньше. Юридический срок договора сюда не подставляется.'
            else:
                reason = 'Нет отдельного физического прогноза для этой позиции с единственной полной связью ГПР и подтверждённым объёмом выполнения.'
                comments['forecast_finish'] = comments['forecast_delay_days'] = reason
            if row.get('finish') and row['finish']<cut and (row['fact_quantity_ratio'] is None or row['fact_quantity_ratio']<1):
                row['forecast_finish']=row['forecast_delay_days']=None
                comments['forecast_finish']=comments['forecast_delay_days']='Для прогноза незакрытого остатка нужны сопоставимый физический объём и темп.'
            if (physical_known and row.get('unit') and type(row.get('day_deviation')) in (int,float) and math.isfinite(row['day_deviation'])
                    and row['fact_quantity'] is not None and row['fact_quantity']>0 and positive_base
                    and len(targets)==1 and targets[0].get('share')==1 and row.get('finish') and row['finish']<cut):
                import developaid_contract_gpr_reporting as reporting
                source_line=scheduled[targets[0]['code']]
                intervals=plan.links.dated_segments(source_line) or [(dt.date.fromisoformat(source_line['start']),dt.date.fromisoformat(source_line['finish']))]
                origin=min(a for a,b in intervals)
                physical_line={**source_line,'reporting_events':(observed or {}).get('reporting_events') or [],'reporting_plan_start':current.get('start')}
                source_dates=[(value.get('source') or {}).get('source_date') if fact.get('source')=='ks6a' else value.get('end') for value in (observed or {}).get('sources') or []]
                progress={'fact_quantity':row['fact_quantity'],'contract_quantity':quantity,'unit':row['unit'],
                    'fraction':row['fact_quantity_ratio'],'planned_fraction':row['plan_quantity_ratio'],
                    'delta_pp':(row['fact_quantity_ratio']-row['plan_quantity_ratio'])*100,
                    'source_dates':sorted({value for value in source_dates if value and value<=cut})}
                model=reporting.project(physical_line,progress,[((a-origin).days,(b-origin).days+1) for a,b in intervals],origin.isoformat(),cut)
                forecast=model.get('forecast')
                if forecast:
                    row['forecast_finish']=forecast['finish']
                    row['forecast_delay_days']=(dt.date.fromisoformat(forecast['finish'])-dt.date.fromisoformat(row['finish'])).days
                    row['forecast_kind']='physical_remaining_forecast'
                    comments['forecast_finish']=comments['forecast_delay_days']=reporting.forecast_text(forecast)
            if row['fact_quantity'] == 0:
                # A zero volume can establish physical lag when evidenced, but
                # it cannot establish a positive pace or a point finish date.
                row['forecast_finish'] = row['forecast_delay_days'] = None
                row.pop('forecast_kind', None)
                comments['forecast_finish'] = comments['forecast_delay_days'] = \
                    'Прогноз даты не определён: нет подтверждённого положительного темпа выполнения.'
            if row['fact_quantity'] is None:
                comments['fact_quantity'] = row['physical_audit']['reason']
            report = _ks_reporting(row, fact, identity, observed, unread.get(identity), reviewed, identity not in nonleaf)
            if report is None:
                report = _ks6_reporting(row, fact, identity, ks6_sources,
                    group=(position.get('is_group') is True or position.get('group_row') is True
                           or position.get('kind') in {'group', 'heading', 'section'}),
                    unread=unread.get(identity), observed=observed)
            if report is not None:
                row['ks_reporting'] = report
            row['schedule_reporting'] = _schedule_reporting(row, cut, full_schedule_link=(
                len(targets) == 1 and targets[0].get('share') == 1 and source_codes[targets[0]['code']] == 1))
            rows.append(row)
    return {'layout': LAYOUT, 'available': True, 'cut': cut, 'rows': rows, 'headings': headings,
            'estimate_title': document.get('title') or '', 'estimate_sha256': document['sha256'],
            'source': fact.get('source'), 'source_note': fact.get('source_note') or '',
            'ks_reporting': {'schema': KS_REPORTING_SCHEMA, 'notice': KS_REPORTING_NOTICE},
            'schedule_reporting': {'schema': SCHEDULE_REPORTING_SCHEMA, 'notice': SCHEDULE_REPORTING_NOTICE},
            'date_assumption': schedule.get('assumption') or '',
            'plan_assumption': listed['plan'].get('assumption') or '',
            'remaining_start': current.get('start'),
            'remaining_source': (current.get('start_source') or {}).get('title'),
            'fact_assumption': fact.get('assumption') or '',
            'statement_summary': listed.get('control',{}).get('statement_summary'),
            'confirmation': fact.get('confirmation') or {}, 'act_evidence': fact.get('act_evidence') or {},
            'data_gaps': listed.get('control', {}).get('data_gaps') or [],
            'legal_deadline': (listed.get('terms') or {}).get('deadline'),
            'coverage': listed.get('comparison', {}).get('coverage') or {}}
