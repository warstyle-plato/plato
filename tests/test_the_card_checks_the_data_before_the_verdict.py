"""Сверка «решение ↔ карточка» стоит на экране и ДО вердикта.

«Вердикт стоит раньше проверки данных» — замечание владельца о правой карточке
КРТ. Расхождение считалось на сервере (`decision_tep_check`) и не выводилось на
экран НИ РАЗУ: ноль упоминаний в `ui.py`. Ровно тот же класс, что уже ловился с
реновацией и признаками карточки города, — посчитанное на сервере, но не
показанное, неотличимо от непосчитанного.

Вторая половина правки — про сам ответ. Прежняя `catalogue_mismatch` отдавала
ПУСТОЙ СПИСОК и когда всё сошлось, и когда сверять было не с чем; тест на неё
даже писал в комментарии «нечего сверять — не сошлось», а утверждал `== []`.
Ответа три, и на экране они звучат по-разному.

Проверяется нажатием в настоящем Chromium: строковый тест увидел бы имя
функции и в сломанном коде.

Запуск: python3 -m pytest tests/test_the_card_checks_the_data_before_the_verdict.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_search import krt_decision_tep as tep  # noqa: E402

PORT = 18795

# Три площадки — три ответа сверки. У «сошлось» и «расходится» есть карточка и
# прочитанное решение; у третьей карточки города нет вовсе, и сличать её цифры
# не с чем по построению.
_PROJECTS = [
    {"slug": "agrees", "name": "Сошлось", "status": "Планируемый", "okrug": "ЦАО",
     "area_ha": 3.0, "total_gfa_sqm": 90_000, "housing_gfa_sqm": 60_000},
    {"slug": "differs", "name": "Разошлось", "status": "Планируемый", "okrug": "САО",
     "area_ha": 1.0, "total_gfa_sqm": 20_000, "housing_gfa_sqm": 10_000},
    {"slug": "unread", "name": "Решение не читано", "status": "Планируемый",
     "okrug": "ВАО", "area_ha": 2.0, "total_gfa_sqm": 30_000, "housing_gfa_sqm": 20_000},
]

_DECISIONS = {
    "total": 3, "matched": 2, "complete": True, "stale": False,
    "retrieved_at": 1_788_000_000,
    "decisions": [
        {"id": "100", "title": "Проект решения …", "url": "https://www.mos.ru/x/1/",
         "address": "Первая ул., влд. 1", "okrug": "ЦАО", "published_at": 1_787_605_200},
        {"id": "200", "title": "Проект решения …", "url": "https://www.mos.ru/x/2/",
         "address": "Вторая ул., влд. 2", "okrug": "САО", "published_at": 1_787_605_200},
        {"id": "300", "title": "Проект решения …", "url": "https://www.mos.ru/x/3/",
         "address": "Третья ул., влд. 3", "okrug": "ЮАО", "published_at": 1_787_605_200},
    ],
    "matched_rows": [
        {"slug": "agrees", "published_at": 1_787_605_200,
         "url": "https://www.mos.ru/x/1/", "title": "Проект решения …", "id": "100"},
        {"slug": "differs", "published_at": 1_787_605_200,
         "url": "https://www.mos.ru/x/2/", "title": "Проект решения …", "id": "200"},
    ],
    "tep": {
        "100": {"available": True, "read": True, "area_ha": 3.0,
                "total_gfa_sqm": 90_000.0, "housing_gfa_sqm": 60_000.0},
        # Гектары не сходятся вдвое: пара собрана неверно, и метрам её верить
        # нельзя — это и обязано быть сказано словами.
        "200": {"available": True, "read": True, "area_ha": 2.0,
                "total_gfa_sqm": 20_000.0, "housing_gfa_sqm": 10_000.0},
    },
    "tep_coverage": {"read": 2, "failed": 0, "unknown": 1, "silent": 0, "reasons": {}},
    "tep_pending": [],
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


# --- сам ответ сверки --------------------------------------------------------

def test_nothing_to_compare_is_not_agreement():
    """Три ответа, а не два: сошлось, расходится и сверять не с чем."""
    ours = {"area_ha": 3.0, "total_gfa_sqm": 90_000.0, "housing_gfa_sqm": 60_000.0}

    same = tep.catalogue_check(ours, dict(ours))
    assert same["problems"] == []
    assert "площадь территории" in same["compared"], same

    other = tep.catalogue_check(ours, {"area_ha": 0.93, "total_gfa_sqm": 51_040})
    assert any("площадь территории" in one for one in other["problems"]), other
    assert any("общий объём" in one for one in other["problems"]), other

    # Главное: у карточки без величин сверять НЕ С ЧЕМ, и от «сошлось» это
    # отличается составом сверенного, а не пустотой списка расхождений.
    empty = tep.catalogue_check(ours, {})
    assert empty["problems"] == []
    assert empty["compared"] == [], empty
    assert empty != same, "«не с чем сверять» неотличимо от «сошлось»"


# --- и то же самое на экране -------------------------------------------------

@pytest.mark.timeout(180)
def test_the_card_says_the_check_before_the_score() -> None:
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

            def card(slug: str) -> str:
                page.evaluate("(s)=>selectKrt(state.krt.find(x=>x.slug===s))", slug)
                page.wait_for_timeout(120)
                # Тихая проверка («сверять не с чем») с 0.22.10 живёт в разделе
                # «чего не хватает»: на живом каталоге она у 501 строки из 580 и
                # постоянной припиской сверху перестаёт читаться. Раскрываем всё,
                # иначе innerText свёрнутого раздела её просто не покажет.
                page.evaluate(
                    "document.querySelectorAll('#krtSide details')"
                    ".forEach(d=>{d.open=true})")
                page.wait_for_timeout(60)
                return page.evaluate("document.getElementById('krtSide').innerText")

            agrees = card("agrees")
            differs = card("differs")
            unread = card("unread")
            # Площадка-решение: карточки города нет, второго числа не существует.
            decision_slug = page.evaluate(
                "(state.krt.find(x=>x.no_card)||{}).slug")
            no_card = card(decision_slug) if decision_slug else ""
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not errors, errors

    # Сошлось — и сказано, ЧТО именно сверено: «сошлось» без состава сверки
    # ничем не отличается от «сверять было не с чем».
    assert "Проверка данных: сошлось" in agrees, agrees
    assert "площадь территории" in agrees, agrees

    # Расходится — расхождение названо числами обоих источников, и сказано,
    # что каталог решением не подменяется.
    assert "Проверка данных: расходится" in differs, differs
    assert "в решении 2" in differs and "в каталоге 1" in differs, differs

    # Не читано и нет карточки — два разных ответа, и ни один не «сошлось».
    assert "сверять не с чем" in unread, unread
    assert "пара с документом не найдена" in unread, unread
    assert "Решение прочитано" not in unread, "сказано «прочитано» про непрочитанное"
    assert "Проверка данных: сошлось" not in unread, unread
    if no_card:
        assert "сверять не с чем" in no_card, no_card

    # И порядок: проверка, которой ЕСТЬ что сказать, стоит ВЫШЕ вердикта —
    # ради этого правка. Молчащая уехала вниз, и это держит
    # tests/test_the_krt_card_says_each_thing_once.py.
    assert agrees.index("Проверка данных") < agrees.index("Балл площадки"), agrees
    assert differs.index("Проверка данных") < differs.index("Балл площадки"), differs
    assert unread.index("Балл площадки") < unread.index("Проверка данных"), unread
