"""Bounded hashes explain statement-family decisions for one verified card.

This reader never returns values of definition fields, changes a source, or
chooses a financial result. Both input sets are already qualified by the
one-card source review; unverified or neighbouring records are excluded.
"""
from __future__ import annotations

import copy
import json

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
import developaid_monitor_statement_sources as statements
from developaid_monitor_statement_union import _digest, _source

_HEADERS = ('period_year', 'object_scope', 'system_scope', 'site_scope', 'scope_evidence')


def _binding(ledger):
    source = dict(ledger.get('source') or {}, snapshot_id=ledger.get('archive_snapshot_id'),
                  file_sha256=ledger.get('file_sha256'))
    return _source(source)


def _fields(ledger, reference, *, by_coordinate=False):
    items = list(ledger.get('items') or [])
    if by_coordinate:
        items.sort(key=lambda item: json.dumps(
            [(item.get('source') or {}).get(key) for key in ('sheet', 'row')], default=str))
    result = {key: _digest(statements._content(ledger.get(key))) for key in _HEADERS}
    result.update({'reference.'+key: _digest(reference.get(key))
                   for key in ('planned_amount_basis', 'completed_amount_basis')})
    for key in statements._DEFINITION:
        result['items.'+key] = _digest(statements._content([item.get(key) for item in items]))
    result['items.source_row'] = _digest([(item.get('source') or {}).get('row') for item in items])
    return result


def _observation(ledger):
    reference, = statements._family_references([(ledger, [])])
    coords = [[(item.get('source') or {}).get(key) for key in ('sheet', 'row')]
              for item in ledger.get('items') or []]
    return {'qualified_source': statements._qualified_source(reference, ledger),
            'source_complete': ledger.get('source_complete') is True,
            'family_sha256': statements._family(reference, ledger),
            'definition_sha256': _fields(ledger, reference),
            'coordinate_definition_sha256': _fields(ledger, reference, by_coordinate=True),
            'item_order_sha256': _digest(coords),
            'coordinate_set_sha256': _digest(sorted(coords, key=lambda value: json.dumps(value, default=str))),
            'duplicate_coordinates': len(coords)-len({_digest(value) for value in coords}),
            'items': len(coords)}


def _coverage(newer, older):
    try:
        return statements._covers(newer, older)
    except (TypeError, ValueError, KeyError, OverflowError):
        return None  # Invalid cached values are an unknown, never a proof.


def read(project, contract_id, cut, originals):
    """Compare actual composition inputs with this card's hash-verified parses."""
    fresh = {}
    for ledger in originals:
        fresh[_binding(ledger)] = ledger
    composition = contracts._composition(project, cut)
    selected = next((items for identifier, items in contracts._groups(composition['primary'], project)
                     if identifier == contract_id), [])
    used = [ledger for ledger in selected if ledger.get('kind') == 'ledger']
    matched = [ledger for ledger in used if _binding(ledger) in fresh]
    family_map = statements.statement_family_map([(ledger, []) for ledger in matched])
    latest = max(used, key=lambda ledger: (ledger['source_date'], _binding(ledger)), default=None)
    if latest is not None and _binding(latest) not in fresh:
        latest = None
    latest_family = _observation(latest)['family_sha256'] if latest is not None else None
    latest_original = fresh[_binding(latest)] if latest is not None else None
    latest_original_family = (_observation(latest_original)['family_sha256']
                              if latest_original is not None else None)
    rows = []
    for ledger in matched:
        original = fresh[_binding(ledger)]
        effective, native = _observation(ledger), _observation(original)
        snapshot = composition['by_snapshot'].get(ledger['archive_snapshot_id']) or {}
        rows.append({'snapshot_id': ledger['archive_snapshot_id'], 'source_date': ledger['source_date'],
            'file_sha256': ledger.get('file_sha256'),
            'source': copy.deepcopy(ledger.get('source') or {}),
            'source_parse_state': snapshot.get('source_parse_state'),
            'parser_schema_current': snapshot.get('parser_schema') == ledgers.PARSER_SCHEMA,
            'parser_fingerprint_current': snapshot.get('parser_fingerprint') == ledgers._PARSER_FINGERPRINT,
            'composition': effective, 'verified_original': native,
            'different_definition_fields': [key for key in effective['definition_sha256']
                if effective['definition_sha256'][key] != native['definition_sha256'][key]],
            'different_coordinate_definition_fields': [key for key in effective['coordinate_definition_sha256']
                if effective['coordinate_definition_sha256'][key] != native['coordinate_definition_sha256'][key]],
            'covers_by_latest_input': _coverage(latest, ledger) if latest is not None else None,
            'covers_by_latest_original': _coverage(latest_original, original) if latest_original is not None else None,
            'same_family_as_latest_input': (effective['family_sha256'] is not None
                and effective['family_sha256'] == latest_family) if latest is not None else None,
            'same_family_as_latest_original': (native['family_sha256'] is not None
                and native['family_sha256'] == latest_original_family) if latest_original is not None else None,
            'composition_family_sha256': family_map.get(_binding(ledger))})
    return {'schema': 'contract-statement-family-proof-v1',
            'scope': 'selected_card_verified_sources_only', 'contract_id': contract_id, 'cut': cut,
            'current_parser_fingerprint': ledgers._PARSER_FINGERPRINT,
            'state': ('no_detail_inputs' if not used else 'read' if len(matched) == len(used) else 'incomplete'),
            'complete': bool(used) and len(matched) == len(used),
            'input_count': len(used), 'verified_input_count': len(matched),
            'unverified_inputs_omitted': len(used)-len(matched),
            'sources': rows}
