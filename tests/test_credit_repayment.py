"""Погашение кредитов «Кутузов Сити»: проверка готовности (ТЗ владельца, п. 9) и
условия договоров (выписка `docs/projects/kutuzov_credit_terms.md`).

Каждая проверка падает на подделке, которую называет:

- основной долг при полной выборке без досрочных — 6 610,689 млн ₽, по датам ТЗ;
  база НКЛ 2025 — долг на конец доступности, досрочное до неё второй раз из
  графика не вычитается, досрочное после — уменьшает ближайшие платежи (А п. 6.1);
- ставка — по п. 4.1.1: покрытие эскроу и ступени I(v); у НКЛ 2026 эскроу —
  долей в совокупном чистом долге, а не целиком;
- раскрытие эскроу делает долг срочным в размере раскрытого (А п. 6.1.2);
- эскроу и другие источники не учитываются дважды, заблокированный остаток
  платёж не покрывает;
- перенос раскрытия за дату платежа увеличивает потребность во внешних деньгах;
- отложенные (капитализированные) проценты входят в обязательства в дату
  окончания отсрочки, закрытие всех эскроу эту дату приближает;
- достаточность эскроу (А п. 8.2.60) и ковенанты; без бизнес-плана — «нет данных»;
- каждое число верхнего блока раскрывается до формулы и исходных данных.

Запуск: python3 -m pytest tests/test_credit_repayment.py -q
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import credit_repayment_fixture as fx  # noqa: E402
import developaid_credit_repayment as credit  # noqa: E402

M = credit.M
NONE = {"payments": []}
# Полная выборка, раскрытия нет: график не трогает ничего, кроме базы.
FULL = {"facts.nkl2025": {"debt": 5485.689, "drawn": 5485.689, "accrued_interest": 0.0,
                          "accrued_fee": 0.0},
        "facts.nkl2026": {"debt": 1125.0, "drawn": 1125.0, "accrued_interest": 0.0,
                          "accrued_fee": 0.0},
        "plan.nkl2025": {"draws": [], "prepayments": []},
        "plan.nkl2026": {"draws": [], "prepayments": []},
        "disclosure": {"items": []}}
# ТЗ, п. 3: суммарно при полной выборке, млн ₽.
TZ_TABLE = {"2027-09-30": 3346.270, "2027-12-30": 383.998, "2028-03-30": 383.998,
            "2028-06-30": 383.998, "2028-09-30": 438.855, "2028-12-30": 438.855,
            "2029-03-30": 368.464, "2029-06-30": 438.750, "2029-09-30": 427.500}
A, B = credit.PRESETS["kutuzov_city"]["loans"]


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
    # Досрочные — платежи своих дат; по графику — 4900 − 300 (досрочное до базы уже
    # в базе и второй раз не вычитается: иначе было бы 4500).
    assert paid["2027-03-01"] == pytest.approx(100 * M)
    assert paid["2027-11-01"] == pytest.approx(300 * M)
    assert sum(paid.values()) == pytest.approx(5000 * M, abs=1.0)
    scheduled = {d: v for d, v in paid.items() if d not in {"2027-03-01", "2027-11-01"}}
    assert sum(scheduled.values()) == pytest.approx(4600 * M, abs=1.0)
    # Досрочное после базы — ближайший платёж (А пп. 6.1, 6.2, 5.9): декабрь 2027.
    assert paid["2027-12-30"] == pytest.approx((0.07 * 4900 - 300) * M)
    assert paid["2029-03-30"] == pytest.approx(0.02 * 4900 * M)


def test_the_2026_base_is_the_drawn_limit_and_an_extract_clause_moves_the_prepayment():
    terms = {"prepayment_order": {"value": "from_last", "source": "ОУ банка, п. 3.7"}}
    changes = dict(FULL, **{"plan.nkl2026": {"draws": [], "prepayments": [
        {"date": "2027-05-01", "amount": 125.0}]}, "terms.nkl2026": terms})
    got = credit.forecast(fx.inputs(changes))
    loan = got["loans"][1]
    assert loan["base"]["amount"] == pytest.approx(1125 * M)  # выбранный лимит, не долг 1000
    assert loan["terms"]["prepayment_order"]["source"] == "ОУ банка, п. 3.7"
    paid = _principal(got, "nkl2026")
    assert paid["2029-03-30"] == pytest.approx(258.75 * M)
    assert paid["2029-06-30"] == pytest.approx(438.75 * M)
    assert paid["2029-09-30"] == pytest.approx(302.5 * M)
    # По умолчанию (как в А) — с ближайшего: 258,75 − 125.
    default = credit.forecast(fx.inputs(dict(changes, **{"terms.nkl2026": {}})))
    assert _principal(default, "nkl2026")["2029-03-30"] == pytest.approx(133.75 * M)


# --- 2. Ставка по договорам -----------------------------------------------

def _sums(k, a, e, net=None, key=16.0, margin=4.78):
    return {"days": 1, "K": k, "A": a, "E": e, "net": k - a if net is None else net,
            "base": key + margin}


def test_the_rate_follows_the_escrow_coverage_as_in_clause_4_1_1():
    def rate(k, a, e):
        return credit.segment_rate(A, "contract", "full", _sums(k, a, e))

    # Ниже 100 %: (A·2,02 + F·4,26 + (K−A−F)·(КС+4,78)) / K.
    got, cover = rate(1000, 100, 450)
    assert cover == pytest.approx(0.5)
    assert got == pytest.approx((100 * 2.02 + 450 * 4.26 + 450 * 20.78) / 1000)
    assert rate(1000, 0, 1150)[0] == pytest.approx(2.56)
    assert rate(1000, 0, 1250)[0] == pytest.approx(0.86)
    assert rate(1000, 0, 1251)[0] == pytest.approx(0.01)
    # С аккредитивами при покрытии ≥ 100 %: (A·2,02 + (K−A)·I(v)) / K.
    assert rate(1000, 200, 900)[0] == pytest.approx((200 * 2.02 + 800 * 2.56) / 1000)


def test_the_2026_rate_takes_an_escrow_share_not_the_whole_escrow():
    # Совокупный чистый долг 5000, эскроу 6000: покрытие 1,2 → I(v) Б = 3,39 %.
    got, cover = credit.segment_rate(B, "analogy", "share",
                                     _sums(1000, 0, 6000, net=5000, margin=4.14))
    assert cover == pytest.approx(1.2) and got == pytest.approx(3.39)
    # Весь эскроу дал бы покрытие 6,0 и 0,01 % — двойной учёт денег эскроу.
    assert credit.segment_rate(B, "analogy", "full", _sums(1000, 0, 6000))[0] == \
        pytest.approx(0.01)
    # Ниже 100 % у Б: доля F_Б = E·(K_Б−A_Б)/чистый долг.
    got, cover = credit.segment_rate(B, "analogy", "share",
                                     _sums(1000, 0, 2500, net=5000, margin=4.14))
    assert cover == pytest.approx(0.5)
    assert got == pytest.approx((500 * 4.75 + 500 * 20.14) / 1000)


def test_interest_is_capitalised_in_deferral_and_paid_on_the_28th_after():
    flat = {"path": [{"from": "2026-01-01", "rate": 15.22}]}  # база НКЛ 2025 — 20 %
    changes = dict(FULL, key_rate=flat, escrow={"balance": 0.0}, contracts=NONE, sales=NONE,
                   refunds=NONE, letters_of_credit={"balance": 0.0, "by_loan": {
                       "nkl2025": 0.0, "nkl2026": 0.0}})
    changes["facts.nkl2025"] = dict(FULL["facts.nkl2025"], debt=1000.0)
    rows = _rows(credit.forecast(fx.inputs(changes)))
    for day, row in rows.items():
        if day < "2027-09-30" and "nkl2025" in row["loans"]:
            assert row["loans"]["nkl2025"]["total"] < 1.0, day
    # Отсрочка: каждый месяц — в долг по процентам, на капитализированное — базовая.
    share = 0.20 / 365
    deferred, iod, day, month = 400.0, 20.0, datetime.date(2026, 10, 1), 0.0
    while day < datetime.date(2027, 9, 30):
        day += datetime.timedelta(days=1)
        iod += deferred * share
        month += 1000 * share
        if (day + datetime.timedelta(days=1)).day == 1 or day == datetime.date(2027, 9, 30):
            deferred += month
            month = 0.0
    sept = rows["2027-09-30"]["loans"]["nkl2025"]
    assert sept["deferred"] == pytest.approx(deferred * M)
    assert sept["interest_on_deferred"] == pytest.approx(iod * M)
    # После отсрочки — проценты октября 28 ноября.
    october = rows["2027-11-28"]["loans"]["nkl2025"]["interest"]
    assert october == pytest.approx((1000 - 0.61 * 1000) * share * 31 * M)


def test_closing_every_escrow_ends_the_deferral_early():
    items = {"items": [{"date": "2027-03-15", "amount": None, "confirmed": True,
                        "final": True}]}
    got = credit.forecast(fx.inputs(dict(FULL, disclosure=items)))
    assert [loan["deferral_end"] for loan in got["loans"]] == ["2027-03-15", "2027-03-15"]
    march = _rows(got)["2027-03-15"]["loans"]
    assert march["nkl2025"]["deferred"] > 400 * M
    assert march["nkl2026"]["deferred"] > 10 * M
    assert "все эскроу закрываются 15.03.2027" in got["loans"][0]["deferral_reason"]


# --- 3. Раскрытие и источники — один раз ----------------------------------

def test_the_escrow_counts_each_payment_once():
    changes = dict(FULL, **{
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
        "refunds": {"payments": [{"date": "2026-11-20", "amount": 30.0}]}})
    got = credit.forecast(fx.inputs(changes))
    # Продажа декабря известна месяцем — датирована 31.12; поступление 05.12 — днём.
    on = credit._escrow_on(got["escrow"], datetime.date(2026, 12, 30))
    assert on["before"] == pytest.approx((1000 + 300 + 50 - 30) * M)
    assert got["escrow"]["sales_excluded"] == pytest.approx(460 * M)
    december = next(m for m in got["months"] if m["month"] == "2026-12")
    assert december["blocked"] == pytest.approx(1420 * M)
    assert december["inflow_sales"] == pytest.approx(100 * M)


def _disclosed(day="2027-09-01", amount=3000.0, **extra):
    return dict(FULL, **{
        "escrow": {"balance": 10000.0}, "contracts": NONE, "sales": NONE, "refunds": NONE,
        "disclosure": {"items": [{"date": day, "amount": amount, "confirmed": True,
                                  "final": False}]},
        "free_cash": {"items": [{"date": "2027-08-01", "amount": 500.0}]},
        "extra": {"items": [{"date": "2027-09-15", "amount": 200.0, "confirmed": True},
                            {"date": "2027-09-15", "amount": 900.0, "confirmed": False}]}},
        **extra)


def test_a_disclosure_makes_the_debt_due_in_its_amount():
    rows = _rows(credit.forecast(fx.inputs(_disclosed())))
    day = rows["2027-09-01"]
    # Сначала НКЛ 2025 (допущение до ответа банка) — в размере раскрытого.
    a = day["loans"]["nkl2025"]
    assert a["total"] == pytest.approx(3000 * M)
    assert "nkl2026" not in day["loans"]
    assert day["disclosed_used"] == pytest.approx(3000 * M) and day["deficit"] == 0.0
    # Капитализированные проценты — первыми, остаток — в основной долг, ближайший платёж.
    prepaid = a["principal"]
    assert a["deferred"] > 400 * M and prepaid > 0
    assert rows["2027-09-30"]["loans"]["nkl2025"]["principal"] == pytest.approx(
        0.61 * 5485.689 * M - prepaid)


def test_disclosed_and_other_money_pays_one_date_and_blocked_escrow_pays_none():
    rows = _rows(credit.forecast(fx.inputs(_disclosed())))
    sept, dec = rows["2027-09-30"], rows["2027-12-30"]
    assert sept["disclosed_available"] == pytest.approx(0.0)
    assert (sept["free_used"], sept["extra_used"]) == (pytest.approx(500 * M),
                                                       pytest.approx(200 * M))
    assert sept["deficit"] == pytest.approx(sept["total"] - 700 * M)
    # Потраченное на сентябрь декабрь не покрывает; 7 000 на эскроу заблокированы.
    assert dec["escrow_before"] == pytest.approx(7000 * M)
    assert dec["deficit"] == pytest.approx(dec["total"])


def test_in_the_pool_mode_disclosed_money_is_spent_once():
    pool = {"disclosure_repays": {"value": "pool", "source": "проверка"}}
    rows = _rows(credit.forecast(fx.inputs(_disclosed(**{"terms.nkl2025": pool,
                                                         "terms.nkl2026": pool}))))
    sept, dec = rows["2027-09-30"], rows["2027-12-30"]
    assert sept["disclosed_used"] == pytest.approx(3000 * M)
    assert sept["deficit"] == pytest.approx(sept["total"] - 3700 * M)
    assert dec["disclosed_available"] == pytest.approx(0.0)
    assert dec["deficit"] == pytest.approx(dec["total"])


def test_moving_the_disclosure_past_the_payment_raises_the_outside_need():
    early = credit.analyse(fx.inputs(_disclosed("2027-09-20")))
    late = credit.analyse(fx.inputs(_disclosed("2027-10-20")))
    before = _rows(early["base"])["2027-09-30"]
    after = _rows(late["base"])["2027-09-30"]
    assert after["need_outside"] == pytest.approx(before["need_outside"] + 3000 * M, abs=10 * M)
    assert after["deficit"] > before["deficit"] + 2900 * M
    assert after["late_disclosure"] and not before["late_disclosure"]
    assert late["status"]["color"] == "red"
    assert any("позже платежа 30.09.2027" in r for r in late["status"]["reasons"])
    changes = credit.compare(credit.snapshot(early), late)
    assert any("перенесено с 20.09.2027 на 20.10.2027 — за дату обязательного платежа "
               "30.09.2027" in c["text"] for c in changes), changes


# --- 4. Достаточность эскроу и ковенанты -----------------------------------

def test_escrow_sufficiency_is_the_clause_8_2_60_sum():
    got = credit.forecast(fx.inputs())
    fact = next(i for i in got["sufficiency"] if i["kind"] == "fact")
    # Долг 3000 + невыбранный лимит 2485,689 + неуплаченное 400 + 20 + планируемые проценты.
    assert fact["debt"] == pytest.approx(3000 * M)
    assert fact["undrawn"] == pytest.approx(2485.689 * M)
    assert fact["unpaid"] == pytest.approx(420 * M)
    assert fact["planned_interest"] > 0
    assert fact["need"] == pytest.approx(fact["debt"] + fact["undrawn"] + fact["unpaid"]
                                         + fact["planned_interest"])
    assert fact["escrow"] == pytest.approx(2500 * M) and fact["ok"] is False
    rich = credit.forecast(fx.inputs({"escrow": {"balance": 9000.0}}))
    assert next(i for i in rich["sufficiency"] if i["kind"] == "fact")["ok"] is True
    assert rich["top"]["sufficiency_forecast"]["formula"]


def test_covenants_read_no_data_without_the_business_plan_and_catch_a_shortfall():
    got = credit.forecast(fx.inputs())
    assert [c["state"] for c in got["covenants"]] == ["no_data", "no_data"]
    plan = {"escrow": [{"date": "2026-12-31", "amount": 4000.0},
                       {"date": "2027-03-31", "amount": 4200.0}],
            "ddu": [{"quarter": "2026 Q4", "amount": 600.0},
                    {"quarter": "2027 Q1", "amount": 600.0}]}
    got = credit.forecast(fx.inputs({"business_plan": plan, "contracts": {
        "payments": fx.raw()["contracts"]["payments"],
        "signed": [{"month": "2026-10", "amount": 100.0}]}}))
    escrow, sales = got["covenants"]
    # Прогноз остатка на 31.12.2026 против плана 4 000: отставание больше 25 % → нарушение.
    first = escrow["items"][0]
    assert first["date"] == "2026-12-31" and first["kind"] == "прогноз"
    assert first["gap"] == pytest.approx(1 - first["actual"] / (4000 * M))
    assert first["gap"] >= 0.25 and escrow["state"] == "breach"
    # ДДУ: 100 подписано в октябре + прогноз продаж ноября–марта по 100 — 600 против
    # 1 200 за два квартала: отставание 50 % → нарушение.
    item = sales["items"][0]
    assert item["plan"] == pytest.approx(1200 * M)
    assert item["actual"] == pytest.approx((100 + 5 * 100) * M)
    assert item["gap"] == pytest.approx(0.5) and sales["state"] == "breach"


# --- 5. Раскрытие до исходных данных; нет данных — не ноль ------------------

def test_every_top_number_opens_to_its_formula_and_sources():
    result = credit.analyse(fx.inputs())
    top = result["base"]["top"]
    shown = ["debt_now", "escrow_now", "next", "escrow_at_next", "disclosed_at_next",
             "outside_at_next", "deficit_at_next", "sufficiency_fact", "sufficiency_forecast",
             "first_deficit", "max_deficit"]
    for key in shown:
        assert top[key]["formula"] and top[key]["inputs"], key
    page = credit.render_html(result)
    block = page[page.index("<table class='credit-top'>"):]
    block = block[:block.index("</table>")]
    assert block.count("как посчитано") == len(shown)
    assert "проверочные данные, на 01.10.2026" in block
    assert credit.mln(top["debt_now"]["value"]) == "3 200,000"
    assert f"<td>{credit.mln(top['next']['value'])}</td>" in block
    # Допущение по ставке НКЛ 2026 — видно в сводке.
    assert "Ставка по НКЛ 2026 посчитана по аналогии с НКЛ 2025" in page


def test_missing_data_reads_no_data_not_zero():
    # Нет только свободных денег — платёж известен, а дефицит нет.
    alone = credit.forecast(fx.inputs(drop=("free_cash",)))
    assert alone["top"]["next"]["value"] is not None
    assert alone["top"]["deficit_at_next"]["value"] is None
    result = credit.analyse(fx.inputs(drop=("free_cash", "key_rate")))
    top = result["base"]["top"]
    assert top["deficit_at_next"]["value"] is None
    assert result["status"]["color"] == "unknown"
    assert any(row["total"] is None for row in result["base"]["rows"])
    page = credit.render_html(result)
    row = page[page.index("Непокрытый дефицит"):]
    assert row[:row.index("</tr>")].count(credit.NO_DATA) >= 1
    assert "прогнозе ключевой ставки" in page
    with pytest.raises(ValueError, match="единицу"):
        credit.normalize("escrow", {"as_of": "2026-10-01", "source": "банк",
                                    "data": {"balance": 1}})
    with pytest.raises(ValueError, match="дата актуальности"):
        credit.normalize("escrow", {"source": "банк", "unit": "млн ₽", "data": {"balance": 1}})
    with pytest.raises(ValueError, match="confirmed"):
        credit.normalize("disclosure", {"as_of": "2026-10-01", "source": "банк",
                                        "unit": "млн ₽", "data": {"items": [
                                            {"date": "2027-01-01", "final": True}]}})
    with pytest.raises(ValueError, match="пункт договора"):
        credit.normalize("terms.nkl2026", {"as_of": "2026-10-01", "source": "выписка",
                                           "data": {"rate": {"value": "contract"}}})


# --- 6. Статус -------------------------------------------------------------

def _covered(confirmed):
    return dict(FULL, **{
        "contracts": NONE, "sales": NONE, "refunds": NONE, "escrow": {"balance": 9000.0},
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
    assert set(credit.DATASETS) - {"terms.nkl2025"} <= set(names)
