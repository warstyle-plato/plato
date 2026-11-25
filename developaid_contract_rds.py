"""Position-ordered RDS presentation of the canonical card, without reading or repricing sources."""
from __future__ import annotations

import datetime as dt
import math
from collections import Counter

import developaid_contract_plan as plan
from developaid_contract_fact import _money
from developaid_monitor_statement_union import _unit

LAYOUT = 'rds-plan-fact-v2'
FIELDS = ('number', 'name', 'unit', 'start', 'finish', 'plan_quantity', 'plan_quantity_ratio',
          'fact_quantity', 'fact_quantity_ratio', 'quantity_deviation', 'planned', 'fact', 'deviation',
          'day_deviation', 'forecast_finish', 'forecast_delay_days')


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
    schedule = (documents.get(current.get('schedule_sha256')) or {}).get('schedule') or {}
    scheduled = {line['code']: line for line in schedule.get('lines') or []}
    usage = Counter(line['code'] for item in current['position_links'] if item['status'] in ('confirmed', 'proposed')
                    for line in item.get('lines') or [] if line.get('share'))
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
            for output, actual, planned in (('quantity_deviation', 'fact_quantity', 'plan_quantity'),
                                           ('deviation', 'fact', 'planned')):
                if row[actual] is not None and row[planned] is not None:
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
            canonical = None
            if len(targets) == 1:
                code = targets[0]['code']
                control = controls.get(code) or {}
                operations = [part for part in (control.get('operations') or {}).get('lines', [])
                              if part.get('position_key') == (binding or {}).get('key') and
                              (part.get('source') or {}).get('sha256') == document['sha256']]
                if len(operations) == 1:
                    canonical = operations[0]
                elif usage[code] == 1:
                    canonical = control
            if canonical and canonical.get('state') != 'unknown' and row['fact_quantity'] is not None and \
                    canonical.get('lag_days') is not None and canonical.get('ahead_days') is not None:
                row['day_deviation'] = canonical['ahead_days']-canonical['lag_days']
            else:
                comments['day_deviation'] = 'Для этой позиции РДС отклонение в днях отдельно не рассчитано; сроки договора и просрочка его не заменяют.'
            # Reuse an individual physical forecast only for a unique full-scope link.
            # No monetary fallback, proportional extrapolation or group forecast.
            volume = (canonical or {}).get('volume') or {}
            share = targets[0].get('share') if len(targets) == 1 else None
            forecast_known = (canonical and canonical.get('state') not in (None, 'unknown') and positive_base and
                type(row['fact_quantity']) in (int, float) and math.isfinite(row['fact_quantity']) and type(share) in (int, float) and share == 1 and
                type(volume.get('quantity')) in (int, float) and math.isfinite(volume['quantity']) and
                abs(volume['quantity']-quantity) <= 1e-6 and
                _unit(volume.get('unit')) == _unit(row['unit']) and
                type(volume.get('fact')) in (int, float) and math.isfinite(volume['fact']) and
                abs(volume['fact']-row['fact_quantity']) <= 1e-6)
            finish = (canonical.get('finished') if canonical.get('state') == 'done' else
                      canonical.get('forecast_finish')) if forecast_known else None
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
            rows.append(row)
    return {'layout': LAYOUT, 'available': True, 'cut': cut, 'rows': rows, 'headings': headings,
            'estimate_title': document.get('title') or '', 'estimate_sha256': document['sha256'],
            'source': fact.get('source'), 'source_note': fact.get('source_note') or '',
            'date_assumption': schedule.get('assumption') or '',
            'plan_assumption': listed['plan'].get('assumption') or '',
            'remaining_start': current.get('start'),
            'remaining_source': (current.get('start_source') or {}).get('title'),
            'fact_assumption': fact.get('assumption') or '',
            'confirmation': fact.get('confirmation') or {}, 'act_evidence': fact.get('act_evidence') or {},
            'data_gaps': listed.get('control', {}).get('data_gaps') or [],
            'legal_deadline': (listed.get('terms') or {}).get('deadline'),
            'coverage': listed.get('comparison', {}).get('coverage') or {}}
