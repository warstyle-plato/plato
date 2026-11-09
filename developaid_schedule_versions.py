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


def _events(folder: Path, legacy_sha: str):
    path = folder/'schedule_versions.json'
    if not path.exists():
        return []
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
                    or _day(event['effective_from']).isoformat() < last_day
                    or dt.datetime.fromisoformat(event['approved_at']).utcoffset() != dt.timedelta(0)):
                raise ValueError
            previous, last_day = event['source_sha256'], event['effective_from']
        return events
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('История утверждённых версий ГПР не читается. Обратитесь к администратору.') from None


def state(folder: Path, legacy: Path | None, cut: str = ''):
    """No process cache: both workers observe the same committed log."""
    legacy_sha = _legacy(legacy)
    events = _events(folder, legacy_sha)
    if cut:
        _day(cut)
    applicable = [event for event in events if not cut or event['effective_from'] <= cut]
    event = applicable[-1] if applicable else None
    path = folder/'schedule_sources'/f"{event['source_sha256']}.xlsx" if event else legacy
    if event and digest(_read(path)) != event['source_sha256']:
        raise ValueError('Отпечаток сохранённой версии ГПР не совпадает с утверждённым.')
    return {'path': path, 'source_sha256': event['source_sha256'] if event else legacy_sha,
            'revision': event['revision'] if event else 0,
            'effective_from': event['effective_from'] if event else '',
            'approved_at': event['approved_at'] if event else '',
            'latest_source_sha256': events[-1]['source_sha256'] if events else legacy_sha,
            'latest_effective_from': events[-1]['effective_from'] if events else '',
            'versions': events}


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
            expected_source_sha256: str, effective_from: str, author: str = ''):
    source_sha = digest(data)
    if not _SHA.fullmatch(expected_previous_sha256 or '') or not _SHA.fullmatch(expected_source_sha256 or ''):
        raise ValueError('Сначала проверьте выбранную версию ГПР перед утверждением.')
    if source_sha != expected_source_sha256:
        raise ScheduleVersionConflict('Файл изменился после проверки. Проверьте его заново.')
    day = _day(effective_from)
    now = _now()
    if day < now.date():
        raise ValueError('Новая версия может действовать с сегодняшней или будущей даты; прежние срезы сохраняются.')
    with lock(folder):
        current = state(folder, legacy)
        if not current['source_sha256']:
            raise ValueError('Сначала загрузите первый утверждённый план проекта.')
        if current['latest_source_sha256'] != expected_previous_sha256:
            raise ScheduleVersionConflict('Утверждённый план уже изменён другим запросом. Проверьте новую версию заново.')
        if current['latest_effective_from'] and effective_from < current['latest_effective_from']:
            raise ValueError('Дата новой версии не может быть раньше уже утверждённой следующей версии.')
        if source_sha == expected_previous_sha256:
            return dict(current, unchanged=True)
        events = current['versions']
        if len(events) >= MAX_VERSIONS:
            raise ValueError('Достигнут предел версий ГПР. Обратитесь к администратору.')
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
                 'author': str(author or '')[:200]}
        _atomic(folder/'schedule_versions.json', json.dumps(
            {'schema': 1, 'versions': [*events, event]}, ensure_ascii=False).encode())
        return dict(state(folder, legacy), unchanged=False)
