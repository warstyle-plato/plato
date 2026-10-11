"""Мытищи: соседи берут цену у всероссийского кабинета, регион — у участка.

Две поломки одной жалобы (#657). Первая: проект области, пришедший из обоих
кабинетов, принадлежал первой базе списка — московской, а она на цену и темп
проекта области отвечает 403. Вторая: страница шлёт точку участка без
адреса, и регион для свода искался в строке «шир., долг.» — не находился.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from market_search.pulse import PulseNetwork, PulseProject
from market_search.region_market import RegionMarketCollector

from tests.test_pulse_region_market import T0, _mo_pulse

RUSSIA = "https://russia.pulsprodaj.ru"
MOSCOW = "https://pulsprodaj.ru"
LAT, LON = 55.9105, 37.7360  # Мытищи
MYTISHCHI = "Московская область, г.о. Мытищи, ул. Колпакова"


class Site:
    """Одна база «Пульса»: свой справочник, свои ответы, счёт вопросов."""

    def __init__(self, base: str, projects, *, prices=None, refuse: bool = False):
        self.base = base
        self._projects = [PulseProject(**{**row, "base": base}) for row in projects]
        self.prices = prices or {}
        self.refuse = refuse
        self.available = True
        self.errors: list[str] = []
        self.asked: list[tuple[str, str]] = []

    def projects(self, **kwargs):
        return list(self._projects)

    def segments(self, **kwargs):
        return {item.complex_id: "Комфорт" for item in self._projects}

    def _answer(self, name: str, cid: str):
        self.asked.append((name, cid))
        if self.refuse:
            self.errors.append(f"/api/app/complex/{name}/: HTTP Error 403: FORBIDDEN")
            return None
        return None

    def price(self, cid):
        if self.refuse:
            return self._answer("price_stats", cid)
        self.asked.append(("price_stats", cid))
        value = self.prices.get(cid)
        return {"price_per_sqm": value, "observed_at": "2026-10-01", "lot_count": 30} if value else None

    def sales(self, cid):
        return self._answer("sales", cid)

    def __getattr__(self, name):
        # Карточка, сроки, стадия — в этих тестах пусто у обеих баз.
        return lambda *args, **kwargs: {}


def _row(cid: str, name: str, shift: float = 0.0) -> dict:
    return {"complex_id": cid, "name": name, "latitude": LAT + shift,
            "longitude": LON, "address": MYTISHCHI}


def _network() -> tuple[PulseNetwork, Site, Site]:
    rows = [_row("4184", "ЖК Мытищи Парк"), _row("4185", "ЖК Летный", 0.005)]
    # Порядок как на проде: московская база первой. Те же номера — в обеих.
    moscow = Site(MOSCOW, rows, refuse=True)
    russia = Site(RUSSIA, rows, prices={"4184": 210_000, "4185": 230_000})
    return PulseNetwork([moscow, russia]), moscow, russia


def test_a_mo_project_from_both_cabinets_is_asked_at_the_russia_one() -> None:
    network, moscow, russia = _network()

    assert network.price("4184")["price_per_sqm"] == 210_000
    near = network.near(LAT, LON, 2.5)
    assert [item.base for _, item in near] == [RUSSIA, RUSSIA]
    # Московский кабинет проект области не спрашивается вовсе: 403 там нет.
    assert moscow.asked == [] and moscow.errors == []


def test_a_moscow_project_keeps_the_order_and_a_silent_owner_falls_back() -> None:
    row = {**_row("77", "ЖК Москва"), "address": "г. Москва, ул. Ленина, 1"}
    moscow = Site(MOSCOW, [row], prices={"77": 400_000})
    russia = Site(RUSSIA, [row], prices={"77": 1})
    network = PulseNetwork([moscow, russia])
    assert network.price("77")["price_per_sqm"] == 400_000
    assert network.near(LAT, LON, 1)[0][1].base == MOSCOW

    # Владелец промолчал — спрашивается вторая база с тем же проектом.
    silent = Site(MOSCOW, [row], refuse=True)
    network = PulseNetwork([silent, Site(RUSSIA, [row], prices={"77": 390_000})])
    assert network.price("77")["price_per_sqm"] == 390_000


def test_the_site_region_comes_from_the_cadastre_then_the_point_then_the_address() -> None:
    from market_search.region_market import site_region

    near = [(0.4, PulseProject("4184", "ЖК", LAT, LON, address=MYTISHCHI))]
    by_cad = site_region(cadastre="50:12:0100105:1234", neighbours=near, address="г. Москва")
    assert (by_cad["code"], by_cad["name"], by_cad["source"]) == ("50", "Московская область", "cadastre")
    by_point = site_region(neighbours=near, address=f"{LAT}, {LON}")
    assert (by_point["name"], by_point["source"]) == ("Московская область", "point")
    assert site_region(address="МО, Мытищи")["source"] == "address"
    assert site_region(address=f"{LAT}, {LON}") is None
    # Районы Новой Москвы хранят номер области: по префиксу регион не решается.
    assert site_region(cadastre="50:21:0120316:777") is None


def _service(tmp_path: Path, pulse):
    from market_search.service_v6 import MarketDiscoveryService

    # Свод Московской области — тем же сбором, что на проде, в каталог сервиса.
    RegionMarketCollector(_mo_pulse(), tmp_path / "pulse-regions", regions=["50"],
                          pause_seconds=0, sleep=lambda s: None, clock=lambda: T0).run_due()
    service = MarketDiscoveryService(tmp_path)
    service.pulse = pulse
    return service


def test_mytishchi_point_with_cadastre_gets_the_mo_class_summary(tmp_path: Path) -> None:
    """Страница шлёт точку и кадастр, адреса с областью нет — свод МО всё равно выбран."""
    empty = SimpleNamespace(available=True, errors=[], segments=lambda: {},
                            near=lambda lat, lon, radius_km: [], price=lambda cid: None)
    hint = _service(tmp_path, empty).price_hint(
        address=None, latitude=LAT, longitude=LON, segment="Комфорт",
        cadastral="50:12:0100105:1234",
    )
    assert hint["available"] is True, hint.get("reason")
    assert hint["basis_title"] == "по классу: Московская область"
    assert hint["location"]["region"]["source"] == "cadastre"
    assert "адрес с областью" not in str(hint)


def test_mytishchi_point_alone_gets_priced_neighbours_and_the_mo_summary(tmp_path: Path) -> None:
    """Жалоба владельца целиком: только точка участка, московская база первой."""
    network, moscow, _ = _network()
    hint = _service(tmp_path, network).price_hint(address=None, latitude=LAT, longitude=LON)
    assert hint["peer_search"]["with_price"] == 2, hint.get("reason")
    assert not any("403" in text for text in hint["peer_search"]["errors"])
    assert hint["location"]["city_reference"] is True
    assert hint["location"]["region"]["name"] == "Московская область"
    assert moscow.asked == []
