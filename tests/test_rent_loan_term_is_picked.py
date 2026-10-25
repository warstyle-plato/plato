"""Подбор срока кредита аренды и срок удержания, с которого аренда обгоняет продажу.

Владелец, 25.10.2026: «может в настройках где-то быть для доходного метода
подбор параметра срока кредита, чтобы можно было его погасить с баллоном или
без за счёт доходного потока? Сейчас непонятно — арендный бизнес вообще не
проходит, или за 10 лет нет, а за 15 уже выгоднее продажи».

* Подбор (`loan_term_pick`) даёт два срока рядом: самый короткий, при котором
  аренда в каждом году покрывает платежи с запасом банка 1,20 при нынешнем
  баллоне, и самый короткий, при котором аренда гасит кредит целиком без
  баллона. Нет такого срока до 30 лет — ответ называет причину.
* Срок, истёкший до ввода, покрытием не считается: движок показывает у него
  огромный DSCR, потому что долг гасится разом в месяц ввода.
* Кнопка «Подобрать» у поля — отдельный запрос (`/loan-term-pick`); срок
  встаёт в поле с пометкой «подобран», повторяется сам при смене вводных, а
  ручное число сильнее подбора.
* «Сравнение стратегий» называет срок удержания, начиная с которого аренда
  обгоняет лучшую продажу по NPV проекта.

Запуск: python3 -m pytest tests/test_rent_loan_term_is_picked.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_nonres_strategy as ns  # noqa: E402
import main_legacy as core  # noqa: E402
from test_an_office_shows_sale_and_rent_side_by_side import _spec  # noqa: E402

# Офис, которому аренда по силам: кредит поменьше, аренда повыше.
FEASIBLE = {"offices_loan_share_pct": 30, "offices_rent_th_per_sqm_month": 6}


def _loan(x: dict, t: dict, term: int, balloon: float) -> dict:
    """Кредит офиса прямым расчётом движка, без подбора: срок и баллон
    заданы, удержание не короче срока кредита."""
    y = copy.deepcopy(x)
    y.update(offices_strategy=ns.STRATEGY_INCOME, offices_loan_term_years=term,
             offices_loan_balloon_pct=balloon,
             offices_hold_years=max(int(y.get("offices_hold_years") or 5), term))
    run = core._calculate_economics(core.CalcRequest(inputs=y, tep=copy.deepcopy(t), rates=[]))
    obj = next(o for o in run["finance"]["nonres"]["objects"] if o["key"] == "offices")
    return {"dscr": obj["kpi"]["dscr_min"], "commissioning": obj["commissioning"],
            "maturity": obj["kpi"]["loan_maturity"], "balloon": obj["kpi"]["loan_balloon"]}


def _covered(loan: dict, floor: float) -> bool:
    return loan["maturity"] > loan["commissioning"] and loan["dscr"] is not None and loan["dscr"] >= floor


@pytest.fixture(scope="module")
def feasible() -> dict:
    x, t = _spec(offices_strategy=ns.STRATEGY_INCOME, **FEASIBLE)
    return {"x": x, "t": t, "pick": core.loan_term_pick(x, t, [], "offices")}


def test_the_bank_term_is_the_shortest_that_covers_with_a_margin(feasible) -> None:
    x, t, bank = feasible["x"], feasible["t"], feasible["pick"]["bank"]
    years = bank["years"]
    assert years and bank["floor"] == core.DEBT_METRIC_TARGET == 1.20
    assert bank["balloon_pct"] == 20
    assert _covered(_loan(x, t, years, 20), 1.20)
    assert not _covered(_loan(x, t, years - 1, 20), 1.20)
    assert f"не короче {years} лет" in bank["text"] and "20%" in bank["text"]


def test_the_full_term_repays_the_whole_loan_from_the_rent(feasible) -> None:
    x, t, full = feasible["x"], feasible["t"], feasible["pick"]["full"]
    years = full["years"]
    assert years and full["balloon_pct"] == 0 and full["floor"] == 1.0
    loan = _loan(x, t, years, 0)
    assert _covered(loan, 1.0) and loan["balloon"] == 0
    assert not _covered(_loan(x, t, years - 1, 0), 1.0)
    assert "без крупного последнего платежа" in full["text"]


def test_a_term_ending_before_the_opening_is_not_coverage(feasible) -> None:
    """Подделка: срок короче стройки. Движок даёт ему огромный DSCR (долг
    гасится разом в месяц ввода, мимо покрытия), но подбор его не берёт."""
    x, t = feasible["x"], feasible["t"]
    short = _loan(x, t, 1, 20)
    assert short["maturity"] <= short["commissioning"] and short["dscr"] > 1.2
    assert core._loan_term_trial(x, t, [], "offices", 1, 20)["dscr_min"] is None
    assert feasible["pick"]["bank"]["years"] > 1


def test_no_term_up_to_thirty_years_names_the_reason() -> None:
    x, t = _spec(offices_strategy=ns.STRATEGY_INCOME)
    pick = core.loan_term_pick(x, t, [], "offices")
    assert pick["max_years"] == ns.LONG_TERM_MAX_YEARS == 30
    for variant in (pick["bank"], pick["full"]):
        assert variant["years"] is None
        assert "подходящего срока нет" in variant["text"]
        assert "даже при сроке 30 лет" in variant["text"]
        # Причина: даже проценты аренда не покрывает — срок тут не поможет.
        assert "Одни только проценты" in variant["text"] and "не поможет" in variant["text"]
    assert _loan(x, t, 30, 20)["dscr"] < 1.0


def test_the_term_counts_only_with_annuity_repayment() -> None:
    x, t = _spec(offices_strategy=ns.STRATEGY_INCOME, offices_debt_repayment=ns.REPAY_SWEEP)
    with pytest.raises(ValueError, match="аннуитет"):
        core.loan_term_pick(x, t, [], "offices")


def test_the_route_answers_and_refuses_with_a_reason(feasible) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(core.app)
    body = {"inputs": feasible["x"], "tep": feasible["t"], "rates": [], "phasing": {}}
    answer = client.post("/loan-term-pick", json={**body, "prefix": "offices"})
    assert answer.status_code == 200
    assert answer.json()["bank"]["years"] == feasible["pick"]["bank"]["years"]
    refused = client.post("/loan-term-pick", json={**body, "prefix": "housing"})
    assert refused.status_code == 400 and "нет доходного метода" in refused.json()["detail"]


def test_the_calculation_itself_does_not_pick(feasible, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("подбор срока внутри расчёта")

    monkeypatch.setattr(core, "loan_term_pick", boom)
    result = core.calculate(core.CalcRequest(inputs=feasible["x"], tep=feasible["t"], rates=[]))
    assert result["summary"]["npv"] is not None


# --- срок удержания в «Сравнении стратегий» ---------------------------------------

def _npv(x: dict, t: dict, strategy: str, **over) -> float:
    return core._strategy_npv(x, t, [], ("offices",), strategy, fixed=over or None)


def _hold_line(x: dict, t: dict) -> dict:
    bundle = core._run_authoritative_model(x, t, [], {})
    block = core.strategy_compare_for_report(bundle, x, t, [], {})
    return next(p for p in block["items"][0]["points"] if p["kind"] == "hold")


def test_the_hold_from_which_rent_beats_the_sale() -> None:
    # Дешёвые деньги (дисконт 5%) и аренда, которой хватает только на долгий срок.
    x, t = _spec(offices_strategy=ns.STRATEGY_DIRECT, offices_rent_th_per_sqm_month=2.6,
                 discount_rate_pct=5)
    line = _hold_line(x, t)
    years = line["value"]
    sale = max(_npv(x, t, ns.STRATEGY_DDU), _npv(x, t, ns.STRATEGY_DIRECT))
    assert years and 1 < years < 30
    assert _npv(x, t, ns.STRATEGY_INCOME, hold_years=years) >= sale
    assert _npv(x, t, ns.STRATEGY_INCOME, hold_years=years - 1) < sale
    assert _npv(x, t, ns.STRATEGY_INCOME, hold_years=30) >= sale
    assert line["text"].startswith(f"Аренда обгоняет продажу по ДДУ при удержании здания от {years} лет")
    assert "(сейчас 5 лет)" in line["text"]


def test_rent_that_never_beats_the_sale_says_so() -> None:
    x, t = _spec(offices_strategy=ns.STRATEGY_DIRECT)
    line = _hold_line(x, t)
    assert line["value"] is None and line["years"] == []
    assert "не обгоняет продажу по ДДУ ни при каком сроке удержания здания от 1 до 30 лет" in line["text"]
    assert "Ближе всего она, если держать здание" in line["text"]


def test_the_office_book_keeps_a_long_hold_and_a_long_loan() -> None:
    """Удержание и кредит дольше прежних 5 и 10 лет книга не обрезает: месяцев
    в её таблицах хватает, и каждый итог сходится с движком."""
    openpyxl = pytest.importorskip("openpyxl")
    import office_workbook as ow

    x, t = _spec(offices_strategy=ns.STRATEGY_INCOME, offices_hold_years=15,
                 offices_loan_term_years=20, offices_loan_balloon_pct=0, **FEASIBLE)
    content, _, meta = core.build_project_workbook(x, t, [], {}, project_name="Офис")
    assert meta.get("checks") == ow.PASSED and meta.get("missing") == []
    verdict, bad = ow.verdict(ow.evaluate(openpyxl.load_workbook(io.BytesIO(content))))
    assert verdict == ow.PASSED and bad == []


# --- страница: браузер ----------------------------------------------------------------

PORT = 18998

SET = r"""([id, value]) => {
  const el = document.querySelector(`[data-field="${id}"] input, [data-field="${id}"] select`);
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  el.onchange();
}"""

READ = r"""() => {
  const field = document.querySelector('[data-field="offices_loan_term_years"]');
  const seen = el => !!el && el.offsetParent !== null;
  return {
    value: inputs.offices_loan_term_years,
    shown: field ? field.querySelector('input').value : null,
    origin: (inputs._field_origin || {})['inputs.offices_loan_term_years'] || null,
    note: field ? (field.querySelector('.glavapu-origin') || {}).textContent || '' : '',
    button: field ? seen(field.querySelector('.loan-term-pick-go')) : false,
    lines: field ? [...field.querySelectorAll('.loan-term-pick-lines li')].map(li => li.textContent) : [],
    inputs: JSON.parse(JSON.stringify(inputs)), tep};
}"""

PICKED = "() => ((inputs._field_origin||{})['inputs.offices_loan_term_years']||{}).source === 'picked'"


@pytest.fixture(scope="module")
def page_state() -> dict:
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
            page.goto(base, wait_until="domcontentloaded")
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_enabled", True])
            browser.wait_for_result(page)
            page.evaluate("() => { applyProjectKind('nonresidential'); closeProjectKindDialog(); }")
            browser.wait_for_result(page)
            for key, value in [("offices_strategy", "income"), *FEASIBLE.items()]:
                page.evaluate(SET, [key, value])
                browser.wait_for_result(page)
            page.evaluate("() => openTab('inputs', null)")
            # Группа объекта и её разделы свёрнуты — открываем, как человек.
            page.evaluate("""() => { let el = document.querySelector('[data-field="offices_loan_term_years"]');
              for (; el; el = el.parentElement) if (el.tagName === 'DETAILS') el.open = true; }""")
            out["before"] = page.evaluate(READ)
            page.click('[data-field="offices_loan_term_years"] .loan-term-pick-go')
            page.wait_for_function(PICKED, timeout=60_000)
            browser.wait_for_result(page)
            out["picked"] = page.evaluate(READ)
            # Вводные изменились — подобранный срок подбирается заново сам.
            page.evaluate(SET, ["offices_loan_share_pct", 20])
            page.wait_for_function(
                f"() => inputs.offices_loan_term_years !== {out['picked']['value']}", timeout=60_000)
            browser.wait_for_result(page)
            out["repicked"] = page.evaluate(READ)
            # Ручное число сильнее подбора: следующая смена вводных его не трогает.
            page.evaluate(SET, ["offices_loan_term_years", 17])
            browser.wait_for_result(page)
            page.evaluate(SET, ["offices_loan_share_pct", 25])
            browser.wait_for_result(page)
            page.wait_for_timeout(500)
            out["manual"] = page.evaluate(READ)
            out["errors"] = errors
            page.close()
    return out


def test_the_page_has_a_pick_button_at_the_loan_term(page_state) -> None:
    assert page_state["errors"] == []
    assert page_state["before"]["button"]
    assert page_state["before"]["origin"] is None


def test_the_picked_term_is_the_engine_pick_and_says_so(page_state) -> None:
    state = page_state["picked"]
    x, t = copy.deepcopy(state["inputs"]), state["tep"]
    x["offices_loan_term_years"] = page_state["before"]["value"]
    pick = core.loan_term_pick(x, t, [], "offices")
    assert state["value"] == pick["bank"]["years"] and state["shown"] == str(pick["bank"]["years"])
    assert state["origin"]["source"] == "picked" and state["origin"]["mode"] == "bank"
    assert state["note"].startswith(f"подобран: {pick['bank']['years']} лет")
    assert state["lines"] == [pick["bank"]["text"], pick["full"]["text"]]


def test_a_picked_term_follows_its_inputs(page_state) -> None:
    state = page_state["repicked"]
    pick = core.loan_term_pick(state["inputs"], state["tep"], [], "offices")
    assert state["inputs"]["offices_loan_share_pct"] == 20
    assert state["value"] == pick["bank"]["years"] != page_state["picked"]["value"]
    assert state["origin"]["source"] == "picked"


def test_a_typed_term_is_stronger_than_the_pick(page_state) -> None:
    state = page_state["manual"]
    assert state["value"] == 17 and state["origin"]["source"] == "manual"
    assert state["inputs"]["offices_loan_share_pct"] == 25
