"""Фильтры и сортировка блока КРТ проверяются нажатием, а не чтением исходника.

«Сортировки по полям не работают! Статуса объектов в списке и фильтры наверху
не корректируют вообще. Статус проект решения вообще не даёт ничего» (владелец,
04.09.2026). Измерение на снимке прода в настоящем Chromium показало ровно одно
из трёх: выбор «Проект решения» давал НОЛЬ строк из 298. Причина — второй ответ
на один вопрос: сервер стал писать в такую строку слово «Проект решения», а
отбор на странице искал ПУСТОЕ слово. Строковый тест этого поймать не мог: обе
строки в файле присутствовали.

Поэтому здесь нажимают. Проверяется то, что видно: каждый выбор статуса даёт
свои строки, сумма выборов равна каталогу (ни одна площадка не выпадает молча),
клик по заголовку меняет порядок и помечает саму колонку.

Запуск: python3 -m pytest tests/test_the_krt_filters_actually_filter.py -q
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

PORT = 18793

_PROJECTS = [
    {"slug": "planned-one", "name": "Планируемая один", "status": "Планируемый",
     "okrug": "ЦАО", "area_ha": 3.0, "total_gfa_sqm": 90_000, "housing_gfa_sqm": 60_000},
    {"slug": "planned-two", "name": "Планируемая два", "status": "Планируемый",
     "okrug": "САО", "area_ha": 1.0, "total_gfa_sqm": 20_000, "housing_gfa_sqm": 10_000},
    {"slug": "running-one", "name": "В работе", "status": "В реализации",
     "okrug": "ВАО", "area_ha": 9.0, "total_gfa_sqm": 300_000, "housing_gfa_sqm": 250_000},
    # Съехавший разбор: округом стало слово статуса, статусом — хвост адреса.
    {"slug": "shifted", "name": "Съехавшая", "status": "влд. 13",
     "okrug": "Планируемый", "area_ha": 26_500.0, "total_gfa_sqm": 350.0,
     "housing_gfa_sqm": 27_580.0, "parse_problem": "округ «Планируемый» не из московских"},
]

_DECISIONS = {
    "total": 2, "matched": 0, "complete": True, "stale": False,
    "retrieved_at": 1_788_000_000,
    "decisions": [
        {"id": "347614220", "title": "Проект решения …", "url": "https://www.mos.ru/x/1/",
         "address": "Большой Тишинский пер., влд. 8", "okrug": "ЦАО",
         "kind": "нежилой застройки", "published_at": 1_787_605_200},
        {"id": "349135220", "title": "Проект решения …", "url": "https://www.mos.ru/x/2/",
         "address": "ул. Архитектора Власова, влд. 59", "okrug": "ЮЗАО",
         "kind": "нежилой застройки", "published_at": 1_788_382_800},
    ],
    "matched_rows": [],
    # ТЭП первого прочитан из его PDF, второй ещё не читали: это разные
    # ответы, и на экране они обязаны различаться.
    "tep": {"347614220": {"available": True, "read": True, "area_ha": 0.28,
                          "total_gfa_sqm": 9_800.0, "housing_gfa_sqm": 9_800.0,
                          "pdf_url": "https://www.mos.ru/upload/x.pdf"}},
    "tep_coverage": {"read": 1, "failed": 0, "unknown": 1, "silent": 0, "reasons": {}},
    "tep_pending": ["349135220"],
}


def _app():
    from fastapi import FastAPI

    from auction_search.api import install

    app = FastAPI()
    app.state.market_discovery_service = SimpleNamespace(
        krt=SimpleNamespace(
            catalogue=lambda **_: list(_PROJECTS),
            status=lambda: {"complete": True, "refreshing": False,
                            "decisions_refreshing": False, "retrieved_at": 1_788_000_000,
                            "ttl_seconds": 86_400},
            decisions=lambda **_: dict(_DECISIONS),
        ),
    )
    install(app)
    return app


READ = """() => ({
  rows: document.querySelectorAll('#krtRows tr').length,
  first: [...document.querySelectorAll('#krtRows tr')].map(t => t.children[0].innerText.split('\\n')[0]),
})"""


@pytest.mark.timeout(180)
def test_every_status_choice_gives_its_rows_and_none_vanish() -> None:
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

            def rows_for(value: str) -> int:
                page.evaluate(
                    "(v)=>{document.getElementById('krtStatus').value=v;filterKrt()}", value)
                page.wait_for_timeout(120)
                return page.evaluate("document.querySelectorAll('#krtRows tr').length")

            counts = {value: rows_for(value)
                      for value in ("", "planned", "running", "draft", "unparsed")}
            options = page.evaluate(
                "[...document.getElementById('krtStatus').options].map(o=>o.textContent)")
            page.evaluate("document.getElementById('krtStatus').value='';filterKrt()")

            # Сортировка: нажимаем сам заголовок, как человек.
            page.click("#krtTableWrap th[data-sort='area']")
            page.wait_for_timeout(150)
            by_area = page.evaluate(READ)
            marks = page.evaluate(
                "[...document.querySelectorAll('#krtTableWrap th[data-sort]')]"
                ".map(t=>[t.dataset.sort,t.textContent])")
            page.click("#krtTableWrap th[data-sort='area']")
            page.wait_for_timeout(150)
            by_area_back = page.evaluate(READ)
            cells = page.evaluate(
                "[...document.querySelectorAll('#krtRows tr')].map(t=>t.innerText)")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors
    assert everything == 6, "каталог и проекты решений не сложились в один список"
    assert counts[""] == 6
    # Каждый выбор даёт свои строки, и вместе они дают ВЕСЬ каталог: площадка,
    # не попавшая ни в один выбор, исчезает с экрана молча.
    assert counts["planned"] == 2, counts
    assert counts["running"] == 1, counts
    assert counts["draft"] == 2, "выбор «проект решения» снова не даёт ничего"
    assert counts["unparsed"] == 1, counts
    assert counts["planned"] + counts["running"] + counts["draft"] + counts["unparsed"] \
        == counts[""], counts
    # Число рядом с выбором отвечает на «сколько это даст» до нажатия: пустой
    # выбор иначе неотличим от сломанного фильтра.
    assert any("(2)" in one for one in options), options

    # Внутри равных значений грубой колонки порядок остаётся по баллу, а не
    # по алфавиту: у «Шага» три значения на весь каталог, и алфавит внутри них
    # читается как «сортировка ничего не сделала».
    # Порядок меняется и виден: у отсортированной колонки стоит стрелка.
    assert by_area["first"][0] == "В работе", by_area["first"]
    assert by_area_back["first"][0] != by_area["first"][0], "второе нажатие не перевернуло"
    assert [name for key, name in marks if key == "area"][0].endswith("▼"), marks
    assert all(not name.endswith(("▲", "▼")) for key, name in marks if key != "area"), marks

    # Съехавшая строка не выдаёт свои сдвинутые значения за прочитанные.
    shifted = [one for one in cells if "Съехавшая" in one][0]
    assert "26 500" not in shifted and "не разобрано" in shifted, shifted
    # У площадки, ТЭП которой взят из самого решения, стоят её числа; у той,
    # чей документ ещё не прочитан, — прочерк, а не ноль.
    read = [one for one in cells if "Тишинский" in one][0]
    unread = [one for one in cells if "Власова" in one][0]
    # Неразрывный пробел разделителя тысяч — часть форматирования, не числа.
    assert "9\u00a0800" in read and "0.28 га" in read, read
    assert "— · ТЭП не указан" in unread, unread
    assert "0 · " not in unread, "балл без ТЭП снова печатается нулём"
