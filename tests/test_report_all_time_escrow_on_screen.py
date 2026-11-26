"""Настоящая страница сводки и печатный документ читают один DTO эскроу."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import developaid_management_report as report
from browser import chromium_or_skip
from test_report_all_time_escrow import END, LABEL, _kept, _row


def test_all_time_card_on_native_report_page_and_in_pdf(monkeypatch):
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import pymupdf
    from developaid_report_page import REPORT_PAGE
    from market_search import report_pdf

    monkeypatch.setattr(report.sales_store, "load", lambda *args: _kept([_row()]))
    built = report.build("Пустой синтетический", "week", END, sales_project="synthetic")
    rendered = report.render_html(built)
    document = report_pdf.document(rendered, style=report.REPORT_STYLE, title="Синтетическая сводка")
    errors, paths = [], []

    def respond(route):
        request = route.request
        url = urlsplit(request.url)
        assert url.hostname == "escrow-card.test"
        paths.append(url.path)
        if url.path == "/report":
            route.fulfill(content_type="text/html", body=REPORT_PAGE)
        elif url.path == "/monitor/report/projects":
            route.fulfill(json={"projects": [{"project": built["project"], "sales": {"sales_project": "synthetic"}}],
                                "sales_projects": ["synthetic"]})
        elif url.path == "/monitor/report/build":
            route.fulfill(content_type="application/json", body=json.dumps({"html": rendered}))
        elif url.path in {"/monitor/notes", "/monitor/report/mailing", "/monitor/legal", "/monitor/photos"}:
            route.fulfill(json={})
        else:
            route.abort()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            for width in (1280, 390):
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", respond)
                page.add_init_script("localStorage.setItem('plato_projects_key','synthetic-browser-key')")
                page.goto("http://escrow-card.test/report", wait_until="domcontentloaded")
                tile = page.locator("#reportBox .tile").filter(has=page.locator(".k", has_text=LABEL))
                tile.wait_for(state="visible")
                assert tile.count() == 1
                assert tile.locator(".v").inner_text() == "20,0 млн ₽"
                note = " ".join(tile.locator(".n").inner_text().split())
                assert "Ещё ожидается 60,0 млн ₽" in note
                assert "18.10.2026" in note and "не остаток банка" in note
                tile.scroll_into_view_if_needed()
                box = tile.bounding_box()
                assert box and box["width"] > 100 and box["x"] >= 0 and box["x"]+box["width"] <= width
                assert tile.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                labels = page.locator("#reportBox .tile .k").all_text_contents()
                assert next(i for i, text in enumerate(labels) if LABEL in text) > next(
                    i for i, text in enumerate(labels) if "На эскроу по продажам квартала" in text)
                page.close()
            printable = browser.new_page()
            printable.route("**/*", lambda route: route.abort())
            printable.set_content(document, wait_until="load")
            pdf = printable.pdf(format="A4", print_background=True)
            printable.close()
        finally:
            browser.close()
    assert not errors
    assert "/monitor/report/build" in paths
    with pymupdf.open(stream=pdf, filetype="pdf") as printed:
        text = " ".join(" ".join(page.get_text() for page in printed).split())
        assert LABEL.casefold() in text.casefold()
        assert "20,0 млн ₽" in text and "Ещё ожидается 60,0 млн ₽" in text
        assert "18.10.2026" in text and "не остаток банка" in text
