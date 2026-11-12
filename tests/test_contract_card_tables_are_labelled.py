"""На телефоне таблицы карточки договора становятся карточками: у каждой графы видна её подпись.

Шапка таблицы на узком экране спрятана, поэтому подпись графы — это `data-label` ячейки,
выведенный через `td::before`. Проверяется отрисованная карточка с расчётом, графиком, связями,
планом, фактом и отклонением, собранная настоящим разбором документов.
"""
from __future__ import annotations

import pytest

import developaid_contract_fact as fact
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT
from tests.test_contract_fact_prices_ks_by_the_edition import REGISTER_ROW, card  # noqa: F401

UNLABELLED = '''() => [...document.querySelectorAll('#contractsDetails .contract-detail table.contract-table')]
    .flatMap(table => [...table.tBodies].flatMap(body => [...body.rows]))
    .flatMap(row => [...row.cells])
    .filter(cell => cell.offsetParent && cell.colSpan === 1 && cell.textContent.trim())
    .filter(cell => !getComputedStyle(cell, '::before').content.replace(/^none$|^normal$|^""$/, ''))
    .map(cell => cell.closest('details').querySelector('summary').textContent + ': ' + cell.textContent.trim().slice(0, 40))'''


def _open_every_table(page):
    page.evaluate("document.querySelectorAll('#contractsDetails details').forEach(d => d.open = true)")


@pytest.mark.parametrize("width", [390, 1440])
def test_every_cell_of_the_card_tables_names_its_column_on_the_phone(card, width):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    with browser_page(width) as (page, _, errors):
        _serve(page, [], cut="2026-02-04", acts=fact.acts(REGISTER_ROW))
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.locator("#contractDocuments .contract-control")).to_be_visible()
        _open_every_table(page)
        tables = page.locator("#contractsDetails .contract-detail table.contract-table")
        assert tables.count() >= 6, "расчёт, график, связи, план, факт и отклонение"
        if width == 390:
            assert page.evaluate(UNLABELLED) == []
            head = tables.first.locator("thead")
            assert head.evaluate("e => getComputedStyle(e).display") == "none"
        else:
            # На широком экране подписи не дублируют видимую шапку.
            assert tables.first.locator("thead").is_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert errors == []


def test_a_broken_connection_during_upload_says_the_file_may_be_kept(card):  # noqa: F811
    from playwright.sync_api import expect

    from test_monitor_cumulative_controls import browser_page
    from tests.test_contract_card_confirms_and_chooses_links import _serve
    with browser_page(1440) as (page, _, errors):
        _serve(page, [], cut="2026-02-04")
        page.route("**/monitor/contracts/document-upload", lambda route: route.abort())
        page.locator("#contractsTab").click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.locator("#contractDocuments .contract-document").first).to_be_visible()
        page.locator("#contractDocumentFile").set_input_files(
            {"name": "ДС5.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.7 synthetic"})
        page.locator("#contractDocumentUpload").click()
        expect(page.locator("#contractDocumentsMsg")).to_have_text(
            "Связь прервалась во время загрузки PDF. Файл мог сохраниться: откройте карточку договора заново "
            "и проверьте список документов, прежде чем загружать файл ещё раз.")
        expect(page.locator("#contractDocumentUpload")).to_be_enabled()


def test_a_file_that_is_no_pdf_is_refused_with_what_to_do(card):  # noqa: F811
    import developaid_contract_files as files
    from tests.test_contract_card_confirms_and_chooses_links import PROJECT, ROW
    with pytest.raises(files.ContractFilesProblem, match="Сохраните документ в PDF заново.*загрузите ещё раз"):
        files.store(PROJECT, ROW, "ДС.pdf", b"not a pdf")
    with pytest.raises(files.ContractFilesProblem, match="Сохраните документ в PDF заново.*загрузите ещё раз"):
        files.store(PROJECT, ROW, "ДС.pdf", b"%PDF-1.7 broken")
