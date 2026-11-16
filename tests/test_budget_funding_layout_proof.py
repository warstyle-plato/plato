"""Synthetic layout-only observations; source values never enter the DTO."""
import copy
import hashlib
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
import pytest
import xlsxwriter

import developaid_budget_funding_layout_proof as layout
import developaid_budget_funding_source as source
from test_budget_funding_data_validation_metadata import extension, worksheet, raw, Sheet, MAIN, X14, XM

RUNTIME = {'commit': 'a' * 40, 'version': '0.0.1'}
CANARY = 'SYNTHETIC-PRIVATE-TEXT-MUST-NOT-LEAVE-SOURCE'


def workbook(extra=None, *, tail=b'', corrupt=False):
    book = openpyxl.Workbook()
    book.active.title = source.ESTIMATE
    book.active['A1'] = 7
    data = io.BytesIO()
    book.save(data)
    book.close()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as old, zipfile.ZipFile(out, 'w') as new:
        for member in old.infolist():
            content = old.read(member.filename)
            if member.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(content)
                if extra is not None:
                    root.append(extra)
                content = raw(root) + tail
            new.writestr(member, content)
    result = bytearray(out.getvalue())
    if corrupt:
        # Change only the central-directory CRC: complete ZIP member reads fail.
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            member = archive.getinfo('xl/worksheets/sheet1.xml')
        at = 0
        while True:
            at = result.index(b'PK\x01\x02', at)
            name_len = int.from_bytes(result[at+28:at+30], 'little')
            if result[at+46:at+46+name_len] == member.filename.encode():
                result[at+16:at+20] = (member.CRC ^ 1).to_bytes(4, 'little')
                break
            at += 4
    return bytes(result)


def cf_extension():
    data = io.BytesIO()
    book = xlsxwriter.Workbook(data, {'in_memory': True})
    sheet = book.add_worksheet('Synthetic')
    sheet.write('A1', 1)
    sheet.conditional_format('A1:A5', {'type': 'data_bar', 'data_bar_2010': True,
        'min_type': 'formula', 'min_value': '=MIN(A1:A5)',
        'max_type': 'formula', 'max_value': '=MAX(A1:A5)'})
    book.close()
    with zipfile.ZipFile(io.BytesIO(data.getvalue())) as archive:
        return ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).find('{'+MAIN+'}extLst')


@pytest.fixture
def pair(monkeypatch):
    state = {'raw': workbook(extension(('formula1', 'formula2'))), 'calls': [], 'fm_after': None, 'rss_after': None}
    finance = {'sha256': hashlib.sha256(b'synthetic finance').hexdigest(), 'bytes': 17,
        'metadata_sha256': None, 'metadata_bound_to_bytes': False,
        'namespace_sha256': 'd'*64, 'aliases_sha256': None}
    def finance_copy(project):
        state['calls'].append('fm')
        if state['calls'].count('fm') > 1 and state['fm_after']:
            raise state['fm_after']
        return b'synthetic finance', {'opaque': CANARY}, copy.deepcopy(finance)
    def rss_copy(project, cut):
        state['calls'].append('rss')
        if state['calls'].count('rss') > 1 and state['rss_after']:
            raise state['rss_after']
        identity = {'sha256': hashlib.sha256(state['raw']).hexdigest(), 'bytes': len(state['raw']),
            'metadata_sha256': 'e'*64, 'metadata_bound_to_bytes': True, 'version_date': '2026-11-01',
            'namespace_sha256': 'd'*64, 'aliases_sha256': None}
        return state['raw'], {'opaque': CANARY}, identity
    monkeypatch.setattr(layout.ahr, '_copy', finance_copy)
    monkeypatch.setattr(source, '_rss_copy', rss_copy)
    for name in ('capture', '_finance', '_bank', '_header', '_role', '_sheet'):
        monkeypatch.setattr(source, name, lambda *a, **k: pytest.fail('financial/cell reader entered'))
    def expected():
        return {'runtime_commit': RUNTIME['commit'], 'producer_sha256': layout.producer_hashes(),
            'finance_sha256': finance['sha256'], 'rss_sha256': hashlib.sha256(state['raw']).hexdigest(),
            'namespace_sha256': 'd'*64, 'aliases_sha256': None}
    state['expected'] = expected
    state['capture'] = lambda: layout.capture_layout_proof('Synthetic', '2026-11-13', expected(), runtime=RUNTIME)
    return state


def assert_unknown(value):
    assert value['outcome'] != 'verified'
    assert value['safe_extent'] == {'state': 'unknown', 'max_row': None, 'max_column': None,
        'rectangle_cells': None, 'basis': 'no_accepted_complete_extent'}
    assert value['remaining_failure'] is not None


def test_DV_proof_is_complete_but_does_not_claim_CF_predicates_or_export_text(pair, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    for name in ('iter_rows', 'cell'):
        monkeypatch.setattr(ReadOnlyWorksheet, name, lambda *a, **k: pytest.fail('cell access'))
    value = pair['capture']()
    assert value['outcome'] == 'verified'
    assert value['safe_extent']['rectangle_cells'] == 1
    assert value['current_pair']['state'] == 'stable_expected'
    assert pair['calls'] == ['fm', 'rss', 'fm', 'rss']
    classification = value['classification']
    assert (classification['cf_state'], classification['dv_state']) == ('not_applicable', 'accepted')
    counts = classification['counts']
    assert counts['dv_formula1_starts'] == counts['dv_formula2_starts'] == counts['dv_sqref_starts'] == 1
    assert counts['foreign_formula_starts'] == counts['cf_predicate_evaluations'] == 2
    assert classification['cf11']['path'] == {'match': 0, 'no_match': 2, 'not_evaluated': 0}
    assert classification['cf11']['extension_uri']['not_evaluated'] == 2
    assert CANARY not in json.dumps(value) and 'SYNTHETIC-OPAQUE' not in json.dumps(value)
    assert len(json.dumps(value).encode()) < layout.MAX_OUTPUT


@pytest.mark.parametrize('kind', ['CF', 'both', 'absent'])
def test_CF_DV_and_absence_are_separate_complete_classifications(pair, kind):
    extra = cf_extension() if kind != 'absent' else None
    if kind == 'both':
        extra.append(extension()[0])
    pair['raw'] = workbook(extra)
    value = pair['capture']()
    assert value['outcome'] == 'verified'
    classification = value['classification']
    assert classification['cf_state'] == ('absent' if kind == 'absent' else 'accepted')
    assert classification['dv_state'] == ('accepted' if kind == 'both' else 'absent')
    if kind != 'absent':
        assert classification['counts']['cf_start_predicate_matches'] == 2
        assert all(states['match'] == 2 for states in classification['cf11'].values())


@pytest.mark.parametrize('fault', ['attributes', 'nested', 'count', 'order'])
def test_known_invalid_DV_never_falls_through_and_keeps_extent_unknown(pair, fault):
    extra = extension(('formula1', 'formula2'))
    group, record = extra[0][0], extra[0][0][0]
    if fault == 'attributes':
        group.set('unknown', CANARY)
    elif fault == 'nested':
        ET.SubElement(record[0][0], '{'+MAIN+'}v').text = CANARY
    elif fault == 'count':
        group.set('count', '2')
    else:
        record.insert(0, record[-1])
    pair['raw'] = workbook(extra)
    value = pair['capture']()
    assert_unknown(value)
    assert value['remaining_failure']['extent_reason'] == 'metadata_formula_structure'
    assert value['classification']['dv_state'] == 'rejected'
    assert pair['calls'] == ['fm', 'rss', 'fm', 'rss']
    if fault == 'attributes':
        assert value['classification']['counts']['cf_predicate_evaluations'] == 0
        assert value['classification']['cf_state'] == 'unknown'


@pytest.mark.parametrize('parse', ['success', 'rejected', 'exception', 'close_exception'])
@pytest.mark.parametrize('post', ['changed', 'fm_error', 'rss_error', 'both_error'])
def test_both_postflight_helpers_run_after_every_parsed_outcome(pair, monkeypatch, parse, post):
    original = source._verified_payload_extent
    def scan(*args, **kwargs):
        if parse == 'exception':
            raise RuntimeError(CANARY)
        result = original(*args, **kwargs)
        if post == 'changed':
            pair['raw'] += b'changed after copied proof'
        return result
    monkeypatch.setattr(source, '_verified_payload_extent', scan)
    if parse == 'rejected':
        extra = extension();extra[0][0].set('count', '2');pair['raw'] = workbook(extra)
    if parse == 'close_exception':
        from contextlib import contextmanager
        original_book = source._book
        @contextmanager
        def closes_badly(raw):
            with original_book(raw) as book:
                yield book
            raise RuntimeError(CANARY)
        monkeypatch.setattr(source, '_book', closes_badly)
    if post in ('fm_error', 'both_error'):
        pair['fm_after'] = OSError(CANARY)
    if post in ('rss_error', 'both_error'):
        pair['rss_after'] = source.SourceProblem('source_changed')
    value = pair['capture']()
    assert pair['calls'] == ['fm', 'rss', 'fm', 'rss']
    assert_unknown(value)
    assert CANARY not in json.dumps(value)
    if post == 'changed' and parse == 'exception':
        assert value['remaining_failure']['stage'] == 'rss_estimate'
    elif post in ('rss_error', 'both_error', 'changed'):
        assert value['current_pair']['state'] == 'changed'
        assert value['outcome'] == 'rejected'
    else:
        assert value['current_pair']['state'] == 'unknown'
        assert value['outcome'] == 'source_unavailable'


def test_full_ZIP_EOF_CRC_is_required_after_valid_DV(pair):
    pair['raw'] = workbook(extension(), tail=b' ' * 131072, corrupt=True)
    value = pair['capture']()
    assert_unknown(value)
    assert value['classification']['scan'] != 'complete'
    assert value['remaining_failure']['extent_reason'] == 'zip_integrity_failure'
    assert pair['calls'] == ['fm', 'rss', 'fm', 'rss']


@pytest.mark.parametrize('fault', ['runtime', 'producer', 'source'])
def test_wrong_bindings_never_enter_parser(pair, monkeypatch, fault):
    expected = pair['expected']()
    if fault == 'runtime':
        expected['runtime_commit'] = 'f'*40
    elif fault == 'producer':
        expected['producer_sha256']['budget_source'] = 'f'*64
    else:
        expected['rss_sha256'] = 'f'*64
    monkeypatch.setattr(source, '_book', lambda *a, **k: pytest.fail('parser before binding'))
    if fault != 'source':
        with pytest.raises(layout.LayoutProblem):
            layout.capture_layout_proof('Synthetic', '2026-11-13', expected, runtime=RUNTIME)
        assert pair['calls'] == []
    else:
        value = layout.capture_layout_proof('Synthetic', '2026-11-13', expected, runtime=RUNTIME)
        assert_unknown(value)
        assert value['outcome'] == 'binding_mismatch'


@pytest.mark.parametrize('fault', ['extra', 'bool_counter', 'extent_product', 'CF_claim', 'prefix_acceptance',
                                 'unknown_dimensions', 'schema_bool', 'flag_int', 'changed_verified',
                                 'missing_identity', 'stable_false', 'lazy_states', 'unknown_pair_verdict'])
def test_closed_DTO_rejects_impossible_claims_and_values(pair, fault):
    value = pair['capture']()
    if fault == 'extra':value['formula'] = CANARY
    elif fault == 'bool_counter':value['classification']['counts']['dv_rules_seen'] = True
    elif fault == 'extent_product':value['safe_extent']['rectangle_cells'] = 2
    elif fault == 'CF_claim':value['classification']['cf_state'] = 'accepted'
    elif fault == 'prefix_acceptance':value['classification']['scan'] = 'observed_prefix'
    elif fault == 'unknown_dimensions':value['safe_extent']['state'] = 'unknown'
    elif fault == 'schema_bool':value['schema'] = True
    elif fault == 'flag_int':value['financial_acceptance'] = 0
    elif fault == 'missing_identity':value['current_pair']['finance']['sha256'] = None
    elif fault == 'stable_false':value['current_pair']['before_after_equal'] = False
    elif fault == 'lazy_states':value['classification']['cf11']['data_seen'] = {'match':2,'no_match':0,'not_evaluated':0}
    elif fault == 'unknown_pair_verdict':value['current_pair']['state'] = 'unknown'
    else:value['current_pair']['state'] = 'changed'
    with pytest.raises(layout.LayoutProblem):layout.validate_projection(value)


def test_output_caps_and_request_closure_do_not_export_arbitrary_fields(pair, monkeypatch):
    expected = pair['expected']()
    request = {'key': 'SYNTHETIC', 'session': '', 'purpose': layout.PURPOSE, 'scope': layout.SCOPE,
        'ticket': '1'*32, 'project': 'Synthetic', 'cut': '2026-11-13', 'expected': expected}
    assert layout.parse_request(json.dumps(request).encode(), start=True) == request
    for bad in ({**request, 'filename': CANARY}, {**request, 'expected': {**expected, 'rss_metadata_sha256': None}}):
        with pytest.raises(layout.LayoutProblem):layout.parse_request(json.dumps(bad).encode(), start=True)
    with pytest.raises(layout.LayoutProblem):layout.parse_request(b'{"key":"x","key":"y"}', start=True)
    with pytest.raises(layout.LayoutProblem):layout.parse_request(b' '*(layout.MAX_REQUEST+1), start=True)
    monkeypatch.setattr(layout, 'MAX_OUTPUT', 10)
    with pytest.raises(layout.LayoutProblem):pair['capture']()


def test_observation_is_one_native_traversal_and_old_callers_keep_diagnostics(monkeypatch):
    root = worksheet(extension())
    class Single(Sheet):
        calls = 0
        def _get_source(self):
            self.calls += 1
            assert self.calls == 1
            return super()._get_source()
    original = source._formatting_formula_checks
    calls = []
    def checks(*args):
        calls.append(True)
        return original(*args)
    monkeypatch.setattr(source, '_formatting_formula_checks', checks)
    report = {}
    assert source._verified_payload_extent(Single(raw(root)), _observation=report) == (1, 1)
    assert len(calls) == report['counts']['cf_predicate_evaluations'] == 1
    root[-1][0][0].set('count', '2')
    old_failure, report_failure = {}, {}
    assert source._verified_payload_extent(Sheet(raw(root)), _failure=old_failure) is None
    assert source._verified_payload_extent(Sheet(raw(root)), _failure=report_failure, _observation={}) is None
    assert old_failure == report_failure


@pytest.mark.parametrize('finance_metadata', [False, True])
def test_native_copy_pair_keeps_source_bytes_metadata_and_current_selection(tmp_path, monkeypatch, finance_metadata):
    import developaid_monitor as monitor
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    project = 'Synthetic layout'
    slug = monitor._slug(project)
    folder = monitor._SNAPSHOT_DIR/slug
    baseline, estimates = folder/'baseline', folder/'estimate'
    baseline.mkdir(parents=True);estimates.mkdir()
    finance = b'Synthetic identity-only FM, never parsed as a workbook'
    (baseline/'finance.xlsx').write_bytes(finance)
    if finance_metadata:
        (baseline/'finance_meta.json').write_text(json.dumps({'source_sha256':hashlib.sha256(finance).hexdigest()}))
    rss = workbook(extension())
    (estimates/'2026-11-01.xlsx').write_bytes(rss)
    (estimates/'2026-11-01.json').write_text(json.dumps({'taken_at':'2026-11-01',
        'bytes':len(rss),'source_sha256':hashlib.sha256(rss).hexdigest(),'opaque':CANARY}))
    files = [path for path in folder.rglob('*') if path.is_file()]
    before = {path:(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns) for path in files}
    expected = {'runtime_commit':RUNTIME['commit'],'producer_sha256':layout.producer_hashes(),
        'finance_sha256':hashlib.sha256(finance).hexdigest(),'rss_sha256':hashlib.sha256(rss).hexdigest(),
        'namespace_sha256':hashlib.sha256(slug.encode()).hexdigest(),'aliases_sha256':None}
    value = layout.capture_layout_proof(project,'2026-11-13',expected,runtime=RUNTIME)
    assert value['outcome'] == 'verified'
    assert value['current_pair']['finance']['metadata_bound_to_bytes'] is finance_metadata
    assert (value['current_pair']['finance']['metadata_sha256'] is not None) is finance_metadata
    assert value['current_pair']['rss']['metadata_sha256'] is not None
    assert CANARY not in json.dumps(value)
    assert before == {path:(path.read_bytes(),path.stat().st_ino,path.stat().st_mtime_ns) for path in files}
    assert set(path for path in folder.rglob('*') if path.is_file()) - set(files) == {baseline/'.schedule_versions.lock'}
