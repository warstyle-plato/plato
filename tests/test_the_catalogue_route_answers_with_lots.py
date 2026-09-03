"""Маршрут каталога торгов проходится целиком — с лотами, а не только пустой.

27.08.2026 торги отвечали 500 на любой непустой каталог: в `auction_search/api.py`
не было импорта `profile_fit`, и сборка ответа падала на `NameError` — то есть
ровно там, где лот есть. Пустой каталог при этом отвечал исправно, и ни одна
проверка мимо не проходила: соответствие профилю проверялось вызовом функции
напрямую, а маршрут с лотом не звал никто.

Отсюда правило проверки: маршрут, который собирает ответ из элементов, обязан
быть пройден С элементом. Пустой ответ проходит мимо всей сборки.

Рядом закреплено второе: один недоступный источник не отменяет остальные.
Прежде его исключение доходило до маршрута, тот отвечал 502, и каталог пропадал
целиком — из-за одной площадки, у которой моргнула сеть.

Запуск: python3 -m pytest tests/test_the_catalogue_route_answers_with_lots.py -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auction_search import api as auction_api
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind
from auction_search.service import AuctionSearchService


def _lot() -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.LOT_ONLINE,
            lot_url="https://catalog.lot-online.ru/example",
            external_lot_id="RAD-TEST",
            fetched_at="2026-08-21T18:00:00Z",
        ),
        lot_kind=LotKind.LAND_SALE,
        title="Участок под застройку",
        land_area_sqm=5000,
        address="Москва, Коммунарка",
        cadastral_numbers=["77:01:0004023:1"],
        start_price_rub=250_000_000,
        application_deadline="2026-12-01T00:00:00Z",
    )


class _One:
    """Источник, у которого лот есть."""

    platform_name = "Тестовая площадка"

    def discover_moscow(self, *, deadline=None):
        return [_lot()]

    def fetch_lot(self, lot_url: str):  # pragma: no cover — не зовётся
        raise NotImplementedError


class _Broken:
    """Источник, у которого моргнула сеть."""

    platform_name = "Недоступная площадка"

    def discover_moscow(self, *, deadline=None):
        raise OSError("сеть не ответила")

    def fetch_lot(self, lot_url: str):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture()
def client(monkeypatch):
    import main_registry

    return TestClient(main_registry.app, raise_server_exceptions=False)


def test_a_catalogue_with_a_lot_answers_two_hundred(client, monkeypatch):
    """Пустой ответ проходит мимо всей сборки — проверять надо с лотом."""
    monkeypatch.setattr(auction_api, "_discovery_adapters", lambda source="all": [_One()])
    got = client.get("/auctions/discover?source=all")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["count"] == 1
    # Сверяются счётчики воронки, а не состав словаря: у отчёта с 03.09.2026
    # своя строка про КРТ, и равенство целиком упало бы при верном поведении.
    # Это уже второй экземпляр той же хрупкой проверки — утверждение здесь про
    # числа, а не про то, что к отчёту нельзя ничего добавить.
    quality = body["quality"]
    assert {key: quality[key] for key in
            ("seen", "accepted", "incomplete", "outside_profile", "noise")} == {
        "seen": 1,
        "accepted": 1,
        "incomplete": 0,
        "outside_profile": 0,
        "noise": 0,
    }
    row = body["lots"][0]
    for key in ("fit", "quality", "screening", "analysis"):
        assert key in row, key
    assert isinstance(row["fit"], dict) and "fit" in row["fit"], row["fit"]
    assert row["quality"]["accepted"] is True


def test_a_broken_source_does_not_take_the_others_with_it(client, monkeypatch):
    """Каталог пропадал целиком из-за одной площадки."""
    monkeypatch.setattr(
        auction_api, "_discovery_adapters", lambda source="all": [_Broken(), _One()])
    got = client.get("/auctions/discover?source=all")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["count"] == 1, "живой источник обязан доехать"
    said = " ".join(str(report.get("reason", "")) for report in body["coverage"])
    assert "не ответил" in said, "молча выброшенный источник читается как «лотов нет»"


def test_the_failure_is_named_not_swallowed():
    """Причина отказа источника — часть ответа, а не строка в логе."""
    broken = _Broken()
    AuctionSearchService([broken]).discover_moscow(budget_seconds=5)
    assert "не ответил" in broken.last_report["reason"]
    assert "OSError" in broken.last_report["reason"]


def test_every_source_gets_its_own_row_in_the_coverage(client, monkeypatch):
    """Экран читал только первый отчёт списка и печатал его ключами: про
    четыре источника из пяти на нём не было ничего, включая их отказы."""
    monkeypatch.setattr(
        auction_api, "_discovery_adapters", lambda source="all": [_Broken(), _One()])
    body = client.get("/auctions/discover?source=all").json()
    names = [row.get("source") for row in body["coverage"]]
    assert "Недоступная площадка" in names
    assert "Тестовая площадка" in names, "живой источник тоже обязан назваться"


def test_the_screen_prints_all_the_rows_not_the_first():
    from auction_search import ui

    body = ui.AUCTIONS_PAGE[ui.AUCTIONS_PAGE.index("function renderCoverage(){"):]
    body = body[:body.index("\nfunction areaLine(")]
    assert "state.coverage||[]" in body
    assert "coverage)[0]" not in body and "coverage||[])[0]" not in body, \
        "читается первый отчёт, остальные источники молчат"
    assert "forEach" in body, "строка на каждый источник"
    assert "x.why" in body, "причина отказа доезжает до экрана"
