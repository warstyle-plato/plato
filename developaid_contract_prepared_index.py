"""Bounded existing-cache index evidence, never a parser or financial reader.

Only current persisted manifests are eligible. Originals, parse caches,
header decisions and identity journals are never refreshed or written here.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

import developaid_contract_source_review as source_review
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers

SCHEMA = 'ks6-existing-cache-index-v1'
ROSTER_SCHEMA = 'ks6-cache-source-roster-v1'
CONTENT_SCHEMA = 'ks6-cache-relative-content-v1'
MAX_ARCHIVES = 32
MAX_FILES = 128
MAX_SHEETS = 512
MAX_RECORDS = 512
MAX_POSITIONS = 20_000
MAX_ENTRIES = 512
MAX_MANIFEST_BYTES = 24 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_RESULT_BYTES = 262144
MAX_NODES = 1_000_000
MAX_DEPTH = 32
MAX_ALIASES_BYTES = 65536
MAX_ALIAS_ENTRIES = 1024
HASH = re.compile(r'[0-9a-f]{64}\Z')
SID = re.compile(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}\Z')


class PreparedIndexProblem(contracts.ContractProblem):
    pass


def _need(condition, message):
    if not condition:
        raise PreparedIndexProblem(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def text_sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _alias_component(value):
    if (type(value) is not str or not 0 < len(value) <= 255 or value in {'.', '..'}
            or any(c in value for c in '/\\\0') or any(ord(c) < 32 for c in value)):
        return False
    try:
        return len(value.encode('utf-8')) <= 255
    except UnicodeError:
        return False


def _strict_alias_map(held):
    if held is None:
        return {}
    value = _decode(held[0])
    _need(type(value) is dict and set(value) == {'aliases'} and type(value['aliases']) is dict
          and len(value['aliases']) <= MAX_ALIAS_ENTRIES,
          'Структура файла псевдонимов не подтверждена.')
    _need(all(_alias_component(k) and _alias_component(v) for k, v in value['aliases'].items()),
          'Каталог в файле псевдонимов не подтверждён.')
    return value['aliases']


def _native_alias_cache_snapshot(state):
    """Observe only; never warm, clear or repair the legacy process cache."""
    _need(type(state) is dict and set(state) == {'key', 'map'} and type(state['map']) is dict
          and len(state['map']) <= MAX_ALIAS_ENTRIES, 'Состояние native alias cache не подтверждено.')
    key = state['key']
    _need(key is None or type(key) is tuple and len(key) == 3
          and type(key[0]) is str and 0 < len(key[0]) <= 4096
          and type(key[1]) is int and -(2**63) <= key[1] < 2**63
          and type(key[2]) is int and 0 <= key[2] < 2**63,
          'Ключ native alias cache не подтверждён.')
    size = 0
    for name, target in state['map'].items():
        _need(type(name) is str and type(target) is str and len(name) <= 4096 and len(target) <= 4096,
              'Типы native alias cache не подтверждены.')
        size += len(canonical(name)) + len(canonical(target))
        _need(size <= MAX_ALIASES_BYTES, 'Объём native alias cache превышает предел.')
    snapshot = copy.deepcopy(state)
    _need(snapshot == state, 'Native alias cache изменился во время наблюдения.')
    return snapshot


def _shape(value):
    todo, nodes = [(value, 0)], 0
    while todo:
        item, depth = todo.pop()
        nodes += 1
        _need(nodes <= MAX_NODES and depth <= MAX_DEPTH, 'Структура cache выходит за предел проверки.')
        if type(item) is dict:
            _need(all(type(key) is str for key in item), 'Ключ cache имеет неверный тип.')
            todo.extend((v, depth + 1) for v in item.values())
        elif type(item) is list:
            todo.extend((v, depth + 1) for v in item)
        else:
            _need(type(item) in {str, int, bool, type(None)} or
                  type(item) is float and math.isfinite(item), 'Значение cache имеет неверный тип.')


def _decode(data):
    def pairs(values):
        result = {}
        for key, value in values:
            _need(key not in result, 'В cache повторён ключ.')
            result[key] = value
        return result
    def invalid(_):
        raise PreparedIndexProblem('Число cache не подтверждено.')
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
        _shape(value)
        return value
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, PreparedIndexProblem):
            raise
        raise PreparedIndexProblem('Сохранённый cache не прочитан.') from None


class _Directory:
    """Read-only held no-follow ancestry, with fd-relative bounded reads."""
    def __init__(self, path):
        self.nodes = []
        path = Path(path).absolute()
        _need('..' not in path.parts, 'Каталог cache не подтверждён.')
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.nodes.append((None, fd, self._identity(os.fstat(fd))))
            for name in path.parts[1:]:
                self.verify()
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=self.nodes[-1][1])
                self.nodes.append((name, fd, self._identity(os.fstat(fd))))
            self.fd = self.nodes[-1][1]
            self.verify()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _identity(info):
        return info.st_dev, info.st_ino

    def verify(self):
        for index, (name, fd, expected) in enumerate(self.nodes):
            info = os.fstat(fd)
            _need(stat.S_ISDIR(info.st_mode) and info.st_nlink >= 1 and
                  self._identity(info) == expected, 'Каталог cache изменился.')
            if index:
                entry = os.stat(name, dir_fd=self.nodes[index - 1][1], follow_symlinks=False)
                _need(stat.S_ISDIR(entry.st_mode) and self._identity(entry) == expected,
                      'Путь cache заменён или содержит ссылку.')

    def names(self):
        self.verify()
        names = sorted(os.listdir(self.fd))
        _need(len(names) <= MAX_ENTRIES, 'Состав каталога cache превышает предел.')
        self.verify()
        return names

    def read(self, name, cap, *, optional=False, with_pin=False):
        _need(type(name) is str and name not in {'', '.', '..'} and
              not any(c in name for c in '/\\\0'), 'Имя cache не подтверждено.')
        self.verify()
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        except FileNotFoundError:
            if optional:
                return None
            raise
        with os.fdopen(fd, 'rb') as handle:
            before = os.fstat(handle.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= cap,
                  'Файл cache имеет неверный тип или размер.')
            data = handle.read(cap + 1)
            after = os.fstat(handle.fileno())
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode, s.st_nlink)
        entry = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        _need(len(data) == before.st_size <= cap and signature(before) == signature(after)
              and signature(entry) == signature(before), 'Файл cache изменился во время чтения.')
        self.verify()
        return (data, signature(before)) if with_pin else data

    def absent(self, name):
        self.verify()
        try:
            os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return True
        return False

    def close(self):
        for _, fd, _ in reversed(self.nodes):
            os.close(fd)
        self.nodes.clear()


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _source_key(record):
    _need(type(record) is dict and type(record.get('source')) is dict,
          'Координаты cache не подтверждены.')
    source = record['source']
    filename, sheet, row = (source.get(k) for k in ('filename', 'sheet', 'row'))
    _need(type(filename) is str and 0 < len(filename) <= 240 and
          type(sheet) is str and 0 < len(sheet) <= 200 and
          type(row) is int and 1 <= row <= 1_000_000, 'Координаты cache неоднозначны.')
    return filename, sheet, row


def record_content_view(record):
    """Shared typed seam for native cached records and retained audit DTOs.

    Only known audit annotations and the audit's formula/filename omission are
    removed. Business scalars/unknowns remain unchanged. Item order is proved
    separately by the ordinal map, so content is sorted by immutable source.
    """
    value = copy.deepcopy(record)
    for key in ('source_coordinates_scope', 'formula_text_omitted', 'identity_state',
                'contract_date_cut_qualification', 'source_identity_sha256', 'header_cells',
                'headers_truncated', 'periods_scope', 'binding_verified'):
        value.pop(key, None)
    if 'items' in value:
        _need(type(value['items']) is list, 'Состав строк cache не подтверждён.')
        keys = [_source_key(item) for item in value['items']]
        _need(len(keys) == len(set(keys)), 'В cache повторена координата позиции.')
        for item in value['items']:
            item.pop('raw_quantity_cells', None)
            _need(type(item.get('periods', [])) is list, 'Периоды cache не подтверждены.')
            for period in item.get('periods', []):
                _need(type(period) is dict, 'Период cache имеет неверный тип.')
                period.pop('cut_qualification', None)
        value['items'].sort(key=_source_key)
    return source_review._audit_relative(value, '')


def source_content_basis(snapshots):
    """Pure expected-content helper; it does not attest parser stamps or IDs."""
    archives = []
    for snapshot in snapshots:
        rows = []
        for kind, field in ((0, 'ledgers'), (1, 'summary_contracts')):
            for record in snapshot.get(field) or []:
                filename, sheet, row = _source_key(record)
                _need(_hash(record.get('file_sha256')), 'SHA записи cache отсутствует.')
                rows.append([kind, record['file_sha256'], text_sha256(filename), text_sha256(sheet), row,
                             digest(record_content_view(record))])
        rows.sort()
        _need(len(rows) == len({tuple(r[:5]) for r in rows}), 'В cache повторена запись источника.')
        archives.append(dict(snapshot_id=snapshot['snapshot_id'], records=rows))
    archives.sort(key=lambda a: a['snapshot_id'])
    return dict(schema=CONTENT_SCHEMA, archives=archives)


def source_content_digest(snapshots):
    return digest(source_content_basis(snapshots))


def source_roster_digest(cut, archives):
    """Same hash-only SID/date/file basis for cache and caller's saved audit.

    No original/member sizes are available in persisted manifests. This basis
    is deliberately different from the retained-original corpus token.
    """
    rows = []
    for archive in archives:
        files = sorted([[f['filename_sha256'], f['file_sha256']] for f in archive['files']])
        rows.append(dict(snapshot_id=archive['snapshot_id'], taken_at=archive['taken_at'], files=files))
    rows.sort(key=lambda a: (a['taken_at'], a['snapshot_id']))
    return digest(dict(schema=ROSTER_SCHEMA, cut=cut, archives=rows))


def _producer():
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (ledgers, contracts, source_review, monitor)} | {
                'developaid_contract_prepared_index': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def _cache_view(snapshot, remaining_positions, remaining_records):
    _need(type(snapshot.get('parser_schema')) is int and snapshot['parser_schema'] == ledgers.PARSER_SCHEMA
          and type(snapshot.get('identity_schema')) is int and snapshot['identity_schema'] == 4,
          'Схема cache не является текущей наблюдаемой схемой.')
    _need(snapshot.get('source_parse_state') in (None, 'current'),
          'Cache содержит неизвестное или устаревшее состояние разбора.')
    _need(ledgers.basis_metadata_current(snapshot), 'Сохранённые основания cache устарели.')
    _need(type(snapshot.get('ledgers')) is list and type(snapshot.get('summary_contracts')) is list,
          'Состав cache не подтверждён.')
    _need(len(snapshot['ledgers']) + len(snapshot['summary_contracts']) <= remaining_records,
          'Предел записей cache превышен.')
    for record in [*snapshot['ledgers'], *snapshot['summary_contracts']]:
        _need(type(record) is dict and not {'contract_date_original', 'date_confirmation'} & record.keys(),
              'В cache находится effective-уточнение; текущий профиль его не принимает.')
    for record in snapshot['ledgers']:
        _need(_hash(record.get('file_sha256')) and type(record.get('identity_source')) is dict
              and type(record.get('party_evidence')) is dict,
              'Структура identity-входа cache не подтверждена.')
        _need(type(record.get('items')) is list, 'Состав позиций cache неизвестен.')
        for item in record['items']:
            _need(type(item) is dict and type(item.get('periods')) is list,
                  'Состав периодов cache неизвестен.')
            for period in item['periods']:
                _need(type(period) is dict and type(period.get('label')) is str
                      and all(period.get(k) is None or type(period.get(k)) is str
                              for k in ('date_start', 'date_end')),
                      'Типы дат периода cache не подтверждены.')
    _need(sum(len(r['items']) for r in snapshot['ledgers']) <= remaining_positions,
          'Предел позиций cache превышен.')
    restored = ledgers._restore_period_dates(snapshot)
    return restored


def _native_ignored_file(record):
    """Recognize only exact metadata records emitted by the native parser."""
    if (type(record) is not dict or set(record) != {'filename', 'status', 'warnings'}
            or record['status'] != 'ignored' or type(record['filename']) is not str
            or record['warnings'] != ['Служебный файл архива.']):
        return False
    name = record['filename']
    try:
        name.encode('utf-8')
        return (ledgers._safe_name(name) == name and not name.endswith('/')
                and (name.startswith('__MACOSX/') or name.rsplit('/', 1)[-1] == '.DS_Store'))
    except (ledgers.LedgerProblem, UnicodeError):
        return False


def _project(snapshots, cut):
    file_rows, sheet_rows, record_rows, index_rows, states, read_snapshots = [], [], [], [], [], []
    manifest_files = 0
    for ai, snapshot in enumerate(snapshots):
        _need(type(snapshot.get('files')) is list, 'Опись файлов cache отсутствует.')
        file_map, seen_names = {}, set()
        for f in snapshot['files']:
            manifest_files += 1
            _need(manifest_files <= MAX_FILES, 'Предел файлов cache превышен.')
            _need(type(f) is dict and type(f.get('filename')) is str and 0 < len(f['filename']) <= 240,
                  'Опись cache неполна или содержит неподдерживаемый файл.')
            name_key = f['filename'].casefold().rstrip('/')
            _need(name_key not in seen_names, 'В cache повторено имя файла.')
            seen_names.add(name_key)
            if f.get('status') == 'ignored':
                _need(_native_ignored_file(f), 'Опись cache неполна или содержит неподдерживаемый файл.')
                continue
            _need(f.get('status') == 'parsed' and _hash(f.get('sha256')),
                  'Опись cache неполна или содержит неподдерживаемый файл.')
            _need(f['filename'] not in file_map, 'В cache повторено имя файла.')
            file_map[f['filename']] = len(file_rows)
            file_rows.append([ai, f['sha256'], text_sha256(f['filename'])])
        _need(len(file_rows) <= MAX_FILES, 'Предел файлов cache превышен.')
        read = _cache_view(snapshot, MAX_POSITIONS - len(index_rows), MAX_RECORDS - len(record_rows))
        read_snapshots.append(read)
        sheet_map, stored_keys, read_keys = {}, [], []
        for stage, target in ((snapshot, stored_keys), (read, read_keys)):
            for kind, field in ((0, 'ledgers'), (1, 'summary_contracts')):
                target.extend([kind, *_source_key(r)] for r in stage[field])
        _need(stored_keys == read_keys, 'Порядок cache изменился при подготовке.')
        for kind, field in ((0, 'ledgers'), (1, 'summary_contracts')):
            seen = set()
            for ri, record in enumerate(read[field]):
                filename, sheet, row = _source_key(record)
                key = (filename, sheet, row)
                _need(key not in seen and filename in file_map, 'Запись cache имеет чужую или повторённую координату.')
                seen.add(key)
                fi = file_map[filename]
                _need(record.get('file_sha256') == file_rows[fi][1], 'SHA записи не совпал с описью cache.')
                sk = (fi, sheet)
                if sk not in sheet_map:
                    sheet_map[sk] = len(sheet_rows)
                    sheet_rows.append([fi, text_sha256(sheet)])
                si = sheet_map[sk]
                record_index = len(record_rows)
                record_rows.append([ai, fi, si, kind, row, ri, ri, digest(record_content_view(record))])
                if kind == 0:
                    _need(type(record.get('items')) is list, 'Строки ledger cache отсутствуют.')
                    positions = set()
                    for ii, item in enumerate(record['items']):
                        point = _source_key(item)
                        _need(point[:2] == key[:2] and point not in positions,
                              'Позиция cache имеет чужую или повторённую координату.')
                        positions.add(point)
                        group = item.get('is_group')
                        row_kind = 0 if group is True else 1 if group is False else 2
                        _need(group is None or type(group) is bool, 'Тип строки cache не подтверждён.')
                        index_rows.append([record_index, point[2], ri, ii, ri, ii,
                                           row_kind, 0, digest(list(point))])
                    _need(len(index_rows) <= MAX_POSITIONS, 'Предел позиций cache превышен.')
                _need(len(record_rows) <= MAX_RECORDS and len(sheet_rows) <= MAX_SHEETS,
                      'Предел записей или листов cache превышен.')
        states.append(dict(snapshot_id=snapshot['snapshot_id'], parser_schema=snapshot['parser_schema'],
            identity_schema=snapshot['identity_schema'], basis_metadata_current=True,
            observed_stored_parse_state=snapshot.get('source_parse_state'),
            identity_input_shape_complete=True, future_consumer_invoked=False,
            read_branch='current_restore_only',
            stored_order_sha256=digest(stored_keys), read_order_sha256=digest(read_keys)))
        used_files = {r[1] for r in record_rows if r[0] == ai}
        _need(file_map and used_files == set(file_map.values()), 'Опись cache содержит файл без записи источника.')
    return dict(files=file_rows, sheets=sheet_rows, records=record_rows, position_index_rows=index_rows,
                archive_states=states), read_snapshots


def project_index(project, cut, snapshot_ids, expected_project_scope,
                  expected_cached_source_roster_sha256, expected_source_content_sha256,
                  caller_reference_corpus_token):
    _need(type(project) is str and 0 < len(project.strip()) <= 200, 'Выберите проект.')
    _need(type(cut) is str and contracts._date(cut) == cut, 'Дата среза cache не подтверждена.')
    _need(type(snapshot_ids) is list and 1 <= len(snapshot_ids) <= MAX_ARCHIVES
          and all(type(s) is str and SID.fullmatch(s) and s[:10] <= cut for s in snapshot_ids)
          and len(set(snapshot_ids)) == len(snapshot_ids), 'Неверный закрытый состав cache.')
    for s in snapshot_ids:
        _need(contracts._date(s[:10]) == s[:10], 'Дата cache не подтверждена.')
    _need(all(_hash(v) for v in (expected_project_scope, expected_cached_source_roster_sha256,
          expected_source_content_sha256, caller_reference_corpus_token)), 'Неверный hash контекста cache.')
    producer = _producer()
    opened = []
    try:
        configured_base = monitor._SNAPSHOT_DIR
        _need(isinstance(configured_base, Path), 'Каталог native cache не подтверждён.')
        base = configured_base.absolute()
        alias_name = monitor._ALIASES_FILE
        _need(_alias_component(alias_name), 'Имя файла псевдонимов не подтверждено.')
        base_dir = _Directory(base); opened.append(base_dir)
        aliases = base_dir.read(alias_name, MAX_ALIASES_BYTES, optional=True, with_pin=True)
        alias_map = _strict_alias_map(aliases)
        cache_object = monitor._ALIAS_CACHE
        native_cache = _native_alias_cache_snapshot(cache_object)
        fd_key = (str(configured_base / alias_name), aliases[1][3], aliases[1][2]) if aliases is not None else None
        cache_key_matches = aliases is not None and native_cache['key'] == fd_key
        _need(not cache_key_matches or native_cache['map'] == alias_map,
              'Native alias cache не совпал с точным файлом при том же ключе.')
        branch = ('missing_alias_file_empty_map' if aliases is None else
                  'warm_key_matching_fd' if cache_key_matches else 'would_reload')
        native_slug_function = monitor._slug
        input_slug = native_slug_function(project.strip())
        _need(_alias_component(input_slug), 'Исходный каталог проекта не подтверждён.')
        slug = alias_map.get(input_slug, input_slug)
        location = os.path.normpath(os.path.join(str(base), slug))
        _need(_alias_component(slug) and os.path.dirname(location) == str(base)
              and location.startswith(str(base) + os.sep),
              'Пространство cache не подтверждено.')
        scope = digest(dict(namespace=slug))
        _need(scope == expected_project_scope, 'Пространство cache не совпало с наблюдаемым scope.')
        project_dir = _Directory(base / slug); opened.append(project_dir)
        root = _Directory(base / slug / 'cumulative'); opened.append(root)
        def guard():
            for directory in opened:
                directory.verify()
            _need(monitor._SNAPSHOT_DIR == configured_base and configured_base.absolute() == base
                  and monitor._ALIASES_FILE == alias_name
                  and monitor._slug is native_slug_function and native_slug_function(project.strip()) == input_slug
                  and base_dir.read(alias_name, MAX_ALIASES_BYTES, optional=True, with_pin=True) == aliases
                  and monitor._ALIAS_CACHE is cache_object
                  and _native_alias_cache_snapshot(cache_object) == native_cache,
                  'Пространство cache изменилось.')
            _need(project_dir.absent('cumulative_header_dates.json'),
                  'Наблюдается файл уточнений шапок; необходим отдельный профиль.')
        def capture():
            guard()
            names = root.names()
            found = sorted(name[:-5] for name in names if name.endswith('.json')
                           and SID.fullmatch(name[:-5]) and name[:10] <= cut)
            orphan = [name[:-4] for name in names if name.endswith('.zip')
                      and SID.fullmatch(name[:-4]) and name[:10] <= cut and name[:-4] not in found]
            _need(found == sorted(snapshot_ids) and not orphan, 'Состав cache неполон или изменился.')
            raw, total = {}, 0
            for sid in found:
                raw[sid] = root.read(sid + '.json', MAX_MANIFEST_BYTES, with_pin=True)
                total += len(raw[sid][0])
                _need(total <= MAX_TOTAL_BYTES, 'Общий предел metadata cache превышен.')
            guard()
            return raw
        before = capture()
        snapshots = []
        for sid, (data, _) in before.items():
            snapshot = _decode(data)
            _need(type(snapshot) is dict and snapshot.get('snapshot_id') == sid
                  and snapshot.get('taken_at') == sid[:10] and snapshot.get('sha256') == sid[11:],
                  'Идентичность manifest cache не подтверждена.')
            snapshots.append(snapshot)
        projected, read_views = _project(snapshots, cut)
        archives = [dict(snapshot_id=s['snapshot_id'], taken_at=s['taken_at'],
            files=[dict(filename_sha256=f[2], file_sha256=f[1])
                   for f in projected['files'] if f[0] == ai])
            for ai, s in enumerate(snapshots)]
        roster = source_roster_digest(cut, archives)
        _need(roster == expected_cached_source_roster_sha256, 'Наблюдаемая опись cache не совпала с ожидаемой.')
        content = source_content_digest(read_views)
        _need(content == expected_source_content_sha256, 'Содержимое cache не совпало с сохранённым typed view.')
        manifest_seal = digest([[sid, hashlib.sha256(data).hexdigest(), list(pin)]
                                for sid, (data, pin) in before.items()])
        result = dict(schema=SCHEMA, scope='existing_current_cache_indices_before_future_consumer_or_ownership',
            cut=cut, project_scope=scope, caller_reference_corpus_token=caller_reference_corpus_token,
            original_corpus_verified=False, original_bytes_read=0, cache_writes=0,
            cached_source_roster_schema=ROSTER_SCHEMA, cached_source_roster_sha256=roster,
            content_view_schema=CONTENT_SCHEMA, source_content_sha256=content,
            formula_semantics_verified=False, duplicate_exclusion_verified=False,
            producer=producer, manifest_set_before_sha256=manifest_seal,
            manifest_set_after_sha256=manifest_seal,
            namespace_seal_sha256=digest(dict(scope=scope, alias_file_pin=
                [hashlib.sha256(aliases[0]).hexdigest(), list(aliases[1])] if aliases is not None else None,
                strict_alias_map_sha256=digest(alias_map), native_cache_sha256=digest(native_cache), branch=branch)),
            namespace_resolution=dict(basis='held_fd_alias_inputs_and_observed_cache_not_legacy_execution',
                resolution_source='strict_held_fd_map',
                branch=branch, alias_file_present=aliases is not None,
                strict_alias_map_sha256=digest(alias_map), native_cache_key_matches_fd=cache_key_matches,
                native_cache_before_sha256=digest(native_cache), native_cache_after_sha256=digest(native_cache),
                legacy_resolver_invoked=False, current_native_consumer_invoked=False),
            header_file=dict(present=False, bytes=None, sha256=None),
            manifests=[dict(snapshot_id=sid, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                            file_identity_sha256=digest(list(pin)))
                       for sid, (data, pin) in before.items()], **projected,
            counts=dict(archives=len(snapshots), files=len(projected['files']), sheets=len(projected['sheets']),
                        records=len(projected['records']), positions=len(projected['position_index_rows'])),
            row_lineage_schema=dict(stored_current=0), complete=True, truncated=False,
            columns=dict(files=['archive', 'book_sha256', 'filename_sha256'],
                sheets=['file', 'sheet_sha256'],
                records=['archive', 'file', 'sheet', 'kind', 'source_row', 'stored_index', 'read_index', 'content_sha256'],
                position_index_rows=['record', 'source_row', 'stored_li', 'stored_ii', 'read_li', 'read_ii',
                                     'row_kind', 'lineage', 'source_key_sha256']),
            future_consumer_invoked=False,
            limits=dict(canonical_output_bytes=MAX_RESULT_BYTES, envelope_reservation_bytes=1024),
            namespace_preimage_observed=False, operational_card_ids_provided=False,
            physical_binding_verified=None, financial_complete=None, consumer_complete=None)
        result['projection_sha256'] = digest(result)
        _need(len(canonical(result)) + 1024 <= MAX_RESULT_BYTES, 'Проекция cache превышает предел; частичный результат не возвращается.')
        _need(before == capture() and _producer() == producer,
              'Manifest cache или код изменился во время проверки.')
        guard()
        return result
    except PreparedIndexProblem:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, RuntimeError):
        raise PreparedIndexProblem('Наблюдаемый cache не подтверждён; чтение остановлено.') from None
    finally:
        for directory in reversed(opened):
            directory.close()
