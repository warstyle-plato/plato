"""Соседний класс — только при нехватке своего (решение владельца 13.10.2026).

Прод 0.25.64, Мытищи: «Бизнес» 309 183 по 11 соседям, «Комфорт» — те же
309 183 по 11, «Стандарт» — 313 944 по 6. Правило 10.08 брало в выборку
соседний уровень всегда: «Бизнес» и «Комфорт» собирали одну и ту же выборку,
а «Стандарт», у которого своих ЖК рядом нет вовсе, — дорогой «Комфорт».

Теперь: сначала только свой класс; своих меньше трёх — свод класса (по
муниципалитету, по региону); свода нет — соседний класс. Каждая замена
названа в `basis_title`, его страница показывает рядом с числом.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from market_search.market_reference import MoscowMarket
from market_search.price_hint import BASIS_CITY, BASIS_PEERS, price_hint
from market_search.segments import OWN_CLASS_ENOUGH, SCOPE_ADJACENT, SCOPE_SAME, class_scope

FRESH = "2026-10-01"
SINCE = "2026-04-01"


def peer(segment, price, observed=FRESH):
    return {"segment": segment, "price_per_sqm": price, "observed_at": observed}


# Мытищи, живой кабинет 12.10.2026 (цены ₽/м²), классы — после #673.
BUSINESS = [peer("Бизнес", 333_673), peer("Бизнес", 258_636), peer("Бизнес", 260_365),
            peer("Бизнес", 344_412)]
COMFORT = [peer("Комфорт", 279_902), peer("Комфорт", 389_293), peer("Комфорт", 309_183),
           peer("Комфорт", 367_950), peer("Комфорт", 318_704)]
UNKNOWN = [peer(None, 273_791)]  # Новое Медведково: «Комфорт, Типовой»
MYTISHCHI = BUSINESS + COMFORT + UNKNOWN


def test_the_threshold_is_the_median_minimum() -> None:
    assert OWN_CLASS_ENOUGH == 3
    assert class_scope(3) == SCOPE_SAME and class_scope(2) == SCOPE_ADJACENT


def test_enough_own_class_takes_only_its_own() -> None:
    business = price_hint(peers=MYTISHCHI, segment="Бизнес", city=MoscowMarket({}), fresh_since=SINCE)
    comfort = price_hint(peers=MYTISHCHI, segment="Комфорт", city=MoscowMarket({}), fresh_since=SINCE)
    assert business["basis"] == comfort["basis"] == BASIS_PEERS
    # Свой класс и сосед без класса — без соседнего уровня.
    assert business["sample"] == 5
    assert business["price_per_sqm"] == statistics.median([p["price_per_sqm"] for p in BUSINESS + UNKNOWN])
    assert comfort["sample"] == 6
    assert business["price_per_sqm"] != comfort["price_per_sqm"]
    assert business["class_scope"] == SCOPE_SAME


def _summary(segment: str, price: int) -> MoscowMarket:
    return MoscowMarket({
        "current": {segment: {"projects": 40, "price_median": price}},
        "last_month": "2026-10",
    })


def test_few_own_class_takes_the_class_summary_and_says_so() -> None:
    hint = price_hint(peers=MYTISHCHI, segment="Стандарт/Эконом", city=_summary("Стандарт/Эконом", 190_000),
                      fresh_since=SINCE)
    assert hint["basis"] == BASIS_CITY and hint["price_per_sqm"] == 190_000
    assert hint["basis_title"].startswith("соседних ЖК класса «Стандарт/Эконом» мало (0) — взят свод")
    assert hint["class_fallback"] == {"own_peers": 0, "needed": 3, "taken": BASIS_CITY}


def test_without_a_summary_the_adjacent_class_is_taken_and_named() -> None:
    hint = price_hint(peers=MYTISHCHI, segment="Стандарт/Эконом", city=MoscowMarket({}), fresh_since=SINCE)
    assert hint["basis"] == "peers_adjacent"
    assert hint["class_scope"] == SCOPE_ADJACENT
    assert hint["basis_title"].startswith("соседних ЖК класса «Стандарт/Эконом» мало (0) — взят соседний класс")
    assert hint["sample"] == 6  # «Комфорт» и сосед без класса; «Бизнес» — через ступень


def test_a_neighbour_without_a_class_does_not_close_the_shortage() -> None:
    peers = [peer("Бизнес", 300_000), peer("Бизнес", 310_000), peer(None, 250_000), peer(None, 260_000),
             peer("Комфорт", 200_000)]
    hint = price_hint(peers=peers, segment="Бизнес", city=MoscowMarket({}), fresh_since=SINCE)
    assert hint["basis"] == "peers_adjacent"
    assert hint["class_fallback"]["own_peers"] == 2


def test_the_analog_selection_takes_the_adjacent_level_only_when_short(tmp_path: Path) -> None:
    from market_search.service_v6 import MarketDiscoveryService as ServiceV6

    def row(name, segment):
        return {"name": name, "segment": segment, "distance_km": 0.6, "coordinates": {}}

    service = ServiceV6(tmp_path)
    many = [row("Э1", "элитный"), row("Э2", "элитный"), row("Э3", "элитный"), row("Savvin", "премиум")]
    quarantine: list[dict] = []
    kept, _ = service._apply_comparability(many, quarantine, subject_district=None, requested="элитный")
    assert "Savvin" not in {r["name"] for r in kept}
    assert "соседний уровень" in quarantine[0]["reason"]

    few = [row("Э1", "элитный"), row("Э2", "элитный"), row("Savvin", "премиум")]
    kept, _ = service._apply_comparability(few, [], subject_district=None, requested="элитный")
    assert "Savvin" in {r["name"] for r in kept}
