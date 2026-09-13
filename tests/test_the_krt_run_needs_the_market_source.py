"""Прогон КРТ не идёт там, где источник рынка выключен.

Журнал Render, 07.09.2026: `RemoteServiceError: Источник рыночных данных
выключен: не заданы PULSE_LOGIN и PULSE_PASSWORD` — трассировка на КАЖДУЮ
площадку подряд. Бот поднимает тот же модуль торгов, что и ядро, а доступ к
«Пульсу» живёт в окружении и есть только у ядра. Прогон при этом честно ходил
в каталог, честно падал на первом же шаге модели и писал строке «Расчёт не
выполнен» — на диск, который у бота живёт до следующей выкатки.

Наличие модуля признаком не является — как маршрут Платона решает
`PLATO_AI_URL`, а не наличие ключа. Спрашивается то, что отвечает на вопрос:
включён ли источник (`pulse.available`), и ответ один на модуль
(`_market_source_off`) — у кнопки и у недельного прогона.

Запуск: python3 -m pytest tests/test_the_krt_run_needs_the_market_source.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import api as auction_api  # noqa: E402

API = (ROOT / "auction_search" / "api.py").read_text(encoding="utf-8")

CATALOGUE = [
    {"slug": "site-1", "name": "Площадка", "status": "Планируемый",
     "area_ha": 3.0, "housing_gfa_sqm": 50_000},
]


def _app(monkeypatch, *, source_on: bool):
    fastapi = pytest.importorskip("fastapi")
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    app = fastapi.FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        pulse=SimpleNamespace(available=source_on),
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(row) for row in CATALOGUE],
            status=lambda: {"complete": True, "refreshing": False},
            decisions=lambda **_: {"decisions": [], "matched_rows": [], "tep": {}},
        ),
    )
    auction_api.install(app)
    return app


def _run(app, **body):
    from fastapi.testclient import TestClient

    return TestClient(app).post("/auctions/krt/ranking/refresh",
                                headers={"X-Market-Key": "test-key"}, json=body)


def test_the_button_names_the_reason_instead_of_failing_every_site(monkeypatch) -> None:
    """Отказ, названный заранее, — свойство хоста; отказ после нажатия — поломка."""
    answer = _run(_app(monkeypatch, source_on=False))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["started"] is False, "прогон пошёл там, где считать нечем"
    assert "PULSE_LOGIN" in body["reason"], body
    assert body["progress"]["running"] is False, "нить прогона всё-таки поднялась"


def test_the_run_still_starts_where_the_source_is_on(monkeypatch) -> None:
    """Сторож не должен запирать хост, который считать умеет."""
    answer = _run(_app(monkeypatch, source_on=True))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["started"] is True or body["progress"]["running"], body
    assert "PULSE_LOGIN" not in str(body.get("reason") or "")


def test_the_weekly_run_asks_the_same_one_question() -> None:
    """Один ответ на модуль: разойдись кнопка с прогоном, ночью повторилось бы то же.

    Проверяется контракт — что прогон спрашивает ИМЕННО этот ответ и делает это
    ДО обращения к каталогу: гейт после `due()` уже разбудил бы обход.
    """
    start = API.index("    def _weekly_ranking(")
    body = API[start:API.index("\n    # main.py loads the canonical legacy core", start)]
    assert "_market_source_off()" in body, "недельный прогон источник не спрашивает"
    assert body.index("_market_source_off()") < body.index("krt_ranking.due()"), \
        "источник спрашивается после каталога — обход уже разбужен"
    assert API.count("    def _market_source_off(") == 1, "ответ объявлен дважды"
