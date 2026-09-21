from __future__ import annotations

import pytest

from auction_search import nagatino_parcels
from auction_search.krt_investment_score import (
    _nagatino_cost_stack,
    absorption_points,
    burden_points,
    llcr_points,
    methodology,
    price_points,
    score,
)
from auction_search.krt_score_lab import krt_score_lab_page


def test_running_krt_stays_visible_but_has_no_score() -> None:
    page = krt_score_lab_page()
    assert '<option value="running">В реализации</option>' in page
    assert "status_kind!=='running'" not in page
    assert "В реализации · без балла" in page

    got = score(
        status_kind="running",
        llcr=1.30,
        market_rub_sqm=700_000,
        target_rub_sqm=600_000,
        local_sqm_month=10_000,
        benchmark_sqm_month=6_000,
        burden_pct=0,
    )
    assert got["score"] is None
    assert got["coverage_pct"] == 100
    assert "балл не присваивается" in got["reason"]


def test_lab_has_one_price_scenario_control_and_no_weight_sliders() -> None:
    page = krt_score_lab_page()
    assert "Ценовой ориентир, ₽/м²" in page
    assert 'id="target"' in page
    assert 'type="range"' not in page
    assert "Вес по умолчанию" not in page
    assert "фиксированная методика 40/20/20/20".casefold() in page.casefold()


def test_fixed_score_breakpoints() -> None:
    assert llcr_points(0.99) == 0
    assert llcr_points(1.00) == 0
    assert llcr_points(1.10) == 10
    assert llcr_points(1.20) == 30
    assert llcr_points(1.30) == 40
    assert llcr_points(1.40) == 40

    assert price_points(420_000, 600_000) == pytest.approx(0)
    assert price_points(480_000, 600_000) == pytest.approx(5)
    assert price_points(540_000, 600_000) == pytest.approx(12)
    assert price_points(600_000, 600_000) == pytest.approx(20)

    assert absorption_points(5_000, 10_000) == pytest.approx(0)
    assert absorption_points(10_000, 10_000) == pytest.approx(10)
    assert absorption_points(15_000, 10_000) == pytest.approx(20)

    assert burden_points(0) == pytest.approx(20)
    assert burden_points(5) == pytest.approx(18)
    assert burden_points(10) == pytest.approx(14)
    assert burden_points(20) == pytest.approx(5)
    assert burden_points(30) == pytest.approx(0)


def test_missing_component_does_not_get_renormalised_to_a_full_score() -> None:
    got = score(
        status_kind="planned",
        llcr=1.25,
        market_rub_sqm=650_000,
        target_rub_sqm=600_000,
        local_sqm_month=None,
        benchmark_sqm_month=None,
        burden_pct=8,
    )
    assert got["score"] is None
    assert got["coverage_pct"] == 80
    assert "absorption" in got["reason"]


def test_methodology_is_the_browser_source_of_thresholds() -> None:
    rules = methodology()
    assert rules["weights"] == {"llcr": 40, "price": 20, "absorption": 20, "burden": 20}
    assert rules["rules"]["running"] == "visible_unscored"
    assert rules["rules"]["buyout"] == "non_moscow_cadastral_value"
    assert rules["rules"]["moscow_property"] == "zero_buyout"
    assert rules["rules"]["absorption_unit"] == "sqm_per_month"


def test_nagatino_cadastral_buyout_is_non_moscow_egrn_value() -> None:
    stack = _nagatino_cost_stack()
    buy = nagatino_parcels.buyout()
    expected = (
        float(buy["others"]["land_value_rub"])
        + float(buy["others"]["objects_value_rub"])
    ) / 1_000_000
    city = (
        float(buy["city"]["land_value_rub"])
        + float(buy["city"]["objects_value_rub"])
    ) / 1_000_000
    assert stack["cadastral_buyout_mln"] == pytest.approx(expected, abs=0.001)
    assert stack["moscow_cadastral_excluded_mln"] == pytest.approx(city, abs=0.001)
    assert stack["housing_gfa_sqm"] > 0
    assert stack["total_known_mln"] >= stack["cadastral_buyout_mln"]


def test_lab_reuses_current_catalogue_and_ranking_without_refresh() -> None:
    page = krt_score_lab_page()
    assert "fetch('/auctions/krt-lab/data?ts='" in page
    assert "/ranking/refresh" not in page
    assert "?refresh=true" not in page
