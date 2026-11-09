"""One dependency/RNV presentation model for Monitor and management documents.

Dates come from the existing PM propagation; this module cannot approve a
baseline, infer missing links, infer a calendar or turn a source percentage into
a duration. Partial results are deliberately separate from an asserted RNV.
"""
from __future__ import annotations

import datetime as dt
import html
from typing import Any

import developaid_monitor_schedule_graph as graph


def _iso(value):
    return value.isoformat() if isinstance(value, dt.date) else None


def model(pm: dict, seeds: dict[str, dt.date], *, evidence: bool = False,
          actual_finishes: dict[str, dt.date] | None = None) -> dict:
    actual_finishes = actual_finishes or {}
    reasons = list(pm.get('validation_issues') or [])
    tasks = pm.get('tasks') or {}
    if not pm.get('known') or not tasks:
        return {'state': 'unknown', 'rows': [], 'edges': [], 'confirmation': pm.get('confirmation') or {}, 'rnv': {
            'state': 'unknown', 'approved': None, 'forecast': None, 'indicative_forecast': None,
            'delay_days': None, 'driving_chain': [],
            'reasons': [pm.get('reason') or 'Выгрузка PM с подтверждёнными связями работ не загружена.']}}
    valid_types = {'FS', 'SS', 'FF', 'SF'}
    safe_tasks = {}
    for tid, task in tasks.items():
        if not isinstance(task.get('start'), dt.date) or not isinstance(task.get('finish'), dt.date):
            reasons.append('В PM есть работа без распознанных дат.')
            continue
        if task['finish'] < task['start']:
            reasons.append('В PM есть работа с окончанием раньше начала.')
            continue
        good_edges = []
        for edge in task.get('predecessors') or []:
            if edge.get('id') not in tasks:
                reasons.append('В PM есть ссылка на отсутствующего предшественника.')
            elif edge.get('type', 'FS') not in valid_types:
                reasons.append('В PM есть неподдерживаемый тип связи.')
            elif not isinstance(edge.get('lag_days', 0), (int, float)):
                reasons.append('В PM есть связь с нераспознанным лагом.')
            else:
                good_edges.append(dict(edge, type=edge.get('type', 'FS'), lag_days=edge.get('lag_days', 0)))
        safe_tasks[tid] = dict(task, predecessors=good_edges,
                               total_float_days=task.get('total_float_days') or 0,
                               free_float_days=task.get('free_float_days') or 0)
    # Remove edges to rows rejected for missing dates. Never silently call the
    # resulting reduced network complete.
    for task in safe_tasks.values():
        task['predecessors'] = [e for e in task['predecessors'] if e['id'] in safe_tasks]
    indegrees = {tid: len(t['predecessors']) for tid, t in safe_tasks.items()}
    successors = {tid: [] for tid in safe_tasks}
    for tid, task in safe_tasks.items():
        for edge in task['predecessors']:
            successors[edge['id']].append(tid)
    queue = [tid for tid, count in indegrees.items() if not count]
    ordered = 0
    while queue:
        tid = queue.pop()
        ordered += 1
        for successor in successors[tid]:
            indegrees[successor] -= 1
            if not indegrees[successor]:
                queue.append(successor)
    has_cycle = ordered != len(safe_tasks)
    if has_cycle:
        reasons.append('В сети зависимостей обнаружен цикл; прогноз по этой сети не рассчитан.')
    if not pm.get('calendar_confirmed'):
        reasons.append('Рабочий календарь не подтверждён: показан только расчёт в календарных днях.')
    if not pm.get('rnv_chain_complete'):
        reasons.append('Полнота цепочки до РНВ, включая приёмку и получение разрешения, не подтверждена.')
    if not evidence:
        reasons.append('Нет актуального темпа или утверждённого переноса, подтверждающего прогноз.')
    propagated = (graph._propagate(dict(pm, tasks=safe_tasks), seeds, actual_finishes=actual_finishes)
                  if not has_cycle else {})
    rows, edges = [], []
    for tid, source in safe_tasks.items():
        task = propagated.get(tid) or source
        forecast_start = task.get('forecast_start') if evidence and not has_cycle else None
        forecast_finish = task.get('forecast_finish') if evidence and not has_cycle else None
        actual_finish = actual_finishes.get(tid)
        if isinstance(actual_finish, dt.date):
            forecast_start, forecast_finish = None, actual_finish
        rows.append({'id': tid, 'name': source.get('name') or tid,
                     'plan_start': _iso(source['start']), 'plan_finish': _iso(source['finish']),
                     'forecast_start': _iso(forecast_start), 'forecast_finish': _iso(forecast_finish),
                     'actual_finish': _iso(actual_finish),
                     'own_delay_days': task.get('own_delay_days') if forecast_finish else None,
                     'inherited_delay_days': task.get('inherited_delay_days') if forecast_finish else None,
                     'remaining_float_days': (task.get('current_float_days') if forecast_finish
                         and source.get('total_float_known', True) else None),
                     'float_source': 'PM' if source.get('total_float_known', True) else 'unknown'})
        edges.extend({'from': edge['id'], 'to': tid, 'type': edge['type'],
                      'lag_days': edge['lag_days']} for edge in source['predecessors'])
    rnv_id = pm.get('rnv_id')
    ancestors, pending = set(), [rnv_id]
    while pending:
        tid = pending.pop()
        if tid in safe_tasks and tid not in ancestors:
            ancestors.add(tid)
            pending.extend(e['id'] for e in safe_tasks[tid]['predecessors'])
    incompatible_facts = False
    for tid in ancestors:
        task = propagated.get(tid) or {}
        seed = seeds.get(tid)
        if (isinstance(seed, dt.date) and seed < safe_tasks[tid]['finish']
                and tid not in actual_finishes):
            reasons.append('Раннее окончание работы «'+str(task.get('name') or tid)+
                           '» передано без подтверждения факта; игнорирование этой даты не подтверждает РНВ.')
        if task.get('completion_conflicts'):
            incompatible_facts = True
            reasons.append('Фактическое завершение работы «'+str(task.get('name') or tid)+
                           '» противоречит зависимостям. Факт сохранён; итоговый срок РНВ не подтверждён.')
        if task.get('unknown_actual_starts'):
            incompatible_facts = True
            reasons.append('Для связи от начала завершённой работы к «'+str(task.get('name') or tid)+
                           '» фактическое начало не подтверждено.')
    rnv = propagated.get(rnv_id) or safe_tasks.get(rnv_id)
    if not rnv:
        reasons.append('В PM не найдена отдельная веха получения РНВ; конец строительных работ её не заменяет.')
    elif not rnv.get('predecessors'):
        reasons.append('Веха РНВ не связана с предыдущими этапами.')
    ambiguous_rnv = len(pm.get('rnv_candidates') or []) > 1
    if ambiguous_rnv:
        reasons.append('В PM несколько вех РНВ; итоговая веха проекта не выбрана.')
    chain, seen = [], set()
    cursor = rnv_id
    while cursor in propagated and cursor not in seen:
        seen.add(cursor)
        task = propagated[cursor]
        chain.append({'id': cursor, 'name': task.get('name') or cursor})
        pushing = [edge for edge in task['predecessors']
                   if graph._constraint_start(edge, propagated[edge['id']], task) == task['forecast_start']]
        if not pushing:
            break
        # Several equally driving predecessors are kept as branches in edges;
        # a display chain is one explanation, not an exclusive critical path.
        cursor = sorted(pushing, key=lambda e: str(e['id']))[0]['id']
    approved = rnv.get('finish') if rnv else None
    indicative = (rnv.get('forecast_finish') if rnv and evidence and not has_cycle
                  and not ambiguous_rnv and not incompatible_facts else None)
    state = 'unknown' if not indicative else 'partial' if reasons else 'complete'
    return {'state': 'ok', 'rows': rows, 'edges': edges, 'source': pm.get('source') or '',
            'confirmation': pm.get('confirmation') or {},
            'calendar_basis': 'calendar_days', 'rnv': {'state': state,
                'approved': _iso(approved), 'forecast': _iso(indicative) if state == 'complete' else None,
                'indicative_forecast': _iso(indicative),
                'delay_days': (indicative-approved).days if indicative and approved else None,
                'driving_chain': list(reversed(chain)) if indicative else [],
                'reasons': list(dict.fromkeys(reasons))}}


def _technical_render(block: dict) -> str:
    """Escaped technical evidence for opt-in Monitor details."""
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    rnv = block.get('rnv') or {}
    date = lambda value: dt.date.fromisoformat(value).strftime('%d.%m.%Y') if value else '—'
    state = rnv.get('state')
    out = ['<section class="dependency-timeline"><h3>Сдвиги по цепочке работ и прогноз РНВ</h3>',
           '<p><b>План РНВ:</b> '+esc(date(rnv.get('approved')))+' · <b>Прогноз РНВ:</b> '+
           esc(date(rnv.get('forecast')) if state == 'complete' else
                date(rnv.get('forecast'))+' — оценка по ГПР' if state == 'estimate' else
                'неполный' if state == 'partial' else 'недостаточно данных')+'</p>']
    if state == 'partial' and rnv.get('indicative_forecast'):
        out.append('<p>'+('По работам ГПР с прогнозом: ' if rnv.get('basis') == 'gpr' else 'По известной части сети: ')
                   +esc(date(rnv['indicative_forecast']))+
                   ' · сдвиг '+esc(rnv.get('delay_days'))+' дн. Это не подтверждённый итоговый срок РНВ.</p>')
    for reason in rnv.get('reasons') or []:
        out.append('<p class="note">'+esc(reason)+'</p>')
    confirmation = block.get('confirmation') or {}
    if confirmation.get('recorded_at'):
        out.append('<p class="note"><b>Проверка исходного графика:</b> '+
                   ('Расчёт в календарных днях подтверждён.' if confirmation.get('calendar_basis') == 'calendar_days'
                    else 'Календарь не подтверждён.')+' '+
                   ('Полнота цепочки до РНВ подтверждена.' if confirmation.get('rnv_chain_complete')
                    else 'Полнота цепочки до РНВ не подтверждена.')+' Проверка от '+
                   esc(date(confirmation['recorded_at'][:10]))+'. '+esc(confirmation.get('note'))+'</p>')
    chain = rnv.get('driving_chain') or []
    if chain and rnv.get('basis') == 'gpr':
        out.append('<p><b>Срок тянет работа:</b> «'+esc(chain[0]['name'])+'»'+
                   (' — '+esc(chain[0]['reason']) if chain[0].get('reason') else '')+'</p>')
    elif chain:
        out.append('<p><b>Одна из ведущих цепочек:</b> '+ ' → '.join(esc(row['name']) for row in chain)+'</p>')
    if block.get('physical'):
        from developaid_schedule_physical import render as render_physical
        out.append(render_physical(block['physical']))
    all_rows = block.get('rows') or []
    out.append('<h4>Все работы исходной сети ('+str(len(all_rows))+')</h4><div style="overflow-x:auto"><table class="schedule-all-tasks"><thead><tr><th>Работа / ID</th><th>План</th><th>Расчёт / факт окончания</th><th>Собственная задержка</th><th>От предыдущих этапов</th><th>Резерв</th></tr></thead><tbody>')
    for row in all_rows:
        out.append('<tr data-network-task="'+esc(row['id'])+'"><td>'+esc(row['name'])+'<br><small>'+esc(row['id'])+'</small></td><td>'+esc(date(row.get('plan_start')))+' — '+esc(date(row.get('plan_finish')))+'</td><td>'+('Факт завершения: ' if row.get('actual_finish') else '')+esc(date(row.get('actual_finish') or row.get('forecast_finish')))+'</td><td>'+esc('нет данных' if row.get('own_delay_days') is None else row['own_delay_days'])+'</td><td>'+esc('нет данных' if row.get('inherited_delay_days') is None else row['inherited_delay_days'])+'</td><td>'+esc('не указан' if row.get('remaining_float_days') is None else row['remaining_float_days'])+'</td></tr>')
    out.append('</tbody></table></div>')
    # A small example can show its whole network. Large networks use the same
    # explicitly selected driver explanation; every task is accessible above.
    rows = all_rows if len(all_rows) <= 12 else overview_rows(block)[0]
    if not rows:
        out.append('</section>')
        return ''.join(out)
    days = [dt.date.fromisoformat(r[k]) for r in rows
            for k in ('plan_start', 'plan_finish', 'forecast_start', 'forecast_finish') if r.get(k)]
    first, last = min(days), max(days)
    span = max((last-first).days, 1)
    x = lambda value: 260+530*(dt.date.fromisoformat(value)-first).days/span
    positions = {row['id']: i for i, row in enumerate(rows)}
    physical_rows = {row['task_id']: row for row in (block.get('physical') or {}).get('tasks') or []}
    out.append('<div style="overflow-x:auto"><svg role="img" aria-label="Зависимости и сдвиги работ" '
               f'viewBox="0 0 1000 {len(rows)*48+42}" style="width:100%;min-width:850px" xmlns="http://www.w3.org/2000/svg">')
    out.append('<defs><marker id="dependency-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6" fill="#8a6200"/></marker></defs>')
    out.append('<text x="260" y="14" font-size="12">'+esc(date(first.isoformat()))+'</text><text x="700" y="14" font-size="12">'+esc(date(last.isoformat()))+'</text>')
    for edge in block.get('edges') or []:
        if edge['from'] not in positions or edge['to'] not in positions:
            continue
        pred, succ = rows[positions[edge['from']]], rows[positions[edge['to']]]
        pf = 'forecast_finish' if edge['type'][0] == 'F' else 'forecast_start'
        sf = 'forecast_start' if edge['type'][1] == 'S' else 'forecast_finish'
        if not pred.get(pf) or not succ.get(sf):
            continue
        px, sx = x(pred[pf]), x(succ[sf])
        py, sy = 42+positions[pred['id']]*48, 42+positions[succ['id']]*48
        out.append(f'<path d="M{px:.1f} {py}H{px+8:.1f}V{sy}H{sx:.1f}" fill="none" stroke="#8a6200" marker-end="url(#dependency-arrow)"><title>'+esc(edge['type'])+' '+esc(edge['lag_days'])+' дн.</title></path>')
    for i, row in enumerate(rows):
        y = 30+i*48
        out.append(f'<text x="0" y="{y+10}" font-size="12"><title>'+esc(row['name'])+'</title>'+esc(row['name'][:35])+'</text>')
        a, b = x(row['plan_start']), x(row['plan_finish'])
        out.append(f'<rect x="{a:.1f}" y="{y}" width="{max(2,b-a):.1f}" height="6" fill="#cbd1d9"/>')
        physical_row = physical_rows.get(row['id']) or {}
        physical_progress = physical_row.get('progress') if physical_row.get('mode') == 'quantities' else None
        if isinstance(physical_progress, (int, float)) and 0 <= physical_progress <= 1:
            out.append(f'<rect x="{a:.1f}" y="{y}" width="{max(0,(b-a)*physical_progress):.1f}" height="6" fill="#2e7d55"><title>Подтверждённый натуральный объём: {physical_progress*100:.1f}%</title></rect>')
        if row.get('forecast_start') and row.get('forecast_finish'):
            a, b = x(row['forecast_start']), x(row['forecast_finish'])
            out.append(f'<rect x="{a:.1f}" y="{y+9}" width="{max(2,b-a):.1f}" height="6" fill="#205c96"/>')
        if row.get('actual_finish'):
            out.append(f'<circle cx="{x(row["actual_finish"]):.1f}" cy="{y+12}" r="4" fill="#2e7d55"><title>Факт завершения: '+esc(date(row['actual_finish']))+'</title></circle>')
        own, inherited = row.get('own_delay_days'), row.get('inherited_delay_days')
        out.append(f'<text x="805" y="{y+12}" font-size="11">Своя: '+esc('—' if own is None else own)+' · от этапов: '+esc('—' if inherited is None else inherited)+'</text>')
        label = ' · факт: ' if row.get('actual_finish') else ' → '
        out.append(f'<text x="260" y="{y+31}" font-size="10">'+esc(date(row['plan_finish']))+label+esc(date(row.get('forecast_finish')))+' · резерв: '+esc('не указан' if row.get('remaining_float_days') is None else str(row['remaining_float_days'])+' дн.')+'</text>')
    out.append('</svg></div><p class="note">Серое — исходный план; зелёное на плановой полосе — доля натурального объёма отдельной работы; зелёная точка — факт окончания без предположения о фактическом начале; синее — расчёт по известным данным; стрелки — связи PM. Разные компоненты не усредняются. Унаследованные сдвиги по цепочке не складываются.</p></section>')
    return ''.join(out)


def overview_rows(block: dict) -> tuple[list[dict], str]:
    """Select an explanation of the existing driving chain, never PM file order.

    This does not change or aggregate the network. Long chains retain their
    largest own-delay source and final steps; the complete chain remains in the
    technical view. Finished historical rows cannot crowd out the current cause.
    """
    all_rows = {row['id']: row for row in block.get('rows') or []}
    chain = [all_rows[item['id']] for item in (block.get('rnv') or {}).get('driving_chain') or []
             if item['id'] in all_rows]
    pending = [row for row in chain if not row.get('actual_finish')]
    delayed = [row for row in chain
               if (row.get('own_delay_days') or 0) > 0 or (row.get('inherited_delay_days') or 0) > 0]
    if delayed:
        origins = [row for row in delayed if (row.get('own_delay_days') or 0) > 0]
        source = max(origins or delayed,
                     key=lambda row: (row.get('own_delay_days') or 0,
                                      row.get('inherited_delay_days') or 0,
                                      row.get('forecast_finish') or ''))
        selected_ids = {source['id'], *(row['id'] for row in pending[-3:])}
        rows = [row for row in chain if row['id'] in selected_ids]
        hidden = len(chain)-len(rows)
        note = ('Показаны источник задержки и завершающие этапы одной из ведущих цепочек. '
                'Переносы по цепочке не складываются.')
        if hidden:
            note += f' Ещё работ в этой цепочке: {hidden}; они доступны в подробном графике Монитора.'
        return rows, note
    # A PM may contain delayed jobs without a confirmed path to RNV. They are
    # useful operational facts, but must not be labelled the project's driver.
    available = [row for row in all_rows.values() if not row.get('actual_finish')
                 and ((row.get('own_delay_days') or 0) > 0
                      or (row.get('inherited_delay_days') or 0) > 0)]
    if available:
        own = max(available, key=lambda row: (row.get('own_delay_days') or 0,
                                              row.get('forecast_finish') or ''))
        inherited = max(available, key=lambda row: (row.get('inherited_delay_days') or 0,
                                                    row.get('forecast_finish') or ''))
        return list({row['id']: row for row in (own, inherited)}.values()), (
            'Показаны работы с наибольшей собственной и унаследованной задержкой. '
            'Их влияние на итоговый РНВ не подтверждено.')
    planned = [row for row in all_rows.values() if not row.get('actual_finish')
               and row.get('plan_start') and row.get('plan_finish')]
    if planned:
        return sorted(planned, key=lambda row: (row['plan_finish'], row['plan_start'], str(row['id'])),
                      reverse=True)[:3], (
            'Показаны работы с самыми поздними сроками исходного плана. '
            'Это не прогноз и не подтверждённая цепочка переноса РНВ.')
    return [], 'Подтверждённой цепочки переноса для отображения пока нет.'


def render(block: dict, *, context: str = 'monitor') -> str:
    """RNV text and physical evidence, without dependency drawings."""
    if context == 'report':
        import developaid_report_schedule as executive
        return executive.render(executive.model(block))
    from developaid_schedule_visual import styles, date_text, physical_summary
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    rnv = block.get('rnv') or {}
    state = rnv.get('state')
    gpr = rnv.get('basis') == 'gpr'
    forecast = (date_text(rnv.get('forecast')) if state == 'complete' and rnv.get('forecast')
                else date_text(rnv.get('forecast'))+' — оценка по ГПР' if state == 'estimate' and rnv.get('forecast')
                else 'неполный' if state == 'partial' else 'недостаточно данных')
    delta = rnv.get('delay_days')
    delay = (f'{delta:+g} дн.' if state in {'complete', 'partial', 'estimate'}
             and isinstance(delta, (int, float)) else 'не определён')
    out = [styles(), '<section class="dependency-timeline schedule-overview">',
           '<h3>РНВ и причины переноса срока</h3>',
           '<div class="schedule-rnv-cards"><div><span>'+esc(rnv.get('plan_label') or 'План РНВ')+'</span><strong>'+esc(date_text(rnv.get('plan_date') or rnv.get('approved')))+'</strong></div>',
           '<div class="'+('schedule-warning' if state != 'complete' else '')+'"><span>Прогноз РНВ</span><strong>'+esc(forecast)+'</strong></div>',
           '<div><span>Сдвиг РНВ'+(' по работам ГПР с прогнозом' if state == 'partial' and gpr else ' по известной части сети' if state == 'partial' else '')+'</span><strong>'+esc(delay)+'</strong></div></div>']
    if state == 'partial' and rnv.get('indicative_forecast'):
        out.append('<p class="schedule-note">'+('По работам ГПР с прогнозом: ' if gpr else 'По известной части сети: ')
                   +esc(date_text(rnv['indicative_forecast']))+'. Это не подтверждённый итоговый срок РНВ.</p>')
    chain = rnv.get('driving_chain') or []
    if gpr and chain:
        out.append('<p class="schedule-note"><b>Срок тянет работа:</b> «'+esc(chain[0].get('name') or '')+'»'
                   +(' — '+esc(chain[0]['reason']) if chain[0].get('reason') else '')+'</p>')
    reasons = rnv.get('reasons') or []
    for reason in reasons[:3]:
        out.append('<p class="schedule-note">'+esc(reason)+'</p>')
    if len(reasons) > 3:
        out.append('<details class="schedule-reasons"><summary>Все причины неполного прогноза ('+str(len(reasons))+')</summary>'+''.join('<p class="schedule-note">'+esc(reason)+'</p>' for reason in reasons[3:])+'</details>')
    # Owner's decision: no dependency drawing in Monitor or the summary. The
    # RNV cards, reasons, physical summary and calendar check stay; the chain
    # lanes and the technical network view are not drawn. The model (rows,
    # edges) stays in the cut. The work that drives the date is named as text.
    chain = rnv.get('driving_chain') or []
    if chain and not gpr:
        out.append('<p class="schedule-note"><b>Срок тянет:</b> '+esc(chain[-1].get('name') or '')+'</p>')
    out.append(physical_summary(block.get('physical'), include_covered=False))
    if not block.get('history'):
        out.append('<p class="schedule-note">Сравнение версий ГПР пока не рассчитано.</p>')
    confirmation = block.get('confirmation') or {}
    if confirmation.get('recorded_at'):
        calendar = ('Расчёт в календарных днях подтверждён.'
                    if confirmation.get('calendar_basis') == 'calendar_days' else 'Календарь не подтверждён.')
        chain = ('Полнота цепочки до РНВ подтверждена.'
                 if confirmation.get('rnv_chain_complete') else 'Полнота цепочки до РНВ не подтверждена.')
        out.append('<div class="schedule-confirmation-summary"><p class="schedule-note"><b>Проверка исходного графика</b> от '+esc(date_text(confirmation['recorded_at']))+'. '+esc(calendar+' '+chain)+'</p><p class="schedule-note">'+esc(confirmation.get('note'))+'</p></div>')
    out.append('</section>')
    return ''.join(out)
