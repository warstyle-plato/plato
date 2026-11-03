"""«Ничего не найдено» при двух десятках найденных объектов — неправда.

По городскому адресу Подмосковья («Одинцово, Маковского ул., 28») НСПД
возвращает дом и его квартиры, но не земельный участок. Фильтр оставлял только
участки, скрывал остальное — и человек читал «По этому запросу участок не
найден», хотя портал ответил двадцатью двумя объектами. Найденное при этом
выбрасывалось, и поиск начинался заново с внешнего геокодера, у которого точка
хуже: дом уже найден, его координаты точнее любого подбора по строке.

Три шага вместо одного тупика:
1. номер участка из карточки ОКС, если портал его несёт;
2. участок под найденным домом — по координатам самого дома;
3. если участка нет ни там ни там — показать найденные объекты и сказать
   прямо, что участок не отдан, а не «ничего не найдено».

Сеть в тестах не участвует: ответы НСПД подставляются.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def feature(number: str, *, kind: str, address: str = "", lat: float = 55.66,
            lng: float = 37.28, land_parcel: str = "") -> dict:
    """Объект в том виде, в каком его отдаёт геопортал."""
    options = {"cad_num": number, "readable_address": address}
    if kind == "land":
        options.update(land_record_area=1200.0, land_record_category_type="Земли населённых пунктов")
    elif kind == "building":
        options.update(build_record_area=4300.0, year_built="1998", purpose="Многоквартирный дом")
    else:
        options.update(build_record_area=54.0, purpose="Помещение")
    if land_parcel:
        options["land_cad_number"] = land_parcel
    merc_x = lng * 20037508.34 / 180.0
    merc_y = 7467000.0
    return {"properties": {"options": options},
            "geometry": {"type": "Point", "coordinates": [merc_x, merc_y]}}


HOUSE = "50:20:0010203:1001"
FLATS = [f"50:20:0010203:{2000 + i}" for i in range(21)]
PARCEL = "50:20:0010203:15"
ADDRESS = "Московская область, Одинцово, Маковского ул., 28"


@pytest.fixture
def portal(monkeypatch):
    """Подставной НСПД: что вернуть на поиск и что — на точку."""
    state = {"search": {}, "point": [], "calls": []}

    def fake_search(query):
        state["calls"].append(("search", query))
        return state["search"].get(query, [])

    def fake_point(lat, lng):
        state["calls"].append(("point", round(lat, 3), round(lng, 3)))
        return state["point"]

    monkeypatch.setattr(core, "_nspd_search_features", fake_search)
    monkeypatch.setattr(core, "_nspd_point_features", fake_point)
    monkeypatch.setattr(core, "_geocode_address", lambda *a, **kw: ([], []))
    monkeypatch.setattr(core, "_core_api_url", lambda path: "")
    return state


def lookup(query: str) -> dict:
    return core.land_lookup(core.LandLookupRequest(query=query, limit=30))


# --- дом найден, участка среди объектов нет ------------------------------------

def test_the_parcel_comes_from_the_building_card(portal):
    """Короткий путь: портал сам назвал участок под домом."""
    portal["search"][ADDRESS] = [
        feature(HOUSE, kind="building", address=ADDRESS, land_parcel=PARCEL),
        *[feature(number, kind="premise", address=ADDRESS) for number in FLATS],
    ]
    portal["search"][PARCEL] = [feature(PARCEL, kind="land", address=ADDRESS)]
    data = lookup(ADDRESS)
    assert [item["cadastral_number"] for item in data["results"]] == [PARCEL]
    assert data["found_count"] == 1


def test_the_parcel_is_found_under_the_building(portal):
    """Карточка участка не назвала — берём точку самого дома."""
    portal["search"][ADDRESS] = [
        feature(HOUSE, kind="building", address=ADDRESS),
        *[feature(number, kind="premise", address=ADDRESS) for number in FLATS],
    ]
    portal["point"] = [feature(PARCEL, kind="land", address=ADDRESS)]
    data = lookup(ADDRESS)
    assert [item["cadastral_number"] for item in data["results"]] == [PARCEL]
    assert data["results"][0]["found_under"] == HOUSE


def test_the_point_is_taken_from_the_house_not_from_a_geocoder(portal):
    """Дом уже найден: его координаты точнее подбора по строке адреса."""
    portal["search"][ADDRESS] = [feature(HOUSE, kind="building", address=ADDRESS)]
    portal["point"] = [feature(PARCEL, kind="land")]
    lookup(ADDRESS)
    assert any(call[0] == "point" for call in portal["calls"]), "точка дома не проверялась"


# --- участок не дался ничем -----------------------------------------------------

def test_the_found_objects_are_shown_instead_of_nothing(portal):
    """Двадцать два объекта найдено — «ничего не найдено» этого не описывает."""
    portal["search"][ADDRESS] = [
        feature(HOUSE, kind="building", address=ADDRESS),
        *[feature(number, kind="premise", address=ADDRESS) for number in FLATS],
    ]
    portal["point"] = []
    data = lookup(ADDRESS)
    assert data["results"], "найденные объекты снова выброшены"
    assert HOUSE in [item["cadastral_number"] for item in data["results"]]


def test_the_message_says_what_actually_happened(portal):
    portal["search"][ADDRESS] = [feature(HOUSE, kind="building", address=ADDRESS)]
    portal["point"] = []
    text = " ".join(str(item) for item in lookup(ADDRESS)["warnings"]).lower()
    assert "участок по этому адресу егрн не отдал" in text
    assert "кадастровый номер" in text
    # «Адрес не распознан» рядом с найденным домом — противоречие.
    assert "адрес не распознан" not in text


def test_nothing_hidden_when_everything_is_shown(portal):
    """Счётчик скрытого рядом с показанными объектами противоречит сам себе."""
    portal["search"][ADDRESS] = [
        feature(HOUSE, kind="building", address=ADDRESS),
        *[feature(number, kind="premise", address=ADDRESS) for number in FLATS],
    ]
    portal["point"] = []
    data = lookup(ADDRESS)
    assert data["hidden_count"] == 0


# --- ничего не сломалось в обычных путях -----------------------------------------

def test_a_plain_parcel_search_is_unchanged(portal):
    """Когда участок в выдаче есть, он и остаётся единственным ответом."""
    portal["search"][ADDRESS] = [
        feature(PARCEL, kind="land", address=ADDRESS),
        feature(HOUSE, kind="building", address=ADDRESS),
    ]
    data = lookup(ADDRESS)
    assert [item["cadastral_number"] for item in data["results"]] == [PARCEL]
    assert data["hidden"].get("building") == 1


def test_an_empty_portal_answer_still_says_so(portal):
    portal["search"][ADDRESS] = []
    data = lookup(ADDRESS)
    assert data["results"] == []
    text = " ".join(str(item) for item in data["warnings"])
    assert "адрес не распознан" in text.lower()


def test_a_cadastral_query_does_not_take_this_path(portal):
    """Номер спрашивают явно — подстановок под ним быть не должно."""
    portal["search"][PARCEL] = [feature(PARCEL, kind="land")]
    data = lookup(PARCEL)
    assert data["mode"] == "cadastral"
    assert [item["cadastral_number"] for item in data["results"]] == [PARCEL]
