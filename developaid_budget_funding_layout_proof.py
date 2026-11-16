"""Admin-only saved-source layout metadata, without financial observations.

Only the fixed RSS estimate worksheet is classified. Source selection and XML
acceptance belong to the existing native readers; this module observes them.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

import developaid_admin_expenses_source as ahr
import developaid_budget_funding_source as source
import developaid_cached_source_audit as audit

PURPOSE = 'budget_funding_layout_proof_v1'
SCOPE = 'rss_estimate_only'
MAX_REQUEST = 12288
MAX_OUTPUT = 60 * 1024
MAX_WIRE = 64 * 1024
MAX_FAILURE = 2048
_PRODUCERS = {
    'budget_source': 'developaid_budget_funding_source.py',
    'layout_proof': 'developaid_budget_funding_layout_proof.py',
    'monitor_routes': 'engine/monitor.py',
    'cached_source_reader': 'developaid_cached_source_audit.py',
    'admin_source_reader': 'developaid_admin_expenses_source.py',
}
_COUNT_NAMES = ('foreign_formula_starts', 'cf_predicate_evaluations', 'cf_path_candidates',
    'cf_start_predicate_matches', 'dv_containers_seen', 'dv_rules_seen', 'dv_formula1_starts',
    'dv_formula2_starts', 'dv_sqref_starts', 'dv_formula_start_matches',
    'rejected_foreign_formula_starts')
SHA = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Commit = Annotated[str, Field(pattern=r'^[0-9a-f]{40}$')]
Ticket = Annotated[str, Field(pattern=r'^[0-9a-f]{32}$')]
Counter = Annotated[int, Field(ge=0, le=16_000_000)]
Day = Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')]


class LayoutProblem(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


_ProducerMap = create_model('_ProducerMap', __base__=_Closed,
    **{name: (SHA, ...) for name in _PRODUCERS})


class _Runtime(_Closed):
    commit: Commit
    version: Annotated[str, Field(pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$', max_length=32)]


class _Expected(_Closed):
    runtime_commit: Commit
    producer_sha256: _ProducerMap
    finance_sha256: SHA
    rss_sha256: SHA
    namespace_sha256: SHA
    aliases_sha256: SHA | None


class _ResultRequest(_Closed):
    key: Annotated[str, Field(min_length=1, max_length=4096)]
    session: Annotated[str, Field(max_length=4096)]
    purpose: Literal['budget_funding_layout_proof_v1']
    ticket: Ticket


class _StartRequest(_ResultRequest):
    scope: Literal['rss_estimate_only']
    project: Annotated[str, Field(min_length=1, max_length=200)]
    cut: Day
    expected: _Expected

    @model_validator(mode='after')
    def native_identity(self):
        if (not self.project.strip() or self.project.strip() in {'.', '..'}
                or any(c in self.project for c in ('/', '\\', '\0'))):
            raise ValueError('project_invalid')
        day = dt.date.fromisoformat(self.cut)
        if day.isoformat() != self.cut or day > dt.date.today():
            raise ValueError('cut_invalid')
        return self


class _Member(_Closed):
    sha256: SHA | None
    bytes: Annotated[int, Field(ge=1, le=16 * 1024 * 1024)] | None
    metadata_sha256: SHA | None
    metadata_bound_to_bytes: bool | None


class _Pair(_Closed):
    state: Literal['stable_expected', 'stable_mismatch', 'changed', 'unknown']
    before_after_equal: bool | None
    namespace_sha256: SHA | None
    aliases_sha256: SHA | None
    finance: _Member
    rss: _Member
    rss_version_date: Day | None
    historical_financial_eligibility: Literal['not_assessed']

    @model_validator(mode='after')
    def observed_pair_states(self):
        if self.state.startswith('stable_') and self.before_after_equal is not True:
            raise ValueError('stable_pair_not_observed')
        if self.state == 'unknown' and self.before_after_equal is not None:
            raise ValueError('unknown_pair_has_verdict')
        if self.state == 'stable_expected' and (self.namespace_sha256 is None
                or self.rss_version_date is None or any(member.sha256 is None or member.bytes is None
                    or member.metadata_bound_to_bytes is None for member in (self.finance, self.rss))):
            raise ValueError('expected_pair_identity_missing')
        return self


class _Extent(_Closed):
    state: Literal['verified', 'unknown']
    max_row: Annotated[int, Field(ge=1, le=20000)] | None
    max_column: Annotated[int, Field(ge=1, le=1000)] | None
    rectangle_cells: Annotated[int, Field(ge=1, le=2_000_000)] | None
    basis: Literal['complete_XML_full_ZIP_EOF_CRC_native_payload_rules', 'no_accepted_complete_extent']

    @model_validator(mode='after')
    def complete_or_unknown(self):
        dimensions = (self.max_row, self.max_column, self.rectangle_cells)
        if self.state == 'verified':
            if (None in dimensions or self.max_row * self.max_column != self.rectangle_cells
                    or self.basis != 'complete_XML_full_ZIP_EOF_CRC_native_payload_rules'):
                raise ValueError('extent_not_verified')
        elif dimensions != (None, None, None) or self.basis != 'no_accepted_complete_extent':
            raise ValueError('unknown_extent_has_dimensions')
        return self


_Counts = create_model('_Counts', __base__=_Closed,
    **{name: (Counter | None, ...) for name in _COUNT_NAMES})


class _States(_Closed):
    match: Counter | None
    no_match: Counter | None
    not_evaluated: Counter | None


_CF11 = create_model('_CF11', __base__=_Closed,
    **{name: (_States, ...) for name in source._FORMATTING_FORMULA_CHECKS})


class _Classification(_Closed):
    scan: Literal['complete', 'observed_prefix', 'not_observed']
    cf_state: Literal['accepted', 'absent', 'not_applicable', 'rejected', 'unknown']
    dv_state: Literal['accepted', 'absent', 'rejected', 'unknown']
    counts: _Counts
    cf11_sample_scope: Literal['native_CF_acceptance_predicate_evaluations_only']
    cf11: _CF11

    @model_validator(mode='after')
    def observed_lazy_states(self):
        counts = self.counts.model_dump()
        predicates = self.cf11.model_dump()
        if self.scan == 'not_observed':
            if (any(value is not None for value in counts.values())
                    or any(value is not None for states in predicates.values() for value in states.values())
                    or self.cf_state != 'unknown' or self.dv_state != 'unknown'):
                raise ValueError('unobserved_is_unknown')
            return self
        if (any(value is None for value in counts.values())
                or any(value is None for states in predicates.values() for value in states.values())):
            raise ValueError('observed_counters_missing')
        total = counts['cf_predicate_evaluations']
        active = total
        for name in source._FORMATTING_FORMULA_CHECKS:
            states = predicates[name]
            if (sum(states.values()) != total or states['not_evaluated'] != total - active
                    or states['match'] + states['no_match'] != active):
                raise ValueError('impossible_lazy_states')
            active = states['match']
        if (active != counts['cf_start_predicate_matches']
                or total > counts['foreign_formula_starts']
                or counts['cf_path_candidates'] > counts['foreign_formula_starts']
                or counts['rejected_foreign_formula_starts'] > counts['foreign_formula_starts']
                or counts['dv_formula_start_matches'] > counts['dv_formula1_starts'] + counts['dv_formula2_starts']):
            raise ValueError('classification_counter_mismatch')
        if self.scan != 'complete':
            if self.cf_state not in ('unknown', 'rejected') or self.dv_state not in ('unknown', 'rejected'):
                raise ValueError('prefix_is_not_acceptance')
        else:
            cf = ('accepted' if counts['cf_path_candidates'] else 'not_applicable'
                  if counts['dv_formula_start_matches'] else 'absent')
            dv = 'accepted' if counts['dv_containers_seen'] else 'absent'
            if (self.cf_state != cf or self.dv_state != dv
                    or counts['cf_start_predicate_matches'] != counts['cf_path_candidates']):
                raise ValueError('complete_classification_mismatch')
        return self


class _Failure(_Closed):
    stage: Literal['preflight', 'source_pair', 'rss_estimate', 'postflight', 'serialization']
    code: Literal['request_invalid', 'runtime_binding_mismatch', 'producer_binding_mismatch',
        'expected_source_mismatch', 'source_unavailable', 'source_changed', 'project_identity_changed',
        'worksheet_missing', 'extent_rejected', 'projection_size_limit', 'internal_proof_failure']
    extent_reason: Literal[tuple(sorted(source._EXTENT_REASONS))] | None
    context: Literal['root', 'sheet_data', 'row', 'cell', 'worksheet_metadata', 'unknown'] | None
    namespace_local_name: Literal['sheetData', 'row', 'c', 'v', 'f', 'is'] | None
    namespace_path_sha256: SHA | None
    namespace_path_depth: Annotated[int, Field(ge=1, le=64)] | None


class _Projection(_Closed):
    schema_version: Literal[1] = Field(alias='schema')
    purpose: Literal['budget_funding_layout_proof_v1']
    scope: Literal['rss_estimate_only']
    runtime: _Runtime
    producer_sha256: _ProducerMap
    current_pair: _Pair
    outcome: Literal['verified', 'rejected', 'source_unavailable', 'binding_mismatch']
    safe_extent: _Extent
    classification: _Classification
    remaining_failure: _Failure | None
    financial_acceptance: bool
    full_BPL_at_cut_confirmed: bool
    formulas_evaluated: bool
    source_files_written: bool
    metadata_import_aliases_retention_written: bool

    @field_validator('schema_version', mode='before')
    @classmethod
    def exact_schema_integer(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('schema_invalid')
        return value

    @model_validator(mode='after')
    def verified_only_after_stability(self):
        verified = self.outcome == 'verified'
        if (verified != (self.safe_extent.state == 'verified')
                or verified != (self.remaining_failure is None)
                or verified and (self.current_pair.state != 'stable_expected'
                    or self.current_pair.before_after_equal is not True
                    or self.classification.scan != 'complete')):
            raise ValueError('verified_layout_not_proven')
        if self.current_pair.state == 'changed' and (self.outcome != 'rejected'
                or self.current_pair.before_after_equal is not False):
            raise ValueError('changed_pair_not_rejected')
        if any(getattr(self, name) is not False for name in ('financial_acceptance',
                'full_BPL_at_cut_confirmed', 'formulas_evaluated', 'source_files_written',
                'metadata_import_aliases_retention_written')):
            raise ValueError('layout_is_not_financial_acceptance')
        return self


def parse_request(raw, *, start):
    try:
        if type(raw) is not bytes or len(raw) > MAX_REQUEST:
            raise ValueError()
        model = _StartRequest if start else _ResultRequest
        return model.model_validate(audit._json(raw)).model_dump()
    except (ValueError, TypeError, audit.AuditError):
        raise LayoutProblem('request_invalid') from None


def producer_hashes():
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / relative).read_bytes()).hexdigest()
            for name, relative in _PRODUCERS.items()}


def validate_bindings(expected, runtime):
    try:
        expected = _Expected.model_validate(expected).model_dump()
        runtime = _Runtime.model_validate(runtime).model_dump()
        if runtime['commit'] != expected['runtime_commit']:
            raise LayoutProblem('runtime_binding_mismatch')
        producers = producer_hashes()
        if producers != expected['producer_sha256']:
            raise LayoutProblem('producer_binding_mismatch')
        return expected, runtime, producers
    except LayoutProblem:
        raise
    except (ValueError, TypeError, OSError):
        raise LayoutProblem('request_invalid') from None


def _failure(stage, code, proof=None):
    proof = source._checked_extent_failure(proof) if proof else None
    fingerprint = proof.get('namespace_path_fingerprint', {}) if proof else {}
    namespace = proof.get('namespace_rejection', {}) if proof else {}
    return {'stage': stage, 'code': code, 'extent_reason': proof['reason'] if proof else None,
        'context': proof['context'] if proof else None,
        'namespace_local_name': namespace.get('local_name'),
        'namespace_path_sha256': fingerprint.get('sha256'),
        'namespace_path_depth': proof.get('namespace_structure', {}).get('depth') if fingerprint else None}


def _member(identity):
    identity = identity or {}
    return {key: identity.get(key) for key in ('sha256', 'bytes', 'metadata_sha256', 'metadata_bound_to_bytes')}


def _classification(observation):
    scan = observation.get('scan', 'not_observed')
    observed = scan != 'not_observed'
    counts = observation.get('counts', {})
    if scan == 'complete':
        cf = ('accepted' if counts['cf_path_candidates'] else 'not_applicable'
              if counts['dv_formula_start_matches'] else 'absent')
        dv = 'accepted' if counts['dv_containers_seen'] else 'absent'
    else:
        cf = 'rejected' if observation.get('cf_rejected') else 'unknown'
        dv = 'rejected' if observation.get('dv_rejected') else 'unknown'
    return {'scan': scan, 'cf_state': cf, 'dv_state': dv,
        'counts': {name: counts.get(name) if observed else None for name in _COUNT_NAMES},
        'cf11_sample_scope': 'native_CF_acceptance_predicate_evaluations_only',
        'cf11': observation.get('cf11') if observed else {
            name: dict.fromkeys(('match', 'no_match', 'not_evaluated'))
            for name in source._FORMATTING_FORMULA_CHECKS}}


def validate_projection(value):
    """Reject impossible/extra fields before a DTO enters the native job store."""
    try:
        checked = _Projection.model_validate(value).model_dump(by_alias=True)
        encoded = json.dumps(checked, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > MAX_OUTPUT:
            raise LayoutProblem('projection_size_limit')
        failure = checked['remaining_failure']
        if failure is not None and len(json.dumps(failure, ensure_ascii=False).encode()) > MAX_FAILURE:
            raise LayoutProblem('projection_size_limit')
        return checked
    except (ValueError, TypeError):
        raise LayoutProblem('projection_size_limit') from None


def capture_layout_proof(project, cut, expected, *, runtime):
    expected, runtime, producers = validate_bindings(expected, runtime)
    observation, proof_failure = {}, {}
    extent = None
    before = None
    identity_matches = False
    finance_source = rss_source = None
    pair_state, equal, outcome = 'unknown', None, 'source_unavailable'
    failure = _failure('source_pair', 'source_unavailable')
    try:
        _, fm_meta, finance_source = ahr._copy(project)
        raw, rss_meta, rss_source = source._rss_copy(project, cut)
        before = copy.deepcopy((fm_meta, finance_source, rss_meta, rss_source))
        identity_matches = (raw is not None
            and finance_source.get('sha256') == expected['finance_sha256']
            and rss_source.get('sha256') == expected['rss_sha256']
            and all(item.get('namespace_sha256') == expected['namespace_sha256']
                    and item.get('aliases_sha256') == expected['aliases_sha256']
                    for item in (finance_source, rss_source)))
        if not identity_matches:
            outcome = 'binding_mismatch' if raw is not None else 'source_unavailable'
            failure = _failure('source_pair', 'expected_source_mismatch' if raw is not None else 'source_unavailable')
        else:
            outcome = 'rejected'
            with source._book(raw) as book:
                if source.ESTIMATE not in book.sheetnames:
                    failure = _failure('rss_estimate', 'worksheet_missing')
                else:
                    extent = source._verified_payload_extent(book[source.ESTIMATE],
                        _failure=proof_failure, _observation=observation)
                    failure = None if extent is not None else _failure('rss_estimate', 'extent_rejected', proof_failure)
    except Exception:
        # No arbitrary source/exception text survives. Postflight still runs.
        extent = None
        failure = _failure('rss_estimate' if before is not None else 'source_pair', 'source_unavailable')
        outcome = 'source_unavailable'
    finally:
        if before is not None:
            after = []
            after_errors = []
            # Deliberately independent attempts: failure of FM must not skip RSS.
            for reader in (lambda: ahr._copy(project), lambda: source._rss_copy(project, cut)):
                try:
                    _, metadata, identity = reader()
                    after.extend((metadata, identity))
                except Exception as exc:
                    after_errors.append(isinstance(exc, source.SourceProblem) and exc.code == 'source_changed')
            if after_errors:
                extent = None
                if any(after_errors):
                    pair_state, equal, outcome = 'changed', False, 'rejected'
                    failure = _failure('postflight', 'source_changed')
                else:
                    pair_state, equal, outcome = 'unknown', None, 'source_unavailable'
                    failure = _failure('postflight', 'source_unavailable')
            elif tuple(after) != before:
                pair_state, equal, outcome, extent = 'changed', False, 'rejected', None
                failure = _failure('postflight', 'source_changed')
            else:
                equal = True
                pair_state = 'stable_expected' if identity_matches else 'stable_mismatch'

    verified = (extent is not None and observation.get('scan') == 'complete'
                and pair_state == 'stable_expected' and equal is True and failure is None)
    if verified:
        outcome = 'verified'
    else:
        extent = None
        failure = failure or _failure('rss_estimate', 'internal_proof_failure')
    pair = {'state': pair_state, 'before_after_equal': equal,
        'namespace_sha256': (finance_source or {}).get('namespace_sha256'),
        'aliases_sha256': (finance_source or {}).get('aliases_sha256'),
        'finance': _member(finance_source), 'rss': _member(rss_source),
        'rss_version_date': (rss_source or {}).get('version_date'),
        'historical_financial_eligibility': 'not_assessed'}
    return validate_projection({'schema': 1, 'purpose': PURPOSE, 'scope': SCOPE,
        'runtime': runtime, 'producer_sha256': producers, 'current_pair': pair, 'outcome': outcome,
        'safe_extent': {'state': 'verified' if verified else 'unknown',
            'max_row': extent[0] if verified else None, 'max_column': extent[1] if verified else None,
            'rectangle_cells': extent[0] * extent[1] if verified else None,
            'basis': 'complete_XML_full_ZIP_EOF_CRC_native_payload_rules' if verified else 'no_accepted_complete_extent'},
        'classification': _classification(observation), 'remaining_failure': failure,
        'financial_acceptance': False, 'full_BPL_at_cut_confirmed': False, 'formulas_evaluated': False,
        'source_files_written': False, 'metadata_import_aliases_retention_written': False})
