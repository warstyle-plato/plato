"""Развёрнутая карта: контур обязан лежать на подложке, а метр — быть метром.

Миниатюра участка отвечает на «как выглядит», но подвинуть её нельзя: сервер
отдал ровно тот bbox, о котором его попросили. Развёрнутая карта тянет тайлы
поштучно и позволяет посмотреть окружение (решение владельца, 27.08.2026).

Здесь закреплено то, что ломается молча:

- **клиент и сервер считают пиксель одной формулой.** Тайлы кладутся по
  `landMapWorldPx/Py`, а серверная склейка `_basemap_png` — по своей паре
  px/py. Разойдись они на слагаемое — контур встанет рядом с подложкой, и
  выглядеть это будет как неточность ЕГРН, а не как наша ошибка;
- **проекция и обратный ход — взаимно обратные.** На них держатся и перенос
  карты пальцем, и линейка: точка под курсором обязана вернуться в себя;
- **меркаторный метр — не метр земли.** Он растянут на 1/cos(широты), и на
  широте Москвы линейка без пересчёта врёт почти вдвое;
- **тайл спрашивается только существующий.** Маршрут проверяет диапазоны сам:
  z/x/y приходят из браузера, а наружу с ними идём мы;
- **геометрия для карты берётся та же, что нарисована на миниатюре** — второй
  сборки нет, иначе про один участок вышло бы две картинки, обе достоверные.

Запуск: python3 -m pytest tests/test_land_map_pans.py -q
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
NODE = shutil.which("node")

MERC_RING = [[4200000.0, 7550000.0], [4200100.0, 7550000.0],
             [4200100.0, 7550100.0], [4200000.0, 7550100.0], [4200000.0, 7550000.0]]


def _maths() -> str:
    """Настоящие функции карты со страницы, а не их пересказ."""
    names = ("LAND_MAP_WORLD", "LAND_MAP_ORIGIN")
    head = "\n".join(
        re.search(rf"(const {name}=[^;]+;)", core.PAGE).group(1) for name in names)
    body = []
    for name in ("landMapScale", "landMapLat", "landMapGround", "landMapMetres",
                 "landMapWorldPx", "landMapWorldPy", "landMapProject", "landMapUnproject"):
        match = re.search(rf"(function {name}\(.*?\n?\}})\n", core.PAGE, re.S)
        assert match, f"{name} не найдена на странице"
        body.append(match.group(1))
    return head + "\n" + "\n".join(body) + "\n"


def _run(expression: str):
    if not NODE:
        pytest.skip("node недоступен")
    script = _maths() + f"console.log(JSON.stringify({expression}));"
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_the_client_places_tiles_where_the_server_glues_them():
    """Та же формула пикселя, что у _basemap_png, — иначе контур съедет."""
    zoom = 16
    world = 2 * 20037508.342789244
    origin = -20037508.342789244
    scale = world / (256.0 * (1 << zoom))
    for x, y in ((4200000.0, 7550000.0), (-1234567.0, 100.0)):
        expected_x = (x - origin) / scale
        expected_y = (-y - origin) / scale
        got_x = _run(f"landMapWorldPx({x},{zoom})")
        got_y = _run(f"landMapWorldPy({y},{zoom})")
        assert math.isclose(got_x, expected_x, rel_tol=1e-9), (got_x, expected_x)
        assert math.isclose(got_y, expected_y, rel_tol=1e-9), (got_y, expected_y)


def test_the_view_centre_lands_in_the_middle_of_the_stage():
    view = {"zoom": 16, "cx": 4200050.0, "cy": 7550050.0, "width": 900, "height": 520}
    point = _run(f"landMapProject([4200050.0,7550050.0],{json.dumps(view)})")
    assert [round(v, 6) for v in point] == [450.0, 260.0]


def test_north_is_up_and_east_is_right():
    """Знак широты — то место, где карта переворачивается и никто не замечает."""
    view = {"zoom": 16, "cx": 4200000.0, "cy": 7550000.0, "width": 900, "height": 520}
    east = _run(f"landMapProject([4200500.0,7550000.0],{json.dumps(view)})")
    north = _run(f"landMapProject([4200000.0,7550500.0],{json.dumps(view)})")
    assert east[0] > 450.0 and math.isclose(east[1], 260.0)
    assert north[1] < 260.0 and math.isclose(north[0], 450.0)


def test_projection_and_its_inverse_agree():
    """На обратном ходе держатся перенос карты и линейка."""
    view = {"zoom": 15, "cx": 4200050.0, "cy": 7550050.0, "width": 837, "height": 431}
    point = [4201234.5, 7551987.25]
    back = _run(f"(v=>landMapUnproject(v[0],v[1],{json.dumps(view)}))"
                f"(landMapProject({json.dumps(point)},{json.dumps(view)}))")
    assert math.isclose(back[0], point[0], rel_tol=1e-9)
    assert math.isclose(back[1], point[1], rel_tol=1e-9)


def test_a_mercator_metre_is_not_a_metre_on_the_ground():
    """На широте Москвы 100 меркаторных метров — около 56 настоящих."""
    metres = _run("landMapGround(100,7550000)")
    assert 50 < metres < 60, metres
    # У экватора растяжения нет — а значит и пересчёт не выдумывает поправку
    # там, где её быть не должно.
    assert math.isclose(_run("landMapGround(100,0)"), 100.0, rel_tol=1e-6)


def test_the_ruler_speaks_the_language_of_the_parking_coefficient():
    """К1 задаётся расстоянием до станции — линейка меряет то же самое."""
    match = re.search(r"(function landMapClick\(event\)\{.*?\n\})", core.PAGE, re.S)
    assert match, "landMapClick не найдена"
    assert "К1" in match.group(1), "линейка не объясняет, зачем она нужна"
    note = re.search(r"(function renderLandMap\(\)\{.*?\n\})\n", core.PAGE, re.S)
    assert note and "по прямой" in note.group(1), (
        "расстояние обязано назвать себя прямым: К1 меряется по пешеходным путям")


def test_the_tile_route_checks_the_numbers_itself():
    client = TestClient(_wrapper.app)
    assert client.get("/land/tiles/25/1/1.png").status_code == 400, "масштаб вне диапазона"
    assert client.get("/land/tiles/2/9/1.png").status_code == 400, "тайл вне карты мира"
    assert client.get("/land/tiles/2/-1/1.png").status_code in (400, 404)


def test_a_tile_is_served_and_cached_by_the_browser(monkeypatch):
    monkeypatch.setattr(core, "_osm_tile", lambda z, x, y: b"\x89PNG-tile")
    client = TestClient(_wrapper.app)
    response = client.get("/land/tiles/16/39000/20500.png")
    assert response.status_code == 200
    assert response.content == b"\x89PNG-tile"
    assert response.headers["content-type"] == "image/png"
    # Неделя в браузере — то, чем живая карта не выкачивает чужой сервис.
    assert "max-age=604800" in response.headers.get("cache-control", "")


def test_a_dead_tile_source_is_a_gap_not_a_crash():
    def boom(*_args):
        raise RuntimeError("источник молчит")
    original = core._osm_tile
    core._osm_tile = boom
    try:
        assert TestClient(_wrapper.app).get("/land/tiles/16/39000/20500.png").status_code == 502
    finally:
        core._osm_tile = original


def test_the_map_reuses_the_geometry_already_drawn():
    """Второй сборки контура нет: две картинки одного участка разойдутся."""
    match = re.search(r"(function landMapFromContour\(cad\)\{.*?\n\})", core.PAGE, re.S)
    assert match, "landMapFromContour не найдена"
    body = match.group(1)
    assert "landLookup" in body and "contour_merc" in body
    assert "landScreeningLast" in body, "зоны берутся не из показанного скрининга"
    assert "cadastral_number===cad" in body.replace(" ", ""), (
        "участок ищется не по номеру: список фильтруется и переставляется")


def test_the_minature_offers_to_open_the_map():
    assert 'onclick="landMapFromContour(' in core.PAGE
    assert 'id="landMapStage"' in core.PAGE
    assert core.PAGE.count("развернуть карту") >= 2, (
        "кнопка нужна и у миниатюры участка, и у пятна застройки")


def test_the_number_travels_as_an_attribute_not_as_code():
    """Экранированное значение внутри onclick снова становится кодом.

    escapeHtml делает из кавычки `&#39;`, а браузер раскодирует атрибут ДО
    того, как отдаст его содержимое разбору скрипта, — и подстановка в
    JS-строку обработчика оказывается не защищённой, а только выглядящей так.
    """
    assert "landMapFromContour(this.dataset.cad)" in core.PAGE
    assert "landMapFromContour('" not in core.PAGE, (
        "номер подставлен внутрь JS-строки обработчика")


def test_the_printed_picture_stays_the_printed_picture():
    """Карта на экране печатную картинку не подменяет."""
    assert "/land/map-image?bbox=" in core.PAGE, "миниатюра осталась на своём источнике"
    assert "_telegram_territory_photo" in Path("main_legacy.py").read_text(encoding="utf-8")


def test_the_tile_source_is_swappable_without_touching_code():
    """Публичный OSM годится посмотреть; под поток нужен свой — одной строкой."""
    source = Path("main_legacy.py").read_text(encoding="utf-8")
    assert '_env_str("OSM_TILE_URL"' in source
    route = re.search(r'(def land_tile\(.*?\n\n\n)', source, re.S)
    assert route and "OSM_TILE_URL" in route.group(1), (
        "маршрут тайлов молчит о том, что источник сменный — молчаливое "
        "выкачивание чужого сервиса выглядит так же, как своё")
