"""Техзаказчик слит с управлением, подземные СМР — с наземными.

В книге одна строка «Управление проектом» и одна «Основное строительство ЖК».
Движок ведёт управление, технического заказчика и авторский надзор порознь, а
СМР — отдельно по наземной и подземной части. Раскладывать их в книге некуда,
и пока передавалась только своя доля, книга считала управление своими 5%
(291,9 млн ₽ против 523,1) и знала лишь наземную часть.

Передаётся то же самое одним числом: процент, дающий сумму трёх статей на базе
книги, и ставка, дающая сумму обеих частей на всём ГНС.

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


def exported(**overrides):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700)
    inputs.update(overrides)
    data, report = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    sheet = openpyxl.load_workbook(io.BytesIO(data))["Вводные"]
    # Подпись в колонке B, значения сценариев в D–F. Колонка G не читается:
    # там формула INDEX, выбирающая сценарий, и трогать её нельзя.
    wanted = {"Управление проектом": "project_management_pct",
              "Основное строительство ЖК": "main_above_th_per_sqm"}
    values = {}
    for row in range(1, sheet.max_row + 1):
        label = str(sheet.cell(row, 2).value or "").strip()
        if label in wanted and wanted[label] not in values:
            values[wanted[label]] = sheet.cell(row, 4).value
    return values, report, inputs


def engine(inputs):
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=core.TEP_DEFAULT, rates=[]))
    return result["capex"]


def test_management_carries_the_technical_supervision():
    values, _, inputs = exported()
    capex = engine(inputs)
    base = sum(float(capex.get(k) or 0) for k in (
        "ird", "design_p", "design_rd", "preparation", "main_above", "main_under",
        "gc_fee", "utilities", "landscaping", "commissioning", "site_maintenance",
        "reserve", "social"))
    merged = sum(float(capex.get(k) or 0) for k in (
        "project_management", "technical_supervision", "author_supervision"))

    assert values["project_management_pct"] == pytest.approx(merged / base, abs=1e-6)
    assert values["project_management_pct"] > inputs["project_management_pct"] / 100, (
        "техзаказчик не добавился к управлению")


def test_the_rate_covers_both_construction_parts():
    """Ставки наземной и подземной части взвешиваются по ГНС."""
    values, _, inputs = exported(main_above_th_per_sqm=190, main_under_th_per_sqm=120)
    capex = engine(inputs)
    gns = sum(float((core.TEP_DEFAULT.get(k) or {}).get("gns") or 0) for k in core.TEP_DEFAULT)
    expected = (float(capex["main_above"]) + float(capex["main_under"])) / gns / 1000

    assert values["main_above_th_per_sqm"] == pytest.approx(expected, abs=1e-6)
    assert 120 < values["main_above_th_per_sqm"] < 190, "ставка не взвешена"


def test_equal_rates_stay_the_same():
    """Если обе части по одной ставке, взвешивание её не двигает."""
    values, _, _ = exported(main_above_th_per_sqm=190, main_under_th_per_sqm=190)

    assert values["main_above_th_per_sqm"] == pytest.approx(190, abs=0.01)


def test_the_scenario_switch_survives():
    """Колонка G — переключатель сценария, её запись значением убивает."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["purchase_price_mln"] = 700
    data, _ = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    sheet = openpyxl.load_workbook(io.BytesIO(data))["Вводные"]

    for row in range(1, sheet.max_row + 1):
        if str(sheet.cell(row, 2).value or "").strip() in (
                "Управление проектом", "Основное строительство ЖК"):
            assert str(sheet.cell(row, 7).value or "").startswith("=INDEX"), f"строка {row}"


def test_both_substitutions_are_reported():
    _, report, _ = exported()
    labels = [i["label"] for i in report["filled"] if i.get("sheet") == "Вводные"]

    assert any("техзаказчиком" in text for text in labels)
    assert any("подземной" in text for text in labels)


def test_a_failure_is_reported_not_swallowed():
    """Молча оставить книге её собственные проценты нельзя."""
    source = Path(core.__file__).read_text(encoding="utf-8")
    start = source.index("_plato_merge_management_and_smr(sheet")

    assert "missing.append" in source[start:start + 400]
