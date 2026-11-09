"""Immutable approved schedule sources with an atomic, cross-worker revision log."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

MAX_BYTES = 20 * 1024 * 1024
MAX_VERSIONS = 500
_SHA = re.compile(r'[0-9a-f]{64}')


class ScheduleVersionConflict(ValueError):
    pass


def _day(value):
    try:
        day = dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError('Укажите существующую дату начала действия плана.') from None
    if day.isoformat() != value:
        raise ValueError('Дата начала действия плана нужна в формате ГГГГ-ММ-ДД.')
    return day


def _now():
    return dt.datetime.now(dt.timezone.utc)


def digest(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Выберите непустой файл ГПР размером до 20 МБ.')
    return hashlib.sha256(data).hexdigest()


def _read(path):
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES+1)
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Сохранённый исходник ГПР пуст или превышает допустимый размер.')
    return data


def _legacy(path):
    return digest(_read(path)) if path is not None else ''


def _journal(folder: Path, legacy_sha: str):
    path = folder/'schedule_versions.json'
    if not path.exists():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        events = payload['versions']
        if (payload.get('schema') != 1 or not isinstance(events, list)
                or len(events) > MAX_VERSIONS):
            raise ValueError
        previous, last_day = legacy_sha, ''
        for number, event in enumerate(events, 1):
            if (not isinstance(event, dict)
                    or type(event.get('revision')) is not int or event['revision'] != number
                    or not _SHA.fullmatch(event.get('source_sha256') or '')
                    or event.get('previous_source_sha256') != previous
                    or event.get('baseline_scope', 'full_schedule') not in {'full_schedule','remaining_work'}
                    or _day(event['effective_from']).isoformat() < last_day
                    or dt.datetime.fromisoformat(event['approved_at']).utcoffset() != dt.timedelta(0)):
                raise ValueError
            previous, last_day = event['source_sha256'], event['effective_from']
        owners = payload.get('owner_decisions', [])
        if not isinstance(owners, list) or len(owners) > MAX_VERSIONS:
            raise ValueError
        last_day = ''
        for number, owner in enumerate(owners, 1):
            if (not isinstance(owner, dict) or type(owner.get('revision')) is not int or owner['revision'] != number
                    or owner.get('source') != 'owner_decision'
                    or _day(owner['effective_from']).isoformat() < last_day
                    or _day(owner['date']).isoformat() != owner['date']
                    or not isinstance(owner.get('note'), str) or not owner['note'].strip()
                    or len(owner['note']) > 1000
                    or owner['effective_from'] < owner['recorded_at'][:10]
                    or dt.datetime.fromisoformat(owner['recorded_at']).utcoffset() != dt.timedelta(0)):
                raise ValueError
            last_day = owner['effective_from']
        return events, owners
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('История утверждённых версий ГПР не читается. Обратитесь к администратору.') from None


def state(folder: Path, legacy: Path | None, cut: str = ''):
    """No process cache: both workers observe the same committed log."""
    legacy_sha = _legacy(legacy)
    events, owners = _journal(folder, legacy_sha)
    if cut:
        _day(cut)
    applicable = [event for event in events if not cut or event['effective_from'] <= cut]
    event = applicable[-1] if applicable else None
    active_owners = [owner for owner in owners if not cut or owner['effective_from'] <= cut]
    path = folder/'schedule_sources'/f"{event['source_sha256']}.xlsx" if event else legacy
    if event and digest(_read(path)) != event['source_sha256']:
        raise ValueError('Отпечаток сохранённой версии ГПР не совпадает с утверждённым.')
    return {'path': path, 'source_sha256': event['source_sha256'] if event else legacy_sha,
            'revision': event['revision'] if event else 0,
            'effective_from': event['effective_from'] if event else '',
            'approved_at': event['approved_at'] if event else '',
            'latest_source_sha256': events[-1]['source_sha256'] if events else legacy_sha,
            'latest_effective_from': events[-1]['effective_from'] if events else '',
            'versions': events,
            'baseline_scope': event.get('baseline_scope', 'full_schedule') if event else 'full_schedule',
            'latest_baseline_scope': events[-1].get('baseline_scope', 'full_schedule') if events else 'full_schedule',
            'owner_rnv': active_owners[-1] if active_owners else None,
            'owner_rnv_revision': len(owners), 'owner_decisions': owners}


def accepts_fact(folder: Path, legacy: Path | None, cut: str, fact_day: str,
                 source_sha256: str = '', *, selected=None, origin=None):
    """Unknown legacy fact identities never migrate to a new plan with equal IDs."""
    selected = selected if selected is not None else state(folder, legacy, cut)
    if source_sha256:
        return source_sha256 == selected['source_sha256']
    origin = origin if origin is not None else state(folder, legacy, fact_day)
    return selected['revision'] == 0 and origin['revision'] == 0


@contextlib.contextmanager
def lock(folder: Path):
    import fcntl
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'.schedule_versions.lock').open('a+b') as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _atomic(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(prefix='.schedule-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def approve(folder: Path, legacy: Path | None, data: bytes, *, expected_previous_sha256: str,
            expected_source_sha256: str, effective_from: str, author: str = '',
            owner_rnv_date=None, owner_rnv_note=None, expected_owner_rnv_revision=None,
            baseline_scope=None):
    source_sha = digest(data)
    if not _SHA.fullmatch(expected_previous_sha256 or '') or not _SHA.fullmatch(expected_source_sha256 or ''):
        raise ValueError('Сначала проверьте выбранную версию ГПР перед утверждением.')
    if source_sha != expected_source_sha256:
        raise ScheduleVersionConflict('Файл изменился после проверки. Проверьте его заново.')
    day = _day(effective_from)
    owner_requested = owner_rnv_date is not None
    if owner_requested:
        _day(owner_rnv_date)
        if not isinstance(owner_rnv_note, str) or not owner_rnv_note.strip() or len(owner_rnv_note) > 1000:
            raise ValueError('Укажите основание плановой даты РНВ владельца (до 1000 знаков).')
    elif owner_rnv_note is not None:
        raise ValueError('Для решения владельца нужна плановая дата РНВ.')
    if baseline_scope is not None and baseline_scope not in {'full_schedule','remaining_work'}:
        raise ValueError('Укажите полный план или план оставшихся работ.')
    now = _now()
    if day < now.date():
        raise ValueError('Новая версия может действовать с сегодняшней или будущей даты; прежние срезы сохраняются.')
    with lock(folder):
        now = _now()
        if day < now.date():
            raise ValueError('Новая версия или решение владельца не могут менять прошлые срезы.')
        current = state(folder, legacy)
        if not current['source_sha256']:
            raise ValueError('Сначала загрузите первый утверждённый план проекта.')
        if current['latest_source_sha256'] != expected_previous_sha256:
            raise ScheduleVersionConflict('Утверждённый план уже изменён другим запросом. Проверьте новую версию заново.')
        if owner_requested and (type(expected_owner_rnv_revision) is not int
                or expected_owner_rnv_revision != current['owner_rnv_revision']):
            raise ScheduleVersionConflict('Решение о плановой дате РНВ уже изменено. Проверьте его заново.')
        if (source_sha != expected_previous_sha256 and current['latest_effective_from']
                and effective_from < current['latest_effective_from']):
            raise ValueError('Дата новой версии не может быть раньше уже утверждённой следующей версии.')
        source_changed = source_sha != expected_previous_sha256
        if not source_changed and baseline_scope is not None and baseline_scope != current['latest_baseline_scope']:
            raise ValueError('Изменение состава плана требует утверждения новой версии исходного файла.')
        owners = current['owner_decisions']
        if owner_requested and owners and effective_from < owners[-1]['effective_from']:
            raise ValueError('Дата действия решения не может быть раньше уже записанного следующего решения владельца.')
        same_owner = bool(owners and owner_requested and owners[-1]['date'] == owner_rnv_date
                          and owners[-1]['note'] == owner_rnv_note.strip()
                          and owners[-1]['effective_from'] == effective_from)
        owner_changed = owner_requested and not same_owner
        if not source_changed and not owner_changed:
            return dict(current, unchanged=True)
        if owner_changed and len(owners) >= MAX_VERSIONS:
            raise ValueError('Достигнут предел решений владельца. Обратитесь к администратору.')
        events = current['versions']
        if source_changed and len(events) >= MAX_VERSIONS:
            raise ValueError('Достигнут предел версий ГПР. Обратитесь к администратору.')
        if source_changed:
            sources = folder/'schedule_sources'
            sources.mkdir(exist_ok=True)
            path = sources/f'{source_sha}.xlsx'
            if path.exists():
                if digest(_read(path)) != source_sha:
                    raise ValueError('Сохранённый исходник версии ГПР повреждён.')
            else:
                _atomic(path, data)
            event = {'revision': len(events)+1, 'source_sha256': source_sha,
                     'previous_source_sha256': expected_previous_sha256,
                     'effective_from': effective_from, 'approved_at': now.isoformat(),
                     'author': str(author or '')[:200],
                     'baseline_scope': baseline_scope or current['latest_baseline_scope']}
            events = [*events, event]
        if owner_changed:
            owners = [*owners, {'revision': len(owners)+1, 'source': 'owner_decision',
                'date': owner_rnv_date, 'effective_from': effective_from,
                'recorded_at': now.isoformat(), 'note': owner_rnv_note.strip(),
                'author': str(author or 'administrator')[:200]}]
        _atomic(folder/'schedule_versions.json', json.dumps(
            {'schema': 1, 'versions': events, 'owner_decisions': owners}, ensure_ascii=False).encode())
        return dict(state(folder, legacy), unchanged=False)
