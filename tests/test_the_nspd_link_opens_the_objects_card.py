"""Ссылка на НСПД открывает карточку объекта, а не только место на карте.

Владелец, 27.09.2026: ссылка по координатам открывает нужный квартал, но дом
приходится искать глазами. Ссылка «скопировать» самой НСПД несёт
`selectedCard=<id объекта>,<слой>,<номер>` — движок берёт id и слой из ответа
поиска. Нет их — карточку не угадываем, ссылка остаётся по точке.
"""

from __future__ import annotations

import main_legacy as core

POINT = {"type": "Point", "coordinates": [37.626035, 55.689108]}


def _feature(**extra):
    return {"geometry": POINT, "properties": {"categoryName": "Земельные участки ЕГРН",
                                              "options": {}, **extra.pop("properties", {})},
            **extra}


def test_the_link_selects_the_card_like_nspd_own_copy_link():
    got = core._normalize_nspd_feature(
        _feature(id=153363435, properties={"category": 36368}), "77:05:0004001:2046")
    assert got["map_url"].endswith("&selectedCard=153363435%2C36368%2C77%3A05%3A0004001%3A2046")
    assert "coordinate_x=" in got["map_url"] and "is_copy_url=true" in got["map_url"]
    assert (got["nspd_id"], got["nspd_layer"]) == ("153363435", "36368")


def test_without_id_or_layer_the_card_is_not_guessed():
    for feature in (_feature(properties={"category": 36368}), _feature(id=153363435),
                    _feature(id="abc", properties={"category": 36368})):
        url = core._normalize_nspd_feature(feature, "77:05:0004001:2046")["map_url"]
        assert "selectedCard" not in url and "coordinate_x=" in url
