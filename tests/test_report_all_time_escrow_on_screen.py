"""The real report PAGE and printed HTML show the same canonical cash pair."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

import developaid_management_report as report
from browser import chromium_or_skip
from test_report_all_time_escrow import LABEL, _built


def test_ready_cloud_pair_on_native_page_and_printed_document():
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import pymupdf
    from developaid_report_page import REPORT_PAGE
    from market_search import report_pdf

    built = _built()
    rendered = report.render_html(built)
    document = report_pdf.document(rendered, style=report.REPORT_STYLE, title="Синтетическая сводка")
    errors = []

    def respond(route):
        url = urlsplit(route.request.url)
        assert url.hostname == "escrow-total.test"
        if url.path == "/report":
            route.fulfill(content_type="text/html", body=REPORT_PAGE)
        elif url.path == "/monitor/report/projects":
            route.fulfill(json={"projects": [{"project": built["project"]}], "sales_projects": []})
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
                page.goto("http://escrow-total.test/report", wait_until="domcontentloaded")
                tile = page.locator("#reportBox .tile").filter(has=page.locator(".k", has_text=LABEL))
                tile.wait_for(state="visible")
                assert tile.count() == 1 and tile.locator(".v").inner_text() == "20,0 млн ₽"
                note = " ".join(tile.locator(".n").inner_text().split())
                assert "Ещё ожидается 30,0 млн ₽" in note and "Источник загружен 23.11.2026" in note
                assert "не остаток банка после раскрытий" in note
                tile.scroll_into_view_if_needed()
                box = tile.bounding_box()
                assert box and box["x"] >= 0 and box["x"]+box["width"] <= width
                assert tile.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                page.close()
            page = browser.new_page()
            page.route("**/*", lambda route: route.abort())
            page.set_content(document, wait_until="load")
            pdf = page.pdf(format="A4", print_background=True)
            page.close()
        finally:
            browser.close()
    assert not errors
    with pymupdf.open(stream=pdf, filetype="pdf") as printed:
        text = " ".join(" ".join(page.get_text() for page in printed).split())
        assert LABEL.casefold() in text.casefold()
        assert "20,0 млн ₽" in text and "Ещё ожидается 30,0 млн ₽" in text
        assert "Источник загружен 23.11.2026" in text
