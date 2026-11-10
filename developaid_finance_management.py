"""Source-bound management article for all recognised economic admin expenses.

This overlay never changes original bank codes, monetary allocations or money.
It applies one owner decision to TOTAL, FACT and PLAN of the same FM rows.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import developaid_finance_allocations as bank_allocations
import developaid_monitor as monitor

AllocationProblem = bank_allocations.AllocationProblem
SCOPE = 'all_economic_admin_total_fact_plan'
ARTICLE = '2.6'


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _folder(project):
    return monitor._project_dir(project) / 'finance_management'


def _source(project):
    return (monitor._project_dir(project) / 'baseline' / 'finance.xlsx').read_bytes()


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _events(project):
    events = []
    required = {'schema', 'revision', 'source_sha256', 'scope', 'management_article',
                'item_ids', 'basis', 'actor', 'note', 'recorded_at'}
    for revision, path in enumerate(sorted(_folder(project).glob('[0-9]*.json')), 1):
        event = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(event, dict):
            raise ValueError('invalid management allocation history')
        recorded = dt.datetime.fromisoformat(event.get('recorded_at', ''))
        ids = event.get('item_ids')
        if (set(event) != required or type(event.get('schema')) is not int or event['schema'] != 1
                or type(event.get('revision')) is not int or event['revision'] != revision
                or path.stem != f'{revision:012d}' or not _digest(event.get('source_sha256'))
                or event.get('scope') != SCOPE or event.get('management_article') not in ('', ARTICLE)
                or event.get('basis') != 'owner_instruction' or event.get('actor') != 'administrator'
                or not isinstance(event.get('note'), str) or not event['note'].strip()
                or len(event['note']) > 1000 or recorded.utcoffset() != dt.timedelta(0)
                or not isinstance(ids, list) or not 1 <= len(ids) <= 1000
                or any(not _digest(item) for item in ids) or len(set(ids)) != len(ids)):
            raise ValueError('invalid management allocation history')
        events.append(event)
    return events


def active(project, source_sha256, cut=''):
    day = dt.date.fromisoformat(cut) if cut else _now().date()
    events = _events(project)
    applicable = [event for event in events if event['source_sha256'] == source_sha256
                  and dt.datetime.fromisoformat(event['recorded_at']).date() <= day]
    return {'source_sha256': source_sha256, 'revision': events[-1]['revision'] if events else 0,
            'scope': SCOPE, 'cut': day.isoformat(), 'decision': applicable[-1] if applicable else None}


def _item_id(source_sha256, item):
    source = item.get('source') or {}
    code, sheet, row = item.get('code'), source.get('sheet'), source.get('row')
    if (not isinstance(code, str) or not code or not isinstance(sheet, str) or not sheet
            or type(row) is not int or row < 1):
        raise ValueError('unqualified economic admin source row')
    raw = json.dumps([source_sha256, 'economic_admin', code, sheet, row], ensure_ascii=False,
                     separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def candidates(model):
    composition = model.get('budget_composition') or {}
    source_sha256 = composition.get('source_sha256')
    if not _digest(source_sha256):
        return []
    result, seen = [], set()
    for item in composition.get('admin_items') or []:
        identifier = _item_id(source_sha256, item)
        if identifier in seen:
            raise ValueError('duplicate economic admin source row')
        seen.add(identifier)
        allocation = item.get('money_allocation') or {}
        result.append({'item_id': identifier, 'code': item['code'], 'source': dict(item['source']),
                       'bank_source_chapters': sorted((allocation.get('by_chapter') or {}).keys()),
                       'scope': ['total', 'fact', 'plan']})
    return result


def view(project, cut=''):
    try:
        raw = _source(project)
    except OSError as exc:
        raise AllocationProblem('В проекте нет доступной финансовой модели.', 503) from exc
    source_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        state = active(project, source_sha256, cut)
        rows = candidates(bank_allocations._read_model(raw))
    except (ValueError, KeyError, TypeError) as exc:
        raise AllocationProblem('История управленческого отнесения или строки АХР не подтверждены.', 503) from exc
    return {**state, 'rows': rows, 'can_edit': state['cut'] == _now().date().isoformat(),
            'basis': 'owner_instruction', 'money_changed': False, 'bank_sources_changed': False}


def apply(project, source_sha256, revision, item_ids, management_article, note, cut=''):
    if cut and cut != _now().date().isoformat():
        raise AllocationProblem('Решение сохраняется на текущую дату; исторический срез не изменяется.', 409)
    if (not _digest(source_sha256) or type(revision) is not int or revision < 0
            or management_article not in ('', ARTICLE) or not isinstance(item_ids, list)
            or not 1 <= len(item_ids) <= 1000 or any(not _digest(item) for item in item_ids)
            or len(set(item_ids)) != len(item_ids)):
        raise AllocationProblem('Передайте все распознанные строки АХР и управленческую статью 2.6.')
    if not isinstance(note, str) or not note.strip() or len(note) > 1000:
        raise AllocationProblem('Укажите решение владельца и основание (до 1000 знаков).')
    with bank_allocations.source_lock(project):
        raw = _source(project)
        source_sha = hashlib.sha256(raw).hexdigest()
        try:
            state = active(project, source_sha)
            eligible = {row['item_id'] for row in candidates(bank_allocations._read_model(raw))}
        except (ValueError, KeyError, TypeError) as exc:
            raise AllocationProblem('Источник или история управленческого отнесения не подтверждены.', 503) from exc
        if source_sha256 != source_sha or revision != state['revision']:
            raise AllocationProblem('Финансовая модель или решение изменились. Перечитайте строки.', 409)
        if not eligible or set(item_ids) != eligible:
            raise AllocationProblem('Решение должно относиться ко всем распознанным экономическим строкам АХР.', 409)
        if hashlib.sha256(_source(project)).hexdigest() != source_sha:
            raise AllocationProblem('Финансовая модель изменилась во время проверки.', 409)
        event = {'schema': 1, 'revision': revision + 1, 'source_sha256': source_sha,
                 'scope': SCOPE, 'management_article': management_article,
                 'item_ids': sorted(item_ids), 'basis': 'owner_instruction', 'actor': 'administrator',
                 'note': note.strip(), 'recorded_at': _now().isoformat()}
        folder = _folder(project)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.event-', dir=folder)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(event, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / f'{revision + 1:012d}.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if hashlib.sha256(_source(project)).hexdigest() != source_sha:
            raise AllocationProblem('Источник изменился. Решение сохранено только для прежнего SHA.', 409)
    return view(project)


def qualify(project, model, cut=''):
    composition = model.get('budget_composition') or {}
    source_sha = composition.get('source_sha256')
    if not _digest(source_sha):
        return model
    try:
        state = active(project, source_sha, cut)
        event = state['decision']
        if not event or not event['management_article']:
            return model
        ids = {row['item_id'] for row in candidates(model)}
        if not ids or ids != set(event['item_ids']):
            raise ValueError('management source membership changed')
        if hashlib.sha256(_source(project)).hexdigest() != source_sha:
            raise ValueError('management source changed')
        result = copy.deepcopy(model)
        comp = result['budget_composition']
        comp['management_allocation'] = {**event, 'state': 'active', 'money_changed': False,
                                         'bank_sources_changed': False}
        admin_keys = {(item['code'], item['source']['sheet'], item['source']['row'])
                      for item in comp.get('admin_items') or []}
        for items in (comp.get('admin_items') or [], comp.get('budget_items') or []):
            for item in items:
                source = item.get('source') or {}
                if (item.get('code'), source.get('sheet'), source.get('row')) in admin_keys:
                    item.update(management_article=ARTICLE, management_article_origin='owner_instruction',
                                management_policy_revision=event['revision'])
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return dict(model, management_allocation_problem=
                    'Управленческая статья АХР не применена: источник или история решений недоступны.')
