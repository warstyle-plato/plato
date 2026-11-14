"""Bounded append-only identity decisions. Source and choice files are immutable."""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import fcntl
import functools
import hashlib
import json
import os
import re
import stat
from pathlib import Path

import developaid_monitor as monitor

LOG = 'contract_identity_decisions.jsonl'
MAX_BYTES = 1024 * 1024
MAX_EVENTS = 256
MAX_EVENT_BYTES = 128 * 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')
_NAMESPACE = contextvars.ContextVar('contract_identity_namespace', default=None)


class IdentityProblem(ValueError):
    def __init__(self, message, status=409):
        self.status = status
        super().__init__(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate key')
            out[key] = value
        return out
    def nonfinite(_):
        raise ValueError('nonfinite number')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        raise IdentityProblem('Сохранённые уточнения реквизитов не прочитаны. Проверьте журнал решений.', 503) from None


def _unbound_root(project):
    if not isinstance(project, str) or not project.strip() or len(project) > 200:
        raise IdentityProblem('Выберите проект.', 400)
    slug = monitor._resolved_slug(project.strip())
    if not isinstance(slug, str) or slug in {'', '.', '..'} or any(x in slug for x in ('/', '\\', '\0')):
        raise IdentityProblem('Каталог проекта не подтверждён.', 400)
    base = os.path.abspath(monitor._SNAPSHOT_DIR)
    location = os.path.normpath(os.path.join(base, slug))
    if os.path.dirname(location) != base or not location.startswith(base+os.sep):
        raise IdentityProblem('Каталог проекта не подтверждён.', 400)
    root = Path(location)
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise IdentityProblem('Каталог проекта не подтверждён.', 503)
    return root


def project_root(project):
    pinned = _NAMESPACE.get()
    if pinned is not None:
        if not isinstance(project, str) or project.strip() != pinned['project']:
            raise IdentityProblem('Проверка относится к другому проекту.', 409)
        return pinned['root']
    return _unbound_root(project)


def assert_namespace(project):
    pinned = _NAMESPACE.get()
    if pinned is not None and (_unbound_root(project) != pinned['root']
            or read_bytes(pinned['aliases'], 64*1024) != pinned['aliases_bytes']
            or Path(monitor._SNAPSHOT_DIR).absolute() != pinned['base']):
        raise IdentityProblem('Привязка имени проекта изменилась. Обновите инвентаризацию.', 409)


@contextlib.contextmanager
def namespace(project):
    """Native merge owns EX on this same global lock; identity operations use SH.

    Root pinning additionally prevents a late/uncooperative alias retarget from
    taking an A lock but appending a revision-zero journal under B.
    """
    if _NAMESPACE.get() is not None:
        project_root(project)
        yield
        return
    base = Path(monitor._SNAPSHOT_DIR).absolute()
    if not base.is_dir() or base.is_symlink():
        raise IdentityProblem('Сохранённый проект не найден.', 404)
    fd = os.open(base/'.aliases.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise IdentityProblem('Блокировка пространства проектов недоступна.', 503)
        fcntl.flock(handle, fcntl.LOCK_SH)
        root = _unbound_root(project)
        aliases = base/monitor._ALIASES_FILE
        token = _NAMESPACE.set({'project': project.strip(), 'root': root, 'base': base,
                                'aliases': aliases, 'aliases_bytes': read_bytes(aliases, 64*1024)})
        try:
            yield
            assert_namespace(project)
        finally:
            _NAMESPACE.reset(token)


def in_namespace(function):
    @functools.wraps(function)
    def bound(project, *args, **kwargs):
        with namespace(project):
            return function(project, *args, **kwargs)
    return bound


def project_scope(project):
    return digest({'namespace': project_root(project).name})


def read_bytes(path, cap=MAX_BYTES):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError:
        raise IdentityProblem('Метаданные проекта недоступны.', 503) from None
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > cap:
            raise IdentityProblem('Метаданные проекта выходят за пределы ограниченного чтения.', 413)
        raw = source.read(cap+1)
        after = os.fstat(source.fileno())
    if len(raw) > cap or len(raw) != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise IdentityProblem('Метаданные изменились во время чтения. Обновите проверку.', 409)
    return raw


def _timestamp(value):
    try:
        found = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise IdentityProblem('В журнале уточнений не подтверждено время записи.', 503) from None
    if found.tzinfo is None or found.utcoffset() != dt.timedelta(0):
        raise IdentityProblem('В журнале уточнений не подтверждено время записи.', 503)
    return found


def validate_member(member):
    """Closed evidence schema; no caller paths or alternative IDs are accepted."""
    fields = {'raw_id', 'snapshot_id', 'archive_sha256', 'source_date', 'identity',
              'sources', 'source_identity_complete', 'source_token'}
    bad = IdentityProblem('Привязка версии источника не подтверждена.', 503)
    if not isinstance(member, dict) or set(member) != fields:
        raise bad
    for key in ('raw_id', 'archive_sha256', 'source_token'):
        if not isinstance(member[key], str) or not HASH.fullmatch(member[key]):
            raise bad
    try:
        day = dt.date.fromisoformat(member['source_date']).isoformat()
    except (TypeError, ValueError):
        raise bad from None
    if day != member['source_date'] or member['snapshot_id'] != day+'-'+member['archive_sha256']:
        raise bad
    identity = member['identity']
    if not isinstance(identity, dict) or set(identity) != {'customer', 'contractor', 'contract', 'contract_date'}:
        raise bad
    if any(not isinstance(identity[key], str) or not identity[key].strip() or len(identity[key]) > 2000
           for key in ('customer', 'contractor', 'contract')):
        raise bad
    try:
        contract_day = dt.date.fromisoformat(identity['contract_date']).isoformat()
    except (TypeError, ValueError):
        raise bad from None
    if contract_day != identity['contract_date'] or member['source_identity_complete'] is not True:
        raise bad
    sources = member['sources']
    if not isinstance(sources, list) or not 1 <= len(sources) <= 256:
        raise bad
    for source in sources:
        if (not isinstance(source, dict) or set(source) != {'file_sha256', 'source_locator_sha256', 'kind'}
                or source['kind'] not in {'ledger', 'summary'}
                or any(not isinstance(source[key], str) or not HASH.fullmatch(source[key])
                       for key in ('file_sha256', 'source_locator_sha256'))):
            raise bad
    if member['source_token'] != digest({key: value for key, value in member.items() if key != 'source_token'}):
        raise bad


def decode_log(project, raw):
    if raw is None:
        return {'revision': 0, 'head': '0'*64, 'events': [], 'active': [], 'sha256': None}
    if not raw or not raw.endswith(b'\n'):
        raise IdentityProblem('Журнал уточнений записан не полностью. Прежнее решение не подставлено.', 503)
    lines = raw.splitlines()
    if len(lines) > MAX_EVENTS:
        raise IdentityProblem('Достигнут предел журнала уточнений.', 413)
    events, head, active, historical_pairs = [], '0'*64, {}, []
    previous_time = None
    for sequence, line in enumerate(lines, 1):
        if len(line) > MAX_EVENT_BYTES:
            raise IdentityProblem('Запись уточнения превышает допустимый размер.', 413)
        event = strict_json(line)
        if not isinstance(event, dict) or set(event) != {'sequence', 'previous', 'event_id', 'recorded_at',
                'project_scope', 'actor', 'action', 'payload'}:
            raise IdentityProblem('Формат журнала уточнений не подтверждён.', 503)
        sealed = {key: value for key, value in event.items() if key != 'event_id'}
        when = _timestamp(event['recorded_at'])
        if (type(event['sequence']) is not int or event['sequence'] != sequence or event['previous'] != head
                or event['event_id'] != digest(sealed) or event['project_scope'] != project_scope(project)
                or not isinstance(event['actor'], str) or not HASH.fullmatch(event['actor'])
                or previous_time is not None and when < previous_time):
            raise IdentityProblem('Целостность журнала уточнений не подтверждена.', 503)
        payload = event['payload']
        if event['action'] == 'confirm':
            if not isinstance(payload, dict) or set(payload) != {'members', 'anchor_id', 'canonical_number', 'note',
                                                               'inventory_sha256', 'reviewed_archives', 'inventory_cut'}:
                raise IdentityProblem('Реквизиты решения не подтверждены.', 503)
            members = payload['members']
            if not isinstance(members, list) or not 2 <= len(members) <= 64:
                raise IdentityProblem('Реквизиты решения не подтверждены.', 503)
            for member in members:
                validate_member(member)
            archives = payload['reviewed_archives']
            try:
                cut = dt.date.fromisoformat(payload['inventory_cut']).isoformat()
            except (TypeError, ValueError):
                raise IdentityProblem('Дата проверки решения не подтверждена.', 503) from None
            if (cut != payload['inventory_cut'] or not isinstance(archives, list) or not 1 <= len(archives) <= 32
                    or any(not isinstance(sid, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', sid)
                           or day(sid[:10]) != sid[:10]
                           or sid[:10] > cut for sid in archives)
                    or sorted(set(archives)) != archives or any(member['snapshot_id'] not in archives for member in members)):
                raise IdentityProblem('Состав проверенных архивов решения не подтверждён.', 503)
            ids = {member['raw_id'] for member in members}
            if (len(ids) != 2 or any(not isinstance(x, str) or not HASH.fullmatch(x) for x in ids)
                    or payload['anchor_id'] not in ids or not isinstance(payload['canonical_number'], str)
                    or not payload['canonical_number'] or len(payload['canonical_number']) > 80
                    or not isinstance(payload['note'], str) or not payload['note'].strip() or len(payload['note']) > 500
                    or not isinstance(payload['inventory_sha256'], str) or not HASH.fullmatch(payload['inventory_sha256'])):
                raise IdentityProblem('Реквизиты решения не подтверждены.', 503)
            if any(ids & {m['raw_id'] for m in value['payload']['members']} for value in active.values()):
                raise IdentityProblem('В журнале пересекаются действующие уточнения. Они не объединены по цепочке.', 503)
            if any(ids & pair and ids != pair for pair in historical_pairs):
                raise IdentityProblem('Карточки исторических уточнений не объединены в цепочку или цикл.', 503)
            historical_pairs.append(ids)
            active[event['event_id']] = event
        elif event['action'] == 'revoke':
            if (not isinstance(payload, dict) or set(payload) != {'decision_id', 'note'}
                    or not isinstance(payload['decision_id'], str) or payload['decision_id'] not in active):
                raise IdentityProblem('Отмена уточнения не относится к действующему решению.', 503)
            if not isinstance(payload['note'], str) or not payload['note'].strip() or len(payload['note']) > 500:
                raise IdentityProblem('Причина отмены уточнения не подтверждена.', 503)
            active.pop(payload['decision_id'])
        else:
            raise IdentityProblem('Действие журнала уточнений не распознано.', 503)
        events.append(event)
        head, previous_time = event['event_id'], when
    return {'revision': len(events), 'head': head, 'events': events, 'active': list(active.values()),
            'sha256': hashlib.sha256(raw).hexdigest()}


def load(project):
    return decode_log(project, read_bytes(project_root(project)/LOG))


@contextlib.contextmanager
def locked(project):
    with namespace(project):
        root = project_root(project)
        if not root.is_dir():
            raise IdentityProblem('Сохранённый проект не найден.', 404)
        fd = os.open(root/'.contract_identity.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IdentityProblem('Блокировка уточнений недоступна.', 503)
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def append_locked(project, *, expected_revision, actor, action, payload):
    """Caller owns locked(project) and has revalidated the bounded inventory."""
    if _NAMESPACE.get() is None:
        raise IdentityProblem('Пространство проекта не закреплено для записи.', 409)
    assert_namespace(project)
    state = load(project)
    if type(expected_revision) is not int or expected_revision != state['revision']:
        raise IdentityProblem('Уточнения уже изменились. Обновите проверку перед сохранением.', 409)
    if not isinstance(actor, str) or not HASH.fullmatch(actor):
        raise IdentityProblem('Автор решения не подтверждён.', 403)
    if state['revision'] >= MAX_EVENTS:
        raise IdentityProblem('Достигнут предел журнала уточнений.', 413)
    recorded = _now()
    if state['events'] and _timestamp(recorded) < _timestamp(state['events'][-1]['recorded_at']):
        raise IdentityProblem('Время новой записи не подтверждено. Повторите проверку часов сервера.', 503)
    event = {'sequence': state['revision']+1, 'previous': state['head'], 'recorded_at': recorded,
             'project_scope': project_scope(project), 'actor': actor, 'action': action, 'payload': payload}
    event['event_id'] = digest(event)
    raw = canonical(event)+b'\n'
    if len(raw) > MAX_EVENT_BYTES:
        raise IdentityProblem('Уточнение превышает допустимый размер.', 413)
    path = project_root(project)/LOG
    current = read_bytes(path) or b''
    if len(current)+len(raw) > MAX_BYTES:
        raise IdentityProblem('Достигнут предел журнала уточнений.', 413)
    decode_log(project, current+raw)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'ab', buffering=0) as target:
        info = os.fstat(target.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(current):
            raise IdentityProblem('Журнал уточнений изменился перед записью.', 409)
        if target.write(raw) != len(raw):
            raise IdentityProblem('Уточнение записано не полностью. Проверьте журнал.', 503)
        os.fsync(target.fileno())
    checked = load(project)
    return {'revision': checked['revision'], 'event_id': event['event_id'],
            'recorded_at': recorded, 'action': action, 'financial_acceptance': False}
