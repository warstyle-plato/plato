"""An identity correction is not a financial-edition decision.

Only synthetic retained sources and temporary native confirmation journals.
"""
from __future__ import annotations

import datetime as dt
import io

import openpyxl
import pytest

import developaid_contract_identity as identity
import developaid_contract_identity_store as journal
import developaid_contract_ownership as ownership
import developaid_monitor as monitor
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_closing_summary_contracts import closing_book
from test_contract_identity_corrections import pins
from test_contracts_from_cumulative_headers import ks
from test_ledger_merged_cost_fields import add_caches
from test_monitor_cumulative_ledgers import archive

PROJECT = 'Synthetic two-source contract'
CUT = '2026-11-14'


def changed_book(raw, changes, caches=None):
    book = openpyxl.load_workbook(io.BytesIO(raw))
    for cell, value in changes.items():
        book.active[cell] = value
    output = io.BytesIO()
    book.save(output)
    return add_caches(output.getvalue(), caches) if caches else output.getvalue()


@pytest.fixture
def pair(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monkeypatch.setattr(contracts, '_read_rss', lambda *_: ([], None, []))
    old = changed_book(ks(number='SOURCE-A'),
        {'C1':'ООО «Учебный заказчик»', 'C2':'ООО «Учебный исполнитель»'})
    newer = changed_book(closing_book(reference='Дог. № SOURCE-B от 01.01.26'),
        {'D7':3, 'E7':dt.date(2026,5,31), 'F7':80}, {'C8':1500, 'F8':380})
    ledgers.store_archive(PROJECT, archive([('Ledger.xlsx', old)]), '2026-11-06', 'first.zip')
    ledgers.store_archive(PROJECT, archive([('Summary.xlsx', newer)]), '2026-11-13', 'second.zip')
    original = contracts.build(PROJECT, CUT, include_history=False)
    by_number = {row['contract']:row for row in original['rows']}
    assert by_number['SOURCE-A']['completed'] == 400
    assert by_number['SOURCE-B']['physical_items'] == []
    assert by_number['SOURCE-B']['summary_progress']['completed'] == 380
    return {'root':journal.project_root(PROJECT), 'before':original,
            'old':by_number['SOURCE-A']['id'], 'new':by_number['SOURCE-B']['id']}


def confirm(pair):
    checked = identity.inventory(PROJECT, [pair['old'], pair['new']], CUT)
    return identity.confirm(PROJECT, checked['raw_ids'], CUT,
        expected_revision=checked['revision'], inventory_sha256=checked['inventory_sha256'],
        source_tokens=[member['source_token'] for member in checked['source_versions']],
        anchor_id=pair['old'], canonical_number='SOURCE-B',
        note='Synthetic number correction; financial edition is not selected.', actor='a'*64)


def assert_unknown(row):
    for key in ('amount','completed','remaining','completion_ratio','deadline'):
        assert row[key] is None
    assert row['progress']['ratio'] is None
    assert row['risk']['forecast_finish'] is None
    assert row['advance']['paid'] is None
    assert row['schedule_control']['finish'] is None
    assert row['logical_ownership']['gap'] == 'financial_source_choice_required'


def test_post_raw_fold_keeps_financial_summary_with_zero_physical_items(pair):
    confirm(pair)
    before = pins(pair['root'])
    view = contracts.build(PROJECT, CUT, include_history=False)
    assert contracts.raw_rows(view) == pair['before']['rows']
    assert len(view['rows']) == 1
    row = view['rows'][0]
    assert row['id'] == pair['old'] and row['contract'] == 'SOURCE-B'
    assert_unknown(row)
    assert row['raw_observations'] == pair['before']['rows']
    assert pins(pair['root']) == before


def test_history_does_not_rebuild_logical_identity_for_every_previous_cut(pair, monkeypatch):
    confirm(pair)
    original, calls = identity.resolve, []
    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(identity, 'resolve', counted)
    row = contracts.build(PROJECT, CUT)['rows'][0]
    assert len(calls) == 1
    assert_unknown(row)
    assert row['progress']['series'] == []
    assert len(row['raw_observations']) == 2


def test_historical_cut_does_not_create_a_future_source_card(pair):
    confirm(pair)
    view = contracts.build(PROJECT, '2026-11-06', include_history=False)
    assert [row['id'] for row in contracts.raw_rows(view)] == [pair['old']]
    assert contracts.find_raw_row(view, pair['new']) is None
    assert [row['id'] for row in view['rows']] == [pair['old']]
    assert view['rows'][0]['completed'] == 400  # one observed source, no aggregate


@pytest.mark.parametrize('change', ['revoke', 'new_archive'])
def test_unresolved_ownership_keeps_raw_sources_without_a_logical_financial_total(pair, change):
    saved = confirm(pair)
    if change == 'revoke':
        identity.revoke(PROJECT, decision_id=saved['event_id'], expected_revision=saved['revision'],
                        note='Synthetic revocation.', actor='a'*64)
    else:
        ledgers.store_archive(PROJECT, archive([('Unreviewed.xlsx', changed_book(ks(number='SOURCE-B'), {'C1':'ООО «Учебный заказчик»','C2':'ООО «Учебный исполнитель»'}))]),
                              CUT, 'unreviewed.zip')
    view = contracts.build(PROJECT, CUT, include_history=False)
    assert len(contracts.raw_rows(view)) == 2
    assert view['logical_ownership']['logical_contracts'] is None
    assert len(view['rows']) == 2
    for row in view['rows']:
        assert_unknown(row)
    import developaid_management_report as report
    markup = report._contract_performance_html(report.contract_risks(PROJECT,CUT))
    assert 'Принадлежность исходных карточек не подтверждена' in markup
    assert 'Единый договор:' not in markup


def test_enrichment_rejects_a_changed_journal_head_instead_of_reusing_an_old_overlay(pair):
    saved = confirm(pair)
    view = contracts.build(PROJECT, CUT, include_history=False)
    identity.revoke(PROJECT, decision_id=saved['event_id'], expected_revision=saved['revision'],
                    note='Synthetic late revocation.', actor='a'*64)
    import developaid_contract_files as cards
    with pytest.raises(ownership.OwnershipProblem, match='изменились'):
        cards.register_control(PROJECT, view, CUT)


def test_late_manifest_day_drift_is_not_hidden_by_an_unchanged_snapshot_id(pair, monkeypatch):
    confirm(pair)
    original = identity.resolve
    listing = ledgers.list_snapshots
    def drift(*args, **kwargs):
        result = original(*args, **kwargs)
        def changed(project):
            rows = listing(project)
            for row in rows:
                if row['taken_at'] == '2026-11-13':
                    row['taken_at'] = '2026-11-12'
            return rows
        monkeypatch.setattr(ledgers, 'list_snapshots', changed)
        return result
    monkeypatch.setattr(identity, 'resolve', drift)
    with pytest.raises(contracts.ContractProblem, match='Дата сохранённого архива'):
        contracts.build(PROJECT,CUT,include_history=False)


def test_raw_getters_keep_both_original_addresses_and_no_future_documents(pair, monkeypatch):
    confirm(pair)
    import main
    import developaid_contract_files as cards
    calls = []
    def listing(project, identifier, cut, acts):
        calls.append(identifier)
        return {'contract_id':identifier,'documents':[]}
    monkeypatch.setattr(cards, 'listing', listing)
    for identifier in (pair['old'],pair['new']):
        result = main.core._monitor_cumulative_execute('documents',
            {'project':PROJECT,'cut':CUT,'contract_id':identifier})
        assert result['ok'] and result['contract_id'] == identifier
    assert calls == [pair['old'],pair['new']]
    result = main.core._monitor_cumulative_execute('documents',
        {'project':PROJECT,'cut':'2026-11-06','contract_id':pair['new']})
    assert result['ok'] is False
    assert calls == [pair['old'],pair['new']]


def test_management_projection_keeps_raw_provenance_and_unknown_parent(pair):
    confirm(pair)
    import developaid_management_report as report
    block = report.contract_risks(PROJECT, CUT)
    row, = block['performance_rows']
    assert row['amount'] is None and row['completed'] is None and row['deadline'] is None
    assert row['progress']['ratio'] is None and row['risk']['forecast_finish'] is None
    assert row['advance']['paid'] is None
    assert {raw['id'] for raw in row['raw_observations']} == {pair['old'],pair['new']}
    markup = report._contract_performance_html(block)
    assert 'Единый договор: исходные карточки отдельно' in markup
    assert 'Финансовый источник, срок и общий прогноз между ними не выбраны' in markup
    assert 'data-raw-contract=\''+pair['old'] in markup
    assert 'data-raw-contract=\''+pair['new'] in markup


def test_management_pdf_keeps_both_source_dates_and_the_financial_gap(pair):
    from playwright.sync_api import sync_playwright
    from browser import chromium_or_skip
    from market_search import report_pdf
    import developaid_management_report as report
    import pymupdf
    confirm(pair)
    block = report.contract_risks(PROJECT, CUT)
    markup = report_pdf.document(report._contract_performance_html(block),
                                 style=report.REPORT_STYLE, title='Synthetic source choice')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.set_content(markup)
            pdf = page.pdf(format='A4', print_background=True)
        finally:
            browser.close()
    document = pymupdf.open(stream=pdf, filetype='pdf')
    text = '\n'.join(page.get_text() for page in document)
    assert 'SOURCE-A' in text and 'SOURCE-B' in text
    assert '06.11.2026' in text and '13.11.2026' in text
    assert 'Финансовый источник' in text and 'не выбраны' in text
    assert '25,3%' in text  # own summary source, not a logical total


@pytest.mark.parametrize('width', [390,1440])
def test_page_opens_each_raw_card_without_assigning_its_money_to_the_logical_parent(pair, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    confirm(pair)
    view = contracts.build(PROJECT, CUT, include_history=False)
    with browser_page(width) as (page,responses,errors):
        responses.data = view
        requested = []
        def documents(route):
            requested.append(route.request.post_data_json['contract_id'])
            route.fulfill(json={'ok':True,'documents':[],'removed':[]})
        page.route('**/monitor/contracts/documents', documents)
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsRows tr[data-contract-id]')).to_have_count(1)
        row = page.locator('#contractsRows tr[data-contract-id]')
        expect(row).to_contain_text('Финансовый источник')
        expect(row.locator('.term')).to_have_text('Уточнить срок')
        expect(row.locator('.contract-schedule')).to_have_text('Проверить исходные карточки')
        expect(row).to_contain_text('Финансовый источник, срок и общий прогноз между карточками не выбраны')
        row.locator('.contract-open').click()
        expect(page.locator('.contract-ownership-source')).to_be_visible()
        expect(page.locator('[data-raw-contract]')).to_have_count(2)
        page.locator('[data-raw-contract="'+pair['new']+'"]').click()
        expect(page.locator('[data-raw-contract="'+pair['new']+'"][aria-current="true"]')).to_be_visible()
        expect(page.locator('#contractDialogTitle')).to_contain_text('SOURCE-B')
        expect(page.locator('#contractCardSummary')).to_contain_text('1\u00a0500 ₽')
        expect(page.locator('#contractDocumentsMsg')).to_contain_text('Документы этого договора ещё не загружены')
        assert not errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert requested and requested[-1] == pair['new']
