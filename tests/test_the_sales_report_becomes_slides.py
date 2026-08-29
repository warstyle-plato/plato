"""Слайд — это раздел отчёта о продажах, а не его пересказ.

«Выгрузка отчёта в PDF или PPT для презентации маркетингу… страниц PDF = слайд
или раздел PDF = слайд» (владелец, 27.08.2026). Разделы и страницы у нас
совпадают — раздел свода печатается со своей страницы, — поэтому ответ один:
слайд отвечает разделу.

Собрать колоду «по тем же данным» значило бы завести вторую реализацию отчёта о
продажах. Она разошлась бы с экраном молча, и обе выглядели бы верными — это
уже случалось в боте, в отчёте о рынке и в книге. Поэтому на слайд уходит
СНИМОК того же раздела, снятый с той самой разметки, которой печатается PDF, а
в самом сборщике колоды нет ни одного числа.

Запуск: python3 -m pytest tests/test_the_sales_report_becomes_slides.py -q
"""

from __future__ import annotations

import io
import re
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search import sales_deck  # noqa: E402
from market_search.cabinet import cabinet_page, cabinet_style  # noqa: E402


def script() -> str:
    return max(re.findall(r"<script[^>]*>(.*?)</script>", cabinet_page(), re.S), key=len)


def _png(width: int, height: int) -> bytes:
    """Настоящий PNG нужного размера: сборщик читает размер из заголовка."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + kind + data
                + zlib.crc32(kind + data).to_bytes(4, "big"))

    head = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def test_the_deck_builder_touches_no_number_of_its_own() -> None:
    """Первое «просто посчитать долю» здесь — это вторая экономика продаж.

    Модуль не знает ни одного поля свода: он получает снятые разделы и
    складывает их в файл. Ловится это тем, что имена величин в нём не
    встречаются вовсе.
    """
    body = (ROOT / "market_search" / "sales_deck.py").read_text(encoding="utf-8")
    for name in ("amount", "escrow", "units", "contracts", "summarise",
                 "conclusions", "by_channel", "pool"):
        assert name not in body, f"сборщик колоды знает про «{name}» — это второй счёт"
    assert "contracting" not in body


def test_the_dependency_is_declared_where_the_image_reads_it() -> None:
    """Библиотека, которой нет в образе, — это отказ на проде и зелёный набор."""
    assert "python-pptx" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_a_slide_carries_the_section_picture_its_title_and_its_conclusion() -> None:
    pptx = pytest.importorskip("pptx")

    pages = [
        {"title": "Динамика", "png": _png(1180, 600), "note": "Продажи выросли."},
        {"title": "Каналы продаж", "png": _png(1180, 1900), "note": "Брокеры — 48,3%."},
        {"title": "На чём посчитано", "lines": ["Источники: контрактация ЦФ — 2026-08-20."]},
    ]
    raw = sales_deck.build(pages, title="Продажи — Тестовый ЖК",
                           subtitle="срез 2026-08-20", footer="DevelopAid")
    deck = pptx.Presentation(io.BytesIO(raw))
    slides = list(deck.slides)
    # Титул плюс по слайду на раздел: слайд отвечает разделу.
    assert len(slides) == len(pages) + 1
    assert "Продажи — Тестовый ЖК" in slides[0].shapes[0].text_frame.text
    for page, slide in zip(pages, slides[1:]):
        texts = [s.text_frame.text for s in slide.shapes if s.has_text_frame]
        assert page["title"] in texts[0]
        if page.get("png"):
            pictures = [s for s in slide.shapes if s.shape_type == 13]
            assert len(pictures) == 1, "раздел без картинки — это раздел без содержимого"
            shot = pictures[0]
            # Высокий раздел ужимается по высоте и не вылезает за лист: обрезанная
            # таблица читается как таблица, которая кончилась.
            assert shot.left >= 0 and shot.top >= 0
            assert shot.left + shot.width <= deck.slide_width
            assert shot.top + shot.height <= deck.slide_height
        else:
            assert any(page["lines"][0] in text for text in texts)
        if page.get("note"):
            assert slide.notes_slide.notes_text_frame.text == page["note"]


def test_a_shot_that_is_not_a_picture_is_refused_not_stretched() -> None:
    with pytest.raises(sales_deck.DeckUnavailable):
        sales_deck._png_size(b"not a png at all, honestly")


def test_nothing_to_show_is_said_out_loud() -> None:
    with pytest.raises(sales_deck.DeckUnavailable):
        sales_deck.build([], title="Продажи", subtitle="", footer="")


def test_the_button_sends_the_same_markup_as_the_pdf() -> None:
    """Две сборки одной колоды разойдутся — значит разметка одна и та же."""
    body = script()
    assert 'id="salesppt"' in cabinet_page()
    start = body.index("$('#salesppt').onclick=")
    handler = body[start:start + 2200]
    assert "salesPrintHtml()" in handler, "презентация собиралась бы из другой разметки"
    assert "'/cabinet/sales.pptx'" in handler
    # Отката у презентации нет: браузер её не соберёт. Значит причина называется.
    assert "Презентация не собралась" in handler
    assert "window.print()" not in handler


def test_the_route_refuses_an_empty_body_with_a_reason(tmp_path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    app = FastAPI()
    install(app)
    client = TestClient(app)
    client.post("/cabinet/login", content="key=stand-key-2026",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False)

    answer = client.post("/cabinet/sales.pptx", json={"html": "   "})
    assert answer.status_code == 422, answer.text
    assert "пуст" in answer.json()["detail"]

    # А закрытый кабинет отвечает про кабинет, а не про пустой свод: причина
    # отказа обязана быть той, что есть на самом деле.
    monkeypatch.delenv("MARKET_CABINET_KEY", raising=False)
    closed = TestClient(app).post("/cabinet/sales.pptx", json={"html": "<b>x</b>"})
    assert closed.status_code == 503 and "Кабинет" in closed.json()["detail"]


def test_the_sections_of_the_screen_become_the_slides_of_the_deck(tmp_path) -> None:
    """Проверяется настоящим браузером: снимок раздела — это поведение DOM.

    Без Chromium — пропуск, а не зелёный прогон на пустом месте: колоду в CI
    собрать нечем, и делать вид, что собрали, нельзя.
    """
    pytest.importorskip("pptx")
    play = pytest.importorskip("playwright.sync_api")
    import importlib

    import browser_launch

    from market_search import contracting

    got = importlib.import_module("test_contracting_summary")._summary()
    got["sources"] = [{"kind": "contracting", "name": "контрактация ЦФ",
                       "at": "2026-08-20T10:00:00"}]
    got["plans"] = contracting.plan_comparison(got)
    got["conclusions"] = contracting.conclusions(got)
    got["pool"] = contracting.pool_progress(got, [], None, None)

    file = tmp_path / "cabinet.html"
    file.write_text(cabinet_page().replace("__DEVELOPAID_VERSION__", "test"), encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.goto(file.as_uri())
            markup = tab.evaluate("(d)=>{renderSales(d); return salesPrintHtml()}", got)
        finally:
            browser.close()

    sections = markup.count('class="salesblock"')
    assert sections >= 3
    try:
        pages = sales_deck.shots(markup, style=cabinet_style())
    except sales_deck.DeckUnavailable as exc:
        pytest.skip(f"снять разделы нечем: {exc}")
    titles = [page["title"] for page in pages]
    assert titles[0] == "Ключевые числа", "колода начинается с чисел, а не с середины"
    assert titles[-1] == "На чём посчитано", "оговорка осталась бы на экране"
    assert len(pages) == sections + 2
    assert all(page.get("png") or page.get("lines") for page in pages)
    raw = sales_deck.build(pages, title="Продажи", subtitle="срез", footer="DevelopAid")
    assert raw[:2] == b"PK", "это не .pptx"
