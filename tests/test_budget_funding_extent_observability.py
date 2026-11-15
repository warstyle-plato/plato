"""Closed failure reasons and one exact Excel2010 metadata compatibility path."""
import builtins
import copy
import io
import json
import zipfile
import xml.etree.ElementTree as ET

import pytest
import xlsxwriter

import developaid_budget_funding_source as proof
from test_budget_funding_source_proof import rss_bytes, fm_bytes, CUT
from test_budget_funding_effective_extent import (FakeSheet, xml, inflated,
    changed_member, with_long_xml_tail, corrupted_sheet_crc, NS, TAG)

X14='http://schemas.microsoft.com/office/spreadsheetml/2009/9/main'
XM='http://schemas.microsoft.com/office/excel/2006/main'
PRIVATE='PRIVATE-FORMULA-NAME-PATH-SECRET-CANARY'


def data_bar_extension():
    """Use a real ordinary writer, not a copy of the production whitelist."""
    out=io.BytesIO();book=xlsxwriter.Workbook(out,{'in_memory':True})
    sheet=book.add_worksheet('Synthetic');sheet.write('A1',1)
    sheet.conditional_format('A1:A5',{'type':'data_bar','data_bar_2010':True,
        'min_type':'formula','min_value':'=MIN($A$1:$A$5)',
        'max_type':'formula','max_value':'=MAX($A$1:$A$5)'})
    book.close()
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as archive:
        return ET.fromstring(archive.read('xl/worksheets/sheet1.xml')).find(TAG+'extLst')


def decorated(raw, *, edit=None, member='xl/worksheets/sheet1.xml', far=False):
    extension=data_bar_extension()
    if edit:edit(extension)
    def change(data):
        root=ET.fromstring(data);root.append(extension)
        return ET.tostring(root,encoding='utf-8',xml_declaration=True)
    raw=changed_member(raw,member,change)
    return inflated(raw,member=member,payload=f'<row xmlns="{NS}" r="900000"><c r="GR900000" s="0" t="n"/></row>') if far else raw


def reason(sheet):
    value={};assert proof._verified_payload_extent(sheet,_failure=value) is None
    checked=proof._checked_extent_failure(value)
    assert checked==value and len(json.dumps(value).encode())<1024
    assert PRIVATE not in json.dumps(value) and value['complete_proof'] is False
    return value


def failed_diagnostic(sheet):
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:
        proof._sheet(type('Book',(),{'sheetnames':[proof.ESTIMATE], '__getitem__':lambda self,name:sheet})(),proof.ESTIMATE)
    caught.value.captured_source={'sha256':'a'*64,'bytes':1234,'path':PRIVATE}
    got=proof.failure_diagnostic(caught.value)
    assert len(json.dumps(got).encode())<=2048 and PRIVATE not in json.dumps(got)
    assert got['dimension_basis']=='worksheet_metadata_not_verified_content_extents'
    assert not got['financial_acceptance'] and got['identity_captured_before_failure_not_pair_confirmation']
    return got


@pytest.mark.parametrize('member',['xl/worksheets/sheet1.xml','xl/worksheets/sheet2.xml'])
def test_real_excel2010_data_bar_compact_farstyle_has_identical_bank_money_units_and_anchors(member):
    clean=rss_bytes();compact=decorated(clean,member=member);styled=decorated(clean,member=member,far=True)
    expected=proof._bank(clean,proof._day(CUT))
    assert proof._bank(compact,proof._day(CUT))==expected==proof._bank(styled,proof._day(CUT))
    assert 'extent_proof' not in json.dumps(expected)


def test_same_metadata_recovery_preserves_finance_composition_and_unit_evidence():
    clean=fm_bytes()
    assert proof._finance(decorated(clean,far=True))==proof._finance(clean)


def test_new_path_is_causal_against_the_original_blanket_foreign_formula_refusal(monkeypatch):
    raw=decorated(rss_bytes(),far=True)
    assert proof._bank(raw,proof._day(CUT))
    monkeypatch.setattr(proof,'_formatting_formula',lambda *args:False)
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:proof._bank(raw,proof._day(CUT))
    # The forced Boolean refusal contradicts the real predicate's all-match
    # observation. Keep the typed refusal, without exporting an impossible proof.
    assert caught.value.extent_failure=={}
    caught.value.captured_source={'sha256':'a'*64,'bytes':len(raw)}
    diagnostic=proof.failure_diagnostic(caught.value)
    assert 'extent_proof' not in diagnostic
    assert not diagnostic['complete_projection'] and not diagnostic['financial_acceptance']


@pytest.mark.parametrize('mutate',[
    lambda root:root.find(TAG+'ext').set('uri','{00000000-0000-0000-0000-000000000000}'),
    lambda root:next(root.iter('{'+X14+'}cfRule')).set('type','cellIs'),
    lambda root:next(root.iter('{'+X14+'}cfRule')).set('id',PRIVATE),
    lambda root:next(root.iter('{'+X14+'}cfvo')).set('type','num'),
    lambda root:next(root.iter('{'+XM+'}f')).set('ref','A1:A900000'),
    lambda root:ET.SubElement(next(root.iter('{'+XM+'}f')),'{'+NS+'}v').__setattr__('text',PRIVATE),
    lambda root:next(root.iter('{'+X14+'}cfvo')).append(copy.deepcopy(next(root.iter('{'+XM+'}f')))),
    lambda root:next(root.iter('{'+X14+'}cfvo')).append(ET.Element('{urn:unknown}child')),
    lambda root:next(root.iter('{'+XM+'}f')).__setattr__('tag','{urn:unknown}f'),
])
def test_only_exact_supported_metadata_path_is_accepted(mutate):
    raw=decorated(rss_bytes(),edit=mutate,far=True)
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:proof._bank(raw,proof._day(CUT))
    value=caught.value.extent_failure
    assert value['reason'] in {'payload_namespace_unknown','metadata_formula_structure'}
    assert value['context']=='worksheet_metadata' and PRIVATE not in json.dumps(value)


def test_nested_exact_metadata_subtree_inside_a_cell_is_not_a_bypass():
    extension=ET.tostring(data_bar_extension(),encoding='unicode')
    data=xml(f'<row r="1"><c r="A1"><v>1</v></c><c r="B1">{extension}</c></row>')
    assert reason(FakeSheet(data))['reason']=='payload_namespace_unknown'


def test_unknown_metadata_wrapper_cannot_spoof_the_exact_qname_path():
    def wrap(extension):
        parent=next(extension.iter('{'+X14+'}dataBar'));threshold=next(extension.iter('{'+X14+'}cfvo'))
        parent.remove(threshold);ET.SubElement(parent,'{'+X14+'}unknown').append(threshold)
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:
        proof._bank(decorated(rss_bytes(),edit=wrap,far=True),proof._day(CUT))
    assert caught.value.extent_failure['reason']=='payload_namespace_unknown'


@pytest.mark.parametrize('body',['<v>0</v>','<f/>','<is><t/></is>'])
def test_supported_metadata_never_hides_real_far_payload(body):
    raw=inflated(decorated(rss_bytes()),payload=f'<row xmlns="{NS}" r="20001"><c r="A20001">{body}</c></row>')
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:proof._bank(raw,proof._day(CUT))
    assert caught.value.extent_failure['reason']=='payload_size_limit'
    assert caught.value.extent_failure['context']=='cell'


@pytest.mark.parametrize('payload,code,context',[
    ('<row r="20001"><c r="A20001"><v>0</v></c></row>','payload_size_limit','cell'),
    ('<row r="20001"><c r="A20001"><f/></c></row>','payload_size_limit','cell'),
    ('<row r="20001"><c r="A20001"><is><t/></is></c></row>','payload_size_limit','cell'),
    (f'<row r="1"><c r="A1"><f xmlns="{XM}"/></c></row>','payload_namespace_unknown','cell'),
    ('<row><c r="A1"><v>1</v></c></row>','row_reference_unknown','sheet_data'),
    ('<row r="1"><c r="B1"><v>1</v></c><c r="A1"><v>2</v></c></row>','cell_reference_order','cell'),
    ('<row r="1"><c r="A1"><f ref="B1:A1"/></c></row>','formula_area_order','cell'),
    ('<row r="1"><c r="A1"><f ref="A1 B1"/></c></row>','coordinate_invalid','cell'),
])
def test_rejection_reasons_and_partial_contexts_do_not_change_payload_guards(payload,code,context):
    value=reason(FakeSheet(xml(payload)))
    assert value['reason']==code and value['context']==context


def test_dtd_limit_and_crc_guards_remain_required_after_the_metadata_exception(monkeypatch):
    extension=ET.tostring(data_bar_extension(),encoding='unicode')
    raw=xml('<row r="1"><c r="A1"><v>1</v></c></row>',before='<!DOCTYPE worksheet [<!ENTITY private "'+PRIVATE+'">]>')
    assert reason(FakeSheet(raw))['reason']=='worksheet_namespace_or_doctype'
    styled=decorated(rss_bytes(),far=True)
    padded=with_long_xml_tail(styled)
    assert proof._bank(padded,proof._day(CUT))==proof._bank(rss_bytes(),proof._day(CUT))
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit') as caught:proof._bank(corrupted_sheet_crc(padded),proof._day(CUT))
    assert caught.value.extent_failure['reason']=='zip_integrity_failure'
    monkeypatch.setattr(proof.ahr,'MAX_EXPANDED',50)
    assert reason(FakeSheet(xml('<row r="1"><c r="A1"><v>1</v></c></row>')))['reason']=='extent_read_limit'


@pytest.mark.parametrize('tail',['<broken','<worksheet/>','unexpected'])
def test_trailing_xml_failures_are_coded_without_text(tail):
    raw=xml('<row r="1"><c r="A1"><v>1</v></c></row>',after=tail+PRIVATE)
    assert reason(FakeSheet(raw))['reason']=='xml_parse_failure'


def test_late_trailing_failure_does_not_reuse_a_closed_cell_context():
    raw=xml('<row r="1"><c r="A1"><v>1</v></c></row>',after=' '*250000+'<broken')
    value=reason(FakeSheet(raw))
    assert value['reason']=='xml_parse_failure' and value['context']=='root'


def test_no_second_proof_scan_and_no_native_cell_iteration_before_a_bounded_view():
    class Single(FakeSheet):
        calls=0
        def _get_source(self):self.calls+=1;assert self.calls==1;return super()._get_source()
    sheet=Single(xml('<row r="1"><c r="A1"><v>1</v></c></row>'))
    book=type('Book',(),{'sheetnames':[proof.ESTIMATE],'__getitem__':lambda self,name:sheet})()
    view=proof._sheet(book,proof.ESTIMATE)
    assert isinstance(view,proof._BoundedWorksheetView) and sheet.calls==1
    assert (sheet.max_row,sheet.max_column)==(900000,200)


@pytest.mark.parametrize('kind',['cells','nodes'])
def test_existing_xml_resource_limits_have_bounded_counters(monkeypatch,kind):
    monkeypatch.setattr(proof,'MAX_CELLS',1)
    first='<row r="1"><c r="A1"><v>1</v></c>'
    data=first+'<c r="B1"/></row>' if kind=='cells' else first+'</row>'+('<extension/>'*10)
    value=reason(FakeSheet(xml(data)))
    assert value['reason']==('xml_cell_resource_limit' if kind=='cells' else 'xml_resource_limit')
    assert value['cell_elements_seen']<=2 and value['xml_nodes_seen']<=9


@pytest.mark.parametrize('exception,expected',[(OSError(PRIVATE),'source_stream_failure'),(RuntimeError(PRIVATE),'internal_proof_failure')])
def test_foreign_exception_material_cannot_enter_the_diagnostic(exception,expected):
    class Broken(FakeSheet):
        def _get_source(self):raise exception
    value=failed_diagnostic(Broken(b''))['extent_proof']
    assert value['reason']==expected and value['xml_bytes_observed'] is None


def test_parser_import_failure_is_unknown_io_not_an_empty_success(monkeypatch):
    original=builtins.__import__
    def missing(name,*args,**kwargs):
        if name=='lxml':raise ImportError(PRIVATE)
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',missing)
    value=reason(FakeSheet(b''))
    assert value['reason']=='parser_unavailable' and value['xml_bytes_observed'] is None
    assert value['candidate_payload_max_row'] is None and value['candidate_payload_max_column'] is None
    assert value['candidate_payload_rectangle'] is None


@pytest.mark.parametrize('key,value',[
    ('reason',PRIVATE),('reason',[]),('context',PRIVATE),('context',{}),
    ('cell_elements_seen',True),('xml_nodes_seen',10**100),('xml_bytes_observed',float('nan')),
    ('candidate_payload_rectangle',1),('extra',PRIVATE)])
def test_malformed_observability_is_discarded_without_losing_the_old_typed_failure(key,value):
    sheet=FakeSheet(xml('<row r="20001"><c r="A20001"><v>1</v></c></row>'))
    diagnostic=reason(sheet);diagnostic[key]=value
    exc=proof._WorksheetSizeProblem(proof.ESTIMATE,900000,200,diagnostic)
    exc.captured_source={'sha256':'a'*64,'bytes':1234,'path':PRIVATE}
    got=proof.failure_diagnostic(exc)
    assert got is not None and 'extent_proof' not in got and PRIVATE not in json.dumps(got)


def test_enriched_failure_is_bounded_and_still_not_a_coherent_source_projection():
    got=failed_diagnostic(FakeSheet(xml('<row r="20001"><c r="A20001"><v>1</v></c></row>')))
    assert got['extent_proof']['reason']=='payload_size_limit'
    assert got['extent_proof']['candidate_payload_max_row']==20001
    assert got['extent_proof']['candidate_payload_rectangle']==20001
    assert not got['extent_proof']['complete_proof'] and not got['complete_projection']
