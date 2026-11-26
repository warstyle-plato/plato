"""Last known physical quantity against each day's source plan.

Observation checkpoints retain their dates and outcomes. Forward-held state is
an analytical comparison, never a production interval or a new observation.
No history is backfilled before the first confirmation; source gaps stay empty.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

import developaid_contract_plan as plan

SCHEMA = 'contract-physical-state-v2'
COLORS = {'plan': 'D9D9D9', 'unknown': 'E4DFEC', 'closure_unconfirmed': 'E4DFEC', 'fact': '70AD47',
          'warning': 'FFD966', 'overdue': 'E06666', 'lag': 'FFD966'}
LEGEND = ('Серый — будущий план; сиреневый — нет подтверждённых данных или завершение после срока не подтверждено. '
          'Зелёный — известный физический объём покрывает план на этот день; жёлтый — отставание до срока; '
          'красный — незавершённость подтверждена источником после срока ГПР. '
          'Последний известный объём сохраняется до следующего наблюдения и среза; план сравнивается с ним на каждый день. '
          'Накопленный объём не подтверждает даты производства; перенос не означает новые работы. '
          'До первого наблюдения факт неизвестен; реальные разрывы исходного ГПР сохранены. '
          'Будущее остаётся серым. План равномерный по активным интервалам ГПР, если профиль объёмов не указан. '
          'Дата последнего подтверждения и возраст данных показаны отдельно. '
          'Чёрная линия — срез; оранжевая — сегодня. Денежное закрытие не является оплатой или физической готовностью.')


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
    result = {'schema': SCHEMA, 'basis': 'last_known_quantity_daily_plan', 'cut': cut,
              'history_available': False, 'checkpoints': [], 'bars': [],
              'current': None, 'note': 'Нет подтверждённого физического объёма. Это не нулевое выполнение.'}
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
            # A material-only/cost-derived zero increment is retained in the
            # source stream, but cannot establish a physical baseline or refresh it.
            if all(item['work_quantity'] == 0 and 'нулевой суммой' in
                   str(item.get('physical_quantity_basis') or '').lower() for item in group):
                continue
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
    if observed and (not last_report or observed > last_report):
        planned = plan.done(line, observed, plan_start)
        snapshot = {**current, 'date': observed.isoformat(), 'start': observed.isoformat(),
            'planned_fraction': planned, 'delta_pp': (progress['fraction']-planned)*100,
            'state': _state(progress['fraction'], planned, observed, finish),
            'range_kind': 'source_snapshot', 'date_basis': 'dated_source_snapshot'}
        result['checkpoints'].append(snapshot)
        last_report = observed
    # An observation becomes known on its own date, never at the beginning of
    # a reported production period. Carry only its quantity forward, comparing
    # it with each day's plan. Later catch-up cannot repaint an earlier day.
    checkpoints = result['checkpoints']
    for index, point in enumerate(checkpoints):
        begin = day(point['date'])
        until = day(checkpoints[index+1]['date'])-dt.timedelta(days=1) if index+1 < len(checkpoints) else date
        for left, right in parts:
            lo, hi = max(left, (begin-first).days), min(right, (until-first).days+1, cut_offset+1)
            for offset in range(lo, hi):
                at = first+dt.timedelta(days=offset)
                planned = plan.done(line, at, plan_start)
                state = _state(point['fact_fraction'], planned, at, finish)
                if state == 'overdue' and begin <= finish:
                    state = 'closure_unconfirmed'
                _append(result['bars'], offset, state, point, 'known_state', at, planned)
        # The extension is not part of the source plan. It starts only on a
        # post-deadline confirmation; no retroactive red from a later document.
        if begin > finish and point['fact_fraction'] < 1-1e-9:
            lo, hi = max((finish-first).days+1, (begin-first).days), min((until-first).days+1, cut_offset+1)
            for offset in range(lo, hi):
                at = first+dt.timedelta(days=offset)
                _append(result['bars'], offset, 'overdue', point, 'overdue_extension', at, 1.0)
    last_checkpoint = checkpoints[-1] if checkpoints else None
    if current['state'] == 'overdue' and not (last_checkpoint and day(last_checkpoint['date']) > finish):
        current['state'] = 'closure_unconfirmed'
    result['last_confirmed_at'] = last_checkpoint['date'] if last_checkpoint else None
    result['age_days'] = (date-day(last_checkpoint['date'])).days if last_checkpoint else None
    result['note'] = ('Последний подтверждённый объём: '+format(last_checkpoint['fact_quantity'], '.15g')+
        ' '+progress['unit']+' на '+last_checkpoint['date']+'; возраст данных на срез: '+str(result['age_days'])+
        ' дн. Объём перенесён до среза без новых наблюдений; цвет сравнивает его с планом каждого дня. '
        'Отчётные результаты сохранены по действующей редакции ГПР; это не история опубликованных вердиктов.'
        if last_checkpoint else 'Нет датированного подтверждения объёма. Прежние периоды не восстановлены.')

    return result



def _append(bars, offset, state, point, kind, at, planned):
    previous = bars[-1] if bars else None
    if previous and previous['end'] == offset and (previous['state'], previous['report_date'], previous['range_kind']) == (state, point['date'], kind):
        previous['end'] = offset+1
        previous['state_finish'] = at.isoformat()
        previous['planned_fraction_finish'] = planned
    else:
        bars.append({'start': offset, 'end': offset+1, 'state': state,
                     'report_date': point['date'], 'range_kind': kind,
                     'state_start':at.isoformat(), 'state_finish':at.isoformat(),
                     'planned_fraction_start':planned, 'planned_fraction_finish':planned,
                     'fact_quantity': point['fact_quantity'], 'fact_fraction': point['fact_fraction'],
                     'carried_forward': True, 'not_actual_dates': True})


def cell_states(model, ticks):
    """Never colour a mixed future/gap cell as though it were wholly observed."""
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
        bars = [bar for bar in model['bars'] if bar['start'] <= lo and bar['end'] >= hi]
        if bars:
            result[i] = bars[-1]
    return result
