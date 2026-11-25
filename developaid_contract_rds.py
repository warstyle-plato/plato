"""Position-ordered RDS presentation of the canonical card, without reading or repricing sources."""
from __future__ import annotations

import datetime as dt
from collections import Counter

import developaid_contract_plan as plan
from developaid_contract_fact import _money

LAYOUT = 'rds-plan-fact-v1'
FIELDS = ('number', 'name', 'unit', 'start', 'finish', 'plan_quantity', 'fact_quantity',
          'quantity_deviation', 'planned', 'fact', 'deviation', 'day_deviation')


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
                       estimate=estimate_index, index=index, source_sha256=document['sha256'], comments=comments)
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
