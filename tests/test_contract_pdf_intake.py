"""Synthetic original PDFs exercise initial source admission and later real KS intake."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import zipfile

import openpyxl
import pymupdf
import pytest

import developaid_contract_fact as fact
import developaid_contract_files as files
import developaid_contract_identity_store as namespace
import developaid_contract_pdf_intake as intake
import developaid_contract_source_review as review
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from tests.test_contract_documents_are_read_from_their_tables import _page, _text

PROJECT, CUT = 'Учебный PDF', '2026-11-18'
ACTOR = 'a' * 64
CUSTOMER = 'ООО «Заказчик Учебный»'
CONTRACTOR = 'ООО «Подрядчик Учебный»'


def pdf(number='88-ТСТ', agreement=False, extra=''):
    doc = pymupdf.open()
    page = _page(doc)
    header = ('Дополнительное соглашение № 1 к ' if agreement else '') + f'Договор подряда № {number} от 01.02.2026'
    customer = f'{CUSTOMER}, именуемое в дальнейшем «Заказчик»'
    contractor = f'{CONTRACTOR}, именуемое в дальнейшем «Подрядчик»'
    for i, text in enumerate([header, customer, contractor, extra]):
        _text(page, 40, 45 + i * 24, text)
    raw = doc.tobytes()
    doc.close()
    claims = {'source_sha256': hashlib.sha256(raw).hexdigest(), 'contract_number': number, 'contract_date': '2026-02-01',
              'customer': {'name': CUSTOMER, 'designation': 'Заказчик', 'page': 1, 'quote': customer},
              'contractor': {'name': CONTRACTOR, 'designation': 'Подрядчик', 'page': 1, 'quote': contractor}}
    return raw, claims


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    root = monitor._project_dir(PROJECT)
    (root/'estimate').mkdir()
    (root/'estimate'/'source.txt').write_text('Synthetic project source')
    return root


def admit(raw, claims, **kwargs):
    checked = intake.preview(PROJECT, raw, **claims)
    saved = intake.commit(PROJECT, raw, filename='synthetic.pdf', expected_revision=checked['revision'],
                          preview_token=checked['preview_token'], actor=ACTOR, **claims, **kwargs)
    return checked, saved


def test_original_is_source_bound_and_not_a_financial_or_execution_fact(project):
    raw, claims = pdf()
    checked, saved = admit(raw, claims)
    assert saved['contract_id'] == contracts._groups([checked['evidence']['identity']], PROJECT)[0][0]
    assert saved['financial_acceptance'] is False and saved['revision'] == 1
    row, = contracts.build(PROJECT, CUT)['rows']
    assert row['source_kind'] == 'contract_document'
    assert all(row.get(k) is None for k in ('amount', 'completed', 'remaining', 'completion_ratio'))
    assert row['advance']['paid'] is None and row['advance']['unworked'] is None
    assert not row['physical_items'] and not row['financial_sources']
    assert row['document_provenance'][0]['evidence'] == checked['evidence']
    assert row['document_provenance'][0]['actor'] == ACTOR
    listing = files.listing(PROJECT, row['id'], CUT, fact.acts(row))
    assert listing['fact']['total'] is None and listing['fact']['source'] is None
    assert listing['control']['total'] is None and listing['control']['forecast'] is None
    assert len(listing['documents']) == 1
    assert 'КС-6а' in listing['fact']['note'] and 'факт взят' not in listing['fact']['source_note']
    source_review = review.review(PROJECT, row['id'], CUT)
    assert source_review['source_family'] == 'confirmed_contract_pdf' and source_review['source_count'] == 1
    assert (project/'contract_documents'/row['id']/(claims['source_sha256']+'.pdf')).read_bytes() == raw
    assert not (project/'cumulative').exists()
    assert contracts.build(PROJECT, '2026-01-31')['rows'] == []


def test_existing_card_js_names_the_pdf_source_and_keeps_unknown_values(project):
    from developaid_monitor_page import MONITOR_PAGE
    from tests import page_blocks
    raw, claims = pdf()
    admit(raw, claims)
    register = contracts.build(PROJECT, CUT, include_history=False)
    prelude = 'const contractRegister='+json.dumps(register, ensure_ascii=False)+';'
    rendered = page_blocks.run_json(prelude, """
const row=contractRegister.rows[0];
console.log(JSON.stringify({label:contractUniverseLabel(),physical:contractPhysicalSourceHtml(row),
financial:contractFinancialSourceHtml(row)}));
""", page=MONITOR_PAGE)
    assert rendered['label'] == 'Источников договоров'
    assert 'Накопительная КС-6а к ней не привязана' in rendered['physical']
    assert 'КС-2 и накопительная КС-6а не предоставлены' not in rendered['physical']
    assert 'В накопительной нет объёмов' not in rendered['physical']
    assert 'Выполнение по документам' in rendered['financial']
    assert 'Выполнено по накопительным' not in rendered['financial']
    assert 'Оплачено: —' in rendered['financial']


@pytest.mark.parametrize('change,reason', [
    ({'source_sha256': 'b'*64}, 'SHA'), ({'contract_number': 'OTHER'}, 'Номер'),
    ({'contract_date': '2026-02-02'}, 'Номер'),
    ({'customer': {'name': CUSTOMER, 'designation': 'Заказчик', 'page': 2, 'quote': 'absent'}}, 'страницу'),
    ({'customer': {'name': CUSTOMER, 'designation': 'Заказчик', 'page': 1, 'quote': 'absent'}}, 'Цитата'),
])
def test_source_and_identity_mismatches_never_publish_a_card(project, change, reason):
    raw, claims = pdf()
    with pytest.raises(intake.IntakeProblem, match=reason):
        intake.preview(PROJECT, raw, **{**claims, **change})
    assert not (project/intake.REGISTRY).exists()
    assert not (project/'contract_documents').exists()


def test_roles_cannot_be_swapped_or_confirmed_from_a_whole_page(project):
    raw, claims = pdf()
    swapped = {**claims, 'customer': {**claims['contractor'], 'designation': 'Заказчик'},
               'contractor': {**claims['customer'], 'designation': 'Подрядчик'}}
    with pytest.raises(intake.IntakeProblem, match='Цитата'):
        intake.preview(PROJECT, raw, **swapped)
    with pymupdf.open(stream=raw, filetype='pdf') as doc:
        whole = doc[0].get_text()
    with pytest.raises(intake.IntakeProblem, match='отдельная цитата'):
        intake.preview(PROJECT, raw, **{**claims, 'customer': {**claims['customer'], 'quote': whole}})
    with pytest.raises(intake.IntakeProblem, match='полное наименование'):
        intake.preview(PROJECT, raw, **{**claims, 'customer': {**claims['customer'], 'name': 'ООО «Заказчик»'}})


def test_supplement_cannot_be_an_initial_contract(project):
    raw, claims = pdf(agreement=True)
    with pytest.raises(intake.IntakeProblem, match='основному договору'):
        intake.preview(PROJECT, raw, **claims)


def test_unknown_project_namespace_and_symlink_are_refused(project):
    raw, claims = pdf()
    with pytest.raises(intake.IntakeProblem, match='существующий проект'):
        intake.preview('Несуществующий проект', raw, **claims)
    assert not (project.parent/monitor._slug('Несуществующий проект')).exists()
    (project/intake.REGISTRY).symlink_to(project/'estimate'/'source.txt')
    with pytest.raises(intake.IntakeProblem, match='Ссылка'):
        intake.preview(PROJECT, raw, **claims)


def test_token_project_source_roles_revision_and_cas_are_bound(project):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    args = dict(filename='source.pdf', expected_revision=0, preview_token=checked['preview_token'], actor=ACTOR, **claims)
    with pytest.raises(intake.IntakeProblem, match='Проверка относится'):
        intake.commit(PROJECT, raw, **{**args, 'expected_revision': 1})
    changed = {**claims['customer'], 'name': claims['customer']['name'].upper()}
    with pytest.raises(intake.IntakeProblem, match='Проверка относится'):
        intake.commit(PROJECT, raw, **{**args, 'customer': changed})
    other = monitor._project_dir('Другой учебный')
    (other/'estimate').mkdir()
    (other/'estimate'/'source.txt').write_text('Synthetic')
    with pytest.raises(intake.IntakeProblem, match='Проверка относится'):
        intake.commit('Другой учебный', raw, **args)
    other_raw, other_claims = pdf('89-ТСТ')
    with pytest.raises(intake.IntakeProblem, match='Проверка относится'):
        intake.commit(PROJECT, other_raw, **{**args, **other_claims})
    _, saved = admit(raw, claims)
    with pytest.raises(intake.IntakeProblem, match='уже изменился'):
        intake.commit(PROJECT, other_raw, filename='other.pdf', expected_revision=0,
                      preview_token=intake._token(intake._evidence(PROJECT, other_raw, **other_claims), 0),
                      actor=ACTOR, **other_claims)
    again = intake.commit(PROJECT, raw, **args)
    assert again['already'] and again['contract_id'] == saved['contract_id']
    assert json.loads((project/intake.REGISTRY).read_text())['revision'] == 1


def test_concurrent_commits_publish_one_revision_and_one_pdf(project):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    def save(_):
        return intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                             preview_token=checked['preview_token'], actor=ACTOR, **claims)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = workers.map(save, range(2))
    assert sorted([first['already'], second['already']]) == [False, True]
    assert first['contract_id'] == second['contract_id']
    assert len(list((project/'contract_documents').glob('*/*.pdf'))) == 1
    assert intake._read_state(PROJECT)['revision'] == 1


def test_original_tampering_fails_closed_and_unpublished_native_file_is_retryable(project, monkeypatch):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    original = files._write
    def crash(path, value):
        if path.name == intake.REGISTRY:
            raise OSError('Synthetic crash before publication')
        original(path, value)
    monkeypatch.setattr(files, '_write', crash)
    with pytest.raises(OSError, match='Synthetic crash'):
        intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert contracts.build(PROJECT, CUT)['rows'] == []
    monkeypatch.setattr(files, '_write', original)
    _, saved = admit(raw, claims)
    path = project/'contract_documents'/saved['contract_id']/(claims['source_sha256']+'.pdf')
    path.write_bytes(b'%PDF synthetic corruption')
    with pytest.raises(intake.IntakeProblem, match='изменился'):
        contracts.build(PROJECT, CUT)
    with pytest.raises(intake.IntakeProblem, match='изменился'):
        intake.commit(PROJECT, raw, filename='retry.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)


def test_namespace_retarget_cannot_publish_or_write_under_the_other_project(project, monkeypatch):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    other = monitor._project_dir('Другой учебный')
    other.mkdir(exist_ok=True)
    original = files.store
    def retarget(*args, **kwargs):
        (monitor._SNAPSHOT_DIR/monitor._ALIASES_FILE).write_text(json.dumps(
            {'aliases': {monitor._slug(PROJECT): other.name}}))
        return original(*args, **kwargs)
    monkeypatch.setattr(files, 'store', retarget)
    with pytest.raises(namespace.IdentityProblem, match='Привязка имени проекта изменилась'):
        intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert not (project/intake.REGISTRY).exists()
    assert not (other/'contract_documents').exists()
    assert not (other/intake.REGISTRY).exists()


def test_registry_budget_is_checked_before_publishing_a_source(project, monkeypatch):
    raw, claims = pdf()
    checked = intake.preview(PROJECT, raw, **claims)
    monkeypatch.setattr(intake, 'MAX_REGISTRY_BYTES', 10)
    with pytest.raises(intake.IntakeProblem, match='предел реестра'):
        intake.commit(PROJECT, raw, filename='source.pdf', expected_revision=0,
                      preview_token=checked['preview_token'], actor=ACTOR, **claims)
    assert not (project/intake.REGISTRY).exists()
    assert not (project/'contract_documents').exists()


def test_missing_native_read_cannot_silently_hide_the_admitted_original(project):
    raw, claims = pdf()
    _, saved = admit(raw, claims)
    (project/'contract_documents'/saved['contract_id']/(claims['source_sha256']+'.json')).unlink()
    with pytest.raises(intake.IntakeProblem, match='сохранённый разбор'):
        contracts.build(PROJECT, CUT)


def test_later_native_ks_has_one_card_and_retains_source_documents_even_with_full_legal_form(project):
    raw, claims = pdf()
    _, saved = admit(raw, claims)
    # Native ZIP parser: only its real supported workbook schema creates KS.
    import datetime as dt
    from tests.test_contracts_from_cumulative_headers import ks
    book = openpyxl.load_workbook(io.BytesIO(ks(number='88-ТСТ', date=dt.date(2026, 2, 1))))
    sheet = book.active
    sheet['C1'] = CUSTOMER
    sheet['C2'] = 'Общество с ограниченной ответственностью «Подрядчик Учебный»'
    stream = io.BytesIO()
    book.save(stream)
    content = stream.getvalue()
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, 'w') as archive:
        archive.writestr('synthetic.xlsx', content)
    ledgers.store_archive(PROJECT, packed.getvalue(), CUT, 'synthetic.zip')
    row, = contracts.build(PROJECT, CUT, include_history=False)['rows']
    assert row['source_kind'] == 'cumulative' and row['id'] != saved['contract_id']
    assert row['document_source_ids'] == [saved['contract_id']]
    assert row['document_provenance'][0]['source_sha256'] == claims['source_sha256']
    listed = files.listing(PROJECT, row['id'], CUT, fact.acts(row))
    assert [d['sha256'] for d in listed['documents']] == [claims['source_sha256']]
    assert files.store(PROJECT, row, 'copy.pdf', raw)['already']
    removed = files.remove(PROJECT, row['id'], claims['source_sha256'], cut=CUT, acts=fact.acts(row))
    assert not removed['documents'] and len(removed['removed']) == 1
    restored = files.remove(PROJECT, row['id'], claims['source_sha256'], restore=True, cut=CUT, acts=fact.acts(row))
    assert len(restored['documents']) == 1
