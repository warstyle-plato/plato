"""Линия ПФ, рассчитавшаяся в РВЭ, после него не кредитует.

На «Нагатино» (четыре очереди, LLCR 1,23x, 35,5 млрд ₽ прибыли) отчёт
называл проект дефолтным на 625 млн ₽ (владелец, 04.09.2026: «в блоке
финансирование написана откровенная ахинея»). 625 млн — последний платёж
рассрочки за покупку («625@54»), июль 2031: РВЭ первой очереди в январе 2031,
остаточные продажи кончились в июне, а платёж выбирался с ПФ — с линии,
которую раскрытый эскроу закрыл полностью полгода назад, — и гасить его было
уже нечем: продаж нет. Правило «закрытая линия не кредитует и не собирает»
было закрыто для переноса долга и не закрыто для линии, рассчитавшейся сама.

Закреплено:
- после РВЭ, когда долг погашен раскрытием целиком, выборок ПФ нет: расход
  платит касса очереди (отток в потоке на капитал), долг на конец — ноль;
- дефолта у проекта нет, оговорка «прибыль бумажная» не появляется;
- сценарий держит платёж ПОСЛЕ конца продаж — иначе он гасился бы продажами
  того же месяца, и ветка не проверялась бы.

Запуск: python3 -m pytest tests/test_a_settled_pf_line_does_not_lend_after_rve.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


@pytest.fixture(scope="module")
def result() -> dict:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000,
                  purchase_price_mln=2000, ird_months=12, construction_months=24,
                  residual_sales_months=6)
    # РнС через 12 мес., РВЭ через 36, продажи кончаются на 42-м; платёж на
    # 46-м месяце (ноябрь 2030) приходит, когда продавать уже нечего.
    inputs["purchase_schedule"] = "1500@0; 500@46"
    return core.calculate(core.CalcRequest(inputs=inputs, tep=copy.deepcopy(core.TEP_DEFAULT)))


LATE_MONTH = "2030-11-01"


def _rows(result: dict) -> list[dict]:
    return result["finance"]["rows"]


def _late_row(result: dict) -> dict:
    return next(r for r in _rows(result) if str(r["month"]) == LATE_MONTH)


def test_the_late_installment_comes_after_the_last_sale(result: dict) -> None:
    """Предохранитель сценария: платёж стоит там, где продаж уже нет."""
    late = _late_row(result)
    assert float(late.get("project_costs") or 0) >= 499e6, late
    assert float(late.get("sales") or 0) == 0, late
    assert result["dates"]["rve"] < LATE_MONTH


def test_the_settled_line_lends_nothing_after_rve(result: dict) -> None:
    fin = result["finance"]
    assert fin["rve_pf_shortfall"] == 0, "сценарий должен рассчитаться в РВЭ целиком"
    rows = _rows(result)
    rve_paid = [r for r in rows if float(r.get("escrow_release") or 0) > 0]
    assert rve_paid, "раскрытия эскроу нет"
    rve_month = str(rve_paid[0]["month"])
    after = [r for r in rows if str(r["month"]) > rve_month]
    assert sum(float(r.get("pf_draw") or 0) for r in after) == 0, "после РВЭ линия выбирает"
    assert fin["ending_pf"] == 0
    assert fin.get("default_date") is None


def test_the_late_installment_is_paid_by_cash(result: dict) -> None:
    months = [str(m) for m in result["monthly"]["months"]]
    equity = result["cashflow"]["equity"]
    assert equity[months.index(LATE_MONTH)] <= -499e6


# --- книга считает так же ------------------------------------------------------

def test_the_workbook_closes_the_settled_line_too():
    """Методику меняют в двух местах: строка 44 книги v4 после РВЭ выбирает
    только там, где долг в РВЭ остался (строка 29 по предыдущие месяцы > 0)."""
    import io

    openpyxl = pytest.importorskip("openpyxl")
    sys.path.insert(0, str(ROOT / "tests"))
    from xlsx_eval import Evaluator

    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(apartment_price_th=650, commercial_price_th=650, parking_price_th=5000,
                  purchase_price_mln=2000, ird_months=12, construction_months=24,
                  residual_sales_months=6, purchase_schedule="1500@0; 500@46")
    content, _, missing = core.build_project_workbook(
        inputs, copy.deepcopy(core.TEP_DEFAULT), [], {}, project_name="П")
    assert not [m for m in missing if "44" in m or "29" in m], missing
    sys.setrecursionlimit(400000)
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    checks = evaluator.workbook["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", (
            str(checks[f"A{row}"].value),
            evaluator.cell("ПРОВЕРКИ", f"B{row}"), evaluator.cell("ПРОВЕРКИ", f"C{row}"))
