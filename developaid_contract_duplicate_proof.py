"""Closed raw-source normalization evidence; never return formulas or amounts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import developaid_contract_source_review as review
import developaid_monitor_ledgers as ledgers

SCHEMA = 'ks6-native-duplicate-proof-v1'
MAX_SHEETS = 8
MAX_RECORDS = 8
MAX_ITEMS = 4096
MAX_PERIODS = 16384
MAX_PROOFS = 8
MAX_PROOF_CELLS = 16
MAX_CELLS = 100_000
MAX_RESULT_BYTES = 64 * 1024


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _locator(item):
    source = item.get('source') or {}
    return dict(sheet=source.get('sheet'), row=source.get('row'), period_year=item.get('period_year'))


def _normalization(value):
    if not isinstance(value, dict):
        raise review.SourceReviewProblem('Основание копии имеет неверную структуру; доказательство не принято.')
    coordinate = ledgers._cell_coordinates(value.get('cell'))
    column = coordinate[0] if coordinate else None
    normalized = ledgers._sum_row_range(value.get('formula'), column) if coordinate else None
    return dict(cell=value.get('cell'), column=column,
        input_sha256=_digest(value), audit_input_sha256=_digest(review._audit_relative(value, '')),
        state='normalized' if normalized else 'invalid',
        range=dict(column=column, start_row=normalized[0], end_row=normalized[1]) if normalized else None)


def _record(record, rows, sha, cut, index):
    items = record.get('items') or []
    native_pin = _digest(items)
    # Exactly the existing page producer's item view, including relative cell
    # evidence and cut qualifications. This is not a guessed inverse DTO.
    audit_items = review._audit_record(record, rows, [], sha, cut, page_headers=True)['items']
    verified = ledgers.verified_duplicate_sources(items)
    indexed = {}
    for position, item in enumerate(items):
        indexed.setdefault(ledgers._duplicate_key(item), []).append((position, item))
    proofs = []
    for position, item in enumerate(items):
        if item.get('is_duplicate') is not True:
            continue
        proof = item.get('duplicate_proof')
        if not isinstance(proof, dict) or not isinstance(proof.get('plan'), dict) or not isinstance(proof.get('completed'), list):
            raise review.SourceReviewProblem('Основание копии не прочитано полностью; доказательство не принято.')
        if len(proof['completed'])+1 > MAX_PROOF_CELLS:
            raise review.SourceReviewProblem('Слишком много ячеек основания копии; доказательство не принято.')
        original = item.get('duplicate_of') or {}
        key = ledgers._duplicate_key(item)
        target = tuple(original.get(k) for k in ('filename', 'sheet', 'period_year', 'row'))
        matches = indexed.get(target) or []
        canonical_position, canonical = matches[0] if len(matches) == 1 else (None, None)
        proofs.append(dict(item_index=position, locator=_locator(item),
            canonical_item_index=canonical_position, canonical_locator=_locator(canonical) if canonical else None,
            native_item_sha256=_digest(item), audit_item_sha256=_digest(audit_items[position]),
            native_canonical_sha256=_digest(canonical) if canonical else None,
            audit_canonical_sha256=_digest(audit_items[canonical_position]) if canonical else None,
            plan=_normalization(proof['plan']), completed=[_normalization(f) for f in proof['completed']],
            verified_duplicate_source=key in verified,
            verified_target=dict(sheet=verified[key].get('sheet'), row=verified[key].get('row'),
                period_year=verified[key].get('period_year')) if key in verified else None))
        if len(proofs) > MAX_PROOFS:
            raise review.SourceReviewProblem('Слишком много копий для ограниченной проверки.')
    if _digest(items) != native_pin:
        raise review.SourceReviewProblem('Входные позиции изменились во время нормализации.')
    return dict(record_index=index, locator=_locator(record), item_count=len(items),
        native_items_sha256=native_pin, audit_items_sha256=_digest(audit_items), proofs=proofs)


def _producer():
    return dict(current_parser_schema=ledgers.PARSER_SCHEMA,
        code_sha256={module.__name__:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (ledgers, review)},
        proof_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


def project_proof(project, cut, selected, expected_token, directory_fd, guard, inventory):
    producer = _producer()
    snapshots = inventory()
    eligible = [s for s in snapshots if s['taken_at'] <= cut]
    archives, payloads, sizes = review._page_inventory(project, eligible, directory_fd, guard, selected)
    token = review.corpus_token(project, cut, archives)
    if token != expected_token or len(selected) != 1 or selected != payloads.keys():
        raise review.SourceReviewProblem('SHA книги или корпус не совпал с предыдущим чтением.')
    if [s for s in inventory() if s['taken_at'] <= cut] != eligible:
        raise review.SourceReviewProblem('Состав исходников изменился до нормализации.')
    sha = next(iter(selected))
    name, payload = payloads.pop(sha)
    parser_name = ('source.xlsx' if payload.startswith(b'PK\x03\x04') else 'source.xls'
        if payload.startswith(b'\xd0\xcf\x11\xe0') or payload[:2] in {b'\x09\x00',b'\x09\x02',b'\x09\x04',b'\x09\x08'} else name)
    budget = dict(text_bytes=0, materialized_cells=0, max_materialized_cells=MAX_CELLS)
    sheets = ledgers._read_workbook(parser_name, payload, budget)
    if len(sheets) > MAX_SHEETS:
        raise review.SourceReviewProblem('В книге больше листов, чем допускает проверка копий.')
    records, items, periods, proofs, proof_cells = [], 0, 0, 0, 0
    for title, rows in sheets:
        # Use the inventory filename just as the existing audit producer does.
        record = ledgers._ledger(name, title, rows)
        if record is None:
            continue  # This scope attests physical KS records, never summary money.
        record['file_sha256'] = sha
        items += len(record.get('items') or [])
        periods += sum(len(i.get('periods') or []) for i in record.get('items') or [])
        if len(records) >= MAX_RECORDS or items > MAX_ITEMS or periods > MAX_PERIODS:
            raise review.SourceReviewProblem('Предел позиций или периодов проверки копий превышен.')
        projected = _record(record, rows, sha, cut, len(records))
        proofs += len(projected['proofs'])
        proof_cells += sum(1+len(p['completed']) for p in projected['proofs'])
        if proofs > MAX_PROOFS or proof_cells > MAX_PROOF_CELLS:
            raise review.SourceReviewProblem('Предел оснований копий превышен; частичное доказательство не возвращается.')
        records.append(projected)
    after = inventory()
    if [s for s in after if s['taken_at'] <= cut] != eligible:
        raise review.SourceReviewProblem('Состав исходников изменился во время нормализации.')
    checked, _, checked_sizes = review._page_inventory(project, eligible, directory_fd, guard, set())
    if review.corpus_token(project, cut, checked) != token or checked_sizes != sizes:
        raise review.SourceReviewProblem('Исходники изменились во время нормализации; результат не принят.')
    if [s for s in inventory() if s['taken_at'] <= cut] != eligible:
        raise review.SourceReviewProblem('Состав исходников изменился после проверки.')
    if _producer() != producer:
        raise review.SourceReviewProblem('Код обработчика изменился во время проверки; доказательство не принято.')
    result = dict(schema=SCHEMA, scope='current_native_raw_items_not_effective_or_persisted_bindings',
        project=project, cut=cut, book_sha256=sha, corpus_token_schema=review.CORPUS_TOKEN_SCHEMA,
        corpus_token=token, source_stable_verified=True,
        producer=producer,
        parser_filename_sha256=hashlib.sha256(name.encode()).hexdigest(),
        source_observations=[dict(snapshot_id=a['snapshot_id'], taken_at=a['taken_at'],
            archive_sha256=a['archive_sha256'], filename_sha256=hashlib.sha256(f['filename'].encode()).hexdigest())
            for a in archives for f in a['files'] if f.get('file_sha256') == sha],
        records=records, record_count=len(records), proof_count=proofs,
        audit_view_schema='source-audit-page-v1-items', native_items_order='current_book_sheet_then_parser_item_order',
        native_items_complete=True, binding_verified=None, financial_complete=None,
        limits=dict(selected_books=1,sheets=MAX_SHEETS,records=MAX_RECORDS,positions=MAX_ITEMS,
            periods=MAX_PERIODS,proofs=MAX_PROOFS,proof_cells=MAX_PROOF_CELLS,
            materialized_cells=MAX_CELLS,result_bytes=MAX_RESULT_BYTES))
    # Bind each record/order/input pin to the exact project/cut/corpus/source and
    # current producer. A foreign proof cannot be substituted by matching rows.
    result['projection_sha256'] = _digest(result)
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        raise review.SourceReviewProblem('Доказательство не помещается в установленный предел; результат не принят.')
    return result
