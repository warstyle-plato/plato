"""Regression cases from independent source-bound intake review; all data is synthetic."""
import hashlib
import json

import pymupdf
import pytest

import developaid_contract_files as files
import developaid_contract_pdf_intake as intake
import developaid_contract_fact as fact
import developaid_monitor_contracts as contracts
from test_contract_pdf_intake import PROJECT, CUT, ACTOR, CUSTOMER, CONTRACTOR, pdf, project, admit
from tests.test_contract_documents_are_read_from_their_tables import _page, _text


def custom_pdf(customer_clause=None, contractor_clause=None, header=None, separate=False):
    customer_clause = customer_clause or f'{CUSTOMER}, именуемое в дальнейшем «Заказчик»'
    contractor_clause = contractor_clause or f'{CONTRACTOR}, именуемое в дальнейшем «Подрядчик»'
    doc = pymupdf.open()
    p = _page(doc)
    _text(p, 40, 45, header or 'Договор подряда № 88-ТСТ от 01.02.2026')
    if separate:
        p = _page(doc)
    _text(p, 40, 90, customer_clause)
    if separate:
        p = _page(doc)
    _text(p, 40, 135, contractor_clause)
    raw = doc.tobytes()
    doc.close()
    _, claims = pdf()
    claims['source_sha256'] = hashlib.sha256(raw).hexdigest()
    claims['customer'].update(quote=customer_clause, page=2 if separate else 1)
    claims['contractor'].update(quote=contractor_clause, page=3 if separate else 1)
    return raw, claims



@pytest.mark.parametrize('clause', [
    f'{CUSTOMER}, не именуемое в дальнейшем «Заказчик»',
    f'{CUSTOMER}, именуемое в дальнейшем «Заказчик-свидетель»',
])
def test_independent_nonmatching_or_negated_role_does_not_admit(project, clause):
    raw, claims = custom_pdf(customer_clause=clause)
    with pytest.raises(intake.IntakeProblem):
        intake.preview(PROJECT, raw, **claims)



def test_independent_source_quote_cannot_move_legal_name_boundary(project):
    original = f'{CUSTOMER}, находящееся в Москве, именуемое в дальнейшем «Заказчик»'
    raw, claims = custom_pdf(customer_clause=original)
    claims['customer']['name'] = 'ООО «Заказчик Учебный, находящееся в Москве»'
    claims['customer']['quote'] = 'ООО «Заказчик Учебный, находящееся в Москве», именуемое в дальнейшем «Заказчик»'
    with pytest.raises(intake.IntakeProblem):
        intake.preview(PROJECT, raw, **claims)


@pytest.mark.parametrize('negative', ['не', 'ни'])
def test_role_citation_cannot_cut_off_a_source_negation(project, negative):
    raw, claims = custom_pdf(customer_clause=f'{negative} Заказчик: {CUSTOMER}')
    claims['customer']['quote'] = f'Заказчик: {CUSTOMER}'
    with pytest.raises(intake.IntakeProblem):
        intake.preview(PROJECT, raw, **claims)



def test_independent_valid_json_corruption_before_publication_cannot_be_admitted(project, monkeypatch):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    original_write = files._write
    def crash(path, data):
        if path.name == intake.REGISTRY:
            raise OSError('simulated interrupted publication')
        return original_write(path, data)
    with monkeypatch.context() as patch:
        patch.setattr(files, '_write', crash)
        with pytest.raises(OSError):
            intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                          preview_token=checked['preview_token'], actor=ACTOR, **claims)
    path = project/'contract_documents'/checked['contract_id']/(claims['source_sha256']+'.json')
    record = json.loads(path.read_bytes())
    record['contract'] = {'number': 'ANOTHER-CONTRACT', 'date': '2020-01-01'}
    path.write_text(json.dumps(record))
    with pytest.raises((intake.IntakeProblem, files.ContractFilesProblem)):
        intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert not (project/intake.REGISTRY).exists()



def test_independent_corrupted_pdf_after_interrupted_publish_cannot_report_success(project, monkeypatch):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    original_write = files._write
    def crash(path, data):
        if path.name == intake.REGISTRY:
            raise OSError('simulated interrupted publication')
        return original_write(path, data)
    with monkeypatch.context() as patch:
        patch.setattr(files, '_write', crash)
        with pytest.raises(OSError):
            intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                          preview_token=checked['preview_token'], actor=ACTOR, **claims)
    persisted = project/'contract_documents'/checked['contract_id']/(claims['source_sha256']+'.pdf')
    persisted.write_bytes(b'%PDF corrupted before publication')
    try:
        result = intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                               preview_token=checked['preview_token'], actor=ACTOR, **claims)
    except (intake.IntakeProblem, files.ContractFilesProblem):
        assert not (project/intake.REGISTRY).exists()
        return
    assert result['revision'] == 1
    assert persisted.read_bytes() == raw, 'Commit reported success but retained a corrupted original'



def test_independent_prior_choices_survive_native_merge_and_can_be_cleared_from_new_edition(project):
    import datetime as dt
    import io
    import zipfile
    import openpyxl
    import developaid_monitor_ledgers as ledgers
    from tests.test_contracts_from_cumulative_headers import ks
    from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf
    from tests.test_contract_link_choices_are_kept_and_carried import _walls
    raw, claims = pdf()
    checked, saved = admit(raw, claims)
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    title = ('Приложение № 1.2 к Дополнительному соглашению № 4 от 01.02.2026',
             'к Договору подряда № 88-ТСТ от 01.02.2026', 'Расчёт договорной стоимости на завершение работ')
    files.store(PROJECT, row, 'schedule.pdf', schedule_pdf(title=('Договор подряда № 88-ТСТ от 01.02.2026',)))
    old_estimate = files.store(PROJECT, row, 'estimate.pdf', estimate_pdf(title=title))['sha256']
    listed = files.listing(PROJECT, row['id'], CUT, fact.acts(row))
    walls = _walls(listed, old_estimate)
    selected = files.save_links(PROJECT, row['id'], old_estimate, 0,
                               [{'index': walls['index'], 'lines': ['2.3']}], cut=CUT, acts=fact.acts(row))
    assert _walls(selected, old_estimate)['status'] == 'confirmed'
    old_folder = project/'contract_documents'/row['id']
    old_choices = (old_folder/files.CHOICES).read_bytes()
    retried = intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                            preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert retried['already'] is True
    assert (old_folder/files.CHOICES).read_bytes() == old_choices
    wb = openpyxl.load_workbook(io.BytesIO(ks(number='88-ТСТ', date=dt.date(2026, 2, 1))))
    wb.active['C1'] = CUSTOMER
    wb.active['C2'] = 'Общество с ограниченной ответственностью «Подрядчик Учебный»'
    book_stream = io.BytesIO()
    wb.save(book_stream)
    zip_stream = io.BytesIO()
    with zipfile.ZipFile(zip_stream, 'w') as zf:
        zf.writestr('ks.xlsx', book_stream.getvalue())
    ledgers.store_archive(PROJECT, zip_stream.getvalue(), CUT, 'synthetic.zip')
    native, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    assert native['id'] != row['id'] and native['document_source_ids'] == [row['id']]
    assert _walls(files.listing(PROJECT, native['id'], CUT, fact.acts(native)), old_estimate)['status'] == 'confirmed'
    assert (old_folder/files.CHOICES).read_bytes() == old_choices
    newer_title = (title[0].replace('№ 4 от 01.02.2026', '№ 5 от 01.03.2026'), *title[1:])
    new_estimate = files.store(PROJECT, native, 'new-estimate.pdf', estimate_pdf(title=newer_title))['sha256']
    listed = files.listing(PROJECT, native['id'], CUT, fact.acts(native))
    new_walls = _walls(listed, new_estimate)
    assert new_walls['status'] == 'confirmed'
    cleared = files.save_links(PROJECT, native['id'], new_estimate, 0,
                               [{'index': new_walls['index']}], clear=True, cut=CUT, acts=fact.acts(native))
    assert _walls(cleared, new_estimate)['status'] != 'confirmed', 'Clear left the inherited initial-folder choice active'
    assert old_folder.is_dir()
    assert (old_folder/files.CHOICES).read_bytes() == old_choices
    assert _walls(cleared, old_estimate)['status'] != 'confirmed'
    confirmed = files.save_links(PROJECT, native['id'], old_estimate, 0,
                                 [{'index': walls['index'], 'lines': ['2.3']}], cut=CUT, acts=fact.acts(native))
    assert _walls(confirmed, new_estimate)['status'] == 'confirmed'
    assert (old_folder/files.CHOICES).read_bytes() == old_choices
