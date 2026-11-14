"""Private source-bound owner decisions for otherwise blank FM bank codes.

Amounts always come from reconciled workbook formula sources. Decisions only
classify selected immutable source cells; they neither amend XLSX nor cover a
deficit. Append-only events have a global revision and historical cut fence.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import re
import tempfile
import copy
from contextlib import contextmanager
from pathlib import Path

import developaid_monitor as monitor

_QUALIFIED_CACHE = {}


class AllocationProblem(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now():
    return dt.datetime.now(dt.timezone.utc)


def source_cell_id(source_sha256: str, sheet: str, row: int, bank_column: int, amount_column: int) -> str:
    return hashlib.sha256(json.dumps([source_sha256, sheet, row, bank_column, amount_column],
                                    ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _folder(project):
    return monitor._project_dir(project) / 'finance_allocations'


@contextmanager
def source_lock(project):
    """Shared by allocation commits and the normal baseline replacement path."""
    try:
        import fcntl
    except ImportError:
        raise AllocationProblem('Сохранение банковского отнесения недоступно в этой среде.', 503) from None
    folder = _folder(project)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    with (folder / '.lock').open('a') as lock:
        os.chmod(folder / '.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield folder


def _source(project):
    return (monitor._project_dir(project) / 'baseline' / 'finance.xlsx').read_bytes()


def _events(project):
    events = []
    for revision, path in enumerate(sorted(_folder(project).glob('[0-9]*.json')), 1):
        e = json.loads(path.read_text())
        if (set(e) != {'revision', 'source_sha256', 'assignments', 'basis', 'actor', 'note', 'recorded_at'}
                or type(e.get('revision')) is not int or e['revision'] != revision or path.stem != f'{revision:012d}'
                or not re.fullmatch(r'[0-9a-f]{64}', e.get('source_sha256', ''))
                or e.get('basis') != 'owner_instruction' or e.get('actor') != 'administrator'
                or not isinstance(e.get('note'), str) or not e['note'].strip()
                or not isinstance(e.get('assignments'), list) or not e['assignments']
                or dt.datetime.fromisoformat(e['recorded_at']).utcoffset() != dt.timedelta(0)):
            raise ValueError('invalid finance allocation history')
        seen = set()
        for item in e['assignments']:
            if (set(item) != {'row_id', 'bank_code'} or item['row_id'] in seen
                    or not re.fullmatch(r'[0-9a-f]{64}', item['row_id'])
                    or not re.fullmatch(r'(?:[123](?:\.[0-9]+)+)?', item['bank_code'])):
                raise ValueError('invalid finance allocation record')
            seen.add(item['row_id'])
        events.append(e)
    return events


def active(project, sha, cut=''):
    day = dt.date.fromisoformat(cut) if cut else _now().date()
    events = _events(project)
    assignments = {}
    for e in events:
        if e['source_sha256'] != sha or dt.datetime.fromisoformat(e['recorded_at']).date() > day:
            continue
        for item in e['assignments']:
            if item['bank_code']:
                assignments[item['row_id']] = {**item, 'revision': e['revision'], 'basis': e['basis'],
                    'actor': e['actor'], 'recorded_at': e['recorded_at'], 'note': e['note'], 'source_sha256': sha}
            else:
                assignments.pop(item['row_id'], None)
    return {'source_sha256': sha, 'revision': events[-1]['revision'] if events else 0,
            'assignments': assignments, 'cut': day.isoformat()}


def candidates(model):
    """Only proven FACT source cells with an actually blank original bank cell."""
    rows = {}
    sha = (model.get('budget_composition') or {}).get('source_sha256', '')
    for item in (model.get('budget_composition') or {}).get('admin_items', []):
        allocation = item.get('money_allocation') or {}
        if (allocation.get('known_fields') or {}).get('fact') is not True:
            continue
        for proof in allocation.get('proofs', []):
            if proof.get('field') != 'fact':
                continue
            for source in proof.get('sources', []):
                if not source.get('raw_bank_missing'):
                    continue
                identifier = source_cell_id(sha, source['sheet'], source['row'],
                                            source['bank_column'], source['amount_column'])
                row = {'row_id': identifier, 'sheet': source['sheet'], 'row': source['row'],
                       'bank_column': source['bank_column'], 'amount_column': source['amount_column'],
                       'model_code': item['code'], 'model_amount': source['amount'], 'month': proof['month']}
                if identifier in rows and rows[identifier] != row:
                    raise ValueError('ambiguous source cell')
                rows[identifier] = row
    return list(rows.values())


def _read_model(raw, assignments=None):
    import developaid_monitor_dashboard as dashboard
    stream = io.BytesIO(raw)
    stream.name = 'source.xlsx'
    return dashboard._read_finance_baseline(stream, bank_assignments=assignments)


def view(project, cut=''):
    raw = _source(project)
    sha = hashlib.sha256(raw).hexdigest()
    state = active(project, sha, cut)
    model = _read_model(raw)
    rows = candidates(model)
    for row in rows:
        row['decision'] = state['assignments'].get(row['row_id'])
    return {**state, 'rows': rows, 'can_edit': state['cut'] == _now().date().isoformat(),
            'basis': 'owner_instruction'}


def apply(project, source_sha256, revision, assignments, note, cut=''):
    if cut and cut != _now().date().isoformat():
        raise AllocationProblem('Решение сохраняется на текущую дату; исторический срез не изменяется.', 409)
    if type(revision) is not int or revision < 0:
        raise AllocationProblem('Неверная ревизия решения.')
    if not isinstance(note, str) or not note.strip() or len(note) > 1000:
        raise AllocationProblem('Укажите решение владельца и основание (до 1000 знаков).')
    if not isinstance(assignments, list) or not 1 <= len(assignments) <= 1000:
        raise AllocationProblem('Выберите от 1 до 1000 конкретных строк источника.')
    normalized, seen = [], set()
    for item in assignments:
        if (not isinstance(item, dict) or set(item) != {'row_id', 'bank_code'}
                or not isinstance(item['row_id'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['row_id'])
                or not isinstance(item['bank_code'], str)
                or not re.fullmatch(r'(?:[123](?:\.[0-9]+)+)?', item['bank_code']) or item['row_id'] in seen):
            raise AllocationProblem('Передайте уникальные строки и банковские коды без изменения денежных сумм.')
        seen.add(item['row_id'])
        normalized.append(dict(item))
    with source_lock(project) as folder:
        raw = _source(project)
        sha = hashlib.sha256(raw).hexdigest()
        state = active(project, sha)
        if source_sha256 != sha or revision != state['revision']:
            raise AllocationProblem('Финансовая модель или решение изменились. Перечитайте строки.', 409)
        eligible = {row['row_id'] for row in candidates(_read_model(raw))}
        if not seen <= eligible:
            raise AllocationProblem('Выбранные строки не являются подтверждёнными АХР с пустым кодом банка.', 409)
        if hashlib.sha256(_source(project)).hexdigest() != sha:
            raise AllocationProblem('Финансовая модель изменилась во время проверки.', 409)
        event = {'revision': revision + 1, 'source_sha256': sha, 'assignments': normalized,
                 'basis': 'owner_instruction', 'actor': 'administrator', 'note': note.strip(),
                 'recorded_at': _now().isoformat()}
        fd, temporary = tempfile.mkstemp(prefix='.event-', dir=folder)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(event, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, folder / f'{revision + 1:012d}.json')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if hashlib.sha256(_source(project)).hexdigest() != sha:
            raise AllocationProblem('Источник изменился. Решение сохранено только для прежнего SHA и к новому файлу не применяется.', 409)
    return view(project)


def qualify(project, model, cut=''):
    """Bind decisions to exactly the workbook bytes used by all consumers."""
    sha = (model.get('budget_composition') or {}).get('source_sha256', '')
    if not sha:
        return model
    try:
        state = active(project, sha, cut)
        if not state['assignments']:
            return model
        raw = _source(project)
        if hashlib.sha256(raw).hexdigest() != sha:
            return dict(model, allocation_problem='Версия ФМ изменилась; решение владельца не применено.')
        fingerprint = hashlib.sha256(json.dumps(state['assignments'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        key = (project, sha, fingerprint)
        if key not in _QUALIFIED_CACHE:
            if len(_QUALIFIED_CACHE) >= 8:
                _QUALIFIED_CACHE.clear()
            _QUALIFIED_CACHE[key] = _read_model(raw, state['assignments'])
        result = copy.deepcopy(_QUALIFIED_CACHE[key])
        result['source'] = model.get('source', result.get('source'))
        result['owner_allocation_revision'] = state['revision']
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return dict(model, allocation_problem='Решение владельца не применено: ФМ или история решений недоступны.')
