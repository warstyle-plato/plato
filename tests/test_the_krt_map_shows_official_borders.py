"""Карта КРТ Москвы: официальные границы, а не геокодированная точка.

Найдено живым разбором портала (31.08.2026). Сайт КРТ — Bitrix: список
рендерится сервером постранично, JSON-эндпоинтов `/api/*` нет вовсе (все
кандидаты отвечают 404). Зато карта портала берёт данные одним статическим
файлом `map2025.json`, и в нём лежит ВЕСЬ реестр: 263 площадки против 136 в
постраничном списке и 124 в нашем прежнем снимке.

У каждой записи есть полигон официальных границ. Это снимает оговорку карточки
«официальный полигон границ пока не получен».

И отрицательный ответ, важный не меньше: статусов в данных два — «Планируемый»
и «В реализации». «Проекты на торгах» есть только легендой карты, ни одной
такой записи нет. Значит будущие торги из каталога не выделить.

Запись — массив без имён полей. Имена сверены с числами HTML-карточек и
совпали; неопознанная колонка оставлена под своим номером: подписать её
догадкой значит завести число, за которое никто не отвечает.

Запуск: python3 -m pytest tests/test_the_krt_map_shows_official_borders.py -q
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_map_data as krt  # noqa: E402

# Живая запись из map2025.json, обрезанная до нескольких вершин контура.
LIVE = [
    "№8 Кунцево", "В реализации", "ЗАО", "Кунцево", "",
    "1310", "610080", "0", "13250", "596830", "156320", "15.89", "0", "0",
    {"type": "Polygon", "coordinates": [[
        [37.39442203737125, 55.736626835520546],
        [37.394412223950056, 55.73680278046251],
        [37.39675646050004, 55.73681197176235],
        [37.40128090566730, 55.73558377230110],
        [37.39442203737125, 55.736626835520546]]]},
    "https://krt-bitrix-bucket.storage.yandexcloud.net/iblock/photo.jpg",
    [37.39644312825156, 55.73562213674425],
    "/projects/no8-kuncevo",
]


def test_the_row_is_read_field_by_field() -> None:
    site = krt.parse([LIVE])[0]
    assert site["slug"] == "no8-kuncevo"
    assert site["name"] == "№8 Кунцево"
    assert site["status"] == "В реализации"
    assert site["okrug"] == "ЗАО" and site["district"] == "Кунцево"
    assert site["area_ha"] == 15.89
    assert site["total_gfa_sqm"] == 610080
    assert site["housing_gfa_sqm"] == 596830
    assert site["business_gfa_sqm"] == 13250
    assert site["nonresidential_gfa_sqm"] == 0
    assert site["jobs"] == 1310
    assert site["url"].startswith("https://krt.mos.ru/projects/")


def test_the_unnamed_column_keeps_its_number() -> None:
    """Подписать догадкой — значит завести число, за которое никто не отвечает."""
    site = krt.parse([LIVE])[0]
    assert site["unnamed_10"] == "156320"
    assert not any(key for key in site if key.startswith("unknown"))


def test_the_border_comes_in_the_same_metres_as_the_basemap() -> None:
    """Контур в метрах меркатора — тех же, в которых считает подложка.

    Переводить его в браузере значило бы завести вторую проекцию, а
    перепутанный порядок пары «широта, долгота» молча зеркалит полигон: он
    остаётся правдоподобным и встаёт не туда.
    """
    site = krt.parse([LIVE])[0]
    ring = site["rings_merc"][0]
    assert len(ring) >= 4 and ring[0] == ring[-1], "кольцо обязано замыкаться"
    x, y = ring[0]
    # Кунцево: около 4,16 млн метров на восток и 7,5 млн на север.
    assert 4_100_000 < x < 4_250_000, f"долгота уехала: {x}"
    assert 7_400_000 < y < 7_600_000, f"широта уехала: {y}"
    assert all(isinstance(value, int) for value in ring[0]), \
        "дробная часть метра не видна ни на одной нашей карте, а вес утраивает"
    centre = site["centre_merc"]
    assert math.hypot(centre[0] - x, centre[1] - y) < 5_000


def test_a_row_without_a_link_is_not_a_site() -> None:
    broken = list(LIVE)
    broken[krt.LINK] = ""
    assert krt.parse([broken]) == []
    assert krt.parse([["мало", "полей"]]) == []
    assert krt.parse({"не": "список"}) == []


def test_simplifying_keeps_the_shape_and_the_ends() -> None:
    ring = [[float(i), 0.0] for i in range(0, 200, 2)] + [[0.0, 0.0]]
    thin = krt.simplify(ring, 12.0)
    assert len(thin) < len(ring)
    assert thin[0] == [0, 0] and thin[-1] == [0, 0], "кольцо перестало замыкаться"
    short = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
    assert len(krt.simplify(short, 50.0)) == 4, "короткое кольцо прореживать нечем"


def test_the_frame_of_everything_is_the_frame_of_everything() -> None:
    sites = krt.parse([LIVE])
    box = krt.bbox(sites)
    ring = sites[0]["rings_merc"][0]
    assert box[0] <= min(p[0] for p in ring) and box[2] >= max(p[0] for p in ring)
    assert krt.bbox([]) is None


def test_the_dataset_address_is_the_one_that_answered() -> None:
    assert krt.DATASET_URL == "https://api.krt.mos.ru/map2025.json"
    source = (ROOT / "market_search" / "krt_map_data.py").read_text(encoding="utf-8")
    assert "263" in source and "136" in source, "числа находки названы в самом модуле"
    assert "Проекты на торгах" in source, "отрицательный ответ должен быть записан"


def test_the_page_frames_the_city_and_names_what_is_outside() -> None:
    """Общая рамка тянется до Зеленограда, и город в ней сжимается в пятно."""
    from auction_search import ui

    page = ui.AUCTIONS_PAGE
    assert "function krtMapFrame(" in page
    body = page[page.index("function krtMapFrame("):]
    body = body[:body.index("\nfunction ", 1)]
    assert "0.05" in body and "0.95" in body, "кадр по основной массе, а не по всему"
    assert "outside" in body, "оставшиеся за кадром обязаны быть посчитаны"
    assert "krtMapWhole" in page, "должен быть переключатель на всю Москву"


def test_the_map_never_draws_a_number_of_its_own() -> None:
    """Сводка в подсказке — поля источника, а не наш пересчёт."""
    from auction_search import ui

    page = ui.AUCTIONS_PAGE
    body = page[page.index("function krtMapBind("):]
    body = body[:body.index("\nfunction ", 1)]
    for sign in ("/1e6", "*1e6", "/10000", "Math.round(s."):
        assert sign not in body, f"в подсказке считается своё: {sign}"
