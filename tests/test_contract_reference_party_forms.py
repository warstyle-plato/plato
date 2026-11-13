"""Source display order must not lose the full-price join or rekey a contract."""
from __future__ import annotations

import pytest

import developaid_monitor_contracts as contracts
from test_contracts_from_cumulative_headers import context, parsed, provide, rss_contract


@pytest.mark.parametrize('source,reference', [
    ('НУР ООО', 'ООО «НУР»'),
    ('ООО «НУР»', 'НУР ООО'),
    ('НУР Общество с ограниченной ответственностью', 'ООО «НУР»'),
])
def test_suffix_party_form_preserves_full_price_percent_and_contract_id(context, source, reference):
    snapshot = parsed()
    snapshot['ledgers'][0]['contractor'] = source
    reference_row = rss_contract(contractor=source)
    provide(context, snapshot, [reference_row])
    before, = contracts.build('Example', '2026-11-06')['rows']
    reference_row['contractor'] = reference
    after, = contracts.build('Example', '2026-11-06')['rows']
    assert after['amount'] == 1000
    assert after['completed'] == 400 and after['completion_ratio'] == .4
    assert after['id'] == before['id']
    assert after['contractor'] == source
    assert after['rss_match']['status'] == 'matched'


@pytest.mark.parametrize('reference', ['АО «НУР»', 'ИП НУР', 'ООО «НУР ООО»', 'ООО «НУР Строй»'])
def test_suffix_does_not_merge_different_explicit_party_or_named_suffix(context, reference):
    snapshot = parsed()
    snapshot['ledgers'][0]['contractor'] = 'НУР ООО'
    provide(context, snapshot, [rss_contract(contractor=reference)])
    row, = contracts.build('Example', '2026-11-06')['rows']
    assert row['amount'] is None and row['completion_ratio'] is None
