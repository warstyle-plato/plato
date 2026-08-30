"""Свод продаж уходит в PDF — тем же, что на экране.

Отчёт о продажах жил только на экране: печатать его было нечем, а
`/cabinet/report.pdf` печатал отчёт о РЫНКЕ. Управленцу нужен документ, и
документ этот собирается не второй вёрсткой: собранная заново, она разошлась бы
с экранной, и мы получили бы два достоверных на вид отчёта о продажах с разными
числами — ровно то, что уже ловилось в боте, в отчёте и в книге.

Разница между экраном и бумагой ровно в трёх вещах, и каждая — про бумагу:
кнопки и поле вопроса не текст; переключатель меры — кнопки, а не число (какая
мера показана, сказано подписью под графиком); свёрнутая таблица в документе —
таблица отсутствующая, раскрыть её читателю нечем.

И печать объявлена ОДИН раз на обе поверхности кабинета: две копии разошлись бы
на том, что чинят по одной, — на откате к печати браузера и на тексте отказа.

Запуск: python3 -m pytest tests/test_the_sales_report_prints_itself.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search.cabinet import cabinet_page, cabinet_style  # noqa: E402


def page() -> str:
    return cabinet_page("sales")


def script() -> str:
    return max(re.findall(r"<script[^>]*>(.*?)</script>", page(), re.S), key=len)


def test_the_sales_card_has_a_button_that_is_not_printed() -> None:
    body = page()
    assert 'id="salespdf"' in body, "свод продаж печатать нечем"
    assert 'id="salespdfstate"' in body, "отказ печати некуда доложить"
    head = body[body.index('id="salespdf"') - 400:body.index('id="salespdf"') + 200]
    assert "noprint" in head, "кнопка печати печаталась бы вместе с отчётом"


def test_printing_is_declared_once_for_both_surfaces() -> None:
    """Рынок и продажи печатают разное содержимое, но одним путём."""
    body = script()
    assert "async function printPdf(" in body
    assert body.count("'/cabinet/report.pdf'") == 1, "вторая копия печати разойдётся с первой"
    for caller in ("on('#pdf','click'", "$('#salespdf').onclick="):
        start = body.index(caller)
        assert "printPdf({" in body[start:start + 700], f"{caller} печатает сам по себе"


def test_the_paper_differs_from_the_screen_in_three_named_things() -> None:
    body = script()
    start = body.index("function salesPrintHtml(){")
    fn = body[start:body.index("\n}", start)]
    assert ".noprint" in fn and "remove()" in fn, "кнопки и поле вопроса печатались бы"
    assert ".switch" in fn, "переключатель меры печатался бы кнопками"
    assert "details" in fn and "setAttribute('open'" in fn, \
        "свёрнутая таблица в документе — отсутствующая таблица"
    assert "cloneNode(true)" in fn, "экран правится под печать — на экране пропало бы то же самое"


def test_the_conversation_with_platon_does_not_go_to_paper() -> None:
    body = script()
    ask = body[body.index("Спросить Платона Сергеевича о продажах") - 200:]
    assert "noprint" in ask[:200], "поле ввода на бумаге не текст"


def test_a_section_of_the_screen_is_a_page_of_the_document() -> None:
    """Раздел, начатый на дне листа, рвёт график, таблицу и вывод по разным
    страницам — а таблица на чужой странице читается как чужая."""
    style = cabinet_style()
    assert ".salesblock{break-before:page;page-break-before:always}" in style
    assert ".salesblock:first-of-type{break-before:auto" in style, \
        "перед первым разделом стоит шапка, и пустой лист под ней был бы пустым листом"
    assert ".salesnav{display:none !important}" in style, "якорь на бумаге никуда не ведёт"


def _payload() -> dict:
    import importlib

    from market_search import contracting

    got = importlib.import_module("test_contracting_summary")._summary()
    got["sources"] = [{"kind": "contracting", "name": "контрактация ЦФ",
                       "at": "2026-08-20T10:00:00"}]
    got["plans"] = contracting.plan_comparison(got)
    got["conclusions"] = contracting.conclusions(got)
    got["pool"] = contracting.pool_progress(got, [], None, None)
    return got


def test_the_printed_markup_is_the_screen_without_its_tools(tmp_path) -> None:
    """Проверяется настоящим браузером: `cloneNode` и `details` — поведение DOM,
    и строкой в исходнике оно не доказывается. Без Chromium — пропуск, а не
    зелёный прогон на пустом месте."""
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    from market_search import report_pdf

    body = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "cabinet.html"
    file.write_text(body, encoding="utf-8")

    errors: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка кабинета
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(file.as_uri())
            printed = tab.evaluate(
                "(d)=>{renderSales(d); return {print:salesPrintHtml(),"
                " screen:document.querySelector('#sales .card').innerHTML}}", _payload())
        finally:
            browser.close()

    assert not errors, f"страница упала: {errors[:2]}"
    paper, screen = printed["print"], printed["screen"]
    assert "Спросить Платона" in screen and "Спросить Платона" not in paper
    assert "salespdf" in screen and "salespdf" not in paper
    assert 'class="switch"' not in paper
    assert re.search(r"<details(?![^>]*open)", paper) is None, "в документе осталось раскрытие"
    assert "Продажи проекта" in paper and "Источники:" in paper
    assert paper.count('class="salesblock"') >= 3, "разделы до бумаги не доехали"

    # И документ действительно печатается: раздел = страница, поэтому страниц не
    # меньше, чем разделов.
    sections = paper.count('class="salesblock"')
    try:
        raw = report_pdf.render(
            report_pdf.document(paper, style=cabinet_style(), title="Продажи"),
            footer="Продажи · свод продаж DevelopAid")
    except report_pdf.PdfUnavailable as exc:
        pytest.skip(f"печать недоступна: {exc}")
    assert raw[:4] == b"%PDF"
    pages = raw.count(b"/Type /Page\n") + raw.count(b"/Type /Page/") + raw.count(b"/Type /Page ")
    assert pages >= sections, f"страниц {pages} при {sections} разделах"
