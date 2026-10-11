"""Всероссийский кабинет «Пульса» читается своим API, а не московскими адресами.

Второй заход #657. Вход на `russia.pulsprodaj.ru` проходил, но кабинет —
одностраничное приложение: проекты, классы и цены он берёт с `/api/v1/…`, а
наш код спрашивал московские адреса (`/map/` с GeoJSON, `/api/search/`,
`/api/app/complex/price_stats/`) и получал 404. На проде у Мытищ не было ни
соседей с ценой, ни свода по Московской области.

Образцы ответов в `tests/fixtures/pulse_russia/` сняты с живого кабинета
11.10.2026 и обрезаны: без кук, без учётных данных, без людей.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_search.pulse import (
    PulseNetwork,
    PulseProject,
    address_region,
    make_pulse_client,
    pulse_declaration,
    pulse_region,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pulse_russia"
RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"
LAT, LON = 55.9105, 37.7360  # Мытищи

# Старые адреса московского кабинета: всероссийский отвечает на них 404.
MOSCOW_ROUTES = ("/map", "/api/search/", "/api/app/", "/api/compare/", "/sales/", "/complex/")


def _sample(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class Cabinet:
    """Кабинет «вся Россия» по образцам: `/api/v1/…` отвечает, прочее — 404."""

    def __init__(self, *, aggregator=None, sales=None, distinct: bool = False):
        # `distinct` — у каждого ЖК свои проекты площадок (как в жизни);
        # без него все ЖК показывают одни и те же объявления.
        self.distinct = distinct
        self.asked: list[tuple[str, dict | None]] = []
        self.aggregator = aggregator if aggregator is not None else _sample("aggregator_card_data_atlantis.json")
        self.sales = sales if sales is not None else _sample("objects_sales_summary.json")

    def __call__(self, path: str, *, data: bytes | None = None, headers=None) -> bytes:
        body = json.loads(data) if data else None
        self.asked.append((path, body))
        if any(path.startswith(route) for route in MOSCOW_ROUTES):
            import urllib.error

            raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)
        name = path.removeprefix("/api/v1/")
        if name == "regions/search/":
            answer = _sample("regions_search.json")
        elif name == "search/":
            assert body["regionsIds"] == [9] and body["entityType"] == "complex"
            answer = _sample("search_complex.json")
        elif name == "objects_grouped/":
            wanted = set(body["complex_ids"])
            answer = [row for row in _sample("objects_grouped.json") if row["complex_id"] in wanted]
        elif name == "aggregator-card-data/":
            answer = self.aggregator
            if self.distinct:
                tag = body["complex_ids"][0]
                answer = {**answer, "table": [
                    {**row, "code": f"{row['code']}-{tag}"} for row in answer["table"]
                ]}
        elif name == "objects_sales_summary/":
            answer = self.sales
        else:
            raise AssertionError(f"неожиданный адрес {path}")
        return json.dumps(answer, ensure_ascii=False).encode("utf-8")

    def routes(self) -> list[str]:
        return [path for path, _ in self.asked]


def _russia(tmp_path: Path, monkeypatch, cabinet: Cabinet | None = None):
    monkeypatch.setenv("PULSE_LOGIN", "l")
    monkeypatch.setenv("PULSE_PASSWORD", "p")
    monkeypatch.setenv("PULSE_REGIONS", "50")
    client = make_pulse_client(tmp_path, base=RUSSIA)
    cabinet = cabinet or Cabinet()
    client._open = cabinet  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]
    client.sleep = lambda seconds: None
    return client, cabinet


def test_the_russia_catalog_is_read_from_its_api_by_complex(tmp_path: Path, monkeypatch) -> None:
    client, cabinet = _russia(tmp_path, monkeypatch)
    projects = {item.complex_id: item for item in client.projects()}

    # Единица — ЖК кабинета, номер несёт код региона: «50-c350624».
    assert "50-c350624" in projects and len(projects) == 8
    atlantis = projects["50-c350624"]
    assert atlantis.name == "Атлантис" and atlantis.region == "50"
    assert atlantis.address.startswith("Московская область г. Мытищи")
    assert atlantis.to_dict()["url"] == f"{RUSSIA}/complex/350624"
    # ЖК — не декларация: номера ПД из него не выводится.
    assert pulse_declaration("50-c350624") is None and pulse_region("50-c350624") == "50"
    # Ни одного московского адреса: всероссийский кабинет отвечает на них 404.
    assert not [path for path in cabinet.routes() if not path.startswith("/api/v1/")]
    assert client.errors == []


def test_the_region_number_of_the_cabinet_is_found_by_name_not_by_code(tmp_path: Path, monkeypatch) -> None:
    """«50» у кабинета — Астраханская область; Московская там «9»."""
    client, cabinet = _russia(tmp_path, monkeypatch)
    client.projects()
    searched = [body for path, body in cabinet.asked if path == "/api/v1/search/"]
    assert searched == [{"regionsIds": [9], "filters": [{}], "entityType": "complex"}]


def test_the_class_comes_from_the_complex_card_and_a_mixed_class_is_unknown(tmp_path: Path, monkeypatch) -> None:
    client, _ = _russia(tmp_path, monkeypatch)
    classes = client.segments()
    assert classes["50-c350624"] == "Бизнес"
    assert classes["50-c351062"] == "Комфорт"
    # «Типовой, Комфорт» — склейка объектов, а не класс: «не знаем».
    assert "50-c5286" not in classes


def test_the_price_is_the_fullest_listing_source_on_the_latest_date(tmp_path: Path, monkeypatch) -> None:
    client, cabinet = _russia(tmp_path, monkeypatch)
    price = client.price("50-c350624")
    # ЦИАН 15 лотов, Яндекс и Домклик по 17: площадки показывают одни и те же
    # квартиры — лоты не складываются, берётся самая полная площадка.
    assert price["price_per_sqm"] == 258_636 and price["lot_count"] == 17
    assert (price["price_per_sqm_min"], price["price_per_sqm_max"]) == (242_941, 258_636)
    assert price["observed_at"] == "2026-10-01"
    assert price["listings"] == ["cian-3786932", "domclick-116470", "yandex-2768826"]
    assert [body for path, body in cabinet.asked if path == "/api/v1/aggregator-card-data/"] == [
        {"ids": [], "complex_ids": [350624], "object_type": "living"}
    ]
    # Ряд цены — из того же ответа (кэш), без второго запроса.
    series = client.price_history(["50-c350624"])["50-c350624"]
    assert series[-1] == {"month": "2026-10", "value": 242_941}
    assert cabinet.routes().count("/api/v1/aggregator-card-data/") == 1


def test_an_old_listing_date_does_not_hide_behind_a_fresh_one(tmp_path: Path, monkeypatch) -> None:
    sample = _sample("aggregator_card_data_atlantis.json")
    sample["table"][0] = {**sample["table"][0], "price_date": "2026-09-01", "count_price": 900}
    client, _ = _russia(tmp_path, monkeypatch, Cabinet(aggregator=sample))
    price = client.price("50-c350624")
    # 900 лотов ЦИАН — сентябрьские; октябрьская дата свежее и выигрывает.
    assert price["observed_at"] == "2026-10-01" and price["lot_count"] == 17


def test_sales_and_remaining_are_read_for_the_objects_of_the_complex(tmp_path: Path, monkeypatch) -> None:
    client, cabinet = _russia(tmp_path, monkeypatch)
    sales = client.sales("50-c350624")
    assert sales["units_per_month"] == pytest.approx(19.3)
    assert sales["area_per_month"] == pytest.approx(878.3)
    assert sales["units_per_month_3m"] is None  # кабинет его не отдаёт: не ноль
    assert sales["known_sales_for"] == "2024-01 — 2026-08"
    asked = [body for path, body in cabinet.asked if path == "/api/v1/objects_sales_summary/"]
    assert asked == [{"ids": [91008, 91019, 2025645]}]
    assert client.remaining("50-c350624") == {"remaining_units": 656, "remaining_area": 33803}
    assert client.project_totals("50-c350624")["buildings"] == 3


def test_a_closed_subscription_is_named_not_shown_as_no_price(tmp_path: Path, monkeypatch) -> None:
    client, _ = _russia(tmp_path, monkeypatch, Cabinet(aggregator={"subscription_required": True, "table": []}))
    assert client.price("50-c350624") is None
    assert any("закрыты подпиской" in error for error in client.errors)


def test_moscow_cabinet_projects_of_a_covered_region_do_not_double_the_neighbours(tmp_path: Path, monkeypatch) -> None:
    """Московский кабинет знает ЖК области под своим номером и на цену отвечает 403."""
    russia, _ = _russia(tmp_path, monkeypatch)
    moscow = SimpleNamespace(
        base=MOSCOW, errors=[], available=True,
        projects=lambda **kw: [
            PulseProject("4033", "Атлантис", 55.9066, 37.7255, address="МО, г. Мытищи, Новомытищинский пр-т", base=MOSCOW),
            PulseProject("8", "Ньютон", 55.92, 37.74, address="МО, Мытищи г. о., ул. Кирпичная", base=MOSCOW),
            PulseProject("77", "Крылатская", 55.75, 37.41, address="г. Москва, Крылатская ул.", base=MOSCOW),
        ],
    )
    network = PulseNetwork([russia, moscow])
    names = [item.name for _, item in network.near(LAT, LON, 2.5)]
    assert names.count("Атлантис") == 1 and "Ньютон" not in names
    assert any(item.complex_id == "77" for item in network.projects())
    assert network.superseded == {"50": 2}
    assert address_region("МО, Мытищи, мкр.16") == "Московская область"


def test_mytishchi_neighbours_get_prices_from_the_russia_cabinet(tmp_path: Path, monkeypatch) -> None:
    from market_search.service_v6 import MarketDiscoveryService

    monkeypatch.setenv("PULSE_BASE_URL", RUSSIA)
    russia, cabinet = _russia(tmp_path / "pulse", monkeypatch, Cabinet(distinct=True))
    service = MarketDiscoveryService(tmp_path)
    service.pulse = russia
    hint = service.price_hint(address=None, latitude=LAT, longitude=LON, include_projects=True)
    search = hint["peer_search"]
    assert search["found"] == 8 and search["with_price"] == 8, hint.get("reason")
    assert search["same_listing"] == 0 and search["errors"] == []
    assert hint["available"] is True and hint["price_per_sqm"] == 258_636
    # Регион — по точке: проекты кабинета вокруг неё из региона 50.
    assert hint["location"]["region"]["code"] == "50"
    assert hint["location"]["region"]["source"] == "point"
    rows = {row["name"]: row for row in hint["projects"]}
    assert rows["Атлантис"]["segment"] == "Бизнес"
    assert not [path for path in cabinet.routes() if not path.startswith("/api/v1/")]


def test_the_same_listings_count_once_among_the_neighbours(tmp_path: Path, monkeypatch) -> None:
    from market_search.service_v6 import MarketDiscoveryService

    monkeypatch.setenv("PULSE_BASE_URL", RUSSIA)
    russia, _ = _russia(tmp_path / "pulse", monkeypatch)
    service = MarketDiscoveryService(tmp_path)
    service.pulse = russia
    hint = service.price_hint(address=None, latitude=LAT, longitude=LON, include_projects=True)
    # Образец цены один на все ЖК: первая (ближняя) запись — сосед, прочие — повтор.
    assert hint["peer_search"]["with_price"] == 1
    assert hint["peer_search"]["same_listing"] >= 5


def test_the_region_summary_counts_a_complex_once_and_drops_old_listings(tmp_path: Path) -> None:
    from market_search.region_market import RegionMarketCollector

    def project(cid, name):
        return PulseProject(cid, name, LAT, LON, address="Московская область г. Мытищи, ул. 1")

    items = [project(f"50-c{n}", f"ЖК {n}") for n in range(1, 7)]
    prices = {
        "50-c1": (200_000, "2026-10-01", ["cian-1"]),
        "50-c2": (240_000, "2026-10-01", ["cian-2"]),
        "50-c3": (260_000, "2026-10-01", ["yandex-3"]),
        # Та же площадка-проект, что у первого: кабинет разбил ЖК на две записи.
        "50-c4": (200_000, "2026-10-01", ["cian-1", "domclick-9"]),
        # Сданный дом: объявления 2022 года — не цена «на дату сбора».
        "50-c5": (120_000, "2022-03-01", ["cian-5"]),
    }
    sales_asked: list[str] = []
    pulse = SimpleNamespace(
        base=RUSSIA, available=True, errors=[],
        projects=lambda: items,
        segments=lambda fetch=True: {item.complex_id: "Комфорт" for item in items},
        price_history=lambda ids, months: {},
        price=lambda cid: (
            {"price_per_sqm": prices[cid][0], "observed_at": prices[cid][1], "listings": prices[cid][2]}
            if cid in prices else None
        ),
        remaining=lambda cid: {"remaining_units": 10},
        sales=lambda cid: sales_asked.append(cid) or {"units_per_month": 5.0, "area_per_month": 250.0},
    )
    collector = RegionMarketCollector(
        pulse, tmp_path, regions=["50"], pause_seconds=0, sleep=lambda s: None,
        clock=lambda: 1_791_158_400.0,  # 2026-10-05
    )
    assert collector.collect("50")["complete"] is True
    summary = json.loads(collector.summary_path("50").read_text(encoding="utf-8"))
    comfort = summary["current"]["Комфорт"]
    assert comfort["projects"] == 3
    assert comfort["price_median"] == statistics.median([200_000, 240_000, 260_000])
    assert summary["coverage"]["stale_price"] == 1
    assert summary["failed_sample"]["50-c4"].startswith("те же объявления")
    # Муниципалитет из адреса кабинета, где область и город без запятой.
    assert set(summary["by_okrug"]) == {"Мытищи"}
    # Темп у проекта без цены не спрашивается: лишняя нагрузка на кабинет.
    assert "50-c6" not in sales_asked
