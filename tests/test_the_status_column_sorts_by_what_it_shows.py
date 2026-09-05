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
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
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
            page.click("#krtTableWrap th[data-sort='status']")
            page.wait_for_timeout(150)
            shown = page.evaluate(
                "state.krtFiltered.map(x=>krtStatusCell(x)"
                ".replace(/<[^>]*>/g,' ').replace(/\\s+/g,' ').trim())")
            sorted_by = page.evaluate("state.krtFiltered.map(x=>krtValue(x,'status'))")
            dates = page.evaluate(
                "state.krtFiltered.filter(x=>krtStatusWord(x)==='Проект решения')"
                ".map(x=>x.draft_decision_at)")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    # Показано и сравнивается — одно и то же слово, строка в строку.
    assert shown == sorted_by, list(zip(shown, sorted_by))
    # Кусок адреса статусом не становится ни на экране, ни в сортировке.
    assert "влд. 13" not in sorted_by, sorted_by
    assert "не разобрана" in sorted_by, sorted_by
    # Площадки-решения стоят своим блоком и внутри него — по дате, новые выше.
    assert dates == sorted(dates, reverse=True), dates
    # И блоки идут подряд, а не вперемешку: одинаковые слова рядом.
    blocks = [word for i, word in enumerate(sorted_by) if not i or word != sorted_by[i - 1]]
    assert len(blocks) == len(set(blocks)), blocks
