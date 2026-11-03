"""Кнопка «Что пишут об этой площадке» отвечает, а не падает пятисоткой.

Экран владельца (01.09.2026): после нажатия — «сервер ответил ошибкой (код
500)». Причина в имени: маршрут брал поиск у `service`, а это имя живёт
ЛОКАЛЬНО внутри маршрута выдачи лотов и снаружи не существует вовсе. Значит
кнопка не работала никогда, а я говорил о ней как о сделанной.

Поиск берётся у маркетингового движка — того самого, которым считаются соседи
по рынку: второго своего пути наружу не заводим.

Запуск: python3 -m pytest tests/test_the_press_button_answers.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import api as auction_api  # noqa: E402
from market_search.krt_registry import KrtRegistry  # noqa: E402


class _Doc:
    def __init__(self, title: str, snippet: str, url: str) -> None:
        self.title, self.snippet, self.url = title, snippet, url


class _Search:
    configured = True

    def search(self, query: str, **kw):
        return [_Doc("Строгино: застройщик определён",
                     "Проект КРТ в Строгино реализует АО «Пример».",
                     "https://example.org/1")]


class _Market:
    search = _Search()


@pytest.fixture()
def client(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        KrtRegistry, "catalogue",
        lambda self: [{"slug": "strogino", "name": "Строгино тер. 1", "okrug": "СЗАО"}])
    app = fastapi.FastAPI()
    app.state.market_discovery_service = _Market()
    auction_api.install(app)
    return TestClient(app)


def test_the_button_gets_an_answer(client):
    response = client.get("/auctions/krt/strogino/open-sources")
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert body["available"] is True
    assert body["queries"], "запросы к поиску не собраны"


def test_the_search_comes_from_the_market_engine():
    source = Path(auction_api.__file__).read_text(encoding="utf-8")
    assert 'client = getattr(market, "search", None)' in source
    assert 'client = getattr(service, "search", None)' not in source, \
        "имя `service` снаружи маршрута выдачи лотов не существует"


def test_an_unconfigured_search_says_so_instead_of_failing(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        KrtRegistry, "catalogue",
        lambda self: [{"slug": "strogino", "name": "Строгино тер. 1", "okrug": "СЗАО"}])
    app = fastapi.FastAPI()
    app.state.market_discovery_service = object()   # поиска нет вовсе
    auction_api.install(app)
    response = TestClient(app).get("/auctions/krt/strogino/open-sources")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False and body["reason"], \
        "ненастроенный поиск обязан назвать причину, а не уронить маршрут"
