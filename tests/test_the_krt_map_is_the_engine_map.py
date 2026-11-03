"""Карта КРТ — живая, и она движковая, а не вторая своя.

Владелец (01.09.2026): «карта у нас нормальная теперь или такая же статичная?».
Была статичная: одна серверная склейка `/land/basemap` картинкой — ни
увеличения, ни перетаскивания. Тайловая карта у сервиса при этом есть давно и
живёт в `PAGE`.

Скопировать её было нельзя по той же причине, по которой нет копии `VERSION`:
копию негде обновлять. А разошедшиеся проекции кладут контур рядом с подложкой
— и выглядит это как неточность источника, а не как наша ошибка. Поэтому код
вынимается из `PAGE` по именам: функция — контракт, она либо есть, либо её нет.

Печатный кадр при этом живая карта не подменяет: неподвижная картинка уходит в
отчёт, а живая отвечает на другой вопрос — «что вокруг».

Запуск: python3 -m pytest tests/test_the_krt_map_is_the_engine_map.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import land_map, ui  # noqa: E402

SITES = [
    {"slug": "site-a", "name": "Маршала Воробьева ул., вл. 12", "okrug": "СЗАО",
     "district": "Строгино", "status": "Планируемый", "area_ha": 10.24,
     "rings_merc": [[[4180000, 7515000], [4180600, 7515000],
                     [4180600, 7515600], [4180000, 7515600]]]},
    {"slug": "site-b", "name": "Молдавская ул., вл. 3-5", "okrug": "ЗАО",
     "district": "Кунцево", "status": "В реализации", "area_ha": 4.1,
     "rings_merc": [[[4172000, 7509000], [4172400, 7509000],
                     [4172400, 7509400], [4172000, 7509400]]]},
]


def _core():
    import main_legacy
    return main_legacy


def test_the_kit_is_lifted_from_the_page_and_not_copied():
    core = _core()
    script = land_map.script(core)
    for name in land_map.FUNCTIONS:
        assert f"function {name}(" in script, f"{name} не вынута из PAGE"
    for name in land_map.CONSTANTS:
        assert name in script
    # Копии в модуле нет: он умеет только доставать.
    source = (ROOT / "auction_search" / "land_map.py").read_text(encoding="utf-8")
    assert "20037508" not in source, "число мира скопировано — копию негде обновлять"
    assert "/land/tiles/" not in source, "адрес тайлов скопирован второй раз"


def test_a_missing_piece_is_a_breakage_not_a_silent_fallback():
    class Stub:
        PAGE = "function landMapScale(z){return 1}"

    with pytest.raises(land_map.MissingPiece):
        land_map.script(Stub())


def test_without_the_engine_the_page_says_so_instead_of_pretending():
    page = ui.auctions_page(None)
    assert "__DEVELOPAID_LAND_MAP" not in page, "плейсхолдер остался строкой на экране"
    assert "Живая карта не подключена" in page, \
        "без движка кнопка просто исчезает — это неотличимо от поломки"


def test_the_assembled_page_carries_the_engine_map():
    page = ui.auctions_page(_core())
    assert "__DEVELOPAID_LAND_MAP" not in page
    assert "function openLandMap(" in page and 'id="landMapDialog"' in page
    assert "/land/tiles/" in page, "тайлов на странице нет — карта осталась картинкой"
    # Своей проекции у страницы торгов нет.
    body = page[page.index("function openKrtLiveMap("):]
    body = body[:body.index("\nfunction ")]
    assert "landMapScale" not in body and "20037508" not in body, \
        "у карты КРТ завелась вторая проекция"


def test_the_still_frame_is_kept_on_purpose():
    """Живая карта не подменяет печатный кадр — он уходит в отчёт."""
    page = ui.auctions_page(_core())
    assert "/land/basemap?" in page, "неподвижный кадр исчез вместе с правкой"
    assert "неподвижен намеренно" in page, "почему кадр не двигается — не сказано"


def test_the_live_map_opens_zooms_and_asks_for_tiles(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(_core()), encoding="utf-8")
    asked: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.on("request", lambda r: asked.append(r.url))
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            tab.evaluate("sites=>openKrtLiveMap(sites)", SITES)
            tab.wait_for_timeout(300)
            first = tab.evaluate(
                "()=>({open:document.getElementById('landMapDialog').style.display,"
                "shapes:document.querySelectorAll('#landMapStage path[data-pick]').length,"
                "zoom:LAND_MAP.zoom,cx:LAND_MAP.cx})")
            tab.evaluate("()=>landMapZoomBy(1)")
            tab.wait_for_timeout(200)
            zoomed = tab.evaluate("()=>LAND_MAP.zoom")
            tab.evaluate("()=>{landMapDown({clientX:600,clientY:400,pointerId:1,"
                         "currentTarget:{setPointerCapture(){}}});"
                         "landMapMove({clientX:500,clientY:400});landMapUp()}")
            moved = tab.evaluate("()=>LAND_MAP.cx")
            tab.close()
        finally:
            browser.close()

    assert first["open"] == "flex", "окно карты не открылось"
    assert first["shapes"] == len(SITES), "контуры площадок на живую карту не попали"
    assert zoomed == first["zoom"] + 1, "увеличение не работает"
    assert moved != first["cx"], "карта не перетаскивается"
    tiles = [url for url in asked if re.search(r"/land/tiles/\d+/\d+/\d+\.png", url)]
    assert tiles, "тайлы не запрашивались — подложка осталась одной картинкой"


def test_a_click_on_a_site_opens_its_card(tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(_core()), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            picked = tab.evaluate(
                """sites=>{
                  window.__picked=null;
                  const real=window.selectKrt;
                  window.selectKrt=row=>{window.__picked=row&&row.slug};
                  state.krt=sites.map(s=>({slug:s.slug,name:s.name,status:s.status}));
                  openKrtLiveMap(sites);
                  const node=document.querySelector('#landMapStage path[data-pick]');
                  LAND_MAP.moved=0;
                  landMapClick({target:node});
                  window.selectKrt=real;
                  return {picked:window.__picked,
                          closed:document.getElementById('landMapDialog').style.display};
                }""", SITES)
            tab.close()
        finally:
            browser.close()
    assert picked["picked"] == SITES[0]["slug"], "щелчок по площадке не открыл её карточку"
    assert picked["closed"] == "none", "окно карты осталось поверх открытой карточки"
