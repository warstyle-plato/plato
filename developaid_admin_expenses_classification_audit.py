"""Bounded classification evidence, never a change to observed cash or a verdict."""
from __future__ import annotations
from decimal import Decimal
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets

import developaid_actuals as actuals

ARTICLE = 'project_management'
MAX_CASES, MAX_GROUPS, MAX_MEMBERS, MAX_CODES = 128, 64, 128, 16
MAX_BYTES = 131072
_CODE = re.compile(r'[0-9]+(?:\.[0-9]+)*\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ARTICLES = {article for _, article in actuals._BDDS_TO_ARTICLE}
_ARTICLES.update(article for pair in actuals._BDDS_GNS_SPLIT.values() for article in pair)
_BASES = {'по договору и коду РСС':'contract_and_estimate', 'по договору':'contract',
          'по контрагенту':'party', 'по коду РСС':'estimate_code', 'unresolved':'unresolved'}


def _code(value):
    return value if isinstance(value, str) and len(value) <= 96 and _CODE.fullmatch(value) else None


def _row(value):
    return value if type(value) is int and 1 <= value <= 1048576 else None


def _possible(event):
    return event['scope_unknown'] or ARTICLE in event['possible_articles']


def _limit(value):
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()) <= MAX_BYTES:
        return value
    value = {key: item for key, item in value.items() if key not in ('cases', 'duplicate_groups')}
    value.update(state='byte_limit', truncated=True, cases=[], duplicate_groups=[],
                 emitted_cases=0, omitted_cases=value.get('total_cases', 0),
                 emitted_groups=0, omitted_groups=value.get('total_groups', 0))
    return value


def unavailable(reason='diagnostic_unavailable'):
    if reason not in ('diagnostic_unavailable','no_eligible_focus_month','source_row_identity_unavailable'):
        reason = 'diagnostic_unavailable'
    return {'schema': 1, 'scope': 'classification_evidence_only', 'state': reason,
            'algorithm': 'ahr-classification-audit-v1', 'classifier_code_fingerprint': actuals._SOURCE_PRINT,
            'financial_acceptance': False, 'confirmed_excess': None, 'cases': [], 'duplicate_groups': []}


class AuditEvents(list):
    """The existing event list, plus optional read-only classifier evidence."""
    def __init__(self, number, scalar):
        super().__init__()
        self._number, self._scalar = number, scalar
        self._key = secrets.token_bytes(32)
        self._evidence = {}
        self._groups = {}
        self._row_groups = {}
        self._failed = False

    def __call__(self, event):
        self.append(event)

    def record_failure(self):
        self._failed = True

    def _link(self, domain, value):
        material = json.dumps(value, ensure_ascii=True, default=str, separators=(',', ':')).encode()
        return hmac.new(self._key, domain.encode()+b'\0'+material, hashlib.sha256).hexdigest()

    def fingerprint(self, item, key):
        try:
            group = self._groups.get(key)
            if group is None:
                group = {'token': self._link('cash-duplicate-v1', key), 'day': item['date'], 'rows': []}
                self._groups[key] = group
            row = item.get('source_row')
            group['rows'].append(row)
            self._row_groups[row] = group
        except Exception:
            self._failed = True

    def record_candidates(self, event, *, exact_codes, contract_codes, party_codes,
                          official_articles, normalized_pair, normalized_contract, flags):
        try:
            self._evidence[id(event)] = {'exact': exact_codes, 'contract': contract_codes,
                'party': party_codes, 'official': official_articles,
                'pair_token': self._link('cash-normalized-pair-v1', normalized_pair),
                'contract_token': self._link('cash-normalized-contract-v1', normalized_contract),
                'binding_flags': {key: value if type(value) is bool else None for key, value in flags.items()
                    if key in ('party_present','contract_present','party_normalized_empty','contract_normalized_empty','pair_normalized_empty')}}
        except Exception:
            self._failed = True

    def _candidate(self, codes):
        if codes is None:
            return None
        valid = sorted(code for code in codes if _code(code) is not None)
        articles = {actuals.article_for(code)[0] for code in codes}
        known = sorted(article for article in articles if article in _ARTICLES)
        return {'codes': valid[:MAX_CODES], 'total_codes': len(codes), 'emitted_codes': min(len(valid), MAX_CODES),
            'omitted_codes': len(codes)-min(len(valid), MAX_CODES), 'redacted_codes': len(codes)-len(valid),
            'articles': known[:MAX_CODES], 'total_articles': len(articles),
            'unmapped_articles': int(None in articles), 'emitted_articles': min(len(known), MAX_CODES),
            'omitted_articles': len(articles)-min(len(known), MAX_CODES),
            'truncated': len(valid) > MAX_CODES or len(known) > MAX_CODES or len(valid) != len(codes)}

    def _case(self, event):
        evidence = self._evidence.get(id(event))
        if evidence is None:
            raise ValueError('classification_evidence_missing')
        official = evidence['official']
        selected = event['article']
        if official is None:
            state = 'unavailable'
        elif not official:
            state = 'missing'
        elif any(article not in _ARTICLES for article in official):
            state = 'redacted_or_unmapped'
        elif len(official) > 1:
            state = 'ambiguous'
        elif selected is None:
            state = 'unique_unselected'
        elif selected in official:
            state = 'same_unique_article'
        else:
            state = 'different_unique_article'
        known_official = sorted(article for article in (official or ()) if article in _ARTICLES)
        group = self._row_groups.get(event['source_row'])
        return {'case_kind': 'included_ahr' if selected == ARTICLE else 'unresolved_duplicate_member',
            'source_row': _row(event['source_row']), 'date': event['date'].isoformat(),
            'signed_amount': self._scalar(self._number(event['amount'])),
            'estimate_code': _code(event['estimate_code']),
            'estimate_code_state': 'canonical' if _code(event['estimate_code']) else 'missing_or_redacted',
            'selected_article': selected if selected in _ARTICLES else None,
            'selected_basis': _BASES.get(event['basis'], 'unavailable'),
            'exact_pair_estimate': self._candidate(evidence['exact']),
            'whole_contract': self._candidate(evidence['contract']),
            'party_when_used': self._candidate(evidence['party']),
            'official_code': {'state': state, 'articles': known_official[:MAX_CODES],
                'total_articles': len(official) if official is not None else None,
                'emitted_articles': len(known_official[:MAX_CODES]),
                'omitted_articles': len(official)-len(known_official[:MAX_CODES]) if official is not None else None,
                'truncated': official is not None and len(official) != len(known_official[:MAX_CODES]),
                'is_wrong_payment_verdict': False},
            'pair_token': evidence['pair_token'], 'contract_token': evidence['contract_token'],
            'binding_flags': evidence['binding_flags'],
            'duplicate_group_token': group['token'] if group and len(group['rows']) > 1 else None}

    def _sum(self, events, empty_zero=False):
        values = [self._number(event['amount']) for event in events]
        known = [value for value in values if value is not None]
        return {'signed_amount': self._scalar(sum(known, Decimal(0))) if len(known) == len(values) and (known or empty_zero) else None,
                'signed_known_part': self._scalar(sum(known, Decimal(0))) if known else None,
                'unknown_amount_count': len(values)-len(known)}

    def build(self, months):
        try:
            return self._build(months)
        except Exception:
            return unavailable()

    def _build(self, months):
        if self._failed:
            return unavailable()
        eligible = [month for month in months if month['source'] == 'rss_observed'
                    and month['duplicate_suspected'] and self._number(month['paid']) is not None]
        if not eligible:
            return unavailable('no_eligible_focus_month')
        focus = min(eligible, key=lambda month: (-abs(self._number(month['paid'])), month['month']))
        month = focus['month']
        in_month = [event for event in self if event['date'] and event['date'].replace(day=1).isoformat() == month]
        selected_cases = [event for event in in_month if event['article'] == ARTICLE]
        invalid_rows = [event for event in in_month if _row(event['source_row']) is None]
        row_ids = [event['source_row'] for event in in_month]
        if invalid_rows or len(set(row_ids)) != len(row_ids):
            result = unavailable('source_row_identity_unavailable')
            result.update(focus_month=month, focus_paid_observed_net=focus['paid'],
                focus_selected_ahr=self._sum(selected_cases), unknown_row_count=len(invalid_rows),
                repeated_row_id_occurrences=len(row_ids)-len(set(row_ids)), truncated=True)
            return result
        by_row = {}
        for event in in_month:
            by_row.setdefault(event['source_row'], []).append(event)
        group_records = []
        unresolved_evidence_rows = set()
        for group in self._groups.values():
            if len(group['rows']) < 2 or group['day'].replace(day=1).isoformat() != month:
                continue
            members = [event for row in group['rows'] for event in by_row.get(row, ())]
            possible = any(_possible(event) for event in members)
            selected = [event for event in members if event['article'] == ARTICLE]
            unresolved = [event for event in members if event['article'] is None and _possible(event)]
            unresolved_evidence_rows.update(event['source_row'] for event in unresolved)
            if not possible and not selected:
                continue
            rows = [_row(row) for row in group['rows']]
            valid_rows = [row for row in rows if row is not None]
            group_records.append({'token': group['token'], 'cardinality': len(rows),
                'member_source_rows': valid_rows[:MAX_MEMBERS], 'emitted_members': min(len(valid_rows), MAX_MEMBERS),
                'omitted_members': len(rows)-min(len(valid_rows), MAX_MEMBERS),
                'unknown_row_count': len(rows)-len(valid_rows), 'truncated': len(rows) > MAX_MEMBERS or len(rows) != len(valid_rows),
                'triggers_existing_month_flag': possible, 'included_ahr_cases': len(selected),
                'included_ahr': self._sum(selected, empty_zero=True),
                'unresolved_members': len(unresolved), 'unresolved': self._sum(unresolved), 'confirmed_excess': None})
        group_records.sort(key=lambda group: (min(group['member_source_rows'], default=1048577), group['token']))
        cases = [event for event in in_month if event['article'] == ARTICLE or event['source_row'] in unresolved_evidence_rows]
        emitted = [self._case(event) for event in cases[:MAX_CASES]]
        groups = group_records[:MAX_GROUPS]
        truncated = len(cases) > MAX_CASES or len(group_records) > MAX_GROUPS or any(group['truncated'] for group in groups)
        truncated = truncated or any(part and part.get('truncated') for case in emitted
            for part in (case['exact_pair_estimate'], case['whole_contract'], case['party_when_used'], case['official_code']))
        result = {'schema': 1, 'scope': 'classification_evidence_only', 'state': 'bounded_observation',
            'algorithm': 'ahr-classification-audit-v1', 'classifier_code_fingerprint': actuals._SOURCE_PRINT,
            'focus_month': month, 'focus_paid_observed_net': focus['paid'],
            'focus_selected_ahr': self._sum(selected_cases), 'focus_selected_ahr_cases': len(selected_cases),
            'unresolved_duplicate_evidence_cases': len(cases)-len(selected_cases), 'total_cases': len(cases), 'emitted_cases': len(emitted),
            'omitted_cases': len(cases)-len(emitted), 'total_groups': len(group_records), 'emitted_groups': len(groups),
            'omitted_groups': len(group_records)-len(groups), 'focus_possible_ahr_unresolved_cases': sum(
                event['article'] is None and _possible(event) for event in in_month),
            'unknown_date_possible_ahr_cases_outside_focus': sum(not event['date'] and _possible(event) for event in self),
            'cases': emitted, 'duplicate_groups': groups, 'truncated': bool(truncated),
            'financial_acceptance': False, 'confirmed_excess': None,
            'duplicate_identity_state': 'fingerprint_has_no_unique_bank_transaction_identity'}
        return _limit(result)


def bind_sources(audit, sources, errors):
    """Only existing postchecked identities; diagnostic failures never affect money."""
    try:
        result = dict(audit)
        result['source_binding'] = {}
        for name in ('fm','rss'):
            identity = sources.get(name) or {}
            clean = {key: value if isinstance(value, str) and _SHA.fullmatch(value) else None
                     for key, value in identity.items() if key in ('sha256','metadata_sha256','namespace_sha256','aliases_sha256')}
            date = identity.get('version_date')
            try:
                clean['version_date'] = date if isinstance(date, str) and dt.date.fromisoformat(date).isoformat() == date else None
            except ValueError:clean['version_date'] = None
            bound = identity.get('metadata_bound_to_bytes')
            clean['metadata_bound_to_bytes'] = bound if type(bound) is bool else None
            result['source_binding'][name] = clean
        commit = os.getenv('APP_COMMIT', '')
        result['runtime_commit'] = commit if re.fullmatch('[0-9a-f]{40}', commit) else None
        if errors:
            result.update(state='source_changed' if any('changed' in str(value) for value in errors.values()) else 'source_unavailable',
                          cases=[], duplicate_groups=[], emitted_cases=0, emitted_groups=0,
                          omitted_cases=result.get('total_cases'), omitted_groups=result.get('total_groups'), truncated=True)
        return _limit(result)
    except Exception:
        return unavailable()
