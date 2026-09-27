"""Рейтинг КРТ собирается одной функцией для карточки, кнопки и фона.

Было три копии. Фоновая звала `score()` без медианных подстановок и каждые
сутки перезаписывала оценку, записанную кнопкой, на «—»; цену окружения брала
у site_verdict — ту самую цену «доминирующего класса», которую правило v5
скрининга запретило, — и засчитывала как измеренную; разовый сбой ЕГРН стирал
прежде собранную нагрузку. Проверки здесь идут через настоящие маршрут и
фоновую функцию приложения, а не через подстроки исходника.
"""

from __future__ import annotations

import sys
import time
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import api, krt_investment_score
from auction_search.krt_ranking import KrtRanking

SLUG = "alpha"
PROJECT = {"slug": SLUG, "name": "Альфа", "status": "Планируемый", "area_ha": 5.0,
           "housing_gfa_sqm": 100_000.0}
OTHER = {"slug": "beta", "name": "Бета", "status": "Планируемый", "area_ha": 3.0}


class _City:
    def area_median(self, segment):
        return 800.0

    def snapshot(self, segment):
        return types.SimpleNamespace(price_median=500_000.0)

    def segments(self):
        return ["Комфорт"]


class _Registry:
    def find(self, query):
        slug = str(query).split(":", 1)[-1]
        return dict(PROJECT) if slug == SLUG else None

    def catalogue(self, refresh=False):
        return [dict(PROJECT)]

    def decisions(self, refresh=False):
        return []


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    monkeypatch.delitem(sys.modules, "developaid_core", raising=False)
    application = FastAPI()
    application.state.market_discovery_service = types.SimpleNamespace(
        krt=_Registry(), city=_City())
    api.install(application)
    ranking = KrtRanking(tmp_path / "market")
    now = int(time.time())
    # Площадка с посчитанными LLCR, ценой и поглощением; нагрузки нет.
    ranking._persist({SLUG: {
        "slug": SLUG, "name": "Альфа", "available": True, "computed_at": now,
        "project_llcr_x": 1.25, "surrounding_price_rub_sqm": 650_000,
        "segment": "Комфорт",
    }})
    # Соседняя площадка с полной нагрузкой — источник медианы.
    ranking._persist({"beta": {
        "slug": "beta", "name": "Бета", "available": True, "computed_at": now,
        "project_llcr_x": 1.1, "surrounding_price_rub_sqm": 600_000,
    }})
    ranking.remember("beta", {"burden_pct": 12.0, "burden_complete": True})
    ranking.save_report(SLUG, {
        "project": PROJECT,
        "market": {
            "peers": [{"area_per_month": 900.0}, {"area_per_month": 700.0}],
            "comparison": {"segment": "Комфорт"},
            # Цена «доминирующего класса» — её рейтинг брать не должен.
            "analysis": {"site": {"price_per_sqm": 3_000_000}},
        },
        "screening": {"available": True, "metrics": {"project_llcr_x": 1.25}},
    })
    return application, ranking


def _complete_burden_rows(ranking, count):
    """Площадки каталога с полностью собранной нагрузкой — выборка медианы."""
    now = int(time.time())
    for index in range(count):
        slug = f"burden-{index}"
        ranking._persist({slug: {"slug": slug, "name": slug, "available": True,
                                 "computed_at": now, "project_llcr_x": 1.2}})
        ranking.remember(slug, {"burden_pct": 10.0 + index, "burden_complete": True})


def test_a_median_of_one_site_is_not_an_answer(app):
    """На проде медиана нагрузки считалась по одной строке из 601.

    Под порогом `MIN_MEDIAN_SAMPLE` составляющая не подставляется: она
    откладывается с причиной, а балл считается по трём остальным.
    """
    application, ranking = app  # в каталоге одна строка с полной нагрузкой (beta)
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    rating = fields["investment_rating"]
    assert rating["imputed"] == [], "медиана одной площадки подставлена как ответ"
    assert [item["component"] for item in rating["deferred"]] == ["burden"]
    assert "по 1 площадкам" in rating["deferred"][0]["reason"]
    assert rating["display_score"] is not None, "отложенная составляющая обнулила балл"
    assert rating["components"]["burden"]["deferred"] is True
    assert rating["coverage_pct"] == 75
    # Медиана не записывается фактом площадки.
    assert fields["burden_pct"] is None
    assert fields["burden_complete"] is False


def test_the_background_keeps_a_numeric_rating_with_a_labelled_median(app):
    application, ranking = app
    _complete_burden_rows(ranking, krt_investment_score.MIN_MEDIAN_SAMPLE)
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    rating = fields["investment_rating"]
    assert rating["display_score"] is not None, "фон снова пишет «—» вместо оценки с медианой"
    assert [item["component"] for item in rating["imputed"]] == ["burden"]
    assert rating["deferred"] == []
    assert rating["components"]["burden"]["estimated"] is True
    assert rating["coverage_pct"] == 75
    assert fields["burden_pct"] is None
    assert fields["burden_complete"] is False


def test_card_and_background_give_one_number(app):
    application, ranking = app
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    card = TestClient(application).get(f"/auctions/krt/{SLUG}/investment-score").json()
    assert card["rating"]["display_score"] == fields["investment_rating"]["display_score"]
    stored = ranking.stored_row(SLUG)["investment_rating"]
    assert stored["display_score"] == card["rating"]["display_score"]


def test_the_dominant_class_price_is_not_counted_as_measured(app):
    application, ranking = app
    ranking.remember(SLUG, {"surrounding_price_rub_sqm": None})
    row = ranking.stored_row(SLUG)
    assert row["surrounding_price_rub_sqm"] is None
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    price = fields["investment_rating"]["components"]["price"]
    assert price["estimated"] is True, "цена site_verdict засчитана как измеренная"
    assert price["value"] == 500_000.0


def test_a_failed_burden_attempt_keeps_the_complete_burden(app, monkeypatch):
    application, ranking = app
    ranking.remember(SLUG, {
        "burden_pct": 9.5, "burden_mln": 950.0, "ordinary_capex_mln": 10_000.0,
        "burden_complete": True,
        "burden_pipeline_version": krt_investment_score.BURDEN_PIPELINE_VERSION,
    })
    monkeypatch.setattr(
        krt_investment_score, "generic_project_burden",
        lambda core, project, screening, **kw: {
            "available": False, "pending": True, "checked_at": int(time.time()),
            "retry_after_seconds": 1800, "reason": "ЕГРН не ответил: 503"})
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    assert fields["burden_complete"] is True
    assert fields["burden_pct"] == 9.5
    assert fields["burden_pending"] is True, "недочитанное должно дочитываться"
    assert fields["investment_rating"]["components"]["burden"]["estimated"] is False

    # Окончательный ответ «не собрано» — уже не сбой: прежняя нагрузка уходит.
    monkeypatch.setattr(
        krt_investment_score, "generic_project_burden",
        lambda core, project, screening, **kw: {
            "available": False, "pending": False, "checked_at": int(time.time()),
            "retry_after_seconds": 86400,
            "reason": "Выкуп не собран полностью: 77:01: стоимость не опубликована"})
    fields = application.state.krt_background_rating_fields(dict(PROJECT))
    assert fields["burden_complete"] is False
    assert fields["burden_pct"] is None
    assert "стоимость не опубликована" in fields["burden_reason"]
