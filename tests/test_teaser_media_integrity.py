"""Counterexamples for mixed PDFs and source-cell identity in photo imports."""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import document_intake as di
import pdf_ocr
from developaid_v2_upgrade import TepPhotoApplyRequest, apply_photo_values, parse_tep_text
from test_v2_photo_tep import TEP_BLOCK


def _pdf(*texts: str) -> bytes:
    output = io.BytesIO()
    draw = canvas.Canvas(output)
    for text in texts:
        if text:
            draw.drawString(40, 750, text)
        draw.showPage()
    draw.save()
    return output.getvalue()


def test_mixed_pdf_reads_only_sparse_pages_and_keeps_their_numbers(monkeypatch):
    data = _pdf('Project information. ' * 8, '', 'Second text layer. ' * 8)
    calls = []

    def recognize(data, *, page_indices):
        calls.append(page_indices)
        return '[стр. 2]\nСтоимость участка 400 млн руб.'

    monkeypatch.setattr(pdf_ocr, 'text', recognize)
    got = di.extract_text(data, 'mixed.pdf')
    assert calls == [[1]]
    assert '[стр. 1]' in got['text'] and '[стр. 3]' in got['text']
    assert '[стр. 2]\nСтоимость участка 400 млн руб.' in got['text']
    assert [row['status'] for row in got['page_coverage']] == ['text', 'ocr', 'text']
    assert got['pages_read'] == 3


def test_unread_scan_in_mixed_pdf_cannot_be_reported_as_read(monkeypatch):
    monkeypatch.setattr(pdf_ocr, 'text', lambda *_a, **_k: '')
    got = di.extract_text(_pdf('Complete source text. ' * 8, ''), 'mixed.pdf')
    assert got['pages_read'] == 1
    assert got['page_coverage'][1]['status'] == 'unread'
    assert 'стр. 2' in got['reason'] and 'не нашло букв' in got['reason']


def test_ocr_failure_on_one_page_keeps_read_neighbours(monkeypatch):
    def recognize(_data, *, page_indices):
        if page_indices == [1]:
            raise pdf_ocr.Unavailable('Нет русского словаря')
        return f'[стр. {page_indices[0]+1}]\nЦена 400 млн руб.'

    monkeypatch.setattr(pdf_ocr, 'text', recognize)
    got = di.extract_text(_pdf('', '', ''), 'scan.pdf')
    assert got['pages_read'] == 2
    assert '[стр. 1]' in got['text'] and '[стр. 3]' in got['text']
    assert 'стр. 2: Нет русского словаря' in got['reason']


def test_selected_page_ocr_has_identity_and_closes_document_on_failure(monkeypatch):
    calls, closed = [], []

    class Document:
        page_count = 3
        def __getitem__(self, index):
            calls.append(index)
            return SimpleNamespace(get_pixmap=lambda **_: SimpleNamespace(tobytes=lambda _: b'png'))
        def close(self):
            closed.append(True)

    import pymupdf
    monkeypatch.setattr(pymupdf, 'open', lambda **_: Document())
    monkeypatch.setattr(pdf_ocr, 'unavailable_reason', lambda: '')
    monkeypatch.setattr(pdf_ocr.subprocess, 'run', lambda *_a, **_k:
                        SimpleNamespace(returncode=0, stdout=b'price 400'))
    assert pdf_ocr.text(b'pdf', page_indices=[2]) == '[стр. 3]\nprice 400'
    assert calls == [2] and closed == [True]
    monkeypatch.setattr(pdf_ocr.subprocess, 'run', lambda *_a, **_k:
                        SimpleNamespace(returncode=1, stdout=b'incorrect partial text'))
    with pytest.raises(pdf_ocr.Unavailable, match='русского словаря'):
        pdf_ocr.text(b'pdf', page_indices=[1])
    assert len(closed) == 2


@pytest.mark.parametrize('format', ['PNG', 'JPEG'])
def test_raw_photo_uses_shared_document_ocr(monkeypatch, format):
    image = Image.new('RGB', (50, 80), 'white')
    output = io.BytesIO()
    image.save(output, format=format)

    def recognize(data, *, page_indices):
        assert len(PdfReader(io.BytesIO(data)).pages) == 1
        assert page_indices == [0]
        return '[стр. 1]\nЦена участка 400 млн руб.'

    monkeypatch.setattr(pdf_ocr, 'text', recognize)
    got = di.extract_text(output.getvalue(), 'photo.' + format.lower())
    assert got['recognized'] is True and got['pages_read'] == 1
    assert '400 млн' in got['text']


def test_photo_orientation_and_size_limit():
    image = Image.new('RGB', (50, 80), 'white')
    exif = image.getexif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, format='JPEG', exif=exif)
    page = PdfReader(io.BytesIO(di._image_pdf(output.getvalue()))).pages[0]
    assert page.mediabox.width > page.mediabox.height
    with pytest.raises(ValueError, match='12 МБ'):
        di._image_pdf(b'x' * (di.IMAGE_MAX_BYTES + 1))


HEADER = 'Наименование   ГНС   Общая площадь   Полезная   Продаваемая   Передается городу   Количество\n'


@pytest.mark.parametrize('line', [
    'Квартиры   10000   —   8000   7500   0   100',
    'Квартиры\t10000\t\t8000\t7500\t0\t100',
])
def test_empty_source_cell_preserves_column_positions(line):
    got = parse_tep_text(HEADER + line, TEP_BLOCK)
    values = {row['field_key']: row['value'] for row in got['suggestions']}
    assert values == {'gns': 10000, 'useful': 8000, 'saleable': 7500, 'transfer': 0, 'units': 100}
    assert all('confidence' not in row for row in got['suggestions'])


@pytest.mark.parametrize('text', [
    HEADER + 'Квартиры 10000 9000 8000 7500 0 100',
    HEADER + 'Квартиры   10000   8000   7500   0   100',
    HEADER + 'Квартиры   10000   9000   8000   7500   0   100   200',
    'Квартиры   10000   9000   8000   7500   0   100',
])
def test_ambiguous_or_unlabelled_column_order_is_not_applied(text):
    got = parse_tep_text(text, TEP_BLOCK)
    assert got['suggestions'] == []
    assert got['warnings']


@pytest.mark.parametrize('value', ['12,345', '12.345'])
def test_ambiguous_decimal_or_thousands_suffix_needs_review(value):
    got = parse_tep_text(HEADER + f'Квартиры   {value}   9000   8000   7500   0   100', TEP_BLOCK)
    assert got['suggestions'] == []


def test_repeated_row_with_different_numbers_is_a_conflict():
    got = parse_tep_text(HEADER + 'Квартиры   10000   9000   8000   7500   0   100\n'
                        + 'Квартиры   20000   19000   18000   17500   0   200', TEP_BLOCK)
    assert got['suggestions'] == []
    assert 'разные строки' in got['warnings'][0]


def test_photo_packet_preserves_source_cells_and_reaches_the_engine():
    import main as wrapper
    import developaid_v2_form
    core = wrapper.core
    block = next(item for item in developaid_v2_form.form_description(core)['blocks']
                 if item.get('kind') == 'tep')
    parking_label = next(row['label'] for row in block['rows'] if row['key'] == 'underground_parking')
    parsed = parse_tep_text(HEADER + 'Квартиры   10000   9000   8000   7200   800   100\n'
                            + f'{parking_label}   2200   2200   0   0   0   50', block)
    fields = parsed['suggestions']
    assert len(fields) == 12
    got = apply_photo_values(core, TepPhotoApplyRequest(
        inputs=dict(core.DEFAULT_INPUTS), tep=core.TEP_DEFAULT, selected=fields))
    assert got['tep']['apartments']['saleable'] == 7200
    assert got['inputs']['underground_manual_spaces'] == 50
    assert got['inputs']['underground_manual_gns_sqm'] == 2200
    result = core.calculate(core.CalcRequest(inputs=got['inputs'], tep=got['tep'], rates=[]))
    rows = {row['key']: row for row in result['tep']['rows']}
    assert rows['apartments']['gns'] == 10000
    assert rows['apartments']['saleable'] == 7200
    assert rows['underground_parking']['units'] == 50
    assert rows['underground_parking']['gns'] == 2200
    assert got['inputs']['_field_origin']['inputs.underground_manual_spaces']['source'] == 'manual'


def test_photo_packet_refuses_conflicting_values_for_one_cell():
    import main as wrapper
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        apply_photo_values(wrapper.core, TepPhotoApplyRequest(selected=[
            {'row_key': 'apartments', 'field_key': 'gns', 'value': 10000},
            {'row_key': 'apartments', 'field_key': 'gns', 'value': 20000},
        ]))
    assert exc.value.status_code == 409


def test_photo_packet_refuses_source_area_that_normative_mode_would_replace():
    import main as wrapper
    from fastapi import HTTPException
    core = wrapper.core
    inputs = dict(core.DEFAULT_INPUTS)
    inputs['social_area_source'] = 'norm'
    with pytest.raises(HTTPException) as exc:
        apply_photo_values(core, TepPhotoApplyRequest(inputs=inputs, tep=core.TEP_DEFAULT, selected=[
            {'row_key': 'kindergarten', 'field_key': 'gns', 'value': 123},
        ]))
    assert exc.value.status_code == 409
    assert 'режим' in exc.value.detail


def test_photo_review_runs_actual_script_and_does_not_claim_numeric_confidence():
    source = (Path(__file__).resolve().parents[1] / 'frontend_v2/upgrade.js').read_text()
    start = source.index('  function renderPhotoReview(')
    function = source[start:source.index('\n  }\n', start) + 5]
    js = '''const photoState={}; const review={};const status={};
const document={getElementById:id=>id==='v2PhotoReview'?review:id==='v2PhotoStatus'?status:{addEventListener(){}}};
const esc=String;const formatNumber=String;const currentField=()=>({value:0});function applyPhotoSuggestions(){};
''' + function + '''
renderPhotoReview({suggestions:[{row_key:'apartments',field_key:'gns',row_label:'Квартиры',field_label:'ГНС',value:10000,source_line:'Квартиры 10000',label_similarity:.99}],recognized_rows:1,total_rows:1});
console.log(JSON.stringify(review));'''
    result = json.loads(subprocess.check_output(['node', '-e', js], text=True))
    assert 'уверенность' not in result['innerHTML']
    assert 'сверьте число с фотографией' in result['innerHTML']
    assert ' checked' not in result['innerHTML']


@pytest.mark.parametrize('edit_during_request', [False, True])
def test_photo_apply_runs_one_real_js_packet_and_preserves_concurrent_edits(edit_during_request):
    source = (Path(__file__).resolve().parents[1] / 'frontend_v2/upgrade.js').read_text()
    start = source.index('  async function applyPhotoSuggestions(')
    function = source[start:source.index('\n  }\n', start) + 5]
    js = '''const photoState={suggestions:[{row_key:'apartments',field_key:'gns',value:10000},{row_key:'apartments',field_key:'saleable',value:7200}],busy:false};
const status={};const button={};const form={draft:{inputs:{purchase_price_mln:400},tep:{apartments:{gns:1,saleable:1}}}};let posted;
const document={querySelectorAll:()=>[{dataset:{photoIndex:0}},{dataset:{photoIndex:1}}],getElementById:id=>id==='v2PhotoStatus'?status:button};
function renderStep(){};
const nativeFetch=async(url,options)=>{posted={url,body:JSON.parse(options.body)};
''' + ('form.draft.inputs.purchase_price_mln=450;' if edit_during_request else '') + '''
return {ok:true,json:async()=>({inputs:{purchase_price_mln:400,_field_origin:{'tep.apartments.gns':{source:'document'}}},tep:{apartments:{gns:10000,saleable:7200}},applied:[{},{}]})};};
''' + function + '''
(async()=>{await applyPhotoSuggestions();console.log(JSON.stringify({form,status,posted}));})();'''
    got = json.loads(subprocess.check_output(['node', '-e', js], text=True))
    assert got['posted']['url'] == '/api/v2/tep-photo/apply'
    assert len(got['posted']['body']['selected']) == 2
    if edit_during_request:
        assert got['form']['draft']['inputs']['purchase_price_mln'] == 450
        assert got['form']['draft']['tep']['apartments']['gns'] == 1
        assert 'изменились' in got['status']['textContent']
    else:
        assert got['form']['draft']['tep']['apartments'] == {'gns': 10000, 'saleable': 7200}
        assert got['form']['draft']['inputs']['_field_origin']['tep.apartments.gns']['source'] == 'document'
