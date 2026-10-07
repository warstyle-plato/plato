"""Чистый расчёт гостиницы (`developaid_hotel_strategy`) и ориентиры полей.

Проверяется то, что легко сломать незаметно: пустое поле не становится нулём,
загрузка выходит на цель за заданный срок, льгота НДС живёт ровно свои годы
и не раздувает расходы, ставки льготного и обычного кредита считаются своими
формулами, лимит кредита режет выдачу и говорит об этом, выход продажей и
удержание различаются, налог, NPV и IRR — общие функции движка, а не копия.

Запуск: python3 -m pytest tests/test_hotel_strategy.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import developaid_finance_math as fm  # noqa: E402
import developaid_hotel_strategy as hs  # noqa: E402
import hotel_presets  # noqa: E402
import hotel_reference as ref  # noqa: E402

COMMISSIONING = date(2030, 1, 1)


def params(**over) -> dict:
    base = {
        "keys": 100, "adr_rub": 15_000, "adr_price_date": "2030-01-01", "index_pct": 0,
        "occ_start_pct": 50, "occ_target_pct": 70, "ramp_months": 12,
        "fnb_pct": 40, "other_pct": 10, "rooms_cost_pct": 20, "fnb_cost_pct": 65,
        "other_cost_pct": 50, "ag_pct": 5, "sm_pct": 2, "pom_pct": 3, "utilities_pct": 4,
        "base_fee_pct": 2, "incentive_fee_pct": 6, "ffe_reserve_pct": 1,
        "insurance_pct": 0.1, "hold_years": 5,
    }
    base.update(over)
    return base


def plan(**over) -> dict:
    capex = {date(2028, m, 1): 40_000_000.0 for m in range(1, 13)}
    capex.update({date(2029, m, 1): 40_000_000.0 for m in range(1, 13)})
    p = {"commissioning": COMMISSIONING, "capex": capex,
         "capex_ffe": {date(2029, 12, 1): 40_000_000.0},
         "capex_land": {date(2028, 1, 1): 50_000_000.0},
         "params": params(), "start": date(2027, 1, 1)}
    p.update(over)
    return p


def run(p: dict | None = None, rate: float = 0.10) -> dict:
    return hs.hotel_flows(p or plan(), lambda month: rate, vat_rate=0.22,
                          profit_tax_rate=0.25, discount_rate=0.15)


# --- поля ---------------------------------------------------------------

def test_an_empty_field_is_named_not_zero():
    p = params()
    del p["adr_rub"]
    p["fnb_pct"] = ""
    missing = {f.key for f in hs.missing_fields(p)}
    assert {"adr_rub", "fnb_pct"} <= missing
    with pytest.raises(ValueError, match="ADR"):
        run(plan(params=p))


def test_a_zero_is_an_answer_not_a_gap():
    assert not hs.missing_fields(params(sm_pct=0))


def test_reference_fields_have_no_silent_default():
    """Числа чужой площадки умолчанием не бывают; умолчание — только закон,
    программа или правило движка, и у него названо происхождение."""
    for field in hs.FIELDS:
        if field.default is not None:
            assert field.origin, field.key
    for name in ("keys", "adr_rub", "occ_start_pct", "occ_target_pct", "fnb_pct",
                 "rooms_cost_pct", "ag_pct", "base_fee_pct", "insurance_pct",
                 "exit_multiple", "dscr_target"):
        assert hs.FIELD_BY_KEY[name].default is None, name


def test_dependent_fields_are_needed_only_with_their_choice():
    p = params()
    assert "exit_multiple" not in {f.key for f in hs.missing_fields(p)}
    p["valuation"] = hs.VALUATION_MULTIPLE
    assert "exit_multiple" in {f.key for f in hs.missing_fields(p)}
    p["repayment"] = hs.REPAY_SCULPTED
    assert "dscr_target" in {f.key for f in hs.missing_fields(p)}
    p["financing"] = hs.FINANCING_NONE
    assert "dscr_target" not in {f.key for f in hs.missing_fields(p)}


# --- эксплуатация -------------------------------------------------------

def test_occupancy_reaches_the_target_after_the_ramp():
    assert hs.occupancy(1, 0.5, 0.7, 12) == 0.5
    assert hs.occupancy(13, 0.5, 0.7, 12) == pytest.approx(0.7)
    assert hs.occupancy(7, 0.5, 0.7, 12) == pytest.approx(0.6)
    assert hs.occupancy(0, 0.5, 0.7, 12) == 0.0


def test_rooms_revenue_is_keys_days_occupancy_adr():
    result = run()
    jan = result["monthly"]
    assert jan["rooms_revenue"][COMMISSIONING] == pytest.approx(100 * 31 * 0.5 * 15_000)
    rooms = jan["rooms_revenue"][COMMISSIONING]
    assert jan["fnb_revenue"][COMMISSIONING] == pytest.approx(rooms * 0.4)
    assert jan["other_revenue"][COMMISSIONING] == pytest.approx(rooms * 1.4 * 0.1)


def test_adr_is_indexed_from_its_price_date():
    p = plan(params=params(index_pct=10, adr_price_date="2029-01-01"))
    result = run(p)
    adr = result["monthly"]["adr"][COMMISSIONING]
    assert adr == pytest.approx(15_000 * 1.1)


def test_vat_relief_lives_its_years_and_is_not_an_expense_base():
    result = run(plan(params=params(vat_relief_years=2)))
    m = result["monthly"]
    first, last, after = COMMISSIONING, date(2031, 12, 1), date(2032, 1, 1)
    assert m["vat_relief"][first] == pytest.approx(m["rooms_revenue"][first] * 0.22)
    assert m["vat_relief"][last] == pytest.approx(m["rooms_revenue"][last] * 0.22)
    assert after not in m["vat_relief"]
    plain = run()["monthly"]
    # Расходы и GOP от льготы не меняются: она — налог, а не работа.
    assert m["gop"][first] == pytest.approx(plain["gop"][first])
    assert m["ebitda"][first] - plain["ebitda"][first] == pytest.approx(m["vat_relief"][first])


def test_usali_lines_add_up_to_ebitda():
    for row in run()["annual"]:
        if not row["rooms_available"]:
            continue
        gop = (row["department_revenue"] - row["rooms_expense"] - row["fnb_expense"]
               - row["other_expense"] - row["ag"] - row["sm"] - row["pom"] - row["utilities"])
        assert row["gop"] == pytest.approx(gop)
        ebitda = (row["gop"] + row["vat_relief"] - row["base_fee"] - row["incentive_fee"]
                  - row["ffe_reserve"] - row["property_tax"] - row["insurance"])
        assert row["ebitda"] == pytest.approx(ebitda)


def test_property_tax_skips_furniture_and_land():
    result = run(plan(params=params(property_tax_pct=2.2)))
    kpi = result["kpi"]
    capex_net = kpi["capex_net"]
    assert kpi["building_net"] == pytest.approx(capex_net - kpi["ffe_net"] - kpi["land"])
    first = result["monthly"]["property_tax"][COMMISSIONING]
    assert first < capex_net * 0.022 / 12
    assert first == pytest.approx(kpi["building_net"] * 0.022 / 12, rel=0.01)


# --- кредит -------------------------------------------------------------

def test_preferential_and_commercial_rates():
    pref = run(plan(params=params(financing=hs.FINANCING_PREFERENTIAL,
                                  pref_key_share_pct=30, pref_margin_pp=3)), rate=0.16)
    com = run(plan(params=params(financing=hs.FINANCING_COMMERCIAL, loan_spread_pp=4)),
              rate=0.16)
    assert all(r == pytest.approx(0.3 * 0.16 + 0.03) for r in pref["monthly"]["loan_rate"].values())
    assert all(r == pytest.approx(0.20) for r in com["monthly"]["loan_rate"].values())
    assert pref["totals"]["loan_interest"] < com["totals"]["loan_interest"]


def test_no_loan_means_no_draws():
    result = run(plan(params=params(financing=hs.FINANCING_NONE)))
    assert result["totals"]["loan_draw"] == 0 and result["kpi"]["loan_peak"] == 0


def test_the_loan_limit_caps_draws_and_says_so():
    result = run(plan(params=params(loan_share_pct=90, loan_limit_th_per_key=5_000)))
    assert result["totals"]["loan_draw"] == pytest.approx(100 * 5_000 * 1000)
    assert any("Лимит кредита" in w for w in result["warnings"])


def test_principal_waits_for_the_grace_and_the_opening():
    result = run(plan(params=params(grace_months=36)))
    m = result["monthly"]
    first_draw = min(m["loan_draw"])
    grace_end = hs.add_months(first_draw, 36)
    scheduled = [mm for mm, v in m["loan_repayment"].items()
                 if v > m.get("loan_vat_prepayment", {}).get(mm, 0.0) + 1e-6]
    assert min(scheduled) >= max(COMMISSIONING, grace_end)


def test_vat_refund_repays_the_loan_not_the_equity():
    result = run()
    m = result["monthly"]
    assert sum(m["loan_vat_prepayment"].values()) == pytest.approx(
        result["totals"]["vat_refund"], rel=1e-9)


def test_sculpted_repayment_keeps_the_target_dscr():
    result = run(plan(params=params(repayment=hs.REPAY_SCULPTED, dscr_target=1.3,
                                    hold_years=15, loan_term_years=15)))
    full = [row for row in result["annual"] if row["months"] == 12 and row.get("dscr")
            and row["loan_repayment"]]
    assert len(full) >= 3
    assert all(row["dscr"] == pytest.approx(1.3, rel=1e-6) for row in full[1:-1])


def test_the_loan_is_closed_by_the_end():
    for mode in (hs.EXIT_SALE, hs.EXIT_HOLD):
        result = run(plan(params=params(exit_mode=mode)))
        assert result["monthly"]["loan_balance"].get(result["horizon_end"], 0.0) == 0.0


# --- выход --------------------------------------------------------------

def test_sale_and_hold_differ_by_the_deal():
    sale = run(plan(params=params(exit_mode=hs.EXIT_SALE, exit_cap_pct=10)))
    hold = run(plan(params=params(exit_mode=hs.EXIT_HOLD, exit_cap_pct=10)))
    end = sale["horizon_end"]
    assert sale["kpi"]["exit_value"] == pytest.approx(hold["kpi"]["exit_value"])
    assert sale["kpi"]["exit_value"] == pytest.approx(sale["kpi"]["forward_ebitda"] / 0.10)
    assert sale["monthly"]["exit_revenue"][end] == pytest.approx(sale["kpi"]["exit_value"])
    assert sale["monthly"]["exit_cost"][end] == pytest.approx(sale["kpi"]["exit_value"] * 0.01)
    assert not hold["monthly"].get("exit_revenue")
    assert hold["monthly"]["residual_value"][end] == pytest.approx(hold["kpi"]["exit_value"])
    assert hold["totals"]["profit_tax"] < sale["totals"]["profit_tax"]


def test_ev_ebitda_valuation():
    result = run(plan(params=params(valuation=hs.VALUATION_MULTIPLE, exit_multiple=6)))
    assert result["kpi"]["exit_value"] == pytest.approx(result["kpi"]["forward_ebitda"] * 6)


# --- налог, NPV, IRR — общие функции -----------------------------------

def test_profit_tax_is_the_shared_schedule():
    result = run()
    months = result["months"]
    m = result["monthly"]
    deductions = {mm: m.get("loan_interest_cap", {}).get(mm, 0.0)
                  + m.get("loan_interest_paid", {}).get(mm, 0.0)
                  + m.get("loan_fee", {}).get(mm, 0.0) for mm in months}
    schedule, _ = fm.profit_tax_schedule(
        months, {mm: m.get("tax_margin", {}).get(mm, 0.0) for mm in months},
        deductions, COMMISSIONING, 0.25)
    assert result["totals"]["profit_tax"] == pytest.approx(sum(schedule.values()))


def test_npv_and_irr_are_the_shared_functions():
    result = run()
    kpi = result["kpi"]
    assert kpi["npv_project"] == pytest.approx(fm.monthly_npv(result["project_cf"], 0.15))
    assert kpi["npv_equity"] == pytest.approx(fm.equity_npv(result["equity_cf"], 0.15))
    assert kpi["irr_equity"] == fm.monthly_irr(result["equity_cf"])


def test_payback():
    # Месяц 0 — целый месяц с вложением: ноль достигнут в конце 13-го месяца.
    assert hs.payback_years([-12.0] + [1.0] * 24) == pytest.approx(13 / 12)
    assert hs.payback_years([-12.0] + [1.0] * 5) is None
    assert hs.payback_years([-12.0] + [1.0] * 24, 0.10) > 13 / 12


def test_engine_names_are_the_shared_functions():
    """Движок зовёт ту же реализацию, а не свою копию."""
    import ast
    tree = ast.parse((ROOT / "main_legacy.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert not {"_monthly_npv", "_equity_npv", "_monthly_irr",
                "_profit_tax_schedule"} & defined


# --- ориентиры ---------------------------------------------------------

def test_every_preset_value_names_known_cells():
    for preset in hotel_presets.PRESETS:
        for field, item in preset.values.items():
            assert field in hs.FIELD_BY_KEY, (preset.key, field)
            assert all(cell in ref.BY_KEY for cell in item.cells), (preset.key, field)


def test_a_preset_fills_values_with_their_origin():
    x = hotel_presets.apply_preset({"hotel_keys": 150}, "dombai", only_empty=True)
    assert x["hotel_keys"] == 150 and "keys" not in x[hotel_presets.ORIGINS_KEY]
    origin = x[hotel_presets.ORIGINS_KEY]["occ_start_pct"]
    assert x["hotel_occ_start_pct"] == pytest.approx(47.0)
    assert origin["text"].startswith("ориентир: Домбай 5*")
    assert "dombai:Предпосылки!E393" in origin["cells"]
    assert not hs.missing_fields(hs.params_from_inputs(x))


def test_a_partial_preset_leaves_its_gaps_empty():
    x = hotel_presets.apply_preset({}, "uai")
    assert "hotel_fnb_pct" not in x
    assert "fnb_pct" in {f.key for f in hs.missing_fields(hs.params_from_inputs(x))}


def test_hint_range_spans_the_presets_of_the_class():
    hint = hotel_presets.hint_range("adr_rub", "5")
    assert hint["min"] < hint["max"]
    assert set(hint["sources"]) == {"Домбай 5*", "UAI 5*"}
    assert hotel_presets.hint_range("adr_rub", "3") is None


def test_the_dombai_adr_is_the_book_chain():
    """Средний ADR ориентира × индекс I кв. 2029 книги = ADR книги (Расчеты!819)."""
    adr_2029 = hotel_presets.BY_KEY["dombai"].values["adr_rub"].value
    q1_index = 1.04 ** 0.25  # книга индексирует на конец квартала
    assert adr_2029 * q1_index == pytest.approx(18537.827, rel=1e-4)
