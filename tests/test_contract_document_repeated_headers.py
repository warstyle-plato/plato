"""Repeated PDF attachment headings stay outside the legal contract number."""
import base64
import hashlib

import pytest
import pymupdf

import developaid_contract_documents as documents
import developaid_contract_files as files
from tests.test_contract_documents_are_read_from_their_tables import _page, _text
from test_contract_pdf_intake import project  # noqa: F401
from test_contract_pdf_intake_api import client, body, finish, PREFIX  # noqa: F401


def attachment(number='73/02.27-УЧ', day='04.03.2027', *, agreement=False):
    lines = [f'Договор подряда № {number}', 'Приложение № 8',
             f'к Договору подряда № {number}', f'от {day}']
    if agreement:
        lines.append('(в редакции Дополнительного соглашения № 1 от 21.08.2027)')
    lines.append('ГРАФИК АВАНСИРОВАНИЯ')
    doc = pymupdf.open()
    page = _page(doc)
    for index, text in enumerate(lines):
        _text(page, 40, 45 + 20*index, text)
    raw = doc.tobytes()
    doc.close()
    return raw


@pytest.mark.parametrize('number', ['73/02.27-УЧ', '74/02.27-УЧ'])
@pytest.mark.parametrize('agreement', [False, True])
def test_complete_pdf_reference_excludes_the_undated_running_header(number, agreement):
    read = documents.read(attachment(number, agreement=agreement))
    assert read['contract'] == {'number': number, 'date': '2027-03-04'}
    assert read['estimates'] == [] and read['schedule'] is None
    assert read['agreement'] == ({'number': '1', 'date': '2027-08-21'} if agreement else None)


@pytest.mark.parametrize('middle', ['Приложение № 8 к', 'к'])
def test_a_different_skipped_running_header_is_an_actionable_refusal(middle):
    text = ('Договор подряда № SIGNED-A '+middle+
            ' Договору подряда № OTHER-B от 04.03.2027')
    with pytest.raises(ValueError, match='неоднозначны'):
        documents.identity(text)
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 40, 45, text)
    raw = doc.tobytes()
    doc.close()
    with pytest.raises(files.ContractFilesProblem, match='неоднозначны'):
        files._record('a'*64, 'synthetic.pdf', raw, '2027-04-05T00:00:00+00:00')


def test_an_identical_running_header_without_an_annex_is_valid():
    read = documents.identity('Договор подряда № УЧ / 7.2 - А Б '
                              'к Договору подряда № УЧ/7.2-АБ от 04.03.2027')
    assert read['contract'] == {'number': 'УЧ/7.2-АБ', 'date': '2027-03-04'}


def test_dated_main_and_agreement_references_keep_their_existing_selection():
    text = ('Договор подряда № AGREEMENT-PARENT от 04.03.2027 '
            'Дополнительное соглашение № 2 от 05.03.2027 '
            'к Договору подряда № AGREEMENT-PARENT от 04.03.2027')
    read = documents.identity(text)
    assert read['contract'] == {'number': 'AGREEMENT-PARENT', 'date': '2027-03-04'}
    assert read['agreement'] == {'number': '2', 'date': '2027-03-05'}


def test_an_ordinary_dated_contract_may_mention_another_contract_in_its_body():
    read = documents.identity('Договор подряда № SIGNED-A от 04.03.2027 '
                              'Работы по Договору подряда № OTHER-B от 01.02.2027')
    assert read['contract'] == {'number': 'SIGNED-A', 'date': '2027-03-04'}


def test_mixed_headers_have_an_actionable_initial_preview_refusal_before_storage(project, client):
    values = body()
    doc = pymupdf.open()
    page = _page(doc)
    _text(page, 40, 45, 'Договор подряда № SIGNED-A Приложение № 8 '
                       'к Договору подряда № OTHER-B от 04.03.2027')
    _text(page, 40, 75, values['customer']['quote'])
    _text(page, 40, 95, values['contractor']['quote'])
    raw = doc.tobytes()
    doc.close()
    values.update(content_base64=base64.b64encode(raw).decode(), source_sha256=hashlib.sha256(raw).hexdigest(),
                  contract_number='OTHER-B', contract_date='2027-03-04')
    result = finish(client, client.post(PREFIX+'preview', json=values))
    assert result.status_code == 200
    payload = result.json()
    assert payload['ok'] is False and payload['status'] == 400 and 'неоднозначны' in payload['detail']
    assert not (project/'contract_pdf_sources.json').exists()
    assert not (project/'contract_documents').exists()


@pytest.mark.parametrize('row', [
    {'contract': 'OTHER-УЧ', 'contract_date': '2027-03-04'},
    {'contract': '73/02.27-УЧ', 'contract_date': '2027-03-05'},
])
def test_repaired_pdf_identity_still_refuses_another_number_or_date(row):
    read = documents.read(attachment())
    assert files._same_contract(read['contract'], row)


@pytest.mark.parametrize('found,target', [('88-УЧ-СМР', '88-УЧ-ВП'), ('89-УЧ-ОВ', '89-УЧ-Вент')])
def test_contract_work_suffixes_are_never_folded_together(found, target):
    read = documents.identity(f'Договор подряда № {found} на выполнение работ г. Москва «4» марта 2027 г.')
    assert read['contract'] == {'number': found, 'date': '2027-03-04'}
    assert files._same_contract(read['contract'], {'contract': target, 'contract_date': '2027-03-04'})


def test_number_punctuation_and_spaces_are_kept_in_an_ordinary_reference():
    read = documents.identity('Договор подряда № УЧ / 7.2 - А Б от 04.03.2027')
    assert read['contract'] == {'number': 'УЧ / 7.2-А Б', 'date': '2027-03-04'}
