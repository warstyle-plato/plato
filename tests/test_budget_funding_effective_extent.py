"""Synthetic worksheet extents: formatting never hides real out-of-bounds payload."""
import io
import zipfile
import xml.etree.ElementTree as ET

import pytest
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

import developaid_budget_funding_source as proof
from test_budget_funding_source_proof import (source, capture, fm_bytes, rss_bytes,
    replace_rss, PROJECT, CUT)  # noqa: F401

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
TAG = '{'+NS+'}'


def changed_member(raw, member, edit):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as old, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as new:
        for item in old.infolist():
            data = old.read(item.filename)
            if item.filename == member:
                data = edit(data)
            new.writestr(item, data)
    return out.getvalue()


def inflated(raw, *, member='xl/worksheets/sheet1.xml', row=900000, column='GR', payload=None):
    def edit(data):
        root = ET.fromstring(data)
        root.find(TAG+'dimension').set('ref', f'A1:{column}{row}')
        if payload is not None:
            root.find(TAG+'sheetData').append(ET.fromstring(payload))
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)
    return changed_member(raw, member, edit)


@pytest.mark.parametrize('member', ['xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml'])
@pytest.mark.parametrize('row,column', [(900000,'GR'),(30,'BEB'),(5000,'AHP')])
def test_oversized_declared_dimension_or_style_only_cell_has_same_bank_values(member,row,column):
    clean = rss_bytes()
    styled = inflated(clean, member=member, row=row, column=column,
        payload=f'<row xmlns="{NS}" r="{row}"><c r="{column}{row}" s="0" t="n"/></row>')
    assert proof._bank(styled, proof._day(CUT)) == proof._bank(clean, proof._day(CUT))


def test_metadata_only_dimension_does_not_require_a_far_cell():
    clean = rss_bytes()
    assert proof._bank(inflated(clean), proof._day(CUT)) == proof._bank(clean, proof._day(CUT))


def test_fm_formatting_recovery_preserves_money_units_and_primary_anchors():
    clean = fm_bytes()
    styled = inflated(clean, payload=f'<row xmlns="{NS}" r="900000"><c r="GR900000" s="0"/></row>')
    assert proof._finance(styled) == proof._finance(clean)


def test_recovered_view_does_not_call_native_iteration_before_proof_or_change_original_dims(monkeypatch):
    raw = inflated(rss_bytes())
    original = ReadOnlyWorksheet.iter_rows
    calls = []
    def bounded(sheet, **kwargs):
        if sheet.title == proof.ESTIMATE:
            calls.append(kwargs)
            assert kwargs.get('max_row') is not None and kwargs['max_row'] <= proof.MAX_ROWS
            assert kwargs.get('max_col') is not None and kwargs['max_col'] <= proof.MAX_COLUMNS
        return original(sheet, **kwargs)
    monkeypatch.setattr(ReadOnlyWorksheet, 'iter_rows', bounded)
    with proof._book(raw) as book:
        original_sheet = book[proof.ESTIMATE]
        dims = (original_sheet.max_row, original_sheet.max_column)
        view = proof._sheet(book, proof.ESTIMATE)
        assert isinstance(view, proof._BoundedWorksheetView)
        assert (original_sheet.max_row, original_sheet.max_column) == dims == (900000,200)
        assert (view.max_row, view.max_column) == (17,7)
        assert calls == []
        assert len(list(view.iter_rows())) == 17
    assert calls


@pytest.mark.parametrize('body', [
    '<v>0</v>', '<v/>', '<f>SUM(A1:A9)</f>', '<f t="shared" si="1"/>',
    '<is><t/></is>', '<is><t>synthetic</t></is>', '<extLst/>'])
def test_any_value_formula_inline_or_unknown_child_beyond_row_cap_still_fails(body):
    raw = inflated(rss_bytes(), payload=f'<row xmlns="{NS}" r="20001"><c r="A20001">{body}</c></row>')
    with pytest.raises(proof.SourceProblem, match='worksheet_size_limit'):
        proof._bank(raw, proof._day(CUT))


@pytest.mark.parametrize('kind,body', [('s','<v>0</v>'),('s',''),('inlineStr',''),
    ('str',''),('e','<v>#N/A</v>'),('b','<v>0</v>'),('d','<v>2026-01-01</v>')])
def test_non_numeric_payload_types_are_not_ignored_as_empty_formatting(kind,body):
    raw = inflated(rss_bytes(), payload=f'<row xmlns="{NS}" r="20001"><c r="A20001" t="{kind}">{body}</c></row>')
    with pytest.raises(proof.SourceProblem, match='worksheet_size_limit'):
        proof._bank(raw, proof._day(CUT))


@pytest.mark.parametrize('row,column',[(20001,'A'),(20,'ALM'),(2500,'AHP')])
def test_old_row_column_and_rectangular_limits_apply_to_real_payload(row,column):
    raw = inflated(rss_bytes(), payload=f'<row xmlns="{NS}" r="{row}"><c r="{column}{row}"><v>1</v></c></row>')
    with pytest.raises(proof.SourceProblem, match='worksheet_size_limit'):
        proof._bank(raw, proof._day(CUT))


class FakeSheet:
    title = proof.ESTIMATE
    max_row = 900000
    max_column = 200
    def __init__(self, xml): self.xml=xml
    def _get_source(self): return io.BytesIO(self.xml)


def xml(data, *, before='', after=''):
    return (f'{before}<worksheet xmlns="{NS}"><dimension ref="A1:GR900000"/><sheetData>{data}</sheetData></worksheet>{after}').encode()


@pytest.mark.parametrize('content',[
    '<row><c r="A1"><v>1</v></c></row>',
    '<row r="1"><c><v>1</v></c></row>',
    '<row r="1"><c r="A2"><v>1</v></c></row>',
    '<row r="1"><c r="A1"><v>1</v></c><c r="A1"><v>2</v></c></row>',
    '<row r="1"><c r="B1"><v>1</v></c><c r="A1"><v>2</v></c></row>',
    '<row r="2"><c r="A2"><v>1</v></c></row><row r="1"><c r="A1"><v>2</v></c></row>',
    '<row r="1"><c r="A1"><v>1</v></c></row><row r="1"><c r="B1"><v>2</v></c></row>',
    '<row r="1"><c r="XFE1"/></row>',
    '<row r="1048577"><c r="A1048577"/></row>',
    '<row r="1"><c r="a1"><v>1</v></c></row>',
    '<c r="A1"><v>1</v></c>',
    '<row r="1"><c xmlns="urn:unknown" r="A1"><v>1</v></c></row>',
    '<row r="1"><c r="A1"><f ref="A1:A20001">1</f></c></row>',
    '<row r="1"><c r="A1"><f ref="A1:XFD1">1</f></c></row>',
    '<row r="1"><c r="A1"><f ref="B1:A1">1</f></c></row>',
    '<row r="1"><c r="A1"><f ref="A1 B1">1</f></c></row>',
    '<row r="900000"><c r="GR900000" s="0"/></row>',
])
def test_ambiguous_refs_or_unproven_empty_sheet_never_become_a_bounded_success(content):
    assert proof._verified_payload_extent(FakeSheet(xml(content))) is None


@pytest.mark.parametrize('doctype',[
    '<!DOCTYPE worksheet [<!ENTITY private "synthetic">]>',
    '<!DOCTYPE worksheet SYSTEM "https://never-fetch.invalid/source">',
    '<!DOCTYPE worksheet [<!ENTITY private SYSTEM "file:///never-read/private">]>',
])
def test_dtd_and_entity_declarations_are_rejected_without_values_or_io(doctype):
    data=xml('<row r="1"><c r="A1"><v>1</v></c></row>',before=doctype)
    assert proof._verified_payload_extent(FakeSheet(data)) is None
    assert proof._verified_payload_extent(FakeSheet(data.decode().encode('utf-16'))) is None


@pytest.mark.parametrize('tail',['<broken','<worksheet/>','unexpected'])
def test_complete_xml_stream_must_be_wellformed_through_eof(tail):
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="1"><c r="A1"><v>1</v></c></row>',after=tail))) is None


def test_formula_dependencies_are_not_evaluated_as_payload_extents():
    data=xml('<row r="1"><c r="A1"><f>SUM(A900000:GR900000)</f></c></row>')
    assert proof._verified_payload_extent(FakeSheet(data)) == (1,1)


def test_deep_or_excessively_expanded_stream_refuses_instead_of_returning_empty(monkeypatch):
    content='<row r="1"><c r="A1">'+('<extension>'*70)+'<v>1</v>'+('</extension>'*70)+'</c></row>'
    assert proof._verified_payload_extent(FakeSheet(xml(content))) is None
    monkeypatch.setattr(proof.ahr,'MAX_EXPANDED',50)
    assert proof._verified_payload_extent(FakeSheet(xml('<row r="1"><c r="A1"><v>1</v></c></row>'))) is None


def test_source_pair_rechecks_and_readonly_bytes_remain_required_after_recovery(source,monkeypatch):
    styled=inflated(source[2]);replace_rss(source,styled)
    paths=[source[0]/'baseline'/'finance.xlsx',source[0]/'estimate'/'2026-11-10.xlsx']
    before={str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in paths}
    got=capture()
    assert got['bank']['observed_payments_at_or_before_cut']['rubles']==280
    assert not got['financial_acceptance'] and not got['source_files_written']
    assert {str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in paths}==before
    original=proof._rss_copy;calls=[]
    def changed(*args,**kwargs):
        raw,meta,identity=original(*args,**kwargs);calls.append(True)
        if len(calls)==2:identity={**identity,'sha256':'f'*64}
        return raw,meta,identity
    monkeypatch.setattr(proof,'_rss_copy',changed)
    with pytest.raises(proof.SourceProblem,match='source_changed'):capture()
    assert len(calls)==2


def test_bounded_view_cannot_be_reopened_with_zero_or_oversized_iteration_limits():
    class Native:
        title='Synthetic'
        def iter_rows(self,**kwargs):pytest.fail('invalid bounds reached native iterator')
        def cell(self,*args):pytest.fail('out-of-bounds cell reached native iterator')
    view=proof._BoundedWorksheetView(Native(),10,7)
    for kwargs in ({'max_row':0},{'max_col':0},{'max_col':1001},{'min_row':0}):
        with pytest.raises(ValueError):list(view.iter_rows(**kwargs))
    assert list(view.iter_rows(min_row=11))==[]
    for row,column in ((0,1),(1,0),(True,1),(20001,1),(1,1001),(20000,101)):
        with pytest.raises(ValueError):view.cell(row,column)


def with_long_xml_tail(raw):
    return changed_member(raw,'xl/worksheets/sheet1.xml',lambda data:data+b' '*250000)


def corrupted_sheet_crc(raw):
    import struct
    data=bytearray(raw);target='xl/worksheets/sheet1.xml'
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        item=archive.getinfo(target);bad=item.CRC^0xffffffff
        struct.pack_into('<I',data,item.header_offset+14,bad)
    offset=0
    while True:
        offset=data.find(b'PK\x01\x02',offset)
        if offset<0:raise AssertionError('synthetic ZIP entry not found')
        count=struct.unpack_from('<H',data,offset+28)[0]
        if bytes(data[offset+46:offset+46+count]).decode()==target:
            struct.pack_into('<I',data,offset+16,bad);return bytes(data)
        offset+=46+count


def test_full_xml_tail_and_crc_are_checked_after_the_closing_worksheet_root():
    clean=rss_bytes();padded=with_long_xml_tail(inflated(clean))
    assert proof._bank(padded,proof._day(CUT))==proof._bank(clean,proof._day(CUT))
    with pytest.raises(proof.SourceProblem,match='worksheet_size_limit'):
        proof._bank(corrupted_sheet_crc(padded),proof._day(CUT))


def test_original_expanded_archive_gate_is_not_replaced_by_extent_proof(monkeypatch):
    monkeypatch.setattr(proof.ahr,'MAX_EXPANDED',100)
    def forbidden(*args):pytest.fail('extent attempted past the existing expanded-byte gate')
    monkeypatch.setattr(proof,'_verified_payload_extent',forbidden)
    with pytest.raises(proof.SourceProblem,match='workbook_size_limit'):
        proof._bank(inflated(rss_bytes()),proof._day(CUT))


@pytest.mark.parametrize('far_cell',[
    '<c r="GR900000">123</c>',
    '<c r="GR900000"><![CDATA[123]]></c>',
    '<c r="GR900000"><!--not proven empty--></c>',
    '<c r="GR900000"/>unexpected',
])
def test_literal_or_unknown_cell_content_is_not_proven_style_only(far_cell):
    content='<row r="1"><c r="A1"><v>1</v></c></row><row r="900000">'+far_cell+'</row>'
    assert proof._verified_payload_extent(FakeSheet(xml(content))) is None


@pytest.mark.parametrize('row,column',[(10,5),(100,5)])
def test_recovered_sheet_preserves_native_blank_cell_reads_beyond_payload_extent(row,column):
    import openpyxl
    book=openpyxl.Workbook();sheet=book.active;sheet.title=proof.ESTIMATE
    sheet['A1']=1;sheet['B2']='Synthetic header'
    stream=io.BytesIO();book.save(stream);book.close();compact=stream.getvalue()
    styled=inflated(compact,payload=f'<row xmlns="{NS}" r="900000"><c r="GR900000" s="0"/></row>')
    with proof._book(compact) as normal,proof._book(styled) as formatted:
        native=proof._sheet(normal,proof.ESTIMATE)
        recovered=proof._sheet(formatted,proof.ESTIMATE)
        assert isinstance(recovered,proof._BoundedWorksheetView)
        assert (recovered.max_row,recovered.max_column)==(2,2)
        assert recovered.cell(row,column).value is native.cell(row,column).value is None
        assert (formatted[proof.ESTIMATE].max_row,formatted[proof.ESTIMATE].max_column)==(900000,200)
