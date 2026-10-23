"""Без ключа раздел «Торги» читают, но не пишут.

Когда ни ключ просмотра, ни личные ключи не заданы, ворота раздела выключены,
и чтение открыто всем — так решил владелец. Вместе с чтением были открыты и
запись (отметка «конкурс объявлен», лоты у площадок, заявки модели), команды
пересчёта и пробы источников: посетитель с улицы менял то, что видят все.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auction_search import view_access  # noqa: E402
from auction_search.api import install  # noqa: E402

TEAM_KEY = "team-cabinet-key-for-test"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("AUCTIONS_VIEW_KEY", raising=False)
    monkeypatch.setenv("MARKET_CABINET_KEY", TEAM_KEY)
    remembered = []
    application = FastAPI()
    application.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            decisions=lambda **_: {"decisions": [], "complete": True},
            status=lambda: {"complete": True, "refreshing": False},
            tender_lots_known=lambda: {},
            remember_tender_lots=lambda *a, **k: remembered.append(a),
        ),
    )
    install(application)
    application.state.remembered = remembered
    return application


@pytest.mark.parametrize("method,path", [
    ("POST", "/auctions/krt/tenders"),
    ("POST", "/auctions/krt/some-site/tender-order"),
    ("POST", "/auctions/lot-notes/request"),
    ("POST", "/auctions/ingest"),
    ("POST", "/auctions/ask"),
    ("GET", "/auctions/krt/api-probe?url=https://api.krt.mos.ru/"),
    ("GET", "/auctions/etp/probe/browser?platform=x"),
    ("GET", "/auctions/source-page?url=https://example.com/"),
    ("GET", "/auctions/krt?refresh=1"),
])
def test_a_stranger_does_not_write_or_probe(app, method, path):
    answer = TestClient(app).request(method, path, json={"lots": []})
    assert answer.status_code == 401, (path, answer.text)
    assert "только для просмотра" in answer.json()["detail"]
    assert app.state.remembered == []


def test_a_stranger_still_reads(app):
    assert view_access.anonymous_problem("GET", "/auctions/krt", {}) == ""
    assert view_access.anonymous_problem("GET", "/auctions/krt/x/report", {}) == ""
    assert view_access.anonymous_problem("POST", "/auctions/table", {}) == ""
    assert TestClient(app).get("/auctions/krt/decisions").status_code != 401


def test_the_team_writes(app):
    client = TestClient(app, headers={"X-Market-Key": TEAM_KEY})
    answer = client.post("/auctions/krt/tenders", json={"lots": []})
    assert answer.status_code == 200, answer.text


def test_a_made_up_key_is_not_the_team(app):
    answer = TestClient(app).post("/auctions/krt/tenders?key=junk&session=junk",
                                  json={"lots": []})
    assert answer.status_code == 401
