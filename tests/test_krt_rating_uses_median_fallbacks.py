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
    # Сама политика подстановок живёт в методике — там её проверяют без
    # приложения; маршрут только читает наблюдения каталога и зовёт её.
    policy = inspect.getsource(krt_investment_score.rating_inputs)
    assert 'score_local_absorption = score_benchmark_absorption' in policy
    assert 'score_burden_pct = value' in policy
    assert "catalogue_medians=_rating_catalogue_medians()" in route
    assert "city_reference=_city_rating_reference(segment)" in route
    # Подстановка влияет на БАЛЛ, а не на фактовое поле строки: в ranking.json
    # едет измеренная нагрузка, а не медиана. Проверяется на самом блоке
    # записи, а не по всему срезу: имя score_burden_pct законно стоит рядом —
    # в политике подстановок, откуда балл берёт свои входы.
    remembered = route[route.index('"investment_rating": stored_rating'):]
    assert '"burden_pct": burden_pct' in remembered
    assert "score_burden_pct" not in remembered
    # Политика подстановок одна на оба пересчёта, и зовут её и кнопка, и фон.
    assert source.count("def _rating_score_inputs") == 1
    assert source.count("policy = _rating_score_inputs(") == 2


def test_catalogue_marks_median_based_ratings_as_estimated() -> None:
    page = auctions_page()
    assert "% факта" in page
    assert "медиана:" in page
    assert "с медианой" in page
    # Балл по трём составляющим из четырёх называет себя: не показанный, он
    # читался бы как полная оценка. Причина едет подсказкой того же места.
    assert "без составляющей:" in page
    assert "r.deferred" in page
    assert "без составляющей '+incomplete" in page
