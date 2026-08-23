"""Скрининг спрашивает участок, а не точку в его середине.

`_land_screen_findings` опрашивал шестьдесят два слоя НСПД в одном пикселе —
центре участка. Охранная зона ЛЭП идёт полосой вдоль границы: в центр она не
попадает, слой отвечает пусто, и вердикт говорит «критических ограничений не
обнаружено» на непроверенном. Кейс владельца — 50:21:0120316:1221, 23.08.2026;
до того Коммунарка, 22.08.2026.

Прежняя правка про долю накрытия (`_land_coverage_shares`) чинила вторую
половину вопроса — как измерить найденную зону. Первую, как её найти, она не
трогала.

Здесь опрос идёт пикселем размером с участок: WMS ищет объекты под пикселем, и
пиксель во весь участок спрашивает «что пересекает этот участок». Ответ выходит
с запасом — зона, задевшая рамку, но не сам участок, отсеивается долей
накрытия по настоящему контуру.

Живой НСПД из песочницы закрыт (WAF пускает только ядро), поэтому портал здесь
подменён: проверяется, ЧТО мы у него спрашиваем, а не что он отвечает.

Запуск: python3 -m pytest tests/test_screening_asks_the_contour.py -q
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

# Прямоугольный участок примерно 100 × 60 м.
PARCEL = {"type": "Polygon", "coordinates": [[
    [37.5500, 55.7200], [37.5516, 55.7200], [37.5516, 55.7206],
    [37.5500, 55.7206], [37.5500, 55.7200]]]}


def _asked(monkeypatch, geometry):
    """Возвращает разобранные параметры запросов, ушедших в НСПД."""
    sent: list[dict[str, str]] = []

    def fake(params: str, layer_id: int, api_version: str):
        sent.append(dict(urllib.parse.parse_qsl(params)))
        return {"features": []}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo_request", fake)
    core._land_screen_findings(55.7203, 37.5508, geometry)
    return sent


# --- чем спрашиваем ----------------------------------------------------------

def test_the_query_pixel_covers_the_whole_parcel(monkeypatch):
    """Пиксель во весь участок вместо пикселя в его середине."""
    sent = _asked(monkeypatch, PARCEL)
    assert sent, "ни одного запроса не ушло"
    for params in sent:
        assert params["WIDTH"] == "1" and params["HEIGHT"] == "1"
        west, south, east, north = (float(v) for v in params["BBOX"].split(","))
        assert (west, south, east, north) == pytest.approx(
            (37.5500, 55.7200, 37.5516, 55.7206))


def test_every_layer_is_asked_about_the_contour(monkeypatch):
    """Слои остались те же — изменился вопрос, а не их список."""
    sent = _asked(monkeypatch, PARCEL)
    assert len({int(p["QUERY_LAYERS"]) for p in sent}) == len(core._NSPD_SCREEN_LAYERS)


def test_a_strip_along_the_edge_is_no_longer_missed(monkeypatch):
    """Главная проверка: зона, не накрывающая центр, теперь находится.

    Полоса шириной в четверть участка вдоль западной границы. Центр участка в
    неё не попадает — прежним точечным опросом её было не увидеть.
    """
    strip = {"type": "Polygon", "coordinates": [[
        [37.5500, 55.7200], [37.5504, 55.7200], [37.5504, 55.7206],
        [37.5500, 55.7206], [37.5500, 55.7200]]]}
    centre_x, centre_y = 37.5508, 55.7203
    assert not (37.5500 <= centre_x <= 37.5504), "полоса накрывает центр — тест не о том"

    def fake(params: str, layer_id: int, api_version: str):
        # Отвечает только один слой и только на запрос, задевающий полосу.
        fields = dict(urllib.parse.parse_qsl(params))
        west, south, east, north = (float(v) for v in fields["BBOX"].split(","))
        if int(fields["QUERY_LAYERS"]) != core._NSPD_SCREEN_LAYERS[0]:
            return {"features": []}
        if west > 37.5504 or east < 37.5500:
            return {"features": []}
        return {"features": [{
            "geometry": strip,
            "properties": {"options": {
                "categoryName": "Охранная зона объектов электросетевого хозяйства",
                "type_zone": "Охранная зона ЛЭП",
                "reg_numb_border": "50:21-6.1234",
                "name_by_doc": "Охранная зона ВЛ 110 кВ",
            }},
        }]}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo_request", fake)
    found = core._land_screen_findings(centre_y, centre_x, PARCEL)
    assert found, "полоса вдоль границы снова не найдена"
    assert "ЛЭП" in (found[0].get("name") or "") + (found[0].get("type_zone") or "")
    # И доля накрытия посчитана по настоящему контуру, а не по рамке запроса.
    assert 15 < float(found[0]["coverage_pct"]) < 35, found[0]["coverage_pct"]


def test_without_geometry_the_probe_falls_back_to_a_point(monkeypatch):
    """Границ нет — накладывать нечего, и это другой ответ, а не тот же."""
    sent = _asked(monkeypatch, None)
    assert sent
    for params in sent:
        assert params["WIDTH"] == "512", "точечный опрос подменён контурным"


# --- метод назван вслух ------------------------------------------------------

def test_the_method_travels_with_the_findings(monkeypatch):
    def fake(params: str, layer_id: int, api_version: str):
        fields = dict(urllib.parse.parse_qsl(params))
        if int(fields["QUERY_LAYERS"]) != core._NSPD_SCREEN_LAYERS[0]:
            return {"features": []}
        return {"features": [{"geometry": PARCEL, "properties": {"options": {
            "categoryName": "Зона с особыми условиями", "type_zone": "Санитарная зона",
            "reg_numb_border": "50:21-6.9", "name_by_doc": "СЗЗ"}}}]}

    monkeypatch.setattr(core, "_nspd_getfeatureinfo_request", fake)
    assert core._land_screen_findings(55.7203, 37.5508, PARCEL)[0]["probe_method"] == "contour"
    assert core._land_screen_findings(55.7203, 37.5508, None)[0]["probe_method"] == "point"


def test_the_disclaimer_says_what_was_asked():
    """Пустой результат точечного опроса — не «чисто»."""
    contour = core._land_screening_verdict([], probed=True, method="contour")
    assert "по контуру участка" in contour["disclaimer"]
    assert contour["probe_method"] == "contour"

    point = core._land_screening_verdict([], probed=True, method="point")
    assert "в одной точке" in point["disclaimer"]
    assert "ЛЭП" in point["disclaimer"], "пример полосы вдоль края назван"
    assert "проверкой участка не является" in point["disclaimer"]


def test_a_single_point_parcel_downgrades_the_whole_summary():
    """Свод не имеет права выглядеть увереннее своей слабой части."""
    import inspect

    source = inspect.getsource(core.land_screening)
    assert 'p.get("probe_method") == "point"' in source


# --- границы участка ---------------------------------------------------------

def test_bounds_are_read_in_both_coordinate_systems():
    """НСПД отдаёт геометрию и в градусах, и в веб-меркаторе."""
    degrees = core._geometry_bounds_wgs84(PARCEL)
    assert degrees == pytest.approx((37.5500, 55.7200, 37.5516, 55.7206))

    corners = [core._wgs84_to_mercator(lat, lng)
               for lng, lat in ((37.5500, 55.7200), (37.5516, 55.7206))]
    mercator = {"type": "Polygon", "coordinates": [[
        [corners[0][0], corners[0][1]], [corners[1][0], corners[0][1]],
        [corners[1][0], corners[1][1]], [corners[0][0], corners[1][1]]]]}
    assert core._geometry_bounds_wgs84(mercator) == pytest.approx(degrees, abs=1e-6)


def test_an_empty_geometry_gives_nothing_not_zero():
    assert core._geometry_bounds_wgs84(None) is None
    assert core._geometry_bounds_wgs84({"type": "Polygon", "coordinates": []}) is None
