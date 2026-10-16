"""IRR проекта — главный; IRR капитала — вторым и с пометкой «не показателен».

Решение владельца 16.10.2026 («IRR проекта + пометка»): карточка решения
показывала «IRR 305,14%» — IRR собственного капитала проекта, где всё до ПФ
несёт БРИДЖ и своих денег почти нет. Арифметически верно, но не доходность.

- IRR проекта считается по потоку до финансирования (без процентов, комиссий
  и тел кредитов, как строка книги «Проектный CF до финансирования»), по тому
  же потоку, что NPV проекта (`cashflow.project`).
- IRR капитала — числом, только если своих денег не меньше 10 % полных затрат
  (выбор владельца); иначе «не показателен: своих денег N млн ₽ (X% затрат)».
  Решает одна функция движка (`summary.equity_irr`); страница, тизер, книга v4,
  бот и Платон читают её решение.

Каждая проверка падает на прежнем коде: там не было ни `irr_project`, ни
решения, и IRR капитала стоял числом 557 %. Проверки страницы — ещё и на
подделке, где страница решала бы по своим деньгам сама.

Запуск: python3 -m pytest tests/test_irr_project_is_the_headline.py -q
"""

from __future__ import annotations

import copy
import io
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as _wrapper  # noqa: E402
from browser import chromium_or_skip, serve  # noqa: E402
from developaid_finance_math import monthly_irr, monthly_npv  # noqa: E402

core = _wrapper.core
PORT = 18803
THIN = "не показателен: своих денег"
# Рост цены 3 %/мес.: долг погашен, своих денег ~916 млн ₽ — 2,1 % затрат,
# IRR капитала 557 %. Контрпример — те же вводные и 6 млрд своих до ПФ.
THIN_INPUTS = {"project_name": "Почти без своих денег", "monthly_growth_pre_pct": 3}
EQUITY_INPUTS = {"project_name": "Со своими деньгами", "monthly_growth_pre_pct": 3,
                 "pre_pf_own_funds_mln": 6000}


def _inputs(update: dict) -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(update)
    return inputs


def _run(update: dict) -> dict:
    return core._run_authoritative_model(_inputs(update), copy.deepcopy(core.TEP_DEFAULT), [], {})


@pytest.fixture(scope="module")
def thin() -> dict:
    return _run(THIN_INPUTS)


@pytest.fixture(scope="module")
def funded() -> dict:
    return _run(EQUITY_INPUTS)


def test_the_engine_heads_with_the_project_irr(thin, funded):
    summary = thin["consolidated"]["summary"]
    assert summary["equity_returns"]["status"] == "ok", "стенд не про непогашенный долг"
    assert isinstance(summary["irr_project"], float) and 0 < summary["irr_project"] < 2
    verdict = summary["equity_irr"]
    assert verdict["status"] == "thin_equity" and verdict["meaningful"] is False
    assert summary["irr_equity"] is None, "IRR капитала числом при почти нулевых своих деньгах"
    assert summary["irr_equity_raw"] > 1, "стенд не про IRR капитала сотнями процентов"
    assert verdict["own_funds_share"] < core.EQUITY_IRR_MIN_OWN_SHARE
    assert verdict["label"].startswith(THIN) and "% затрат)" in verdict["label"]
    assert core.equity_irr_label(summary) == verdict["label"]

    ok = funded["consolidated"]["summary"]
    assert ok["equity_irr"]["status"] == "ok" and ok["equity_irr"]["meaningful"] is True
    assert isinstance(ok["irr_equity"], float) and isinstance(ok["irr_project"], float)
    assert ok["equity_irr"]["own_funds_share"] >= core.EQUITY_IRR_MIN_OWN_SHARE
    assert core.equity_irr_label(ok) is None


def test_the_threshold_is_the_owners():
    assert core.EQUITY_IRR_MIN_OWN_SHARE == pytest.approx(0.10)


def test_npv_and_irr_of_the_project_read_one_flow_before_financing(thin):
    """NPV и IRR проекта — один поток, и в нём нет ни процентов, ни комиссий."""
    result = thin["consolidated"]
    summary, flow = result["summary"], result["cashflow"]["project"]
    rate = float(_inputs(THIN_INPUTS).get("discount_rate_pct", 20)) / 100
    assert summary["npv"] == pytest.approx(monthly_npv(flow, rate), rel=1e-9)
    assert summary["irr_project"] == pytest.approx(monthly_irr(flow), abs=1e-9)
    # До финансирования: стоимость кредита не уменьшает поток проекта. Сумма
    # потока — прибыль до процентов: чистая прибыль плюс проценты и комиссии
    # (налог и НДС уже вычтены и там, и там).
    finance_cost = float(summary["financing_cost"])
    assert finance_cost > 1e8
    assert sum(flow) == pytest.approx(float(summary["net_profit"]) + finance_cost, rel=1e-6)


def test_the_phases_and_the_whole_are_decided():
    """Свои деньги свода — сумма вложений очередей, как КОНСОЛИДАТОР!M8."""
    phasing = {"enabled": True, "mode": "phased", "phase_count": 2, "user_enabled": True,
               "phase_gap_months": 12,
               "phases": [{"name": f"О{i + 1}", "start_offset_months": 12 * i,
                           "construction_months": 30} for i in range(2)]}
    bundle = core._run_authoritative_model(_inputs(THIN_INPUTS), copy.deepcopy(core.TEP_DEFAULT),
                                           [], phasing)
    phases = [item["result"]["summary"] for item in bundle["phases"]]
    whole = bundle["consolidated"]["summary"]
    assert whole["equity_contributed"] == pytest.approx(
        sum(p["equity_contributed"] for p in phases), rel=1e-9)
    for summary in [whole] + phases:
        assert "equity_irr" in summary and "irr_project" in summary
        if summary["equity_irr"]["meaningful"] is False:
            assert summary["irr_equity"] is None


def test_plato_names_the_project_irr_and_explains_the_equity_one(thin, funded):
    snap = core._result_snapshot(thin["consolidated"])
    assert isinstance(snap["irr_project_pct"], float)
    assert snap["irr_equity_pct"] is None, "Платон получил бы 557 % как доходность"
    assert snap["irr_equity_label"].startswith(THIN)
    assert "БРИДЖ" in snap["irr_equity_reason"] or "кредит" in snap["irr_equity_reason"]
    assert "irr_project_pct" in core._AGENT_INSTRUCTIONS
    assert "не показателен" in core._AGENT_INSTRUCTIONS
    ok = core._result_snapshot(funded["consolidated"])
    assert isinstance(ok["irr_equity_pct"], float) and ok["irr_equity_label"] is None


def test_the_presentation_numbers_carry_the_label(thin, funded):
    eff = core.presentation_numbers(thin["consolidated"])["efficiency"]
    assert isinstance(eff["irr_project"], float)
    assert eff["irr_equity"] is None and eff["irr_equity_na"].startswith(THIN)
    eff = core.presentation_numbers(funded["consolidated"])["efficiency"]
    assert isinstance(eff["irr_equity"], float) and eff["irr_equity_na"] is None


def _teaser_text(bundle: dict, update: dict) -> str:
    from pypdf import PdfReader
    pdf = core.build_teaser_pdf(bundle, _inputs(update), copy.deepcopy(core.TEP_DEFAULT), {})
    reader = PdfReader(io.BytesIO(pdf))
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in reader.pages))


def test_the_teaser_heads_with_the_project_irr(thin, funded):
    text = _teaser_text(thin, THIN_INPUTS)
    assert "IRR проекта" in text, text[:400]
    assert THIN in text, "тизер напечатал IRR капитала числом"
    assert "Equity IRR" not in text
    assert THIN not in _teaser_text(funded, EQUITY_INPUTS), "контрпример: IRR капитала числом"


def _book(update: dict):
    openpyxl = pytest.importorskip("openpyxl")
    from xlsx_eval import Evaluator

    content, _name, meta = core.build_project_workbook(
        _inputs(update), copy.deepcopy(core.TEP_DEFAULT), [], {}, project_name="IRR")
    assert list(meta.get("missing") or []) == [], meta.get("missing")
    sys.setrecursionlimit(400000)
    return Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))


def _dashboard_value(book, key: str):
    import v4_dashboard
    return book.cell(v4_dashboard.DATA_SHEET, f"C{v4_dashboard.DATA_ROWS[key]}")


def test_the_book_obeys_the_same_threshold(thin, funded):
    """ОТЧЕТ!B14 (через КОНСОЛИДАТОР!N8) — тот же порог и та же подпись."""
    book = _book(THIN_INPUTS)
    shown = book.cell("ОТЧЕТ", "B14")
    label = thin["consolidated"]["summary"]["equity_irr"]["label"]
    assert isinstance(shown, str) and shown.startswith(THIN), shown
    # Книга пишет число без разделителя тысяч — сравниваем без пробелов.
    assert shown.replace(" ", "") == label.replace(" ", "").replace(" ", ""), (shown, label)
    assert _dashboard_value(book, "irr_project") == pytest.approx(
        thin["consolidated"]["summary"]["irr_project"], abs=1e-9)

    book = _book(EQUITY_INPUTS)
    assert book.cell("ОТЧЕТ", "B14") == pytest.approx(
        funded["consolidated"]["summary"]["irr_equity"], abs=1e-4)


def test_the_dashboard_puts_the_project_irr_first():
    import v4_dashboard
    keys = [item[0] for item in v4_dashboard.DATA_ITEMS]
    assert keys.index("irr_project") < keys.index("irr_equity")


VERDICT = r"""() => {
  const lead = () => document.getElementById('iaVerdictLead').textContent;
  const before = lead();
  const s = lastResult.summary;
  const status = (s.equity_irr || {}).status;
  // Подделка: движок сказал «показателен» при тех же своих деньгах.
  s.equity_irr = Object.assign({}, s.equity_irr, {status: 'ok', meaningful: true, label: null});
  s.irr_equity = 0.4321;
  renderResult();
  return {before, after: lead(), status};
}"""

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  el.value = value;
  el.onchange();
}"""


def test_the_decision_card_heads_with_the_project_irr():
    """Отрисованная карточка «Инвестиционное решение» (корень, слой IA)."""
    chrome = chromium_or_skip()
    from playwright.sync_api import sync_playwright

    import main_registry

    errors: list[str] = []
    with serve(main_registry.app, PORT) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chrome))
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="domcontentloaded")
            page.wait_for_function("() => typeof lastResult !== 'undefined' && lastResult")
            page.evaluate(SET, ["monthly_growth_pre_pct", 3])
            page.wait_for_function(
                "() => lastResult && lastResult.summary.equity_irr"
                " && lastResult.summary.equity_irr.status === 'thin_equity'", timeout=120_000)
            page.evaluate("() => openTab('report', document.querySelector('[data-tab=report]'))")
            page.wait_for_function("() => document.getElementById('iaVerdictLead')"
                                   " && document.getElementById('iaVerdictLead').textContent")
            page.wait_for_timeout(500)
            got = page.evaluate(VERDICT)
        finally:
            browser.close()

    other = [line for line in errors if "Failed to fetch" not in line]
    assert not other, f"страница упала: {other[:2]}"
    assert got["status"] == "thin_equity", got
    before, after = got["before"], got["after"]
    assert re.search(r"IRR проекта \d", before), before
    assert "IRR капитала " + THIN in before, before
    assert before.index("IRR проекта") < before.index("IRR капитала")
    assert not re.search(r"IRR капитала \d", before), before
    # Подделка: страница печатает число, то есть не решает сама.
    assert THIN not in after and re.search(r"IRR капитала 43", after), after


def test_the_classic_table_and_the_chat_summary_read_the_engine():
    page = core.PAGE
    assert "row('IRR проекта (до финансирования)'" in page
    assert "row('IRR собственного капитала',irrEquityNa(r.summary)" in page
    assert "irr_equity_label:irrEquityNa(s)," in page
    assert "'IRR equity'" not in page
