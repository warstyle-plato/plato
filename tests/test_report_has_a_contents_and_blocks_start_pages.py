"""Содержание в начале сводки; каждый блок документа — с новой страницы.

«А в начало содержание? в пдф блоки финансирование продажи бюджет и споры и
тд начинать с новой страницы?» (владелец, 22.10.2026). Содержание — ссылки на
блоки в порядке владельца; в документе каждый блок начинается с новой
страницы, на странице /report страница не рвётся. «Споры и претензии» —
свой блок, а не подраздел общей информации.

Запуск: python3 -m pytest tests/test_report_has_a_contents_and_blocks_start_pages.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_management_report_analytics import _full  # noqa: E402

import developaid_management_report as report  # noqa: E402
import developaid_monitor as monitor  # noqa: E402
from developaid_report_page import REPORT_PAGE  # noqa: E402

TITLES = ["Главное за период", "Стройка", "Продажи", "Финансирование", "Погашение кредитов",
          "Бюджет месяца",
          "Споры и претензии", "Общая информация"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))


def test_the_contents_lead_and_name_every_block_in_order():
    page = report.render_html(_full())
    toc = page[page.index("<ol class='toc'>"):page.index("</ol>")]
    assert page.index("<ol class='toc'>") < page.index("<div class='tiles'>")
    assert re.findall(r"<a href='#block-(\w+)'>([^<]+)</a>", toc) == [
        ("main", "Главное за период"), ("build", "Стройка"), ("sales", "Продажи"),
        ("funding", "Финансирование"), ("credit", "Погашение кредитов"),
        ("budget", "Бюджет месяца"),
        ("legal", "Споры и претензии"), ("info", "Общая информация")]
    headings = re.findall(r"<h2 class='block(?: first)?' id='block-(\w+)'>([^<]+)</h2>", page)
    assert "<h2 class='block first' id='block-main'>" in page
    assert [title for _, title in headings] == TITLES
    assert [key for key, _ in headings] == re.findall(r"#block-(\w+)", toc)
    # Споры — свой блок, не подраздел «Общей информации».
    assert "<h3>Споры и претензии</h3>" not in page
    assert page.index(">Споры и претензии</h2>") < page.index(">Общая информация</h2>")
    # Пустая сводка — те же восемь блоков: без данных блок называет причину, а не исчезает.
    empty = report.render_html(report.build("Пусто", "week", "2026-10-18"))
    assert len(re.findall(r"<h2 class='block", empty)) == 8


def test_in_the_document_every_block_starts_a_page_and_the_screen_does_not_break():
    from browser import chromium_or_skip

    chrome = chromium_or_skip()
    pymupdf = pytest.importorskip("pymupdf")
    from playwright.sync_api import sync_playwright

    from market_search import report_pdf

    body = report.render_html(_full())
    document = report_pdf.document(body, style=report.REPORT_STYLE, title="Проба")
    try:
        raw = report_pdf.render(document, footer="Проба", executable_path=str(chrome))
    except report_pdf.PdfUnavailable as exc:
        pytest.skip(f"Chromium недоступен: {exc}")
    pdf = pymupdf.open(stream=raw, filetype="pdf")
    first = pdf[0].get_text()
    for title in TITLES:
        assert title in first, f"в содержании на первой странице нет «{title}»"
    # «Главное» — на первой странице под плитками, как решил владелец.
    assert any(rect.y0 > 120 for rect in pdf[0].search_for("Главное за период"))
    # Заголовок каждого следующего блока — первая строка своей страницы, у каждого своя.
    seen: list[int] = [0]
    for title in TITLES[1:]:
        hits = [(index, rect) for index, page in enumerate(pdf)
                for rect in page.search_for(title) if rect.y0 < 120 and rect.height > 9]
        hits = [hit for hit in hits if hit[0] not in seen]
        assert hits, f"блок «{title}» не начинает страницу"
        page_index, rect = hits[0]
        top = min(block[1] for block in pdf[page_index].get_text("blocks") if block[4].strip())
        assert rect.y0 <= top + 1, f"«{title}» на стр. {page_index + 1} не первый на странице"
        seen.append(page_index)
    assert seen == sorted(seen) and len(set(seen)) == len(TITLES)
    assert seen[1] == 1, "«Стройка» должна открывать вторую страницу"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page(viewport={"width": 1100, "height": 900})
            tab.route("**/*", lambda route: route.fulfill(status=200, body="{}",
                                                           content_type="application/json"))
            tab.set_content(REPORT_PAGE)
            tab.evaluate("html => { document.getElementById('reportBox').innerHTML = html; "
                         "document.getElementById('privateArea').classList.remove('hidden') }", body)
            # На экране разрыв страницы ничего не значит, а ссылка содержания ведёт к блоку.
            assert tab.evaluate("getComputedStyle(document.querySelector('#reportBox h2.block'))"
                                ".breakBefore") in {"auto", ""}
            tab.click("#reportBox ol.toc a[href='#block-funding']")
            top = tab.evaluate("document.getElementById('block-funding').getBoundingClientRect().top")
            assert -2 <= top <= 40, f"после клика по содержанию блок не вверху экрана: {top}"
        finally:
            browser.close()
