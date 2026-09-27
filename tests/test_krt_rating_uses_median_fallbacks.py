"""Regression: catalogue ratings stay numeric when some inputs are estimated.

Measured project/local-market facts still define coverage. Missing inputs may
use explicitly labelled medians so one absent field does not erase the whole
ranking. Estimates must never be persisted back as project facts.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import api, krt_investment_score  # noqa: E402
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


def test_api_uses_city_and_catalogue_medians_without_overwriting_facts() -> None:
    source = inspect.getsource(api.install)
    route = source[
        source.index("def _rating_catalogue_medians"):
        source.index("async def auction_krt_nagatino_live_data")
    ]

    assert "_city_rating_reference" in route
    assert 'median_of("project_llcr_x"' in route
    assert 'median_of("burden_pct"' in route
    assert 'score_local_absorption = score_benchmark_absorption' in route
    assert 'score_burden_pct = item.get("value")' in route
    # The estimate affects the score, not the factual burden field in ranking.json.
    assert '"burden_pct": burden_pct' in route
    assert '"burden_pct": score_burden_pct' not in route


def test_catalogue_marks_median_based_ratings_as_estimated() -> None:
    page = auctions_page()
    assert "% факта" in page
    assert "медиана:" in page
    assert "с медианой" in page
