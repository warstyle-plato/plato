"""Недельный свод рынка региона из кабинета «Пульса».

Месячный отчёт есть только по Москве; по остальной России свод собирается
из кабинета поштучно — фоном, раз в неделю, с паузами, лимитом и
продолжением после обрыва. Формат тот же, что у `moscow-market`, и читает
его тот же читатель. Нет данных — причина, а не ноль.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_search.market_reference import MarketAtlas, MoscowMarket, RegionMarket
from market_search.price_hint import BASIS_CITY, BASIS_OKRUG, price_hint
from market_search.pulse import PulseProject
from market_search.region_market import (
    INTERVAL_SECONDS,
    RegionMarketCollector,
    build_region_market,
    configured_regions,
    municipality_of,
)

RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"
T0 = 1_790_000_000.0  # 2026-09 — точка отсчёта часов сбора


def _project(cid: str, address: str) -> PulseProject:
    return PulseProject(complex_id=cid, name=f"ЖК {cid}", latitude=55.9, longitude=37.7,
                        address=address, base=RUSSIA)


class FakePulse:
    """Заглушка клиента: те же методы, что у `PulseClient`, и счётчик вызовов."""

    def __init__(self, projects, *, prices, classes, sales=None, remaining=None,
                 history=None, base=RUSSIA, available=True):
        self._projects = projects
        self.prices = prices
        self.classes = classes
        self.sales_by_id = sales or {}
        self.remaining_by_id = remaining or {}
        self.history = history or {}
        self.sites = [SimpleNamespace(base=base)]
        self.base = base
        self.available = available
        self.errors: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def projects(self, **kwargs):
        return list(self._projects)

    def segments(self, **kwargs):
        return dict(self.classes)

    def price_history(self, ids, months=12):
        self.calls.append(("history", ",".join(ids)))
        return {cid: self.history[cid] for cid in ids if cid in self.history}

    def price(self, cid):
        self.calls.append(("price", cid))
        value = self.prices.get(cid)
        if value is None:
            return None
        return {"price_per_sqm": value, "observed_at": "2026-09-28", "lot_count": 40}

    def remaining(self, cid):
        self.calls.append(("remaining", cid))
        return self.remaining_by_id.get(cid, {})

    def sales(self, cid):
        self.calls.append(("sales", cid))
        return self.sales_by_id.get(cid)


def _mo_pulse(**overrides) -> FakePulse:
    projects = [
        _project("50-000001", "Московская область, г.о. Мытищи, ул. Мира, 1"),
        _project("50-000002", "Московская область, г.о. Мытищи, ул. Колпакова"),
        _project("50-000003", "Московская обл., г. Химки, ул. Лавочкина"),
        _project("50-000004", "Московская обл., Ленинский г.о., д. Сапроново"),
        # Без цены: в продаже нет, в медианы не входит.
        _project("50-000005", "Московская область, г.о. Мытищи, д. Пирогово"),
        # Чужой регион с ценой-выбросом: в свод МО попасть не должен.
        _project("77-000009", "Москва, Крылатская ул."),
        # Московский номер без кода региона — тоже не МО.
        _project("4184", "Московская область, г.о. Мытищи"),
    ]
    kwargs = dict(
        prices={"50-000001": 200_000, "50-000002": 240_000, "50-000003": 260_000,
                "50-000004": 300_000, "77-000009": 9_000_000, "4184": 9_000_000},
        classes={"50-000001": "Комфорт", "50-000002": "Комфорт", "50-000003": "Комфорт",
                 "50-000004": "Бизнес", "50-000005": "Комфорт",
                 "77-000009": "Комфорт", "4184": "Комфорт"},
        sales={
            "50-000001": {"units_per_month": 20, "area_per_month": 900.0},
            "50-000002": {"units_per_month": 10, "area_per_month": 500.0},
            # Темпа нет вовсе (ноль) — это не наблюдение темпа.
            "50-000003": {"units_per_month": 0, "area_per_month": 0},
            "50-000004": {"units_per_month": 5, "area_per_month": 350.0},
        },
        remaining={"50-000001": {"remaining_units": 100}, "50-000002": {"remaining_units": 50},
                   "50-000005": {"remaining_units": 7}},
        history={
            "50-000001": [{"month": "2026-08", "value": 190_000}, {"month": "2026-09", "value": 200_000}],
            "50-000002": [{"month": "2026-08", "value": 230_000}, {"month": "2026-09", "value": 240_000}],
            "50-000003": [{"month": "2026-09", "value": 260_000}],
        },
    )
    kwargs.update(overrides)
    return FakePulse(projects, **kwargs)


def _collector(pulse, tmp_path: Path, **kwargs) -> RegionMarketCollector:
    clock = kwargs.pop("clock", None) or (lambda: T0)
    return RegionMarketCollector(pulse, tmp_path / "pulse-regions", regions=["50"],
                                 pause_seconds=0, sleep=lambda s: None, clock=clock, **kwargs)


def test_the_region_summary_is_built_from_the_cabinet_only_for_its_region(tmp_path: Path) -> None:
    pulse = _mo_pulse()
    collector = _collector(pulse, tmp_path)
    outcome = collector.run_due()
    assert outcome["started"] is True and outcome["regions"]["50"]["complete"] is True

    summary = json.loads(collector.summary_path("50").read_text(encoding="utf-8"))
    comfort = summary["current"]["Комфорт"]
    # Медиана — по трём проектам МО с ценой; выброс Москвы и номер без кода
    # региона в свод не попали, проект без цены — тоже.
    assert comfort["projects"] == 3
    assert comfort["price_median"] == statistics.median([200_000, 240_000, 260_000])
    assert summary["current"]["Бизнес"]["price_median"] == 300_000
    asked = {cid for kind, cid in pulse.calls if kind == "price"}
    assert asked == {f"50-00000{n}" for n in range(1, 6)}
    # Средняя ступень — муниципалитет из адреса.
    assert set(summary["by_okrug"]) == {"Мытищи", "Химки", "Ленинский"}
    assert summary["by_okrug"]["Мытищи"]["Комфорт"]["projects"] == 2
    # Эталон поглощения: проект с нулевым темпом в медиану не входит.
    assert summary["area_median_by_segment"]["Комфорт"] == statistics.median([900.0, 500.0])
    assert summary["area_median_projects"]["Комфорт"] == 2
    # Помесячный ряд — из истории цены; продаж помесячно нет — None, не 0.
    row = summary["by_class"]["Комфорт"][-1]
    assert row["m"] == "2026-09" and row["n"] == 3 and row["price"] == 240_000
    assert row["sold"] is None and row["sold_sum"] is None and row["m2_sum"] is None
    # Подписи источника и покрытия.
    assert summary["source_kind"] == "cabinet" and summary["region"] == "50"
    assert "Московская область" in summary["source"]
    assert summary["coverage"] == {
        "projects_total": 5, "projects_answered": 5, "projects_on_sale": 4,
        "without_segment": 0, "without_municipality": 0, "failed": 0,
    }


def test_a_project_without_any_answer_is_counted_not_zeroed(tmp_path: Path) -> None:
    pulse = _mo_pulse()
    pulse.errors_on = "50-000002"
    original = pulse.price

    def price(cid):
        if cid == "50-000002":
            pulse.errors.append("price_stats 50-000002: HTTP 500")
            return None
        return original(cid)

    pulse.price = price
    pulse.sales_by_id.pop("50-000002")
    pulse.remaining_by_id.pop("50-000002")
    collector = _collector(pulse, tmp_path)
    collector.run_due()
    summary = json.loads(collector.summary_path("50").read_text(encoding="utf-8"))
    assert summary["coverage"]["failed"] == 1
    assert "HTTP 500" in summary["failed_sample"]["50-000002"]
    assert summary["current"]["Комфорт"]["projects"] == 2
    status = collector.status()["regions"][0]
    assert status["coverage"]["failed"] == 1 and status["collected_at"]


def test_the_limit_stops_a_pass_and_the_next_worker_continues(tmp_path: Path) -> None:
    pulse = _mo_pulse()
    first = _collector(pulse, tmp_path, limit=2)
    outcome = first.run_due()["regions"]["50"]
    assert outcome == {"ok": True, "complete": False, "done": 2, "total": 5}
    assert not first.summary_path("50").exists()
    assert first.status()["regions"][0]["in_progress"]["done"] == 2
    assert first.due("50") is True

    # Второй воркер (свой объект, своя память) продолжает с места обрыва.
    other = _mo_pulse()
    second = _collector(other, tmp_path, limit=10)
    assert second.run_due()["regions"]["50"]["complete"] is True
    asked = [cid for kind, cid in other.calls if kind == "price"]
    assert sorted(asked) == ["50-000003", "50-000004", "50-000005"]
    assert not second.progress_path("50").exists()


def test_the_collection_runs_once_a_week(tmp_path: Path) -> None:
    now = [T0]
    collector = _collector(_mo_pulse(), tmp_path, clock=lambda: now[0])
    assert collector.run_due()["regions"]["50"]["complete"] is True
    now[0] = T0 + 6 * 86400
    assert collector.due("50") is False
    assert collector.run_due() == {"started": True, "regions": {}}
    now[0] = T0 + INTERVAL_SECONDS + 60
    assert collector.due("50") is True


def test_without_the_russia_base_the_collector_says_so(tmp_path: Path) -> None:
    pulse = _mo_pulse(base=MOSCOW)
    collector = _collector(pulse, tmp_path)
    outcome = collector.run_due()
    assert outcome["started"] is False
    assert "russia.pulsprodaj.ru" in outcome["reason"] and "PULSE_BASE_URL" in outcome["reason"]
    assert pulse.calls == []
    row = collector.status()["regions"][0]
    assert row["reason"] == outcome["reason"] and row["collected_at"] is None
    # Отказ не записан как попытка: задали переменную — сбор идёт сразу.
    assert collector.due("50") is True


def test_a_region_absent_from_the_catalog_has_a_reason(tmp_path: Path) -> None:
    pulse = _mo_pulse()
    collector = RegionMarketCollector(pulse, tmp_path / "r", regions=["66"], pause_seconds=0,
                                      sleep=lambda s: None, clock=lambda: T0)
    outcome = collector.run_due()["regions"]["66"]
    assert outcome["ok"] is False and "66-NNNN" in outcome["reason"]
    assert "Свердловская" in collector.status()["regions"][0]["reason"]
    assert not collector.summary_path("66").exists()


def test_another_worker_holding_the_lock_is_not_disturbed(tmp_path: Path) -> None:
    collector = _collector(_mo_pulse(), tmp_path)
    collector.lock_path.parent.mkdir(parents=True, exist_ok=True)
    collector.lock_path.write_text("1")
    assert collector.run_due() == {"started": False, "reason": "Сбор уже идёт в другом воркере"}
    assert collector.status()["busy"] is True


def test_regions_are_a_setting_with_mo_first() -> None:
    assert configured_regions("") == ["50"]
    assert configured_regions("50, 78;47 ,xx") == ["50", "78", "47"]


@pytest.mark.parametrize(
    "address, name",
    [
        ("Московская область, г.о. Мытищи, ул. Мира", "Мытищи"),
        ("Московская обл., Ленинский г.о., д. Сапроново", "Ленинский"),
        ("Московская обл., г. Химки, ул. Лавочкина", "Химки"),
        ("Московская область, Красногорск, мкр. Опалиха", None),
        ("", None),
    ],
)
def test_the_municipality_is_read_only_from_an_explicit_mark(address, name) -> None:
    assert municipality_of(address) == name


def _region_file(tmp_path: Path) -> Path:
    collector = _collector(_mo_pulse(), tmp_path)
    collector.run_due()
    return collector.dir


def test_the_same_reader_serves_the_region_and_moscow_stays_from_the_report(tmp_path: Path) -> None:
    moscow = MoscowMarket({"current": {"Комфорт": {"projects": 49, "price_median": 458_900}},
                           "source": "отчёт", "last_month": "2026-09"})
    atlas = MarketAtlas(moscow, _region_file(tmp_path))

    assert atlas.for_address("г. Москва, ул. Ленина, 1") is moscow
    region = atlas.for_address("Московская область, г.о. Мытищи, ул. Летная")
    assert isinstance(region, RegionMarket)
    assert region.snapshot("Комфорт").price_median == 240_000
    assert region.area_median("Комфорт") == 700.0
    assert region.okrug("Мытищи", "Комфорт")["projects"] == 2
    assert region.okrug_of("МО, Химки, ул. Лавочкина") == "Химки"
    scope = atlas.scope("Московская область, г.о. Мытищи")
    assert scope["covered"] is True and scope["source_kind"] == "cabinet" and scope["region"] == "50"
    assert atlas.for_address("МО, Мытищи, Летная ул.") is region

    # Регион без свода: Москва не подставляется, причина названа.
    other = atlas.scope("Ленинградская область, г. Мурино")
    assert other["covered"] is False
    assert "Ленинградская область" in other["region"]["reason"]


def test_the_price_hint_names_the_region_not_moscow(tmp_path: Path) -> None:
    region = MarketAtlas(MoscowMarket({}), _region_file(tmp_path)).for_address(
        "Московская область, г.о. Мытищи"
    )
    by_place = price_hint(peers=[], segment="Комфорт", okrug="Мытищи", city=region)
    assert by_place["basis"] == BASIS_OKRUG and by_place["price_per_sqm"] == 220_000
    assert by_place["basis_title"] == "по муниципалитету и классу"
    by_region = price_hint(peers=[], segment="Комфорт", okrug="Дубна", city=region)
    assert by_region["basis"] == BASIS_CITY and by_region["price_per_sqm"] == 240_000
    assert "Московская область" in by_region["basis_title"] and "Москве" not in by_region["basis_title"]


def test_a_region_summary_without_projects_is_not_built_from_nothing() -> None:
    summary = build_region_market("50", {"50-1": {"segment": "Комфорт"}},
                                  collected_at="2026-10-06T00:00:00+00:00", projects_total=1)
    assert summary["current"] == {} and summary["coverage"]["projects_on_sale"] == 0
    assert not RegionMarket(summary).available


def test_the_regions_route_is_behind_the_cabinet_key(monkeypatch, tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from market_search.api import install

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKET_CABINET_KEY", "stand-key-2026")
    monkeypatch.delenv("PULSE_BASE_URL", raising=False)
    app = FastAPI()
    install(app)
    assert TestClient(app).get("/market/pulse/regions").status_code == 401
    opened = TestClient(app, headers={"X-Market-Key": "stand-key-2026"})
    answer = opened.get("/market/pulse/regions")
    assert answer.headers["content-type"] == "application/json; charset=utf-8"
    status = answer.json()
    assert "russia.pulsprodaj.ru" in status["blocker"]
    assert status["regions"][0]["region"] == "50" and status["interval_days"] == 7
    run = opened.post("/market/pulse/regions/run").json()
    assert run["started"] is False and "PULSE_BASE_URL" in run["reason"]
    assert opened.post("/market/pulse/regions/run", params={"region": "99"}).status_code == 400


def test_without_a_summary_the_address_gets_the_real_reason_not_old_moscow(tmp_path: Path) -> None:
    """Мытищи без свода: причина — состояние сбора, а не «Москва старая»."""
    moscow = MoscowMarket({"current": {"Комфорт": {"projects": 49, "price_median": 458_900}}})
    address = "Летная улица, 15, Мытищи, Московская область, Россия"

    # Всероссийская база не подключена — так и сказано.
    off = _collector(_mo_pulse(base=MOSCOW), tmp_path / "off")
    reason = MarketAtlas(moscow, off.dir, explain=off.explain).scope(address)["region"]["reason"]
    assert "Московская область" in reason and "russia.pulsprodaj.ru" in reason
    assert "Москва старая" not in reason

    # Сбор идёт — сколько из скольких.
    going = _collector(_mo_pulse(), tmp_path / "going", limit=2)
    going.run_due()
    reason = MarketAtlas(moscow, going.dir, explain=going.explain).scope(address)["region"]["reason"]
    assert "собирается" in reason and "2 из 5" in reason

    # Сбора ещё не было.
    fresh = _collector(_mo_pulse(), tmp_path / "fresh")
    reason = MarketAtlas(moscow, fresh.dir, explain=fresh.explain).scope("МО, Мытищи")["region"]["reason"]
    assert "ещё не собирался" in reason and "/market/pulse/regions/run" in reason

    # Регион не в настройке.
    reason = MarketAtlas(moscow, fresh.dir, explain=fresh.explain).scope(
        "Ленинградская область, г. Мурино")["region"]["reason"]
    assert "не включён в сбор" in reason and "PULSE_REGIONS=50" in reason

    # Свод готов — адрес покрыт, причины нет.
    fresh.run_due()
    scope = MarketAtlas(moscow, fresh.dir, explain=fresh.explain).scope(address)
    assert scope["covered"] is True and scope["source_kind"] == "cabinet"


def test_the_price_hint_in_mytishchi_names_the_region_reason(monkeypatch, tmp_path: Path) -> None:
    """То, что видит владелец под полем цены: не «Москва старая», а причина региона."""
    from market_search.service_v6 import MarketDiscoveryService

    monkeypatch.delenv("PULSE_BASE_URL", raising=False)
    service = MarketDiscoveryService(tmp_path)
    service.pulse = SimpleNamespace(
        available=True, segments=lambda: {}, near=lambda lat, lon, radius_km: [],
        metrics=lambda cid: {}, price=lambda cid: None, project_totals=lambda cid: {},
        find_project=lambda query: None, price_history=lambda ids, months=12: {},
        remaining=lambda cid: {},
    )
    hint = service.price_hint(address="Летная улица, 15, Мытищи, Московская область",
                              latitude=55.91, longitude=37.73)
    assert hint["available"] is False
    assert "Москва старая" not in hint["reason"]
    assert "Свода по региону «Московская область» нет" in hint["reason"]
    assert "russia.pulsprodaj.ru" in hint["reason"]
    # «Соседей нет» тоже с причиной: в радиусе пусто — так и сказано.
    assert "не нашёл ни одного проекта" in hint["reason"]
    assert hint["peer_search"]["found"] == 0


def test_neighbours_without_a_price_are_counted_in_the_reason(monkeypatch, tmp_path: Path) -> None:
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    near = [(0.5, _project("50-000001", "Московская область, г.о. Мытищи")),
            (0.9, _project("50-000002", "Московская область, г.о. Мытищи"))]
    service.pulse = SimpleNamespace(
        available=True, segments=lambda: {}, near=lambda lat, lon, radius_km: near,
        price=lambda cid: None, errors=["price_stats 50-000002: HTTP 502"],
    )
    original = service.pulse.price

    def price(cid):
        service.pulse.errors.append(f"price_stats {cid}: HTTP 502")
        return original(cid)

    service.pulse.errors = []
    service.pulse.price = price
    hint = service.price_hint(address="Мытищи, Московская область", latitude=55.91, longitude=37.73)
    assert hint["peer_search"]["found"] == 2 and hint["peer_search"]["without_price"] == 2
    assert "проектов «Пульса» 2" in hint["reason"] and "без цены 2" in hint["reason"]
    assert "HTTP 502" in hint["reason"]
