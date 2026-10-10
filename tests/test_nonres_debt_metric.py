"""Чем мерить долг нежилого проекта: DSCR кредита объектов, а не LLCR.

Владелец (05.10.2026, снимки экрана): у нежилого проекта карточка
«Инвестиционное решение» судила по LLCR −8,68x и подбирала цену входа по
LLCR, первая страница PDF печатала LLCR, календарь — полосу БРИДЖа. LLCR там
считать не из чего: ПФ нет, и число — деление нуля.

Проверки держат одно решение движка (`report_layout.debt_metric`) и его
читателей: вердикт движка, подбор цены `/ia/goal-seek`, плитку PDF, календарь
и карточку решения на отрисованной странице.

Запуск: python3 -m pytest tests/test_nonres_debt_metric.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main as wrapper  # noqa: E402
from ia_preview import install  # noqa: E402
from test_nonres_object_result import _spec  # noqa: E402

core = wrapper.core


def _nonres_inputs(**over):
    x, t = _spec(retail_enabled=False, **over)
    for key in core.MKD_PRODUCTS:
        for col in ("gns", "total_area", "useful", "saleable", "transfer", "units"):
            if key in t:
                t[key][col] = 0
    x["project_kind"] = core.PROJECT_KIND_NONRESIDENTIAL
    # Ставка метрового объекта нежилого проекта — СМР; умолчание то же, что
    # ставит страница при выборе вида (`object_smr_rate`, решение 06.10.2026).
    for key, turnkey in core.OBJECT_SMR_RATE_DEFAULTS.items():
        if key not in over and float(x.get(key) or 0) == turnkey:
            x[key] = core.object_smr_rate(turnkey, x)
    return x, t


_CACHE: dict[tuple, dict] = {}


def _nonres(**over) -> dict:
    key = tuple(sorted(over.items()))
    if key not in _CACHE:
        x, t = _nonres_inputs(**over)
        _CACHE[key] = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    return _CACHE[key]


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    install(app, core)
    return TestClient(app)


def _payload(**over) -> dict:
    x, t = _nonres_inputs(**over)
    return {"inputs": x, "tep": t, "rates": [], "phasing": {}}


# --- решение движка ------------------------------------------------------------

def test_a_project_with_pf_is_judged_by_llcr() -> None:
    x, t = _spec(offices_strategy="ddu", retail_strategy="ddu")
    result = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    metric = result["report"]["layout"]["debt_metric"]
    assert metric["key"] == "llcr" and metric["value"] == pytest.approx(result["summary"]["llcr"])


def test_a_nonresidential_rent_project_is_judged_by_the_object_dscr() -> None:
    result = _nonres()
    metric = result["report"]["layout"]["debt_metric"]
    office = next(o for o in result["finance"]["nonres"]["objects"] if o["key"] == "offices")
    assert metric["key"] == "dscr"
    assert metric["value"] == pytest.approx(office["kpi"]["dscr_min"])
    assert metric["target"] == 1.20 and metric["floor"] == 1.00
    assert core._layout_dscr(result["report"]["layout"]) == pytest.approx(metric["value"])


def test_a_direct_sale_has_no_debt_cover_and_says_why() -> None:
    metric = _nonres(offices_strategy="direct")["report"]["layout"]["debt_metric"]
    assert metric["key"] is None and metric["value"] is None
    assert "выручкой прямых продаж" in metric["reason"]


def test_the_engine_verdict_does_not_speak_of_llcr_without_pf() -> None:
    verdict = core._purchase_feasibility(500, 900, -8.68, 0.0, 0.0, None, 0.0, None, None, True)
    assert verdict["status"] == "positive"
    assert "LLCR" not in verdict["text"] and "выручкой прямых продаж" in verdict["text"]
    # Проект с ПФ — по-прежнему по LLCR.
    assert "LLCR" in core._purchase_feasibility(500, 900, 1.5, 0.0)["text"]


# --- экономика сходится: EBITDA, расходы, прибыль ----------------------------------

def _pnl_gaps(summary: dict, finance: dict, expense_structure: list) -> dict[str, float]:
    """Расхождения строк «Экономики проекта»: каждое должно быть нулём."""
    return {
        "ebitda − проценты ≠ прибыль до налога":
            summary["ebitda"] - summary["financing_cost"] - summary["profit_before_tax"],
        "выручка − расходы всего ≠ чистая прибыль":
            summary["revenue"] - summary["total_expenses"] - summary["net_profit"],
        "структура расходов ≠ расходы всего":
            sum(e["value"] for e in expense_structure) - summary["total_expenses"],
        "выручка − CAPEX − маркетинг − расходы объектов ≠ EBITDA":
            summary["revenue"] - summary["capex"] - summary["commercial_costs"]
            - float(finance.get("nonres_costs") or 0.0) - summary["ebitda"],
    }


@pytest.mark.parametrize("strategy", ["direct", "income"])
def test_the_economics_lines_add_up_with_objects_outside_ddu(strategy) -> None:
    """Снимок владельца: EBITDA 15,52 − проценты 1,12 = 14,40, а прибыль до
    налога 12,45. Расходы объектов вне ДДУ (продажи ДКП, OPEX, налог на
    имущество, выход) прибыль вычитала, а EBITDA и «Расходы всего» — нет."""
    result = _nonres(offices_strategy=strategy)
    assert float(result["finance"]["nonres_costs"]) > 0
    gaps = _pnl_gaps(result["summary"], result["finance"], result["report"]["expense_structure"])
    assert all(abs(v) < 1.0 for v in gaps.values()), gaps
    labels = [e["label"] for e in result["report"]["expense_structure"]]
    assert core.NONRES_COSTS_LABEL in labels


def test_the_economics_check_catches_the_old_ebitda() -> None:
    """Подделка: EBITDA без расходов объектов — проверка обязана покраснеть."""
    result = _nonres(offices_strategy="direct")
    forged = dict(result["summary"])
    forged["ebitda"] += float(result["finance"]["nonres_costs"])
    gaps = _pnl_gaps(forged, result["finance"], result["report"]["expense_structure"])
    assert abs(gaps["ebitda − проценты ≠ прибыль до налога"]) > 1.0


# --- подбор цены входа ----------------------------------------------------------

def test_the_ceiling_of_a_rent_project_holds_the_dscr(client: TestClient) -> None:
    over = dict(offices_rent_th_per_sqm_month=9.0, offices_loan_share_pct=50, purchase_price_mln=500)
    data = client.post("/ia/goal-seek", json=_payload(**over)).json()
    assert data["available"] is True and data["target_metric"] == "dscr"
    ceiling = data["solution"]["variable"]
    assert data["solution"]["metric"] == pytest.approx(1.20, abs=1e-3)
    above = _nonres(**{**over, "purchase_price_mln": round(ceiling + 50, 1)})
    assert above["report"]["layout"]["debt_metric"]["value"] < 1.20


def test_a_direct_sale_is_not_searched(client: TestClient, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("подбор по показателю, которого нет")
    monkeypatch.setattr(core, "_tool_goal_seek", forbidden)
    data = client.post("/ia/goal-seek", json=_payload(offices_strategy="direct")).json()
    assert data["available"] is False and data["target_metric"] is None
    assert "выручкой прямых продаж" in data["reason"]


# --- PDF и календарь -----------------------------------------------------------

def test_the_pdf_front_tile_reads_the_debt_metric() -> None:
    import pdf_first_page_extension as front
    assert front._debt_metric_tile(_nonres(), core)[0] == "DSCR кредита объектов (мин.)"
    assert front._debt_metric_tile(_nonres(offices_strategy="direct"), core) == \
        ("Кредит объектов", "гасится выручкой ДКП")
    x, t = _spec(offices_strategy="ddu", retail_strategy="ddu")
    mixed = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    assert front._debt_metric_tile(mixed, core)[0] == "LLCR"


def test_the_calendar_shows_the_object_loan_not_a_bridge() -> None:
    events = {e["label"]: e for e in _nonres()["report"]["calendar"]["events"]}
    assert "БРИДЖ" not in events and "Строительство ЖК" not in events
    loan = events["Кредит объекта — Офисы"]
    financing = next(o for o in _nonres()["finance"]["nonres"]["objects"])["financing"]
    assert loan["group"] == "Финансирование" and loan["end"] == financing["repaid_month"]
    x, t = _spec(offices_strategy="ddu", retail_strategy="ddu")
    mixed = core.calculate(core.CalcRequest(inputs=x, tep=t, rates=[]))
    labels = {e["label"] for e in mixed["report"]["calendar"]["events"]}
    assert {"БРИДЖ", "Строительство ЖК"} <= labels


# --- отрисованная страница -------------------------------------------------------

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

VERDICT = r"""() => {
  const card = document.getElementById('iaVerdict');
  const chips = [...document.querySelectorAll('.ai-chip')]
    .filter(c => c.offsetParent !== null || getComputedStyle(c).display !== 'none')
    .map(c => c.innerText.trim());
  const economics = [...document.querySelectorAll('#economicsTable tr')]
    .map(tr => [...tr.cells].map(c => c.innerText.trim()));
  return {text: card ? card.innerText : null, economics,
          nonresCosts: (lastResult.finance || {}).nonres_costs,
          nonresCostsShown: money((lastResult.finance || {}).nonres_costs || 0),
          cells: card ? [...card.querySelectorAll('.ia-verdict-cell')].map(c => [
            c.querySelector('span').innerText.trim(), c.querySelector('b').innerText.trim()]) : [],
          chips, metric: lastResult.report.layout.debt_metric};
}"""


@pytest.fixture(scope="module")
def drawn() -> dict:
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    import browser
    import main_registry

    path = browser.chromium_or_skip()
    out: dict = {}
    with browser.serve(main_registry.app, 18986) as base, sync_playwright() as pw:
        with pw.chromium.launch(executable_path=str(path)) as engine:
            page = engine.new_page(viewport={"width": 1440, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            page.evaluate(SET, ["offices_enabled", True])
            page.wait_for_function("() => lastResult && lastResult.revenue.offices > 0")
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            for strategy in ("income", "direct"):
                page.evaluate(SET, ["offices_strategy", strategy])
                page.wait_for_function(
                    "s => (lastResult.report.nonres_financing||[]).some(o => o.strategy === s)"
                    " && lastResult.report.layout.debt_metric",
                    arg=strategy)
                page.evaluate("() => openTab('report', document.querySelector('[data-tab=report]'))")
                page.wait_for_function("() => document.getElementById('iaVerdict')")
                page.wait_for_timeout(1500)
                out[strategy] = page.evaluate(VERDICT)
            out["errors"] = errors
            page.close()
    return out


def test_the_verdict_card_of_a_rent_project_reads_the_dscr(drawn) -> None:
    state = drawn["income"]
    assert state["metric"]["key"] == "dscr"
    assert "LLCR" not in state["text"]
    first = state["cells"][0]
    assert first[0] == state["metric"]["label"].upper() or first[0] == state["metric"]["label"]
    assert first[1] == f"{state['metric']['value']:.2f}".replace(".", ",") + "x"
    assert "порог банка DSCR 1,20x" in state["text"]
    assert not any("LLCR" in chip for chip in state["chips"])
    assert drawn["errors"] == []


def test_the_page_economics_names_the_object_costs_before_ebitda(drawn) -> None:
    rows = drawn["direct"]["economics"]
    labels = [r[0] for r in rows]
    line = labels.index(core.NONRES_COSTS_LABEL)
    assert line < labels.index("EBITDA")
    assert rows[line][1] == f"({drawn['direct']['nonresCostsShown']})"


def test_the_verdict_card_of_a_direct_sale_does_not_search_a_ceiling(drawn) -> None:
    state = drawn["direct"]
    assert "LLCR" not in state["text"] and "не достигается" not in state["text"]
    cells = dict(state["cells"])
    assert cells.get("МАКСИМУМ ЦЕНЫ ВХОДА", cells.get("Максимум цены входа")) == "не подбирается"
