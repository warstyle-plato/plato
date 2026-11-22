"""Office results share housing sections and native report components.

Keep the object-specific financial rows and their reconciliation, while checking
real DOM components for unit economics, expenses and financing. Hotel helpers
remain compatible with its separate nine-section report. Rendered-value and
order checks must reject forged labels, amounts, area bases and totals.

Run: python -m pytest tests/test_nonres_report_layout.py -q
"""

from __future__ import annotations

import copy
import html
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402
import page_blocks  # noqa: E402
from test_nonres_debt_metric import _nonres_inputs  # noqa: E402
from test_nonres_object_result import _spec  # noqa: E402

core = wrapper.core

HOTEL_TITLES = ["Решение", "Объект и участок", "Стратегия реализации", "Доходы", "Затраты",
          "Финансирование", "Экономика собственника", "Чувствительность", "Календарь"]
HOTEL_KEYS = ["decision", "object", "strategy", "income", "costs", "finance", "owner",
        "sensitivity", "calendar"]

TITLES = ["Участок и продукт", "Итог", "Очереди проекта", "Расходы", "Доходы",
          "Финансирование", "Чувствительность", "Календарный план"]
KEYS = ["site", "summary", "phases", "expenses", "income", "finance", "sensitivity", "calendar"]

_CACHE: dict[tuple, dict] = {}


def _two_objects(**over) -> tuple[dict, dict]:
    """Проект без жилья: офисы в аренду и ТЦ на продажу ДКП, участок куплен."""
    x, t = _spec(purchase_price_mln=1500, **over)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    return x, t


def _run(kind: str = "two", **over) -> dict:
    key = (kind, *sorted(over.items()))
    if key not in _CACHE:
        x, t = _two_objects(**over) if kind == "two" else _nonres_inputs(**over)
        _CACHE[key] = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    return _CACHE[key]


def _sections(result: dict) -> dict[str, dict]:
    return {s["key"]: s for s in result["report"]["object_report"]["sections"]}


def _walk_blocks(blocks: list[dict], *, rendered_only: bool = False):
    """Groups are the production schema; ui_ref/ui_children mount native DOM."""
    for block in blocks:
        if rendered_only and (block.get("ui_ref") or block.get("ui_children")):
            continue
        yield block
        yield from _walk_blocks(block.get("blocks") or [], rendered_only=rendered_only)


def _block(section: dict, title: str) -> dict:
    return next(b for b in _walk_blocks(section["blocks"]) if b.get("title") == title)


def _values(block: dict) -> dict[str, object]:
    return {r["label"]: r["value"] for r in block.get("rows") or []}


# --- решение движка -----------------------------------------------------------

def test_a_project_without_housing_uses_the_eight_housing_sections() -> None:
    layout = _run()["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_OBJECT
    assert [s["key"] for s in layout["sections"]] == KEYS
    assert [s["title"] for s in layout["sections"]] == TITLES
    assert all(s["brief"] for s in layout["sections"] if s["key"] != "phases")
    report = _run()["report"]["object_report"]
    assert [s["key"] for s in report["sections"]] == KEYS


@pytest.mark.parametrize("over", [
    {},  # жильё по умолчанию
    {"offices_enabled": True, "offices_gba_sqm": 40000.0, "offices_saleable_sqm": 24000.0,
     "offices_strategy": "income"},  # смешанный: жильё и офис вне ДДУ
])
def test_housing_and_mixed_projects_keep_their_report(over) -> None:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    t = copy.deepcopy(core.TEP_DEFAULT)
    x.update(over)
    if over:
        x, t = _spec(**over)
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    layout = result["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_HOUSING
    assert [s["key"] for s in layout["sections"]] == [
        "site", "summary", "phases", "expenses", "income", "finance", "sensitivity", "calendar"]
    assert result["report"]["object_report"] == {}


def test_a_nonresidential_project_with_ddu_keeps_the_object_frame() -> None:
    # Решение владельца (10.10.2026): проект без жилья — всегда рамка объекта.
    # Прежде объект по ДДУ (умолчание стратегии) уводил весь проект в жилую
    # рамку с квартирами, РВЭ и нулями. ПФ и эскроу — блок «Финансирования».
    result = _run(offices_strategy="ddu", retail_strategy="ddu")
    layout = result["report"]["layout"]
    assert layout["kind"] == core.REPORT_KIND_OBJECT and layout["object_frame"] is True
    assert layout["project_finance"] is True
    assert [s["key"] for s in layout["sections"]] == KEYS
    sections = _sections(result)
    strategy = _values(_block(_block(sections["income"], "Нежильё — стратегия реализации"), "Офисы"))
    assert strategy["Стратегия"] == core.nonres_strategy.STRATEGY_LABELS["ddu"]
    income = _values(_block(_block(sections["income"], "Доходы объектов — подробности"), "Офисы"))
    assert income["Выручка продаж по ДДУ (эскроу)"] == pytest.approx(result["revenue"]["offices"])
    pf = _values(_block(sections["finance"], "Проектное финансирование объектов по ДДУ"))
    assert pf["Проектное финансирование — пик"] == pytest.approx(result["report"]["financing"]["pf_peak"])
    assert pf["БРИДЖ — пик"] == pytest.approx(result["finance"]["peak_bridge"])
    assert pf["LLCR"] == pytest.approx(result["summary"]["llcr"])
    costs = [r["label"] for b in _walk_blocks(sections["expenses"]["blocks"]) for r in b.get("rows") or []]
    assert not any("не этим отчётом" in label for label in costs)
    assert "Смета объекта — Офисы" in [b.get("title") for b in _walk_blocks(sections["expenses"]["blocks"])]


def test_a_hotel_has_a_frame_of_its_own() -> None:
    x = copy.deepcopy(core.DEFAULT_INPUTS)
    x["project_kind"] = core.PROJECT_KIND_HOTEL
    assert core.report_kind(x) == core.REPORT_KIND_HOTEL
    assert core.report_kind({"project_kind": core.PROJECT_KIND_NONRESIDENTIAL}) == core.REPORT_KIND_OBJECT
    assert core.report_kind({}) == core.REPORT_KIND_HOUSING
    assert core.object_frame({"kind": core.REPORT_KIND_HOTEL})
    assert not core.object_frame({"kind": core.REPORT_KIND_HOUSING})


def test_without_a_deal_price_the_decision_reads_the_object() -> None:
    # Решение владельца (10.10.2026): без цены сделки вывод — по экономике
    # объекта, а оценка покупки названа несделанной.
    x, t = _two_objects()
    x["purchase_price_mln"] = 0
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert float(result["deal"].get("price_mln") or 0) == 0
    verdict = _sections(result)["summary"]["verdict"]
    assert verdict["title"] != "Вывод не сформирован"
    assert "Цена участка не задана — оценка покупки не делалась." in verdict["text"]


def test_an_income_object_without_a_loan_is_not_said_to_repay_by_sales() -> None:
    metric = core.debt_metric({}, False, [{"strategy": "income", "kpi": {},
                                           "totals": {"loan_peak": 0.0}}])
    assert metric["key"] is None
    assert "нет кредита" in metric["reason"] and "прямых продаж" not in metric["reason"]


# --- один источник ------------------------------------------------------------

def test_the_object_estimate_and_the_common_costs_add_up_to_the_capex() -> None:
    result = _run()
    costs = _sections(result)["expenses"]
    estimates = [b for b in _walk_blocks(costs["blocks"]) if str(b.get("title", "")).startswith("Смета объекта")]
    assert {b["title"] for b in estimates} == {"Смета объекта — Офисы", "Смета объекта — Коммерция ОСЗ"}
    total = sum(_values(b)["Итого смета объекта"] for b in estimates)
    common = _values(_block(costs, "Общие затраты проекта — участок, ИРД, проект, сети"))
    assert total + common["Итого общие затраты"] == pytest.approx(result["capex"]["total"], rel=1e-9)
    # Части сметы объекта — его статья плюс начисленное от неё.
    for block in estimates:
        rows = _values(block)
        parts = sum(v for k, v in rows.items() if k not in (
            "Итого смета объекта", "на м² наземной ГНС объекта", "на м² арендопригодной / продаваемой"))
        assert parts == pytest.approx(rows["Итого смета объекта"])
    # Генподряд и техзаказчик проекта без жилья — целиком доли объектов:
    # «общими» строками их нет. Резерв — доля объекта со своей стройки, а
    # резерв на статьи проекта (полная смета нежилого, 06.10.2026) — общей
    # строкой «Резерв — вне объектов»; вместе — резерв проекта.
    for key in ("gc_fee", "technical_supervision"):
        assert sum(p[key] for p in result["object_costs"].values()) == pytest.approx(result["capex"][key])
    assert not {"Вознаграждение генподрядчика — вне объектов",
                "Технический заказчик — вне объектов"} & set(common)
    reserve_objects = sum(p["reserve"] for p in result["object_costs"].values())
    assert reserve_objects + common["Резерв — вне объектов"] == pytest.approx(result["capex"]["reserve"])
    assert common["Участок — стоимость сделки"] == pytest.approx(1500e6)


def test_the_estimate_follows_the_cost_scenario() -> None:
    base, dear = _run(), _run(scenario_cost_multiplier=1.1)
    for key, parts in base["object_costs"].items():
        for name, value in parts.items():
            assert dear["object_costs"][key][name] == pytest.approx(value * 1.1)


def test_the_income_statement_reaches_the_net_profit_of_the_engine() -> None:
    result = _run()
    s = result["summary"]
    pnl = _values(_block(_sections(result)["summary"], "Экономика проекта"))
    assert pnl["Выручка"] - pnl["Затраты стройки (смета объектов и общие)"] \
        - pnl["Эксплуатация, налог на имущество, продажа и выход"] \
        - pnl.get("Коммерческие расходы", 0.0) == pytest.approx(pnl["EBITDA"], rel=1e-9)
    assert pnl["EBITDA"] - pnl["Проценты и комиссии"] == pytest.approx(pnl["Прибыль до налога"])
    assert pnl["Прибыль до налога"] - pnl["Налог на прибыль"] - pnl["НДС к уплате"] \
        == pytest.approx(pnl["Чистая прибыль"])
    assert pnl["Чистая прибыль"] == s["net_profit"] and pnl["EBITDA"] == s["ebitda"]


def test_the_decision_reads_the_engine() -> None:
    result = _run()
    decision = _sections(result)["summary"]
    rows = _values(_block(decision, "Ключевые параметры"))
    layout, equity = result["report"]["layout"], result["report"]["equity_participation"]
    metric = layout["debt_metric"]
    assert rows[metric["label"]] == metric["value"]
    irr = result["summary"]["irr_equity"]
    # Нет IRR — строка называет причину, а не молчит пустой клеткой.
    assert rows["IRR собственника"] == irr if irr is not None \
        else str(rows["IRR собственника"]).startswith("не считается")
    assert rows["NPV собственника @20%"] == equity["npv"]
    assert rows["Пик собственных средств"] == equity["peak"]
    assert rows["Чистая прибыль проекта"] == result["summary"]["net_profit"]
    verdict = core._purchase_feasibility(
        1500, result["summary"]["net_profit"] / 1e6, 0.0, 0.0, 0.0, None, 0.0, None,
        core._layout_dscr(layout), core._layout_no_debt_cover(layout))
    assert decision["verdict"] == verdict
    assert decision["goal_seek"]["metric"] == metric["key"]


def test_strategy_and_income_come_from_the_object_rows() -> None:
    result = _run()
    sections = _sections(result)
    objects = {o["title"]: o for o in result["finance"]["nonres"]["objects"]}
    offices = _values(_block(_block(sections["income"], "Нежильё — стратегия реализации"), "Офисы"))
    assert offices["Ставка аренды"] == core.DEFAULT_INPUTS["offices_rent_th_per_sqm_month"] and offices["Выход"] == "Продажа по ставке капитализации"
    retail = _values(_block(_block(sections["income"], "Нежильё — стратегия реализации"), "Коммерция ОСЗ"))
    assert retail["Стартовая цена ДКП"] == pytest.approx(450.0)
    years = _block(sections["income"], "По годам — Офисы")["years"]
    assert sum(y["noi"] for y in years) == pytest.approx(objects["Офисы"]["totals"]["noi"])
    assert sum(y["rent_revenue"] for y in years) == pytest.approx(objects["Офисы"]["totals"]["rent_revenue"])
    sold = _block(sections["income"], "График продаж — Коммерция ОСЗ")["years"]
    assert sold[-1]["sold_share"] == pytest.approx(1.0)


def test_the_calendar_has_no_escrow_milestones() -> None:
    events = _sections(_run())["calendar"]["calendar"]["events"]
    labels = [e["label"] for e in events]
    assert not {"Старт продаж", "РВЭ / РНВ", "Окончание продаж", "Продажи"} & set(labels)
    assert {"Заполнение — Офисы", "Аренда — Офисы", "Выход: продажа — Офисы",
            "Продажи ДКП — Коммерция ОСЗ", "Кредит объекта — Офисы"} <= set(labels)


def test_sensitivity_moves_the_factors_of_the_objects() -> None:
    sensitivity = _sections(_run())["sensitivity"]["sensitivity"]
    assert sensitivity["metric"] == "dscr"
    keys = set(sensitivity["parameters"])
    assert {"offices_rent_th_per_sqm_month", "offices_occupancy_stable_pct", "offices_exit_cap_pct",
            "retail_price_th_per_sqm", "offices_loan_spread_pp", "purchase_price_mln"} <= keys
    # Цены квартир у проекта без жилья нет, и аренды у проданного ТЦ — тоже.
    assert not {"apartment_price_th", "retail_rent_th_per_sqm_month", "offices_price_th_per_sqm"} & keys
    x, t = _two_objects()
    report = core.run_sensitivity(x, t, [], {}, metric="dscr", change_pct=10,
                                  parameters=["offices_rent_th_per_sqm_month"])
    item = report["items"][0]
    assert item["label"] == "Ставка аренды — офисы"
    assert item["high_result"] > report["base"]["value"] > item["low_result"]


# --- страница: page_blocks ----------------------------------------------------

def _render_blocks(report: dict) -> dict:
    prelude = "const inputs={site_area_ha:1.5,cadastral_numbers:'77:01:0001001:1'};\nconst R=%s;\n" % (
        json.dumps({"report": report}, ensure_ascii=False))
    tail = r"""
const rep=objectReportOf(R);
const out=rep.sections.filter(s=>!OBJECT_SHARED_SECTIONS[s.key]).map(s=>({key:s.key,
 html:s.blocks.map(b=>objectBlockHtml(b,s)).join('')}));
console.log(JSON.stringify(out));
"""
    out, _ = page_blocks.run(prelude, tail)
    return {item["key"]: item["html"] for item in json.loads(out)}


def _cells(markup: str) -> list[tuple[str, str]]:
    """Строки таблиц движка (`object-rows`); участок из вводных — своя таблица."""
    tables = "".join(re.findall(r'<table class="[^"]*\bobject-rows\b[^"]*">[\s\S]*?</table>', markup))
    # Подписи с «&» (F&B, FF&E) страница экранирует — сравниваем текст.
    return [(html.unescape(re.sub("<[^>]+>", "", a)), html.unescape(re.sub("<[^>]+>", "", b)))
            for a, b in
            re.findall(r"<tr(?: class=\"section\")?><td>([\s\S]*?)</td><td>([\s\S]*?)</td></tr>",
                       tables)]


_SCALE = {"": 1.0, "млрд ₽": 1e9, "млн ₽": 1e6, "тыс ₽/м²": 1.0, "м²": 1.0, "x": 1.0, "%": 0.01}


def _number(text: str) -> tuple[float, float]:
    """Напечатанное число и полшага его последнего знака — в единицах движка."""
    clean = text.replace(" ", " ").replace(" ", " ").strip()
    unit = next((u for u in _SCALE if u and clean.endswith(u)), "")
    digits = clean[:len(clean) - len(unit)].strip().replace(" ", "").replace(",", ".").replace("−", "-")
    step = 10 ** -len(digits.split(".")[1]) if "." in digits else 1.0
    return float(digits) * _SCALE[unit], step / 2 * _SCALE[unit] + 1e-9


def _drawn_mismatches(drawn: dict[str, str], report: dict) -> list[str]:
    """Что напечатала страница против строк движка: подписи по порядку и числа
    — разбором напечатанного, а не формулой страницы."""
    out = []
    for section in report["object_report"]["sections"]:
        if section["key"] not in drawn:
            continue
        cells = _cells(drawn[section["key"]])
        rows = [r for b in _walk_blocks(section["blocks"], rendered_only=True) if not b.get("ref") and b.get("kind") != "verdict"
                for r in b.get("rows") or []]
        if [c[0] for c in cells] != [r["label"] for r in rows]:
            out.append(f"{section['key']}: строки не те")
            continue
        for (label, cell), row in zip(cells, rows):
            if row["unit"] in ("rub", "sqm", "th", "mult", "pct") and row["value"] is not None:
                value, tolerance = _number(cell)
                if abs(value - float(row["value"])) > tolerance:
                    out.append(f"{section['key']}: {label} — {cell} вместо {row['value']}")
            elif row["unit"] == "text" and cell != str(row["value"]):
                out.append(f"{section['key']}: {label} — {cell}")
    return out


def test_the_page_prints_the_sections_and_native_component_slots() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    assert list(drawn) == [k for k in KEYS if k not in ("phases", "sensitivity", "calendar")]
    assert _drawn_mismatches(drawn, report) == []
    verdict = _sections(_run())["summary"]["verdict"]
    assert verdict["title"] in drawn["summary"]
    assert 'data-report-component="unitEconomicsTable"' in drawn["summary"]
    assert 'data-report-component="expenseStructureChart"' in drawn["expenses"]
    assert 'data-report-children="rsFinance"' in drawn["finance"]
    assert "Площадь участка" in drawn["site"] and "77:01:0001001:1" in drawn["site"]


def test_the_page_check_fails_on_a_forgery() -> None:
    report = _run()["report"]
    drawn = _render_blocks(report)
    forged = dict(drawn)
    forged["expenses"] = drawn["expenses"].replace("Резерв — доля объекта", "Резерв", 1)
    forged["summary"] = re.sub(r"(<td>EBITDA</td><td>)[^<]+", r"\g<1>0,00 млрд ₽", drawn["summary"])
    assert len(_drawn_mismatches(forged, report)) == 2


# --- структура расходов ------------------------------------------------------
# Владелец (25.10.2026): «почему в результате нет суммы расходов, как по
# жилью?» — и решение: «Структура расходов» первым блоком раздела «Затраты».

def _expense_rows(result: dict) -> list[dict]:
    first = _sections(result)["expenses"]["blocks"][0]
    assert first["title"] == "Структура расходов"
    return first["years"]


def _expense_mismatches(drawn: list[list[str]], rows: list[dict]) -> list[str]:
    """Напечатанные строки таблицы против строк движка — разбором текста."""
    if [d[0] for d in drawn] != [r["label"] for r in rows]:
        return ["строки не те"]
    out = []
    for cells, row in zip(drawn, rows):
        label, money, share = cells[:3]
        for cell, value in ((money, row["value"]), (share, row["share"])):
            number, tolerance = _number(cell)
            if abs(number - float(value)) > tolerance:
                out.append(f"{label}: {cell} вместо {value}")
    return out


def _drawn_expense(markup: str) -> list[list[str]]:
    table = re.search(r'<table class="object-years">[\s\S]*?</table>', markup).group(0)
    body = table.split("<tbody>", 1)[1]
    return [[html.unescape(re.sub("<[^>]+>", "", c)) for c in re.findall(r"<td>([\s\S]*?)</td>", tr)]
            for tr in re.findall(r"<tr>([\s\S]*?)</tr>", body)]


@pytest.mark.parametrize("kind", ["two", "one"])
def test_the_costs_open_with_the_expense_structure_of_the_engine(kind: str) -> None:
    """Строки — те же, что `report.expense_structure` жилого отчёта, не своя
    сборка; итог — `summary.total_expenses`, и сумма статей с ним сходится."""
    result = _run(kind)
    rows = _expense_rows(result)
    engine = result["report"]["expense_structure"]
    assert [(r["label"], r["value"], r["share"]) for r in rows[:-1]] == [
        (e["label"], e["value"], e["share"]) for e in engine]
    total = rows[-1]
    assert total["label"] == "Расходы всего"
    assert total["value"] == result["summary"]["total_expenses"]
    assert sum(r["value"] for r in rows[:-1]) == pytest.approx(total["value"], abs=1.0)
    assert sum(r["share"] for r in rows[:-1]) == pytest.approx(1.0)


def test_the_costs_of_the_objects_on_their_own_loan_are_in_the_structure() -> None:
    """Эксплуатация, налог на имущество, продажа и выход объектов, проценты и
    комиссии их кредита и сделка — статьями таблицы, а не теряются."""
    result = _run()
    values = {r["label"]: r["value"] for r in _expense_rows(result)}
    objects = result["finance"]["nonres"]["objects"]
    assert objects, "у проекта нет объектов на своём кредите — проверять нечего"

    def total(key: str) -> float:
        return sum(float(o["totals"].get(key) or 0.0) for o in objects)

    own = total("opex") + total("property_tax") + total("selling_cost") + total("exit_cost")
    assert own > 0 and values[result["report"]["nonres_costs_label"]] == pytest.approx(own, abs=1.0)
    # Комиссии за резервирование и неиспользованный лимит — внутри `loan_fee`.
    loan = total("loan_interest") + total("loan_fee")
    assert loan > 0 and values["Проценты и комиссии"] == pytest.approx(loan, abs=1.0)
    assert values["Цена приобретения"] == pytest.approx(1500e6)
    summary = result["summary"]
    assert values["Налог на прибыль"] == summary["profit_tax"]
    assert values["НДС"] == summary["vat"]


def test_a_housing_project_has_the_same_structure_of_expenses() -> None:
    """Тот же блок у жилья: строки движка складываются в «Расходы всего»."""
    result = core.calculate(core.CalcRequest(inputs=copy.deepcopy(core.DEFAULT_INPUTS),
                                             tep=copy.deepcopy(core.TEP_DEFAULT), rates=[]))
    assert "object_report" not in result["report"] or not result["report"]["object_report"]
    rows = result["report"]["expense_structure"]
    assert sum(r["value"] for r in rows) == pytest.approx(result["summary"]["total_expenses"], abs=1.0)


def test_the_bottom_total_no_longer_repeats_the_expenses() -> None:
    """«Расходы всего» стоит итогом структуры; внизу остаётся одна стройка."""
    result = _run()
    costs = _sections(result)["expenses"]
    titles = [b.get("title") for b in _walk_blocks(costs["blocks"])]
    assert titles[0] == "Структура расходов" and titles[-1] == "Итог стройки"
    assert "Итог" not in titles
    labels = [r["label"] for b in _walk_blocks(costs["blocks"]) for r in b.get("rows") or []]
    assert not any(label.startswith("Расходы проекта всего") for label in labels)
    assert _values(_block(costs, "Итог стройки")) == {
        "Затраты стройки — смета объектов и общие": result["summary"]["capex"]}


def _unit_mismatches(drawn: list[list[str]], items: list[dict]) -> list[str]:
    """The native five-column table: every row names its actual area base."""
    if [d[0] for d in drawn] != [i["label"] for i in items]:
        return ["строки не те"]
    out = []
    for (label, total, per_base, base, second), item in zip(drawn, items):
        expected_base = "м² " + core.TERMS[item["base"]].genitive
        if base != expected_base:
            out.append(f"{label}: база {base} вместо {expected_base}")
        expected_second = item["per_saleable_th"] if item["base"] != core.UNIT_BASE_SALEABLE else None
        for cell, value in ((total, item["total"]), (per_base, item["per_base_th"]), (second, expected_second)):
            if value is None:
                if cell != "—":
                    out.append(f"{label}: {cell} вместо прочерка")
                continue
            number, tolerance = _number(cell)
            if abs(number - float(value)) > tolerance:
                out.append(f"{label}: {cell} вместо {value}")
    return out


def test_summary_opens_with_economy_parameters_and_native_unit_table() -> None:
    result = _run()
    blocks = _sections(result)["summary"]["blocks"]
    assert [b["title"] for b in blocks[:3]] == ["Экономика проекта", "Ключевые параметры", "Удельная экономика"]
    unit = blocks[2]
    assert unit["ui_ref"] == "unitEconomicsTable"
    assert unit["items"] == result["report"]["unit_economics"]
    assert [c[1] for c in unit["columns"]] == [
        "Показатель", "Всего", "тыс. ₽/м² своей базы", "База", "тыс. ₽/м² прод."]
    items = result["report"]["unit_economics"]
    rows = {r["label"]: r for r in unit["years"]}
    assert rows["Выручка"]["base_label"] == "м² продаваемой площади"
    assert rows["Выручка"]["second_base"] is None
    capex = next(i for i in items if i["key"] == "capex")
    assert rows["CAPEX"]["per_base_th"] == capex["per_base_th"]
    assert rows["CAPEX"]["second_base"] == capex["per_saleable_th"]
    assert [(b["title"], b.get("details")) for b in blocks[3:5]] == [
        ("Инвестиционное решение", True), ("Допущения и ограничения", True)]
    income = _sections(result)["income"]["blocks"]
    assert next(b for b in income if b["title"] == "Нежильё — стратегия реализации")["kind"] == "group"
    assert next(b for b in income if b["title"] == "Темпы и цены продаж")["kind"] == "group"


def test_housing_leftovers_remain_diagnostics_and_are_not_display_rows() -> None:
    result = _run()
    assert result["summary"]["project_kind_leftovers"]
    rows = core.project_kind_rows(result["summary"])
    assert not any("Осталось от жилья" in r["label"] for r in rows)


# --- страница: браузер --------------------------------------------------------

PORT = 18991

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

READ = r"""() => {
  openTab('report', null);
  const seen = el => el && el.offsetParent !== null;
  const cells = tr => [...tr.cells].map(c => c.textContent.trim());
  const table = id => {const b=document.getElementById(id),t=b?.closest('table');return {
    head:[...t.querySelectorAll('thead th')].map(c=>c.textContent.trim()),
    rows:[...b.querySelectorAll(':scope > tr')].filter(tr=>!tr.classList.contains('sub')).map(cells)}};
  const sections = [...document.querySelectorAll('#report .report-section')].filter(seen)
    .map(s => ({id: s.id, title: s.querySelector('.report-section-title').textContent.trim(),
                rows: [...s.querySelectorAll('table.object-rows tr')].map(cells)}));
  const unit=document.getElementById('unitEconomicsTable'),expense=document.getElementById('expenseStructureChart');
  const homes=window.__nativeReportTest;
  const chart = svg => svg && ({viewBox:svg.getAttribute('viewBox'),unit:svg.getAttribute('aria-label'),
    width:svg.getBoundingClientRect().width,height:svg.getBoundingClientRect().height,
    fontPx:[...svg.querySelectorAll('text')].map(t=>Number(t.getAttribute('font-size'))*svg.getBoundingClientRect().width/svg.viewBox.baseVal.width),
    fills:[...new Set([...svg.querySelectorAll('rect,circle')].map(n=>n.getAttribute('fill')))],
    grid:[...new Set([...svg.querySelectorAll('line')].map(n=>n.getAttribute('stroke')))]});
  return {sections, toc: [...document.querySelectorAll('#reportToc a')].map(a => a.textContent.trim()),
          financeTables: [...document.querySelectorAll('#rsObj-finance table.nonres-finance')]
            .filter(seen).map(t => t.dataset.object),
          equity: seen(document.querySelector('#rsObj-finance .equity-box table')),
          housingShown: ['rsSite', 'rsSummary', 'rsExpenses', 'rsIncome', 'rsFinance']
            .filter(id => seen(document.getElementById(id))),
          summaryCards: [...document.querySelectorAll('#rsObj-summary > .card, #rsObj-summary > .report-2col > .card')]
            .map(c=>(c.querySelector('.section-title')||c.querySelector('summary'))?.textContent.trim()),
          summaryDetails: [...document.querySelectorAll('#rsObj-summary > details')].map(d=>({title:d.querySelector('summary').textContent.trim(),open:d.open})),
          costsCards: [...document.querySelectorAll('#rsObj-expenses .section-title')].filter(seen).map(t=>t.textContent.trim()),
          unit:table('unitEconomicsTable'), expense:table('expenseStructureTable'),
          expenseTotal:document.getElementById('expenseTotal').textContent.trim(),
          expenseChart:[...expense.querySelectorAll('.expense-row')].map(r=>({label:r.querySelector('.expense-label').textContent.trim(),width:parseFloat(r.querySelector('.expense-fill').style.width)})),
          native:{unitIdentity:!homes||homes.unit===unit.closest('.card'),
                  expenseIdentity:!homes||homes.expense===expense.closest('.card'),
                  unitSection:unit.closest('.report-section').id,expenseSection:expense.closest('.report-section').id,
                  financeIdentities:!homes||homes.finance.every(n=>n.closest('.report-section')?.id===(document.getElementById('objectReport').hidden?'rsFinance':'rsObj-finance')),
                  uniqueIds:['unitEconomicsTable','expenseStructureChart','reportTaxTable','reportFinanceTable'].every(id=>document.querySelectorAll('#'+id).length===1)},
          gantt: [...document.querySelectorAll('#reportCalendarGantt .gantt-label.group')].map(x=>x.textContent.trim()),
          charts:{apartment:chart(document.querySelector('#apartmentPaceChart svg')),
                  office:[...document.querySelectorAll('#rsObj-income .sales-period-chart svg')].map(chart)},
          inputs, tep};
}"""


def _post(base: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/calculate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def _read(page) -> dict:
    page.evaluate("() => openTab('report',null)")
    # ResizeObserver draws the shared chart after its report tab becomes visible.
    page.wait_for_function("""() => [...document.querySelectorAll('#report [data-report-chart],#apartmentPaceChart')]
      .filter(n=>n.offsetParent!==null).every(n=>{
        const svg=n.querySelector('svg');
        return svg?Math.abs(svg.viewBox.baseVal.width-Math.max(280,n.clientWidth))<1
                  :n.textContent.includes('Нет данных для графика');
      })""")
    return page.evaluate(READ)


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    import browser

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # После каждого шага — конец расчёта (`wait_for_result`), а не
            # признак в итоге. Признак «вёрстка объекта» истинен уже у итога
            # шага перед сменой стратегии (ДДУ — тоже рамка объекта): успей
            # тот ответ до правки поля, ожидание кончалось сразу, и страница
            # читалась по ДДУ, а движок сверялся по аренде.
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate("""() => { window.__nativeReportTest={
              unit:document.getElementById('unitEconomicsTable').closest('.card'),
              expense:document.getElementById('expenseStructureChart').closest('.card'),
              finance:[...document.getElementById('rsFinance').children].filter(n=>!n.classList.contains('report-section-title'))}; }""")
            out["housing"] = _read(page)
            page.evaluate(SET, ["offices_enabled", True])
            browser.wait_for_result(page)
            assert page.evaluate("() => lastResult.revenue.offices > 0")
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_strategy", "income"])
            browser.wait_for_result(page)
            # Аренда — без проектного финансирования: итог ДДУ здесь не пройдёт.
            assert page.evaluate("() => lastResult.report.layout.kind === 'object'"
                                 " && lastResult.report.layout.project_finance === false")
            state = _read(page)
            state["engine"] = _post(base, {"inputs": state["inputs"], "tep": state["tep"], "rates": []})
            out["object"] = state
            out["rendererProbe"] = page.evaluate(r"""() => {
              const rows=[{month:'2027-01',q:1,left:5},{month:'2027-02',q:null,left:null},
                          {month:'2027-03',q:0,left:2},{month:'2027-04',q:4,left:0}];
              const parse=unit=>new DOMParser().parseFromString(salesPeriodSvg(rows,[['q','Объём'],['left','Остаток']],unit),'image/svg+xml');
              const doc=parse('м²'),pieces=parse('шт.');
              return {unit:doc.documentElement.getAttribute('aria-label'),piecesUnit:pieces.documentElement.getAttribute('aria-label'),
                titles:[...doc.querySelectorAll('circle[fill="#202020"] title')].map(n=>n.textContent),
                segments:doc.querySelectorAll('polyline[stroke="#202020"]').length,
                circles:doc.querySelectorAll('circle[fill="#202020"]').length};
            }""")
            page.evaluate("() => renderResult()")
            out["rerender"] = _read(page)
            page.set_viewport_size({"width":390,"height":844})
            out["narrow"] = _read(page)
            page.set_viewport_size({"width":1440,"height":900})
            page.evaluate("() => { applyProjectKind('mixed'); closeProjectKindDialog(); }")
            browser.wait_for_result(page)
            out["restored"] = _read(page)
            out["errors"] = errors
            page.close()
    return out


def test_the_rendered_page_uses_the_common_sections_and_card_order(walk) -> None:
    state = walk["object"]
    titles = [s["title"] for s in state["sections"]]
    assert titles == TITLES
    assert state["toc"] == [title for key,title in zip(KEYS,TITLES) if key != "phases"]
    assert state["housingShown"] == []
    assert state["summaryCards"][:3] == ["Экономика проекта", "Ключевые параметры", "Удельная экономика"]
    assert state["summaryDetails"][:2] == [
        {"title":"Инвестиционное решение","open":False}, {"title":"Допущения и ограничения","open":False}]
    assert state["financeTables"] == ["offices"] and state["equity"] is True
    assert "Аренда" in state["gantt"] and "Выход" in state["gantt"]
    assert walk["errors"] == []


def test_the_rendered_numbers_are_the_engine_numbers(walk) -> None:
    state, engine = walk["object"], walk["object"]["engine"]
    drawn = {s["id"].removeprefix("rsObj-"): '<table class="metric-table object-rows">' + "".join(
        f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in (r for r in s["rows"] if len(r) == 2))
        + "</table>" for s in state["sections"] if s["id"].startswith("rsObj-")}
    assert _drawn_mismatches(drawn, engine["report"]) == []
    estimate = next(r for r in state["sections"] if r["id"] == "rsObj-expenses")["rows"]
    assert ["Вознаграждение генподрядчика — доля объекта"] == [
        r[0] for r in estimate if r[0].startswith("Вознаграждение генподрядчика")]


def test_the_object_frame_reuses_the_native_five_column_unit_table(walk) -> None:
    state, engine = walk["object"], walk["object"]["engine"]
    assert state["unit"]["head"] == walk["housing"]["unit"]["head"] == [
        "Показатель", "Всего", "тыс. ₽/м² своей базы", "База", "тыс. ₽/м² прод."]
    assert _unit_mismatches(state["unit"]["rows"], engine["report"]["unit_economics"]) == []
    native = state["native"]
    assert native["unitIdentity"] and native["unitSection"] == "rsObj-summary"


def test_the_native_unit_check_rejects_zero_substitution_and_wrong_base(walk) -> None:
    drawn, items = walk["object"]["unit"]["rows"], walk["object"]["engine"]["report"]["unit_economics"]
    zero = [[*r[:4], "0,0"] if r[0] == "Выручка" else r for r in drawn]
    assert _unit_mismatches(zero, items)
    wrong_base = [[*r[:3], "м² продаваемой площади", r[4]] if r[0] == "CAPEX" else r for r in drawn]
    assert _unit_mismatches(wrong_base, items)


def test_the_rendered_expenses_use_the_original_housing_chart_and_table(walk) -> None:
    state, engine = walk["object"], walk["object"]["engine"]
    assert state["costsCards"][0] == "Структура расходов"
    assert state["costsCards"][-1] == "Итог стройки"
    assert state["expense"]["head"] == walk["housing"]["expense"]["head"]
    rows = engine["report"]["expense_structure"]
    assert _expense_mismatches(state["expense"]["rows"], rows) == []
    assert [r["label"] for r in state["expenseChart"]] == [r["label"] for r in rows]
    assert [r["width"] for r in state["expenseChart"]] == pytest.approx([max(0,min(100,r["share"]*100)) for r in rows],abs=5e-5)
    value, tolerance = _number(state["expenseTotal"])
    assert abs(value-engine["summary"]["total_expenses"]) <= tolerance
    assert state["native"]["expenseIdentity"] and state["native"]["expenseSection"] == "rsObj-expenses"


def test_the_native_expense_check_rejects_changed_amounts_missing_rows_and_shares(walk) -> None:
    drawn = walk["object"]["expense"]["rows"]
    rows = walk["object"]["engine"]["report"]["expense_structure"]
    wrong_amount = [[r[0], "1,00 млрд ₽", *r[2:]] if i == 0 else r for i,r in enumerate(drawn)]
    assert _expense_mismatches(wrong_amount, rows)
    assert _expense_mismatches(drawn[:-1], rows)
    assert _expense_mismatches(drawn, [{**rows[0],"share":.5},*rows[1:]])


def test_housing_and_office_sales_graphs_use_the_same_real_renderer(walk) -> None:
    apartment=walk["housing"]["charts"]["apartment"]
    office=walk["object"]["charts"]["office"]
    assert apartment is not None and office
    assert apartment["unit"] == "квартир/мес."
    for chart in [apartment,*office]:
        box=[float(v) for v in chart["viewBox"].split()]
        assert box[:2] == [0,0] and box[3] == 210
        assert box[2] == pytest.approx(chart["width"],abs=1)
        assert chart["height"] == pytest.approx(210,abs=1)
        assert all(v == pytest.approx(11,abs=.1) for v in chart["fontPx"])
        assert chart["grid"] == ["#e5e5e5"]
        assert chart["fills"] and set(chart["fills"]) <= {"#202020", "#888"}
        assert "#202020" in chart["fills"] and chart["unit"]
    assert "%" in {c["unit"] for c in office} and "млн ₽" in {c["unit"] for c in office}
    narrow=walk["narrow"]["charts"]["office"]
    assert narrow and len(narrow)==len(office)
    for chart in narrow:
        assert chart["height"] == pytest.approx(210,abs=1)
        assert all(v == pytest.approx(11,abs=.1) for v in chart["fontPx"])
    probe=walk["rendererProbe"]
    assert probe["unit"] == "м²" and probe["piecesUnit"] == "шт."
    assert probe["circles"] == 3 and probe["segments"] == 2
    assert not any("2027-02" in title for title in probe["titles"])
    assert any("2027-03: Объём 0 м²" == title for title in probe["titles"])


def test_native_nodes_survive_rerender_and_return_to_housing(walk) -> None:
    for key in ("object", "rerender", "restored"):
        native=walk[key]["native"]
        assert native["unitIdentity"] and native["expenseIdentity"] and native["financeIdentities"] and native["uniqueIds"], key
    assert walk["restored"]["native"]["unitSection"] == "rsSummary"
    assert walk["restored"]["native"]["expenseSection"] == "rsExpenses"


def test_a_housing_project_keeps_its_page(walk) -> None:
    for state in (walk["housing"], walk["restored"]):
        assert [s["id"] for s in state["sections"]][:2] == ["rsSite", "rsSummary"]
        assert not any(s["id"].startswith("rsObj-") for s in state["sections"])
        assert "Решение" not in state["toc"]


# --- PDF ----------------------------------------------------------------------

def _pdf_text(result: dict, inputs: dict, tep: dict) -> str:
    pypdf = pytest.importorskip("pypdf")
    data = core._build_developaid_pdf({"result": result, "inputs": inputs, "tep": tep, "rates": [],
                                       "phasing": {}, "scenario": "base", "project_name": "Офисы"})
    return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)


def _in_order(text: str, titles: list[str]) -> list[str]:
    """Заголовки, которых нет на своём месте: каждый ищется строкой после
    предыдущего."""
    missing, at = [], 0
    lines = text.splitlines()
    for title in titles:
        index = next((i for i in range(at, len(lines)) if lines[i].strip() == title), None)
        if index is None:
            missing.append(title)
        else:
            at = index + 1
    return missing


@pytest.fixture(scope="module")
def object_pdf() -> str:
    x, t = _two_objects()
    return _pdf_text(_run(), x, t)


def test_the_pdf_follows_common_sections_and_places_unit_economics_early(object_pdf) -> None:
    applicable=[title for key,title in zip(KEYS,TITLES) if key != "phases"]
    assert _in_order(object_pdf, applicable) == []
    assert _in_order(object_pdf, ["Итог", "Экономика проекта", "Ключевые параметры", "Удельная экономика", "Расходы"]) == []
    assert "Вознаграждение генподрядчика — доля объекта" in object_pdf
    assert "Осталось от жилья во вводных" not in object_pdf
    assert "Класс жилья" not in object_pdf


def test_the_pdf_opens_expenses_with_the_common_expense_structure(object_pdf) -> None:
    text=object_pdf[object_pdf.index("\nРасходы\n"):]
    assert text.index("Структура расходов") < text.index("Смета объекта")
    unit=object_pdf[object_pdf.index("\nУдельная экономика\n"):object_pdf.index("\nРасходы\n")]
    for phrase in ("Показатель", "Всего", "На м² своей базы", "База", "тыс ₽/м² продаваемой"):
        assert phrase in " ".join(unit.split())
    total=re.search(r"Итого расходы\s+([\d\s,.-]+(?:млрд|млн)\s*₽)",text).group(1)
    value,tolerance=_number(" ".join(total.split()))
    assert abs(value-_run()["summary"]["total_expenses"])<=tolerance


def test_the_pdf_order_check_fails_on_a_forgery(object_pdf) -> None:
    applicable=[title for key,title in zip(KEYS,TITLES) if key != "phases"]
    swapped=object_pdf.replace("\nДоходы\n", "\n§\n",1).replace("\nРасходы\n", "\nДоходы\n",1)
    assert _in_order(swapped, applicable)


# --- тизер и бот --------------------------------------------------------------

def test_the_teaser_prints_the_same_sections(tmp_path) -> None:
    pypdf = pytest.importorskip("pypdf")
    x, t = _two_objects()
    bundle = core._run_authoritative_model(x, t, [], {})
    path = tmp_path / "teaser.pdf"
    path.write_bytes(core.build_teaser_pdf(bundle, x, t, {}))
    pages = pypdf.PdfReader(str(path)).pages
    assert len(pages) == 2
    text = "\n".join(p.extract_text() or "" for p in pages)
    first=pages[0].extract_text() or ""
    assert _in_order(first,["Участок и продукт", "Экономика проекта", "Удельная экономика"]) == []
    assert _in_order(text,TITLES[2:]) == []
    assert "тыс ₽/м² общей площади" in " ".join(first.split())
    assert "тыс ₽/м² продаваемой площади" in " ".join(first.split())
    result=bundle["consolidated"]
    unit_text=first.split("Удельная экономика",1)[1]
    printed=re.search(r"Выручка\s+([\d\s,.-]+)\s+—\s+([\d\s,.-]+)",unit_text)
    assert printed, "нативная таблица должна оставлять прочерк у выручки на общей базе"
    value,tolerance=_number(printed.group(1).strip())
    assert abs(value*1e6-result["summary"]["revenue"])<=tolerance*1e6
    price,tolerance=_number(printed.group(2).strip())
    revenue=next(i for i in result["report"]["unit_economics"] if i["key"]=="revenue")
    assert abs(price-revenue["per_saleable_th"])<=tolerance
    assert "LLCR" not in text and "Удельная экономика" in first


def test_the_bot_card_lists_the_sections_in_order(monkeypatch) -> None:
    x, t = _two_objects()
    layout = core._run_authoritative_model(x, t, [], {})["consolidated"]["report"]["layout"]
    sent: list[str] = []
    monkeypatch.setattr(core, "_telegram_verify_session", lambda s: {"chat_id": 42, "cad": []})
    monkeypatch.setattr(core, "_telegram_user_allowed", lambda c: True)
    monkeypatch.setattr(core, "_telegram_send_message", lambda chat_id, text, **kw: sent.append(text))
    monkeypatch.setattr(core, "_telegram_web_app_url", lambda *a, **k: "https://example.org/")
    core.telegram_result(core.TelegramResultRequest(session="s", summary={
        "purchase_price_mln": 1500, "net_profit_mln": 900, "llcr": 0.0, "layout": layout}))
    text = sent[0]
    heads = re.findall(r"<b>\d+\. ([^<]+)</b>", text)
    assert heads == TITLES
    decision = next(s for s in layout["sections"] if s["key"] == "summary")
    assert f"• <b>{decision['brief'][0]['value']}</b>" in text
    assert "LLCR" not in text and "квартиры" not in text and "Оценка целесообразности" not in text
