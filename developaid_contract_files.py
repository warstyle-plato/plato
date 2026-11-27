"""Contract PDFs uploaded into the contract card of «Договоры».

A file belongs to one contract of the register (its 64-hex id). The PDF is kept
next to its read result, so a newer reader reads it again instead of serving a
frozen answer. A document that names another contract is refused: a schedule
of a neighbouring contract must not become this one's plan. Each contract or
supplementary agreement is an edition; two files of one edition are both kept
and named, the choice is the owner's. Positions of each estimate are proposed
links to the schedule of the latest edition at or before it; the owner's
choices (`links.json`) are laid over the proposals. A removed file stays on
disk with the time of removal and can be returned. Authenticate first.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
import threading
from pathlib import Path

import developaid_contract_act_dates as act_dates
import developaid_contract_acts as acts_in_card
import developaid_contract_documents as documents
import developaid_contract_control as control
import developaid_contract_comparison as comparison
import developaid_contract_fact as fact
import developaid_contract_link_choices as choices
import developaid_contract_plan as plan
import developaid_contract_scan as scan
import developaid_contract_schedule_links as links
import developaid_contract_terms as terms
import developaid_contract_price as price
import developaid_contract_stage_profile as stage_profile

MAX_BYTES = 20 * 1024 * 1024
CHOICES = "links.json"
MAX_PARSE_REFRESH_FILES = 64
MAX_PARSE_REFRESH_BYTES = 64 * 1024 * 1024


class ContractFilesProblem(ValueError):
    """A controlled, safe message that may be returned to an authenticated user."""


class ParseRefreshRequired(ContractFilesProblem):
    """The bounded register must prepare its old derived reads separately."""


def _directory(project: str, contract_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", str(contract_id or "")):
        raise ContractFilesProblem("Выберите договор из списка.")
    if not str(project or "").strip():
        raise ContractFilesProblem("Выберите проект.")
    # Initial source commits pin this namespace while native merge holds the
    # same global aliases lock. Follow that pin even if aliases change late.
    import developaid_contract_identity_store as namespace
    try:
        root = namespace.project_root(project)
    except namespace.IdentityProblem as exc:
        raise ContractFilesProblem(str(exc)) from None
    return root / "contract_documents" / contract_id


def _write(path: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(prefix=".part-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


_held = threading.local()


@contextlib.contextmanager
def _locked(folder: Path):
    """One writer per card across both workers; a thread already holding the card's lock goes on."""
    import developaid_contract_identity_store as identity_store
    if str(folder / ".lock") in identity_store._HELD_NATIVE_LOCKS.get():
        yield
        return
    held = _held.__dict__.setdefault("folders", set())
    key = str(folder)
    if key in held:
        yield
        return
    if folder.is_symlink() or folder.parent.is_symlink():
        raise ContractFilesProblem('Происхождение каталога договора не подтверждено.')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        import fcntl
    except ImportError:
        raise ContractFilesProblem("Сохранение в карточке договора недоступно в этой среде.") from None
    try:
        descriptor = os.open(folder / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise ContractFilesProblem('Блокировка карточки договора недоступна.') from None
    with os.fdopen(descriptor, "a+b") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ContractFilesProblem('Блокировка карточки договора не подтверждена.')
        fcntl.flock(handle, fcntl.LOCK_EX)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)


def _json(path: Path, value) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _shown(iso: str | None) -> str:
    return ".".join(reversed(iso.split("-"))) if iso else "без даты"


def _same_contract(found: dict | None, row: dict) -> str:
    """Empty when the document names the card's contract; otherwise the reason."""
    from developaid_monitor_contracts import _contract_number
    if not found:
        return ""
    number = _contract_number(found.get("number"), reference=True)
    expected = _contract_number(row.get("contract"), reference=True)
    date, expected_date = found.get("date"), row.get("contract_date")
    if number == expected and (not expected_date or date == expected_date):
        return ""
    return (f"В документе договор № {found.get('number')} от {_shown(date)}, а в карточке — "
            f"договор № {row.get('contract') or '—'} от {_shown(expected_date)}. "
            "Загрузите документ этого договора.")


def awaits_confirmation(record: dict) -> bool:
    """A scan whose recognised header the user has not confirmed: shown in the card, counted nowhere."""
    return bool(record.get("scan")) and not record["scan"].get("confirmed_at")


def _named_in_scan(record: dict, row: dict) -> bool:
    """The card's contract number stands in the recognised text of the scan."""
    from developaid_monitor_contracts import _contract_number
    expected = _contract_number(row.get("contract"), reference=True)
    return bool(expected) and expected in _contract_number((record.get("scan") or {}).get("text"))


def _record(sha: str, filename: str, content: bytes, uploaded_at: str) -> dict:
    try:
        read = documents.read(content)
    except ValueError as exc:
        raise ContractFilesProblem(str(exc)) from None
    return {"sha256": sha, "filename": filename, "uploaded_at": uploaded_at,
            "reader": documents.READER_VERSION, **read}


def store(project: str, row: dict, filename: str, content: bytes, *, source_policy: dict | None = None) -> dict:
    """Keep a PDF; optional automatic intake preserves existing source lifecycles."""
    if source_policy is not None:
        return _store_preserving_sources(project, row, filename, content, source_policy)
    return _store_core(project, row, filename, content)


def _store_core(project: str, row: dict, filename: str, content: bytes, *, allow_restore=True, before_write=None) -> dict:
    """Read and keep one PDF of the contract `row`; the same file twice is one file."""
    folder = _directory(project, row.get("id"))
    if not content or len(content) > MAX_BYTES:
        raise ContractFilesProblem("Выберите непустой PDF размером не больше 20 МБ.")
    if not content.startswith(b"%PDF"):
        raise ContractFilesProblem("Файл не открылся как PDF. Сохраните документ в PDF заново, например выгрузкой из системы электронного документооборота, и загрузите ещё раз.")
    sha = hashlib.sha256(content).hexdigest()
    folder = _document_folder(project, row.get('id'), sha, {'document_source_ids': row.get('document_source_ids') or []})
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Identity inventory/CAS shares this native lock, including first upload.
    with _locked(folder):
        existing = folder / f"{sha}.json"
        if existing.exists() and (folder / f"{sha}.pdf").exists():
            if not allow_restore:
                record = _preserved_record(folder, sha)
                return {**_summary(record), "already": True, "restored": False,
                        "preserved_removed": bool(record.get('removed_at'))}
            record = _current(folder, sha)
            restored = bool(record.pop("removed_at", None))
            if restored:
                _json(existing, record)
            return {**_summary(record), "already": True, "restored": restored}
        record = _record(sha, Path(str(filename or "")).name[:240] or "документ.pdf", content, _now())
        if record.get("scan"):
            # A misread number does not refuse a scan: the contract is checked again when it is confirmed.
            record["scan"]["card_number_found"] = _named_in_scan(record, row)
        else:
            reason = _same_contract(record.get("contract"), row)
            if reason:
                raise ContractFilesProblem(reason)
        if (record.get('schedule') or {}).get('lines') and any(
                (prior.get('schedule') or {}).get('lines') and not prior.get('removed_at')
                for prior in _all_records(_folders(project, row['id'], row))):
            # Existing saved graphs retain their provenance. A newly uploaded
            # replacement needs explicit evidence of the signed current edition.
            record['gpr_pending'] = True
        if before_write is not None:
            before_write(record)
        _write(folder / f"{sha}.pdf", content)
        _json(existing, record)
        return {**_summary(record), "already": False, "restored": False}


def source_family(project: str, row: dict) -> list[str]:
    folders = _folders(project, row['id'], row)
    identifiers = [folder.name for folder in folders]
    if not 1 <= len(identifiers) <= 8:
        raise ContractFilesProblem('Состав исходных карточек требует отдельной сверки.')
    return identifiers


def source_preservation_guard(project: str, row: dict) -> dict:
    import developaid_contract_identity as identity
    import developaid_monitor_ledgers as ledgers
    family = source_family(project, row)
    return {'family': family,
            'bindings_sha256': identity_store_digest(identity.metadata_inventory(project, family, correction=True)),
            'archive_revision': ledgers.snapshot_inventory(project)['revision'],
            'decision_head': namespace_decision_head(project)}


def namespace_decision_head(project):
    import developaid_contract_identity_store as namespace
    return namespace.load(project)['head']


def identity_store_digest(value):
    import developaid_contract_identity_store as namespace
    return namespace.digest(value)


def _preserved_record(folder: Path, sha: str) -> dict:
    import developaid_contract_identity_store as namespace
    raw = namespace.read_bytes(folder/(sha+'.pdf'), MAX_BYTES)
    metadata = namespace.read_bytes(folder/(sha+'.json'), 16*1024*1024)
    if not raw or hashlib.sha256(raw).hexdigest() != sha or not metadata:
        raise ContractFilesProblem('Сохранённый исходник не совпал с отпечатком; автоматический приём остановлен.')
    record = namespace.strict_json(metadata)
    if not isinstance(record, dict) or record.get('sha256') != sha:
        raise ContractFilesProblem('Сохранённая карточка исходника не подтверждена.')
    return record


def _store_preserving_sources(project, row, filename, content, expected):
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as namespace
    if namespace._NAMESPACE.get() is None:
        raise ContractFilesProblem('Для автоматического приёма пространство проекта должно быть закреплено.')
    family = source_family(project, row)
    if (not isinstance(expected, dict) or set(expected) != {'family','bindings_sha256','archive_revision','decision_head'}
            or expected.get('family') != family
            or any(not re.fullmatch(r'[0-9a-f]{64}', str(expected.get(key) or '')) for key in ('bindings_sha256','archive_revision','decision_head'))):
        raise ContractFilesProblem('Проверка исходников относится к другому составу карточек.')
    if not content or len(content) > MAX_BYTES or not content.startswith(b'%PDF'):
        raise ContractFilesProblem('Выберите непустой PDF размером не больше 20 МБ.')
    sha = hashlib.sha256(content).hexdigest()
    # Identity/project lock is held by the caller. Acquire the complete family
    # in native global order before choosing a storage target or pinning state.
    import contextlib
    wanted = {str(path) for path in identity.binding_lock_paths(project, family, correction=True)}
    held = namespace._HELD_NATIVE_LOCKS.get()
    if held and not wanted.issubset(held):
        raise ContractFilesProblem('Неполная блокировка источников. Повторите приём через текущую карточку.')
    lock = contextlib.nullcontext() if wanted.issubset(held) else identity._binding_locks(project, family, correction=True)
    with lock:
        folder = _document_folder(project, row['id'], sha, row)
        if (folder/(sha+'.json')).exists() or (folder/(sha+'.pdf')).exists():
            record = _preserved_record(folder, sha)
            return {**_summary(record), 'already': True, 'restored': False,
                    'preserved_removed': bool(record.get('removed_at')),
                    'source_policy_guard': source_preservation_guard(project, row)}
        if source_preservation_guard(project, row) != expected:
            raise ContractFilesProblem('Состояние исходников изменилось. Повторите проверку перед применением.')
        def before_write(record):
            namespace.assert_namespace(project)
            if source_preservation_guard(project, row) != expected:
                raise ContractFilesProblem('Источники изменились во время разбора. Автоматический приём остановлен.')
            header = record.get('contract')
            if (not isinstance(header, dict) or not isinstance(header.get('number'), str)
                    or not header['number'].strip() or namespace.day(header.get('date')) is None
                    or _same_contract(header, row)):
                raise ContractFilesProblem('В исходном PDF не подтверждены номер и дата этого договора.')
        result = _store_core(project, row, filename, content, allow_restore=False, before_write=before_write)
        return {**result, 'source_policy_guard': source_preservation_guard(project, row)}


def _stored(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ContractFilesProblem("Сохранённый документ договора не прочитан; проверьте хранилище проекта.") from None


def _requires_refresh(record: dict) -> bool:
    if record.get('reader') == documents.READER_VERSION or record.get('scan') is not None:
        return False
    reader = record.get('reader')
    if isinstance(reader, int) and not isinstance(reader, bool) and reader > documents.READER_VERSION:
        raise ContractFilesProblem('Версия сохранённого разбора новее установленной. '
                                   'Документ не изменён; требуется проверка версии приложения.')
    return True


def _current(folder: Path, sha: str) -> dict:
    """The stored read, read again from the PDF when the reader has changed since.

    The new read is written under the card's lock over the record as it is then: a removal
    written meanwhile by the other worker is kept, not overwritten by the older copy.
    """
    path = folder / f"{sha}.json"
    record = _stored(path)
    # A scan is not recognised again by a newer reader of text: its confirmed header stays as confirmed.
    if not _requires_refresh(record):
        return record
    with _locked(folder):
        record = _stored(path)
        if not _requires_refresh(record):
            return record
        return _reread(folder, sha, record)


def _reread(folder: Path, sha: str, record: dict, verified_bytes: bytes | None = None,
            price_provenance: dict | None = None, expected_metadata_sha256: str | None = None,
            _metadata_read=None, _stage=False) -> dict:
    import developaid_contract_ownership as ownership
    ownership.require_unpinned_refresh(folder.name)
    path, pdf = folder / f"{sha}.json", folder / f"{sha}.pdf"
    if not pdf.exists():
        record.setdefault("warnings", []).insert(
            0, "Файл документа не сохранился: показан прежний разбор, перечитать его нечем.")
        return record
    try:
        import developaid_contract_identity_store as namespace
        raw = verified_bytes if verified_bytes is not None else namespace.read_bytes(pdf, MAX_BYTES)
        if raw is None or hashlib.sha256(raw).hexdigest() != sha:
            raise ContractFilesProblem('Исходный PDF не соответствует сохранённому SHA256; разбор не использован.')
        fresh = _record(sha, record.get("filename", ""), raw, record.get("uploaded_at", ""))
        if record.get("removed_at"):
            fresh["removed_at"] = record["removed_at"]
        if record.get('gpr_pending'):
            fresh['gpr_pending'] = True
            if record.get('gpr_discovery'):
                fresh['gpr_discovery'] = record['gpr_discovery']
        if (not (record.get('schedule') or {}).get('lines')
                and (fresh.get('schedule') or {}).get('lines')):
            # Parser discovery is not evidence that a new signed edition has
            # been accepted. Previously recognised legacy graphs keep their
            # original unknown-signature status; only a newly found graph is
            # held for the separate exact-source activation decision.
            fresh['gpr_pending'] = True
            fresh.setdefault('gpr_discovery', {'reason': 'new_graph_discovered_by_reader',
                'from_reader': record.get('reader'), 'to_reader': documents.READER_VERSION,
                'source_pdf_sha256': sha, 'previous_schedule_sha256': namespace.digest(record.get('schedule')),
                'previous_metadata_sha256': hashlib.sha256(namespace.canonical(record)).hexdigest()})
        if price_provenance:
            import developaid_contract_price_provenance as provenance
            marker = provenance.build(record, fresh, sha, folder.name, raw,
                price_provenance['metadata_sha256'], price_provenance['event'], price_provenance['before'])
            if marker is not None:
                fresh[provenance.FIELD] = marker
    except ContractFilesProblem as exc:
        fresh = {**record, "reader": documents.READER_VERSION, "estimates": [], "schedule": None,
                 "warnings": [str(exc)]}
    if _stage:
        return fresh
    _publish_reread(path, fresh, expected_metadata_sha256, _metadata_read)
    return fresh


def _publish_reread(path, fresh, expected_metadata_sha256, metadata_read=None):
    import developaid_contract_ownership as ownership
    ownership.require_unpinned_refresh(path.parent.name)
    if expected_metadata_sha256:
        import developaid_contract_identity_store as namespace
        current = (metadata_read.read(path) if metadata_read is not None else namespace.read_bytes(path, 4*1024*1024))
        if current is None or hashlib.sha256(current).hexdigest() != expected_metadata_sha256:
            raise ContractFilesProblem('Исходные привязки изменились во время обновления разбора. Обновите реестр.')
    _json(path, fresh)


def refresh_parse_cache(project: str, groups: list[tuple[tuple[str, ...], bool]], budget: dict | None = None,
                        approvals: dict | None = None, *, selected_documents: frozenset | None = None,
                        _proof_budget=None, _future_price_passes=None) -> dict | None:
    """Refresh bounded derived caches BEFORE the first ownership binding pin.

    The caller passes only already relevant native identity groups. Existing
    metadata validation supplies the no-follow/size/file-count boundary; the
    same sorted card locks serialize refresh and owner document mutations.
    Nothing here refreshes, drops or approves a previously captured pin.
    """
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as namespace
    budget = budget if budget is not None else {'files': 0, 'bytes': 0, 'metadata_files': 0, 'metadata_bytes': 0}
    approvals = approvals or {}
    before_read, after_read = None, None
    scan_read = _proof_budget.phase() if _proof_budget is not None else None
    groups = [(tuple(identity.correction_ids(list(members)) if correction else identity._ids(list(members))), correction)
              for members, correction in groups]
    if selected_documents is not None and (len(selected_documents) != 1 or any(
            not isinstance(item, tuple) or len(item) != 2
            or not all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in item)
            or not any(item[0] in members for members, _ in groups) for item in selected_documents)):
        raise ContractFilesProblem('Состав отдельного обновления документа не подтверждён.')
    identifiers = sorted({identifier for members, _ in groups for identifier in members})
    folders = [identity._safe_path(project, 'contract_documents', identifier) for identifier in identifiers]

    def cached(path, reader):
        raw = reader.read(path) if reader is not None else namespace.read_bytes(path, 4*1024*1024)
        if reader is None:
            budget['metadata_files'] += raw is not None
            budget['metadata_bytes'] += len(raw or b'')
        if _proof_budget is None and (budget['metadata_files'] > identity.MAX_FILES or budget['metadata_bytes'] > identity.MAX_METADATA_BYTES):
            raise ContractFilesProblem('Метаданные обновления разборов превышают предел одной сборки.')
        if raw is None:
            raise ContractFilesProblem('Метаданные документа изменились до обновления разбора.')
        value = namespace.strict_json(raw)
        if not isinstance(value, dict):
            raise ContractFilesProblem('Метаданные документа договора не подтверждены.')
        return value, raw

    # No writer lock is acquired from inside an existing single-card lock.
    # First identify the complete groups that actually require an upgrade.
    stale = set()
    for folder in folders:
        for path in sorted(folder.glob('*.json')):
            if re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                if selected_documents is not None and (folder.name, path.stem) not in selected_documents:
                    continue
                value, _ = cached(path, scan_read)
                if _requires_refresh(value):
                    stale.add(folder.name)
    groups = [(members, correction) for members, correction in groups if stale.intersection(members)]
    if not groups:
        return
    identifiers = sorted({identifier for members, _ in groups for identifier in members})
    folders = [identity._safe_path(project, 'contract_documents', identifier) for identifier in identifiers]
    held = {str(Path(value).absolute()) for value in _held.__dict__.get('folders', set())}
    for value in namespace._HELD_NATIVE_LOCKS.get():
        path = Path(value)
        if path.name == '.lock' and path.parent.parent.name == 'contract_documents':
            held.add(str(path.parent.absolute()))
    if held and not {str(folder.absolute()) for folder in folders} <= held:
        raise ContractFilesProblem('Для обновления разборов нужна полная блокировка исходных карточек. '
                                   'Обновите реестр перед повторной операцией.')
    with contextlib.ExitStack() as locks:
        for folder in sorted(folders):
            locks.enter_context(_locked(folder))
        if _proof_budget is not None:
            # All are reserved before any own write. None shares cached
            # bytes with preflight, the write CAS, or the final read seal.
            before_read = _proof_budget.phase()
            write_read = _proof_budget.phase()
            after_read = _proof_budget.phase()
        else:
            write_read = None
        # Validate under native locks, before reading or writing derived data.
        before_by_group = {}
        for members, correction in groups:
            inventory = identity.metadata_inventory(project, list(members), correction=correction,
                _read=before_read.inventory() if before_read is not None else None)
            before_by_group[members] = inventory
            if before_read is None:
                budget['metadata_files'] += inventory['metadata_files_read']
                budget['metadata_bytes'] += inventory['metadata_bytes_read']
                budget['files'] += inventory.get('price_source_files_read', 0)
                budget['bytes'] += inventory.get('price_source_bytes_read', 0)
            if _proof_budget is None and (budget['metadata_files'] > identity.MAX_FILES or budget['metadata_bytes'] > identity.MAX_METADATA_BYTES):
                raise ContractFilesProblem('Метаданные обновления разборов превышают предел одной сборки.')
            if budget['files'] > MAX_PARSE_REFRESH_FILES or budget['bytes'] > MAX_PARSE_REFRESH_BYTES:
                raise ContractFilesProblem('Объём проверки источников цены превышает предел одной сборки.')
        candidates = []
        for folder in folders:
            for path in sorted(folder.glob('*.json')):
                if not re.fullmatch(r'[0-9a-f]{64}\.json', path.name):
                    continue
                if selected_documents is not None and (folder.name, path.stem) not in selected_documents:
                    continue
                record, metadata = cached(path, before_read)
                if not _requires_refresh(record):
                    continue
                pdf = folder/(path.stem+'.pdf')
                if not pdf.exists():
                    raise ContractFilesProblem('Исходный PDF для обновления разбора не найден. Проверьте хранилище проекта.')
                # The parser receives these exact no-follow descriptor bytes.
                read_cap = MAX_BYTES
                if _proof_budget is not None:
                    read_cap = min(read_cap, (MAX_PARSE_REFRESH_BYTES-budget['bytes'])//2)
                    if budget['files']+2 > MAX_PARSE_REFRESH_FILES or pdf.lstat().st_size > read_cap:
                        raise ParseRefreshRequired('Объём обновления разборов превышает предел одной сборки. Обновите документы отдельной операцией.')
                raw = namespace.read_bytes(pdf, read_cap)
                if raw is None or hashlib.sha256(raw).hexdigest() != path.stem:
                    raise ContractFilesProblem('Исходный PDF не соответствует сохранённому SHA256; обновление разбора отменено.')
                # Reserve the second verified descriptor read before any
                # writes, so source-validation budget failure is preflight.
                budget['bytes'] += 2*len(raw)
                budget['files'] += 2
                provenance_context = None
                for members, _ in groups:
                    if folder.name not in members:
                        continue
                    before = before_by_group[members]
                    card = next((card for card in before['cards'] if card['raw_id'] == folder.name), {})
                    previous = next((doc for doc in card.get('documents') or [] if doc['document_sha256'] == path.stem), {})
                    if (previous.get('metadata') or {}).get('sha256') != hashlib.sha256(metadata).hexdigest():
                        raise ContractFilesProblem('Метаданные документа изменились до обновления разбора.')
                    event = approvals.get(members)
                    if event and ((event['payload'].get('price_document_evidence') or {}).get('document_sha256') == path.stem
                                  and event['payload']['roles']['price_raw_id'] == folder.name):
                        provenance_context = {'event': event, 'before': before,
                                              'metadata_sha256': hashlib.sha256(metadata).hexdigest()}
                if _proof_budget is None:
                    budget['metadata_files'] += 1
                    budget['metadata_bytes'] += len(metadata)
                    if budget['metadata_files'] > identity.MAX_FILES or budget['metadata_bytes'] > identity.MAX_METADATA_BYTES:
                        raise ContractFilesProblem('Метаданные обновления разборов превышают предел одной сборки.')
                candidates.append((folder, path.stem, record, raw, provenance_context, hashlib.sha256(metadata).hexdigest()))
                if budget['files'] > MAX_PARSE_REFRESH_FILES or budget['bytes'] > MAX_PARSE_REFRESH_BYTES:
                    raise ParseRefreshRequired('Объём обновления разборов превышает предел одной сборки. Обновите документы отдельной операцией.')
        own_writes, staged, future_pdfs = {}, [], {}
        for folder, sha, record, raw, provenance_context, previous_metadata in candidates:
            fresh = _reread(folder, sha, record, raw, provenance_context, previous_metadata,
                            _metadata_read=write_read, _stage=_proof_budget is not None)
            written = json.dumps(fresh, ensure_ascii=False, allow_nan=False).encode('utf-8')
            if _proof_budget is not None:
                _proof_budget.reserve_output(folder/(sha+'.json'), len(written))
                staged.append((folder/(sha+'.json'), fresh, previous_metadata))
                if 'price_reader_provenance' in fresh:
                    future_pdfs[folder/(sha+'.pdf')] = len(raw)
            own_writes[(folder.name, sha)] = (hashlib.sha256(written).hexdigest(),
                                              'price_reader_provenance' in fresh)
        if _proof_budget is not None:
            # After inventory, first pin, two nested validations, final seal,
            # and a strict resolver where present: PDF caps are not multiplied.
            after_pdfs = {path: len(raw or b'') for path, raw in before_read.pdfs.items()}
            after_pdfs.update(future_pdfs)
            passes = (4+any(not correction for _, correction in groups)
                      if _future_price_passes is None else _future_price_passes)
            _proof_budget.reserve_price_proofs(future_pdfs, passes, after_pdfs)
            for folder, sha, _, _, _, _ in candidates:
                raw = namespace.read_bytes(folder/(sha+'.pdf'), MAX_BYTES)
                if raw is None or hashlib.sha256(raw).hexdigest() != sha:
                    raise ContractFilesProblem('Исходный PDF изменился во время обновления разбора.')
            for path, fresh, previous_metadata in staged:
                _publish_reread(path, fresh, previous_metadata, write_read)
        else:
            for folder, sha, _, _, _, _ in candidates:
                raw = namespace.read_bytes(folder/(sha+'.pdf'), MAX_BYTES)
                if raw is None or hashlib.sha256(raw).hexdigest() != sha:
                    raise ContractFilesProblem('Исходный PDF изменился во время обновления разбора.')

        def sealed(inventory, *, after=False):
            observed = copy.deepcopy(inventory)
            # Diagnostic read counters change with our new derived witness;
            # the actual ReadContext still pins every field, including them.
            for key in ('metadata_files_read', 'metadata_bytes_read',
                        'price_source_files_read', 'price_source_bytes_read'):
                observed.pop(key, None)
            for card in observed['cards']:
                for index, document in enumerate(card['documents']):
                    key = (card['raw_id'], document['document_sha256'])
                    if key not in own_writes:
                        continue
                    expected, price_witness = own_writes[key]
                    if after and ((document.get('metadata') or {}).get('sha256') != expected
                            or price_witness and (document.get('price_reader_provenance') or {}).get('state') != 'verified'):
                        raise ContractFilesProblem('Исходные привязки изменились во время обновления разбора. Обновите реестр.')
                    card['documents'][index] = {'document_sha256': key[1], 'own_refresh_sha256': expected}
            return observed

        # Only exact bytes written by this controlled refresh may differ.
        # An owner deadline/links/header or any other metadata edit during
        # parsing cannot be absorbed into the first ownership binding pin.
        for members, correction in groups:
            after = identity.metadata_inventory(project, list(members), correction=correction,
                _read=after_read.inventory() if after_read is not None else None)
            if after_read is None:
                budget['metadata_files'] += after['metadata_files_read']
                budget['metadata_bytes'] += after['metadata_bytes_read']
                budget['files'] += after.get('price_source_files_read', 0)
                budget['bytes'] += after.get('price_source_bytes_read', 0)
            if ((_proof_budget is None and (budget['metadata_files'] > identity.MAX_FILES or budget['metadata_bytes'] > identity.MAX_METADATA_BYTES))
                    or budget['files'] > MAX_PARSE_REFRESH_FILES or budget['bytes'] > MAX_PARSE_REFRESH_BYTES):
                raise ContractFilesProblem('Общий объём проверки обновлённых разборов превышает предел одной сборки.')
            if sealed(before_by_group[members]) != sealed(after, after=True):
                raise ContractFilesProblem('Исходные привязки изменились во время обновления разбора. Обновите реестр.')
        return own_writes


def _edition(record: dict) -> tuple:
    act = record.get("act")
    if act:
        # An act of acceptance is no edition of the plan: it follows the contract and its agreements.
        number = act.get("number") or ""
        return (2, act.get("date") or "", int(number) if number.isdigit() else 0)
    agreement = record.get("agreement")
    if not agreement:
        return (0, (record.get("contract") or {}).get("date") or "", 0)
    number = agreement.get("number") or ""
    return (1, agreement.get("date") or "", int(number) if number.isdigit() else 0)


def _title(record: dict) -> str:
    agreement, contract, act = record.get("agreement"), record.get("contract"), record.get("act")
    if act:
        return f"Акт КС-2 № {act.get('number') or 'без номера'} от {_shown(act.get('date'))}"
    if agreement:
        return f"Дополнительное соглашение № {agreement['number']} от {_shown(agreement.get('date'))}"
    if contract:
        return f"Договор № {contract['number']} от {_shown(contract.get('date'))}"
    return "Документ без номера договора и соглашения"


def _summary(record: dict) -> dict:
    schedule = record.get("schedule") or {}
    return {"sha256": record["sha256"], "filename": record.get("filename", ""), "title": _title(record),
            "estimates": len(record.get("estimates") or []), "schedule_lines": len(schedule.get("lines") or []),
            "corrections": len(schedule.get("corrections") or [])}


def _records(folder: Path) -> list[dict]:
    """Documents in the card, contract first, agreements by date; removed ones are not among them."""
    records = [_current(folder, path.stem) for path in sorted(folder.glob("*.json"))
               if re.fullmatch(r"[0-9a-f]{64}", path.stem)]
    records.sort(key=lambda r: (_edition(r), r.get("uploaded_at", ""), r["sha256"]))
    for record in records:
        record["title"] = _title(record)
    return records


def _folders(project: str, contract_id: str, found: dict | None = None) -> list[Path]:
    """Native archive IDs stay unchanged; initial PDF folders stay at their source IDs."""
    identifiers = [contract_id, *((found or {}).get('document_source_ids') or [])]
    return [_directory(project, identifier) for identifier in dict.fromkeys(identifiers)]


def _all_records(folders: list[Path]) -> list[dict]:
    records = {}
    for folder in reversed(folders):
        records.update({record['sha256']: record for record in _records(folder)})
    return sorted(records.values(), key=lambda r: (_edition(r), r.get('uploaded_at', ''), r['sha256']))


def _document_folder(project: str, contract_id: str, sha: str, found: dict | None = None) -> Path:
    if not re.fullmatch(r'[0-9a-f]{64}', str(sha or '')):
        raise ContractFilesProblem('Документ не найден в карточке: обновите карточку.')
    folders = _folders(project, contract_id, found)
    return next((folder for folder in folders if (folder / (sha+'.json')).exists()), folders[0])


def _in_force(records: list[dict]):
    """Each estimate with the latest schedule at or before its edition."""
    current = None
    for record in records:
        if (record.get("schedule") or {}).get("lines"):
            current = record
        for index, estimate in enumerate(record.get("estimates") or []):
            yield record, index, estimate, current


def _proposal(record: dict, estimate: dict, schedule: dict | None) -> dict:
    return links.propose(estimate, schedule and schedule["schedule"], agreement=bool(record.get("agreement")))


def _date(record: dict) -> str | None:
    return ((record.get("agreement") or record.get("contract")) or {}).get("date")


def _remaining_starts(records: list[dict]) -> dict:
    """Replacing the same remaining annex does not accept all work done since its first edition.

    Carry its start only within an explicitly dated annex series following the
    same accepted-work snapshot. A new accepted snapshot (including a separate
    PDF of the same agreement), another annex, or a full estimate starts a new
    series. Incomplete identifiers never establish continuity.
    """
    accepted = [r for r in records if _date(r) and
                any(e.get('scope') == 'accepted' for e in r.get('estimates') or [])]
    starts, previous = {}, None
    for record in records:
        estimates = [e for e in record.get('estimates') or [] if e.get('scope') != 'accepted']
        if not estimates:
            continue
        if any(e.get('scope') != 'remaining' for e in estimates):
            previous = None
            if any(e.get('scope') == 'remaining' for e in estimates):
                starts[record['sha256']] = {'date': _date(record), 'sha256': record['sha256'],
                                            'title': record['title']}
            continue
        agreement = record.get('agreement') or {}
        explicit = bool(agreement.get('number') and agreement.get('date')) and all(
            e.get('annex') and e.get('edition') == agreement for e in estimates)
        annexes = tuple(sorted(e.get('annex') or '' for e in estimates))
        epoch = max((_edition(r) for r in accepted if _edition(r) <= _edition(record)), default=None)
        key = (annexes, epoch) if explicit and epoch is not None else None
        basis = (previous[1] if key is not None and previous and previous[0] == key else
                 {'date': _date(record), 'sha256': record['sha256'], 'title': record['title']})
        starts[record['sha256']] = basis
        previous = (key, basis)
    return starts



def _editions(records: list[dict], chosen: dict) -> list[dict]:
    """Documents that bring an estimate or a schedule, each with the latest of both at or before it."""
    editions, schedule, source = [], None, None
    remaining_starts = _remaining_starts(records)
    for record in records:
        brings_schedule = bool((record.get("schedule") or {}).get("lines"))
        brings_estimate = any(e.get("scope") != "accepted" for e in record.get("estimates") or [])
        schedule = record if brings_schedule else schedule
        source = record if brings_estimate else source
        if source is None or not (brings_schedule or brings_estimate):
            continue
        estimates = []
        for estimate in source["estimates"]:
            if estimate["links"]["schedule_sha256"] != (schedule["sha256"] if schedule else ""):
                # A newer schedule without a new estimate: the links are carried onto it.
                estimate = {**estimate, "links": choices.apply(_proposal(source, estimate, schedule), chosen,
                                                               schedule and schedule["schedule"])}
            estimates.append(estimate)
        remaining = any(e.get("scope") == "remaining" for e in source["estimates"])
        editions.append({"sha256": record["sha256"], "title": record["title"], "date": _date(record),
                         "estimates": estimates, "estimate_title": source["title"],
                         "estimate_sha256": source['sha256'],
                         "schedule": schedule and schedule["schedule"],
                         "schedule_sha256": schedule["sha256"] if schedule else "",
                         "schedule_title": schedule["title"] if schedule else "",
                         "start": remaining_starts[source['sha256']]['date'] if remaining else None,
                         "start_source": remaining_starts.get(source['sha256']) if remaining else None})
    return editions


def _choices(folder: Path) -> dict:
    try:
        stored = json.loads((folder / CHOICES).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        raise ContractFilesProblem("Сохранённые связи с графиком не прочитаны; проверьте хранилище проекта.") from None
    return stored.get("choices") or {}


def document_terms(project: str, contract_id: str, cut: str, source_ids: list[str] | None = None) -> dict:
    """Source-bound conditions, read from the same saved PDFs as the card."""
    return terms.resolve(_all_records(_folders(project, contract_id, {'document_source_ids': source_ids or []})), cut)


def document_prices(project: str, contract_id: str, cut: str, source_ids: list[str] | None = None) -> dict:
    """Explicit full price from saved clauses; never an estimate's maximum total."""
    return price.resolve(_all_records(_folders(project, contract_id, {'document_source_ids': source_ids or []})), cut)


@stage_profile.stage('card_listing')
def listing(project: str, contract_id: str, cut: str = "", acts: dict | None = None) -> dict:
    # One source/anchor snapshot across both workers, including projections and
    # the exported read guard. Reads never combine old dates with a new graph.
    folders = _folders(project, contract_id, acts)
    with contextlib.ExitStack() as locks:
        for folder in sorted(folders):
            if folder.is_dir():
                locks.enter_context(_locked(folder))
        return _listing(project, contract_id, cut, acts)


def _listing(project: str, contract_id: str, cut: str = "", acts: dict | None = None) -> dict:
    """Every document in the card with its links, the accumulated plan and fact on `cut` and the removed files.

    `acts` are the KS-6a works of the contract on `cut` (`fact.acts`); None when the register has none.
    """
    folders = _folders(project, contract_id, acts)
    cut = cut or dt.date.today().isoformat()
    if not any(candidate.is_dir() for candidate in folders):
        acts = act_dates.resolve(acts, [], cut)
        performed = acts_in_card.accumulated([], cut)
        return _with_control({"contract_id": contract_id, "documents": [], "removed": [],
                              "plan": plan.build([], cut), "fact": _fact([], None, acts, cut, performed),
                              "performed": performed}, acts, cut)
    every = _all_records(folders)
    import developaid_contract_gpr as gpr
    history = sorted((event for folder in folders for event in gpr.events(folder)),
                     key=lambda event: (event['recorded_at'], event['event_id']))
    records = gpr.project_records([r for r in every if not r.get("removed_at")], history)
    # An unconfirmed scan is listed with its proposal; the plan, the fact and the act dates do not see it.
    counted = gpr.counted([r for r in records if not awaits_confirmation(r)])
    acts = act_dates.resolve(acts, counted, cut)
    performed = acts_in_card.accumulated(counted, cut)
    performed['excluded'].extend({
        'number': r['act'].get('number'), 'date': r['act'].get('date'),
        'sha256': r.get('sha256'), 'filename': r.get('filename'),
        'reason': 'скан, значения не подтверждены'}
        for r in records if awaits_confirmation(r) and r.get('act'))
    for record in records:
        notes = _scan_notes(record) if record.get("scan") else []
        if not record.get("contract"):
            notes.append("Номер договора в документе не прочитан: документ привязан к договору по выбору "
                         "в карточке.")
        # Of the acts of one number the later is in force (`acts_in_card.in_force`); other documents name twins.
        twins = [r["filename"] for r in records if r is not record and _edition(r) == _edition(record)
                 and not acts_in_card.number(record.get("act"))]
        for found in (performed["replaced"], performed["copies"], performed["notes"]):
            if found.get(record["sha256"]):
                notes.append(found[record["sha256"]])
        if record.get("act"):
            record["act_state"] = ("replaced" if record["sha256"] in performed["replaced"] else
                                   "copy" if record["sha256"] in performed["copies"] else "in_force")
        if twins:
            notes.append(f"{record['title']} загружен{'о' if record.get('agreement') else ''} ещё и файлом "
                         f"«{'», «'.join(twins)}». Проверьте, какой из файлов действующий.")
        record["warnings"] = notes + list(record.get("warnings") or [])
        if record.get("schedule"):
            # Редактор связей предлагает строки по тому же правилу, что сервер.
            record["schedule"] = {**record["schedule"], "unfit": links.unfit(record["schedule"])}
    chosen = {key: value for candidate in reversed(folders) for key, value in _choices(candidate).items()}
    for record, _, estimate, schedule in _in_force(counted):
        result = choices.apply(_proposal(record, estimate, schedule), chosen, schedule and schedule["schedule"])
        estimate["links"] = {**result, "schedule": schedule["title"] if schedule else "",
                             "schedule_sha256": schedule["sha256"] if schedule else ""}
    removed = [{"sha256": r["sha256"], "filename": r.get("filename", ""), "title": r["title"],
                "removed_at": r["removed_at"]} for r in every if r.get("removed_at")]
    editions = _editions(counted, chosen)
    planned = plan.build(editions, cut)
    result = _with_control({"contract_id": contract_id, "documents": records, "removed": removed, "plan": planned,
                          "fact": _fact(editions, planned["in_force"], acts, cut, performed),
                          "performed": performed},
                         acts, cut)
    result['gpr'] = gpr.view(project, contract_id, records, folders, cut)
    result['gpr']['document_source_ids'] = (acts or {}).get('document_source_ids') or []
    result['gpr']['staffing'] = gpr.staffing(result['gpr'].get('schedule'), date=cut)
    return result


_SCAN_FIELDS = (("contract", "number", "номер договора"), ("contract", "date", "дата договора"),
                ("agreement", "number", "номер соглашения"), ("agreement", "date", "дата соглашения"),
                ("act", "number", "номер акта"), ("act", "date", "дата акта"),
                ("act", "start", "начало отчётного периода"), ("act", "finish", "конец отчётного периода"))


def _scan_notes(record: dict) -> list[str]:
    """What the card says of a scan: to be checked, or confirmed with the values the user changed."""
    found = record["scan"]
    # The recognised text stays in the store for the contract check; the page gets the header only.
    record["scan"] = {key: value for key, value in found.items() if key != "text"}
    if not found.get("confirmed_at"):
        number = "" if found.get("card_number_found") else (
            " Номер договора из карточки в распознанном тексте не найден: убедитесь, что это документ "
            "этого договора.")
        return [scan.CHECK + number]
    changed = found.get("corrected") or []
    return [f"Шапка прочитана со скана и подтверждена {_shown(found['confirmed_at'][:10])}"
            + (f"; исправлено вручную: {', '.join(changed)}." if changed else "; исправлений не было.")]


def confirm_scan(project: str, row: dict, sha256: str, kind: str, values: dict, cut: str = "",
                 acts: dict | None = None) -> dict:
    """Take the checked header of a scan into the card: from now on it counts like a read document.

    `kind` is what the document is (contract, agreement, act) and `values` its header as the user
    confirmed it; each value that differs from the recognised one is named as corrected by hand.
    """
    folder = _document_folder(project, row.get('id'), sha256, acts)
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")) or not (folder / f"{sha256}.json").exists():
        raise ContractFilesProblem("Документ не найден в карточке: обновите карточку.")
    if kind not in ("contract", "agreement", "act"):
        raise ContractFilesProblem("Выберите, что это за документ: договор, дополнительное соглашение или акт КС-2.")
    text = lambda key: str(values.get(key) or "").strip()[:80]
    day = lambda key: _day(text(key))
    header = {"contract": {"number": documents._contract_number(text("contract_number")) or None,
                           "date": day("contract_date")}, "agreement": None, "act": None}
    if kind == "agreement":
        header["agreement"] = {"number": text("agreement_number") or "б/н", "date": day("agreement_date")}
        if not header["agreement"]["date"]:
            raise ContractFilesProblem("Впишите дату дополнительного соглашения: по ней соглашение встаёт "
                                       "в ряд редакций договора.")
    elif kind == "act":
        header["act"] = {"number": text("act_number") or None, "date": day("act_date"), "start": day("act_start"),
                         "finish": day("act_finish"), "total": None, "positions": [], "table_total": None}
        found = header["act"]
        if not (found["number"] and found["date"] and found["start"] and found["finish"]):
            raise ContractFilesProblem("Впишите номер акта, его дату и обе даты отчётного периода: по ним "
                                       "датируется выполнение в накопительной КС-6а.")
        if found["start"] > found["finish"]:
            raise ContractFilesProblem("Начало отчётного периода позже его конца: проверьте даты акта.")
    elif not (header["contract"]["number"] and header["contract"]["date"]):
        raise ContractFilesProblem("Впишите номер и дату договора.")
    if header["contract"]["number"]:
        reason = _same_contract(header["contract"], row)
        if reason:
            raise ContractFilesProblem(reason)
    else:
        header["contract"] = None
    with _locked(folder):
        record = _current(folder, sha256)
        if not record.get("scan"):
            raise ContractFilesProblem("Этот документ прочитан из текста PDF, подтверждать его не нужно.")
        read = record["scan"].get("read") or {}
        record.update(header)
        # What recognition missed is now filled in by the user; only the tables stay unread.
        record["warnings"] = [scan.TABLES_NOT_READ]
        record["scan"].update(confirmed_at=_now(), kind=kind, corrected=[
            label for part, key, label in _SCAN_FIELDS
            if (header.get(part) or {}).get(key) != (read.get(part) or {}).get(key)
            and (header.get(part) or {}).get(key) is not None])
        _json(folder / f"{sha256}.json", record)
    return listing(project, row.get("id"), cut, acts)


def _day(text: str) -> str | None:
    try:
        return dt.date.fromisoformat(text).isoformat() if text else None
    except ValueError:
        raise ContractFilesProblem(f"Дата «{text}» не прочитана: выберите её в календаре.") from None


def _fact(editions, in_force, acts, cut, performed):
    """KS-6a fact on `cut`, with dates and confirmation supplied by the КС-2."""
    return {**fact.build(editions, in_force, acts, cut, performed),
            "act_dates": (acts or {}).get("act_dates") or []}


def _with_control(listed, acts, cut):
    """The deviation, lag and forecast of the listed plan and fact (step 7)."""
    conditions = terms.resolve(listed.get('documents') or [], cut)
    price_condition = price.resolve(listed.get('documents') or [], cut)
    if price_condition['history']:
        listed['price'] = price_condition
    deadline, label = (acts or {}).get('deadline'), (acts or {}).get('deadline_label') or ''
    if conditions['history']:
        listed['terms'] = conditions
        manual = (acts or {}).get('deadline_manual')
        if not manual:
            deadline = conditions['deadline']
            label = (conditions['source'] or {}).get('label') or ''
    listed["control"] = control.build(listed["plan"], listed["fact"], deadline, label, cut)
    # Known source dates are useful even before money/fact can be matched.
    # They are a source-plan interval, never a legal deadline or a forecast.
    current = next((edition for edition in listed['plan'].get('editions') or [] if edition.get('in_force')), None)
    source_sha = (current or {}).get('schedule_sha256')
    records = listed.get('documents') or []
    source = _schedule_source([record for record in records if record['sha256'] == source_sha]
                              if source_sha else records, cut)
    if source:
        listed['control']['schedule_source'] = source
    identity = _schedule_identity(listed.get('documents') or [],cut)
    # The new undated, source-only fallback needs an explicit contract binding.
    # Keep the existing dated-interval/control policy unchanged.
    binding = (identity or {}).get('contract') or {}
    if not binding.get('number') or not binding.get('date'):
        identity = None
    listed['comparison'] = comparison.build(listed,cut,identity['sha256'] if identity else None)
    # Comparison owns coverage of the full source GPR. Its partial state must
    # reach the register too: no rejected KS period does not mean all works
    # of the contract were matched to the estimate and its current scope.
    listed['control']['coverage'] = dict(listed['comparison']['coverage'])
    if listed['control'].get('statement_summary'):
        listed['control']['statement_summary']['current']['coverage']=dict(listed['comparison']['coverage'])
    if listed['control'].get('total') is not None:
        listed['control']['total']['incomplete'] = bool(
            listed['control']['total'].get('incomplete') or listed['comparison']['coverage']['partial'])
    listed['control']['forecast'] = listed['comparison']['forecast']
    return listed


def _schedule_identity(records, cut):
    """Unique eligible source document; unread dates do not erase its identity."""
    eligible = [r for r in records if not r.get('removed_at') and not r.get('act')
                and r.get('gpr_status') not in {'pending_signed_confirmation', 'conflicting_edition'}
                and not (r.get('scan') and not r['scan'].get('confirmed_at'))
                and (r.get('schedule') or {}).get('lines') and _date(r) and _date(r) <= cut]
    if not eligible:
        return None
    record = max(eligible, key=_edition)
    if sum(_edition(r) == _edition(record) for r in eligible) > 1:
        return None  # Conflicting documents of one edition need an explicit choice.
    return record


def _schedule_source(records, cut):
    record = _schedule_identity(records,cut)
    if record is None:
        return None
    lines = record['schedule']['lines']
    dated = [r for r in lines if r.get('start') and r.get('finish') and r['start'] <= r['finish']]
    if not dated:
        return None
    precision = {line['date_precision'] for line in lines if line.get('date_precision')}
    return {'start': min(r['start'] for r in dated), 'finish': max(r['finish'] for r in dated),
            'title': record.get('title') or _title(record), 'date': _date(record),
            'sha256': record['sha256'], 'dated': len(dated), 'undated': len(lines)-len(dated),
            'assumption': record['schedule'].get('assumption') or '',
            'date_precision': next(iter(precision)) if len(precision) == 1 else None, 'basis': 'source_gpr'}


def _register_control_raw(project: str, register: dict, cut: str) -> dict:
    """Put the card's deviation, lag and forecast on every row of the register as `schedule_control`.

    The numbers are the card's own (`listing`), not a second calculation; a card that fails keeps
    the register and says why in its row.
    """
    for row in register.get("rows") or []:
        try:
            acts = stage_profile.call('card_acts', fact.acts, row)
            listed = listing(project, row.get("_documents_raw_id") or row["id"], cut, acts)
        except ContractFilesProblem as exc:
            row["schedule_control"] = {"documents": None, "note": str(exc)}
            continue
        except Exception as exc:
            logging.getLogger("developaid.monitor").error("Contract card control unavailable (%s)", type(exc).__name__)
            row["schedule_control"] = {"documents": None, "note": "Отчёт по графику договора не построен: документы "
                                       "карточки не прочитаны. Откройте карточку договора и обновите её."}
            continue
        found = listed["control"]
        total, forecast = found["total"] or {}, found["forecast"] or {}
        row["schedule_control"] = {
            "documents": len(listed["documents"]),
            "note": found["note"] if listed["documents"] else "ГПР и расчёт договора в карточку не загружены.",
            **{k: total.get(k) for k in ("state", "lag_days", "ahead_days", "planned", "fact", "deviation", "percent",
                                         "readiness", "plan_share", "plan_done", "overdue_days", "overdue_works",
                                         "auto", "incomplete")},
            "source": found.get("source"), "preliminary": bool(found.get("preliminary")),
            "confirmation": found.get("confirmation"),
            'act_evidence': found.get('act_evidence'),
            'statement_summary': found.get('statement_summary'),
            "left_out": found["left_out"],
            "coverage": found.get("coverage"),
            "components": found.get("components") or {},
            "data_gaps": found["data_gaps"],
            "forecast_scope": forecast.get("scope"),
            "whole_contract_finish": forecast.get("whole_contract_finish"),
            **{k: forecast.get(k) for k in ("finish", "deadline", "from_register", "done", "threat", "days_over",
                                            "days_early", "passed")}}
        if listed.get('gpr'):
            row['schedule_control']['gpr_binding'] = {key: value for key, value in listed['gpr'].items()
                if key in {'project', 'contract_id', 'guard', 'document_source_ids', 'source'}}
        if found.get('schedule_source'):
            row['schedule_control']['schedule_source'] = found['schedule_source']
    return register


@stage_profile.stage('card_controls')
def register_control(project: str, register: dict, cut: str) -> dict:
    import developaid_contract_ownership as ownership
    with ownership.read_scope(project, cut) as context:
        context.require_current(register)
        if not ownership.has_raw_views(register):
            return _register_control_raw(project, register, cut)
        raw = ownership.raw_view(register)
        corrected_ids = {identifier for state in register['logical_ownership']['states'].values()
                         if state.get('membership_confirmed') for identifier in state['member_ids']}
        # Historical raw controls are read lazily when their card is opened.
        # Do not calculate all duplicate source folders and then throw them away.
        _register_control_raw(project, dict(raw, rows=[row for row in raw['rows'] if row['id'] not in corrected_ids]), cut)
        result = ownership.refresh(register, raw)
        import developaid_contract_correction as correction
        for row in result['rows']:
            if not row.get('source_correction'):
                continue
            try:
                active = correction.materialize(result, row)
                active['_documents_raw_id'] = row['source_correction']['roles']['documents_raw_id']
                _register_control_raw(project, {'rows': [active]}, cut)
                row['schedule_control'] = active['schedule_control']
            except correction.store.IdentityProblem as exc:
                row['schedule_control'] = {'state': 'unknown', 'documents': None, 'note': str(exc)}
        return result


def save_links(project: str, contract_id: str, sha256: str, estimate: int, picked: list[dict],
               clear: bool = False, cut: str = "", acts: dict | None = None) -> dict:
    """Confirm, choose or clear links of positions of one estimate; all positions or none are saved."""
    source_folder = _document_folder(project, contract_id, sha256, acts)
    if not (source_folder / (sha256+'.json')).is_file():
        # No documents, no card folder: an id without a card does not get an empty folder.
        raise ContractFilesProblem("Расчёт не найден среди документов карточки: обновите карточку.")
    # Choices belong to the visible card/position, not to the PDF's physical
    # folder. This primary overlay can also suppress inherited source choices.
    folder = _directory(project, contract_id)
    with _locked(folder):
        records = [r for r in _all_records(_folders(project, contract_id, acts)) if not r.get("removed_at")]
        found = next(((record, current, schedule) for record, index, current, schedule in _in_force(records)
                      if record["sha256"] == sha256 and index == estimate), None)
        if found is None:
            raise ContractFilesProblem("Расчёт не найден среди документов карточки: обновите карточку.")
        record, current, schedule = found
        positions = _proposal(record, current, schedule)["positions"]
        stored, now = _choices(folder), _now()
        for choice in picked:
            index = choice.get("index")
            if not isinstance(index, int) or not 0 <= index < len(positions):
                raise ContractFilesProblem("Позиция не найдена в расчёте: обновите карточку.")
            item = positions[index]
            if clear:
                stored[item['key']] = None  # An explicit clear masks lower-priority source folders.
                continue
            try:
                stored[item["key"]] = choices.decide(item, schedule and schedule["schedule"], choice.get("lines"),
                                                     choice.get("shares"), now)
            except choices.LinkChoiceProblem as exc:
                raise ContractFilesProblem(str(exc)) from None
        _json(folder / CHOICES, {"version": 1, "choices": stored})
    return listing(project, contract_id, cut, acts)


def remove(project: str, contract_id: str, sha256: str, *, restore: bool = False, cut: str = "",
           acts: dict | None = None) -> dict:
    """Take a file out of the card, or return it; the file itself is kept."""
    folder = _document_folder(project, contract_id, sha256, acts)
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")) or not (folder / f"{sha256}.json").exists():
        raise ContractFilesProblem("Документ не найден в карточке: обновите карточку.")
    with _locked(folder):
        record = _current(folder, sha256)
        if restore:
            record.pop("removed_at", None)
        else:
            record["removed_at"] = _now()
        _json(folder / f"{sha256}.json", record)
    return listing(project, contract_id, cut, acts)
