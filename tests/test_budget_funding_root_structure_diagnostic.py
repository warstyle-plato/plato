"""Synthetic root ownership and closed metadata diagnostics, never source exports."""
import copy
import concurrent.futures
import json
import xml.etree.ElementTree as ET

import pytest

import developaid_budget_funding_source as proof
from test_budget_funding_effective_extent import FakeSheet, NS, TAG, changed_member, inflated, xml
from test_budget_funding_extent_observability import data_bar_extension, XM
from test_budget_funding_source_proof import rss_bytes


PAYLOAD = '<row r="1"><c r="A1"><v>1</v></c></row>'
CANARY = 'SYNTHETIC-NEVER-EXPORT-XML-FORMULA-ATTRIBUTE-OR-QNAME'


def nested_data(order='only', wrapper='worksheet'):
    nested = f'<extLst><ext><{wrapper}><sheetData>{PAYLOAD}</sheetData></{wrapper}></ext></extLst>'
    canonical = f'<sheetData>{PAYLOAD}</sheetData>'
    body = {'only': nested, 'before': canonical + nested, 'after': nested + canonical}[order]
    return f'<worksheet xmlns="{NS}">{body}</worksheet>'.encode()


@pytest.mark.parametrize('order', ['only', 'before', 'after'])
@pytest.mark.parametrize('wrapper', ['worksheet', 'unknown'])
def test_only_authentic_root_sheet_data_can_own_rows(order, wrapper):
    failure = {}
    assert proof._verified_payload_extent(FakeSheet(nested_data(order, wrapper)), _failure=failure) is None
    assert failure['reason'] == 'sheet_data_ambiguous'
    assert failure['complete_proof'] is False
    assert failure['sheet_data_seen'] is (order == 'before')


def test_native_bounded_reader_cannot_admit_nested_worksheet_instead_of_root_data():
    def hide_root_data(raw):
        root = ET.fromstring(raw)
        data = root.find(TAG + 'sheetData')
        root.remove(data)
        extension = ET.SubElement(ET.SubElement(root, TAG + 'extLst'), TAG + 'ext')
        ET.SubElement(extension, TAG + 'worksheet').append(data)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    raw = changed_member(inflated(rss_bytes()), 'xl/worksheets/sheet1.xml', hide_root_data)
    with pytest.raises(proof.SourceProblem, match='worksheet_size_limit') as caught:
        with proof._book(raw) as book:
            proof._sheet(book, proof.ESTIMATE)
    assert caught.value.extent_failure['reason'] == 'sheet_data_ambiguous'


def test_authentic_root_data_still_has_its_original_extent():
    assert proof._verified_payload_extent(FakeSheet(xml(PAYLOAD))) == (1, 1)


def formatting_case():
    from lxml import etree
    root = etree.fromstring(xml(PAYLOAD))
    root.append(etree.fromstring(ET.tostring(data_bar_extension())))
    formula = next(root.iter('{' + XM + '}f'))
    stack = list(reversed([p.tag for p in formula.iterancestors()])) + [formula.tag]
    return root, formula, stack


def rejected(raw):
    failure = {}
    assert proof._verified_payload_extent(FakeSheet(raw), _failure=failure) is None
    assert failure['reason'] == 'payload_namespace_unknown'
    assert proof._checked_extent_failure(failure) == failure
    assert failure['complete_proof'] is False
    assert CANARY not in json.dumps(failure)
    return failure


def outer(failure):
    exc = proof._WorksheetSizeProblem(proof.ESTIMATE, 1048576, 16384, failure)
    exc.captured_source = {'sha256': 'a' * 64, 'bytes': proof.MAX_SOURCE}
    return proof.failure_diagnostic(exc)


@pytest.mark.parametrize('key', proof._FORMATTING_FORMULA_CHECKS)
def test_shared_exception_preserves_the_first_failed_condition_and_short_circuit(key):
    _, formula, stack = formatting_case()
    data_seen, active_row, active_cell = True, None, None
    if key == 'path':
        stack.insert(1, '{urn:synthetic:' + CANARY + '}unknown')
    elif key == 'data_seen':
        data_seen = False
    elif key == 'row_inactive':
        active_row = 1
    elif key == 'cell_inactive':
        active_cell = {}
    elif key == 'attributes_empty':
        formula.set('private', CANARY)
    elif key == 'first_child':
        formula.addprevious(formula.makeelement('previous', {}))
    else:
        parents = list(formula.iterancestors())
        if key == 'cfvo_formula':
            parents[0].set('type', 'num')
        elif key == 'rule_data_bar':
            parents[2].set('type', 'cellIs')
        elif key == 'rule_guid':
            parents[2].set('id', CANARY)
        elif key == 'extension_attributes':
            parents[5].set('private', CANARY)
        elif key == 'extension_uri':
            parents[5].set('uri', CANARY)
    at = proof._FORMATTING_FORMULA_CHECKS.index(key)
    expected = ['match'] * at + ['no_match'] + ['not_evaluated'] * (10 - at)
    assert proof._formatting_formula_checks(stack, formula, data_seen, active_row, active_cell) == expected
    assert proof._formatting_formula(stack, formula, data_seen, active_row, active_cell) is False
    diagnostic = proof._namespace_structure(stack, formula, data_seen, active_row, active_cell)
    assert diagnostic['checks'] == expected and diagnostic['first_unmet'] == key
    assert proof._checked_namespace_structure(diagnostic) is True
    assert CANARY not in json.dumps(diagnostic)


def test_unknown_path_does_not_inspect_any_formula_or_ancestor_attributes():
    class NoAttributes:
        def __getattribute__(self, name):
            raise AssertionError('Unexpected attribute/ancestor inspection: ' + name)
    states = proof._formatting_formula_checks(['{urn:synthetic}other'], NoAttributes(), True, None, None)
    assert states == ['no_match'] + ['not_evaluated'] * 10


def test_supported_writer_exception_and_case_insensitive_extension_uri_keep_acceptance():
    _, formula, stack = formatting_case()
    assert proof._formatting_formula(stack, formula, True, None, None) is True
    assert proof._formatting_formula_checks(stack, formula, True, None, None) == ['match'] * 11
    extension = list(formula.iterancestors())[5]
    extension.set('uri', extension.get('uri').lower())
    assert proof._formatting_formula(stack, formula, True, None, None) is True


@pytest.mark.parametrize('kind', ['num', 'percent', 'percentile'])
def test_other_cfvo_types_remain_rejected_with_an_exact_closed_mismatch(kind):
    from lxml import etree
    root, formula, _ = formatting_case()
    formula.text = CANARY
    formula.getparent().set('type', kind)
    failure = rejected(etree.tostring(root))
    assert failure['namespace_rejection'] == {'local_name': 'f', 'namespace_uri': XM, 'truncated': False}
    value = failure['namespace_structure']
    assert value['path'] == ['worksheet', 'extLst', 'ext', 'x14:cfs', 'x14:cf',
                             'x14:rule', 'x14:bar', 'x14:cfvo', 'xm:f']
    assert value['depth'] == 9 and value['truncated'] is False and value['other'] is False
    assert value['first_unmet'] == 'cfvo_formula'
    assert value['checks'] == ['match'] * 6 + ['no_match'] + ['not_evaluated'] * 4
    assert outer(failure)['extent_proof'] == failure


@pytest.mark.parametrize('depth', [4, 12, 13, 64])
def test_only_closed_tokens_leave_unknown_ancestry_with_explicit_depth_and_truncation(depth):
    wrappers = depth - 4
    raw = xml(PAYLOAD).replace(b'</worksheet>', (
        '<extLst><ext>' + ('<' + CANARY + '>') * wrappers
        + '<xm:f xmlns:xm="' + XM + '" private="' + CANARY + '">' + CANARY + '</xm:f>'
        + ('</' + CANARY + '>') * wrappers + '</ext></extLst></worksheet>').encode())
    failure = rejected(raw)
    structure = failure['namespace_structure']
    assert structure['depth'] == depth
    assert len(structure['path']) == min(depth, 12)
    assert structure['truncated'] is (depth > 12)
    assert structure['other'] is (wrappers > 0)
    assert structure['first_unmet'] == 'path'
    assert structure['checks'] == ['no_match'] + ['not_evaluated'] * 10


@pytest.mark.parametrize('body,reason', [
    ('<extLst><row r="1"><c r="A1"><v>1</v></c></row></extLst>', 'row_reference_unknown'),
    ('<extLst><c r="A1"><v>1</v></c></extLst>', 'cell_structure_unknown'),
    ('<sheetData><row r="1"><extLst><c r="A1"><v>1</v></c></extLst></row></sheetData>', 'cell_structure_unknown'),
])
def test_native_rows_and_cells_outside_the_owned_subtree_cannot_become_payload(body, reason):
    failure = {}
    assert proof._verified_payload_extent(FakeSheet(f'<worksheet xmlns="{NS}">{body}</worksheet>'.encode()),
                                          _failure=failure) is None
    assert failure['reason'] == reason


@pytest.mark.parametrize('change', [
    {'path': []}, {'path': ['private']}, {'path': 'worksheet'}, {'depth': True}, {'depth': 65},
    {'truncated': 1}, {'truncated': True}, {'other': 1}, {'other': True},
    {'first_unmet': CANARY}, {'first_unmet': 'none'}, {'checks': []},
    {'checks': ['no_match'] * 11}, {'checks': ['match'] * 11}, {'extra': CANARY},
    {'checks': ['match'] * 6 + [True] + ['not_evaluated'] * 4},
    {'path': ['worksheet', 'extLst', 'ext', 'other']}, {'first_unmet': []},
])
def test_malformed_structure_is_discarded_without_losing_the_typed_failure(change):
    from lxml import etree
    root, formula, _ = formatting_case()
    formula.getparent().set('type', 'num')
    failure = rejected(etree.tostring(root))
    failure['namespace_structure'].update(change)
    assert proof._checked_extent_failure(failure) is None
    result = outer(failure)
    assert result['stage'] == 'rss_estimate' and 'extent_proof' not in result
    assert result['complete_projection'] is False and CANARY not in json.dumps(result)


def test_structure_requires_the_legacy_namespace_rejection_and_its_existing_reason():
    from lxml import etree
    root, formula, _ = formatting_case()
    formula.getparent().set('type', 'num')
    failure = rejected(etree.tostring(root))
    legacy = copy.deepcopy(failure)
    legacy.pop('namespace_structure')
    assert proof._checked_extent_failure(legacy) == legacy
    failure.pop('namespace_rejection')
    assert proof._checked_extent_failure(failure) is None
    legacy['reason'] = 'xml_parse_failure'
    assert proof._checked_extent_failure(legacy) is None


def test_token_path_and_observed_namespace_cannot_disagree():
    from lxml import etree
    root, formula, _ = formatting_case()
    formula.getparent().set('type', 'num')
    failure = rejected(etree.tostring(root))
    failure['namespace_rejection']['namespace_uri'] = 'urn:synthetic:other'
    assert proof._checked_extent_failure(failure) is None


def test_all_matching_exception_is_a_valid_helper_result_but_never_a_rejection_envelope():
    from lxml import etree
    root, formula, stack = formatting_case()
    all_match = proof._namespace_structure(stack, formula, True, None, None)
    assert all_match['first_unmet'] == 'none' and all_match['checks'] == ['match'] * 11
    assert proof._checked_namespace_structure(all_match) is True
    assert proof._formatting_formula(stack, formula, True, None, None) is True
    formula.getparent().set('type', 'num')
    failure = rejected(etree.tostring(root))
    failure['namespace_structure'] = all_match
    assert proof._checked_extent_failure(failure) is None
    diagnostic = outer(failure)
    assert 'extent_proof' not in diagnostic
    assert diagnostic['complete_projection'] is False and diagnostic['financial_acceptance'] is False


def test_whole_diagnostic_keeps_the_2048_byte_bound_with_largest_URI_and_all_counter_widths():
    raw = xml(PAYLOAD).replace(b'</worksheet>', (
        '<extLst><ext><other:f xmlns:other="' + 'x' * 256 + '"/></ext></extLst></worksheet>').encode())
    failure = rejected(raw)
    failure.update(candidate_payload_max_row=1048576, candidate_payload_max_column=16384,
                   candidate_payload_rectangle=1048576 * 16384, cell_elements_seen=proof.MAX_CELLS + 1,
                   xml_nodes_seen=proof.MAX_CELLS * 8 + 1, xml_bytes_observed=proof.ahr.MAX_EXPANDED + 65536)
    failure['namespace_structure'].update(path=['worksheet'] * 12, depth=64, truncated=True, other=True)
    result = outer(failure)
    assert result['extent_proof'] == failure
    assert len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) <= proof.MAX_FAILURE_DIAGNOSTIC == 2048


def test_structure_is_per_call_and_does_not_survive_a_different_refusal_or_success():
    raw = xml(PAYLOAD).replace(b'</worksheet>', f'<extLst><xm:f xmlns:xm="{XM}"/></extLst></worksheet>'.encode())
    failure = rejected(raw)
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="20001"><c r="A20001"><v>1</v></c></row>')),
                                          _failure=failure) is None
    assert failure['reason'] == 'payload_size_limit' and 'namespace_structure' not in failure
    assert proof._verified_payload_extent(FakeSheet(raw), _failure=failure) is None
    assert 'namespace_structure' in failure
    assert proof._verified_payload_extent(FakeSheet(xml(PAYLOAD)), _failure=failure) == (1, 1)
    assert 'namespace_structure' not in failure and 'namespace_rejection' not in failure
    def one(depth):
        body = '<x>' * depth + f'<xm:f xmlns:xm="{XM}"/>' + '</x>' * depth
        return rejected(xml(PAYLOAD).replace(b'</worksheet>', ('<extLst>' + body + '</extLst></worksheet>').encode()))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(8)))
    assert [item['namespace_structure']['depth'] for item in results] == list(range(3, 11))


@pytest.mark.parametrize('local,reason', [('sheetData', 'sheet_data_ambiguous'),
    ('row', 'row_reference_unknown'), ('c', 'cell_structure_unknown')])
def test_qname_lookalike_parent_does_not_replace_the_actual_owner(monkeypatch, local, reason):
    from lxml import etree
    root = etree.fromstring(f'<worksheet xmlns="{NS}"><sheetData>{PAYLOAD}</sheetData></worksheet>'.encode())
    target = next(root.iter(TAG + local))
    impostor = etree.Element(target.getparent().tag)
    class Element:
        def __getattr__(self, name):
            return getattr(target, name)
        def getparent(self):
            return impostor
    def starts(element):
        yield 'start', Element() if element is target else element
        for child in element:
            yield from starts(child)
    monkeypatch.setattr(etree, 'iterparse', lambda *args, **kwargs: starts(root))
    failure = {}
    assert proof._verified_payload_extent(FakeSheet(b''), _failure=failure) is None
    assert failure['reason'] == reason
