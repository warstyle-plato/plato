"""Use a second existing text reader before classifying a page as a scan.

The owner's PDF remains private. These regressions pair a real native PDF layer
with the weak primary-reader output that triggered the unnecessary OCR path.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

import document_intake as intake
import document_processing as processing
import pdf_ocr


def pdf(*layers):
    output=io.BytesIO();draw=canvas.Canvas(output)
    for text in layers:
        if text:draw.drawString(40,750,text)
        draw.showPage()
    draw.save()
    return output.getvalue()


def primary(monkeypatch,*layers):
    import pypdf
    pages=[SimpleNamespace(extract_text=lambda text=text:text) for text in layers]
    monkeypatch.setattr(pypdf,'PdfReader',lambda *_:SimpleNamespace(pages=pages))


@pytest.mark.parametrize('recognize',[True,False])
def test_existing_native_layer_is_read_before_ocr_without_claiming_recognition(monkeypatch,recognize):
    native='Readable native source text with its original words and punctuation.'
    data=pdf(native)
    primary(monkeypatch,'•\n28 13')
    monkeypatch.setattr(pdf_ocr,'text',lambda *a,**k:pytest.fail('Readable page reached OCR'))
    result=intake.extract_text(data,'source.pdf',recognize=recognize)
    assert result['text'].strip()=='[стр. 1]\n'+native
    assert result['pages_read']==1 and not result['recognized'] and not result['scanned']
    assert result['reason']==''
    assert result['page_coverage']==[{'page':1,'status':'text','needs_recognition':False}]


def test_complete_primary_layer_does_not_open_the_alternate_reader(monkeypatch):
    text='Primary source text already contains a complete readable layer.'
    primary(monkeypatch,text)
    monkeypatch.setattr(intake,'_native_pdf_text',lambda *a:pytest.fail('Complete layer read twice'))
    result=intake.extract_text(b'primary-mocked','source.pdf')
    assert result['text']=='[стр. 1]\n'+text and result['pages_read']==1


def test_mixed_native_and_scanned_pages_keep_source_page_identity_and_ocr_budget(monkeypatch):
    first='Native source on page one stays attached to its original page.'
    third='Primary source on page three stays attached to its original page.'
    data=pdf(first,'',third)
    primary(monkeypatch,'•','',third)
    calls=[]
    monkeypatch.setattr(intake,'OCR_MAX_PAGES',1)
    monkeypatch.setattr(pdf_ocr,'text',lambda data,*,page_indices:
        calls.append(page_indices) or '[стр. 2]\nText read from the scanned page.')
    result=intake.extract_text(data,'mixed.pdf')
    assert calls==[[1]]
    assert '[стр. 1]\n'+first in result['text']
    assert '[стр. 2]\nText read from the scanned page.' in result['text']
    assert '[стр. 3]\n'+third in result['text']
    assert [row['status'] for row in result['page_coverage']]==['text','ocr','text']
    assert result['pages_read']==3 and result['recognized']


def test_sparse_alternate_layer_does_not_lower_the_existing_completeness_threshold(monkeypatch):
    data=pdf('Short native layer')
    primary(monkeypatch,'•\n28 13')
    monkeypatch.setattr(pdf_ocr,'text',lambda *a,**k:pytest.fail('recognize=False reached OCR'))
    result=intake.extract_text(data,'source.pdf',recognize=False)
    assert result['pages_read']==0 and result['page_coverage'][0]['status']=='partial'
    assert result['text']=='[стр. 1]\n•\n28 13' and result['scanned']


def test_alternate_reader_never_reads_beyond_the_existing_page_limit(monkeypatch):
    text='A native source layer with enough complete original text to be read.'
    data=pdf(text,text)
    primary(monkeypatch,'•','•')
    monkeypatch.setattr(intake,'MAX_PAGES',1)
    result=intake.extract_text(data,'limited.pdf',recognize=False)
    assert result['pages']==2 and result['pages_read']==1
    assert result['page_coverage'][1]['status']=='unread'
    assert result['page_coverage'][1]['reason']=='предел чтения — 1 страниц'
    assert '[стр. 2]' not in result['text']


def test_native_layout_joins_unit_and_punctuation_fragments_without_changing_source_glyphs():
    import xml.etree.ElementTree as ET
    root=ET.Element('page');block=ET.SubElement(root,'block')
    def line(text,x,y,synthetic_gap=False):
        item=ET.SubElement(block,'line',dir='1 0');font=ET.SubElement(item,'font')
        for c in text:
            ET.SubElement(font,'char',c=c,x=str(x),y=str(y),flags='532' if synthetic_gap and c==' ' else '16')
    line('Source area',10,10);line('12, 34',100,10,True);line('ha',140,10)
    line('Literal source space 12, 34',10,20)
    line('Gross area 56 700 m',10,30);line('²',140,30)
    line('Places 120',10,40);line('мест',100,40);line(';',140,40)
    page=SimpleNamespace(get_text=lambda *a,**k:ET.tostring(root,encoding='unicode'))
    text=intake._native_pdf_lines(page)
    assert text=='Source area 12,34 ha\nLiteral source space 12, 34\nGross area 56 700 m²\nPlaces 120 мест;'


def test_rotated_native_text_keeps_the_readers_original_order():
    xml='<page><block><line dir="0 -1"><char c="A" x="1" y="1"/></line></block></page>'
    page=SimpleNamespace(get_text=lambda mode,**kwargs:xml if mode=='xml' else 'Original rotated layer')
    assert intake._native_pdf_lines(page)=='Original rotated layer'


def test_large_native_layer_does_not_expand_to_a_glyph_tree():
    text='A'*(intake.DOCUMENT_TEXT_BUDGET+1)
    def get_text(mode,**kwargs):
        assert mode=='text', 'A large layer must not allocate an expanded XML tree'
        return text
    assert intake._native_pdf_lines(SimpleNamespace(get_text=get_text))==text


@pytest.mark.parametrize('failure',['open','page'])
def test_alternate_parser_failure_preserves_the_existing_ocr_path_and_closes_document(monkeypatch,failure):
    import pymupdf
    primary(monkeypatch,'•')
    closed=[]
    class Document:
        def __getitem__(self,index):raise ValueError('synthetic native-page failure')
        def close(self):closed.append(True)
    def open_document(**kwargs):
        if failure=='open':raise RuntimeError('synthetic native-open failure')
        return Document()
    monkeypatch.setattr(pymupdf,'open',open_document)
    monkeypatch.setattr(pdf_ocr,'text',lambda *a,**k:'[стр. 1]\nA scanned page still uses the existing OCR path.')
    result=intake.extract_text(b'primary-mocked','source.pdf')
    assert result['recognized'] and result['pages_read']==1
    assert closed==([] if failure=='open' else [True])


@pytest.mark.parametrize('phase',['open','read'])
@pytest.mark.parametrize('outcome',['cancelled','expired'])
def test_alternate_reader_closes_and_propagates_the_native_operation_stop(monkeypatch,phase,outcome):
    import pymupdf
    primary(monkeypatch,'•')
    now=[0.0];current=[True];closed=[]
    monkeypatch.setattr(processing.time,'monotonic',lambda:now[0])
    def stop():
        if outcome=='cancelled':current[0]=False
        else:now[0]=2.0
    class Document:
        def __getitem__(self,index):
            def text(kind,**kwargs):
                assert phase=='read'
                stop()
                return '<page/>'
            return SimpleNamespace(get_text=text)
        def close(self):closed.append(True)
    def open_document(**kwargs):
        if phase=='open':stop()
        return Document()
    monkeypatch.setattr(pymupdf,'open',open_document)
    monkeypatch.setattr(pdf_ocr,'text',lambda *a,**k:pytest.fail('Stopped native layer reached OCR'))
    error=processing.Cancelled if outcome=='cancelled' else processing.Expired
    with processing.operation(seconds=1,current=lambda:current[0]),pytest.raises(error):
        intake.extract_text(b'primary-mocked','source.pdf')
    assert closed==[True]
