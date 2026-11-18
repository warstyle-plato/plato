"""Repeated PDF attachment headings stay outside the legal contract number."""
import pytest
import pymupdf

import developaid_contract_documents as documents
import developaid_contract_files as files
from tests.test_contract_documents_are_read_from_their_tables import _page, _text


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


def test_another_contract_heading_is_a_boundary_even_without_an_annex_heading():
    read = documents.identity('Договор подряда № FIRST-UNDATED '
                              'к Договору подряда № SECOND-DATED от 04.03.2027')
    assert read['contract'] == {'number': 'SECOND-DATED', 'date': '2027-03-04'}


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
