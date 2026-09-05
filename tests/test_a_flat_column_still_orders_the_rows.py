"""Сортировка по «Статусу» ставит одинаковые строки по их дате.

«Статус это дата и она не сортируется правильно» (владелец, 05.09.2026). У 298
площадок-решений статуса города нет вовсе — экран печатает им всем одно слово
«Проект решения о КРТ», и сортировка по одинаковой строке не упорядочивает
ничего: даты в соседней колонке шли вразнобой (29.06.2026, 01.09.2026,
19.06.2025). На экране это неотличимо от сломанной сортировки — та же беда, что
уже ловилась стрелкой у колонки.

Содержание такой строки и есть её дата, поэтому внутри одинакового статуса
порядок задаёт дата проекта решения.

Рядом вторая жалоба того же дня — «торги 0????». Ноль там был двух видов
сразу: «аукционов нет» и «лоты ни разу не собирали». На проде склад связок
«площадка ↔ лот» был пуст при ВОСЬМИ живых аукционах на право договора о КРТ
(Росэлторг, сроки 21.09–02.10.2026), потому что связку писал только маршрут,
которому список присылала страница. Подпись варианта теперь различает пустой
склад и пустой рынок.

Запуск: python3 -m pytest tests/test_a_flat_column_still_orders_the_rows.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PORT = 18796

# Четыре площадки-решения: статус у всех ОДИН И ТОТ ЖЕ, различает их только
# дата. Имена нарочно идут в обратном порядке к датам — иначе прежняя
# сортировка по имени выглядела бы верной.
_DECISIONS = {
    "total": 4, "matched": 0, "complete": True, "stale": False,
    "retrieved_at": 1_788_000_000,
    "decisions": [
        {"id": "401", "title": "Проект решения …", "url": "https://www.mos.ru/x/1/",
         "address": "Аллеевая ул., влд. 1", "okrug": "ЦАО", "published_at": 1_700_000_000},
        {"id": "402", "title": "Проект решения …", "url": "https://www.mos.ru/x/2/",
         "address": "Берёзовая ул., влд. 2", "okrug": "САО", "published_at": 1_780_000_000},
        {"id": "403", "title": "Проект решения …", "url": "https://www.mos.ru/x/3/",
         "address": "Вязовая ул., влд. 3", "okrug": "ВАО", "published_at": 1_760_000_000},
        {"id": "404", "title": "Проект решения …", "url": "https://www.mos.ru/x/4/",
         "address": "Грушевая ул., влд. 4", "okrug": "ЮАО", "published_at": 1_740_000_000},
    ],
    "matched_rows": [],
    "tep": {}, "tep_coverage": {"read": 0, "failed": 0, "unknown": 4, "silent": 0,
                                "reasons": {}},
    "tep_pending": [],
}


def _app():
    from fastapi import FastAPI

    from auction_search.api import install

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [],
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False, "retrieved_at": 1_788_000_000,
                            "ttl_seconds": 86_400},
            decisions=lambda **_: dict(_DECISIONS),
        ),
    )
    install(app)
    return app


@pytest.mark.timeout(180)
def test_the_status_column_orders_the_same_rows_by_date() -> None:
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
            everything = page.evaluate("state.krt.length")

            # Нажимаем сам заголовок, как человек.
            page.click("#krtTableWrap th[data-sort='status']")
            page.wait_for_timeout(150)
            first = page.evaluate(
                "[...document.querySelectorAll('#krtRows tr')]"
                ".map(t=>t.children[0].innerText.split('\\n')[0])")
            dates = page.evaluate(
                "state.krtFiltered.map(x=>x.draft_decision_at)")
            statuses = page.evaluate(
                "[...new Set(state.krtFiltered.map(x=>String(x.status||'')))]")

            # Подпись варианта «Торги»: склад связок пуст, и это сказано словом.
            tender_label = page.evaluate(
                "[...document.querySelectorAll('#krtStageOptions label')]"
                ".map(l=>l.innerText).find(t=>t.startsWith('Торги'))")
            # А когда связка есть — обычное число.
            page.evaluate("state.krtTenders={'x':[{deadline:'2099-01-01'}]};"
                          "renderKrtFilterCounts()")
            page.wait_for_timeout(100)
            tender_known = page.evaluate(
                "[...document.querySelectorAll('#krtStageOptions label')]"
                ".map(l=>l.innerText).find(t=>t.startsWith('Торги'))")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert everything == 4
    # Статус у всех один — сортировать по нему нечего, и раньше строки вставали
    # по имени. Теперь порядок задаёт дата: новые выше.
    assert len(statuses) == 1, statuses
    assert dates == sorted(dates, reverse=True), dates
    assert first[0].startswith("Берёзовая ул., влд. 2"), first
    assert first[-1].startswith("Аллеевая ул., влд. 1"), first

    # «0» и «не собирали» — разные ответы: первый про рынок, второй про нас.
    assert "не собирали" in (tender_label or ""), tender_label
    assert "не собирали" not in (tender_known or ""), tender_known
    assert "(0)" in (tender_known or ""), tender_known
