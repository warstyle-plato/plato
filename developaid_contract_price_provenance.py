"""Event-bound price-component provenance across a verified reader refresh.

This is derived cache evidence, never a new human approval. A legacy approval
can keep its price component only when its complete historical binding witness
was available before refresh. The global document reader is never relabelled.
"""
from __future__ import annotations

import copy
import hashlib
import json

import developaid_contract_identity_store as store
import developaid_contract_documents as documents

FIELD = 'price_reader_provenance'
SCHEMA = 'contract-price-reader-provenance-v1'
LEGACY_READERS = (11, 12, 13, 14, 15, 16, 17)
# Deliberately reviewed text-reader generations. A future reader upgrade must
# re-establish semantic continuity; a larger version number is not evidence.
REFRESH_READERS = (15, 16, 17, 18)
MAX_WITNESS_BYTES = 1024 * 1024
_FIELDS = {'schema', 'origin', 'event_id', 'raw_id', 'source_pdf_sha256', 'from_reader', 'to_reader',
           'approved_bindings', 'approved_bindings_sha256', 'approved_document_evidence',
           'component_sha256', 'selected_price_sha256'}
_BINDING_FIELDS = {'terms_file', 'work_links_file', 'header_dates_file', 'cards',
                   'metadata_files_read', 'metadata_bytes_read', 'old_choice_files_modified'}


def _hash(value):
    return isinstance(value, str) and bool(store.HASH.fullmatch(value))


def component(record):
    """Full semantic values, including native confirmation/withdrawal state."""
    required = ('contract', 'agreement', 'price', 'terms')
    if not isinstance(record, dict) or any(key not in record for key in required):
        return None
    contract, agreement = record['contract'], record['agreement']
    if (not isinstance(contract, dict) or not isinstance(contract.get('number'), str)
            or not contract['number'] or store.day(contract.get('date')) != contract.get('date')
            or not contract.get('date') or not isinstance(record['price'], dict)
            or not record['price'].get('candidates') or not isinstance(record['terms'], dict)):
        return None
    if agreement is not None and (not isinstance(agreement, dict) or not agreement.get('number')
                                  or not agreement.get('date') or store.day(agreement['date']) != agreement['date']):
        return None
    # A text-reader upgrade cannot attest to a scan or a withdrawn document.
    if record.get('scan') is not None or record.get('removed_at') is not None:
        return None
    # Graph-discovery/activation is a separate decision. A derived pending
    # graph flag cannot invalidate, or grant, the human price approval.
    return {key: record.get(key) for key in (*required, 'scan', 'removed_at')}


def _document(snapshot, raw_id, sha):
    if not isinstance(snapshot, dict) or set(snapshot) != _BINDING_FIELDS:
        return None
    if snapshot['old_choice_files_modified'] is not False:
        return None
    cards = snapshot.get('cards')
    if not isinstance(cards, list) or not 2 <= len(cards) <= 8:
        return None
    found = [card for card in cards if isinstance(card, dict) and card.get('raw_id') == raw_id]
    if len(found) != 1 or not isinstance(found[0].get('documents'), list) or len(found[0]['documents']) > 256:
        return None
    docs = [doc for doc in found[0]['documents'] if isinstance(doc, dict) and doc.get('document_sha256') == sha]
    return docs[0] if len(docs) == 1 else None


def _unconfirmed_source(document):
    return bool(document and document.get('withdrawal_marker_present') is False
        and document.get('withdrawal_status') == 'not_marked'
        and document.get('withdrawal_sha256') == store.digest(None)
        and document.get('scan_confirmation_present') is False
        and document.get('scan_confirmation_status') == 'unconfirmed'
        and document.get('scan_confirmation_sha256') == store.digest(None))


def _refresh_pair(previous, current):
    return (type(previous) is int and previous in LEGACY_READERS
            and type(current) is int and current in REFRESH_READERS and previous < current)


def build(old, fresh, sha, raw_id, raw_pdf, old_metadata_sha256, event, before):
    """Called only before binding capture, under the complete native card locks."""
    import developaid_contract_correction as correction
    import developaid_contract_identity as identity
    if (not isinstance(event, dict) or event.get('action') != 'correct_sources'
            or not _hash(event.get('event_id')) or not _refresh_pair(old.get('reader'), fresh.get('reader'))
            or fresh.get('reader') != documents.READER_VERSION
            or old.get('sha256') != sha or fresh.get('sha256') != sha
            or hashlib.sha256(raw_pdf).hexdigest() != sha):
        return None
    payload = event['payload']
    correction.validate_payload(payload)
    evidence = payload['price_document_evidence']
    if (not evidence or payload['roles']['price_raw_id'] != raw_id
            or evidence['document_sha256'] != sha):
        return None
    previous = _document(before, raw_id, sha)
    if (not _unconfirmed_source(previous) or (previous.get('metadata') or {}).get('sha256') != old_metadata_sha256
            or previous.get('reader_version_sha256') != store.digest(old['reader'])):
        return None
    if component(old) is None or component(old) != component(fresh):
        return None
    if FIELD in old:
        # A previously verified witness already seals the complete human event
        # and original bindings. Validate it against the OLD reviewed reader,
        # current component and exact PDF before advancing to another reviewed reader.
        # Unrelated deadline/work-link edits cannot become new price approval.
        projection = _project(old, previous, raw_id, lambda: raw_pdf, old['reader'])
        if not accepts(projection, event, payload['selected_values']['price']):
            return None
        marker = copy.deepcopy(old[FIELD])
        marker['to_reader'] = fresh['reader']
        return marker
    if (store.digest(before) != payload['bindings_sha256']
            or identity.document_evidence(old, sha) != evidence):
        return None
    marker = {'schema': SCHEMA, 'origin': 'verified_reader_refresh', 'event_id': event['event_id'],
        'raw_id': raw_id, 'source_pdf_sha256': sha, 'from_reader': old['reader'], 'to_reader': fresh['reader'],
        'approved_bindings': copy.deepcopy(before), 'approved_bindings_sha256': payload['bindings_sha256'],
        'approved_document_evidence': copy.deepcopy(evidence), 'component_sha256': store.digest(component(fresh)),
        'selected_price_sha256': store.digest(payload['selected_values']['price'])}
    if len(json.dumps(marker, ensure_ascii=False).encode()) > MAX_WITNESS_BYTES:
        return None
    return marker


def project(record, document, raw_id, read_pdf):
    """Validate a persistent witness without consulting mutable active events.

    Event matching is performed by the resolver. Keeping this projection pure
    with respect to the journal avoids changing a metadata binding merely by
    appending a legitimate new human decision.
    """
    return _project(record, document, raw_id, read_pdf, documents.READER_VERSION)


def _project(record, document, raw_id, read_pdf, current_reader):
    import developaid_contract_correction as correction
    marker = record.get(FIELD)
    invalid = {'schema': SCHEMA, 'state': 'invalid', 'reason': 'unsupported_reader_price_evidence'}
    if not isinstance(marker, dict) or set(marker) != _FIELDS:
        return invalid
    if len(json.dumps(marker, ensure_ascii=False).encode()) > MAX_WITNESS_BYTES:
        return invalid
    hashes = ('event_id', 'raw_id', 'source_pdf_sha256', 'approved_bindings_sha256',
              'component_sha256', 'selected_price_sha256')
    if (marker['schema'] != SCHEMA or marker['origin'] != 'verified_reader_refresh'
            or any(not _hash(marker[key]) for key in hashes)
            or marker['raw_id'] != raw_id or marker['source_pdf_sha256'] != document['document_sha256']
            or record.get('sha256') != marker['source_pdf_sha256']
            or not _refresh_pair(marker['from_reader'], marker['to_reader'])
            or marker['to_reader'] != current_reader or record.get('reader') != current_reader):
        return invalid
    evidence = marker['approved_document_evidence']
    if (not isinstance(evidence, dict) or set(evidence) != set(correction.DOCUMENT_EVIDENCE_FIELDS)
            or any(not _hash(value) for value in evidence.values())
            or store.digest(marker['approved_bindings']) != marker['approved_bindings_sha256']):
        return invalid
    previous = _document(marker['approved_bindings'], raw_id, marker['source_pdf_sha256'])
    if (not _unconfirmed_source(previous)
            or any(previous.get(key) != evidence[key] for key in correction.DOCUMENT_EVIDENCE_FIELDS)
            or evidence['reader_version_sha256'] != store.digest(marker['from_reader'])):
        return invalid
    current = component(record)
    if (current is None or store.digest(current) != marker['component_sha256']
            or any(document.get(key) != evidence[key] for key in correction.DOCUMENT_EVIDENCE_FIELDS
                   if key != 'reader_version_sha256')
            or document.get('reader_version_sha256') != store.digest(marker['to_reader'])):
        return {**invalid, 'reason': 'price_component_changed'}
    try:
        raw = read_pdf()
    except store.IdentityProblem:
        return {**invalid, 'reason': 'price_source_unavailable'}
    if raw is None or hashlib.sha256(raw).hexdigest() != marker['source_pdf_sha256']:
        return {**invalid, 'reason': 'price_source_changed'}
    # This remains the approved component's reader-inclusive evidence. The
    # separate current reader is always truthful; no global reader is rewritten.
    return {'schema': SCHEMA, 'state': 'verified', 'event_id': marker['event_id'],
        'approved_bindings_sha256': marker['approved_bindings_sha256'],
        'approved_component_evidence': evidence, 'current_reader_version_sha256': document['reader_version_sha256'],
        'selected_price_sha256': marker['selected_price_sha256'], 'component_sha256': marker['component_sha256'],
        'witness_sha256': store.digest(marker)}


def accepts(projection, event, price):
    """Match only this active human event and its complete saved operand tuple."""
    import developaid_contract_correction as correction
    if not isinstance(projection, dict) or projection.get('state') != 'verified' or price is None:
        return False
    payload = event['payload']
    return bool(projection.get('event_id') == event['event_id']
        and projection.get('approved_bindings_sha256') == payload['bindings_sha256']
        and projection.get('approved_component_evidence') == payload['price_document_evidence']
        and projection.get('selected_price_sha256') == store.digest(payload['selected_values']['price'])
        and {key: price.get(key) for key in correction.SAVED_PRICE} == payload['selected_values']['price']
        and (price.get('amount_source') or {}).get('sha256') == payload['price_document_evidence']['document_sha256'])
