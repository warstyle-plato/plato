"""Synthetic namespace metadata stays in rejected, private admin BPL proofs."""
import concurrent.futures
import hashlib
import json
from xml.sax.saxutils import quoteattr
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

import developaid_budget_funding_source as proof
import developaid_monitor as monitor
import main as wrapper
from test_budget_funding_effective_extent import FakeSheet, xml, inflated, changed_member, TAG
from test_budget_funding_source_proof import (source, rss_bytes, replace_rss, call, poll,
                                             PROJECT, CUT, KEY)  # noqa: F401

URI = 'urn:synthetic:bpl-rejected-namespace'
CANARY = 'SYNTHETIC-XML-TEXT-ATTRIBUTE-CANARY'
LOCALS = ('sheetData', 'row', 'c', 'v', 'f', 'is')


def rejected_xml(uri=URI, local='f'):
    raw = xml('<row r="1"><c r="A1"><v>1</v></c></row>')
    foreign = ('<extLst><ext uri="urn:synthetic:metadata"><other:' + local
               + ' xmlns:other=' + quoteattr(uri) + ' private=' + quoteattr(CANARY)
               + '>' + CANARY + '</other:' + local + '></ext></extLst>').encode()
    return raw.replace(b'</worksheet>', foreign + b'</worksheet>')


def rejection(raw, failure=None):
    failure = {} if failure is None else failure
    assert proof._verified_payload_extent(FakeSheet(raw), _failure=failure) is None
    assert failure['reason'] == 'payload_namespace_unknown'
    assert failure['complete_proof'] is False
    return failure


def outer(failure):
    exc = proof._WorksheetSizeProblem(proof.ESTIMATE, 900000, 200, failure)
    exc.captured_source = {'sha256': 'a' * 64, 'bytes': 1234, 'path': CANARY}
    assert str(exc) == 'worksheet_size_limit'
    return proof.failure_diagnostic(exc)


@pytest.mark.parametrize('local', LOCALS)
def test_actual_foreign_tag_remains_refused_with_only_bounded_namespace_metadata(local):
    value = rejection(rejected_xml(local=local))
    assert value['context'] == 'worksheet_metadata'
    assert value['namespace_rejection'] == {'namespace_uri': URI, 'local_name': local,
                                            'truncated': False}
    diag = outer(value)
    assert diag['extent_proof'] == value and diag['stage'] == 'rss_estimate'
    assert diag['source_identity'] == {'kind': 'rss', 'sha256': 'a' * 64, 'bytes': 1234}
    assert len(json.dumps(diag).encode()) <= 2048
    assert CANARY not in json.dumps(diag)
    assert not diag['complete_projection'] and not diag['financial_acceptance']
    assert 'namespace_rejection' not in str(proof._ExtentProofProblem('payload_namespace_unknown'))


@pytest.mark.parametrize('byte_length', [255, 256, 257])
def test_real_rejection_preserves_exact_URI_or_explicit_truncation(byte_length):
    uri = 'urn:synthetic:' + 'x' * (byte_length - len('urn:synthetic:'))
    got = rejection(rejected_xml(uri))['namespace_rejection']
    assert got == {'namespace_uri': uri if byte_length <= 256 else None,
                   'local_name': 'f', 'truncated': byte_length > 256}
    assert got == outer(rejection(rejected_xml(uri)))['extent_proof']['namespace_rejection']


@pytest.mark.parametrize('uri,accepted', [('', True), ('é' * 128, True),
    ('é' * 127 + 'x', True), ('é' * 128 + 'x', False), ('😀' * 64, True),
    ('😀' * 64 + 'x', False), ('x' * 100000, False)])
def test_namespace_limit_is_UTF8_bytes_without_prefix_or_normalization(uri, accepted):
    got = proof._namespace_rejection('{' + uri + '}v')
    assert got == {'namespace_uri': uri if accepted else None,
                   'local_name': 'v', 'truncated': not accepted}
    assert proof._checked_extent_failure({**rejection(rejected_xml()), 'namespace_rejection': got}) is not None


def test_unqualified_native_local_records_observed_absence_not_an_unknown_URI():
    raw = xml('<row r="1"><c r="A1"><v>1</v></c></row>')
    raw = raw.replace(b'</worksheet>', b'<f xmlns=""/></worksheet>')
    got = rejection(raw)['namespace_rejection']
    assert got == {'namespace_uri': '', 'local_name': 'f', 'truncated': False}


@pytest.mark.parametrize('value', [None, 1, {}, [], '{urn:synthetic}private', 'other}f', '\ud800'])
def test_invalid_or_non_native_local_cannot_become_namespace_export(value):
    assert proof._namespace_rejection(value) is None


@pytest.mark.parametrize('change', [
    {'namespace_uri': None, 'truncated': False}, {'namespace_uri': URI, 'truncated': True},
    {'namespace_uri': 'é' * 129}, {'namespace_uri': 1}, {'namespace_uri': '\ud800'},
    {'local_name': 'private'}, {'local_name': []}, {'truncated': 1}, {'extra': CANARY}])
def test_malformed_nested_metadata_falls_back_to_the_existing_typed_failure(change):
    value = rejection(rejected_xml())
    value['namespace_rejection'].update(change)
    assert proof._checked_extent_failure(value) is None
    diag = outer(value)
    assert diag['stage'] == 'rss_estimate' and 'extent_proof' not in diag
    assert not diag['complete_projection'] and CANARY not in json.dumps(diag)


def test_namespace_metadata_cannot_be_attached_to_an_unrelated_refusal():
    value = rejection(rejected_xml())
    value['reason'] = 'xml_parse_failure'
    assert proof._checked_extent_failure(value) is None
    assert 'extent_proof' not in outer(value)


def test_omitted_QName_or_truncated_URI_does_not_imply_namespace_identified():
    legacy = rejection(rejected_xml())
    legacy.pop('namespace_rejection')
    assert proof._checked_extent_failure(legacy) == legacy
    assert outer(legacy)['extent_proof'] == legacy
    truncated = rejection(rejected_xml('urn:synthetic:' + 'x' * 300))
    assert truncated['namespace_rejection']['namespace_uri'] is None
    assert truncated['namespace_rejection']['truncated'] is True
    assert truncated['complete_proof'] is False


def test_per_invocation_metadata_is_not_reused_after_other_failure_or_success():
    value = rejection(rejected_xml())
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="20001"><c r="A20001"><v>1</v></c></row>')),
                                          _failure=value) is None
    assert value['reason'] == 'payload_size_limit' and 'namespace_rejection' not in value
    rejection(rejected_xml(), value)
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="1"><c r="A1"><v>1</v></c></row>')),
                                          _failure=value) == (1, 1)
    assert 'namespace_rejection' not in value


def test_concurrent_invocations_never_share_the_rejected_tag():
    uris = ['urn:synthetic:independent:' + str(i) for i in range(24)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        values = list(pool.map(lambda uri: rejection(rejected_xml(uri)), uris))
    assert [v['namespace_rejection']['namespace_uri'] for v in values] == uris
    assert all(v['namespace_rejection']['local_name'] == 'f' for v in values)


def rejected_book():
    raw = rss_bytes()
    def edit(data):
        root = ET.fromstring(data)
        extension = ET.SubElement(ET.SubElement(root, TAG + 'extLst'), TAG + 'ext',
                                  {'uri': 'urn:synthetic:metadata'})
        ET.SubElement(extension, '{' + URI + '}f', {'private': CANARY}).text = CANARY
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return changed_member(inflated(raw), 'xl/worksheets/sheet1.xml', edit)


def test_native_admin_job_retains_private_QName_with_exact_source_and_no_money_projection(source, caplog):
    raw = rejected_book()
    replace_rss(source, raw)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in source[0].rglob('*') if p.is_file()}
    client = TestClient(wrapper.core.app)
    started = call(client, project=PROJECT, cut=CUT, ticket='b' * 32)
    assert started.status_code == 202 and started.headers['cache-control'] == 'private, no-store'
    wrong = poll(client, 'b' * 32, session='other')
    assert wrong.status_code == 404 and URI not in wrong.text
    response = poll(client, 'b' * 32)
    assert response.status_code == 200 and response.headers['cache-control'] == 'private, no-store'
    result = response.json()
    assert result['ok'] is False and result['code'] == 'worksheet_size_limit'
    assert 'source_projection' not in result
    diag = result['diagnostic']
    assert diag['stage'] == 'rss_estimate'
    assert diag['source_identity'] == {'kind': 'rss', 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    assert diag['extent_proof']['namespace_rejection'] == {'namespace_uri': URI, 'local_name': 'f', 'truncated': False}
    assert not diag['complete_projection'] and not diag['financial_acceptance']
    assert CANARY not in response.text and CANARY not in caplog.text and URI not in caplog.text
    assert KEY not in response.text and len(json.dumps(diag).encode()) <= 2048
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in source[0].rglob('*') if p.is_file()}
    for path in ('/health', '/monitor', '/openapi.json'):
        public = client.get(path)
        assert URI not in public.text and CANARY not in public.text
    assert '/monitor/audit/budget-funding' not in client.get('/openapi.json').json()['paths']


@pytest.mark.parametrize('key', ['', 'wrong', 'synthetic-market-key'])
def test_unauthorized_input_cannot_read_metadata_or_touch_the_store(source, monkeypatch, key):
    def forbidden(*args, **kwargs):pytest.fail('Source or job store entered before authorization')
    import developaid_management_report_jobs as jobs
    monkeypatch.setattr(proof, 'capture', forbidden)
    monkeypatch.setattr(jobs, 'Store', forbidden)
    client = TestClient(wrapper.core.app)
    for suffix, body in [('', {'project': PROJECT, 'cut': CUT}), ('/result', {'ticket': 'c' * 32})]:
        response = call(client, suffix, key=key, **body)
        assert response.status_code == 403 and response.headers['cache-control'] == 'private, no-store'
        assert URI not in response.text and CANARY not in response.text


def test_enriched_metadata_never_raises_the_existing_envelope_bound(monkeypatch):
    value = rejection(rejected_xml('urn:synthetic:' + 'x' * 242))
    assert len(json.dumps(outer(value)).encode()) <= proof.MAX_FAILURE_DIAGNOSTIC == 2048
    monkeypatch.setattr(proof, 'MAX_FAILURE_DIAGNOSTIC', 1)
    assert outer(value) is None


def test_successful_money_projection_has_no_namespace_failure_metadata():
    clean = proof._bank(rss_bytes(), proof._day(CUT))
    assert 'namespace_rejection' not in json.dumps(clean)
    assert clean['observed_payments_at_or_before_cut']['rubles'] == 280
