"""Компенсация за социальные объекты уезжает в книгу разложенной по типам.

Калькулятор ГлавАПУ считает её тремя строками — ДОО, школа, поликлиника, — и
импорт их читает. В книгу же уходила только плата за смену ВРИ, а строки
компенсации оставались с числами шаблона: 319,1 + 509,6 + 159,8 = 988,4 млн ₽
вместо 580,7. При денежной форме исполнения книга берёт обременение именно
отсюда, поэтому расходы завышались на 407,7 млн ₽, а следом расходились
прибыль (959,6 против 815,4) и LLCR (1,246x против 1,07x).

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

# Реальный расчёт по 77:09:0004014:13.
GLAVAPU = {
    "social_compensation_kindergarten_mln": 188.414,
    "social_compensation_school_mln": 294.540,
    "social_compensation_clinic_mln": 97.714,
}


def sheet(normalized=GLAVAPU):
    inputs = dict(core.DEFAULT_INPUTS)
    inputs["_glavapu_import"] = {"normalized": dict(normalized)}
    data, report = core.fill_plato_template(inputs, core.TEP_DEFAULT, project_name="Проверка")
    workbook = openpyxl.load_workbook(io.BytesIO(data))
    return workbook["Расчет ВРИ (ТЭП)"], report


def money_rows(ws):
    start = next(r for r in range(1, ws.max_row + 1)
                 if "компенсац" in str(ws.cell(r, 2).value or "").lower())
    found = {}
    for r in range(start + 1, start + 8):
        label = str(ws.cell(r, 2).value or "").strip()
        if label in ("ДОО", "Школа", "Поликлиника"):
            found[label] = ws.cell(r, 4).value
    return found


def test_the_breakdown_reaches_the_workbook():
    ws, _ = sheet()

    assert money_rows(ws) == {
        "ДОО": pytest.approx(188.414),
        "Школа": pytest.approx(294.540),
        "Поликлиника": pytest.approx(97.714),
    }


def test_the_total_matches_the_calculator():
    ws, _ = sheet()

    assert sum(money_rows(ws).values()) == pytest.approx(580.668, abs=0.001)


def test_the_capacity_rows_are_left_alone():
    """Те же подписи есть выше — там количество мест, а не деньги."""
    ws, _ = sheet()
    places = next(r for r in range(1, ws.max_row + 1)
                  if "объектов обслуживания" in str(ws.cell(r, 2).value or "").lower())

    for r in range(places + 1, places + 4):
        value = ws.cell(r, 4).value
        assert value not in (188.414, 294.540, 97.714), "деньги легли в строку мощности"


def test_a_project_without_an_import_is_left_alone():
    ws, report = sheet(normalized={})

    assert not [item for item in report["filled"] if "Компенсация" in str(item.get("label"))]


def test_the_substitution_is_reported():
    _, report = sheet()
    labels = [item["label"] for item in report["filled"] if "Компенсация" in str(item.get("label"))]

    assert labels == ["Компенсация · ДОО", "Компенсация · Школа", "Компенсация · Поликлиника"]
