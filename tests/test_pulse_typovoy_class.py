"""«Типовой» всероссийского кабинета — наш «Стандарт/Эконом»; «Атлантис» — один.

Решение владельца 12.10.2026. Всероссийский кабинет «Пульса» пишет класс
словом объекта: «Типовой», «Комфорт», «Бизнес», «Элитный», «Другое». Наш класс
— метка фильтра московского кабинета («Стандарт/Эконом»). Слово «Типовой»
проходило как есть: в своде МО появлялся класс «Типовой», которого не спросит
ни один участок, — 233 ЖК Московской области выпадали из свода «Стандарт/Эконом»
и из сравнения классов у соседей.

«Атлантис» в Мытищах приходил дважды: московский кабинет («4033») пишет его
адрес «г.о. Мытищи, мкр.10-10а…» — без области, и снятие проектов региона,
который отвечает всероссийский кабинет, его не узнавало.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from market_search.pulse import PulseNetwork, PulseProject, pulse_class
from market_search.region_market import RegionMarketCollector, build_region_market

from tests.test_pulse_russia_api import LAT, LON, MOSCOW, Cabinet, _russia

ECONOMY = "Стандарт/Эконом"


@pytest.mark.parametrize(
    "word, ours",
    [
        ("Типовой", ECONOMY),
        ("Комфорт", "Комфорт"),
        ("Бизнес", "Бизнес"),
        ("Элитный", "Элит/De Luxe"),
        # Свои метки карта узнаёт: сохранённый сбор мог их уже перевести.
        (ECONOMY, ECONOMY),
        # Незнакомое слово и склейка объектов — не класс.
        ("Другое", None),
        ("Комфорт, Типовой", None),
        ("Типовая застройка", None),
        ("", None),
        (None, None),
    ],
)
def test_the_class_map_is_explicit(word, ours) -> None:
    assert pulse_class(word) == ours


def test_typovoy_neighbours_are_standard_economy(tmp_path: Path, monkeypatch) -> None:
    client, _ = _russia(tmp_path, monkeypatch)
    classes = client.segments()
    assert classes["50-c350471"] == ECONOMY  # Ярославский, «Типовой»
    assert classes["50-c350624"] == "Бизнес"
    assert "Типовой" not in classes.values()
    # Слово кабинета не теряется: оно видно для расшифровки.
    assert client.segment_raw("50-c350471") == "Типовой"


def test_a_card_cached_before_the_map_is_read_through_it(tmp_path: Path, monkeypatch) -> None:
    client, _ = _russia(tmp_path, monkeypatch)
    client.segments()
    cards = json.loads(client._cards_path.read_text(encoding="utf-8"))
    cards["50-c350471"]["segment"] = "Типовой"  # как записал бы старый код
    client._cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
    assert client.segments(fetch=False)["50-c350471"] == ECONOMY


def test_typovoy_is_in_the_region_summary_as_standard_economy(tmp_path: Path, monkeypatch) -> None:
    russia, _ = _russia(tmp_path / "pulse", monkeypatch, Cabinet(distinct=True))
    collector = RegionMarketCollector(
        russia, tmp_path / "regions", regions=["50"], pause_seconds=0, sleep=lambda s: None,
        clock=lambda: 1_791_158_400.0,  # 2026-10-05
    )
    assert collector.collect("50")["complete"] is True
    summary = json.loads(collector.summary_path("50").read_text(encoding="utf-8"))
    assert "Типовой" not in summary["current"]
    assert summary["current"][ECONOMY]["projects"] == 2  # оба «Ярославских»
    assert summary["coverage"]["unknown_classes"] == {}


def test_an_unknown_class_word_is_seen_not_turned_into_a_class() -> None:
    def record(segment, **extra):
        return {"segment": segment, "price_per_sqm": 200_000, "price_observed_at": "2026-10-01", **extra}

    summary = build_region_market(
        "50",
        {
            # Сохранённый до карты сбор: слово кабинета в поле класса.
            "50-c1": record("Типовой"),
            "50-c2": record(ECONOMY),
            "50-c3": record("Другое"),
            "50-c4": record(None, segment_raw="Другое"),
            "50-c5": record(None, segment_raw="Комфорт, Типовой"),
        },
        collected_at="2026-10-05T00:00:00+00:00",
        projects_total=5,
    )
    assert set(summary["current"]) == {ECONOMY}
    assert summary["current"][ECONOMY]["projects"] == 2
    assert summary["coverage"]["without_segment"] == 3
    assert summary["coverage"]["unknown_classes"] == {"Другое": 2}


def _moscow(*items: PulseProject, asked: list | None = None):
    def price(cid):
        # Московский кабинет на цену ЖК области отвечает 403 (price_stats).
        (asked if asked is not None else []).append(cid)
        return None

    return SimpleNamespace(
        base=MOSCOW, errors=[], available=True, projects=lambda **kw: list(items), price=price,
    )


def test_atlantis_without_a_region_in_its_moscow_address_is_one_neighbour(tmp_path: Path, monkeypatch) -> None:
    russia, _ = _russia(tmp_path, monkeypatch)
    atlantis = next(item for item in russia.projects() if item.complex_id == "50-c350624")
    asked: list[str] = []
    moscow = _moscow(
        # Живой адрес московского кабинета: области в нём нет.
        PulseProject(
            "4033", "Атлантис", atlantis.latitude, atlantis.longitude,
            address="г.о. Мытищи, мкр.10-10а, в р-не расположения жилых домов 62, 64, 66, 68 "
                    "по Новомытищинскому пр-ту",
            base=MOSCOW,
        ),
        asked=asked,
    )
    network = PulseNetwork([russia, moscow])
    names = [item.name for _, item in network.near(LAT, LON, 2.5)]
    assert names.count("Атлантис") == 1
    assert network.superseded == {"50": 1}
    kept = next(item for _, item in network.near(LAT, LON, 2.5) if item.name == "Атлантис")
    assert kept.complex_id == "50-c350624"
    # Цены соседей — только у всероссийского кабинета: 403 московского
    # («pulsprodaj.ru: /api/app/complex/price_stats/») давал именно дубль.
    for _, item in network.near(LAT, LON, 2.5):
        network.price(item.complex_id)
    assert asked == []


def test_a_namesake_elsewhere_or_another_name_at_the_point_is_not_a_twin(tmp_path: Path, monkeypatch) -> None:
    russia, _ = _russia(tmp_path, monkeypatch)
    atlantis = next(item for item in russia.projects() if item.complex_id == "50-c350624")
    moscow = _moscow(
        # Тёзка в километре — другой ЖК.
        PulseProject("1", "Атлантис", atlantis.latitude + 0.01, atlantis.longitude, address="г.о. Мытищи", base=MOSCOW),
        # Другое имя в той же точке — тоже не двойник.
        PulseProject("2", "Ньютон", atlantis.latitude, atlantis.longitude, address="г.о. Мытищи", base=MOSCOW),
    )
    network = PulseNetwork([russia, moscow])
    ids = {item.complex_id for item in network.projects()}
    assert {"1", "2"} <= ids
    assert network.superseded == {}


def test_a_summary_collected_by_another_class_map_is_due_at_once(tmp_path: Path, monkeypatch) -> None:
    """Свод на проде собран до карты: «Типовой» в нём ждал бы недели."""
    russia, _ = _russia(tmp_path / "pulse", monkeypatch, Cabinet(distinct=True))
    collector = RegionMarketCollector(
        russia, tmp_path / "regions", regions=["50"], pause_seconds=0, sleep=lambda s: None,
        clock=lambda: 1_791_158_400.0,  # 2026-10-05
    )
    collector.collect("50")
    assert collector.due("50") is False
    path = collector.summary_path("50")
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary.pop("class_map")
    path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    assert collector.due("50") is True


def _hint(tmp_path: Path, monkeypatch, segment):
    from market_search.service_v6 import MarketDiscoveryService

    monkeypatch.setenv("PULSE_BASE_URL", "https://russia.pulsprodaj.ru")
    russia, _ = _russia(tmp_path / "pulse", monkeypatch, Cabinet(distinct=True))
    service = MarketDiscoveryService(tmp_path)
    service.pulse = russia
    return service.price_hint(address=None, latitude=LAT, longitude=LON, segment=segment, include_projects=True)


def test_the_chosen_class_selects_the_neighbours_of_the_price_hint(tmp_path: Path, monkeypatch) -> None:
    """Прод 0.25.59, Мытищи: «Стандарт» давал 4 соседа — только «Комфорт».

    Соседи «Типовой» не узнавались ни одним классом и выпадали из ориентира с
    причиной «класс Типовой не сопоставим»: у «Стандарт/Эконом» не было ни
    одного своего соседа, а «Комфорт» и «Бизнес» видели одну и ту же выборку.
    """
    economy = _hint(tmp_path / "e", monkeypatch, ECONOMY)
    rows = {row["name"]: row for row in economy["projects"]}
    assert rows["Ярославский"]["segment"] == ECONOMY
    assert rows["Ярославский"]["eligible"] is True, rows["Ярославский"]["excluded_reason"]
    assert rows["Атлантис"]["eligible"] is False  # Бизнес через ступень от эконома

    business = _hint(tmp_path / "b", monkeypatch, "Бизнес")
    rows = {row["name"]: row for row in business["projects"]}
    assert rows["Ярославский"]["eligible"] is False
    assert rows["Атлантис"]["eligible"] is True
