"""Первый квартал модели банка — остаток на дату модели, а не квартал продаж.

«Очевидно, что линия банка в планах взята, в отличие от плана финмодели, не
накопленным итогом… такое ощущение, что разные базы сравнения» (владелец,
05.10.2026). На графике «Факт против планов» линия банка начиналась в 2026 Q1
с 1,6 млрд — втрое выше любого квартала факта — и проваливалась следом:
продажи по договорам идут с 2025 Q3, а модель банка начинается позже и в
первую колонку кладёт всё проданное до своей даты.

Проверки:
- поквартально этот квартал не стоит на линии банка, а едет отдельной записью
  с фактом за квартал и фактом с начала продаж;
- накопленный итог всех трёх линий считает одна функция, и итог банка
  начинается с его остатка;
- вывод под графиком сравнивает факт с той же линией банка, что на графике
  (валовые продажи), а не со строкой рассрочки;
- на отрисованной странице переключатель «накопленным итогом» меняет числа.

Запуск: python3 -m pytest tests/test_the_bank_opening_quarter_is_not_a_quarter.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from market_search import contracting  # noqa: E402

M = 1e6
# Факт по кварталам: продажи с 2025 Q3.
FACT = {"2025 Q3": 450 * M, "2025 Q4": 520 * M, "2026 Q1": 500 * M,
        "2026 Q2": 380 * M, "2026 Q3": 430 * M}
# Модель банка с 2026 Q1: первая колонка — проданное до даты модели.
BANK_GROSS = {"2026 Q1": 1_480 * M, "2026 Q2": 400 * M, "2026 Q3": 488.9 * M,
              "2026 Q4": 600 * M}
# Рассрочка — другая мера (деньги до эскроу), заведомо отличная от валовых.
BANK_CASH = {"2026 Q1": 900 * M, "2026 Q2": 300 * M, "2026 Q3": 350 * M}


def _summary(bank_gross: dict[str, float] = BANK_GROSS) -> dict:
    months = [f"{q[:4]}-{int(q[-1]) * 3 - 2 + i:02d}" for q in FACT for i in range(3)]
    return {
        "by_quarter": [{"quarter": q, "amount": v, "area": v / 250_000,
                        "price_per_sqm": 250_000} for q, v in FACT.items()],
        "by_quarter_flats": {},
        "dynamics": [{"month": m, "amount": FACT[contracting.quarter_of(m)] / 3}
                     for m in months],
        "fm_plan": {"sheet": "Продажи ФМ_new Банников",
                    "plan": {"Итого": {m: {"amount": 230 * M} for m in months}}},
        "bank_plan": {"sheet": "Модель банка_new", "gross_by_quarter": bank_gross,
                      "revenue_by_quarter": BANK_CASH,
                      "area_by_quarter": {q: v / 250_000 for q, v in bank_gross.items()},
                      "price_by_quarter": {q: 250_000.0 for q in bank_gross}},
    }


def _row(plans: dict, label: str) -> dict:
    return next(r for r in plans["quarters"] if r["label"] == label)


def test_the_opening_quarter_is_not_drawn_as_a_quarter() -> None:
    plans = contracting.plan_comparison(_summary())
    first = _row(plans, "2026 Q1")
    assert first["bank_amount"] is None, "остаток банка стоял на линии рядом с квартальным фактом"
    assert first["bank_area"] is None
    assert first["bank_price"] == 250_000.0, "цена — не поток, её квартал сравним"
    assert _row(plans, "2026 Q2")["bank_amount"] == 400 * M
    opening = plans["bank_opening"]
    assert opening["quarter"] == "2026 Q1" and opening["amount"] == 1_480 * M
    assert opening["fact_since"] == "2025 Q3"
    assert opening["fact_quarter"] == 500 * M
    assert opening["fact_to_date"] == 1_470 * M
    assert opening["closer_to"] == "to_date"


def test_one_function_accumulates_all_three_lines() -> None:
    plans = contracting.plan_comparison(_summary())
    rows = plans["quarters"]
    assert [r["fact_amount_cum"] for r in rows] == [450 * M, 970 * M, 1_470 * M,
                                                    1_850 * M, 2_280 * M]
    assert [r["fm_amount_cum"] for r in rows] == [690 * M * k for k in range(1, 6)]
    # До модели банка итога нет (не ноль); с неё — остаток плюс кварталы.
    assert [r["bank_amount_cum"] for r in rows] == [None, None, 1_480 * M,
                                                    1_880 * M, 2_368.9 * M]


def test_a_bank_model_starting_with_sales_has_no_opening() -> None:
    """Контрпример: модель банка с первого квартала продаж — обычный квартал."""
    gross = {"2025 Q3": 460 * M, "2025 Q4": 500 * M, "2026 Q1": 480 * M}
    plans = contracting.plan_comparison(_summary(gross))
    assert plans["bank_opening"] is None
    assert _row(plans, "2025 Q3")["bank_amount"] == 460 * M
    assert _row(plans, "2025 Q3")["bank_amount_cum"] == 460 * M


def test_the_conclusion_compares_the_line_that_is_drawn() -> None:
    summary = _summary()
    summary["plans"] = contracting.plan_comparison(summary)
    text = contracting.conclusions(summary)["bank"]
    # Общие кварталы — 2026 Q2 и Q3 (Q1 — остаток): 810 факт против 888,9 банка.
    assert text.startswith("По 2 общим кварталам факт ниже плана банка на 78,9 млн ₽."), text
    assert "остаток на дату модели" in text
    # Накопленным на 2026 Q3: 2 280 против 2 368,9.
    assert "Накопленным итогом на 2026 Q3 факт ниже плана банка на 88,9 млн ₽" in text


def test_the_page_shows_the_opening_apart_and_switches_to_accumulated(tmp_path) -> None:
    pw = pytest.importorskip("playwright.sync_api")
    import browser_launch

    from market_search.cabinet import cabinet_page
    from test_the_sales_report_survives_a_full_project import full_summary

    got = full_summary()
    got["plans"] = contracting.plan_comparison(_summary())
    body = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "cabinet.html"
    file.write_text(body, encoding="utf-8")

    read = """()=>{
      const box=document.getElementById('planschart');
      const rows=[...box.querySelectorAll('details table tr')].map(
        tr=>[...tr.children].map(td=>td.textContent.trim()));
      return {rows, opening:!!box.querySelector('[data-bank-opening]'),
              text:box.textContent}}"""
    errors: list[str] = []
    with pw.sync_playwright() as play:
        try:
            browser = browser_launch.launch(play)
        except Exception as exc:  # образ без Chromium — не поломка кабинета
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            tab.on("pageerror", lambda e: errors.append(str(e)))
            tab.goto(file.as_uri())
            tab.evaluate("(d)=>showSales(d)", got)
            quarterly = tab.evaluate(read)
            tab.click("#sb-plan button[data-basis='cum']")
            accumulated = tab.evaluate(read)
            pressed = tab.evaluate(
                "()=>document.querySelector(\"#sb-plan button[data-basis='cum']\").classList.contains('on')")
        finally:
            browser.close()

    assert not errors, errors[:2]
    q1 = next(r for r in quarterly["rows"] if r and r[0] == "2026 Q1")
    assert q1[3] == "—", f"остаток банка стоит в квартальной таблице: {q1}"
    assert quarterly["opening"], "остаток банка не показан отдельно"
    assert "1 480" in quarterly["text"].replace(" ", " ")

    q3 = next(r for r in accumulated["rows"] if r and r[0].startswith("2026 Q3"))
    cells = [c.replace(" ", " ") for c in q3]
    assert cells[1] == "2 280,0 млн ₽" and cells[3] == "2 368,9 млн ₽", cells
    assert not accumulated["opening"], "накопленным итогом остаток — часть линии"
    assert "накопленным итогом" in accumulated["text"]
    assert pressed
