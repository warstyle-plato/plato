"""Колонка «Статус» сортируется тем словом, которое в ней написано.

«Статус с датами не приведён в порядок» (владелец, 05.09.2026) — вторая
половина той же жалобы. Дата внутри одинакового статуса упорядочивается с
0.22.4 и работает; сломано было другое, и видно это только на живых данных.

Измерено на проде 05.09.2026 настоящим кодом страницы:

- колонка ПОКАЗЫВАЕТ «Проект решения» у 298 строк и «не разобрана» у трёх;
- сортировка БРАЛА сырое поле `status`: у решений оно пусто (значит
  «неизвестно» — вниз при любом направлении), а у трёх съехавших карточек в
  нём лежит кусок адреса, и «вл. 24», «влд. 1», «влд. 13» вставали
  отдельными блоками между «В реализации» и «Планируемым».

Одна величина, показанная одним словом и сравниваемая другим, читается как
несработавшая сортировка. То же правило, что у `VERSION` и `status_kind`:
слово объявляется один раз, и печатает и сортирует его один и тот же ответ.

Запуск: python3 -m pytest tests/test_the_status_column_sorts_by_what_it_shows.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser import chromium_or_skip

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORT = 18797

# Четыре вида статуса разом: слово города, съехавшая карточка и площадки без
# карточки, различающиеся только датой решения.
_PROJECTS = [
    {"slug": "running", "name": "Стройка идёт", "status": "В реализации",
     "okrug": "ЦАО", "area_ha": 3.0, "housing_gfa_sqm": 60_000},
    {"slug": "planned", "name": "Планируемая площадка", "status": "Планируемый",
     "okrug": "САО", "area_ha": 2.0, "housing_gfa_sqm": 40_000},
    # Съехавший разбор: в поле статуса лежит кусок адреса.
    {"slug": "shifted", "name": "Съехавшая карточка", "status": "влд. 13",
     "okrug": "Планируемый", "parse_problem": "значения съехали на поле",
     "area_ha": 1.0, "housing_gfa_sqm": 20_000},
]

_DECISIONS = {
    "total": 3, "matched": 0, "complete": True, "stale": False,
    "retrieved_at": 1_788_000_000,
    "decisions": [
        {"id": "901", "title": "Проект решения …", "url": "https://www.mos.ru/x/1/",
         "address": "Аллеевая ул., влд. 1", "okrug": "ЦАО", "published_at": 1_700_000_000},
        {"id": "902", "title": "Проект решения …", "url": "https://www.mos.ru/x/2/",
         "address": "Берёзовая ул., влд. 2", "okrug": "САО", "published_at": 1_780_000_000},
        {"id": "903", "title": "Проект решения …", "url": "https://www.mos.ru/x/3/",
         "address": "Вязовая ул., влд. 3", "okrug": "ВАО", "published_at": 1_760_000_000},
    ],
    "matched_rows": [], "tep": {}, "tep_pending": [],
    "tep_coverage": {"read": 0, "failed": 0, "unknown": 3, "silent": 0, "reasons": {}},
}


def _app():
    from fastapi import FastAPI

    from auction_search.api import install

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: list(_PROJECTS),
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False,
                            "retrieved_at": 1_788_000_000, "ttl_seconds": 86_400},
            decisions=lambda **_: dict(_DECISIONS),
        ),
    )
    install(app)
    return app


@pytest.mark.timeout(180)
def test_the_column_and_the_sort_say_the_same_word() -> None:
    # Где браузер — один ответ на весь набор (`tests/browser.py`): он ищет, а
    # не помнит номер сборки, и на машине, где браузер ОБЯЗАН быть, его
    # отсутствие красит проверку красным, а не пропускает её молча.
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=PORT,
                                           log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome))
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{PORT}/auctions", wait_until="domcontentloaded")
            page.evaluate("switchTab(true)")
            for _ in range(40):
                page.wait_for_timeout(250)
                if page.evaluate("state.krt.length"):
                    break
            # Статус больше не отдельная колонка: в таблице показывается
            # дата сигнала/решения. Сортируем именно той величиной, которую
            # пользователь видит в колонке.
            page.click("#krtTableWrap th[data-sort='decided']")
            page.wait_for_timeout(150)
            shown = page.evaluate(
                "state.krtFiltered.map(x=>krtDecisionDateCell(x)"
                ".replace(/<[^>]*>/g,' ').replace(/\\s+/g,' ').trim())")
            sorted_by = page.evaluate("state.krtFiltered.map(x=>krtValue(x,'decided'))")
            dates = page.evaluate(
                "state.krtFiltered.filter(x=>x.draft_decision_at)"
                ".map(x=>x.draft_decision_at)")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    # Колонка дат не сортируется сырым статусом или именем площадки.
    assert all(value is None or isinstance(value, (int, float)) for value in sorted_by)
    assert dates == sorted(dates, reverse=True), dates
    # На строках с решением видна человеческая дата, а не внутренний timestamp.
    assert any("2026" in value for value in shown if value), shown
