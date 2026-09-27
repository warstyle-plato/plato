"""Regression: bulk KRT rating must build the fourth #485 component.

The catalogue button calls investment-score with ensure_model=true.  Before this
regression it only built market/model; generic burden lived exclusively in a
separate background pass, so almost every row stopped at 50/75% and Nagatino
was the lone 100% control case.  Checked through the real route, not through
substrings of the source.
"""

from __future__ import annotations

import sys
import time
import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auction_search import api, krt_investment_score
from auction_search.krt_ranking import KrtRanking
from market_search import cabinet as market_cabinet

FULL_KEY = "plato-market-test-2026"
SLUG = "alpha"
PROJECT = {"slug": SLUG, "name": "Альфа", "status": "Планируемый", "area_ha": 5.0}


class _City:
    def area_median(self, segment):
        return 800.0

    def snapshot(self, segment):
        return types.SimpleNamespace(price_median=500_000.0)

    def segments(self):
        return ["Комфорт"]


class _Registry:
    def find(self, query):
        return dict(PROJECT) if str(query).endswith(SLUG) else None

    def catalogue(self, refresh=False):
        return [dict(PROJECT)]

    def decisions(self, refresh=False):
        return []


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv(market_cabinet.ENV_NAME, FULL_KEY)
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    core = types.ModuleType("developaid_core")
    monkeypatch.setitem(sys.modules, "developaid_core", core)
    app = FastAPI()
    app.state.market_discovery_service = types.SimpleNamespace(
        krt=_Registry(), city=_City())
    api.install(app)
    ranking = KrtRanking(tmp_path / "market")
    ranking._persist({SLUG: {"slug": SLUG, "name": "Альфа", "available": True,
                             "computed_at": int(time.time()), "project_llcr_x": 1.25,
                             "surrounding_price_rub_sqm": 650_000}})
    ranking.save_report(SLUG, {"project": PROJECT, "market": {},
                               "screening": {"available": True}})
    return TestClient(app), ranking


def test_bulk_rating_reads_egrn_to_the_end_and_stores_the_burden(tmp_path, monkeypatch):
    client, ranking = _client(tmp_path, monkeypatch)
    chunks = []

    def burden(core, project, screening, **kw):
        chunks.append(kw.get("lookup_chunk"))
        if len(chunks) < 3:
            return {"available": False, "pending": True, "checked_at": int(time.time()),
                    "retry_after_seconds": 60, "reason": "ЕГРН: дочитано"}
        return {"available": True, "pending": False, "checked_at": int(time.time()),
                "burden_pct": 8.0, "burden_mln": 800.0, "ordinary_capex_mln": 10_000.0,
                "project_llcr_x": 1.21, "components": {"cadastral_mln": 800.0}}

    monkeypatch.setattr(krt_investment_score, "generic_project_burden", burden)
    answer = client.get(f"/auctions/krt/{SLUG}/investment-score",
                        params={"ensure_model": "true"},
                        headers={"X-Market-Key": FULL_KEY})
    assert answer.status_code == 200, answer.text
    assert chunks == [24, 24, 24], "кнопка не дочитывает ЕГРН за три прохода"
    row = ranking.stored_row(SLUG)
    assert row["burden_complete"] is True
    assert row["burden_pct"] == 8.0
    assert row["burden_llcr_x"] == 1.21
    assert answer.json()["rating"]["components"]["burden"]["estimated"] is False


def test_bulk_rating_needs_the_cabinet(tmp_path, monkeypatch):
    client, _ranking = _client(tmp_path, monkeypatch)
    answer = client.get(f"/auctions/krt/{SLUG}/investment-score",
                        params={"ensure_model": "true"})
    assert answer.status_code == 401
