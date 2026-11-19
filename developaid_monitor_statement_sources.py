"""Identical statement imports are one source with preserved archive provenance."""
from __future__ import annotations

import copy
import re

from developaid_monitor_statement_union import _day, _digest, _source

_CONTENT = ('period_year', 'object_scope', 'system_scope', 'site_scope',
            'scope_evidence', 'document_form', 'items', 'source_complete',
            'incomplete_rows_count', 'duplicate_rows_count', 'unread_rows_count',
            'period_dates_known', 'warnings')


def _content(value):
    # A renamed copy is still the same statement. Keep sheet/row/cell evidence,
    # work context, every period and qualifiers; equal totals alone are no proof.
    if isinstance(value, dict):
        return {key: _content(item) for key, item in value.items() if key != 'filename'}
    if isinstance(value, list):
        return [_content(item) for item in value]
    return value


def unique_statement_sources(references, physical_sources):
    """Select the newest identical observation without changing stored imports."""
    ledgers = {_source(dict(ledger.get('source') or {},
                            snapshot_id=ledger.get('archive_snapshot_id'),
                            file_sha256=ledger.get('file_sha256'))): ledger
               for ledger, _ in physical_sources}
    selected, signatures = [], {}
    for reference in sorted(references, key=lambda ref: (
            str(ref.get('source_date') or ''), _source(ref.get('source'))), reverse=True):
        source = reference.get('source') or {}
        ledger = ledgers.get(_source(source))
        valid = (ledger is not None and source.get('filename') and source.get('sheet')
                 and source.get('snapshot_id') and _day(reference.get('source_date'))
                 and re.fullmatch(r'[0-9a-f]{64}', str(source.get('file_sha256') or '')))
        signature = _digest([
            {key: value for key, value in reference.items()
             if key not in {'source', 'source_date', 'label'}},
            _content({key: ledger.get(key) for key in _CONTENT}), source['sheet'],
        ]) if valid else None
        if signature is not None and signature in signatures:
            signatures[signature].setdefault('source_copies', []).append(copy.deepcopy(source))
        else:
            current = copy.deepcopy(reference)
            selected.append(current)
            if signature is not None:
                signatures[signature] = current
    return selected


def statement_source_keys(reference):
    """All immutable bindings represented by one current statement."""
    return {_source(source) for source in [reference.get('source'),
                                          *(reference.get('source_copies') or [])]}
