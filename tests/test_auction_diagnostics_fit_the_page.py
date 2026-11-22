"""The production source report stays readable without widening a phone.

Uses the public production response from 16 November 2026, with per-lot
collector bookkeeping removed. The real refresh handler renders the report.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from auction_search import ui
from browser import chromium_or_skip


@pytest.mark.timeout(120)
def test_source_details_and_krt_reconciliation_fit_loaded_page(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    chrome = chromium_or_skip()
    payload = json.loads((Path(__file__).parent / "fixtures" /
                          "auction_diagnostics_20261116.json").read_text())
    html = ui.auctions_page(None)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            for width in (320, 375, 390, 1280):
                page = browser.new_page(viewport={"width": width, "height": 844})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def respond(route):
                    path = urlsplit(route.request.url).path
                    if path == "/auctions":
                        route.fulfill(content_type="text/html", body=html)
                    else:
                        data = payload if path == "/auctions/discover" else {}
                        route.fulfill(content_type="application/json", body=json.dumps(data))

                def refresh():
                    button = page.locator("#refresh")
                    button.click()
                    expect(button).to_be_enabled()

                page.route("**/*", respond)
                page.goto("http://auction.test/auctions")
                refresh()
                report = page.locator("#coverage")
                expect(report).to_be_visible()
                expect(report).to_contain_text("Сбор неполный")
                expect(report).to_contain_text("Roseltorg")
                details = report.locator("details")
                assert details.count() == 1
                assert details.get_attribute("open") is None
                # Details are present, but do not bury the actual auction list.
                assert report.bounding_box()["height"] < 350
                expect(report.locator(".foldbody")).to_be_hidden()
                audit = page.locator("#krtReconciliation")
                audit_details = audit.locator("details")
                assert audit_details.get_attribute("open") is None
                assert audit.bounding_box()["height"] < 350
                table = page.locator("#krtReconciliation table")
                expect(table.locator("tbody tr")).to_have_count(payload["krt_reconciliation"]["expected"])
                page.screenshot(path=str(tmp_path / f"auction-diagnostics-{width}.png"), full_page=True)
                audit_details.locator("summary").click()
                expect(table).to_be_visible()
                for expanded in (False, True):
                    if expanded:
                        details.locator("summary").click()
                        expect(report.locator(".foldbody")).to_be_visible()
                        expect(report.locator(".foldbody")).to_contain_text(
                            "не прочитано карточек 42 из 106")
                    size = page.evaluate("""() => ({
                        doc: document.documentElement.scrollWidth,
                        viewport: innerWidth,
                        table: document.querySelector('#krtReconciliation table').getBoundingClientRect().right
                    })""")
                    assert size["doc"] <= size["viewport"] + 1, size
                    assert size["table"] <= size["viewport"], size
                details.locator("summary").click()
                refresh()
                expect(report.locator("details")).to_have_count(1)
                assert report.locator("details").get_attribute("open") is None
                expect(table.locator("tbody tr")).to_have_count(payload["krt_reconciliation"]["expected"])
                if width == 320:
                    original_coverage = payload["coverage"]
                    # A failure must remain visible even without a top-level reason.
                    for failure in ({"unread_cards": 1},
                                    {"sections": [{"name": "КРТ", "reason": "HTTP 429"}]},
                                    {"privatization_lists": [{"name": "Земля", "reason": "HTTP 429"}]}):
                        payload["coverage"] = [{"source": "Площадка с ошибкой", **failure}]
                        refresh()
                        expect(report).to_contain_text("Сбор неполный")
                        expect(report).to_contain_text("Площадка с ошибкой")
                        expect(report.locator(".foldbody")).to_be_hidden()
                    payload["coverage"] = [{"source": "Проверенный источник", "kept": 0}]
                    refresh()
                    assert "Сбор неполный" not in report.inner_text()
                    payload["coverage"] = original_coverage
                    first_row = payload["krt_reconciliation"]["rows"][0].copy()
                    payload["krt_reconciliation"]["included"] -= 1
                    payload["krt_reconciliation"]["rows"][0]["reason"] = "Карточка не прочитана: HTTP 429"
                    payload["krt_reconciliation"]["rows"][0]["state"] = "unread"
                    refresh()
                    expect(table).to_be_visible()
                    expect(table).to_contain_text("Карточка не прочитана: HTTP 429")
                    payload["krt_reconciliation"]["included"] += 1
                    payload["krt_reconciliation"]["rows"][0] = first_row
                page.locator("#tabKrt").click()
                expect(page.locator("#krtReconciliation")).to_be_hidden()
                page.locator("#tabAuctions").click()
                expect(page.locator("#krtReconciliation")).to_be_visible()
                assert not errors, errors
                page.close()
        finally:
            browser.close()
