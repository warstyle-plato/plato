"""Read-only completion evidence, independent of the remaining-plan task set.

Archived plans supply identity only. Their percentages and planned dates never
become completion evidence. Source positions are not whole GPR works.
"""
from __future__ import annotations

import hashlib
import json
import math

import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_cumulative_progress as cumulative


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def build(project, cut, snapshot, *, physical):
    """Return qualified works and separate completed source positions; no writes."""
    import developaid_schedule_versions as versions
    folder = monitor._project_dir(project)
    selected = monitor._baseline_state(project, cut)
    legacy = monitor._legacy_baseline_file(project)
    sources = {}
    if legacy is not None:
        sources[hashlib.sha256(legacy.read_bytes()).hexdigest()] = (legacy, '')
    for event in selected['versions']:
        if event['effective_from'] <= cut:
            sources.setdefault(event['source_sha256'], (folder/'baseline'/'schedule_sources'/
                (event['source_sha256']+'.xlsx'), event['effective_from']))
    identities, unresolved = {}, 0

    def source(sha, day):
        nonlocal unresolved
        if sha not in sources or sources[sha][1] > day:
            unresolved += 1
            return None
        if sha not in identities:
            path, _ = sources[sha]
            try:
                data = versions._read(path)
                if versions.digest(data) != sha:
                    raise ValueError('source digest')
                rows = monitor._read_baseline_gpr_bytes(data)['works']
                by_id, duplicate = {}, set()
                for row in rows:
                    key = str(row.get('id') or row.get('wbs') or '')
                    if key in by_id:
                        duplicate.add(key)
                    by_id[key] = row
                identities[sha] = {key: row for key, row in by_id.items() if key and key not in duplicate}
            except (OSError, ValueError, KeyError, TypeError):
                identities[sha] = None
        return identities[sha]

    manual = {}
    for path in sorted((folder/'work_fact').glob('*.json')):
        day = path.name.split('.', 1)[0]
        if not monitor._day(day) or day > cut:
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            sha = payload.get('source_sha256')
            if not sha:
                origin = monitor._baseline_state(project, day)
                sha = origin['source_sha256'] if origin['revision'] == 0 else ''
            old = source(sha, day)
            for row in payload.get('rows') or []:
                tid = str(row.get('id') or '')
                if old and tid in old:
                    manual[(sha, tid)] = (day, _number(row.get('progress')))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            unresolved += 1

    decisions = {}
    for event in physical._history(project):
        if event['recorded_at'][:10] <= cut:
            decisions[event['source_sha256']] = event
    candidates, blockers = {}, {}

    def fact(sha, tid, day, origin, actual_finish=None, sid=None, qualified_at=None):
        old = source(sha, qualified_at or day)
        if not old or tid not in old:
            return None
        row = old[tid]
        return {'fact_id': 'gpr:'+sha+':'+tid, 'scope_kind': 'confirmed_work',
                'name': row.get('name') or tid, 'object': row.get('object') or '',
                'section': row.get('section') or '', 'source_sha256': sha,
                'source_task_id': tid, 'progress': 1.0, 'origin': origin,
                'observed_complete_by': day, 'actual_finish': actual_finish,
                'source': {'kind': 'gpr_fact', 'snapshot_id': sid,
                           'recorded_day': qualified_at or day, 'cells': row.get('source_cells')}}

    for key, (day, value) in manual.items():
        if value is not None and abs(value-1) <= 1e-7:
            candidate = fact(*key, day, 'manual')
            if candidate:
                candidates[key] = candidate
        elif value is not None:
            blockers[key] = max(blockers.get(key, ''), day)
    for sha, event in decisions.items():
        day, config = event['recorded_at'][:10], event['configuration']
        old = source(sha, day)
        if not old:
            continue
        try:
            basis = snapshot
            if config['components'] and (snapshot or {}).get('snapshot_id') != event['snapshot_id']:
                previous = ledgers.effective_snapshot(project, cut,
                    snapshot=ledgers.read_snapshot(project, event['snapshot_id']))
                config = cumulative.project_configuration(previous, snapshot, config)
                if config is None:
                    continue
            allowed = [task for task in config['tasks'] if task['scope_confirmed']
                       and task['mode'] in {'quantities', 'completed'}]
            config = dict(config, tasks=allowed, components=[c for c in config['components']
                if c['task_id'] in {t['task_id'] for t in allowed}])
            measured = physical.evaluate({'tasks': {tid: {'task_id': tid,
                'name': row.get('name') or tid, 'object': row.get('object') or ''}
                for tid, row in old.items()}}, basis, config, cut)
            for task in measured['tasks']:
                tid, value = task['task_id'], _number(task.get('progress'))
                if task.get('mode') not in {'quantities', 'completed'} or not task['scope_confirmed']:
                    continue
                key = sha, tid
                if value is not None and abs(value-1) <= 1e-7 and not task.get('requires_reconciliation'):
                    actual = task.get('actual_finish') if task['mode'] == 'completed' else None
                    observed = task.get('progress_date') or cumulative.snapshot_date(basis) or day
                    candidate = fact(sha, tid, observed, 'confirmed_completion' if actual else
                                     'cumulative_quantities', actual, (basis or {}).get('snapshot_id'), day)
                    if candidate:
                        candidates[key] = candidate
                elif value is not None or task.get('requires_reconciliation'):
                    blockers[key] = max(blockers.get(key, ''), day)
        except (OSError, ValueError, KeyError, TypeError):
            unresolved += 1

    # The same work under several plan versions (code, name, object, section
    # and WBS unchanged) is one fact. A later partial reading in another
    # version does not let the earlier hundred percent stand.
    def work(key):
        row = (identities.get(key[0]) or {}).get(key[1])
        return physical.definition(row) if row else key
    later = {}
    for key, day in blockers.items():
        later[work(key)] = max(later.get(work(key), ''), day)
    chosen = {}
    for key, value in candidates.items():
        if key in blockers or later.get(work(key), '') > value['source']['recorded_day']:
            continue
        rank = lambda f: (not f['actual_finish'], f['actual_finish'] or f['observed_complete_by'], f['fact_id'])
        best = chosen.get(work(key))
        if best is None or rank(value) < rank(best):
            chosen[work(key)] = value
    works = list(chosen.values())

    snapshots = {}
    for meta in ledgers.list_snapshots(project):
        sid = meta.get('snapshot_id') or ''
        if sid[:10] <= cut:
            snapshots[sid] = None
    if snapshot:
        snapshots[snapshot['snapshot_id']] = snapshot
    positions = {}
    for sid, basis in sorted(snapshots.items()):
        try:
            basis = basis or ledgers.effective_snapshot(project, cut,
                snapshot=ledgers.read_snapshot(project, sid))
            day = cumulative.snapshot_date(basis)
            if not day or day > cut:
                continue
            views = cumulative.quantity_views(basis, cut)
            eligible = {id(row) for row in ledgers.aggregation_members(list(views.values()))}
            for key, row in views.items():
                if id(row) not in eligible or (row.get('duplicate_marker_present') and not row.get('is_duplicate')):
                    continue
                identity = row.get('position_key') or sid+':'+key
                ratio = _number(row.get('completion_ratio'))
                if ratio is None:
                    ratio = _number(row.get('reported_completion_ratio'))
                plan = _number(row.get('plan_quantity'))
                positions[identity] = (None if not (plan and plan > 0 and row.get('unit')
                    and ratio is not None and abs(ratio-1) <= 1e-7) else {
                        'fact_id': 'ks:'+identity, 'scope_kind': 'ks_position',
                        'name': row.get('name') or key, 'object': row.get('scope') or '',
                        'contractor': row.get('contractor'), 'contract': row.get('contract'),
                        'source_sha256': basis.get('sha256') or sid[11:], 'source_task_id': None,
                        'progress': 1.0, 'origin': 'cumulative_position',
                        'observed_complete_by': day, 'actual_finish': None,
                        'source': {'kind': 'ks', 'snapshot_id': sid, 'item_id': key,
                                   'cells': row.get('source')}, 'unit': row['unit']})
        except (OSError, ValueError, KeyError, TypeError):
            unresolved += 1
    leaves = [row for row in positions.values() if row]
    return {'qualified_task_completions': sorted(works, key=lambda f: (f['observed_complete_by'], f['fact_id'])),
            'completed_ks_positions': leaves,
            'counts': {'confirmed_works': len(works), 'ks_positions': len(leaves), 'unresolved_sources': unresolved},
            'overall_progress': None,
            'reason': 'Завершённые позиции КС не равны целым работам ГПР. Общая готовность проекта по оставшимся работам не рассчитана.'}


def render(inventory, *, expanded=False):
    """Compact actual markers for whole works; source leaves stay in source views."""
    import html
    esc = lambda value: html.escape(str(value or ''), quote=True)
    works = (inventory or {}).get('qualified_task_completions') or []
    counts = (inventory or {}).get('counts') or {}
    if not works and not counts.get('ks_positions'):
        return ''
    def marker(fact):
        actual, observed = fact.get('actual_finish'), fact.get('observed_complete_by')
        date = actual or observed
        label = ('Завершено ' if actual else '100% на дату ') + str(date or '')
        return ('<li class="completed-work-marker" data-fact-id="'+esc(fact['fact_id'])+'">'
                '<span>'+esc(' · '.join(filter(None, [fact.get('object'), fact.get('name')])))+'</span> '
                '<span class="completed-actual-point" data-date="'+esc(date)+'" '
                'data-date-basis="'+('actual_finish' if actual else 'observed_complete_by')+'">● '+esc(label)+'</span></li>')
    out = ['<style>.completed-work-marker{margin:8px 0;overflow-wrap:anywhere}'
           '.completed-actual-point{display:block;color:#17623b;font-weight:600}</style>',
           '<section class="completed-work-facts"><h3>Подтверждённое выполнение</h3>']
    if works:
        out.append('<p>Завершённых работ с подтверждённым составом: '+str(len(works))+'.</p>')
        out.append('<ul>'+''.join(marker(fact) for fact in (works if expanded else works[:3]))+'</ul>')
        if len(works) > 3 and not expanded:
            out.append('<details><summary>Ещё завершённых работ: '+str(len(works)-3)+'</summary><ul>'+
                       ''.join(marker(fact) for fact in works[3:])+'</ul></details>')
    if counts.get('ks_positions'):
        out.append('<p>Позиций КС с выполненным объёмом: '+str(counts['ks_positions'])+
                   '. Это позиции ведомостей, а не число завершённых работ ГПР. Подробности — в договорах.</p>')
    out.append('<p class="schedule-note">Готовность всего проекта: нет полной сопоставимой базы.</p></section>')
    return ''.join(out)
