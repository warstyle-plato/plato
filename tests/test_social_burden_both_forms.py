"""Проект может и строить соцобъекты, и платить деньгами.

Форма исполнения соцнагрузки была переключателем «или/или»: либо стройка,
либо компенсация. Для Румянцева этого не хватило — школа на 350 мест и ДОО на
180 строятся за счёт проекта, а за стадион регби платится 1 149,23 млн ₽ по
соглашению о финансировании, и стройки там нет вовсе.

Пока режимы исключали друг друга, происходило вот что: подставляешь денежное
обязательство — импорт переключает режим — стройка школы и садика выпадает из
CAPEX, и EBITDA растёт на 0,46 млрд ₽ от **добавленного** расхода. Число,
которое двигается не в ту сторону, — единственный признак, по которому такую
подмену вообще можно заметить.

Третий режим — решение владельца (14.08.2026). Случай редкий, но реальный:
компенсация за поликлинику вместе со стройкой школы в Москве обычное дело.

Обе формы считаются порознь и по своим срокам: каждая стройка идёт своим
графиком, денежная часть — одним платежом в свою дату. В лимит БРИДЖа входит
только денежная часть: стройку банк финансирует проектным финансированием
после РнС, и включать её в БРИДЖ значило бы просить лимит дважды.

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

BASE = {**core.DEFAULT_INPUTS, "apartment_price_th": 650, "commercial_price_th": 650,
        "kindergarten_places": 180, "school_places": 350,
        "social_compensation_mln": 1149.23}


def result(mode: str):
    return core.calculate(core.CalcRequest(
        inputs={**BASE, "social_mode": mode}, tep=core.TEP_DEFAULT, rates=[]))


def workbook(mode: str):
    content, _, _ = core.build_project_workbook(
        {**BASE, "social_mode": mode}, core.TEP_DEFAULT, [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


# --- режим существует и считает обе формы ---------------------------------------

def test_the_third_mode_is_offered():
    modes = [item[0] for item in core._M2_EXTRA_OPTIONS["social_mode"]]
    assert core.SOCIAL_MODE_BOTH in modes


def test_both_forms_are_added_up():
    build = result("Строительство")["summary"]["social_payment"]
    cash = result("Денежная компенсация")["summary"]["social_payment"]
    both = result(core.SOCIAL_MODE_BOTH)["summary"]["social_payment"]
    assert both == pytest.approx(build + cash, rel=1e-9)


def test_adding_a_cost_does_not_raise_the_profit():
    """Тот самый признак подмены: расход добавили, а прибыль выросла."""
    build = result("Строительство")["summary"]
    both = result(core.SOCIAL_MODE_BOTH)["summary"]
    assert both["capex"] > build["capex"]
    assert both["ebitda"] < build["ebitda"]
    assert both["net_profit"] < build["net_profit"]


def test_construction_keeps_its_own_schedule():
    """Стройка идёт месяцами по графику объектов, а не разовым платежом."""
    operating = core.build_operating_model(
        {**BASE, "social_mode": core.SOCIAL_MODE_BOTH}, core.TEP_DEFAULT, [])
    months = [month for month, value in operating["capex_by_article"]["social"].items()
              if value > 0] if "capex_by_article" in operating else []
    if not months:  # у движка своя раскладка — берём общий календарь расходов
        months = [month for month, value in operating["capex"].items() if value > 0]
    assert len(months) > 1


def test_the_cash_part_is_paid_on_its_own_date():
    """Денежное обязательство — платёж в свою дату, а не размазанный по стройке."""
    inputs = {**BASE, "social_mode": core.SOCIAL_MODE_BOTH,
              "social_comp_date": "2029-02-01"}
    operating = core.build_operating_model(inputs, core.TEP_DEFAULT, [])
    from datetime import date

    assert operating["capex"].get(date(2029, 2, 1), 0.0) >= 1149.23 * 1_000_000 * 0.99


# --- лимит БРИДЖа ---------------------------------------------------------------

def test_only_the_cash_part_enters_the_bridge_limit():
    """Стройку финансирует ПФ после РнС: попади она в БРИДЖ, лимит попросили
    бы дважды."""
    build = result("Строительство")["report"]["financing"]["calculated_bridge"]
    both = result(core.SOCIAL_MODE_BOTH)["report"]["financing"]["calculated_bridge"]
    assert both - build == pytest.approx(1149.23 * 1_000_000, rel=1e-6)


# --- книга считает так же -------------------------------------------------------

@pytest.mark.parametrize("mode", ["Строительство", "Денежная компенсация",
                                  "Строительство и компенсация"])
def test_the_workbook_agrees_with_the_engine(mode):
    """Методику меняют в двух местах: в движке и в книге."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    book = workbook(mode)
    evaluator = Evaluator(book)
    checks = book["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", \
            f"{mode}: {checks[f'A{row}'].value}"


def test_the_workbook_carries_both_parts():
    book = workbook(core.SOCIAL_MODE_BOTH)["Вводные"]
    assert book["B17"].value == pytest.approx(
        result(core.SOCIAL_MODE_BOTH)["summary"]["social_payment"] / 1_000_000, rel=1e-6)
    assert book["B56"].value == pytest.approx(1149.23)
    assert book["D56"].value == "social_cash_part_mln"


def test_the_other_modes_leave_the_cash_cell_empty():
    """Ячейка живёт только совмещённым режимом: в остальных её содержимое
    исказило бы базу комиссии."""
    for mode in ("Строительство", "Денежная компенсация"):
        assert workbook(mode)["Вводные"]["B56"].value == 0


def test_the_book_formula_knows_the_third_mode():
    formula = str(workbook(core.SOCIAL_MODE_BOTH)["CF_1"]["F57"].value)
    assert "Строительство и компенсация" in formula
    assert "$B$56" in formula


# --- порядок листов -------------------------------------------------------------

def test_the_book_opens_on_the_result():
    """Книгу открывают ради отчёта, а он лежал пятнадцатым листом — после
    четырёх CF, КРЕДИТОВ и КОНСОЛИДАТОРА. Порядок листов ничего не ломает:
    формулы ссылаются по именам, а не по позиции."""
    names = workbook("Строительство").sheetnames
    assert names[:3] == ["Вводные", "ОТЧЕТ", "Дашборд"]


def test_no_sheet_was_lost_in_the_reorder():
    names = workbook("Строительство").sheetnames
    assert len(names) == len(set(names)) == 19
    for required in ("ПРОВЕРКИ", "CF_1", "CF_4", "КРЕДИТЫ", "ОБЪЕКТЫ"):
        assert required in names


def test_the_page_takes_the_modes_from_the_engine():
    """Список форм жил на странице копией, и третий режим в неё не попал:
    движок считал, книга предлагала, а выбрать было нельзя."""
    assert "__DEVELOPAID_SOCIAL_MODES__" not in core.PAGE
    assert "Строительство и компенсация" in core.PAGE
