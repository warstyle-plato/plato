"""Офисный проект: продажа и аренда рядом, одним расчётом.

Владелец, 22.10.2026, о тизере, отчёте и книге офиса на Пролетарском пр.,
вл. 20: «что это за убожество? а не модель офисника». Решения владельца:

* офис показывает способы продажи бок о бок — продажу блоками после ввода и аренду
  с продажей здания, с 24.10.2026 и продажу по ДДУ, — и видно, какой выгоднее
  (`calculate()["office_paths"]`);
* допущения зависят от класса офиса (B, B+, A, A+), цена продажи — цена
  класса в нежилом проекте, ставка аренды — из неё;
* доходность на затраты — NOI на ВСЕ затраты создания, а не на стройку здания;
* чувствительность цены входа двигает и цену участка, и выкуп участков и
  зданий: прежде «±68 млн» сдвигали 5 млн цены участка, размах выходил нулём,
  а вывод называл параметр главным («с 1,062 до 1,062 в худшую сторону»);
* подземный паркинг нежилого проекта — паркинг его офиса, а не «остаток жилья».

Запуск: python3 -m pytest tests/test_an_office_shows_sale_and_rent_side_by_side.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402

# Пролетарский пр., вл. 20: площади и цена входа из присланного отчёта.
PROLETARSKY = dict(
    project_kind=core.PROJECT_KIND_NONRESIDENTIAL, offices_enabled=True,
    offices_gba_sqm=22842, offices_saleable_sqm=15030, purchase_price_mln=5,
    land_buyout_mln=675, offices_cost_th_per_sqm=110, offices_price_th_per_sqm=273,
    offices_rent_th_per_sqm_month=2.5, offices_exit_cap_pct=10.5, offices_leaseup_months=18,
)


def _spec(**over) -> tuple[dict, dict]:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            t[key][col] = 0
    for key in core.NONRESIDENTIAL_CLEARED_INPUTS:
        x[key] = 0
    x.update(PROLETARSKY)
    x.update(over)
    t.setdefault("offices", {}).update(gns=22842, total_area=21472, useful=15030, saleable=15030)
    return x, t


def _calc(**over) -> dict:
    x, t = _spec(**over)
    return core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))


@pytest.fixture(scope="module")
def ddu() -> dict:
    return _calc(offices_strategy=ns.STRATEGY_DDU)


@pytest.fixture(scope="module")
def direct() -> dict:
    return _calc(offices_strategy=ns.STRATEGY_DIRECT)


# --- три способа одним расчётом ------------------------------------------------

def test_the_office_project_carries_three_ways_to_sell(ddu) -> None:
    """Владелец, 24.10.2026: «Новая книга считает и ДДУ» — продажа по ДДУ
    стоит третьим способом рядом с продажей блоками и арендой."""
    paths = {p["key"]: p for p in ddu["office_paths"]["paths"]}
    assert set(paths) == {ns.STRATEGY_DDU, ns.STRATEGY_DIRECT, ns.STRATEGY_INCOME}
    for path in paths.values():
        assert "error" not in path, path
        assert path["revenue"] > 0 and path["capex"] > 0
    # Аренда меряется NOI, ставкой и стоимостью здания; продажа — нет.
    assert paths[ns.STRATEGY_INCOME]["stabilized_noi"] > 0
    assert paths[ns.STRATEGY_INCOME]["exit_value"] > 0
    assert paths[ns.STRATEGY_DIRECT]["stabilized_noi"] is None
    # Продажа по ДДУ: выручка офиса — его эскроу-продажи, долг — ПФ и LLCR;
    # у продажи блоками и аренды ПФ нет — пусто, а не ноль.
    by_ddu = paths[ns.STRATEGY_DDU]
    assert by_ddu["sale_revenue"] == pytest.approx(by_ddu["revenue"], rel=1e-9)
    assert by_ddu["llcr"] == ddu["summary"]["llcr"] and by_ddu["pf_peak"] > 0
    assert by_ddu["commercial_costs"] == ddu["summary"]["commercial_costs"] > 0
    assert paths[ns.STRATEGY_DIRECT]["llcr"] is None and paths[ns.STRATEGY_INCOME]["pf_peak"] is None
    best = max(paths.values(), key=lambda p: p["npv"])["key"]
    assert ddu["office_paths"]["better"] == best


def test_the_ddu_way_of_a_project_on_ddu_is_the_main_calculation(ddu) -> None:
    """Проект по ДДУ: его способ — основной расчёт, а не второй счёт."""
    block = ddu["office_paths"]
    assert block["current"] == ns.STRATEGY_DDU
    path = next(p for p in block["paths"] if p["key"] == ns.STRATEGY_DDU)
    s = ddu["summary"]
    assert (path["npv"], path["net_profit"], path["revenue"]) == (s["npv"], s["net_profit"], s["revenue"])


def test_the_ddu_way_equals_a_project_run_on_ddu(direct, ddu) -> None:
    path = next(p for p in direct["office_paths"]["paths"] if p["key"] == ns.STRATEGY_DDU)
    assert path["npv"] == pytest.approx(ddu["summary"]["npv"], rel=1e-9)
    assert path["llcr"] == pytest.approx(ddu["summary"]["llcr"], rel=1e-9)
    # ПФ Пролетарского к концу проекта не погашен: NPV капитала снят подписью.
    assert path["npv_equity"] is None and path["equity_returns_label"]


def test_the_path_of_the_project_is_the_main_calculation(direct) -> None:
    """Путь, совпавший со стратегией проекта, — числа основного расчёта, а не
    второй счёт: одно число — один владелец."""
    block = direct["office_paths"]
    assert block["current"] == ns.STRATEGY_DIRECT
    path = next(p for p in block["paths"] if p["key"] == ns.STRATEGY_DIRECT)
    s = direct["summary"]
    assert (path["npv"], path["net_profit"], path["revenue"]) == (s["npv"], s["net_profit"], s["revenue"])


def test_a_path_equals_a_project_run_with_that_strategy(ddu, direct) -> None:
    path = next(p for p in ddu["office_paths"]["paths"] if p["key"] == ns.STRATEGY_DIRECT)
    assert path["npv"] == pytest.approx(direct["summary"]["npv"], rel=1e-9)
    assert path["net_profit"] == pytest.approx(direct["summary"]["net_profit"], rel=1e-9)


def test_a_housing_project_has_no_office_paths() -> None:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x.update(offices_enabled=True)
    result = core.calculate(core.CalcRequest(inputs=x, tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert "office_paths" not in result


def test_the_sensitivity_does_not_compare_paths_in_every_scenario() -> None:
    x, _ = _spec()
    assert core.office_path_prefixes(x) == ("offices",)
    token = core.OFFICE_PATHS_ON.set(False)
    try:
        assert core.office_path_prefixes(x) == ()
    finally:
        core.OFFICE_PATHS_ON.reset(token)


# --- доходность на затраты -----------------------------------------------------

def test_the_yield_on_cost_divides_by_every_creation_cost() -> None:
    result = _calc(offices_strategy=ns.STRATEGY_INCOME)
    obj = result["finance"]["nonres"]["objects"][0]
    kpi, totals = obj["kpi"], obj["totals"]
    common = obj["result"]["common_capex"]
    assert common > 0
    assert kpi["cost_total"] == pytest.approx(totals["capex"] + common)
    assert kpi["yield_on_cost"] == pytest.approx(kpi["stabilized_noi"] / kpi["cost_total"])
    # Старый делитель (стройка здания) давал почти вдвое больше.
    assert kpi["yield_on_cost"] < kpi["stabilized_noi"] / totals["capex"] * 0.7
    tile = next(t for t in result["report"]["layout"]["nonres_tiles"] if t["label"].startswith("Доходность на затраты"))
    assert tile["value"] == pytest.approx(kpi["yield_on_cost"])


# --- шкала класса ---------------------------------------------------------------

def test_the_office_assumptions_follow_the_class() -> None:
    """Класс проекта → класс офиса; цена класса офиса — только в нежилом."""
    for key, office_class in ns.OFFICE_CLASS_BY_PROJECT.items():
        preset = core.PROJECT_CLASS_PRESETS[key]
        # Шкала — у класса офиса, а не в профиле класса проекта.
        assert "offices_rent_th_per_sqm_month" not in preset
        price = ns.OFFICE_CLASS_SCALE[office_class]["price_th_per_sqm"]
        nonres = core.class_base_preset(key, kind=core.PROJECT_KIND_NONRESIDENTIAL)
        assert nonres["offices_price_th_per_sqm"] == price
        assert nonres["offices3_price_th_per_sqm"] == price
        # В жилом проекте офис — на правиле от цены жилья (владелец, 22.10.2026).
        assert core.class_base_preset(key)["offices_price_th_per_sqm"] == \
            core.nonresidential_price_th(preset["apartment_price_th"])


def test_the_owner_prices_by_office_class() -> None:
    prices = {c: ns.OFFICE_CLASS_SCALE[c]["price_th_per_sqm"] for c in ns.OFFICE_CLASSES}
    assert prices == {"B": 400.0, "B+": 550.0, "A": 750.0, "A+": 1000.0}
    rents = [ns.office_class_fields(c)["rent_th_per_sqm_month"] for c in ns.OFFICE_CLASSES]
    assert rents == sorted(rents) and len(set(rents)) == 4


def test_the_defaults_are_office_class_b() -> None:
    for field, value in ns.office_class_fields(ns.DEFAULT_OFFICE_CLASS).items():
        assert core.DEFAULT_INPUTS[f"offices_{field}"] == value
        assert core.DEFAULT_INPUTS[f"offices2_{field}"] == value


def test_the_rent_is_the_market_rate_per_year_indexed_to_commissioning() -> None:
    """Ставка — рыночная на конец 2025 года в год; до ввода она растёт на
    индексацию аренды, как цена продажи до ввода (владелец, 22.10.2026)."""
    assert ns.office_class_fields("B")["rent_th_per_sqm_month"] == round(28.348 / 12, 3)
    assert core.DEFAULT_INPUTS["offices_rent_date"] == "2025-12-01"
    commissioning = __import__("datetime").date(2030, 7, 1)
    assert ns.rent_months_before({"rent_date": "2025-12-01"}, commissioning) == 55
    assert ns.rent_months_before({"rent_date": ""}, commissioning) == 0
    dated = _calc(offices_strategy=ns.STRATEGY_INCOME, offices_rent_date="2025-12-01")
    undated = _calc(offices_strategy=ns.STRATEGY_INCOME, offices_rent_date="")
    rent = lambda r: r["finance"]["nonres"]["objects"][0]["totals"]["rent_revenue"]
    months = ns.rent_months_before({"rent_date": "2025-12-01"}, commissioning)
    assert rent(dated) / rent(undated) == pytest.approx(1.05 ** (months / 12), rel=1e-6)


# --- чувствительность ------------------------------------------------------------

def test_the_entry_price_moves_the_land_and_the_buyout_together() -> None:
    spec = core._SENSITIVITY_BY_KEY["purchase_price_mln"]
    x, t = _spec(offices_strategy=ns.STRATEGY_DIRECT)
    assert core._sensitivity_base_value(spec, x, {}) == 680
    scenario = dict(x)
    core._sensitivity_apply(spec, 748.0, scenario, {})
    assert scenario["purchase_price_mln"] + scenario["land_buyout_mln"] == pytest.approx(748.0)
    assert scenario["land_buyout_mln"] / scenario["purchase_price_mln"] == pytest.approx(675 / 5)
    out = core.run_sensitivity(x, t, [], {}, metric="npv_mln", parameters=["purchase_price_mln"])
    item = out["items"][0]
    # 10% цены входа — 68 млн; NPV двигается на десятки миллионов, а не на 0,5.
    assert item["impact"] > 100


def test_a_parameter_that_moves_nothing_is_not_called_the_strongest() -> None:
    rows = [{"label": "Стоимость покупки / цена входа", "kind": "pct", "impact": 0.0,
             "low_result": 1.062, "high_result": 1.062, "low_input": 612, "high_input": 748}]
    verdict = core._sensitivity_verdict("llcr", 1.062, rows, 10.0, 6.0)
    assert "Наибольшее влияние" not in verdict[0]
    assert verdict[0].startswith("Ни один параметр не изменил")


def test_the_report_tornado_of_an_office_is_npv_for_each_path() -> None:
    x, t = _spec(offices_strategy=ns.STRATEGY_DDU)
    out = core.report_sensitivity(x, t, [], {})
    assert out["base"]["metric"] == "npv_mln"
    paths = out["office_paths"]
    assert set(paths) == {ns.STRATEGY_DIRECT, ns.STRATEGY_INCOME}
    rent = {i["parameter"] for i in paths[ns.STRATEGY_INCOME]["items"]}
    sale = {i["parameter"] for i in paths[ns.STRATEGY_DIRECT]["items"]}
    assert {"offices_rent_th_per_sqm_month", "offices_occupancy_stable_pct",
            "offices_exit_cap_pct", "purchase_price_mln"} <= rent
    assert {"offices_price_th_per_sqm", "purchase_price_mln"} <= sale
    assert "offices_rent_th_per_sqm_month" not in sale


# --- паркинг ------------------------------------------------------------------

def test_the_project_parking_becomes_the_office_parking() -> None:
    result = _calc(offices_strategy=ns.STRATEGY_DIRECT, offices_parking_under_spaces=0,
                   underground_manual_spaces=68, underground_manual_gns_sqm=2380)
    s = result["summary"]
    assert not any("подземный паркинг" in item.lower() for item in s["project_kind_leftovers"])
    assert len(s["project_kind_moves"]) == 1 and "68 машино-мест" in s["project_kind_moves"][0]
    rows = core.project_kind_rows(s)
    assert any(r["label"] == "Паркинг" for r in rows)


def test_two_offices_do_not_guess_whose_parking_it_is() -> None:
    x, t = _spec(offices_parking_under_spaces=0, underground_manual_spaces=68,
                 offices2_enabled=True, offices2_gba_sqm=5000)
    _, _, moves = core.office_takes_project_parking(x, t)
    assert moves == []


def test_the_page_prices_the_office_by_its_class_only_without_housing() -> None:
    """На отрисованной странице: нежилой вид ставит цену класса офиса,
    возврат к смешанному — прежнее правило от цены жилья."""
    sys.path.insert(0, str(ROOT / "tests"))
    from browser import chromium_or_skip, serve  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    import main as wrapper  # noqa: PLC0415

    class_price = core.class_base_preset("business", kind=core.PROJECT_KIND_NONRESIDENTIAL)[
        "offices_price_th_per_sqm"]
    housing_price = core.PROJECT_CLASS_PRESETS["business"]["offices_price_th_per_sqm"]
    assert class_price != housing_price
    with serve(wrapper.app, 18961):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium_or_skip())
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto("http://127.0.0.1:18961/", wait_until="load")
            page.wait_for_function("()=>typeof applyProjectKind==='function'", timeout=60000)
            page.evaluate("()=>{inputs.project_class='business';inputs.offices_enabled=true;"
                          "inputs.offices_price_th_per_sqm=classValue('business','offices_price_th_per_sqm')}")
            before = page.evaluate("()=>inputs.offices_price_th_per_sqm")
            page.evaluate("()=>{try{applyProjectKind('nonresidential')}catch(e){}renderInputs()}")
            nonres = page.evaluate("()=>inputs.offices_price_th_per_sqm")
            page.evaluate("()=>{try{applyProjectKind('mixed')}catch(e){}renderInputs()}")
            back = page.evaluate("()=>inputs.offices_price_th_per_sqm")
            browser.close()
    assert errors == []
    assert (before, nonres, back) == (housing_price, class_price, housing_price)


def test_no_pf_no_reservation_fee() -> None:
    """Плата за резервирование лимита ПФ — только у продаж по ДДУ (владелец,
    24.10.2026: «Исправить: без ПФ платы нет»): у продажи блоками одобренный
    лимит ПФ не открывается."""
    direct = _calc(offices_strategy=ns.STRATEGY_DIRECT, pf_limit_approved_mln=5000)["finance"]
    ddu = _calc(offices_strategy=ns.STRATEGY_DDU, pf_limit_approved_mln=5000)["finance"]
    assert direct["pf_reservation_fee"] == 0 and direct["pf_limit"] == 0
    assert ddu["pf_limit"] == 5_000_000_000
    assert ddu["pf_reservation_fee"] == pytest.approx(5_000_000_000 * core.DEFAULT_INPUTS["reservation_fee_pct"] / 100)
