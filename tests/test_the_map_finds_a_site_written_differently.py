"""Площадка находится в файле карты и тогда, когда имя записано иначе.

«Почему у него единственного нет верного контура на карте, как у других?»
(владелец, 03.09.2026, Варшавское ш., вл. 37 / Нагатинская ул., влд. 3А/6).
Карточка искала площадку по слагу портала, потом по точному имени; у этой
площадки имя списка — два адреса через запятую, и точный ключ не совпадал ни с
чем — точка уходила на геокодер, контур не рисовался. Теперь: сокращения
адреса не различаются, составное имя сверяется по каждому адресу, а последний
ключ — паспорт площадки (район, площадь, жилой объём — один реестр у обоих).

Запуск: python3 -m pytest tests/test_the_map_finds_a_site_written_differently.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import krt_registry as kr  # noqa: E402

SITES = [
    {"slug": "varshavskoe-sh-vl-37", "name": "Варшавское ш., влд. 37", "district": "Нагатино-Садовники",
     "area_ha": 14.62, "housing_gfa_sqm": 229_490, "rings_merc": [[[0, 0], [1, 0], [1, 1]]], "centre_merc": [1, 1]},
    {"slug": "other", "name": "Каширское шоссе, вл. 65", "district": "Москворечье-Сабурово",
     "area_ha": 9.1, "housing_gfa_sqm": 120_000, "rings_merc": [], "centre_merc": [2, 2]},
]


class _Registry(kr.KrtRegistry):
    def __init__(self):  # noqa: D401 — без диска и сети
        pass

    def map_dataset(self, **_kwargs):
        return {"sites": SITES}


def test_the_compound_name_matches_by_one_of_its_addresses() -> None:
    found = _Registry().map_lookup(
        "varshavskoe-shosse-vl-37-nagatinskaya", "Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6")
    assert found["site"]["slug"] == "varshavskoe-sh-vl-37" and found["matched"] == "address"


def test_abbreviations_do_not_split_one_address() -> None:
    assert kr._address_key("Варшавское шоссе, владение 37") == kr._address_key("Варшавское ш., влд. 37")
    assert kr._address_parts("Варшавское шоссе, вл. 37, Нагатинская ул., влд. 3А/6") == [
        "варшавское ш вл 37", "нагатинская ул вл 3а 6"]


def test_the_passport_is_the_last_key() -> None:
    project = {"name": "Промзона № 30 «Нагатино», участок 2", "district": "Нагатино-Садовники",
               "area_ha": 14.6, "housing_gfa_sqm": 229_490}
    found = _Registry().map_lookup("promzona-30", project["name"], project)
    assert found["site"]["slug"] == "varshavskoe-sh-vl-37" and found["matched"] == "passport"


def test_a_different_site_is_not_found_by_the_street_alone() -> None:
    found = _Registry().map_lookup("varsh-12", "Варшавское шоссе, вл. 12",
                                   {"district": "Нагатино-Садовники", "area_ha": 3.0, "housing_gfa_sqm": 50_000})
    assert found["site"] is None and "нет в файле карты" in found["problem"]


def test_the_point_route_says_how_it_was_found() -> None:
    source = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")
    assert "найдена в файле по адресу" in source and "найдена в файле по паспорту" in source
