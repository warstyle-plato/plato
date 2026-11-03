"""Переключатель стратегии ТЦ и офисов — на отрисованной странице.

Мерится то, что видит человек: какие блоки формы объекта нарисованы при
каждой стратегии, появилась ли таблица «Нежильё — стратегия реализации» и
напечатаны ли в ней и в структуре выручки те же числа, что вернул движок на
тех же вводных (отдельный запрос /calculate — не копия из страницы).

Запуск: python3 -m pytest tests/test_nonres_strategy_on_the_page.py -q
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import browser  # noqa: E402
import main_legacy as core  # noqa: E402

PORT = 18983

CARDS = r"""() => [...document.querySelectorAll('details[data-object="offices"] .field-card')]
  .map(c => c.dataset.section)"""

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

STATE = r"""() => {
  const card = document.getElementById('nonresStrategyCard');
  const tables = [...card.querySelectorAll('table.nonres-strategy')].map(t => ({
    object: t.dataset.object, strategy: t.dataset.strategy,
    rows: [...t.querySelectorAll('tbody tr')].map(tr => [...tr.cells].map(c => c.innerText.trim()))}));
  const revenue = [...document.querySelectorAll('#revenueTable tr')]
    .map(tr => [...tr.cells].map(c => c.innerText.trim()));
  return {hidden: card.hidden, visible: card.offsetParent !== null || card.hidden === false,
          tables, revenue, inputs, tep, report: lastResult.report.nonres_strategy,
          officeRevenue: lastResult.revenue.offices, officeMoney: money(lastResult.revenue.offices),
          money: lastResult.report.nonres_strategy.map(o => o.rows.map(r => nonresCell(r)))};
}"""


def _post(base: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/calculate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture(scope="module")
def walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            page.evaluate(SET, ["offices_enabled", True])
            page.wait_for_function("() => lastResult && lastResult.revenue.offices > 0")
            out["ddu"] = {"cards": page.evaluate(CARDS), **page.evaluate(STATE)}
            for strategy in ("income", "direct"):
                page.evaluate(SET, ["offices_strategy", strategy])
                page.wait_for_function(
                    "s => (lastResult.report.nonres_strategy||[]).some(o => o.strategy === s)",
                    arg=strategy)
                state = page.evaluate(STATE)
                state["cards"] = page.evaluate(CARDS)
                state["engine"] = _post(base, {"inputs": state["inputs"], "tep": state["tep"],
                                               "rates": []})
                out[strategy] = state
            out["errors"] = errors
            page.close()
    return out


def test_ddu_draws_no_strategy_blocks_and_no_table(walk) -> None:
    cards = walk["ddu"]["cards"]
    assert "Стратегия реализации" in cards
    assert not {"Прямая продажа", "Доходный метод", "Финансирование объекта"} & set(cards)
    assert {"Цена и рост цены", "Темп продаж"} <= set(cards)
    assert walk["ddu"]["hidden"] is True and walk["ddu"]["tables"] == []
    assert walk["errors"] == []


def test_income_draws_its_blocks_and_hides_the_ddu_price(walk) -> None:
    cards = set(walk["income"]["cards"])
    assert {"Доходный метод", "Финансирование объекта"} <= cards
    assert not {"Прямая продажа", "Цена и рост цены", "Темп продаж"} & cards


def test_direct_draws_the_sale_window_and_the_loan(walk) -> None:
    cards = set(walk["direct"]["cards"])
    assert {"Прямая продажа", "Финансирование объекта", "Цена и рост цены"} <= cards
    assert "Доходный метод" not in cards


@pytest.mark.parametrize("strategy", ["income", "direct"])
def test_the_table_prints_what_the_engine_returned(walk, strategy) -> None:
    state = walk[strategy]
    assert state["hidden"] is False
    [table] = state["tables"]
    assert table["object"] == "offices" and table["strategy"] == strategy
    engine_rows = state["engine"]["report"]["nonres_strategy"][0]["rows"]
    assert [row[0] for row in table["rows"]] == [row["label"] for row in engine_rows]
    # Каждое число таблицы — число движка на тех же вводных, тем же форматом.
    assert [row[1] for row in table["rows"]] == state["money"][0]
    for printed, row in zip(state["report"][0]["rows"], engine_rows):
        if row["unit"] == "rub":
            assert printed["value"] == pytest.approx(row["value"], rel=1e-9)
    # Выручка офисов в структуре выручки — та же, что у стратегии.
    office = next(r for r in state["revenue"] if r and r[0].startswith("Офисы"))
    assert state["officeRevenue"] == pytest.approx(state["engine"]["revenue"]["offices"])
    assert office[1] == state["officeMoney"]


def test_switching_the_strategy_changes_the_totals(walk) -> None:
    assert walk["income"]["officeRevenue"] != walk["ddu"]["officeRevenue"]
    assert walk["direct"]["officeRevenue"] != walk["income"]["officeRevenue"]
    labels = [row[0] for row in walk["direct"]["tables"][0]["rows"]]
    assert "Выручка прямых продаж (ДКП, без эскроу)" in labels
    assert "NOI за срок удержания" not in labels
    income_labels = [row[0] for row in walk["income"]["tables"][0]["rows"]]
    assert "NOI за срок удержания" in income_labels


# --- нежилой проект: свой вид отчёта -----------------------------------------

LAYOUT = r"""() => {
  const hidden = sel => { const el = document.querySelector(sel); return !el || el.hidden || el.offsetParent === null; };
  return {
    layout: lastResult.report.layout,
    tiles: [...document.querySelectorAll('#reportKpi .kpi span')].map(s => s.innerText.trim()),
    values: [...document.querySelectorAll('#reportKpi .kpi')].map(k => [k.querySelector('span').innerText.trim(), k.querySelector('b').innerText.trim()]),
    expected: (lastResult.report.layout.nonres_tiles || []).map(t => [t.label, nonresCell(t)]),
    llcrCardHidden: document.getElementById('llcrTable').closest('[data-needs]').hidden,
    socialHidden: document.getElementById('socialTable').closest('[data-needs]').hidden,
    pfGridHidden: document.getElementById('pfTable').closest('[data-needs]').hidden,
    reportBankHidden: document.getElementById('reportFinanceTable').closest('[data-needs]').hidden,
    objectLoanCards: [...document.querySelectorAll('[data-nonres-finance-card]')]
      .map(c => ({hidden: c.hidden, tables: [...c.querySelectorAll('table.nonres-finance')].map(t => t.dataset.object)})),
  };
}"""


@pytest.fixture(scope="module")
def nonresidential_walk() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(core.app, PORT + 1) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            page.evaluate(SET, ["offices_enabled", True])
            page.wait_for_function("() => lastResult && lastResult.revenue.offices > 0")
            out["mixed_ddu"] = page.evaluate(LAYOUT)
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            page.evaluate(SET, ["offices_strategy", "income"])
            page.wait_for_function(
                "() => lastResult.report.layout && lastResult.report.layout.nonres_strategy"
                " && !lastResult.report.layout.housing")
            out["nonres_income"] = page.evaluate(LAYOUT)
            out["errors"] = errors
            page.close()
    return out


def test_a_mixed_project_keeps_the_bank_blocks(nonresidential_walk) -> None:
    state = nonresidential_walk["mixed_ddu"]
    assert state["layout"]["housing"] and state["layout"]["project_finance"]
    assert "LLCR (расчётный)" in state["tiles"]
    assert state["reportBankHidden"] is False
    assert all(card["hidden"] for card in state["objectLoanCards"])
    assert not state["llcrCardHidden"] and not state["socialHidden"]


def test_a_nonresidential_rent_project_reads_as_its_own_report(nonresidential_walk) -> None:
    state = nonresidential_walk["nonres_income"]
    assert state["layout"]["project_finance"] is False
    # Шапка — деньги объекта, а не БРИДЖ/ПФ/LLCR.
    assert not {"LLCR (расчётный)", "Пиковый БРИДЖ", "Собственные средства до ПФ"} & set(state["tiles"])
    assert "DSCR — минимум по годам" in state["tiles"]
    assert "Стабилизированный NOI, год" in state["tiles"]
    shown = {label: value for label, value in state["values"]}
    for label, value in state["expected"]:
        assert shown[label] == value
    assert state["llcrCardHidden"] and state["socialHidden"] and state["pfGridHidden"]
    # Раздел «Финансирование» отчёта: БРИДЖ/ПФ/LLCR скрыты, кредит объекта — на месте
    # (и в отчёте, и на вкладке «Финансирование»).
    assert state["reportBankHidden"] is True
    # Отчёт, вкладка «Финансирование» и раздел «Финансирование» объектной
    # вёрстки (`object_report`) — таблица движка во всех трёх ящиках.
    assert state["objectLoanCards"] == [{"hidden": False, "tables": ["offices"]}] * 3
    assert nonresidential_walk["errors"] == []
