"""Погашение кредитов «Кутузов Сити»: проверка готовности (ТЗ владельца, п. 9).

Каждая проверка падает на подделке, которую называет:

- основной долг при полной выборке — 6 610,689 млн ₽, по датам как в ТЗ;
  база НКЛ 2025 — долг на конец доступности, досрочное до неё второй раз из
  графика не вычитается;
- эскроу и другие источники не учитываются дважды: деньги месяца остатка уже
  на счёте, продажа из действующего договора — не новая продажа, раскрытое и
  свободные деньги, потраченные на платёж, второй раз платёж не покрывают,
  заблокированный остаток платёж не покрывает;
- перенос раскрытия за дату платежа увеличивает потребность во внешних деньгах;
- отложенные проценты входят в обязательства в дату окончания отсрочки, а
  закрытие всех эскроу эту дату приближает;
- каждое число верхнего блока раскрывается до формулы и исходных данных,
  отсутствующее — «нет данных», а не ноль.

Запуск: python3 -m pytest tests/test_credit_repayment.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import credit_repayment_fixture as fx  # noqa: E402
import developaid_credit_repayment as credit  # noqa: E402

M = credit.M
FULL = {"facts.nkl2025": {"debt": 5485.689, "drawn": 5485.689, "accrued_interest": 0.0,
                          "accrued_fee": 0.0},
        "facts.nkl2026": {"debt": 1125.0, "drawn": 1125.0, "accrued_interest": 0.0,
                          "accrued_fee": 0.0},
        "plan.nkl2025": {"draws": [], "prepayments": []},
        "plan.nkl2026": {"draws": [], "prepayments": []}}
# ТЗ, п. 3: суммарно при полной выборке, млн ₽.
TZ_TABLE = {"2027-09-30": 3346.270, "2027-12-30": 383.998, "2028-03-30": 383.998,
            "2028-06-30": 383.998, "2028-09-30": 438.855, "2028-12-30": 438.855,
            "2029-03-30": 368.464, "2029-06-30": 438.750, "2029-09-30": 427.500}


def _rows(result):
    return {row["date"]: row for row in result["rows"]}


def _principal(result, loan):
    return {row["date"]: row["loans"][loan]["principal"] for row in result["rows"]
            if loan in row["loans"] and row["loans"][loan]["principal"]}


# --- 1. Основной долг по графику -------------------------------------------

def test_at_full_draw_the_schedule_is_6610_689_by_the_tz_dates():
    got = credit.forecast(fx.inputs(FULL))
    principal = {d: r["principal"] for d, r in _rows(got).items() if r["principal"]}
    assert sum(principal.values()) == pytest.approx(6610.689 * M, abs=1.0)
    assert {d: round(v / M, 3) for d, v in principal.items()} == TZ_TABLE
    # Справочный график ТЗ — та же функция графика.
    assert sum(r["total"] for r in credit.reference()) == pytest.approx(6610.689 * M, abs=1.0)


def test_the_2025_base_is_the_debt_at_the_end_of_availability_and_a_prepayment_counts_once():
    plan = {"draws": [{"date": "2027-01-15", "amount": 2000.0}],
            "prepayments": [{"date": "2027-03-01", "amount": 100.0},
                            {"date": "2027-11-01", "amount": 300.0}]}
    got = credit.forecast(fx.inputs(dict(FULL, **{
        "facts.nkl2025": dict(FULL["facts.nkl2025"], debt=3000.0, drawn=3000.0),
        "plan.nkl2025": plan})))
    loan = got["loans"][0]
    # База — долг на 30.06.2027: 3000 + 2000 − 100, а не лимит 5 485,689.
    assert loan["base"]["amount"] == pytest.approx(4900 * M)
    assert loan["base"]["kind"] == "прогноз"
    paid = _principal(got, "nkl2025")
    assert paid["2027-09-30"] == pytest.approx(0.61 * 4900 * M)
    # Досрочное до базы уже в базе: по графику погашается 4900 − 300 (после базы),
    # а не 4900 − 300 − 100.
    assert sum(paid.values()) == pytest.approx(4600 * M, abs=1.0)
    # Досрочное после базы — с последних платежей: 2 % марта 2029 ушли целиком.
    assert "2029-03-30" not in paid
    assert paid["2028-12-30"] == pytest.approx((0.08 * 4900 - (300 - 0.02 * 4900)) * M)


def test_the_2026_base_is_the_drawn_limit_and_the_contract_rule_moves_the_prepayment():
    terms = {"prepayment_order": {"value": "nearest", "source": "выписка договора, п. 7.4"}}
    changes = dict(FULL, **{"plan.nkl2026": {"draws": [], "prepayments": [
        {"date": "2027-05-01", "amount": 125.0}]}, "terms.nkl2026": terms})
    got = credit.forecast(fx.inputs(changes))
    loan = got["loans"][1]
    assert loan["base"]["amount"] == pytest.approx(1125 * M)  # выбранный лимит, а не долг 1000
    assert loan["terms"]["prepayment_order"]["source"] == "выписка договора, п. 7.4"
    paid = _principal(got, "nkl2026")
    # Правило договора «с ближайшего»: 23 % = 258,75 уменьшено на 125.
    assert paid["2029-03-30"] == pytest.approx(133.75 * M)
    assert paid["2029-06-30"] == pytest.approx(438.75 * M)
    assert paid["2029-09-30"] == pytest.approx(427.5 * M)
    assert sum(paid.values()) == pytest.approx(1000 * M)


# --- 2. Эскроу и другие источники — один раз ---------------------------------

def test_the_escrow_counts_each_payment_once():
    changes = {
        "escrow": {"balance": 1000.0},
        "contracts": {"payments": [
            {"month": "2026-09", "amount": 70.0, "contract": "ДДУ-1"},   # уже на счёте
            {"month": "2026-10", "amount": 200.0, "contract": "ДДУ-1"},  # месяц остатка
            {"month": "2026-11", "amount": 300.0, "contract": "ДДУ-2"},
            {"date": "2026-12-05", "amount": 50.0}]},
        "sales": {"sales": [
            {"month": "2026-10", "amount": 400.0},                       # месяц выгрузки договоров
            {"month": "2026-12", "amount": 60.0, "contract": "ДДУ-2"},   # уже договор
            {"month": "2026-12", "amount": 100.0}]},
        "refunds": {"payments": [{"date": "2026-11-20", "amount": 30.0}]},
        "disclosure": {"items": []},
    }
    got = credit.forecast(fx.inputs(changes))
    first = got["rows"][0]
    assert first["date"] == "2026-12-30"
    # Продажа декабря известна месяцем — она датирована 31.12 и платёж 30.12 не
    # покрывает; поступление 05.12 известно днём.
    assert first["escrow_before"] == pytest.approx((1000 + 300 + 50 - 30) * M)
    assert got["escrow"]["sales_excluded"] == pytest.approx(460 * M)
    december = next(m for m in got["months"] if m["month"] == "2026-12")
    assert december["blocked"] == pytest.approx(1420 * M)
    assert december["inflow_sales"] == pytest.approx(100 * M)


def test_disclosed_and_other_money_pays_one_date_and_blocked_escrow_pays_none():
    changes = dict(FULL, **{
        "escrow": {"balance": 10000.0},
        "contracts": {"payments": []}, "sales": {"payments": []},
        "refunds": {"payments": []},
        "disclosure": {"items": [{"date": "2027-09-01", "amount": 3000.0,
                                  "confirmed": True, "final": False}]},
        "free_cash": {"items": [{"date": "2027-08-01", "amount": 500.0}]},
        "extra": {"items": [{"date": "2027-09-15", "amount": 200.0, "confirmed": True},
                            {"date": "2027-09-15", "amount": 900.0, "confirmed": False}]}})
    got = credit.forecast(fx.inputs(changes))
    rows = _rows(got)
    sept, dec = rows["2027-09-30"], rows["2027-12-30"]
    owed = sept["total"]
    assert sept["disclosed_used"] == pytest.approx(3000 * M)
    assert sept["need_outside"] == pytest.approx(owed - 3000 * M)
    assert (sept["free_used"], sept["extra_used"]) == (pytest.approx(500 * M),
                                                       pytest.approx(200 * M))
    assert sept["deficit"] == pytest.approx(owed - 3700 * M)
    # Потраченное на сентябрь декабрь не покрывает; 7 000 на эскроу заблокированы.
    assert dec["escrow_before"] == pytest.approx(7000 * M)
    assert dec["disclosed_available"] == pytest.approx(0.0)
    assert dec["deficit"] == pytest.approx(dec["total"])
    # До раскрытия источник — только свободные деньги.
    for row in got["rows"]:
        if row["date"] < "2027-09-01":
            assert row["disclosed_used"] == 0.0
    # По НКЛ раскрытое раздельно и в сумме — то же, что сводно.
    assert sum(item["disclosed_used"] for item in sept["loans"].values()) == pytest.approx(
        sept["disclosed_used"])


# --- 3. Перенос раскрытия -----------------------------------------------------

def _with_disclosure(day):
    return dict(FULL, **{
        "contracts": {"payments": []}, "sales": {"payments": []},
        "refunds": {"payments": []}, "escrow": {"balance": 5000.0},
        "disclosure": {"items": [{"date": day, "amount": 3000.0,
                                  "confirmed": True, "final": False}]}})


def test_moving_the_disclosure_past_the_payment_raises_the_outside_need():
    early = credit.analyse(fx.inputs(_with_disclosure("2027-09-20")))
    late = credit.analyse(fx.inputs(_with_disclosure("2027-10-20")))
    before = _rows(early["base"])["2027-09-30"]
    after = _rows(late["base"])["2027-09-30"]
    assert after["need_outside"] == pytest.approx(before["need_outside"] + 3000 * M)
    assert after["deficit"] > before["deficit"]
    assert after["late_disclosure"] and not before["late_disclosure"]
    assert late["status"]["color"] == "red"
    assert any("позже платежа 30.09.2027" in r for r in late["status"]["reasons"])
    changes = credit.compare(credit.snapshot(early), late)
    assert any("перенесено с 20.09.2027 на 20.10.2027 — за дату обязательного платежа "
               "30.09.2027" in c["text"] for c in changes), changes
    # Сумма дефицита за прогноз та же: позднее раскрытие гасит декабрь. Сдвиг
    # виден датой — сентябрю денег не хватает больше.


# --- 4. Отложенные проценты ---------------------------------------------------

def _deferred_case(**extra):
    flat = {"path": [{"from": "2026-01-01", "rate": 15.22}]}  # ставка кредита 20 %
    return dict(FULL, **{"facts.nkl2025": dict(FULL["facts.nkl2025"], debt=1000.0,
                                               drawn=5485.689),
                         "key_rate": flat}, **extra)


def test_deferred_interest_falls_due_on_the_end_of_deferral():
    got = credit.forecast(fx.inputs(_deferred_case()))
    rows = _rows(got)
    for day, row in rows.items():
        if day < "2027-09-30":
            assert row["loans"]["nkl2025"]["interest"] == 0.0
            assert row["loans"]["nkl2025"]["deferred"] == 0.0
    share, days = 0.20 / 365, 364  # 02.10.2026–30.09.2027, оба года по 365 дней
    sept = rows["2027-09-30"]["loans"]["nkl2025"]
    assert sept["deferred"] == pytest.approx((400 + 1000 * share * days) * M)
    assert sept["interest_on_deferred"] == pytest.approx(
        (20 + 400 * share * days + 1000 * share ** 2 * (days - 1) * days / 2) * M)
    assert rows["2027-09-30"]["total"] >= sept["deferred"] + sept["interest_on_deferred"]


def test_closing_every_escrow_ends_the_deferral_early():
    items = {"items": [{"date": "2027-03-15", "amount": None, "confirmed": True,
                        "final": True}]}
    got = credit.forecast(fx.inputs(_deferred_case(disclosure=items)))
    assert [loan["deferral_end"] for loan in got["loans"]] == ["2027-03-15", "2027-03-15"]
    march = _rows(got)["2027-03-15"]["loans"]
    assert march["nkl2025"]["deferred"] > 400 * M
    assert march["nkl2026"]["deferred"] > 10 * M
    assert "все эскроу закрываются 15.03.2027" in got["loans"][0]["deferral_reason"]


# --- 5. Раскрытие до исходных данных; нет данных — не ноль ------------------

def test_every_top_number_opens_to_its_formula_and_sources():
    result = credit.analyse(fx.inputs())
    top = result["base"]["top"]
    shown = ["debt_now", "escrow_now", "next", "escrow_at_next", "disclosed_at_next",
             "outside_at_next", "deficit_at_next", "first_deficit", "max_deficit"]
    for key in shown:
        assert top[key]["formula"] and top[key]["inputs"], key
    page = credit.render_html(result)
    block = page[page.index("<table class='credit-top'>"):]
    block = block[:block.index("</table>")]
    assert block.count("как посчитано") == len(shown)
    assert "проверочные данные, на 01.10.2026" in block
    assert credit.mln(top["debt_now"]["value"]) == "3 200,000"
    assert f"<td>{credit.mln(top['next']['value'])}</td>" in block


def test_missing_data_reads_no_data_not_zero():
    result = credit.analyse(fx.inputs(drop=("free_cash", "key_rate")))
    top = result["base"]["top"]
    assert top["deficit_at_next"]["value"] is None
    # Комиссия 30.12.2026 от ставки не зависит, проценты 30.09.2027 — зависят.
    assert top["next"]["value"] is not None
    assert _rows(result["base"])["2027-09-30"]["total"] is None
    assert result["status"]["color"] == "unknown"
    page = credit.render_html(result)
    row = page[page.index("Непокрытый дефицит"):]
    assert row[:row.index("</tr>")].count(credit.NO_DATA) >= 1
    assert "прогнозе ключевой ставки" in page
    # Набор без даты или без единицы не принимается.
    with pytest.raises(ValueError, match="единицу"):
        credit.normalize("escrow", {"as_of": "2026-10-01", "source": "банк",
                                    "data": {"balance": 1}})
    with pytest.raises(ValueError, match="дата актуальности"):
        credit.normalize("escrow", {"source": "банк", "unit": "млн ₽", "data": {"balance": 1}})
    with pytest.raises(ValueError, match="confirmed"):
        credit.normalize("disclosure", {"as_of": "2026-10-01", "source": "банк",
                                        "unit": "млн ₽", "data": {"items": [
                                            {"date": "2027-01-01", "final": True}]}})


# --- 6. Статус -------------------------------------------------------------

def _covered(confirmed):
    return dict(FULL, **{
        "contracts": {"payments": []}, "sales": {"payments": []},
        "refunds": {"payments": []}, "escrow": {"balance": 9000.0},
        "disclosure": {"items": [{"date": "2027-06-01", "amount": None,
                                  "confirmed": confirmed, "final": True}]}})


def test_status_is_green_yellow_red():
    assert credit.analyse(fx.inputs(_covered(True)))["status"]["color"] == "green"
    yellow = credit.analyse(fx.inputs(_covered(False)))["status"]
    assert yellow["color"] == "yellow" and "неподтверждённых" in yellow["reasons"][0]
    assert credit.analyse(fx.inputs())["status"]["color"] == "red"
    stress = credit.analyse(fx.inputs(), {"inflow_cut_pct": 50, "disclosure_delay_months": 6,
                                          "key_rate_pp": 3})
    assert stress["stress"]["top"]["deficit_total"]["value"] > \
        stress["base"]["top"]["deficit_total"]["value"]
    assert stress["stress"]["top"]["interest_cost"]["value"] > \
        stress["base"]["top"]["interest_cost"]["value"]


def test_the_upload_sample_is_accepted_as_is():
    import json

    sample = json.loads((ROOT / "docs" / "samples" / "credit_repayment_template.json")
                        .read_text(encoding="utf-8"))
    names = [credit.normalize(item["name"], item)["name"] for item in sample["datasets"]]
    assert set(credit.DATASETS) - {"terms.nkl2026"} <= set(names)
