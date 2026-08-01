"""CAPEX соцобъектов при денежной компенсации ссылается на деньги, а не на места.

Формулы G6:G8 листа «ОБЪЕКТЫ КРТ» брали 'Расчет ВРИ (ТЭП)'!D54:D56 и делили на
тысячу. В строках 54–56 лежит мощность — 15 мест, 10, 5, — а деньги ниже, в
84–86. По ДОО вместо 188,4 млн ₽ выходило 0,015: ошибка ссылки на строку, а не
методики.

Подписи «ДОО», «Школа», «Поликлиника» на листе повторяются дважды, поэтому
строки ищутся от заголовка компенсации, а не по первому совпадению.

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


def exported():
    data, report = core.fill_plato_template(dict(core.DEFAULT_INPUTS), core.TEP_DEFAULT,
                                            project_name="Проверка")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    return workbook, report


def money_rows(workbook):
    tep = workbook["Расчет ВРИ (ТЭП)"]
    start = next(r for r in range(1, tep.max_row + 1)
                 if "компенсац" in str(tep.cell(r, 2).value or "").lower())
    return {str(tep.cell(r, 2).value).strip(): r
            for r in range(start + 1, start + 8)
            if str(tep.cell(r, 2).value or "").strip() in ("ДОО", "Школа", "Поликлиника")}


def test_the_links_point_at_the_money_rows():
    workbook, _ = exported()
    rows = money_rows(workbook)
    sheet = workbook["ОБЪЕКТЫ КРТ"]

    for cell, label in ((6, "ДОО"), (7, "Школа"), (8, "Поликлиника")):
        assert f"$D${rows[label]}" in sheet.cell(cell, 7).value, sheet.cell(cell, 7).value


def test_the_thousand_divisor_is_gone():
    """В строках компенсации деньги уже в миллионах."""
    workbook, _ = exported()
    sheet = workbook["ОБЪЕКТЫ КРТ"]

    for row in (6, 7, 8):
        assert "/1000" not in sheet.cell(row, 7).value.replace(" ", "")


def test_the_construction_branch_is_untouched():
    """При строительстве стоимость берётся из наших вводных — её не трогаем."""
    workbook, _ = exported()
    sheet = workbook["ОБЪЕКТЫ КРТ"]

    for row, source in ((6, "$G$88"), (7, "$G$93"), (8, "$G$98")):
        formula = sheet.cell(row, 7).value
        assert formula.startswith('=IF(Вводные!$G$82="Строительство"')
        assert source in formula


def test_it_still_is_a_formula():
    workbook, _ = exported()
    sheet = workbook["ОБЪЕКТЫ КРТ"]

    for row in (6, 7, 8):
        assert str(sheet.cell(row, 7).value).startswith("=")


def test_the_substitution_is_reported():
    _, report = exported()
    marks = [i for i in report["filled"] if i.get("sheet") == "ОБЪЕКТЫ КРТ"]

    assert marks and marks[0]["value"] == 3
    assert not [m for m in report["missing"] if "ОБЪЕКТЫ" in m]
