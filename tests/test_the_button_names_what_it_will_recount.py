"""Подпись у кнопки называет то, что кнопка сделает, а не соседнее число.

Кнопка «Пересчитать только их» стояла под числом «Посчитано прежней методикой:
N», а планировала по своему условию: `only_stale` оставляет всё, что не
«посчитано И нынешней методикой», то есть ещё и строки, у которых модели нет
ВОВСЕ. Замер прода 20.09.2026: устаревших 5, запланированных 388 — подпись
называла одно число, а кнопка делала другое, и узнать об этом можно было
только нажав.

Поведение кнопки при этом защитимо: у строки без модели пересчитывать тоже
есть что, и сужать фильтр значило бы отнять работу, которую человек просит.
Врала подпись. Лечится это тем, что оба числа считает ОДНО правило на сервере
(`krt_ranking.model_needs_recount`), а не тем, что на экране заводят второй
счёт: два счёта одного вопроса однажды разошлись бы, и оба выглядели бы
верными.

Запуск: python3 -m pytest tests/test_the_button_names_what_it_will_recount.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search import krt_ranking  # noqa: E402
from auction_search import krt_screening  # noqa: E402
from auction_search import ui  # noqa: E402

FRESH = {
    "slug": "fresh",
    "available": True,
    "rules_version": krt_screening.SCREENING_RULES_VERSION,
    "computed_at": 2,
    "model_fingerprint": krt_ranking.model_fingerprint(),
}
STALE = {
    "slug": "stale",
    "available": True,
    "rules_version": 0,
    "computed_at": 1,
    "engine_version": "0.23.22",
}
# Модели нет вовсе: строка есть, а считать по ней было нечем — или ещё не
# доходили руки. Это НЕ «посчитано прежней методикой»: прежнего счёта у неё не
# было. Но пересчитать её кнопка обязана — иначе она обещает больше, чем даёт.
NEVER = {"slug": "never", "available": False}


def test_the_counter_and_the_planner_are_one_rule():
    """Счётчик и планировщик — один предикат, и это проверяется им же."""
    assert krt_ranking.model_needs_recount(STALE) is True
    assert krt_ranking.model_needs_recount(NEVER) is True
    assert krt_ranking.model_needs_recount(FRESH) is False


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
            catalogue=lambda **_: [{"slug": row["slug"], "name": row["slug"],
                                    "status": "Планируемый",
                                    "housing_gfa_sqm": 200_000}
                                   for row in rows],
            status=lambda: {"complete": True, "refreshing": False},
        ),
        build_report=lambda *a, **k: {},
    )
    install(app)
    return app


def test_the_route_says_how_many_the_button_will_recount(monkeypatch):
    """Число у кнопки равно тому, что кнопка запустит, — по построению."""
    from fastapi.testclient import TestClient

    rows = [dict(STALE), dict(FRESH), dict(NEVER)]
    monkeypatch.setenv("MARKET_CABINET_KEY", "test-key")
    started: list[list[str]] = []
    client = TestClient(_app(rows, started, monkeypatch))

    body = client.get("/auctions/krt/ranking").json()
    assert body["stale_model_count"] == 1, "устаревшее по методике — своя величина"
    assert body["recount_planned_count"] == 2, (
        "кнопка планирует и строку без модели: «прежней методикой» и "
        "«пересчитает» — разные числа")
    # Предохранитель: если они совпали, проверка не значит ничего.
    assert body["recount_planned_count"] != body["stale_model_count"]

    run = client.post("/auctions/krt/ranking/refresh",
                      json={"slugs": [row["slug"] for row in rows],
                            "only_stale": True},
                      headers={"X-Market-Key": "test-key"})
    assert run.status_code == 200, run.text
    assert started == [["stale", "never"]], started
    assert len(started[0]) == body["recount_planned_count"], (
        "число у кнопки разошлось с тем, что кнопка запустила")


def _note(tmp_path, state: dict) -> dict:
    """Что подпись ГОВОРИТ — меряется отрисовкой, а не поиском по исходнику."""
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    file = tmp_path / "auctions.html"
    file.write_text(ui.auctions_page(None), encoding="utf-8")
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка страницы
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 1280, "height": 900})
            # Гасим только чужие запросы страницы: `**/*` погасил бы и саму
            # навигацию к файлу.
            tab.route("http*://**", lambda route: route.abort())
            tab.goto(file.as_uri())
            tab.wait_for_timeout(300)
            got = tab.evaluate(
                """seed=>{
                  Object.assign(state, seed);
                  const box=document.getElementById('krtRankStatus');
                  box.innerHTML='';
                  renderKrtStaleModelNote();
                  const btn=document.getElementById('krtStaleRun');
                  return {text:box.textContent||'', button:btn?btn.textContent:''};
                }""", state)
            tab.close()
        finally:
            browser.close()
    return got


def test_the_note_names_both_numbers(tmp_path):
    got = _note(tmp_path, {"krtStaleModel": 5, "krtRecountPlanned": 388,
                           "krtStaleEngines": [], "krtEngine": "0.24.7"})
    assert "Посчитано прежней методикой: 5" in got["text"], got
    assert "383" in got["text"], (
        "строки без модели не названы — а кнопка их считает", got)
    assert got["button"] == "Пересчитать эти 388", got
    assert "только их" not in got["text"], (
        "«только их» обещает, что пересчитают названные пять", got)


def test_a_catalogue_with_no_model_at_all_still_gets_the_button(tmp_path):
    """Ноль устаревших — не молчание: модели может не быть ни у одной строки."""
    got = _note(tmp_path, {"krtStaleModel": 0, "krtRecountPlanned": 12,
                           "krtStaleEngines": [], "krtEngine": "0.24.7"})
    assert "Модель не считалась ни разу: 12" in got["text"], got
    assert got["button"] == "Пересчитать эти 12", got


def test_nothing_to_recount_says_nothing(tmp_path):
    """Пересчитывать нечего — приписки нет вовсе: постоянную перестают читать."""
    got = _note(tmp_path, {"krtStaleModel": 0, "krtRecountPlanned": 0,
                           "krtStaleEngines": [], "krtEngine": "0.24.7"})
    assert got["text"] == "", got
    assert got["button"] == "", got
