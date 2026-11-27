"""Finite, guarded preparation of derived PDF reads, one PDF per native job.

No identity/source decision is appended and no financial input is imported.
The same bounded source-corpus and fresh-proof phases serve preparation and reads.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import re

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_identity as identity
import developaid_contract_identity_store as store
import developaid_contract_ownership as ownership
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from developaid_contract_metadata_budget import MetadataBudget


class PreparationChanged(files.ContractFilesProblem):
    pass


def _corpus(project, cut):
    """Native archive bytes, manifest bytes, roster and namespace generation."""
    folder = identity._safe_path(project, 'cumulative')
    entries = list(folder.iterdir()) if folder.exists() else []
    if len(entries) > identity.MAX_ARCHIVES*4+16:
        raise files.ContractFilesProblem('Число файлов архивов превышает предел подготовки.')
    manifest_bytes = 0
    for path in entries:
        if path.is_symlink():
            raise PreparationChanged('Происхождение архива не подтверждено. Обновите договоры.')
        if path.suffix == '.json' and identity.SNAP.fullmatch(path.stem):
            size = path.stat().st_size
            if size > ledgers.MAX_PARSED_BYTES:
                raise files.ContractFilesProblem('Метаданные архива превышают предел подготовки.')
            manifest_bytes += size
    if manifest_bytes > identity.MAX_TOTAL_ARCHIVE_BYTES:
        raise files.ContractFilesProblem('Объём метаданных архивов превышает предел подготовки.')
    snapshots = [item for item in ledgers.list_snapshots(project)
                 if contracts._date(item.get('taken_at')) and item['taken_at'] <= cut]
    roster = sorted(item['snapshot_id'] for item in snapshots)
    if len(roster) > identity.MAX_ARCHIVES or len(set(roster)) != len(roster):
        raise files.ContractFilesProblem('Состав архивов превышает предел подготовки документов.')
    if any(item['snapshot_id'][:10] != item['taken_at'] for item in snapshots):
        raise PreparationChanged('Дата архива изменилась. Обновите договоры.')
    witnesses, total = [], 0
    for sid in roster:
        if not isinstance(sid, str) or not identity.SNAP.fullmatch(sid):
            raise files.ContractFilesProblem('Идентичность архива для подготовки документов не подтверждена.')
        path = identity._safe_path(project, 'cumulative', sid+'.zip')
        raw = store.read_bytes(path, 20*1024*1024)
        total += len(raw or b'')
        if raw is None or hashlib.sha256(raw).hexdigest() != sid[11:]:
            raise PreparationChanged('Исходный архив изменился. Обновите договоры.')
        if total > identity.MAX_TOTAL_ARCHIVE_BYTES:
            raise files.ContractFilesProblem('Объём архивов превышает предел подготовки документов.')
        manifest = store.read_bytes(identity._safe_path(project, 'cumulative', sid+'.json'), ledgers.MAX_PARSED_BYTES)
        if manifest is None:
            raise PreparationChanged('Метаданные архива изменились. Обновите договоры.')
        witnesses.append({'snapshot_id': sid, 'bytes': len(raw), 'sha256': sid[11:],
                          'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'manifest_bytes': len(manifest)})
    # Two verified archive passes stay within the existing ownership bound.
    if total*2 > ownership.MAX_VERIFIED_READ_BYTES:
        raise files.ContractFilesProblem('Объём повторной проверки архивов превышает предел подготовки.')
    return {'source_context': ledgers.snapshot_job_context(project), 'archives': witnesses}


def _plan(project, cut, context, groups, read, source_context):
    inventories, stale_by_key = [], {}
    for members, correction in groups:
        inventory = identity.metadata_inventory(project, list(members), correction=correction, _read=read.inventory())
        inventories.append({'members': members, 'correction': correction, 'bindings': inventory})
        event = context.active_events.get(members) or {}
        price = event.get('payload', {}).get('price_document_evidence') or {}
        price_key = ((event.get('payload', {}).get('roles') or {}).get('price_raw_id'),
                     price.get('document_sha256')) if event.get('action') == 'correct_sources' else None
        for card in inventory['cards']:
            for document in card['documents']:
                key = (card['raw_id'], document['document_sha256'])
                path = identity._safe_path(project, 'contract_documents', key[0], key[1]+'.json')
                raw = read.read(path)
                if raw is None or hashlib.sha256(raw).hexdigest() != document['metadata']['sha256']:
                    raise PreparationChanged('Документы изменились во время подготовки. Обновите договоры.')
                record = store.strict_json(raw)
                if record.get('reader') == documents.READER_VERSION or record.get('scan') is not None:
                    continue
                reader = record.get('reader')
                if isinstance(reader, bool) or not isinstance(reader, int) or not 0 < reader < documents.READER_VERSION:
                    raise files.ContractFilesProblem('Версия сохранённого разбора не поддерживается. '
                                                     'Документ не изменён; требуется проверка его версии.')
                # Preserve the full human-approved preimage before upgrading
                # any unrelated document in the same source-selection group.
                target = (0 if key == price_key else 1, key, members, correction)
                if key not in stale_by_key or target < stale_by_key[key]:
                    stale_by_key[key] = target
    # Historical groups can overlap after a revocation. A PDF is still read
    # once; an active price approval, if any, owns its first preparation.
    stale = sorted(stale_by_key.values())
    if len(stale) > identity.MAX_FILES:
        raise files.ContractFilesProblem('Число документов превышает предел отдельного обновления.')
    guard = store.digest({'project_scope': store.project_scope(project), 'cut': cut,
        'reader': documents.READER_VERSION, 'decision_head': context.head,
        'source_context': source_context, 'groups': inventories})
    return guard, stale, inventories


def _sealed(inventories, own_writes, *, after=False):
    observed = copy.deepcopy(inventories)
    for group in observed:
        inventory = group['bindings']
        for key in ('metadata_files_read', 'metadata_bytes_read',
                    'price_source_files_read', 'price_source_bytes_read'):
            inventory.pop(key, None)
        for card in inventory['cards']:
            for index, document in enumerate(card['documents']):
                key = (card['raw_id'], document['document_sha256'])
                if key not in own_writes:
                    continue
                expected, price_witness = own_writes[key]
                if after and ((document.get('metadata') or {}).get('sha256') != expected
                        or price_witness and (document.get('price_reader_provenance') or {}).get('state') != 'verified'):
                    raise PreparationChanged('Документ изменился во время обновления. Обновите договоры.')
                card['documents'][index] = {'document_sha256': key[1], 'own_refresh_sha256': expected}
    return observed


def prepare(project: str, cut: str, expected_guard: str = '') -> dict:
    """Empty guard plans only; each matching nonempty guard prepares one PDF."""
    if ownership._CONTEXT.get() is not None:
        raise files.ContractFilesProblem('Подготовка документов выполняется до сборки реестра.')
    if not isinstance(expected_guard, str) or expected_guard and not re.fullmatch(r'[0-9a-f]{64}', expected_guard):
        raise files.ContractFilesProblem('Проверка состава документов не подтверждена.')
    cut = contracts._cut(cut)
    budget = {'files': 0, 'bytes': 0, 'metadata_files': 0, 'metadata_bytes': 0}
    proof = MetadataBudget(budget)
    with store.locked(project):
        context = ownership.ReadContext(project, cut)
        source_context = _corpus(project, cut)
        composition = contracts._composition(project, cut)
        identifiers = {identifier for identifier, _ in contracts._groups(composition['primary'], project)}
        relevant = {context.pairs[identifier] for identifier in identifiers if identifier in context.pairs}
        if len(relevant) > ownership.MAX_RELEVANT_PAIRS:
            raise files.ContractFilesProblem('Слишком много уточнений для ограниченного обновления документов.')
        groups = [(pair, pair in context.corrections) for pair in sorted(relevant)]
        with contextlib.ExitStack() as locks:
            for identifier in sorted({identifier for pair, _ in groups for identifier in pair}):
                locks.enter_context(files._locked(identity._safe_path(project, 'contract_documents', identifier)))
            before_read = proof.phase()
            guard, stale, before = _plan(project, cut, context, groups, before_read, source_context)
            if expected_guard and expected_guard != guard:
                raise PreparationChanged('Источники или документы изменились после начала обновления. '
                                         'Обновите договоры; уже прочитанные документы сохранены.')
            processed = 0
            if expected_guard and stale:
                after_read = proof.phase()
                _, key, members, correction = stale[0]
                event = context.active_events.get(members) or {}
                approvals = ({members: event} if event.get('action') == 'correct_sources' else {})
                own_writes = files.refresh_parse_cache(project, [(members, correction)], budget, approvals,
                    selected_documents=frozenset({key}), _proof_budget=proof, _future_price_passes=1) or {}
                processed = 1
                previous_count = len(stale)
                guard, stale, after = _plan(project, cut, context, groups, after_read, source_context)
                if (len(stale) != previous_count-1 or set(own_writes) != {key}
                        or _sealed(before, own_writes) != _sealed(after, own_writes, after=True)):
                    raise PreparationChanged('Состав обновляемых документов изменился. Обновите договоры.')
            if store.load(project)['head'] != context.head or _corpus(project, cut) != source_context:
                raise PreparationChanged('Источники изменились во время обновления документов. Обновите договоры.')
            store.assert_namespace(project)
            return {'guard': guard, 'remaining': len(stale), 'processed': processed,
                    'limit': identity.MAX_FILES, 'reader': documents.READER_VERSION, 'done': not stale}
