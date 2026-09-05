"""Связку «площадка ↔ живой лот» помнит сервер, а не вкладка браузера.

«Почему после прогона наш проект на Нагатино опять стал атрибутирование ФСК и
исчезла плашка Торги, а там идёт аукцион же» (владелец, 04.09.2026).

Измерено на проде. Находка публикации лежит в строке рейтинга и переживает
всё: у Варшавского ш., вл. 37 это «ЖК Роттердам от ГК ФСК» со страниц
`novostroy.ru/buildings/varshavskoe-shosse-37/`. А связка с живым лотом
(заявки до 21.09) не хранилась НИГДЕ: её считает сервер по лотам, собранным
соседней вкладкой, и живёт она в памяти браузера. Открыл каталог без соседней
вкладки — плашки нет, и правило «живой лот сильнее публикации» (02.09.2026) не
срабатывает вовсе. Асимметрия хранения и есть ошибка: одна сторона спора
записана на диск, другая испаряется при перезагрузке.

Запуск: python3 -m pytest tests/test_a_live_lot_outlives_the_tab.py -q
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PORT = 18795

SITE = {"slug": "varshavskoe-37", "name": "Варшавское шоссе, вл. 37", "status": "Планируемый",
        "okrug": "ЮАО", "area_ha": 14.0, "total_gfa_sqm": 300_000, "housing_gfa_sqm": 200_000}
# Находка публикации: застройщик назван — но это объявление о продаже ЖК с ТЕМ
# ЖЕ номером дома, а не оператор этой площадки.
PRESS = {"available": True, "taken": False, "operator_named": [],
         "developer_named": [{"name": "ГК ФСК", "quote": "ЖК «Роттердам» от застройщика ГК ФСК",
                              "url": "https://www.novostroy.ru/buildings/varshavskoe-shosse-37/"}],
         "city_needs": [], "agreement": [], "selling_now": [],
         "buckets": [{"key": "developer_named", "title": "Застройщик назван", "heavy": False}]}


def _tomorrow() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 3 * 86400))


LOT = {"title": "Аукцион на право заключения договора о КРТ",
       "url": "https://torgi.gov.ru/lot/1", "deadline": _tomorrow(),
       "source": "roseltorg", "price_rub": 2_400_000_000}


def test_the_server_remembers_which_lot_belongs_to_the_site(tmp_path):
    """Посчитанное сервером сервер и хранит — иначе его негде взять."""
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path)
    assert registry.tender_lots_known() == {}
    registry.remember_tender_lots({"varshavskoe-37": [LOT]})
    known = registry.tender_lots_known()
    assert known["varshavskoe-37"]["lots"] == [LOT]
    assert known["varshavskoe-37"]["seen_at"] > 0

    # Площадка, которой в этом заходе не нашлось, своё НЕ теряет: обход
    # каталога ограничен сроком, и «не собрали» — это не «лота нет».
    registry.remember_tender_lots({"other-site": [LOT]})
    assert "varshavskoe-37" in registry.tender_lots_known()
    # Пустой ответ по площадке тоже ничего не стирает по той же причине.
    registry.remember_tender_lots({"varshavskoe-37": []})
    assert registry.tender_lots_known()["varshavskoe-37"]["lots"] == [LOT]


def _app(tmp_path):
    from fastapi import FastAPI

    from auction_search.api import install
    from market_search.krt_registry import KrtRegistry

    registry = KrtRegistry(tmp_path)
    registry.remember_tender_lots({"varshavskoe-37": [LOT]})
    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: [dict(SITE)],
            status=lambda: {"complete": True, "refreshing": False},
            tender_lots_known=registry.tender_lots_known,
            remember_tender_lots=registry.remember_tender_lots,
        ),
    )
    install(app)
    return app


def test_the_row_carries_the_remembered_lot(tmp_path):
    from fastapi.testclient import TestClient

    answer = TestClient(_app(tmp_path)).get("/auctions/krt")
    assert answer.status_code == 200
    row = answer.json()["projects"][0]
    assert row["tender_lots"] == [LOT], "связка до строки не доезжает"
    assert row["tender_lots_seen_at"] > 0, "когда узнали — часть ответа"


READ = """() => {
  const x = state.krt[0];
  return {
    lots: krtLots(x).length,
    live: !!krtLiveLot(x),
    stage: krtStage(x).key,
    marks: krtMarks(x),
    tender: krtTenderMark(x),
    on_tender: krtOnTender(x),
  };
}"""


@pytest.mark.timeout(180)
def test_in_a_real_browser_the_auction_beats_the_publication(tmp_path):
    """Плашка есть без соседней вкладки, а застройщик с ней не спорит."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        pytest.skip("playwright недоступен")
    chrome = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    if not chrome.exists():
        pytest.skip("chromium в образе не найден")
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(_app(tmp_path), host="127.0.0.1", port=PORT,
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
            # Находка публикации приезжает прогоном и лежит в строке рейтинга.
            page.evaluate("(p)=>{state.krtRank['varshavskoe-37']={press_facts:p}}", PRESS)
            page.evaluate("filterKrt()")
            page.wait_for_timeout(150)
            got = page.evaluate(READ)
            # Соседнюю вкладку «Торги» никто не открывал: в памяти пусто.
            empty = page.evaluate("Object.keys(state.krtTenders||{}).length")
            # А со вчерашним сроком подачи «идут торги» больше не обещаем.
            page.evaluate("()=>{state.krt[0].tender_lots=[{deadline:'2020-01-01'}]}")
            stale = page.evaluate(READ)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert empty == 0, "лоты пришли из соседней вкладки — проверяется не то"
    assert got["lots"] == 1 and got["live"] is True, got
    assert got["on_tender"] is True, "ось «Стадия → Торги» связку не видит"
    assert got["stage"] == "bidding", got
    # Плашка торгов ОДНА: две с одним смыслом читаются как два разных факта.
    # Проверяется ПОДПИСЬ плашки, а не текст подсказки: слова из объяснения
    # видом плашки не являются.
    assert ">идут торги<" in got["tender"], got["tender"]
    # Живой лот сильнее публикации: застройщика площадке не приписываем.
    assert ">ГК ФСК<" not in got["marks"], "метка снова приписывает застройщика"
    # Находка не выброшена — она названа в подсказке как противоречие.
    assert "ГК ФСК" in got["tender"], "молча снятая находка читается как «ничего нет»"
    # Прошедший срок подачи живым лотом не считается — и обещать «идут» нельзя.
    assert stale["live"] is False, "вчерашний срок обещает идущий аукцион"
    assert ">торги были<" in stale["tender"], stale["tender"]
    assert ">идут торги<" not in stale["tender"], stale["tender"]
    assert ">ГК ФСК<" in stale["marks"], "без живого лота находка обязана вернуться"
