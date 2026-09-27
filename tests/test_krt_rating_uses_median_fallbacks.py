"""Regression: catalogue ratings stay numeric when some inputs are estimated.

Measured project/local-market facts still define coverage. Missing inputs may
use explicitly labelled medians so one absent field does not erase the whole
ranking. Estimates must never be persisted back as project facts.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_investment_score  # noqa: E402
from auction_search.ui import auctions_page  # noqa: E402


def test_imputed_components_keep_a_numeric_rating_and_honest_coverage() -> None:
    got = krt_investment_score.score(
        status_kind="planned",
        llcr=1.22,
        market_rub_sqm=650_000,
        target_rub_sqm=600_000,
        local_sqm_month=800,
        benchmark_sqm_month=800,
        burden_pct=10,
        observed_components={"llcr", "price"},
        imputed_components={
            "absorption": "медиана поглощения Москвы, Бизнес",
            "burden": "медиана нагрузки рассчитанных КРТ, n=12",
        },
    )

    assert got["display_score"] is not None
    assert got["coverage_pct"] == 50
    assert {item["component"] for item in got["imputed"]} == {"absorption", "burden"}
    assert got["components"]["absorption"]["estimated"] is True
    assert got["components"]["burden"]["estimated"] is True


def test_genuinely_unresolved_input_can_still_be_null() -> None:
    got = krt_investment_score.score(
        status_kind="planned",
        llcr=1.22,
        market_rub_sqm=650_000,
        local_sqm_month=None,
        benchmark_sqm_month=None,
        burden_pct=None,
    )
    assert got["display_score"] is None
    assert set(got["missing"]) == {"absorption", "burden"}


# Что маршрут и фон подставляют медианы и не пишут их фактом площадки,
# проверяется поведением: tests/test_the_krt_rating_has_one_assembly.py.


def test_catalogue_marks_median_based_ratings_as_estimated() -> None:
    page = auctions_page()
    assert "% факта" in page
    assert "медиана:" in page
    assert "с медианой" in page


def test_a_deferred_component_is_named_and_the_rest_is_scored() -> None:
    got = krt_investment_score.score(
        status_kind="planned",
        llcr=1.30,
        market_rub_sqm=600_000,
        target_rub_sqm=600_000,
        local_sqm_month=800,
        benchmark_sqm_month=800,
        burden_pct=None,
        deferred_components={"burden": "медиана нагрузки по 1 площадке"},
    )
    assert got["display_score"] == round((100 + 100 + 75) / 3)
    assert got["deferred"] == [{"component": "burden", "reason": "медиана нагрузки по 1 площадке"}]
    assert got["missing"] == []
    assert "/ 3" in got["arithmetic"]


def test_two_deferred_components_are_not_a_rating() -> None:
    got = krt_investment_score.score(
        status_kind="planned", llcr=1.30, market_rub_sqm=600_000,
        local_sqm_month=None, benchmark_sqm_month=None, burden_pct=None,
        deferred_components={"burden": "мало площадок", "absorption": "мало площадок"},
    )
    assert got["display_score"] is None
    assert "минимум по 3 из 4" in got["reason"]
