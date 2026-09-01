"""Меню торгов помещается в телефон, а не уезжает вбок.

Снимок владельца (01.09.2026): строка фильтров КРТ обрезана правым краем, под
ней пустое поле — страница шире экрана и едет горизонтально. Замер это
подтвердил: на 390 px ширина страницы была 1165 px.

Причин было две, и вторая сильнее первой. Колонки заданы как `1fr`, а это
`minmax(auto,1fr)` — «не уже своего содержимого»: длинная подпись в `select`
распирает колонку. А у строки КРТ раскладка стояла ИНЛАЙНОВЫМ стилем, который
сильнее любого медиазапроса, — поэтому на телефоне у неё оставалось пять
колонок при любом CSS.

Проверяется настоящим браузером: ширина страницы — это поведение вёрстки, и
строкой в исходнике оно не доказывается.

Запуск: python3 -m pytest tests/test_the_auctions_page_fits_a_phone.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

PHONES = (390, 430)


def test_the_layout_is_not_pinned_by_an_inline_style():
    """Инлайновая сетка сильнее медиазапроса — значит её там быть не должно."""
    page = ui.auctions_page(None)
    assert 'style="grid-template-columns:2fr repeat(4,1fr)"' not in page, \
        "раскладка прибита инлайном — телефонные правила её не увидят"
    assert '.filters.wide{grid-template-columns:' in page, \
        "раскладка объявлена не классом, и переопределить её нечем"
    assert "@media(max-width:640px)" in page, "правил для телефона нет вовсе"


def test_the_page_does_not_scroll_sideways_on_a_phone(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    seen: dict[int, dict] = {}
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            for width in PHONES:
                tab = browser.new_page(viewport={"width": width, "height": 844})
                tab.goto(file.as_uri())
                tab.wait_for_timeout(300)
                tab.evaluate("()=>document.getElementById('tabKrt')?.click()")
                tab.wait_for_timeout(200)
                seen[width] = tab.evaluate(
                    "()=>({doc:document.documentElement.scrollWidth,win:innerWidth,"
                    "filters:document.querySelector('#krtPanel .filters')?.scrollWidth||0})")
                tab.close()
        finally:
            browser.close()

    for width, got in seen.items():
        assert got["doc"] <= got["win"] + 1, (
            f"на {width} px страница шириной {got['doc']} — уезжает вбок")
        assert 0 < got["filters"] <= width, (
            f"на {width} px строка фильтров {got['filters']} px")
