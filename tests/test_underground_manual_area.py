"""Подземную площадь можно задать руками, и её никто не затирает.

Норматив 35 м² на место описывает потребность, а реальный подземный этаж
диктуют пятно застройки, рампы и техпомещения — площадь почти всегда
другая. Задать её было негде: и страница (repairParkingFromGlavapu), и
движок принудительно пересчитывали паркинг из импорта ГлавАПУ перед
каждым расчётом, так что любое ручное значение жило до первого пересчёта.

Теперь заданная площадь главнее импорта, количество мест считается от неё
по нормативу, а сам норматив вынесен во вводные. Пока поле пустое, защита
от устаревших значений localStorage работает ровно как раньше.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

_IMPORT = {"normalized": {"parking_permanent": 25, "parking_guest": 3}}


def _calc(inputs_extra: dict):
    inputs = {**core.DEFAULT_INPUTS, **inputs_extra}
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    row = next(r for r in result["tep"]["rows"] if r["key"] == "underground_parking")
    return row


def test_the_import_still_repairs_stale_values_when_no_manual_area():
    """Пустое поле — прежнее поведение: ГлавАПУ чинит устаревший ТЭП."""
    row = _calc({"_glavapu_import": _IMPORT})
    assert row["units"] == pytest.approx(28)
    assert row["gns"] == pytest.approx(28 * 35)


def test_a_manual_area_outranks_the_import():
    """Заданная площадь переживает пересчёт, а места считаются от неё."""
    row = _calc({"_glavapu_import": _IMPORT, "underground_manual_gns_sqm": 1400})
    assert row["gns"] == pytest.approx(1400)
    assert row["total_area"] == pytest.approx(1400)
    assert row["units"] == pytest.approx(40), "1400 ÷ 35 = 40 машино-мест"


def test_the_norm_per_space_is_an_input_not_a_constant():
    """Норматив вынесен во вводные: 30 м² на место дают другое количество."""
    row = _calc({"underground_manual_gns_sqm": 1200,
                 "underground_area_per_space_sqm": 30})
    assert row["units"] == pytest.approx(40), "1200 ÷ 30 = 40"
    row_default = _calc({"underground_manual_gns_sqm": 1200})
    assert row_default["units"] == pytest.approx(34), "1200 ÷ 35 ≈ 34"


def test_a_manual_area_keeps_parking_unsaleable():
    """Подземный паркинг продаётся местами, а не метрами: продаваемая
    площадь остаётся нулевой, иначе выручка задвоится."""
    row = _calc({"underground_manual_gns_sqm": 1400})
    assert row["saleable"] == pytest.approx(0)
    assert row["useful"] == pytest.approx(0)
    assert row["transfer"] == pytest.approx(0)


def test_the_page_offers_both_fields_and_warns_about_the_shortfall():
    page = core.PAGE
    assert "Площадь подземной парковки" in page
    assert "Норматив площади на машино-место" in page
    assert "function undergroundShortfallNote()" in page
    # Места ГлавАПУ — норматив обеспеченности: нехватку человек должен видеть.
    assert "норматив ГлавАПУ" in page
    assert '"underground_manual_gns_sqm": 0' in page


def test_both_default_sets_carry_the_new_inputs():
    """Страница несёт свою копию умолчаний — разъезд копий уже кусал."""
    assert core.DEFAULT_INPUTS["underground_area_per_space_sqm"] == 35
    assert core.DEFAULT_INPUTS["underground_manual_gns_sqm"] == 0
    assert '"underground_area_per_space_sqm": 35' in core.PAGE
