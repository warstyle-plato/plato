"""Расшифровка рекомендации цены: состав аналогов и стадийная поправка."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from market_search import price_hint_ui, stage
from market_search.pulse import PulseProject
from market_search.service_v6 import MarketDiscoveryService


def test_calendar_stage_is_explicitly_a_proxy() -> None:
    assert stage.calendar_progress("2026-01-01", "2026-11-01", "2026-06-01") == 0.5
    assert stage.calendar_stage_label(0.5) == "середина цикла"
    assert stage.calendar_progress(None, "2026-11-01", "2026-06-01") is None


def test_price_hint_can_return_the_projects_behind_the_number(
    tmp_path: Path, monkeypatch
) -> None:
    service = MarketDiscoveryService(tmp_path)
    service.pulse.login = "x"
    service.pulse.password = "x"
    service.verified_prices.today = date(2026, 9, 22)

    projects = [
        PulseProject(1, "A", 55.75, 37.60, developer="Dev A"),
        PulseProject(2, "B", 55.751, 37.601, developer="Dev B"),
        PulseProject(3, "C", 55.752, 37.602, developer="Dev C"),
    ]
    monkeypatch.setattr(
        service.pulse,
        "near",
        lambda *_args, **_kwargs: [(0.4, projects[0]), (0.8, projects[1]), (1.2, projects[2])],
    )
    monkeypatch.setattr(service.pulse, "segments", lambda: {1: "Бизнес", 2: "Бизнес", 3: "Бизнес"})
    prices = {1: 600_000, 2: 620_000, 3: 640_000}
    monkeypatch.setattr(
        service.pulse,
        "price",
        lambda complex_id: {
            "price_per_sqm": prices[complex_id],
            "price_per_sqm_min": prices[complex_id] - 20_000,
            "price_per_sqm_max": prices[complex_id] + 20_000,
            "lot_count": 20,
            "observed_at": "2026-09-01",
        },
    )
    cards = {
        1: {"sales_start": "2025-01-01", "commissioning": "2027-01-01"},
        2: {"sales_start": "2025-03-01", "commissioning": "2027-03-01"},
        3: {"sales_start": "2025-05-01", "commissioning": "2027-05-01"},
    }
    monkeypatch.setattr(service.cards, "card", lambda complex_id: cards[complex_id])
    monkeypatch.setattr(service.dynamics, "latest", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(service.dynamics, "series", lambda *_args, **_kwargs: [])

    got = service.price_hint(
        address="Москва",
        latitude=55.75,
        longitude=37.60,
        radius_km=2.5,
        include_projects=True,
    )

    assert got["basis"] == "peers"
    assert got["price_per_sqm"] == 620_000
    assert [row["name"] for row in got["projects"]] == ["A", "B", "C"]
    assert all(row["eligible"] for row in got["projects"])
    assert all(row["ready_equivalent_price"] for row in got["projects"])
    assert got["stage_model"]["available"] is True
    assert got["stage_model"]["price_per_sqm"] < got["stage_model"]["ready_price_per_sqm"]


def test_breakdown_page_has_manual_exclusions_and_project_summary() -> None:
    html = price_hint_ui.page()
    assert "/market/price-hint/details" in html
    assert 'class="use"' in html
    assert "Вернуть автоматический состав" in html
    assert "projectDialog" in html
    assert "Старт продаж" in html
    assert "Плановый ввод" in html
    assert "прокси стадии реализации" in html
