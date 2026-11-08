"""Source-bound natural-quantity progress, distinct from accepted cost/EAC.

Mappings group annual rows of ONE physical component explicitly. Annual totals
are reconciled to dated, non-overlapping periods; the full plan is counted once.
Different units are never averaged. The last ninety days of completed periods
provide calendar-day pace; stale or incomplete evidence cannot certify RNV.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import re
import tempfile

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_monitor_schedule_graph as graph

MAX_BINDINGS = 1000
MAX_ROWS = 5000


class PhysicalProblem(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _day(text):
    try:
        value = dt.date.fromisoformat(text)
        return value if value.isoformat() == text else None
    except (TypeError, ValueError):
        return None


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _unit(value):
    # Only typographical variants, no implicit scaling (100m2 != m2).
    return re.sub(r"\s+", "", str(value or '').lower().replace('²', '2').replace('³', '3'))


def _items(snapshot):
    out = {}
    for li, ledger in enumerate((snapshot or {}).get('ledgers') or []):
        for ii, item in enumerate(ledger.get('items') or []):
            out[f'{li}:{ii}'] = dict(item, period_year=ledger.get('period_year'),
                                    contract=ledger.get('contract') or '',
                                    contract_date=ledger.get('contract_date') or '',
                                    contractor=ledger.get('contractor') or '')
    return out


def _validate(config):
    if not isinstance(config, dict) or set(config) != {'tasks', 'components', 'note'}:
        raise PhysicalProblem('Не удалось прочитать состав привязки. Обновите страницу.')
    tasks, components = config['tasks'], config['components']
    if (not isinstance(tasks, list) or not isinstance(components, list)
            or len(tasks) > MAX_BINDINGS or len(components) > MAX_BINDINGS
            or not isinstance(config['note'], str) or not 1 <= len(config['note'].strip()) <= 1000):
        raise PhysicalProblem('Укажите основание привязки и не более 1000 работ или компонентов.')
    task_ids, component_ids, row_ids = set(), set(), set()
    for task in tasks:
        if (not isinstance(task, dict) or set(task) != {'task_id', 'mode', 'scope_confirmed', 'actual_finish'}
                or not isinstance(task['task_id'], str) or not 1 <= len(task['task_id']) <= 128
                or task['task_id'] in task_ids or not isinstance(task['mode'], str)
                or task['mode'] not in {'quantities', 'plan_duration', 'completed'}
                or type(task['scope_confirmed']) is not bool or not isinstance(task['actual_finish'], str)
                or (task['mode'] == 'completed' and not _day(task['actual_finish']))
                or (task['mode'] != 'completed' and task['actual_finish'])):
            raise PhysicalProblem('Проверьте состав работ, основания прогноза и даты завершения.')
        task_ids.add(task['task_id'])
    for component in components:
        if (not isinstance(component, dict) or set(component) != {'component_id', 'task_id', 'item_ids'}
                or not isinstance(component['component_id'], str)
                or not 1 <= len(component['component_id'].strip()) <= 120
                or component['component_id'] in component_ids or not isinstance(component['task_id'], str)
                or component['task_id'] not in task_ids
                or not isinstance(component['item_ids'], list) or not component['item_ids']
                or len(component['item_ids']) > MAX_ROWS):
            raise PhysicalProblem('Укажите уникальное имя компонента, работу и строки накопительных.')
        component_ids.add(component['component_id'])
        for item_id in component['item_ids']:
            if not isinstance(item_id, str) or not re.fullmatch(r'\d{1,5}:\d{1,6}', item_id) or item_id in row_ids:
                raise PhysicalProblem('Одна строка накопительной может входить только в один компонент.')
            row_ids.add(item_id)
            if len(row_ids) > MAX_ROWS:
                raise PhysicalProblem('В одной привязке поддерживается не более 5000 строк.')
    return config


def _history(project):
    result = []
    folder = monitor._project_dir(project) / 'physical_schedule_links'
    for revision, path in enumerate(sorted(folder.glob('[0-9]*.json')), 1):
        event = json.loads(path.read_text(encoding='utf-8'))
        if (type(event['revision']) is not int or event['revision'] != revision or path.stem != f'{revision:012d}'
                or not re.fullmatch(r'[0-9a-f]{64}', event['pm_sha256'])
                or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', event['snapshot_id'])
                or dt.datetime.fromisoformat(event['recorded_at']).utcoffset() != dt.timedelta(0)):
            raise ValueError('invalid physical mapping history')
        _validate(event['configuration'])
        result.append(event)
    return result


def _sources(project, cut, pm=None):
    return pm if pm is not None else graph._load_pm(project), ledgers.effective_snapshot(project, cut)


def _state(project, cut, pm, snapshot):
    events = _history(project)
    sha, sid = pm.get('source_sha256') or '', (snapshot or {}).get('snapshot_id') or ''
    matching = [e for e in events if e['pm_sha256'] == sha and e['snapshot_id'] == sid
                and dt.datetime.fromisoformat(e['recorded_at']).date().isoformat() <= cut]
    latest = matching[-1] if matching else None
    return {'pm_sha256': sha, 'snapshot_id': sid, 'revision': len(events),
            'configuration': latest['configuration'] if latest else {'tasks': [], 'components': [], 'note': ''},
            'recorded_at': latest['recorded_at'] if latest else None,
            'source_changed': bool(events and not matching),
            'can_edit': bool(sha and sid) and cut == _now().date().isoformat()}


def catalog(project, cut, query='', offset=0):
    if not _day(cut):
        raise PhysicalProblem('Укажите существующую дату среза.')
    pm, snapshot = _sources(project, cut)
    state = _state(project, cut, pm, snapshot)
    items = _items(snapshot)
    query = query.casefold().strip()
    rows = [dict(item_id=key, **{field: item.get(field) for field in
            ('name', 'scope', 'unit', 'plan_quantity', 'completed_quantity', 'period_year',
             'contract', 'contract_date', 'contractor', 'source')})
            for key, item in items.items()
            if not query or query in ' '.join(str(item.get(k) or '') for k in
                                               ('name', 'scope', 'contract', 'contractor')).casefold()]
    return dict(state, tasks=[{'task_id': tid, 'name': task.get('name') or tid}
                             for tid, task in (pm.get('tasks') or {}).items()],
                items=rows[offset:offset+200], item_count=len(rows), offset=offset,
                model=evaluate(pm, snapshot, state['configuration'], cut))


def save(project, pm_sha256, snapshot_id, revision, configuration):
    configuration = _validate(configuration)
    folder = monitor._project_dir(project) / 'physical_schedule_links'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    fd = os.open(folder / '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        cut = _now().date().isoformat()
        pm, snapshot = _sources(project, cut)
        state = _state(project, cut, pm, snapshot)
        if not state['can_edit']:
            raise PhysicalProblem('Сначала загрузите PM-график и архив накопительных.')
        if (pm_sha256 != state['pm_sha256'] or snapshot_id != state['snapshot_id']
                or type(revision) is not int or revision != state['revision']):
            raise PhysicalProblem('Исходные данные или привязка изменились. Обновите страницу.', 409)
        tasks, items = pm.get('tasks') or {}, _items(snapshot)
        if any(t['task_id'] not in tasks for t in configuration['tasks']):
            raise PhysicalProblem('В графике больше нет выбранной работы. Обновите данные.', 409)
        if any(i not in items for c in configuration['components'] for i in c['item_ids']):
            raise PhysicalProblem('В накопительных больше нет выбранной строки. Обновите данные.', 409)
        modes = {t['task_id']: t['mode'] for t in configuration['tasks']}
        if any(modes[c['task_id']] != 'quantities' for c in configuration['components']):
            raise PhysicalProblem('Компоненты привязываются только к работам с натуральной выработкой.')
        if any(t['mode'] == 'completed' and t['actual_finish'] > cut for t in configuration['tasks']):
            raise PhysicalProblem('Дата фактического завершения не может быть в будущем.')
        event = {'revision': revision+1, 'pm_sha256': pm_sha256, 'snapshot_id': snapshot_id,
                 'recorded_at': _now().isoformat(), 'actor': 'administrator',
                 'configuration': configuration}
        fd, temporary = tempfile.mkstemp(prefix='.event-', dir=folder)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(event, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / f'{revision+1:012d}.json')
        finally:
            Path(temporary).unlink(missing_ok=True)
    return catalog(project, cut)


def _component(component, items, cut):
    result = {'component_id': component['component_id'], 'task_id': component['task_id'],
              'known': False, 'progress': None, 'forecast_finish': None,
              'rate_per_day': None, 'reason': ''}
    rows = [items.get(key) for key in component['item_ids']]
    def unknown(reason):
        return dict(result, reason=reason)
    if not rows or any(row is None for row in rows):
        return unknown('Выбранная строка накопительной отсутствует.')
    result['sources'] = [{'source': row.get('source') or {}, 'period_year': row.get('period_year'),
                          'contract': row.get('contract'), 'contract_date': row.get('contract_date')}
                         for row in rows]
    units = {_unit(row.get('unit')) for row in rows}
    if len(units) != 1 or '' in units:
        return unknown('В компоненте разные или неизвестные единицы измерения.')
    plans = [_number(row.get('plan_quantity')) for row in rows]
    if any(p is None or p <= 0 for p in plans) or any(abs(p-plans[0]) > max(1e-6, plans[0]*1e-7) for p in plans):
        return unknown('Полный план компонента неизвестен или различается между годовыми книгами.')
    years = [row.get('period_year') for row in rows]
    if len(set(years)) != len(years) or any(type(y) is not int for y in years):
        return unknown('Один год компонента выбран несколько раз или не распознан.')
    # A group deliberately spans annual rows from one exact contract. The
    # operator supplies the cross-year identity; names/amounts never imply it.
    contracts = {(row.get('contractor'), row.get('contract'), row.get('contract_date')) for row in rows}
    if len(rows) > 1 and (len(contracts) != 1 or not all(next(iter(contracts)))
                          or not _day(next(iter(contracts))[2])):
        return unknown('Для группировки по годам нужен один подтверждённый договор с датой и контрагентом.')
    periods = []
    for row in rows:
        annual = _number(row.get('completed_quantity'))
        if annual is None or annual < 0:
            return unknown('Выполненный годовой объём неизвестен или отрицателен.')
        current = []
        for period in row.get('periods') or []:
            a, b, quantity = _day(period.get('date_start')), _day(period.get('date_end')), _number(period.get('quantity'))
            # Empty future columns do not become zero production. They provide
            # no evidence at this cut and are excluded before annual equality.
            if b and b > cut and (quantity is None or quantity == 0):
                continue
            if not a or not b or a > b or quantity is None or quantity < 0:
                return unknown('Не все периоды имеют даты и неотрицательные объёмы.')
            if a.year != row['period_year'] or b.year != row['period_year']:
                return unknown('Период не относится к году накопительной.')
            current.append((a, b, quantity))
        if not current or abs(math.fsum(p[2] for p in current)-annual) > max(1e-6, annual*1e-7):
            return unknown('Сумма датированных периодов не совпадает с годовым итогом.')
        periods.extend(current)
    periods.sort()
    if any(right[0] <= left[1] for left, right in zip(periods, periods[1:])):
        return unknown('Периоды перекрываются: нельзя отличить выработку от повторного накопительного итога.')
    if any(p[1] > cut for p in periods):
        return unknown('В годовом итоге есть период после даты среза; его выполнение на дату среза неизвестно.')
    done = math.fsum(p[2] for p in periods)
    plan = plans[0]
    if done > plan + max(1e-6, plan*1e-7):
        return unknown('Сумма годовых объёмов превышает полный план компонента.')
    result.update(unit=rows[0]['unit'], plan_quantity=plan, completed_quantity=done,
                  progress=done/plan, period_end=periods[-1][1].isoformat())
    cumulative, series = 0, []
    for a, b, quantity in periods:
        cumulative += quantity
        series.append({'start': a.isoformat(), 'end': b.isoformat(), 'quantity': quantity,
                       'cumulative_quantity': cumulative})
    result.update(recent_periods=series[-12:], period_count=len(series))
    if done >= plan - max(1e-6, plan*1e-7):
        # Find the first period when cumulative physical work reaches the plan.
        cumulative = 0
        finish = periods[-1][1]
        for a, b, quantity in periods:
            cumulative += quantity
            if cumulative >= plan - max(1e-6, plan*1e-7):
                finish = b
                break
        return dict(result, known=True, forecast_finish=finish.isoformat(), method='completed_quantities')
    recent = [p for p in periods if p[0] >= cut-dt.timedelta(days=90)]
    if not recent:
        return dict(result, reason='Нет закрытых периодов, целиком входящих в последние 90 дней; текущий темп неизвестен.')
    if (cut-recent[-1][1]).days > 45:
        return dict(result, reason='Последний датированный период старше 45 дней; текущий темп неизвестен.')
    days = (recent[-1][1]-recent[0][0]).days+1
    pace = math.fsum(p[2] for p in recent)/days
    if pace <= 0:
        return dict(result, reason='В последних датированных периодах нет положительной выработки.')
    # Divide once to avoid 50/(50/31) rounding up to 32 whole days.
    remaining = (plan-done)/math.fsum(p[2] for p in recent)*days
    if not math.isfinite(remaining) or remaining > 36500:
        return dict(result, reason='Расчётный остаток превышает 100 лет; надёжного текущего темпа нет.')
    remaining_days = math.ceil(remaining-1e-10)
    try:
        finish = (cut+dt.timedelta(days=remaining_days)).isoformat()
    except OverflowError:
        return dict(result, reason='Расчётная дата выходит за поддерживаемые границы.')
    return dict(result, known=True, rate_per_day=pace, rate_window_start=recent[0][0].isoformat(),
                rate_window_end=recent[-1][1].isoformat(),
                forecast_finish=finish, method='natural_quantity_pace')


def evaluate(pm, snapshot, configuration, cut):
    day = _day(cut)
    if not day:
        raise PhysicalProblem('Укажите существующую дату среза.')
    tasks = pm.get('tasks') or {}
    items = _items(snapshot)
    configs = {row['task_id']: row for row in configuration['tasks']}
    components = [_component(c, items, day) for c in configuration['components']]
    # Only ancestors of the explicit RNV milestone can certify its forecast.
    required, pending = set(), [pm.get('rnv_id')]
    while pending:
        tid = pending.pop()
        if tid not in tasks or tid in required:
            continue
        required.add(tid)
        pending.extend(e['id'] for e in tasks[tid].get('predecessors') or [])
    rows, seeds, actual_finishes, reasons = [], {}, {}, []
    physical_evidence = False
    for tid in tasks:
        config = configs.get(tid)
        own = [c for c in components if c['task_id'] == tid]
        result = {'task_id': tid, 'name': tasks[tid].get('name') or tid, 'components': own,
                  'mode': config['mode'] if config else 'unknown', 'known': False,
                  'forecast_finish': None, 'progress': None, 'reason': ''}
        if config and config['scope_confirmed']:
            if config['mode'] == 'quantities':
                if own and all(c['known'] for c in own):
                    result.update(known=True, forecast_finish=max(c['forecast_finish'] for c in own))
                    # Never average unlike components into a pretend percent.
                    result['progress'] = own[0]['progress'] if len(own) == 1 else None
                    physical_evidence = physical_evidence or tid in required
                else:
                    result['reason'] = 'Не все компоненты задачи имеют достоверную натуральную выработку.'
            elif config['mode'] == 'completed':
                finish = _day(config['actual_finish'])
                if finish and finish <= day:
                    result.update(known=True, forecast_finish=finish.isoformat(), progress=1.0)
                    physical_evidence = physical_evidence or tid in required
                else:
                    result['reason'] = 'Фактическая дата завершения отсутствует или позже среза.'
            elif isinstance(tasks[tid].get('finish'), dt.date) and tasks[tid]['finish'] >= day:
                result['known'] = True
            else:
                result['reason'] = 'Плановый срок уже прошёл; факт завершения или текущий темп не подтверждён.'
        else:
            result['reason'] = 'Состав работы и основание прогноза не подтверждены.'
        if result['forecast_finish']:
            seeds[tid] = result['forecast_finish']
            if (result['mode'] == 'completed' or result['mode'] == 'quantities'
                    and own and all(c.get('method') == 'completed_quantities' for c in own)):
                actual_finishes[tid] = result['forecast_finish']
                result['actual_finish'] = result['forecast_finish']
        rows.append(result)
    # A confirmed non-quantity stage may not have started because its predecessor
    # moved. Keep its planned duration when the same network places its finish
    # in the future; never silently treat a past, unshifted stage as completed.
    propagated = graph._propagate(pm, {tid: _day(value) for tid, value in seeds.items()},
                                 actual_finishes={tid: _day(value) for tid, value in actual_finishes.items()}) if seeds else {}
    for row in rows:
        config = configs.get(row['task_id']) or {}
        shifted = (propagated.get(row['task_id']) or {}).get('forecast_finish')
        if (row['mode'] == 'plan_duration' and config.get('scope_confirmed')
                and isinstance(shifted, dt.date) and shifted >= day):
            row.update(known=True, reason='')
        if row['task_id'] in required and not row['known']:
            reasons.append('Не подтверждены объёмы или факт выполнения работы «'+row['name']+'».')
        network = propagated.get(row['task_id']) or {}
        if row['task_id'] in required and network.get('completion_conflicts'):
            reasons.append('Факт завершения работы «'+row['name']+'» противоречит связям с предшественниками. '
                           'Проверьте фактические даты и зависимости; завершённая работа не переносится в будущее.')
        if row['task_id'] in required and network.get('unknown_actual_starts'):
            reasons.append('Для связи от начала завершённой работы к «'+row['name']+'» '
                           'неизвестна фактическая дата начала; одного окончания недостаточно.')
    if not required:
        reasons.append('В PM не выбрана веха РНВ.')
    if not configuration['tasks']:
        reasons.append('Накопительные ещё не привязаны к работам исходного графика.')
    if not physical_evidence:
        reasons.append('Нет подтверждённого натурального темпа или факта завершения.')
    all_reasons = list(dict.fromkeys(reasons))
    display_reasons = all_reasons[:20]
    if len(all_reasons) > 20:
        display_reasons.append(f'Дополнительно не подтверждены {len(all_reasons)-20} оснований; проверьте весь перечень привязок.')
    return {'state': 'complete' if not reasons else 'partial' if physical_evidence else 'unknown',
            'tasks': rows, 'seeds': seeds, 'actual_finishes': actual_finishes, 'physical_evidence': physical_evidence,
            'reasons': display_reasons, 'basis': 'natural_quantities_and_explicit_facts'}


def build(project, cut, pm):
    if (pm or {}).get('disabled'):
        # Mappings were made to PM tasks; with PM off they do not apply.
        return {'state': 'unknown', 'tasks': [], 'seeds': {}, 'physical_evidence': False,
                'disabled': True,
                'reasons': ['Привязки накопительных к работам PM не применяются: PM отключён. '
                            'Привязка накопительных к работам ГПР — следующим шагом.']}
    try:
        pm, snapshot = _sources(project, cut, pm)
        state = _state(project, cut, pm, snapshot)
        result = evaluate(pm, snapshot, state['configuration'], cut)
        return dict(result, snapshot_id=state['snapshot_id'], pm_sha256=state['pm_sha256'],
                    recorded_at=state['recorded_at'], source_changed=state['source_changed'],
                    confirmation_note=state['configuration']['note'])
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return {'state': 'unknown', 'tasks': [], 'seeds': {}, 'physical_evidence': False,
                'reasons': ['Привязки натуральных объёмов сейчас не читаются; физический прогноз не подтверждён.']}


def render(block):
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    out = ['<section class="physical-progress"><h3>Физическое выполнение по накопительным</h3>',
           '<p>Полный план компонента учитывается один раз. Периоды разных лет не перекрываются; '
           'рублёвое выполнение и поставка материалов не заменяют выполненный монтаж.</p>']
    if block.get('recorded_at'):
        out.append('<p><b>Основание привязки от '+esc(block['recorded_at'][:10])+':</b> '+
                   esc(block.get('confirmation_note'))+'</p>')
    for reason in block.get('reasons') or []:
        out.append('<p class="note">'+esc(reason)+'</p>')
    out.append('<div style="overflow:auto"><table><thead><tr><th>Работа / компонент</th><th>Выполнено / план</th>'
               '<th>Темп в календарный день</th><th>Прогноз окончания</th></tr></thead><tbody>')
    for task in block.get('tasks') or []:
        if task.get('mode') == 'unknown':
            continue
        basis = {'quantities': 'натуральная выработка', 'plan_duration': 'плановая длительность',
                 'completed': 'подтверждённый факт завершения'}.get(task.get('mode'), '')
        finish = task.get('forecast_finish') or ('по связям графика' if task.get('known') and task.get('mode') == 'plan_duration' else 'неизвестен')
        out.append('<tr><th colspan="3">'+esc(task['name'])+' · '+esc(basis)+'</th><th>'+esc(finish)+'</th></tr>')
        if task.get('reason'):
            out.append('<tr><td colspan="4">'+esc(task['reason'])+'</td></tr>')
        for c in task.get('components') or []:
            done, plan, pace = c.get('completed_quantity'), c.get('plan_quantity'), c.get('rate_per_day')
            source_date = (('по ведомости от '+c['observation_date']) if c.get('progress_date_basis') == 'snapshot'
                           and c.get('observation_date') else 'по '+str(c.get('period_end') or ''))
            amount = 'неизвестно' if done is None or plan is None else f'{done:g} / {plan:g} {c.get("unit", "")} · {source_date}'
            rate = 'неизвестен' if pace is None else f'{pace:g} {c.get("unit", "")}/день · {c.get("rate_window_start", "")} — {c.get("rate_window_end", "")}'
            out.append('<tr><td>'+esc(c['component_id'])+'</td><td>'+esc(amount)+'</td><td>'+esc(rate)+'</td><td>'+esc(c.get('forecast_finish') or c.get('reason') or 'неизвестен')+'</td></tr>')
            for evidence in c.get('sources') or []:
                source = evidence['source']
                trace = ' · '.join(str(v) for v in [source.get('filename'), source.get('sheet'),
                    'строка '+str(source.get('row')) if source.get('row') else '',
                    evidence.get('period_year'), 'договор '+str(evidence.get('contract') or ''),
                    evidence.get('contract_date')] if v is not None and v != '')
                out.append('<tr><td colspan="4" class="note">'+esc(trace)+'</td></tr>')
            periods = c.get('recent_periods') or []
            if periods:
                maximum = max((p['quantity'] for p in periods), default=0) or 1
                plot = ['<svg role="img" aria-label="Натуральная выработка по датированным периодам" '
                        f'viewBox="0 0 {len(periods)*42} 75" style="width:100%;max-width:600px;height:100px">']
                for i, period in enumerate(periods):
                    height = 50*period['quantity']/maximum
                    title = f'{period["start"]} — {period["end"]}: {period["quantity"]:g} {c.get("unit", "")}'
                    plot.append(f'<rect x="{i*42+2}" y="{52-height:.2f}" width="28" height="{max(1,height):.2f}" fill="#2e7d55"><title>'+esc(title)+'</title></rect>')
                    plot.append(f'<text x="{i*42+2}" y="68" font-size="8">'+esc(period['end'][5:])+'</text>')
                plot.append('</svg>')
                details = '<details><summary>Выработка по периодам'+(' · последние 12 из '+str(c['period_count']) if c['period_count'] > 12 else '')+'</summary>'+''.join(plot)
                details += '<table><tr><th>Период</th><th>Объём</th><th>Накоплено</th></tr>'
                for period in periods:
                    details += '<tr><td>'+esc(period['start']+' — '+period['end'])+'</td><td>'+esc(f'{period["quantity"]:g} {c.get("unit", "")}')+'</td><td>'+esc(f'{period["cumulative_quantity"]:g}')+'</td></tr>'
                out.append('<tr><td colspan="4">'+details+'</table></details></td></tr>')
    out.append('</tbody></table></div></section>')
    return ''.join(out)
