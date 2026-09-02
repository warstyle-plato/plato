"""Двенадцать колонок КРТ либо помещаются, либо прокручиваются — третьего нет.

Владелец (01.09.2026): «скроллинга таблицы КРТ в бок нет, на компе невозможно
почти правые столбцы увидеть».

Обёртка таблицы стоит с `overflow:auto` — и этого недостаточно. Прокрутка
появляется, только когда таблице ТЕСНО: у `min-width:900px` двенадцать колонок
на рабочем столе умещались в отведённые ~1100 px, никакой прокрутки не
возникало, а колонки сжимались до нечитаемых. То есть «скролла нет» — верное
описание: его и не было, была давка.

Ширина — поведение вёрстки, и строкой в исходнике оно не доказывается: меряет
настоящий браузер.

Рядом вторая находка того же снимка: дата проекта решения печаталась без года
(«10 июня» вместо «10 июня 2025 г.»), а каталог держит документы нескольких
лет — год здесь часть даты, а не украшение.

Запуск: python3 -m pytest tests/test_the_krt_table_scrolls_sideways.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import ui  # noqa: E402

DESKTOPS = (1280, 1440, 1680)

ROWS = [
    {
        "slug": f"site-{i}",
        "name": f"Комплексное развитие территории по адресу улица Маршала Воробьева, вл. {i}",
        "okrug": "Северо-Западный административный округ",
        "district": "район Строгино",
        "status": "Планируемый",
        "area_ha": 10.24,
        "total_gfa_sqm": 323796,
        "housing_gfa_sqm": 294276,
        "jobs": 1200,
        "draft_decision_at": 1749513600,
        "draft_decision_url": "https://www.mos.ru/",
        "no_card": False,
    }
    for i in range(1, 9)
]


def _measure(tmp_path, width: int) -> dict:
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": width, "height": 900})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            tab.evaluate("()=>document.getElementById('tabKrt')?.click()")
            tab.evaluate("rows=>{state.krt=rows;state.krtFiltered=rows;renderKrt()}", ROWS)
            tab.wait_for_timeout(200)
            got = tab.evaluate(
                """()=>{
                  const wrap=document.querySelector('#krtPanel .tablewrap');
                  const heads=[...wrap.querySelectorAll('thead th')];
                  const clipped=[...wrap.querySelectorAll('td')]
                    .filter(c=>c.scrollWidth>c.clientWidth+1).length;
                  wrap.scrollLeft=wrap.scrollWidth;
                  const box=wrap.getBoundingClientRect();
                  const last=heads[heads.length-1].getBoundingClientRect();
                  return {
                    wrap:wrap.clientWidth,
                    content:wrap.scrollWidth,
                    overflow:getComputedStyle(wrap).overflowX,
                    columns:heads.length,
                    clipped:clipped,
                    lastRight:last.right,
                    boxRight:box.right,
                    doc:document.documentElement.scrollWidth,
                    win:innerWidth,
                  };
                }""")
            tab.close()
        finally:
            browser.close()
    return got


@pytest.mark.parametrize("width", DESKTOPS)
def test_every_column_is_reachable_on_a_desktop(tmp_path, width):
    got = _measure(tmp_path, width)
    assert got["columns"] == 12, "колонок стало другое число — пересчитать запас ширины"
    assert got["overflow"] in ("auto", "scroll"), \
        f"обёртка таблицы не прокручивается вбок: overflow-x={got['overflow']}"
    assert got["doc"] <= got["win"] + 1, \
        f"страница шириной {got['doc']} при окне {got['win']} — вбок едет она, а не таблица"
    assert got["lastRight"] <= got["boxRight"] + 1, \
        "последняя колонка не доезжает до края даже в конце прокрутки"
    assert got["content"] > got["wrap"], (
        f"на {width} px таблица {got['content']} px влезла в {got['wrap']} px — прокрутки не "
        "возникает, потому что двенадцать колонок сжаты по месту")
    assert got["clipped"] == 0, \
        f"на {width} px обрезано содержимое {got['clipped']} ячеек"


def test_the_date_of_a_draft_decision_carries_its_year():
    page = ui.auctions_page(None)
    assert "day:'numeric',month:'long',year:'numeric'" in page, \
        "дата проекта решения печатается без года, а каталог держит документы разных лет"


@pytest.mark.parametrize("width", (390, 430, 768))
def test_the_wide_table_does_not_push_the_phone_sideways(tmp_path, width):
    """Запас ширины у таблицы не имеет права стать шириной страницы.

    Ровно этим уже уезжала строка фильтров: `1fr` — это `minmax(auto,1fr)`, и
    минимум колонки равен содержимому. Прокручиваемая обёртка снимает этот
    минимум, но проверяется это браузером, а не рассуждением.
    """
    got = _measure(tmp_path, width)
    assert got["doc"] <= got["win"] + 1, (
        f"на {width} px страница шириной {got['doc']} — запас таблицы распёр её вбок")


# --- Полоса прокрутки сверху -------------------------------------------------
#
# Владелец (01.09.2026): «скролл в КРТ можно сверху сделать? листать 57 лотов
# вниз тяжело». Нижняя полоса лежит под всеми строками: чтобы подвинуть таблицу
# вбок, надо пролистать её вниз, подвинуть и вернуться наверх.
#
# Полоса сверху — зеркало настоящей, а не вторая прокрутка: ширину она берёт у
# самой таблицы, положение синхронизируется в обе стороны. Прокручивать нечего
# — полосы нет вовсе: пустая полоска над таблицей читается как поломка вёрстки.


def _mirror(tmp_path, width: int, rows) -> dict:
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": width, "height": 900})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            tab.evaluate("()=>document.getElementById('tabKrt')?.click()")
            tab.evaluate("r=>{state.krt=r;state.krtFiltered=r;renderKrt()}", rows)
            tab.wait_for_timeout(200)
            got = tab.evaluate(
                """()=>{
                  const bar=document.getElementById('krtScrollTop');
                  const wrap=document.getElementById('krtTableWrap');
                  const before=bar.getBoundingClientRect().top<wrap.getBoundingClientRect().top;
                  bar.scrollLeft=200; bar.dispatchEvent(new Event('scroll'));
                  const pushed=wrap.scrollLeft;
                  wrap.scrollLeft=40; wrap.dispatchEvent(new Event('scroll'));
                  return {hidden:bar.hidden, above:before, pushed:pushed,
                          pulled:bar.scrollLeft,
                          inner:bar.firstElementChild.getBoundingClientRect().width,
                          content:wrap.scrollWidth,
                          doc:document.documentElement.scrollWidth, win:innerWidth};
                }""")
            tab.close()
        finally:
            browser.close()
    return got


def test_the_top_bar_mirrors_the_table(tmp_path):
    got = _mirror(tmp_path, 1440, ROWS)
    assert got["hidden"] is False, "полосы сверху нет там, где таблица не помещается"
    assert got["above"] is True, "полоса оказалась не над таблицей"
    assert abs(got["inner"] - got["content"]) <= 2, \
        "ширина полосы не совпала с шириной таблицы — прокрутка врёт про размер"
    assert got["pushed"] == 200, "таблица не поехала за верхней полосой"
    assert got["pulled"] == 40, "верхняя полоса не поехала за таблицей"
    assert got["doc"] <= got["win"] + 1, "страница уехала вбок вслед за полосой"


def test_nothing_to_scroll_means_no_bar(tmp_path):
    """Пустая полоска над таблицей читается как поломка вёрстки.

    Таблица КРТ шире отведённого места при любом окне — запас в 1360 px стоит
    ради самих колонок, — поэтому случай «прокручивать нечего» достигается
    здесь снятием этого запаса, а не подбором ширины экрана.
    """
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1440, "height": 900})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            tab.evaluate("()=>document.getElementById('tabKrt')?.click()")
            tab.evaluate("r=>{state.krt=r;state.krtFiltered=r;renderKrt()}", ROWS)
            hidden = tab.evaluate(
                """()=>{
                  const table=document.querySelector('#krtTableWrap table');
                  table.style.tableLayout='fixed';
                  table.style.minWidth='0'; table.style.width='200px';
                  syncTopScroll();
                  return document.getElementById('krtScrollTop').hidden;
                }""")
            tab.close()
        finally:
            browser.close()
    assert hidden is True
