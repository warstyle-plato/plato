"""Вкладка «Тестовый отчёт bnMAP»: стоит рядом с отчётом и ничего не считает.

Владелец попросил её для сравнения источников (30.08.2026) — и в том же
разговоре сказал главное: «не сломай текущий рыночный отчёт, этот пока тест».
Отсюда всё устройство: отдельный свёрнутый блок, отдельный маршрут, ни одной
правки в сборке отчёта.

Запуск: python3 -m pytest tests/test_bnmap_comparison_tab.py -q
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import bnmap, bnmap_ui  # noqa: E402
from market_search import cabinet  # noqa: E402


# Форма ответа снята с живого `analytics.reportNearBy` и `analytics.indicators`
# 30.08.2026. Числа здесь свои — важна форма, а чужие данные в репозитории не
# место.
ANSWER = {
    "source": "bnMAP.pro",
    "account": {"tools": ["irn", "service_bi"], "expires": ["2026-09-02"]},
    "note": "Тестовый свод: числа bnMAP показаны как пришли.",
    "errors": [],
    "indicators": {
        "date": "2026-08-25", "pre_date": "2026-08-10",
        "short": {"Kva": {
            "M": {"KolProj": {"val": "350.00"}, "Kol": {"val": "42581.00"},
                  "Avgm2": {"val": "858503.70", "percent": "-0.59"}},
            "MO": {"KolProj": {"val": "240.00"}, "Kol": {"val": "42281.00"},
                   "Avgm2": {"val": "223198.34", "percent": "1.84"}}}},
    },
    "nearby": {
        "radius": [{"id": "1", "name": "Первый", "distance": 0},
                   {"id": "2", "name": "Второй", "distance": 1.2}],
        "nearby": [{"object_id": "1", "project": "Первый", "class": "Бизнес",
                    "agreement": "ДДУ с эскроу", "start_sales_date": "01.02.2018",
                    "date_state_commission": "2027-12-31", "interior": "Без отделки",
                    "metrprice_avg": {"metrprice_avg_total": 955985},
                    "apart_total": {"expo": "181"},
                    "pace_lots": 11, "unrealized_count": 1623}],
        "location": {"2016-02-01": {"current_project_metrprice_avg": 225395.85,
                                    "five_projects_metrprice_avg": 225395.85,
                                    "location_buildings": {"metrprice_avg": 275022.04,
                                                           "expo_num": 3038}}},
    },
}


def test_the_tab_is_on_the_cabinet_page_and_the_placeholder_is_filled() -> None:
    page = cabinet.cabinet_page()
    assert bnmap_ui.PLACEHOLDER not in page, "плейсхолдер вкладки остался неподставленным"
    assert 'id="bnmap"' in page
    assert "Тестовый отчёт bnMAP" in page


def test_the_tab_script_parses() -> None:
    """Незакрытая кавычка в скрипте убивает страницу молча — проверяем узлом.

    Строковый тест такого не ловит: искомая строка есть и в сломанном файле.
    """
    script = re.search(r"<script>(.*?)</script>", bnmap_ui.markup(), re.S)
    assert script, "во вкладке нет скрипта"
    path = ROOT / "tests" / "_bnmap_tab.js"
    path.write_text(script.group(1), encoding="utf-8")
    try:
        done = subprocess.run([_node(), "--check", str(path)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    finally:
        path.unlink(missing_ok=True)


def _node() -> str:
    for name in ("node", "nodejs"):
        try:
            subprocess.run([name, "--version"], capture_output=True, check=True)
            return name
        except Exception:  # noqa: BLE001
            continue
    import pytest

    pytest.skip("node в образе нет")


def test_the_answer_is_shown_as_it_came() -> None:
    html = bnmap_ui.render(ANSWER)
    assert "irn, service_bi" in html and "2026-09-02" in html
    # Зоны названы по-русски, а список зон берётся из ответа, не из кода.
    assert "Московская область" in html and "858 504" in html
    # Сосед виден со своими полями, включая те, которых у «Пульса» нет вовсе.
    assert "ДДУ с эскроу" in html and "955 985" in html
    assert "Второй" in html, "сосед без карточки обязан остаться в таблице"


def test_the_tab_counts_nothing() -> None:
    """Показ, а не второй счёт: разойдясь, обе поверхности выглядели бы верными.

    Форматирование числа разрешено — это оформление; арифметика над величинами
    запрещена, как и в адаптере результата 2.0.
    """
    body = (ROOT / "market_search" / "bnmap_ui.py").read_text()
    code = "\n".join(line.split("#")[0] for line in body.splitlines())
    for sign in (" / ", " * ", " + 0", "sum("):
        assert sign not in code.replace('" / "', ""), f"во вкладке считают: {sign}"


def test_only_methods_with_a_seen_answer_may_be_called() -> None:
    """Незнакомый метод — отказ на месте, а не запрос наугад.

    Каталог bnMAP обещает 253 метода, но обещание имени не ответ: `objectDeals`
    и `domrf.declarations` отвечают 403, а `perspectiveProjects` — пустым
    списком без ошибки. Пока ответ не увиден, звать метод нельзя.
    """
    session = bnmap.Session(ROOT / "tests" / "_bnmap_tmp")
    assert session.call("analytics.magicDeals", {}) is None
    assert any("не сверен" in line for line in session.errors)
    for method in bnmap.REPORT_METHODS:
        assert method in bnmap.VERIFIED


def test_the_report_route_is_registered_and_gated() -> None:
    body = (ROOT / "market_search" / "api.py").read_text()
    assert '@app.get("/market/bnmap/report")' in body
    route = body[body.index('@app.get("/market/bnmap/report")'):]
    assert "cabinet_module.require_cabinet(request)" in route[:2000]


def test_the_object_is_found_by_words_coordinates_or_number(monkeypatch, tmp_path) -> None:
    """Адрес превращается в номер справочником службы отчётов — он бесплатный.

    Раньше вкладка спрашивала номер руками: `layers.data` за региональной
    лицензией, и превратить адрес в идентификатор было нечем. Оказалось —
    есть чем: `v2.reports.projectsMap` отдаёт 1869 проектов Москвы и области с
    координатами и подписки на платформу не требует.
    """
    known = [
        {"object_id": 28, "name": "Матч Поинт", "address": "Василисы Кожиной ул., вл. 13",
         "latitude": 55.736242, "longitude": 37.499905},
        {"object_id": 1539, "name": "Prime Park / Прайм Парк", "address": "Ленинградский пр-т",
         "latitude": 55.794, "longitude": 37.52},
    ]
    monkeypatch.setattr(bnmap, "directory", lambda *a, **k: known)
    assert bnmap.find(tmp_path, "1539")["how"] == "номер введён руками"
    by_name = bnmap.find(tmp_path, "прайм парк")
    assert by_name["object_id"] == 1539 and "названи" in by_name["how"]
    by_address = bnmap.find(tmp_path, "Василисы Кожиной")
    assert by_address["object_id"] == 28
    by_point = bnmap.find(tmp_path, "55.7362, 37.4999")
    assert by_point["object_id"] == 28 and by_point["candidates"][0]["distance_km"] < 0.1


def test_how_the_object_was_recognised_is_shown() -> None:
    """Номер по слову и номер руками выглядят одинаково, а доверие разное."""
    html = bnmap_ui.render({**ANSWER, "found": {
        "how": "совпадение по названию или адресу", "object_id": 1539,
        "candidates": [{"name": "Прайм Парк", "object_id": 1539}]}})
    assert "Объект опознан" in html and "1539" in html
