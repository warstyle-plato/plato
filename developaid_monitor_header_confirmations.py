"""Private, source-bound administrator confirmations of cumulative header dates.

Original workbooks and immutable parsed snapshots are never rewritten. A date
confirmation applies only to the exact archive/file/sheet/cell/raw value.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import developaid_monitor as monitor

MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 6000
FIELDS = {'snapshot_id', 'file_sha256', 'filename', 'sheet', 'cell', 'raw'}
REQUIRED = {'binding', 'contract_date', 'confirmed_at', 'origin'}
OPTIONAL = {'note', 'previous'}
MAX_VERSIONS = 50
MAX_NOTE = 500


class ConfirmationProblem(ValueError):
    pass


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def binding(snapshot: dict, ledger: dict, evidence: dict) -> dict | None:
    source = ledger.get('source') or {}
    point = evidence.get('source') or {}
    result = {'snapshot_id': snapshot.get('snapshot_id'), 'file_sha256': ledger.get('file_sha256'),
              'filename': source.get('filename'), 'sheet': source.get('sheet'),
              'cell': point.get('cell'), 'raw': evidence.get('raw')}
    return result if _valid_binding(result) else None


def _valid_binding(result: dict) -> bool:
    if set(result) != FIELDS or not all(isinstance(v, str) and v for v in result.values()):
        return False
    if not (re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', result['snapshot_id'])
            and re.fullmatch(r'[0-9a-f]{64}', result['file_sha256'])
            and re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]{0,5}', result['cell'])):
        return False
    if len(result['filename']) > 240 or len(result['sheet']) > 200 or len(result['raw']) > 20_000:
        return False
    return True


def _check_version(version) -> None:
    """One dated decision: a date, or None for an explicit revocation."""
    if not isinstance(version, dict):
        raise ValueError
    date = version.get('contract_date')
    if date is not None and not _date(date):
        raise ValueError
    note = version.get('note', '')
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        raise ValueError
    stamp = dt.datetime.fromisoformat(version['confirmed_at'])
    if stamp.tzinfo is None:
        raise ValueError


def _versions(record: dict) -> list[dict]:
    current = {k: v for k, v in record.items() if k in {'contract_date', 'confirmed_at', 'note'}}
    return [*record.get('previous', []), current]


def _effective(record: dict, cut: str) -> dict | None:
    """The decision in force at the cut; a later correction is not backdated."""
    known = [v for v in _versions(record) if v['confirmed_at'][:10] <= cut]
    return known[-1] if known else None


def _key(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')).encode()).hexdigest()


def _path(project: str) -> Path:
    return monitor._project_dir(project) / 'cumulative_header_dates.json'


def _read(project: str) -> dict:
    path = _path(project)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError
        value = json.loads(path.read_bytes())
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise ConfirmationProblem('Уточнения дат шапок не прочитаны; проверьте частное хранилище проекта.') from None
    try:
        if set(value) != {'schema', 'confirmations'} or value['schema'] != 1 or not isinstance(value['confirmations'], dict):
            raise ValueError
        records = value['confirmations']
        if len(records) > MAX_RECORDS:
            raise ValueError
        for key, record in records.items():
            if (not isinstance(record, dict) or not REQUIRED <= set(record) <= REQUIRED | OPTIONAL
                    or not isinstance(record['binding'], dict) or not _valid_binding(record['binding'])
                    or _key(record['binding']) != key or record['origin'] != 'manual_confirmation'):
                raise ValueError
            previous = record.get('previous', [])
            if not isinstance(previous, list) or len(previous) > MAX_VERSIONS:
                raise ValueError
            for version in [*previous, record]:
                _check_version(version)
            # Only a correction may revoke; the first record is always a date.
            if record['contract_date'] is None and not previous:
                raise ValueError
        return records
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ConfirmationProblem('Уточнения дат шапок имеют неверный формат; они не применены.') from None


def apply(project: str, snapshot: dict, cut: str) -> dict:
    records = _read(project)
    result = dict(snapshot, ledgers=[])
    for original in snapshot.get('ledgers') or []:
        ledger = dict(original)
        # A caller can project an already effective view to an earlier cut or
        # after revocation. Always start from the preserved raw header value.
        if 'contract_date_original' in ledger:
            ledger['contract_date'] = ledger.pop('contract_date_original')
        ledger.pop('date_confirmation', None)
        ledger['identity_warnings'] = [warning for warning in ledger.get('identity_warnings') or []
            if warning not in {
                'Дата договора уточнена администратором по исходной ячейке; исходный текст не исправлен.',
                'Уточнения даты разных полей шапки противоречат друг другу.'}]
        matches = []
        for evidence in ledger.get('contract_date_evidence') or []:
            reference = binding(snapshot, ledger, evidence)
            if reference is not None and _key(reference) in records:
                record = records[_key(reference)]
                if record['binding'] == reference:
                    matches.append(record)
        if matches:
            ledger['contract_date_original'] = ledger.get('contract_date')
            effective = [(record, _effective(record, cut)) for record in matches]
            dates = {version['contract_date'] for _, version in effective if version}
            if len(dates) > 1:
                ledger['identity_warnings'] = [*(ledger.get('identity_warnings') or []),
                                              'Уточнения даты разных полей шапки противоречат друг другу.']
                ledger['contract_date'] = None
            else:
                record, version = next(((r, v) for r, v in effective if v), effective[0])
                applicable = version is not None
                shown = version or record
                ledger['date_confirmation'] = {**record, 'contract_date': shown['contract_date'],
                                               'confirmed_at': shown['confirmed_at'],
                                               'note': shown.get('note', ''),
                                               'revoked': applicable and shown['contract_date'] is None,
                                               'applicable_to_cut': applicable}
                if applicable and shown['contract_date'] is not None:
                    ledger['contract_date'] = shown['contract_date']
                    ledger['identity_warnings'] = [*(ledger.get('identity_warnings') or []),
                        'Дата договора уточнена администратором по исходной ячейке; исходный текст не исправлен.']
        result['ledgers'].append(ledger)
    return result


def confirm(project: str, snapshot: dict, *, filename: str, file_sha256: str,
            sheet: str, cell: str, raw: str, contract_date: str, note: str = '') -> dict:
    """Save, correct or revoke (empty date) one cell's date; history is kept."""
    revoke = contract_date == ''
    if not revoke and (not _date(contract_date) or contract_date > dt.date.today().isoformat()):
        raise ConfirmationProblem('Укажите действительную дату договора не позже текущей даты.')
    note = note.strip() if isinstance(note, str) else ''
    if len(note) > MAX_NOTE:
        raise ConfirmationProblem('Основание уточнения — не больше 500 знаков.')
    supplied = {'snapshot_id': snapshot.get('snapshot_id'), 'filename': filename,
                'file_sha256': file_sha256, 'sheet': sheet, 'cell': cell, 'raw': raw}
    references = [binding(snapshot, ledger, evidence) for ledger in snapshot.get('ledgers') or []
                  for evidence in ledger.get('contract_date_evidence') or []]
    if not _valid_binding(supplied) or supplied not in references:
        raise ConfirmationProblem('Исходная шапка не совпадает с выбранными архивом, файлом, листом, ячейкой и сырым текстом; уточнение не сохранено.')
    path = _path(project)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'w') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            records = _read(project)
            key = _key(supplied)
            existing = records.get(key)
            if existing is not None and existing['contract_date'] == (None if revoke else contract_date):
                return existing
            if existing is None and revoke:
                raise ConfirmationProblem('Для этой ячейки нет сохранённого уточнения; снимать нечего.')
            if existing is not None and not note:
                raise ConfirmationProblem('Укажите основание исправления или снятия уточнения: прежнее решение сохраняется в истории.')
            if existing is not None and len(existing.get('previous', [])) >= MAX_VERSIONS:
                raise ConfirmationProblem('У этой ячейки слишком много исправлений; проверьте хранилище.')
            if len(records) >= MAX_RECORDS:
                raise ConfirmationProblem('В проекте слишком много уточнений шапок; проверьте хранилище.')
            record = {'binding': supplied, 'contract_date': None if revoke else contract_date,
                      'confirmed_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'origin': 'manual_confirmation'}
            if note:
                record['note'] = note
            if existing is not None:
                record['previous'] = _versions(existing)
            records[key] = record
            data = json.dumps({'schema': 1, 'confirmations': records}, ensure_ascii=False).encode()
            if len(data) > MAX_BYTES:
                raise ConfirmationProblem('Уточнения шапок превышают допустимый размер; запись не сохранена.')
            temp_fd, temporary = tempfile.mkstemp(prefix='.header-date-', dir=path.parent)
            try:
                with os.fdopen(temp_fd, 'wb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary)
            return record
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
