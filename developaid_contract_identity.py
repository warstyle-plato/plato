"""Owner-confirmed, source-version-bound contract identity support.

No source/choice migration. Inventory is bounded metadata; decisions are a
separate append-only overlay. An absent overlay has no effect on readers.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re

import developaid_contract_identity_store as store

IdentityProblem = store.IdentityProblem
MAX_ARCHIVES = 32
MAX_VERSIONS = 64
MAX_FILES = 256
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024
MAX_TOTAL_ARCHIVE_BYTES = 64 * 1024 * 1024
SNAP = re.compile(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}\Z')


def _ids(raw_ids, *, pair=True):
    if (not isinstance(raw_ids, (list, tuple)) or len(raw_ids) not in ({2} if pair else {1, 2})
            or any(not isinstance(value, str) or not store.HASH.fullmatch(value) for value in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)):
        raise IdentityProblem('Выберите две разные исходные карточки договора.', 400)
    return sorted(raw_ids)


def correction_ids(raw_ids):
    if (not isinstance(raw_ids, (list, tuple)) or not 1 <= len(raw_ids) <= 8
            or any(not isinstance(value, str) or not store.HASH.fullmatch(value) for value in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)):
        raise IdentityProblem('Выберите от двух до восьми разных исходных карточек.', 400)
    return sorted(raw_ids)


def _safe_path(project, *parts):
    path = store.project_root(project)
    for part in parts:
        if not isinstance(part, str) or part in {'', '.', '..'} or any(value in part for value in ('/', '\\', '\0')):
            raise IdentityProblem('Путь метаданных не подтверждён.', 400)
        path = path/part
        if path.is_symlink():
            raise IdentityProblem('Метаданные привязок не подтверждены.', 503)
    return path


def _source_inventory(project, cut, raw_ids, *, correction=False, cache=None):
    """Use the register's exact qualification and ID hashing, without enrichers."""
    import developaid_monitor_contracts as contracts
    import developaid_monitor_ledgers as ledgers
    wanted = set(correction_ids(raw_ids) if correction else _ids(raw_ids, pair=False))
    cut = contracts._cut(cut)
    root = store.project_root(project)
    if not root.is_dir():
        raise IdentityProblem('Сохранённый проект не найден.', 404)
    try:
        folder = _safe_path(project, 'cumulative')
        entries = list(folder.iterdir()) if folder.exists() else []
        if len(entries) > MAX_ARCHIVES*4+16:
            raise IdentityProblem('Число файлов версий превышает предел проверки.', 413)
        manifest_bytes = 0
        for entry in entries:
            if entry.is_symlink():
                raise IdentityProblem('Происхождение версии источника не подтверждено.', 503)
            if SNAP.fullmatch(entry.stem) and entry.suffix == '.json' and entry.stat().st_size > ledgers.MAX_PARSED_BYTES:
                raise IdentityProblem('Метаданные архива превышают предел проверки.', 413)
            if SNAP.fullmatch(entry.stem) and entry.suffix == '.json':
                manifest_bytes += entry.stat().st_size
        if manifest_bytes > MAX_TOTAL_ARCHIVE_BYTES:
            raise IdentityProblem('Объём метаданных версий превышает предел проверки.', 413)
        store.read_bytes(_safe_path(project, 'cumulative_header_dates.json'), 4*1024*1024)
        snapshots = [item for item in ledgers.list_snapshots(project)
                     if contracts._date(item.get('taken_at')) and item['taken_at'] <= cut]
        if len(snapshots) > MAX_ARCHIVES:
            raise IdentityProblem('Число версий источников превышает предел ограниченной проверки.', 413)
        dates = {}
        for item in snapshots:
            sid = item.get('snapshot_id')
            if not isinstance(sid, str) or not SNAP.fullmatch(sid) or sid[:10] != item['taken_at']:
                raise IdentityProblem('Идентичность сохранённого архива не подтверждена.', 503)
            dates.setdefault(item['taken_at'], set()).add(sid)
        if any(len(ids) != 1 for ids in dates.values()):
            raise IdentityProblem('Для одной даты сохранены разные архивы. Источник не выбран по порядку.', 409)
        versions, total_bytes = [], 0
        for day in sorted(dates):
            snapshot = contracts._archive(project, day)
            if not snapshot or snapshot.get('snapshot_id') not in dates[day]:
                raise IdentityProblem('Версия источника изменилась. Обновите проверку.', 409)
            sid = snapshot['snapshot_id']
            raw = (cache.get(('zip', sid)) if cache is not None else None)
            if raw is None:
                raw = store.read_bytes(_safe_path(project, 'cumulative', sid+'.zip'), ledgers.MAX_ARCHIVE_BYTES)
                if cache is not None and raw is not None:
                    cache[('zip', sid)] = raw
            if raw is None or hashlib.sha256(raw).hexdigest() != sid[11:]:
                raise IdentityProblem('Исходный архив недоступен или его SHA изменился. Уточнение не подтверждено.', 409)
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_ARCHIVE_BYTES:
                raise IdentityProblem('Объём исходных версий превышает предел проверки.', 413)
            if cache is not None and sid in cache:
                parsed = cache[sid]
            else:
                parsed = ledgers._current_archive(raw, sid[11:], snapshot.get('filename') or 'Source.zip')
                parsed = ledgers._preserve_source_indices(snapshot, parsed)
                if cache is not None:
                    cache[sid] = parsed
            snapshot = {**snapshot, **parsed}
            snapshot = ledgers.effective_snapshot(project, cut, snapshot=snapshot)
            primary, _, unresolved = contracts.qualified_sources(snapshot, cut)
            if cache is not None:
                cache[('identities', sid)] = [{'raw_id': identifier, 'reference': contracts._reference_key(items[0])}
                                             for identifier, items in contracts._groups(primary, project)]
                cache[('unresolved', sid)] = bool(unresolved)
            files = {}
            for item in snapshot.get('files') or []:
                if isinstance(item.get('filename'), str) and store.HASH.fullmatch(str(item.get('sha256') or '')):
                    files.setdefault(item['filename'], []).append(item['sha256'])
            for identifier, items in contracts._groups(primary, project):
                if identifier not in wanted:
                    continue
                first = items[0]
                identity = {key: first.get(key) for key in ('customer', 'contractor', 'contract', 'contract_date')}
                source_refs = []
                complete = True
                for item in items:
                    source = item.get('source') or {}
                    candidates = files.get(source.get('filename'), [])
                    file_sha = item.get('file_sha256') or (candidates[0] if len(candidates) == 1 else None)
                    if not isinstance(file_sha, str) or not store.HASH.fullmatch(file_sha):
                        complete = False
                        file_sha = None
                    source_refs.append({'file_sha256': file_sha, 'source_locator_sha256': store.digest(source),
                                        'kind': item.get('kind')})
                member = {'raw_id': identifier, 'snapshot_id': snapshot['snapshot_id'],
                          'archive_sha256': snapshot['snapshot_id'][11:], 'source_date': day,
                          'identity': identity, 'sources': sorted(source_refs, key=store.digest),
                          'source_identity_complete': complete}
                member['source_token'] = store.digest(member)
                versions.append(member)
                if len(versions) > MAX_VERSIONS:
                    raise IdentityProblem('Число версий выбранных договоров превышает предел проверки.', 413)
        return versions, sorted(sid for ids in dates.values() for sid in ids)
    except IdentityProblem:
        raise
    except (contracts.ContractProblem, ledgers.LedgerProblem, OSError, ValueError, TypeError, AttributeError, KeyError):
        raise IdentityProblem('Сохранённые версии источников выбранных договоров не прочитаны.', 503) from None


@store.in_namespace
def source_versions(project, cut, raw_ids):
    return _source_inventory(project, cut, raw_ids)[0]


class _Metadata:
    def __init__(self):
        self.bytes = 0
        self.files = 0
        self.price_pdf_bytes = 0
        self.price_pdf_files = 0

    def read(self, path, cap=4*1024*1024):
        raw = store.read_bytes(path, cap)
        self.files += raw is not None
        self.bytes += len(raw or b'')
        if self.files > MAX_FILES or self.bytes > MAX_METADATA_BYTES:
            raise IdentityProblem('Метаданные выбранных карточек превышают предел ограниченной проверки.', 413)
        return raw

    def entry(self, path):
        raw = self.read(path)
        return (store.strict_json(raw) if raw is not None else None,
                {'present': raw is not None, 'bytes': len(raw) if raw is not None else None,
                 'sha256': hashlib.sha256(raw).hexdigest() if raw is not None else None})

    def price_pdf(self, path):
        raw = store.read_bytes(path, 20*1024*1024)
        self.price_pdf_files += 1
        self.price_pdf_bytes += len(raw or b'')
        if self.price_pdf_files > 64 or self.price_pdf_bytes > 64*1024*1024:
            raise IdentityProblem('Объём проверки источников цены превышает предел одной сборки.', 413)
        return raw


def _time_status(value, absent):
    if value is None:
        return absent
    try:
        store._timestamp(value)
        return 'recorded'
    except IdentityProblem:
        return 'unknown'


def document_evidence(record, sha):
    """The unchanged six-field evidence of the native human source decision."""
    return {'document_sha256': sha, 'price_sha256': store.digest(record.get('price')),
            'binding_identity_sha256': store.digest(record.get('contract')),
            'edition_sha256': store.digest([record.get('contract'), record.get('agreement')]),
            'terms_sha256': store.digest(record.get('terms')),
            'reader_version_sha256': store.digest(record.get('reader'))}


def metadata_inventory(project, raw_ids, *, correction=False):
    ids = correction_ids(raw_ids) if correction else _ids(raw_ids)
    read = _Metadata()
    terms, terms_pin = read.entry(_safe_path(project, 'cumulative_terms.json'))
    if terms is not None and not isinstance(terms, dict):
        raise IdentityProblem('Формат сохранённых ручных сроков не подтверждён.', 503)
    links, links_pin = read.entry(_safe_path(project, 'contract_links.json'))
    _, header_pin = read.entry(_safe_path(project, 'cumulative_header_dates.json'))
    if links is not None and (not isinstance(links, dict) or links.get('version') != 1 or not isinstance(links.get('links'), dict)):
        raise IdentityProblem('Формат сохранённых связей работ не подтверждён.', 503)
    out = []
    for identifier in ids:
        term = (terms or {}).get(identifier)
        if term is not None and not isinstance(term, dict):
            raise IdentityProblem('Запись ручного срока не подтверждена.', 503)
        work = []
        for evidence_id, record in ((links or {}).get('links') or {}).items():
            if not isinstance(record, dict):
                raise IdentityProblem('Запись связи работ не подтверждена.', 503)
            candidates = record.get('candidate_contract_ids', [])
            blocked = record.get('blocked_contract_ids', [])
            if not isinstance(candidates, list) or not isinstance(blocked, list):
                raise IdentityProblem('Состав сохранённой связи работ не подтверждён.', 503)
            if identifier not in [record.get('contract_id'), *candidates, *blocked]:
                continue
            work.append({'evidence_id_sha256': store.digest(evidence_id), 'record_sha256': store.digest(record),
                         'confirmed': record.get('confirmed') if type(record.get('confirmed')) is bool else None,
                         'target_is_this_card': record.get('contract_id') == identifier,
                         'explicitly_blocked': identifier in blocked,
                         'signature_sha256': store.digest(record.get('signature')),
                         'other_candidate_count': len([value for value in candidates if value not in ids])})
        folder = _safe_path(project, 'contract_documents', identifier)
        documents, choices = [], {'present': False, 'bytes': None, 'sha256': None}
        if folder.exists():
            if not folder.is_dir():
                raise IdentityProblem('Каталог карточки не подтверждён.', 503)
            entries = sorted(folder.iterdir(), key=lambda item: item.name)
            if len(entries) > MAX_FILES:
                raise IdentityProblem('Число файлов карточки превышает предел проверки.', 413)
            for path in entries:
                if path.is_symlink():
                    raise IdentityProblem('Происхождение метаданных карточки не подтверждено.', 503)
                if path.name == 'links.json':
                    _, choices = read.entry(path)
                elif re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                    record, pin = read.entry(path)
                    if not isinstance(record, dict):
                        raise IdentityProblem('Метаданные документа не подтверждены.', 503)
                    if record.get('scan') is not None and not isinstance(record['scan'], dict):
                        raise IdentityProblem('Подтверждение документа не прочитано.', 503)
                    document = {**document_evidence(record, path.stem), 'metadata': pin,
                        'withdrawal_marker_present': bool(record.get('removed_at')),
                        'withdrawal_status': _time_status(record.get('removed_at'), 'not_marked'),
                        'withdrawal_sha256': store.digest(record.get('removed_at')),
                        'scan_confirmation_sha256': store.digest((record.get('scan') or {}).get('confirmed_at')),
                        'scan_confirmation_status': _time_status((record.get('scan') or {}).get('confirmed_at'), 'unconfirmed'),
                        'scan_confirmation_present': bool((record.get('scan') or {}).get('confirmed_at'))}
                    import developaid_contract_price_provenance as provenance
                    if provenance.FIELD in record:
                        pdf = _safe_path(project, 'contract_documents', identifier, path.stem+'.pdf')
                        document[provenance.FIELD] = provenance.project(record, document, identifier,
                            lambda pdf=pdf: read.price_pdf(pdf))
                    documents.append(document)
        out.append({'raw_id': identifier, 'manual_term_present': term is not None,
                    'manual_term_sha256': store.digest(term) if term is not None else None,
                    'manual_deadline': store.day((term or {}).get('deadline')),
                    'manual_term_time_sha256': store.digest((term or {}).get('updated_at')),
                    'documents': documents, 'document_choices': choices, 'work_links': work})
    result = {'terms_file': terms_pin, 'work_links_file': links_pin, 'header_dates_file': header_pin, 'cards': out,
            'metadata_files_read': read.files, 'metadata_bytes_read': read.bytes,
            'old_choice_files_modified': False}
    if read.price_pdf_files:
        result.update(price_source_bytes_read=read.price_pdf_bytes, price_source_files_read=read.price_pdf_files)
    return result


@store.in_namespace
def inventory(project, raw_ids, cut):
    import developaid_monitor_contracts as contracts
    cut = contracts._cut(cut)
    ids = _ids(raw_ids)
    state = store.load(project)
    versions, reviewed_archives = _source_inventory(project, cut, ids)
    missing = [identifier for identifier in ids if not any(item['raw_id'] == identifier for item in versions)]
    if missing:
        raise IdentityProblem('Одна из выбранных карточек не подтверждена в сохранённых источниках этого проекта.', 404)
    result = {'project_scope': store.project_scope(project), 'cut': cut, 'raw_ids': ids,
              'revision': state['revision'], 'decision_head': state['head'], 'source_versions': versions,
              'reviewed_archives': reviewed_archives,
              'bindings': metadata_inventory(project, ids),
              'decision_history': [{'event_id': event['event_id'], 'action': event['action'],
                                    'recorded_at': event['recorded_at'], 'payload_sha256': store.digest(event['payload'])}
                                   for event in state['events']],
              'financial_acceptance': False}
    result['inventory_sha256'] = store.digest(result)
    if len(store.canonical(result)) > MAX_OUTPUT_BYTES:
        raise IdentityProblem('Результат ограниченной проверки превышает допустимый размер.', 413)
    return result


def _validate_members(project, members, canonical_number, anchor_id):
    import developaid_monitor_contracts as contracts
    ids = _ids(sorted({member.get('raw_id') for member in members}))
    if anchor_id not in ids or not isinstance(canonical_number, str) or not canonical_number or len(canonical_number) > 80:
        raise IdentityProblem('Выберите исходную карточку и подтверждённый номер договора.', 400)
    identities = []
    for member in members:
        store.validate_member(member)
        if (not member.get('source_identity_complete') or not member.get('sources')
                or member.get('source_token') != store.digest({key: value for key, value in member.items() if key != 'source_token'})):
            raise IdentityProblem('Привязка исходной версии договора не подтверждена.', 409)
        identity = member.get('identity') or {}
        date = contracts._date(identity.get('contract_date'))
        base = contracts._reference_key(identity)
        if not all(base) or not date:
            raise IdentityProblem('Для уточнения нужны подтверждённые стороны и дата каждого договора.', 409)
        identities.append((base[0], base[1], date))
    if len(set(identities)) != 1:
        raise IdentityProblem('Стороны или даты источников различаются. Такие договоры не объединены.', 409)
    numbers = {member['identity'].get('contract') for member in members}
    if canonical_number not in numbers:
        raise IdentityProblem('Подтверждённый номер должен присутствовать в одной из проверенных исходных версий.', 409)
    return ids


@contextlib.contextmanager
def _binding_locks(project, raw_ids, *, correction=False):
    """Use the existing native writers' locks, without migrating any data.

    The identity lock is always outermost. No legacy writer takes that lock,
    so native single-file writes cannot form a reverse lock order.
    """
    import fcntl
    paths = [('cumulative', '.lock'), ('cumulative_header_dates.lock',),
             ('cumulative_terms.lock',), ('.contract_links.lock',)]
    paths += [('contract_documents', value, '.lock') for value in (correction_ids(raw_ids) if correction else _ids(raw_ids))]
    with contextlib.ExitStack() as stack:
        held_paths = set(store._HELD_NATIVE_LOCKS.get())
        for parts in paths:
            path = _safe_path(project, *parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            handle = stack.enter_context(os.fdopen(fd, 'a+b'))
            import stat
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IdentityProblem('Блокировка привязок недоступна.', 503)
            fcntl.flock(handle, fcntl.LOCK_EX)
            held_paths.add(str(path))
        token = store._HELD_NATIVE_LOCKS.set(frozenset(held_paths))
        try:
            yield
        finally:
            store._HELD_NATIVE_LOCKS.reset(token)


@store.in_namespace
def confirm(project, raw_ids, cut, *, expected_revision, inventory_sha256, source_tokens,
            anchor_id, canonical_number, note, actor):
    if (not isinstance(source_tokens, list) or not 2 <= len(source_tokens) <= MAX_VERSIONS
            or any(not isinstance(value, str) or not store.HASH.fullmatch(value) for value in source_tokens)
            or len(set(source_tokens)) != len(source_tokens)
            or not isinstance(note, str) or not note.strip() or len(note) > 500):
        raise IdentityProblem('Укажите проверенные версии источников и основание уточнения.', 400)
    with store.locked(project), _binding_locks(project, raw_ids):
        checked = inventory(project, raw_ids, cut)
        if type(expected_revision) is not int or checked['revision'] != expected_revision or checked['inventory_sha256'] != inventory_sha256:
            raise IdentityProblem('Источники или привязки изменились. Обновите проверку перед сохранением.', 409)
        selected = {member['source_token']: member for member in checked['source_versions']}
        if set(source_tokens) != set(selected):
            raise IdentityProblem('Нужны все проверенные версии этих двух карточек; пропущенные версии не объединены.', 409)
        members = [selected[token] for token in sorted(source_tokens)]
        ids = _validate_members(project, members, canonical_number, anchor_id)
        if ids != _ids(raw_ids):
            raise IdentityProblem('Проверка относится к другим исходным карточкам.', 409)
        for event in store.load(project)['active']:
            if set(ids) & {member['raw_id'] for member in event['payload']['members']}:
                raise IdentityProblem('Карточка уже участвует в действующем уточнении. Цепочки и циклы не создаются.', 409)
        # A second complete read seals source and legacy-binding state just
        # before append. Existing source/choice files are never rewritten.
        if inventory(project, raw_ids, cut)['inventory_sha256'] != inventory_sha256:
            raise IdentityProblem('Данные изменились во время проверки. Решение не сохранено.', 409)
        return store.append_locked(project, expected_revision=expected_revision, actor=actor, action='confirm',
            payload={'members': members, 'anchor_id': anchor_id, 'canonical_number': canonical_number,
                     'note': note.strip(), 'inventory_sha256': inventory_sha256,
                     'reviewed_archives': checked['reviewed_archives'], 'inventory_cut': checked['cut']})


@store.in_namespace
def revoke(project, *, expected_revision, decision_id, note, actor):
    if not isinstance(decision_id, str) or not store.HASH.fullmatch(decision_id) or not isinstance(note, str) or not note.strip() or len(note) > 500:
        raise IdentityProblem('Укажите решение и причину его отмены.', 400)
    with store.locked(project):
        state = store.load(project)
        if type(expected_revision) is not int or state['revision'] != expected_revision:
            raise IdentityProblem('Уточнения уже изменились. Обновите проверку.', 409)
        if decision_id not in {event['event_id'] for event in state['active']}:
            raise IdentityProblem('Действующее уточнение не найдено.', 409)
        return store.append_locked(project, expected_revision=expected_revision, actor=actor, action='revoke',
                                   payload={'decision_id': decision_id, 'note': note.strip()})


def _binding_conflicts(bindings):
    """Inventory facts only: never pick an edition, signature or deadline here."""
    cards = bindings['cards']
    gaps = []
    deadlines = {card['manual_deadline'] for card in cards if card['manual_term_present']}
    if len(deadlines) > 1 or any(card['manual_term_present'] and card['manual_deadline'] is None for card in cards):
        gaps.append('manual_deadline_conflict')
    by_sha, editions = {}, {}
    for card in cards:
        for record in card['documents']:
            if record['withdrawal_status'] == 'unknown' and 'withdrawal_unknown' not in gaps:
                gaps.append('withdrawal_unknown')
            if record['scan_confirmation_status'] == 'unknown' and 'scan_confirmation_unknown' not in gaps:
                gaps.append('scan_confirmation_unknown')
            by_sha.setdefault(record['document_sha256'], []).append(record)
            editions.setdefault(record['edition_sha256'], set()).add(record['document_sha256'])
    if any(len({row['withdrawal_sha256'] for row in rows}) > 1 for rows in by_sha.values()):
        gaps.append('withdrawal_conflict')
    if any(len({row['scan_confirmation_sha256'] for row in rows}) > 1 for rows in by_sha.values()):
        gaps.append('scan_confirmation_conflict')
    if any(len(values) > 1 for values in editions.values()):
        gaps.append('document_edition_requires_resolution')
    choices = [card['document_choices']['sha256'] for card in cards if card['document_choices']['present']]
    if len(set(choices)) > 1:
        gaps.append('document_choice_conflict')
    work = {}
    for card in cards:
        for row in card['work_links']:
            work.setdefault(row['evidence_id_sha256'], []).append(row)
    if any(any(row['explicitly_blocked'] or row['confirmed'] is not True or row['other_candidate_count'] for row in rows)
           for rows in work.values()):
        gaps.append('work_link_requires_resolution')
    return gaps


@store.in_namespace
def resolve(project, raw_id, cut, *, source_token=None):
    """Read seam for composition. It does not merge money, documents or choices.

    Both raw IDs remain valid addresses. A revoked or stale correction is an
    explicit unknown, never fallback to a previous correction or alias.
    Callers may coalesce logical ownership ONLY for status=confirmed and only
    for the listed source versions; financial/binding acceptance is separate.
    """
    if not isinstance(raw_id, str) or not store.HASH.fullmatch(raw_id):
        raise IdentityProblem('Выберите исходную карточку договора.', 400)
    if source_token is not None and (not isinstance(source_token, str) or not store.HASH.fullmatch(source_token)):
        raise IdentityProblem('Укажите подтверждённую версию источника.', 400)
    state = store.load(project)
    related = [event for event in state['events'] if event['action'] in {'confirm', 'correct_sources'}
               and raw_id in {member['raw_id'] for member in event['payload']['members']}]
    if not related:
        versions = source_versions(project, cut, [raw_id])
        if not versions:
            raise IdentityProblem('Исходная карточка этого проекта не подтверждена.', 404)
        return {'status': 'raw', 'logical_id': raw_id, 'raw_id': raw_id, 'member_ids': [raw_id],
                'source_versions': versions, 'financial_acceptance': False}
    active = next((event for event in state['active'] if raw_id in
                   {member['raw_id'] for member in event['payload']['members']}), None)
    if active is None:
        return {'status': 'revoked', 'logical_id': None, 'raw_id': raw_id,
                'member_ids': sorted({member['raw_id'] for member in related[-1]['payload']['members']}),
                'decision_id': related[-1]['event_id'], 'financial_acceptance': False,
                'reason': 'Уточнение отменено. Исходные карточки доступны; логическое объединение не подтверждено.'}
    payload = active['payload']
    if active['action'] == 'correct_sources':
        import developaid_contract_correction as correction
        return correction.resolve(project, active, cut)
    _validate_members(project, payload['members'], payload['canonical_number'], payload['anchor_id'])
    ids = sorted({member['raw_id'] for member in payload['members']})
    versions, reviewed_archives = _source_inventory(project, cut, ids)
    checked = {'source_versions': versions,
               'bindings': metadata_inventory(project, ids)}
    # A historical cut selects only the versions already saved by that date.
    # Missing/rekeyed approved sources are drift too, not proof of absence.
    import developaid_monitor_contracts as contracts
    cut = contracts._cut(cut)
    approved = {member['source_token'] for member in payload['members'] if member['source_date'] <= cut}
    current = {member['source_token'] for member in checked['source_versions']}
    approved_archives = [sid for sid in payload['reviewed_archives'] if sid[:10] <= cut]
    confirmed = (bool(current) and current == approved and reviewed_archives == approved_archives
                 and (source_token is None or source_token in current))
    conflicts = _binding_conflicts(checked['bindings'])
    return {'status': 'confirmed' if confirmed else 'source_conflict',
            'logical_id': payload['anchor_id'] if confirmed else None,
            'raw_id': raw_id, 'member_ids': ids, 'canonical_number': payload['canonical_number'],
            'decision_id': active['event_id'], 'decision_recorded_at': active['recorded_at'],
            'source_versions': checked['source_versions'], 'bindings': checked['bindings'],
            'reviewed_archives': reviewed_archives,
            'binding_conflicts': conflicts, 'binding_resolution': 'conflict_or_unknown' if conflicts else 'not_combined',
            'financial_acceptance': False, 'legal_signature_status': 'unknown',
            'annotation': 'Позднее уточнение владельца от '+active['recorded_at']+'. Исходные реквизиты и даты сохранены.',
            'reason': '' if confirmed else 'Есть непроверенная или изменённая версия источника; уточнение к ней не применено.'}
