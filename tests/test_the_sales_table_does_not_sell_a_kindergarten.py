"""Соцобъект не стоит в таблице продаж, и его мощность не в метрах.

«Почему школа, поликлиника и СОШ в метрах квадратных стоят» (владелец,
27.09.2026, снимок прода 0.24.41, вкладка «Доходы», таблица по очередям).

Строки ДОО, СОШ и поликлиники показывали объём очереди «350 м²», «1 000 м²»,
«79 м²» при выручке ноль. Это не метры, а мощность: места, места и посещения
в смену. Единица приходила ЛИТЕРАЛОМ: остаточный цикл сборки списка продуктов
дописывал строку ТЭП, не попавшую в продаваемые, с `"unit": "м²"` и
количеством из `units`. Количество брали из одного поля, подпись — из
литерала.

Две беды, и лечатся они разным:
  1. Единица клетки обязана быть единицей ЭТОГО числа. Берётся у объявленной
     меры счёта (`TEP_COUNT_MEASURE`), а не угадывается.
  2. Соцобъект не продаётся по построению, и в таблице ПРОДАЖ ему не место
     вовсе. Его метры и мощность видны в таблице ТЭП, где у них свои колонки.

Признак «продаётся ли» объявлен, а не выведен из нулевой выручки: продукт,
который в этом расчёте ничего не продал, — не то же самое, что продукт,
который не продаётся никогда.

Запуск: python3 -m pytest tests/test_the_sales_table_does_not_sell_a_kindergarten.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_legacy as core  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402

PORT = 8791
SOCIAL = ("kindergarten", "school", "clinic")


def _inputs() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(project_name="Очереди и соцобъекты", kindergarten_places=350,
                  school_places=1000, clinic_capacity=79,
                  social_mode="Строительство")
    return inputs


def _phasing() -> dict:
    return {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
            "phase_gap_months": 12,
            "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                        "construction_months": 30} for i in range(2)]}


def _tep() -> dict:
    return {key: dict(value) for key, value in core.TEP_DEFAULT.items()}


@pytest.fixture(scope="module")
def phased():
    bundle = core._run_authoritative_model(_inputs(), _tep(), [], _phasing())
    return bundle["consolidated"]["report"]


def test_the_fixture_really_builds_social_objects(phased):
    """Предохранитель: без соцобъектов проверка зелена на любом коде."""
    by_key = {p["key"]: p for p in phased["products"]}
    for key in SOCIAL:
        assert by_key[key]["quantity"] > 0, key


def test_the_capacity_is_not_labelled_in_metres(phased):
    """350 — это места, а не метры."""
    by_key = {p["key"]: p for p in phased["products"]}
    assert by_key["kindergarten"]["unit"] == core.COUNT_PLACES
    assert by_key["school"]["unit"] == core.COUNT_PLACES
    assert by_key["clinic"]["unit"] == core.COUNT_VISITS, (
        "поликлиника меряется посещениями в смену, а не местами")
    for key in SOCIAL:
        assert by_key[key]["unit"] != "м²", key


def test_a_social_object_says_it_is_not_for_sale(phased):
    """Признак объявлен, а не выведен из нулевой выручки."""
    by_key = {p["key"]: p for p in phased["products"]}
    for key in SOCIAL:
        assert by_key[key]["sellable"] is False, key
    assert by_key["apartments"]["sellable"] is True
    # Продукт, который просто ничего не продал, продаваемым быть не перестаёт.
    idle = [p for p in phased["products"]
            if p.get("sellable") is True and not p.get("revenue")]
    assert idle, "в стенде нет ни одного невыстрелившего продаваемого продукта"


def test_the_measure_reaches_the_queue_rows_too(phased):
    """Таблица со снимка — по очередям, и мера нужна в каждой её клетке."""
    by_key = {p["key"]: p for p in phased["phase_products"]}
    for key in SOCIAL:
        row = by_key[key]
        assert row["unit"] != "м²", key
        for phase in row["phases"]:
            assert phase["unit"] != "м²", (key, phase["phase"])


def test_the_money_does_not_move():
    """Правка про подпись и состав таблицы, а не про экономику."""
    plain = core.calculate(core.CalcRequest(inputs=_inputs(), tep=_tep(), rates=[]))
    assert plain["summary"]["revenue"] > 0
    without = copy.deepcopy(core.DEFAULT_INPUTS)
    without.update(project_name="Очереди и соцобъекты")
    bare = core.calculate(core.CalcRequest(inputs=without, tep=_tep(), rates=[]))
    # Соцобъекты денег продаж не приносят: выручка с ними и без них одна.
    assert plain["summary"]["revenue"] == bare["summary"]["revenue"]


def test_in_a_real_browser_the_sales_table_has_no_kindergarten():
    """Проверяется ОТРИСОВАННАЯ страница: в исходнике верный код и сломанный
    выглядят одинаково, а вопрос владельца — про то, что он видит."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    from main_registry import app as registry_app

    with serve(registry_app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(f"{base}/classic", wait_until="domcontentloaded")
            # Ждать конца загрузки, а не часы: `initializeApp` сам зовёт
            # `calculate()` после ответа `/current-key-rate`. Пришёл он позже
            # 700 мс — и загрузочный расчёт обгонял второй расчёт теста: тот
            # возвращал null (номер устарел), а шапка оставалась от очередей.
            tab.wait_for_function("window.__developaidBooted===true", timeout=60000)
            # Таблица продаж рисуется ДВУМЯ ветками — по очередям и сводной.
            # Проверяются обе: починенная одна выглядит как починенные обе.
            got = tab.evaluate(
                """async (payload)=>{
                  const read=()=>{
                    const table=document.getElementById('salesReportTable');
                    const head=document.getElementById('salesReportHead');
                    const tep=document.getElementById('reportTep');
                    return {sales:(table&&table.textContent)||'',
                            head:(head&&head.textContent)||'',
                            tep:(tep&&tep.textContent)||''};
                  };
                  Object.assign(inputs, payload.inputs);
                  phasing = payload.phasing;
                  const first=await calculate();
                  const phased=read();
                  phasing = {enabled:false, phases:[]};
                  const second=await calculate();
                  return {phased:phased, plain:read(),
                          superseded:[first===null, second===null]};
                }""",
                {"inputs": {k: v for k, v in _inputs().items()
                            if not k.startswith("_")},
                 "phasing": _phasing()})
        finally:
            browser.close()

    # Читается то, что нарисовал СВОЙ расчёт: обогнанный другим он ничего не
    # рисует, и проверка смотрела бы на чужую таблицу.
    assert got["superseded"] == [False, False], got["superseded"]
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    for view in ("phased", "plain"):
        sales = got[view]["sales"]
        assert sales.strip(), f"таблица продаж ({view}) пуста — проверять нечего"
        assert "Квартиры" in sales, f"продаваемое из таблицы ({view}) пропало"
        # «Ничего не продал в этом расчёте» и «не продаётся по построению» —
        # разные вещи. Кладовые в стенде нулевые, но продаваемые, и строка их
        # обязана остаться: иначе человек не увидит, что продукт он завёл, а
        # объём не задал. Отбор по выручке выкинул бы её вместе с садиком.
        assert "Кладовые" in sales, (
            f"непроданное выкинули вместе с непродаваемым ({view}): {sales[:300]}")
        for label in ("ДОО", "СОШ", "Поликлиника"):
            assert label not in sales, (
                f"«{label}» стоит в таблице продаж ({view}): {sales[:300]}")
        # И не исчезло из проекта: метры и мощность видны в таблице ТЭП.
        assert "ДОО" in got[view]["tep"], (
            f"соцобъект пропал и из ТЭП ({view}) — это не то же самое")
    # Предохранитель: ветки таблицы РАЗНЫЕ, и проверены обе, а не одна дважды.
    # Имена очередей стоят в шапке, а не в теле: тело — числа по колонкам.
    assert "О1" in got["phased"]["head"], got["phased"]["head"][:200]
    assert "О1" not in got["plain"]["head"], got["plain"]["head"][:200]
