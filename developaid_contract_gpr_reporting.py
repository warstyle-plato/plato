"""Reporting checkpoints over the source plan, never inferred production dates.

Only the selected canonical fact producer supplies physical increments. Older
cached cards have a current total but no period quantities: their previous
periods stay grey. A checkpoint compares cumulative volume to the same-date
uniform active-interval plan; its colour describes the report, not work dates.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

import developaid_contract_plan as plan

SCHEMA = 'contract-physical-reporting-v1'
COLORS = {'plan': 'D9D9D9', 'unknown': 'D9D9D9', 'fact': '70AD47',
          'warning': 'FFD966', 'overdue': 'E06666', 'lag': 'FFD966'}
LEGEND = ('Серый — будущий план или период без сопоставимого физического отчёта. '
          'Зелёный — накопленный физический план выполнен на дату отчёта; '
          'жёлтый — недобор до плана, пока срок работы не прошёл. '
          'Красный — по учтённым объёмам работа не завершена после срока ГПР. '
          'Цвет периода показывает результат сравнения на его отчётную дату, а не даты производства работ. '
          'Накопленный объём не подтверждает даты производства работ. '
          'Будущая часть плана остаётся серой; опережение указано числом. '
          'Прежние периоды без данных не восстанавливаются из последнего общего объёма. '
          'План физического объёма распределён равномерно по активным интервалам ГПР, без разрывов. '
          'Чёрная линия — дата среза; оранжевая — сегодня. Деньги не заменяют физический объём.')


def day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def _state(fraction, planned, date, finish):
    if finish and date > finish and fraction < 1-1e-9:
        return 'overdue'
    return 'warning' if fraction+1e-9 < planned else 'fact'


def project(line, progress, parts, origin, cut):
    """A single plan track plus evidenced report intervals/checkpoint markers.

    `parts` are half-open source-plan offsets. Checkpoint intervals never cross
    the cut or a source gap. The red extension is separately identified as time
    after the deadline, not a fictitious extension of the original plan.
    """
    result = {'schema': SCHEMA, 'basis': 'physical_report_checkpoints', 'cut': cut,
              'history_available': False, 'checkpoints': [], 'bars': [],
              'current': None, 'note': 'Нет сопоставимого физического объёма: прошлые периоды остаются серыми.'}
    date, first, finish = day(cut), day(origin), day(line.get('finish'))
    if (not date or not first or not finish or not day(line.get('start')) or not progress or not parts
            or progress.get('planned_fraction') is None):
        return result
    cut_offset = (date-first).days
    total = progress['contract_quantity']
    plan_start = day(line.get('reporting_plan_start'))
    events, seen, valid = [], {}, True
    for item in line.get('reporting_events') or []:
        end = day(item.get('end'))
        if end and end > date:
            continue
        witness = {key: item.get(key) for key in ('source', 'label', 'start', 'end')}
        expected = hashlib.sha256(json.dumps(witness, sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        if (not end or item.get('quantity_kind') != 'increment'
                or not numeric(item.get('work_quantity')) or item['work_quantity'] < 0
                or not isinstance(item.get('source'), dict) or not item['source']
                or item.get('id') != expected):
            valid = False
            break
        if item['id'] in seen:
            if seen[item['id']] != item:
                valid = False
                break
            continue
        seen[item['id']] = item
        events.append(item)
    # A partial event stream cannot establish earlier cumulative values. In
    # particular, missing events and unknown volumes are not zero baselines.
    valid = (valid and bool(events) and math.isclose(sum(item['work_quantity'] for item in events),
        progress['fact_quantity'], abs_tol=1e-6)
        and math.isclose(plan.done(line, date, plan_start), progress['planned_fraction'], abs_tol=1e-9))
    if valid:
        groups = {}
        for item in events:
            groups.setdefault(item['end'], []).append(item)
        accumulated, previous = 0.0, None
        for end, group in sorted(groups.items()):
            report_date = day(end)
            accumulated += sum(item['work_quantity'] for item in group)
            planned = plan.done(line, report_date, plan_start)
            fraction = accumulated/total
            starts = [day(item.get('start')) for item in group]
            interval_start = min(starts) if starts and all(starts) and all(
                item.get('date_basis') == 'reported_period' and not item.get('preliminary') for item in group) else None
            # A date-only document observation establishes a checkpoint only.
            # Never fill all days since a previous report across a missing period.
            begin = interval_start if interval_start and interval_start <= report_date else report_date
            if previous and begin <= previous:
                begin = previous+dt.timedelta(days=1)
            checkpoint = {'date': end, 'start': begin.isoformat(), 'fact_quantity': accumulated,
                'fact_fraction': fraction, 'planned_fraction': planned, 'delta_pp': (fraction-planned)*100,
                'state': _state(fraction, planned, report_date, finish),
                'source_event_ids': [item['id'] for item in group],
                'sources': [item['source'] for item in group],
                'date_basis': 'reported_period' if interval_start else 'document_observation',
                'range_kind': 'report_interval' if begin < report_date else 'checkpoint'}
            result['checkpoints'].append(checkpoint)
            b, e = (begin-first).days, (report_date-first).days+1
            for left, right in parts:
                lo, hi = max(left, b), min(right, e, cut_offset+1)
                if hi > lo:
                    result['bars'].append({'start': lo, 'end': hi, 'state': checkpoint['state'],
                        'report_date': end, 'range_kind': checkpoint['range_kind']})
            previous = report_date
        result['history_available'] = True
    current = {'date': cut, 'fact_quantity': progress['fact_quantity'],
               'fact_fraction': progress['fraction'], 'planned_fraction': progress['planned_fraction'],
               'delta_pp': progress['delta_pp'],
               'state': _state(progress['fraction'], progress['planned_fraction'], date, finish),
               'range_kind': 'current_snapshot', 'source_dates': progress.get('source_dates') or []}
    result['current'] = current
    observation_days = [day(value) for value in progress.get('source_dates') or []]
    observation_days = [value for value in observation_days if value and value <= date]
    observed = max(observation_days, default=None)
    last_report = day(result['checkpoints'][-1]['date']) if result['checkpoints'] else None
    # The UI cut is an analysis date, not a new physical report. Only a dated
    # source snapshot can add an observation after the last accepted act.
    if observed and (not last_report or observed >= last_report):
        planned = plan.done(line, observed, plan_start)
        snapshot = {**current, 'date': observed.isoformat(), 'start': observed.isoformat(),
            'planned_fraction': planned, 'delta_pp': (progress['fraction']-planned)*100,
            'state': _state(progress['fraction'], planned, observed, finish),
            'range_kind': 'source_snapshot', 'date_basis': 'dated_source_snapshot'}
        result['checkpoints'].append(snapshot)
        offset = (observed-first).days
        for left, right in parts:
            lo, hi = max(left, offset), min(right, offset+1)
            if hi > lo:
                result['bars'].append({'start':lo,'end':hi,'state':snapshot['state'],
                    'report_date':snapshot['date'],'range_kind':'source_snapshot'})
        last_report = observed
    last_checkpoint = result['checkpoints'][-1] if result['checkpoints'] else None
    if last_checkpoint and last_checkpoint['state'] == 'overdue':
        lo, hi = (finish-first).days+1, (last_report-first).days+1
        if hi > lo:
            result['bars'].append({'start': lo, 'end': hi, 'state': 'overdue',
                'report_date':last_checkpoint['date'], 'range_kind': 'overdue_extension'})
    if current['state'] == 'overdue' and not (last_checkpoint and last_checkpoint['state'] == 'overdue'):
        current['state'] = 'closure_unconfirmed'
    result['note'] = ('Периоды сравниваются по принятым физическим объёмам на их отчётные даты. '
        'Пересчёт выполнен по действующей редакции ГПР; это не история ранее опубликованных вердиктов.'
        if valid else 'Прежние физические объёмы по периодам не сохранены. Показана только датированная отметка источника, если его дата подтверждена; прежние периоды не восстановлены.')
    return result


def cell_states(model, ticks):
    """Choose report colours only for ticks wholly within the observed cut."""
    if not model or not ticks:
        return {}
    first = day(ticks[0].get('start'))
    if not first:
        return {}
    result = {}
    for i, tick in enumerate(ticks):
        start, end = day(tick.get('start')), day(tick.get('finish'))
        if not start or not end or tick['finish'] > model['cut']:
            continue
        lo, hi = (start-first).days, (end-first).days+1
        bars = [bar for bar in model['bars'] if bar['start'] < hi and bar['end'] > lo]
        if bars:
            # Preserve visible late status and short point checkpoints when
            # long schedules have multi-day display columns.
            result[i] = max(bars, key=lambda bar: (bar['range_kind'] == 'overdue_extension',
                bar['report_date'], bar['state'] == 'warning'))
    return result
