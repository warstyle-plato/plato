"""Full QName identity is a private digest, never an ancestry acceptance rule."""
import hashlib
import json

import pytest

import developaid_budget_funding_source as proof
from test_budget_funding_effective_extent import FakeSheet, NS, xml
from test_budget_funding_root_structure_diagnostic import outer


SCHEMA = 'expanded-qname-path-v1'
XM = 'http://schemas.microsoft.com/office/excel/2006/main'
ROW = '<row r="1"><c r="A1"><v>1</v></c></row>'
CANARY = 'SYNTHETIC-QNAME-NOT-EXPORTED'


def witness(wrapper='alpha', uri='urn:synthetic:qname:a'):
    extension = (f'<extLst><ext><u:{wrapper} xmlns:u="{uri}">'
                 f'<xm:f xmlns:xm="{XM}">SYNTHETIC-FORMULA-NOT-HASHED</xm:f>'
                 f'</u:{wrapper}></ext></extLst></worksheet>')
    return xml(ROW).replace(b'</worksheet>', extension.encode())


def rejection(raw):
    failure = {}
    assert proof._verified_payload_extent(FakeSheet(raw), _failure=failure) is None
    assert failure['reason'] == 'payload_namespace_unknown'
    assert failure['complete_proof'] is False
    return failure


def test_native_rejection_retains_a_closed_full_path_digest_at_the_same_witness():
    failure = rejection(witness())
    stack = [f'{{{NS}}}worksheet', f'{{{NS}}}extLst', f'{{{NS}}}ext',
             '{urn:synthetic:qname:a}alpha', f'{{{XM}}}f']
    canonical = json.dumps({'schema': SCHEMA, 'path': stack}, ensure_ascii=False,
                           sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert failure['namespace_path_fingerprint'] == {'schema': SCHEMA, 'sha256': hashlib.sha256(canonical).hexdigest()}
    assert set(failure['namespace_structure']) == {'path', 'depth', 'truncated', 'other', 'first_unmet', 'checks'}
    assert failure['namespace_structure']['checks'] == ['no_match'] + ['not_evaluated'] * 10
    assert proof._checked_extent_failure(failure) == failure
    assert outer(failure)['extent_proof'] == failure


@pytest.mark.parametrize('wrapper,uri', [('bravo', 'urn:synthetic:qname:a'), ('alpha', 'urn:synthetic:qname:b')])
def test_same_visible_other_tokens_do_not_erase_full_QName_identity(wrapper, uri):
    first, second = rejection(witness()), rejection(witness(wrapper, uri))
    assert first['namespace_structure'] == second['namespace_structure']
    assert first['namespace_rejection'] == second['namespace_rejection']
    assert first['namespace_path_fingerprint'] != second['namespace_path_fingerprint']


def test_prefix_formula_text_and_arbitrary_attributes_are_not_part_of_QName_path():
    first = rejection(witness())
    renamed = witness().replace(b'xmlns:u=', b'xmlns:z=').replace(b'u:alpha', b'z:alpha')
    changed = renamed.replace(b'SYNTHETIC-FORMULA-NOT-HASHED', CANARY.encode()).replace(
        b'<xm:f ', ('<xm:f private="'+CANARY+'" ').encode())
    second = rejection(changed)
    assert first['namespace_path_fingerprint'] == second['namespace_path_fingerprint']
    assert CANARY not in json.dumps(second)


def test_full_order_and_tail_after_visible_truncation_affect_the_digest():
    a, b = '{urn:synthetic}alpha', '{urn:synthetic}bravo'
    assert proof._namespace_path_fingerprint([a, b]) != proof._namespace_path_fingerprint([b, a])
    def raw(tail):
        names = ['node'+str(i) for i in range(14)] + [tail]
        body = '<extLst><ext>' + ''.join('<'+n+'>' for n in names)
        body += f'<xm:f xmlns:xm="{XM}"/>' + ''.join('</'+n+'>' for n in reversed(names))
        return xml(ROW).replace(b'</worksheet>', (body+'</ext></extLst></worksheet>').encode())
    first, second = rejection(raw('tail_a')), rejection(raw('tail_b'))
    assert first['namespace_structure'] == second['namespace_structure']
    assert first['namespace_structure']['truncated'] is True
    assert first['namespace_path_fingerprint'] != second['namespace_path_fingerprint']


def test_UTF8_canonicalization_preserves_exact_nonASCII_codepoints():
    stack = ['{urn:synthetic:é}узел', '{urn:synthetic}😀']
    canonical = json.dumps({'schema': SCHEMA, 'path': stack}, ensure_ascii=False,
                           sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert proof._namespace_path_fingerprint(stack)['sha256'] == hashlib.sha256(canonical).hexdigest()
    assert proof._namespace_path_fingerprint(stack) != proof._namespace_path_fingerprint(['{urn:synthetic:e\u0301}узел', stack[1]])


@pytest.mark.parametrize('depth', [1, 12, 64])
def test_complete_depth_up_to_the_existing_scan_boundary_is_hashed(depth):
    assert proof._namespace_path_fingerprint(['{urn:synthetic}node']*depth)['schema'] == SCHEMA
    assert proof._namespace_path_fingerprint(['{urn:synthetic}node']*65) is None


@pytest.mark.parametrize('stack', [None, {}, 'private', [], [''], [b'node'], [1], ['\ud800']])
def test_malformed_stack_has_no_partial_or_exception_text_fingerprint(stack):
    assert proof._namespace_path_fingerprint(stack) is None


def test_canonical_byte_limit_is_exact_and_huge_input_is_rejected_before_encoding(monkeypatch):
    tag = '{urn:synthetic}node'
    overhead = len(json.dumps({'schema': SCHEMA, 'path': [tag]}, ensure_ascii=False,
                             sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    full = tag + 'x'*(65536-overhead)
    assert proof._namespace_path_fingerprint([full]) is not None
    assert proof._namespace_path_fingerprint([full+'x']) is None
    monkeypatch.setattr(proof.json, 'dumps', lambda *a, **k: pytest.fail('huge path entered JSON encoder'))
    assert proof._namespace_path_fingerprint(['x'*65537]) is None


def test_budget_omission_changes_only_the_optional_field_and_keeps_the_same_refusal(monkeypatch):
    full = rejection(witness())
    monkeypatch.setattr(proof, '_QNAME_PATH_FINGERPRINT_MAX_BYTES', 1)
    missing = rejection(witness())
    assert missing == {k: v for k, v in full.items() if k != 'namespace_path_fingerprint'}
    assert proof._checked_extent_failure(missing) == missing


@pytest.mark.parametrize('change', [{'schema': 'unknown'}, {'schema': 1}, {'sha256': 'a'*63},
    {'sha256': 'A'*64}, {'sha256': 'g'*64}, {'sha256': []}, {'extra': CANARY}])
def test_malformed_optional_pair_is_rejected_without_losing_false_acceptance_flags(change):
    value = rejection(witness())
    value['namespace_path_fingerprint'].update(change)
    assert proof._checked_extent_failure(value) is None
    diagnostic = outer(value)
    assert 'extent_proof' not in diagnostic
    assert diagnostic['complete_projection'] is diagnostic['financial_acceptance'] is False
    assert CANARY not in json.dumps(diagnostic)


@pytest.mark.parametrize('field', ['namespace_rejection', 'namespace_structure'])
def test_fingerprint_cannot_be_attached_without_both_existing_witness_records(field):
    value = rejection(witness());value.pop(field)
    assert proof._checked_extent_failure(value) is None


def test_outer_cap_omits_only_optional_digest_while_retaining_the_previous_witness(monkeypatch):
    full = rejection(witness())
    legacy = {k: v for k, v in full.items() if k != 'namespace_path_fingerprint'}
    expected = outer(legacy)
    limit = len(json.dumps(expected, ensure_ascii=False, allow_nan=False).encode())
    monkeypatch.setattr(proof, 'MAX_FAILURE_DIAGNOSTIC', limit)
    assert outer(full) == expected


def test_per_call_fingerprint_is_cleared_on_other_failure_and_success():
    value = rejection(witness())
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="20001"><c r="A20001"><v>1</v></c></row>')),
                                          _failure=value) is None
    assert 'namespace_path_fingerprint' not in value
    assert proof._verified_payload_extent(FakeSheet(witness()), _failure=value) is None
    assert 'namespace_path_fingerprint' in value
    assert proof._verified_payload_extent(FakeSheet(xml(ROW)), _failure=value) == (1, 1)
    assert 'namespace_path_fingerprint' not in value
