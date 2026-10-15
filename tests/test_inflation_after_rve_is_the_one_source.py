"""«Инфляция после РВЭ» — единственный источник роста цены после РВЭ.

Было: движок брал рост после РВЭ из «Ежемесячного роста цены после РВЭ»
(`monthly_growth_post_pct`), а видимая «Инфляция после РВЭ, % год» уходила
только в шаблон ПЛАТО — правка её не меняла расчёт. Решение владельца
(15.10.2026): одно поле. Месячная ставка выводится из годовой,
(1 + г)^(1/12) − 1, и в движке, и в книге — формулой от ячейки инфляции.

Проект, сохранённый раньше, несёт прежнее поле. Тронутое значение
переносится в инфляцию с подписью происхождения; нетронутое умолчание (0,25)
снимается — действует видимая инфляция.

Запуск: python3 -m pytest tests/test_inflation_after_rve_is_the_one_source.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402
import v4_inputs  # noqa: E402

core = _wrapper.core
openpyxl = pytest.importorskip("openpyxl")
PORT = 19813


def _inputs(**extra) -> dict:
    return {**core.DEFAULT_INPUTS, "purchase_price_mln": 1000,
            "share_before_rve_pct": 70, **extra}


def _tep() -> dict:
    return {key: dict(row) for key, row in core.TEP_DEFAULT.items()}


def _run(x: dict) -> dict:
    return core.calculate(core.CalcRequest(inputs=x, tep=_tep(), rates=[]))


def _apartments(result: dict) -> float:
    return next(p["revenue"] for p in result["report"]["products"] if p["key"] == "apartments")


def test_the_visible_inflation_moves_the_revenue():
    """Падает на прежнем поведении: там инфляция в расчёт не доходила."""
    low = _apartments(_run(_inputs(inflation_after_rve_pct=0)))
    high = _apartments(_run(_inputs(inflation_after_rve_pct=12)))
    assert high > low * 1.005, (low, high)


def test_the_monthly_rate_is_the_compound_twelfth_root():
    assert core.growth_post_monthly_pct({"inflation_after_rve_pct": 12.682503}) == pytest.approx(1.0, abs=1e-6)
    assert "monthly_growth_post_pct" not in core.DEFAULT_INPUTS
    assert core.growth_post_monthly_pct({}) == pytest.approx((1.03 ** (1 / 12) - 1) * 100)


def test_a_touched_legacy_value_moves_into_inflation_and_keeps_the_money():
    legacy = _run(_inputs(monthly_growth_post_pct=0.5))
    annual = (1.005 ** 12 - 1) * 100
    migrations = legacy.get("input_migrations")
    assert migrations and migrations[0]["key"] == "inflation_after_rve_pct", migrations
    assert migrations[0]["value"] == pytest.approx(annual, abs=1e-5)
    assert "0,5%/мес." in migrations[0]["text"]
    # Перенос не меняет деньги: тот же месячный рост, что считал прежний движок.
    direct = _run(_inputs(inflation_after_rve_pct=annual))
    assert _apartments(legacy) == pytest.approx(_apartments(direct), rel=1e-9)


def test_an_untouched_legacy_default_gives_way_to_the_visible_field():
    x = _inputs(monthly_growth_post_pct=0.25, inflation_after_rve_pct=6)
    result = _run(x)
    assert result["input_migrations"] == [{"from": "monthly_growth_post_pct", "key": None}]
    assert _apartments(result) == pytest.approx(_apartments(_run(_inputs(inflation_after_rve_pct=6))))


def test_a_legacy_default_marked_by_hand_is_a_decision():
    x = _inputs(monthly_growth_post_pct=0.25, _field_origin={
        "inputs.monthly_growth_post_pct": {"source": "manual", "text": "вписано вручную"}})
    migrations = core.migrate_growth_post(x)
    assert migrations[0]["value"] == pytest.approx((1.0025 ** 12 - 1) * 100, abs=1e-5)
    assert x["inflation_after_rve_pct"] == migrations[0]["value"]
    assert "monthly_growth_post_pct" not in x
    assert x["_field_origin"]["inputs.inflation_after_rve_pct"]["source"] == "migrated"
    assert "inputs.monthly_growth_post_pct" not in x["_field_origin"]


def test_the_v4_book_derives_b65_from_the_inflation_cell():
    content, _, _ = core.build_project_workbook(_inputs(inflation_after_rve_pct=6), _tep(), [], {},
                                                project_name="П")
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    sheet = v4_inputs.inputs(book)
    assert str(sheet["B65"].value).replace(" ", "") == "=(1+F59)^(1/12)-1"
    assert sheet["F59"].value == pytest.approx(0.06)


def test_the_m2_book_derives_growth_after_rve_from_inflation():
    data, meta = core.build_plato_model_v2(_inputs(inflation_after_rve_pct=6), _tep(), [],
                                           project_name="П")
    book = openpyxl.load_workbook(io.BytesIO(data))
    sales = book["ПРОДАЖИ"]
    formulas = [str(c.value) for row in sales.iter_rows() for c in row
                if isinstance(c.value, str) and "^(1/12)-1" in c.value]
    # Четыре основных продукта — по формуле от ячейки инфляции «Вводных».
    assert len(formulas) >= 4, formulas
    assert all("Вводные!$B$" in f for f in formulas), formulas


def test_in_a_real_browser_a_saved_legacy_value_lands_in_the_inflation_field():
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
            tab.wait_for_function("window.__developaidBooted===true", timeout=60000)
            got = tab.evaluate(
                """async ()=>{
                  // Состояние, сохранённое до решения: прежнее поле тронуто.
                  inputs.monthly_growth_post_pct=0.5;
                  phasing={enabled:false, phases:[]};
                  const done=await calculate();
                  const field=document.getElementById('f_inflation_after_rve_pct');
                  const wrap=field&&field.parentElement;
                  return {superseded: done===null,
                          legacy: Object.prototype.hasOwnProperty.call(inputs,'monthly_growth_post_pct'),
                          value: Number(inputs.inflation_after_rve_pct),
                          shown: field?Number(field.value):null,
                          note: wrap?wrap.textContent:'',
                          oldField: !!document.getElementById('f_monthly_growth_post_pct')};
                }""")
        finally:
            browser.close()

    assert got["superseded"] is False
    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["legacy"] is False and got["oldField"] is False
    assert got["value"] == pytest.approx((1.005 ** 12 - 1) * 100, abs=1e-4)
    assert got["shown"] == pytest.approx(got["value"], abs=1e-4)
    assert "пересчитано из прежнего поля" in got["note"], got["note"]
