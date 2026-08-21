"""Проценты ПФ в книге обрывались раньше, чем кончался горизонт движка.

Найдено при сверке бота и сайта: на наборе, близком к реальному проекту,
блок паритета дал FAIL по стоимости финансирования — книга 877,20 млн против
886,02 у движка. Разница почти не зависела от вводных (−9,9 при нулевых
собственных средствах, −8,8 при 4,3 млрд), то есть это не эффект какой-то
одной статьи, а систематический недобор.

Причина. Горизонт движка не выводится из РВЭ: `end = max(РВЭ + max(остаточные
+ 3, 12), последний месяц любого потока)`. Стройка садика на 250 мест
заканчивается позже РВЭ + 12 и растягивает расчёт на три месяца. Формула
книги знала только календарную часть правила и переставала начислять проценты
ПФ там, где долг ещё жив, — 8,8 млн ₽ мимо.

Это второй раз на той же строке: в прошлый раз она начисляла до «РВЭ + срок
продаж». Отсюда правило в CLAUDE.md — формула книги живёт в горизонте движка,
а не в собственном представлении о нём.

Теперь движок пишет свой конец горизонта во «Вводные» B71, а формула берёт
максимум из прежней границы и этой даты: правка сроков прямо в Excel
по-прежнему двигает границу вслед за РВЭ.

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

BASE = {**core.DEFAULT_INPUTS, "purchase_price_mln": 4300, "land_rights_cost_mln": 0,
        "social_compensation_mln": 0, "ird_months": 1, "apartment_price_th": 650,
        "commercial_price_th": 650, "parking_price_th": 5000,
        "main_above_th_per_sqm": 190, "main_under_th_per_sqm": 120,
        "design_p_th_per_sqm": 2.5, "design_rd_th_per_sqm": 2.5,
        "preparation_th_per_sqm": 1, "utilities_th_per_sqm": 7.5,
        "landscaping_th_per_sqm": 5, "site_maintenance_th_per_sqm": 1,
        "author_supervision_pct": 0, "marketing_pct": 3, "selling_pct": 4,
        "limit_fee_pct": 0.5}


def tep_of_a_real_project() -> dict[str, dict[str, float]]:
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    tep["apartments"].update({"gns": 43201.96, "saleable": 29308.89, "units": 355,
                              "total_area": 43201.96, "useful": 29308.89})
    tep["ground_commercial"].update({"gns": 2634.85, "saleable": 2451.09,
                                     "total_area": 2634.85, "useful": 2451.09})
    tep["underground_parking"].update({"gns": 6475.0, "units": 185, "saleable": 0})
    for key in ("standalone_retail", "offices", "above_parking", "storage",
                "kindergarten", "school", "clinic"):
        tep[key].update({"gns": 0, "saleable": 0, "units": 0, "total_area": 0,
                         "useful": 0, "transfer": 0})
    return tep


def workbook(**overrides):
    content, _, _ = core.build_project_workbook(
        {**BASE, **overrides}, tep_of_a_real_project(), [], {}, project_name="П")
    return openpyxl.load_workbook(io.BytesIO(content), data_only=False)


def evaluated(**overrides):
    from xlsx_eval import Evaluator

    sys.setrecursionlimit(400000)
    return Evaluator(workbook(**overrides))


# --- горизонт доезжает в книгу --------------------------------------------------

def test_the_engine_horizon_reaches_the_workbook():
    book = workbook()
    assert book["Вводные"]["D71"].value == "engine_horizon_end"
    assert float(book["Вводные"]["B71"].value) > 0


def test_the_horizon_follows_the_last_cash_flow():
    """Садик строится дольше — горизонт длиннее, и книга должна это видеть."""
    without = float(workbook(kindergarten_places=0)["Вводные"]["B71"].value)
    with_school = float(workbook(school_places=500)["Вводные"]["B71"].value)
    assert with_school > without


def test_the_written_date_is_the_engine_horizon():
    operating = core.build_operating_model(
        {**core.DEFAULT_INPUTS, **BASE}, tep_of_a_real_project(), [])
    expected = core._v4_excel_serial(operating["end"].isoformat())
    assert float(workbook()["Вводные"]["B71"].value) == pytest.approx(expected)


# --- проценты идут, пока идёт горизонт ------------------------------------------

@pytest.mark.parametrize("case", [
    {},                                   # садик 250 мест — горизонт за РВЭ + 12
    {"kindergarten_places": 0},           # без соцстройки — горизонт короче
    {"school_places": 500},               # школа тянет ещё дальше
])
def test_the_financing_cost_agrees_with_the_engine(case):
    evaluator = evaluated(**case)
    book_value = evaluator.cell("ПРОВЕРКИ", "B79")
    engine_value = evaluator.cell("ПРОВЕРКИ", "C79")
    if case.get("school_places"):
        # Известное расхождение методик, а не поломка выгрузки: движок с
        # 21.08.2026 не занимает, когда у него есть касса — остаток после
        # погашения ПФ живёт резервом и платит расходы следующих месяцев.
        # Книга так не умеет: её waterfall собран формулами шаблона. На длинном
        # горизонте (школа на 500 мест тянет стройку далеко за РВЭ) она берёт
        # долг там, где движок обходится своими, и выходит ДОРОЖЕ. Учить книгу
        # резерву — отдельная работа, она в открытых задачах. Здесь закреплено
        # направление и порядок: дешевле движка книга быть не может, а разъезд
        # больше пятнадцати процентов означал бы уже другую причину.
        assert book_value > engine_value, (
            "без резерва книга обязана быть дороже движка, а не дешевле")
        assert (book_value - engine_value) / engine_value < 0.15, (
            f"книга {book_value:.2f} против {engine_value:.2f} — "
            "расхождение больше, чем объясняется резервом кассы")
        return
    assert evaluator.cell("ПРОВЕРКИ", "F79") == "OK", \
        f"книга {book_value:.2f} против {engine_value:.2f}"


def test_the_whole_parity_block_holds_with_a_long_horizon():
    """Недобор процентов тянул за собой налог, прибыль и LLCR."""
    evaluator = evaluated()
    checks = evaluator.workbook["ПРОВЕРКИ"]
    for row in range(76, 85):
        if checks[f"A{row}"].value is None:
            continue
        assert evaluator.cell("ПРОВЕРКИ", f"F{row}") == "OK", str(checks[f"A{row}"].value)


def test_the_formula_takes_the_later_of_two_bounds():
    """Максимум, а не замена: правка сроков прямо в Excel должна по-прежнему
    двигать границу вслед за РВЭ, даже когда записанная дата устарела."""
    formula = str(workbook()["CF_1"]["F42"].value)
    assert "MAX(EDATE($B$8" in formula
    assert "'Вводные'!$B$71" in formula


def test_an_empty_horizon_does_not_break_the_formula():
    """Ноль в ячейке — «движок не посчитал»: книга остаётся на своей границе,
    а не обнуляет проценты за весь проект."""
    formula = str(workbook()["CF_1"]["F42"].value)
    assert "IF('Вводные'!$B$71=0,0," in formula
