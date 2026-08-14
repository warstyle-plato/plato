"""Собственные средства до ПФ книга считала банковским долгом.

Владелец включил финансирование за счёт своих денег на этапе БРИДЖа — 3,20
млрд ₽ — и скачал модель. Книга показала пик БРИДЖа 5 007,1 млн против
1 807,2 у движка, пик ПФ 22 091,6 против 18 892,7. Обе разницы — 3 199,9 млн,
то есть ровно внесённая сумма. Дальше механически: +780,0 млн процентов,
−195,0 млн налога, −585,0 млн чистой прибыли, LLCR 1,1436 вместо 1,20.

Причина — та самая, что записана в CLAUDE.md: поля не было в карте записи, и
оно молча осталось нулём из шаблона. Движок тратит свои деньги раньше БРИДЖа
с 6 августа (`main_legacy.py:14681`), книга об этом не знала.

Методика одна на оба: до РнС потребность месяца сначала гасится своими
деньгами, банк добирает остаток. В книге это строки CF_x!56 (расход) и
CF_x!59 (остаток), а «БРИДЖ — выборка» стала «потребность минус свои».

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

BASE = {**core.DEFAULT_INPUTS, "apartment_price_th": 700, "commercial_price_th": 700,
        "parking_price_th": 5000, "purchase_price_mln": 4350,
        "land_rights_cost_mln": 0, "social_compensation_mln": 0, "ird_months": 1}


def workbook(**overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, core.TEP_DEFAULT, [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def evaluated(**overrides):
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(workbook(**overrides))


# --- сумма и доли доезжают ------------------------------------------------------

@pytest.mark.parametrize("amount", [0, 1000, 3200])
def test_the_amount_reaches_the_workbook(amount):
    assert workbook(pre_pf_own_funds_mln=amount)["Вводные"]["B85"].value == amount


def test_the_cell_carries_its_key():
    """По ключу в колонке D книгу читают глазами и сверяют с движком."""
    assert workbook()["Вводные"]["D85"].value == "pre_pf_own_funds_mln"


def test_the_share_defaults_to_the_first_phase():
    """Свои деньги вкладывают на входе — умолчание движка то же, что у покупки.
    Без деления каждая очередь взяла бы всю сумму."""
    book = workbook(pre_pf_own_funds_mln=3200)
    assert [book["Вводные"][f"AI{row}"].value for row in range(88, 92)] == [1.0, 0.0, 0.0, 0.0]


# --- методика книги совпадает с движком ----------------------------------------

@pytest.mark.parametrize("amount", [1000, 3200])
def test_the_workbook_spends_exactly_what_the_engine_spends(amount):
    spent = evaluated(pre_pf_own_funds_mln=amount).cell("CF_1", "B56")
    result = core.calculate(core.CalcRequest(
        inputs={**BASE, "pre_pf_own_funds_mln": amount}, tep=core.TEP_DEFAULT, rates=[]))
    assert spent == pytest.approx(
        result["report"]["financing"]["own_funds"] / 1_000_000, abs=1.0)


def test_own_money_goes_first_and_the_bank_tops_up():
    """Ради чего правка: пик БРИДЖа падает ровно на внесённую сумму."""
    without = evaluated(pre_pf_own_funds_mln=0).cell("ПРОВЕРКИ", "B83")
    with_own = evaluated(pre_pf_own_funds_mln=3200).cell("ПРОВЕРКИ", "B83")
    assert without - with_own == pytest.approx(3200.0, abs=1.0)


def test_the_leftover_never_goes_negative():
    """Своих больше, чем нужно, — банк не нужен, а остаток не уходит в минус."""
    evaluator = evaluated(pre_pf_own_funds_mln=50000)
    assert evaluator.cell("CF_1", "B34") == pytest.approx(0.0, abs=1.0)
    assert evaluator.cell("CF_1", "B59") >= 0.0


def test_the_money_is_spent_only_once():
    """Остаток убывает, а не восстанавливается каждый месяц."""
    evaluator = evaluated(pre_pf_own_funds_mln=1000)
    assert evaluator.cell("CF_1", "B56") == pytest.approx(1000.0, abs=1.0)


def test_the_phases_do_not_each_get_the_whole_sum():
    """Один котёл на проект: без доли каждая очередь профинансировала бы себя
    полностью, и книга «внесла» бы вдвое больше, чем есть."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    phasing = {"mode": "phased", "phase_gap_months": 12, "phases": [
        {"name": "О1", "start_offset_months": 0, "construction_months": 24},
        {"name": "О2", "start_offset_months": 12, "construction_months": 24}]}
    content, _, _ = core.build_project_workbook(
        {**BASE, "pre_pf_own_funds_mln": 3200}, core.TEP_DEFAULT, [], phasing,
        project_name="Очереди")
    evaluator = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    spent = sum(evaluator.cell(sheet, "B56") for sheet in ("CF_1", "CF_2"))
    assert spent == pytest.approx(3200.0, abs=1.0)


# --- паритет книги и движка -----------------------------------------------------

@pytest.mark.parametrize("amount", [0, 3200])
def test_the_parity_block_holds(amount):
    """Тот самый блок, что поймал расхождение и выдал СБОЙ."""
    evaluator = evaluated(pre_pf_own_funds_mln=amount)
    checks = evaluator.workbook["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", str(checks[f"A{row}"].value)


def test_the_roll_forward_still_balances():
    """Выборка БРИДЖа изменилась — контроль фондирования обязан сойтись."""
    evaluator = evaluated(pre_pf_own_funds_mln=3200)
    for row in (60, 61, 62, 63):
        assert abs(evaluator.cell("CF_1", f"B{row}")) < 0.01, f"CF_1 строка {row}"
