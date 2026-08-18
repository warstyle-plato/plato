"""Денежную компенсацию за соцобъекты финансирует БРИДЖ.

Компенсация — условие получения РнС, и банк держит её в лимите БРИДЖа наравне
с покупкой и проектированием (`main_legacy.py`, calculated_bridge_limit). Значит
и платится она в период доступности БРИДЖа: после РнС линия рефинансирована в
ПФ, платить ею нечего. Решение владельца, 18.08.2026: «верно как банк».

До этого стороны считали по-разному и обе молча. Движок платил строго в дату из
вводных; книга — за месяц до РнС своей формулой (`Вводные!B18`), а введённую
дату не видела вовсе: поля не было в карте записи — тот самый случай из правил
проекта, когда ячейка остаётся мусором из шаблона. Пока умолчание совпадало с
«месяцем до РнС», обе стороны сходились случайно. Стоило срокам проекта
разъехаться с датой — и пик БРИДЖа расходился ровно на сумму компенсации:
4712,5 млн в книге против 4132,8 у движка, а следом стоимость финансирования и
чистая прибыль.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import main_legacy as core  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

# РнС = 2027-01 + 18 = 2028-07; бридж-период кончается 2028-06.
BASE = {**core.DEFAULT_INPUTS, "purchase_price_mln": 700, "land_rights_cost_mln": 0,
        "project_start": "2027-01-01", "ird_months": 18, "construction_months": 24,
        "social_mode": "Денежная компенсация", "social_compensation_mln": 580.668,
        "kindergarten_places": 0, "school_places": 0, "clinic_capacity": 0}
PERMIT = date(2028, 7, 1)
LAST_BRIDGE_MONTH = date(2028, 6, 1)


def engine(**overrides):
    return core.calculate(core.CalcRequest(
        inputs={**BASE, **overrides}, tep=core.TEP_DEFAULT, rates=[]))


def workbook(**overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, core.TEP_DEFAULT, [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


# --- методика ---------------------------------------------------------------------

def test_a_date_beyond_the_bridge_moves_back_to_it():
    """Платить после РнС нечем: БРИДЖ к этому месяцу уже рефинансирован."""
    assert core.social_cash_payment_date(
        {"social_comp_date": "2028-12-01"}, PERMIT) == LAST_BRIDGE_MONTH


def test_an_earlier_date_is_respected():
    """Компенсацию платят и раньше — при подписании договора о развитии,
    задолго до разрешения. Это дата обязательства, и её не двигают."""
    assert core.social_cash_payment_date(
        {"social_comp_date": "2027-06-01"}, PERMIT) == date(2027, 6, 1)


@pytest.mark.parametrize("raw", ["", None, "не дата"])
def test_a_missing_date_falls_back_to_the_bridge_period(raw):
    """Пустое поле — не ноль и не сегодня: платёж всё равно в бридж-периоде."""
    assert core.social_cash_payment_date({"social_comp_date": raw}, PERMIT) == LAST_BRIDGE_MONTH


# --- движок -----------------------------------------------------------------------

def test_the_bridge_carries_the_compensation_whatever_the_date():
    """Пик БРИДЖа не зависит от того, поставили дату до РнС или после: и там и
    там компенсацию несёт БРИДЖ. Прежде поздняя дата уводила её в ПФ и роняла
    пик ровно на сумму компенсации."""
    late = engine(social_comp_date="2028-12-01")["finance"]["peak_bridge"]
    on_time = engine(social_comp_date="2028-06-01")["finance"]["peak_bridge"]
    assert late == pytest.approx(on_time, rel=1e-9)


def test_the_compensation_is_inside_the_bridge_peak():
    """Контроль величины: без компенсации пик ниже ровно на неё."""
    with_cash = engine(social_comp_date="2028-12-01")["finance"]["peak_bridge"]
    without = engine(social_comp_date="2028-12-01",
                     social_compensation_mln=0)["finance"]["peak_bridge"]
    assert (with_cash - without) / 1e6 == pytest.approx(BASE["social_compensation_mln"], abs=1.0)


def test_the_payment_date_is_reported():
    """Перенос обязан быть видимым: иначе о нём узнают по пику долга."""
    assert engine(social_comp_date="2028-12-01")["dates"]["social_cash"] == "2028-06-01"
    assert engine(social_comp_date="2027-06-01")["dates"]["social_cash"] == "2027-06-01"


# --- книга ------------------------------------------------------------------------

def test_the_workbook_gets_the_same_date():
    """Ячейка подписана ключом движка, а жила на формуле шаблона. Пока дата
    умолчания совпадала с «месяцем до РнС», это не было видно."""
    cell = workbook(social_comp_date="2027-06-01")["Вводные"]["B18"]
    assert getattr(cell.value, "date", lambda: cell.value)() == date(2027, 6, 1)


def test_the_workbook_moves_a_late_date_the_same_way():
    cell = workbook(social_comp_date="2028-12-01")["Вводные"]["B18"]
    assert getattr(cell.value, "date", lambda: cell.value)() == date(2028, 6, 1)


def test_the_workbook_peak_agrees_with_the_engine():
    """Та самая проверка, которой не было: пик БРИДЖа книги против движка на
    дате, выходящей за бридж-период."""
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    result = engine(social_comp_date="2028-12-01")
    hints = {
        "pf_limit_by_phase": [float(result["finance"].get("pf_limit", 0.0)) / 1e6],
        "bridge_peak_by_phase": [float(result["finance"].get("peak_bridge", 0.0)) / 1e6],
        "parity": core._v4_parity_targets(result),
    }
    content, _, _ = core.build_project_workbook(
        {**BASE, "social_comp_date": "2028-12-01"}, core.TEP_DEFAULT, [], {},
        project_name="П", finance_hints=hints)
    book = Evaluator(openpyxl.load_workbook(io.BytesIO(content), data_only=False))
    assert float(book.cell("ПРОВЕРКИ", "B83")) == pytest.approx(
        result["finance"]["peak_bridge"] / 1e6, abs=5.0)


# --- совмещённый режим ------------------------------------------------------------

def test_the_combined_mode_moves_its_cash_part_too():
    """Проект и строит, и платит: денежная часть — то же обязательство и тот же
    бридж-период, а книга разносит её отдельной строкой графика."""
    late = engine(social_mode=core.SOCIAL_MODE_BOTH, kindergarten_places=250,
                  social_comp_date="2028-12-01")["dates"]["social_cash"]
    assert late == "2028-06-01"
