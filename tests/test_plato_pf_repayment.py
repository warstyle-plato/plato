"""Погашение ПФ считается формулой, а не берётся из листа «факт».

Строка 61 листа «КРЕДИТЫ» в первых двух месяцах тянула погашение из «факта» —
фактических данных действующего проекта. На инвестиционном анализе их нет,
лист пуст, и долг только накапливался: 1,83 → 7,94 млрд ₽ за двадцать четыре
месяца, ни разу не уменьшившись, при доступных к концу 9,56 млрд ₽.

Формула не выдумана: в остальных колонках она уже живая, первые две
приводятся к тому же виду. Модель остаётся моделью — аналитик меняет цены или
сроки, и погашение пересчитывается само.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PLATO_template.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон ПЛАТО не поставляется")


def credits_sheet():
    data, report = core.fill_plato_template(dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT,
                                            project_name="Проверка")
    return openpyxl.load_workbook(io.BytesIO(data))["КРЕДИТЫ"], report


def test_the_fact_sheet_is_no_longer_the_source():
    sheet, _ = credits_sheet()
    left = [c for c in range(1, sheet.max_column + 1)
            if isinstance(sheet.cell(61, c).value, str) and "факт!" in sheet.cell(61, c).value]

    assert left == [], "погашение всё ещё берётся из листа «факт»"


def test_the_repayment_stays_a_formula():
    """Хардкод значений превратил бы модель в отчёт."""
    sheet, _ = credits_sheet()
    monthly = [sheet.cell(61, c).value for c in range(1, sheet.max_column + 1)
               if isinstance(sheet.cell(61, c).value, str)
               and sheet.cell(61, c).value.startswith("=-IF(")]

    assert len(monthly) > 90, "помесячные формулы погашения пропали"


def test_all_monthly_columns_share_one_rule():
    """Две редакции формулы в одной строке — два разных правила погашения."""
    sheet, _ = credits_sheet()
    monthly = [sheet.cell(61, c).value for c in range(1, sheet.max_column + 1)
               if isinstance(sheet.cell(61, c).value, str) and sheet.cell(61, c).value.startswith("=-IF(")]

    assert len(monthly) > 90
    # Одна редакция на все месяцы: отличаются только буквы колонок.
    import re
    shapes = {re.sub(r"[A-Z]{1,2}(?=\d|\$)", "@", formula) for formula in monthly}
    assert len(shapes) == 1, sorted(shapes)[:2]


def test_the_first_month_has_no_circular_reference():
    """Накопительный диапазон в первой колонке вырождается в ссылку на себя."""
    sheet, _ = credits_sheet()
    first = next(c for c in range(1, sheet.max_column + 1)
                 if isinstance(sheet.cell(61, c).value, (int, float)))

    assert sheet.cell(61, first).value == 0
    following = sheet.cell(61, first + 1).value
    assert isinstance(following, str) and following.startswith("=-IF(")


def test_the_substitution_is_reported():
    _, report = credits_sheet()
    marks = [item for item in report["filled"]
             if item.get("sheet") == "КРЕДИТЫ" and item.get("row") == 61]

    assert marks and marks[0]["value"] >= 2
    assert not [m for m in report["missing"] if "погашение" in m]
