"""Строка рейтинга знает, какой методикой посчитана, а не только когда.

«Почему в Нагатино до сих пор цена для расчёта 477» (владелец, 04.09.2026).
Правка «стартовая цена скрининга — рекомендация отчёта, а не медиана входных
цен соседей» уехала на прод в 0.21.81 (04.09, 02:49), а строка площадки была
посчитана 03.09 в 21:58 — до неё, и держала прежнее число. Сегодняшний прогон
по 56 площадкам был прогоном ПУБЛИКАЦИЙ: он обновил находки и не тронул ни
модель, ни цену, — а `computed_at` у строки после него выглядит свежим.

`computed_at` отвечает «когда», а не «чем». Отличить строку прежней методики
было нечем, и на экране она стояла наравне со свежей.

Запуск: python3 -m pytest tests/test_a_row_knows_which_rules_counted_it.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import krt_ranking  # noqa: E402
from auction_search import krt_screening  # noqa: E402

SITE = {"slug": "site", "name": "Площадка", "status": "Планируемый",
        "okrug": "ЮАО", "area_ha": 14.0, "housing_gfa_sqm": 200_000}
SCREENING = {
    "available": True,
    "traffic_light": {"tone": "warn", "label": "Проходит", "score": 55},
    "market": {"start_price_rub_sqm": 670_000, "recommended_segment": "бизнес"},
    "krt": {"project_llcr_x": 1.21, "margin_pct": 12.0},
    "phasing": {"count": 4},
}


def test_the_row_carries_the_rules_that_counted_it():
    row = krt_ranking.score_row(dict(SITE), dict(SCREENING))
    assert row["rules_version"] == krt_screening.SCREENING_RULES_VERSION
    assert row["computed_at"] > 0
    # Выпуск объявлен один раз — `VERSION`; строка берёт его оттуда же.
    import main_legacy as core

    assert row["engine_version"] == core.VERSION


def test_a_row_of_the_previous_rules_is_not_current():
    """Строка без версии посчитана до того, как её завели, — значит прежней."""
    assert krt_ranking.model_is_current({"rules_version":
                                         krt_screening.SCREENING_RULES_VERSION}) is True
    assert krt_ranking.model_is_current({"rules_version": 0}) is False
    assert krt_ranking.model_is_current({}) is False
    # Свежая дата методику не подтверждает: прогон публикаций трогает
    # `computed_at`, не трогая модель.
    import time

    assert krt_ranking.model_is_current({"computed_at": int(time.time())}) is False


def _app(rows, started, monkeypatch):
    from fastapi import FastAPI

    from auction_search.api import install
    from auction_search.krt_ranking import KrtRanking

    # Подменяется ХРАНИЛИЩЕ: в маршрутах `krt_ranking` — экземпляр, а не
    # модуль, и `rows`/`start` у него методы.
    monkeypatch.setattr(KrtRanking, "rows", lambda self: list(rows), raising=True)
    monkeypatch.setattr(
        KrtRanking, "start",
        lambda self, projects, worker: bool(
            started.append([str(p.get("slug")) for p in projects]) or True),
        raising=True)
    monkeypatch.setattr(KrtRanking, "progress", lambda self: {"running": False},
                        raising=True)
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(SITE), {**SITE, "slug": "fresh", "name": "Свежая"}],
            status=lambda: {"complete": True, "refreshing": False},
        ),
        build_report=lambda *a, **k: {},
    )
    install(app)
    return app


def test_the_screen_says_how_many_rows_judge_by_the_old_rules(monkeypatch):
    from fastapi.testclient import TestClient

    rows = [
        {"slug": "site", "available": True, "rules_version": 0, "computed_at": 1},
        {"slug": "fresh", "available": True,
         "rules_version": krt_screening.SCREENING_RULES_VERSION, "computed_at": 2},
    ]
    # Кабинет без ключа закрыт — это не сбой, а решение владельца.
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    started: list[list[str]] = []
    if True:
        client = TestClient(_app(rows, started, monkeypatch))
        answer = client.get("/auctions/krt/ranking")
        assert answer.status_code == 200
        body = answer.json()
        assert body["stale_model_count"] == 1, "устаревшее по методике не посчитано"
        assert body["rules_version"] == krt_screening.SCREENING_RULES_VERSION

        # Прогон по устаревшему берёт ровно его и называет пропущенное:
        # молча пропущенное читается как несостоявшийся прогон.
        run = client.post("/auctions/krt/ranking/refresh",
                          json={"slugs": ["site", "fresh"], "only_stale": True},
                          headers={"X-Market-Key": "test-key"})
        assert run.status_code == 200, run.text
        assert started == [["site"]], started
        assert run.json()["skipped"] == 1

        # Обычный прогон считает и свежие: рынок движется сам, и цена стареет
        # без всяких наших правок. Один ключ на два разных вопроса не отвечает.
        started.clear()
        again = client.post("/auctions/krt/ranking/refresh",
                            json={"slugs": ["site", "fresh"]},
                            headers={"X-Market-Key": "test-key"})
        assert again.status_code == 200, again.text
        assert started == [["site", "fresh"]], started
        assert again.json()["skipped"] == 0


def test_the_page_names_the_number_and_offers_to_recount_it():
    from auction_search.ui import auctions_page

    page = auctions_page(None)
    assert "stale_model_count" in page, "счёт устаревшего до экрана не доезжает"
    assert "Посчитано прежней методикой:" in page
    assert "Пересчитать только их" in page, "число названо, а пересчитать нечем"
    assert "startKrtRanking(true)" in page, "кнопка не просит только устаревшее"
