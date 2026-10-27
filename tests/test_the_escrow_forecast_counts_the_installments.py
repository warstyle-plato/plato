"""Прогноз эскроу учитывает рассрочку; раскрытие в таблице по кварталам — явно.

Владелец, 27.10.2026:
- «В прогнозе эскроу никак не учитывается, что 1,5 млрд на эскроу сейчас при
  продажах 2,5. Причина в рассрочке, которая должна быть погашена при вводе»;
  на вопрос, как раскладывать остаток, — «Равномерно до ввода»;
- на провале «Плана финмодели» 7,31 → 1,96 млрд в квартале раскрытия: «И
  получается бред. По прогнозу ФМ нет уточнения, что она тут гасит долг».

Проверки:
- к вводу на эскроу — накоплено плюс весь остаток по подписанным договорам
  плюс новые продажи по нынешнему темпу подписания; до ввода — равномерно;
  без срока ввода — прежнее продолжение темпа (кабинет продаж его не знает);
- в квартале раскрытия план финмодели берётся на месяц раскрытия, отклонение
  к нему не считается, раскрытие названо: «раскрыто X, из них на погашение
  кредита Y»; провал ряда без пояснения роняет проверку.

Запуск: python3 -m pytest tests/test_the_escrow_forecast_counts_the_installments.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import developaid_management_report as report  # noqa: E402
from market_search import contracting, sales_store  # noqa: E402
from test_management_report_funding import _isolated, _project, _sales  # noqa: E402,F401
from test_management_report_model import M, PROJECT  # noqa: E402

# Подписано 250 млн ₽, на эскроу 150 млн ₽: остаток 100 млн ₽ — рассрочка.
ROWS = [
    {"month": "2026-07", "amount": 150 * M, "escrow_paid": 100 * M,
     "escrow_schedule": [{"month": "2026-07", "amount": 60 * M},
                         {"month": "2026-08", "amount": 20 * M},
                         {"month": "2026-09", "amount": 20 * M}]},
    {"month": "2026-08", "amount": 100 * M, "escrow_paid": 50 * M,
     "escrow_schedule": [{"month": "2026-08", "amount": 30 * M},
                         {"month": "2026-09", "amount": 10 * M},
                         {"month": "2026-10", "amount": 10 * M}]},
]
CREDIT = {"queues": [{"queue": "1 очередь", "repay_from": "2027-02",
                      "escrow": {m: 100 * M for m in ("2026-10", "2026-11", "2026-12",
                                                      "2027-01", "2027-02")},
                      "pf": {m: 200 * M for m in ("2026-10", "2026-11", "2026-12",
                                                  "2027-01", "2027-02")}}]}


def test_the_installments_are_on_the_escrow_by_commissioning():
    block = contracting.escrow_sufficiency({}, ROWS, CREDIT, settle="2027-01")["queues"][0]
    assert block["owed"] == pytest.approx(100 * M)
    # Новые продажи: 250 млн за июль — сентябрь, по 250/3 в месяц.
    assert block["sales_pace"] == pytest.approx(250 / 3 * M)
    assert block["paid_now"] == pytest.approx(150 * M) and block["data_month"] == "2026-10"
    at_entry = contracting.keeping_at(block, "2027-01")
    # К вводу — вся сумма подписанных договоров плюс новые продажи до ввода.
    assert at_entry == pytest.approx((150 + 100 + 3 * 250 / 3) * M)
    assert at_entry >= sum(row["amount"] for row in ROWS)
    # До ввода — равномерно: через месяц треть остатка и треть новых продаж.
    assert contracting.keeping_at(block, "2026-11") == pytest.approx(
        (150 + (100 + 250) / 3) * M)
    # После ввода прироста нет.
    assert contracting.keeping_at(block, "2027-06") == pytest.approx(at_entry)
    # Раскрытие (январь, месяц перед погашением) — тем же расчётом.
    assert block["keeping_pace_escrow"] == pytest.approx(at_entry)


def test_without_a_commissioning_date_the_pace_goes_on():
    """Кабинет продаж срока ввода не знает: прежнее продолжение темпа."""
    block = contracting.escrow_sufficiency({}, ROWS, CREDIT)["queues"][0]
    assert block["settle"] == ""
    # Темп поступлений — июль — сентябрь: (60 + 50 + 30) / 3.
    assert contracting.keeping_at(block, "2027-01") == pytest.approx(
        (140 + 4 * 140 / 3) * M)


def _with_a_dip():
    """План финмодели: на эскроу 105 млн в январе, 20 млн в феврале; кредит
    со 100 до 30 млн — раскрытие с погашением."""
    _project()
    _sales(bank=True)
    kept = sales_store.load(sales_store.default_dir(), "ЖК")
    parts = {name: source["data"] for name, source in kept["sources"].items()}
    queue = parts["credit"]["queues"][0]
    queue["escrow"]["2027-02"] = 20 * M
    queue["pf"]["2027-02"] = 30 * M
    sales_store.save(sales_store.default_dir(), "ЖК", parts, "test.xlsx")


def _built(monkeypatch):
    monkeypatch.setattr(report, "_monitor_view", lambda project, end: {"dashboard": {
        "funding": {"known": False, "reason": "нет"},
        "schedule": {"approved_finish": "2027-03-31"}}})
    return report.build(PROJECT, "week", "2026-10-18", sales_project="ЖК")


def test_the_disclosure_is_told_and_the_dip_is_not_compared(monkeypatch):
    _with_a_dip()
    built = _built(monkeypatch)
    track = built["funding"]["escrow_track"]
    rows = {row["quarter"]: row for row in track["rows"]}
    last = rows["2027 Q1"]
    # План финмодели в квартале раскрытия — на январь, до раскрытия, не 20 млн.
    assert last["fm"] == pytest.approx(105 * M) and last["fm_at"] == "2027-01"
    assert last["gap_fm"] is None and last["after_disclosure"]
    step = track["disclosure"]
    assert (step["released"], step["repaid"]) == (pytest.approx(85 * M), pytest.approx(70 * M))

    said = ("Раскрытие эскроу, январь 2027: по плану финмодели на эскроу 105,0 млн ₽, в "
            "феврале 2027 — 20,0 млн ₽: раскрыто 85,0 млн ₽, из них на погашение кредита "
            "70,0 млн ₽ (остаток кредита с 100,0 млн ₽ до 30,0 млн ₽).")
    text = report.render_text(built)
    page = report.render_html(built)
    assert said in text and said in page
    assert "план финмодели 105,0 млн ₽ на январь 2027, до раскрытия" in text
    assert "105,0 млн ₽ (на январь 2027, до раскрытия)" in page
    # Ввод (март) позже раскрытия: «к вводу» сравнивается с планом до
    # погашения, а не с остатком после него (20 млн эскроу, 30 млн кредита).
    at = built["funding"]["escrow"]["queues"][0]["at_commissioning"]
    assert at["plan_at"] == "2027-01"
    assert (at["plan_escrow"], at["plan_pf"]) == (pytest.approx(105 * M), pytest.approx(100 * M))
    assert "к вводу 31.03.2027 (утверждённый срок; план — на январь 2027, до раскрытия)" in page


def test_a_dip_without_an_explanation_fails(monkeypatch):
    """Падение «Плана финмодели» между кварталами допустимо только с пояснением
    раскрытия в той же строке и словами под таблицей."""
    _with_a_dip()
    built = _built(monkeypatch)
    track = built["funding"]["escrow_track"]
    text = report.render_text(built)
    shown = [row for row in track["rows"] if row.get("fm") is not None]
    for before, after in zip(shown, shown[1:]):
        if after["fm"] < before["fm"]:
            assert after.get("fm_at") and "Раскрытие эскроу" in text, after
    # И сам провал (20 млн после раскрытия) в колонку не попадает.
    assert all(row["fm"] != pytest.approx(20 * M) for row in shown)


def test_without_a_dip_the_plan_stays_comparable(monkeypatch):
    """Ряд финмодели на раскрытии не падает — он накопленный, сравнение остаётся."""
    _project()
    _sales(bank=True)
    built = _built(monkeypatch)
    track = built["funding"]["escrow_track"]
    assert track["disclosure"] is None
    assert all(not row["after_disclosure"] for row in track["rows"])
    assert track["rows"][-1]["gap_fm"] is not None
