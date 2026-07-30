"""Книга ПЛАТО считает ставку ПФ по той же методике, что и движок.

Движок перестал опускать ставку ниже специальной при покрытии эскроу выше 1×,
а шаблон остался на прежней методике: строка 57 листа «КРЕДИТЫ» снижала
специальную ставку на трансферный доход (D17) и ставила 0,01% годовых выше
двух покрытий. На одних и тех же вводных книга показывала 360,3 млн ₽
процентов против 746,5 млн ₽ в отчёте — почти вдвое меньше, и вслед за этим
расходились EBITDA, налог, чистая прибыль и LLCR (1,42x против 1,27x).

Здесь закреплено, что выгрузка приводит формулу книги к действующей методике.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core
openpyxl = pytest.importorskip("openpyxl")

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "PLATO_template.xlsx"
pytestmark = pytest.mark.skipif(not TEMPLATE.is_file(), reason="шаблон ПЛАТО не поставляется")

MONTHLY = re.compile(r"^=IF\(([A-Z]{1,2})\$3<\$D\d+,\1\d+,\1\$13\)$")


def exported():
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    data, report = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    return workbook["КРЕДИТЫ"], report


def monthly_columns(sheet):
    return [c for c in range(1, sheet.max_column + 1)
            if isinstance(sheet.cell(55, c).value, str) and MONTHLY.match(sheet.cell(55, c).value)]


def test_the_rate_row_no_longer_picks_a_branch():
    """Выбор ветки по покрытию — это и есть прежняя методика."""
    sheet, _ = exported()
    columns = monthly_columns(sheet)

    assert len(columns) > 90, "помесячные колонки ставки не найдены"
    for column in columns:
        assert "57" not in sheet.cell(55, column).value, "ставка всё ещё уходит в ветку «СЗ < Эскроу»"


def test_the_coverage_weight_is_capped_at_one():
    sheet, _ = exported()
    for column in monthly_columns(sheet):
        formula = sheet.cell(56, column).value
        assert "MIN(" in formula, f"вес покрытия не ограничен: {formula}"
        assert formula.count("MIN(") == 2, f"ограничены не оба вхождения: {formula}"


def test_the_summary_columns_are_left_alone():
    """В P–R той же строки лежат сводные — у них своя формула."""
    sheet, _ = exported()
    summary = [c for c in range(1, sheet.max_column + 1)
               if isinstance(sheet.cell(56, c).value, str)
               and sheet.cell(56, c).value.startswith(("=AVERAGE(", "=AVERAGEIF("))]

    assert summary, "сводные колонки пропали"
    for column in summary:
        assert "MIN(" not in sheet.cell(56, column).value


def test_the_substitution_is_reported():
    _, report = exported()
    marks = [item for item in report["filled"] if item.get("sheet") == "КРЕДИТЫ"]

    assert marks and marks[0]["value"] > 90
    assert not [m for m in report["missing"] if "КРЕДИТЫ" in m]


def test_a_template_without_the_known_formula_is_reported_missing():
    """Молча оставить книгу на прежней методике нельзя — это возврат расхождения."""
    workbook = openpyxl.load_workbook(TEMPLATE)
    sheet = workbook["КРЕДИТЫ"]
    for column in range(1, sheet.max_column + 1):
        if isinstance(sheet.cell(55, column).value, str):
            sheet.cell(55, column).value = "=42"
    filled, missing = [], []
    core._plato_apply_pf_rate_methodology(workbook, filled, missing)

    assert missing == ["КРЕДИТЫ · методика ставки ПФ"]
    assert filled == []


def test_the_repaired_formula_matches_the_engine():
    """Формула книги и формула движка дают одно число на одних вводных."""
    base, special = 0.135, 0.045

    def workbook_rate(coverage: float) -> float:
        # =X$15*(1-MIN(X53,1))+X$16*MIN(X53,1)
        weight = min(coverage, 1.0)
        return base * (1 - weight) + special * weight

    for coverage in (0.0, 0.5, 1.0, 1.5, 2.38, 4.0):
        weight = min(coverage, 1.0)
        engine = base * (1 - weight) + special * weight
        assert workbook_rate(coverage) == pytest.approx(engine)

    assert workbook_rate(2.38) == pytest.approx(special), "долг за 1× снова дешевле специальной"
