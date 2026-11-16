"""Public-schema synthetic DV metadata; no observed source XML or formula evaluation."""
import copy
import io
import json
import socket
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
import pytest
import xlsxwriter

import developaid_budget_funding_source as proof

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
X14 = 'http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
XM = 'http://schemas.microsoft.com/office/excel/2006/main'
URI = '{CCE6A557-97BC-4B89-ADB6-D9C93CAAB3DF}'
CANARY = 'SYNTHETIC-OPAQUE-NOT-EVALUATED-OR-EXPORTED'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('synthetic XML must not use a network')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)


class Sheet:
    def __init__(self, raw, reader=io.BytesIO):
        self.raw, self.reader = raw, reader

    def _get_source(self):
        return self.reader(self.raw)


def extension(formulas=('formula1',), *, sqref=True):
    """Office2010 public CT_WorksheetExtension/DataValidationFormula grammar."""
    outer = ET.Element('{'+MAIN+'}extLst')
    ext = ET.SubElement(outer, '{'+MAIN+'}ext', uri=URI)
    group = ET.SubElement(ext, '{'+X14+'}dataValidations', count='1', disablePrompts='false')
    record = ET.SubElement(group, '{'+X14+'}dataValidation', type='list', allowBlank='1')
    for name in formulas:
        wrapper = ET.SubElement(record, '{'+X14+'}'+name)
        ET.SubElement(wrapper, '{'+XM+'}f').text = CANARY+'(1/0)'
    if sqref:
        ET.SubElement(record, '{'+XM+'}sqref').text = 'A1:XFD1048576'
    return outer


def worksheet(extra=None):
    root = ET.Element('{'+MAIN+'}worksheet')
    data = ET.SubElement(root, '{'+MAIN+'}sheetData')
    row = ET.SubElement(data, '{'+MAIN+'}row', r='1')
    cell = ET.SubElement(row, '{'+MAIN+'}c', r='A1')
    ET.SubElement(cell, '{'+MAIN+'}v').text = '7'
    tail = ET.SubElement(data, '{'+MAIN+'}row', r='900000')
    ET.SubElement(tail, '{'+MAIN+'}c', r='GR900000', s='0', t='n')
    if extra is not None:
        root.append(extra)
    return root


def raw(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def fail(root, *, reader=io.BytesIO):
    diagnostic = {}
    assert proof._verified_payload_extent(Sheet(raw(root), reader), _failure=diagnostic) is None
    assert diagnostic['complete_proof'] is False
    assert CANARY not in json.dumps(diagnostic)
    assert proof._checked_extent_failure(diagnostic) == diagnostic
    return diagnostic


@pytest.mark.parametrize('formulas', [('formula1',), ('formula2',), ('formula1', 'formula2'), ()])
def test_public_formula_wrappers_and_sqref_do_not_expand_payload(formulas):
    root = worksheet(extension(formulas))
    assert proof._verified_payload_extent(Sheet(raw(root))) == (1, 1)


def test_multiple_standard_validations_and_other_extensions_remain_metadata():
    root = worksheet(extension())
    group = root[-1][0][0]
    group.set('count', '2')
    group.append(copy.deepcopy(group[0]))
    other = ET.SubElement(root[-1], '{'+MAIN+'}ext', uri='{SYNTHETIC-OTHER-EXTENSION}')
    ET.SubElement(other, '{urn:synthetic:metadata}other')
    assert proof._verified_payload_extent(Sheet(raw(root))) == (1, 1)


@pytest.mark.parametrize('count', ['0', '2', '4294967295'])
def test_declared_validation_count_must_match_observed_children(count):
    root = worksheet(extension())
    root[-1][0][0].set('count', count)
    fail(root)


def test_native_sparse_read_preserves_known_cached_values_without_evaluating_metadata():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = 'Synthetic DV'
    sheet['A1'], sheet['B8'], sheet['C8'] = 7, 0, 2.5
    original = io.BytesIO()
    workbook.save(original)
    workbook.close()
    modified = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original.getvalue())) as source, zipfile.ZipFile(modified, 'w') as target:
        for member in source.infolist():
            content = source.read(member.filename)
            if member.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(content)
                root.find('{'+MAIN+'}dimension').set('ref', 'A1:XFD1048576')
                root.append(extension(('formula1', 'formula2')))
                content = raw(root)
            target.writestr(member, content)
    with proof._book(modified.getvalue()) as book:
        bounded = proof._sheet(book, 'Synthetic DV')
        assert (bounded.max_row, bounded.max_column) == (8, 3)
        assert [bounded.cell(1, 1).value, bounded.cell(8, 2).value, bounded.cell(8, 3).value] == [7, 0, 2.5]


@pytest.mark.parametrize('fault', ['wrong_root', 'before_data', 'inside_payload', 'nested_worksheet',
                                 'wrong_namespace', 'wrong_extension_uri', 'reparent_formula'])
def test_scope_namespace_and_root_ownership_cannot_be_spoofed(fault):
    root = worksheet(extension())
    if fault == 'wrong_root':
        root.tag = '{urn:synthetic:wrong}worksheet'
    elif fault == 'before_data':
        metadata = root[-1]
        root.remove(metadata)
        root.insert(0, metadata)
    elif fault == 'inside_payload':
        metadata = root[-1]
        root.remove(metadata)
        root[0][0][0].append(metadata)
    elif fault == 'nested_worksheet':
        metadata = root[-1]
        root.remove(metadata)
        ET.SubElement(root, '{'+MAIN+'}worksheet').append(metadata)
    elif fault == 'wrong_namespace':
        root[-1][0][0].tag = '{urn:synthetic:wrong}dataValidations'
    elif fault == 'wrong_extension_uri':
        root[-1][0].set('uri', '{SYNTHETIC-WRONG-GUID}')
    else:
        record = root[-1][0][0][0]
        formula = record[0][0]
        record[0].remove(formula)
        record.insert(0, formula)
    fail(root)


@pytest.mark.parametrize('target,attribute,value', [
    ('ext', 'private', CANARY), ('extLst', 'private', CANARY),
    ('container', 'count', '-1'), ('container', 'count', '4294967296'),
    ('container', 'disablePrompts', 'yes'), ('container', 'unknown', CANARY),
    ('record', 'type', 'formula'), ('record', 'allowBlank', '2'),
    ('record', 'unknown', CANARY), ('wrapper', 'type', 'formula'),
    ('formula', 'ref', 'XFD1048576'), ('sqref', 'ref', 'A1')])
def test_only_public_attribute_names_and_types_are_metadata(target, attribute, value):
    root = worksheet(extension())
    extlst, ext, container, record = root[-1], root[-1][0], root[-1][0][0], root[-1][0][0][0]
    nodes = dict(extLst=extlst, ext=ext, container=container, record=record,
                 wrapper=record[0], formula=record[0][0], sqref=record[-1])
    nodes[target].set(attribute, value)
    fail(root)


@pytest.mark.parametrize('fault', ['unknown_child', 'duplicate_wrapper', 'reverse_wrappers', 'duplicate_formula',
                                 'formula_child', 'sqref_child', 'duplicate_sqref', 'missing_sqref',
                                 'empty_formula', 'empty_container', 'extra_extension_child', 'container_text'])
def test_closed_DV_grammar_never_falls_back_to_legacy_ignore(fault):
    root = worksheet(extension(('formula1', 'formula2')))
    ext, group, record = root[-1][0], root[-1][0][0], root[-1][0][0][0]
    if fault == 'unknown_child':
        ET.SubElement(record, '{'+X14+'}formula3')
    elif fault == 'duplicate_wrapper':
        record.insert(1, copy.deepcopy(record[0]))
    elif fault == 'reverse_wrappers':
        first = record[0]
        record.remove(first)
        record.insert(1, first)
    elif fault == 'duplicate_formula':
        record[0].append(copy.deepcopy(record[0][0]))
    elif fault == 'formula_child':
        ET.SubElement(record[0][0], '{'+MAIN+'}v').text = CANARY
    elif fault == 'sqref_child':
        ET.SubElement(record[-1], '{'+MAIN+'}v').text = CANARY
    elif fault == 'duplicate_sqref':
        record.append(copy.deepcopy(record[-1]))
    elif fault == 'missing_sqref':
        record.remove(record[-1])
    elif fault == 'empty_formula':
        record[0].remove(record[0][0])
    elif fault == 'empty_container':
        group.remove(record)
    elif fault == 'extra_extension_child':
        ET.SubElement(ext, '{urn:synthetic:unknown}ignored')
    else:
        group.text = CANARY
    fail(root)


def test_formula_and_sqref_text_are_not_inspected_by_the_classifier():
    from lxml import etree
    root = etree.fromstring(raw(worksheet(extension())))
    for name in ('f', 'sqref'):
        leaf = next(root.iter('{'+XM+'}'+name))
        stack = [node.tag for node in reversed(list(leaf.iterancestors()))] + [leaf.tag]
        class OpaqueLeaf:
            def __getattr__(self, attribute):
                if attribute == 'text':
                    raise AssertionError('Metadata text was inspected')
                return getattr(leaf, attribute)
            def __len__(self):
                return len(leaf)
        assert proof._data_validation_metadata(stack, OpaqueLeaf(), True, None, None, root, end=True)
        assert not proof._data_validation_metadata(stack, leaf, True, None, None,
            etree.Element('{'+MAIN+'}worksheet'))


def test_resource_payload_depth_doctype_and_complete_EOF_CRC_guards_remain(monkeypatch):
    root = worksheet(extension())
    payload = root[0][0][0]
    payload.set('r', 'A20001')
    root[0][0].set('r', '20001')
    assert fail(root)['reason'] == 'payload_size_limit'
    root = worksheet(extension())
    with monkeypatch.context() as changed:
        changed.setattr(proof, 'MAX_CELLS', 1)
        assert proof._verified_payload_extent(Sheet(raw(root))) is None
    deep = worksheet(extension())
    node = deep
    for _ in range(65):
        node = ET.SubElement(node, '{urn:synthetic}deep')
    assert fail(deep)['reason'] == 'xml_resource_limit'
    content = raw(root)
    assert proof._verified_payload_extent(Sheet(content+b'<after/>')) is None
    declaration = b'<!DOCTYPE worksheet [<!ENTITY synthetic "'+CANARY.encode()+b'">]>'
    assert proof._verified_payload_extent(Sheet(content.replace(b'?>', b'?>'+declaration, 1))) is None
    class BadCRC(io.BytesIO):
        def read(self, size=-1):
            if self.tell() == len(self.getvalue()):
                raise zipfile.BadZipFile('synthetic CRC failure after the complete XML')
            return super().read(size)
    assert fail(root, reader=BadCRC)['reason'] == 'zip_integrity_failure'


def test_real_writer_data_bar_exception_and_its_eleven_checks_are_unchanged():
    output = io.BytesIO()
    writer = xlsxwriter.Workbook(output, {'in_memory': True})
    sheet = writer.add_worksheet('Synthetic')
    sheet.write('A1', 1)
    sheet.conditional_format('A1:A5', {'type': 'data_bar', 'data_bar_2010': True,
        'min_type': 'formula', 'min_value': '=MIN($A$1:$A$5)',
        'max_type': 'formula', 'max_value': '=MAX($A$1:$A$5)'})
    writer.close()
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        outer = ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).find('{'+MAIN+'}extLst')
    assert proof._verified_payload_extent(Sheet(raw(worksheet(outer)))) == (1, 1)
    from lxml import etree
    root = etree.fromstring(raw(worksheet(outer)))
    formula = next(root.iter('{'+XM+'}f'))
    stack = [node.tag for node in reversed(list(formula.iterancestors()))] + [formula.tag]
    assert proof._formatting_formula_checks(stack, formula, True, None, None) == ['match'] * 11
    formula.set('private', CANARY)
    assert proof._formatting_formula_checks(stack, formula, True, None, None) == ['match'] * 4 + ['no_match'] + ['not_evaluated'] * 6
    assert proof._verified_payload_extent(Sheet(etree.tostring(root))) is None
