"""Identical statement imports are one source with preserved archive provenance."""
from __future__ import annotations

import copy
import math
import re

from developaid_monitor_statement_union import _day, _digest, _source

_CONTENT = ('period_year', 'object_scope', 'system_scope', 'site_scope',
            'scope_evidence', 'document_form', 'items', 'source_complete',
            'incomplete_rows_count', 'duplicate_rows_count', 'unread_rows_count',
            'period_dates_known', 'warnings')
_DEFINITION = ('position', 'name', 'unit', 'scope', 'plan_quantity', 'planned_amount',
               'section_path', 'context_headings', 'parent_row', 'is_group',
               'is_duplicate', 'duplicate_of')
_PERIOD_FACTS = ('quantity', 'material_quantity', 'amount', 'work_amount', 'material_amount')


def _content(value):
    # A renamed copy is still the same statement. Keep sheet/row/cell evidence,
    # work context, every period and qualifiers; equal totals alone are no proof.
    if isinstance(value, dict):
        return {key: _content(item) for key, item in value.items() if key != 'filename'}
    if isinstance(value, list):
        return [_content(item) for item in value]
    return value


def _qualified_source(reference, ledger):
    source = reference.get('source') or {}
    return bool(ledger is not None and source.get('filename') and source.get('sheet')
        and source.get('snapshot_id') and _day(reference.get('source_date'))
        and re.fullmatch(r'[0-9a-f]{64}', str(source.get('file_sha256') or '')))


def _family(reference, ledger):
    if not _qualified_source(reference, ledger) or reference.get('source_complete') is not True:
        return None
    definition = {key: ledger.get(key) for key in
                  ('period_year', 'object_scope', 'system_scope', 'site_scope', 'scope_evidence')}
    definition['items'] = [{**{key: item.get(key) for key in _DEFINITION},
        'source_row': (item.get('source') or {}).get('row')} for item in ledger.get('items') or []]
    return _digest([_content(definition), (reference.get('source') or {}).get('sheet'),
                    reference.get('planned_amount_basis'), reference.get('completed_amount_basis')])


def _covers(newer, older):
    """Every known old movement must still be present and equal in the new book.

    New periods or zero placeholders filled later may extend a cumulative book.
    Missing periods, changed nonzero facts or ambiguous labels prove no coverage.
    """
    for new, old in zip(newer.get('items') or [], older.get('items') or []):
        periods = {}
        for period in new.get('periods') or []:
            key = (period.get('label'), period.get('date_start'), period.get('date_end'))
            if key in periods and key[0]:
                return False
            periods[key] = period
        seen = set()
        movements = [period for period in old.get('periods') or []
                     if any(period.get(field) not in (None, 0) for field in _PERIOD_FACTS)]
        if not movements and any(old.get(field) not in (None, 0) for field in
                                 ('completed_quantity', 'material_quantity', 'completed_amount')):
            return False
        for period in movements:
            key = (period.get('label'), period.get('date_start'), period.get('date_end'))
            if not key[0] or key in seen or key not in periods:
                return False
            seen.add(key)
            for field in _PERIOD_FACTS:
                value = period.get(field)
                current = periods[key].get(field)
                if value is not None and (current is None or not math.isclose(
                        value, current, rel_tol=1e-12, abs_tol=1e-7)):
                    return False
    return True


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
        valid = _qualified_source(reference, ledger)
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
    current = []
    for reference in selected:
        ledger = ledgers.get(_source(reference.get('source')))
        family = _family(reference, ledger)
        replacement = next((new for new in current
            if family is not None and reference['source_date'] < new['source_date']
            and family == _family(new, ledgers.get(_source(new.get('source'))))
            and _covers(ledgers[_source(new.get('source'))], ledger)), None)
        if replacement is None:
            current.append(reference)
        else:
            # A covered previous edition is history, never an identical alias:
            # its annual totals may differ and must not qualify today's facts.
            replacement.setdefault('source_versions', []).append(reference)
    return current


def statement_source_keys(reference):
    """All immutable bindings represented by one current statement."""
    return {_source(source) for source in [reference.get('source'),
                                          *(reference.get('source_copies') or [])]}


def statement_family_map(physical_sources):
    """Proof for this composition only; never write family tags into cached input.

    Exact copies and fully covered editions share the identity of their named
    periods. Their annual totals still remain distinct historical observations.
    """
    references = []
    for ledger, _ in physical_sources:
        def basis(field):
            known = {item.get(field) for item in ledger.get('items') or []} - {None, '', 'unspecified'}
            return next(iter(known)) if len(known) == 1 else 'conflicting' if known else 'unspecified'
        source = dict(ledger.get('source') or {}, snapshot_id=ledger.get('archive_snapshot_id'),
                      file_sha256=ledger.get('file_sha256'), source_date=ledger.get('source_date'))
        references.append({'source': source, 'source_date': ledger.get('source_date'),
            'source_complete': ledger.get('source_complete') is True,
            'planned_amount_basis': basis('planned_amount_basis'),
            'completed_amount_basis': basis('completed_amount_basis')})
    families = {}
    def observations(reference):
        yield reference.get('source') or {}
        yield from reference.get('source_copies') or []
        for previous in reference.get('source_versions') or []:
            yield from observations(previous)
    for reference in unique_statement_sources(references, physical_sources):
        sources = list(observations(reference))
        if len(sources) > 1:
            family = _digest(sorted(_source(source) for source in sources))
            families.update({_source(source): family for source in sources})
    return families
