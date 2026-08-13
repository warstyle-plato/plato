"""Подземный паркинг задаётся решением проекта, а не только нормативом.

ГлавАПУ даёт норматив обеспеченности — минимум, который обязан построить
застройщик. Девелопер решает иначе: нужно 50 мест на продажу против 28 по
нормативу — значит строится ещё подземный этаж, и площадь 50 × 35 = 1 750 м²,
а не 980. Норматив 35 м²/место — гросс: рампы, проезды и техпомещения уже
внутри, поэтому пересчёт мест в площадь прямой.

Задать это было негде: и страница (repairParkingFromGlavapu), и движок перед
каждым расчётом принудительно пересчитывали паркинг из импорта ГлавАПУ, и
любое ручное значение жило до первого пересчёта. Теперь ведущее — количество
мест, площадь производная; площадь можно задать и прямо, когда она известна
из проекта. Пока поля пустые, защита от устаревших значений localStorage
работает ровно как раньше.

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


def test_the_project_decision_outranks_the_norm():
    """Сценарий владельца: норматив ГлавАПУ 28 мест, проекту нужно 50 —
    значит ещё этаж, и площадь 1 750 м², а не 980."""
    row = _calc({"_glavapu_import": _IMPORT, "underground_manual_spaces": 50})
    assert row["units"] == pytest.approx(50)
    assert row["gns"] == pytest.approx(1750), "50 × 35, а не 28 × 35"
    assert row["total_area"] == pytest.approx(1750)


def test_a_known_area_outranks_the_import_too():
    """Площадь из проекта задаётся прямо, места считаются от неё."""
    row = _calc({"_glavapu_import": _IMPORT, "underground_manual_gns_sqm": 1400})
    assert row["gns"] == pytest.approx(1400)
    assert row["units"] == pytest.approx(40), "1400 ÷ 35 = 40 машино-мест"


def test_spaces_and_area_can_be_set_together():
    """Заданы оба — берём как есть: человек знает свой проект, и подгонять
    одно под другое означало бы спорить с ним о его же цифрах."""
    row = _calc({"underground_manual_spaces": 50, "underground_manual_gns_sqm": 1900})
    assert row["units"] == pytest.approx(50)
    assert row["gns"] == pytest.approx(1900)


def test_the_norm_per_space_is_an_input_not_a_constant():
    """Норматив вынесен во вводные: 30 м² на место дают другое количество."""
    row = _calc({"underground_manual_gns_sqm": 1200,
                 "underground_area_per_space_sqm": 30})
    assert row["units"] == pytest.approx(40), "1200 ÷ 30 = 40"
    row_default = _calc({"underground_manual_gns_sqm": 1200})
    assert row_default["units"] == pytest.approx(34), "1200 ÷ 35 ≈ 34"


def test_the_norm_is_gross_so_spaces_convert_directly():
    """35 м² — гросс с рампами и проездами: 50 мест это ровно 1 750 м²,
    накидывать сверху на общие зоны не нужно."""
    row = _calc({"underground_manual_spaces": 50})
    assert row["gns"] == pytest.approx(50 * 35)


def test_a_manual_area_keeps_parking_unsaleable():
    """Подземный паркинг продаётся местами, а не метрами: продаваемая
    площадь остаётся нулевой, иначе выручка задвоится."""
    row = _calc({"underground_manual_gns_sqm": 1400})
    assert row["saleable"] == pytest.approx(0)
    assert row["useful"] == pytest.approx(0)
    assert row["transfer"] == pytest.approx(0)


def test_the_page_offers_both_fields_and_warns_about_the_shortfall():
    page = core.PAGE
    assert "Машино-места — решение проекта" in page
    assert "Площадь подземной парковки" in page
    assert "Норматив площади на машино-место" in page
    assert "function undergroundShortfallNote()" in page
    # Места ГлавАПУ — норматив обеспеченности: нехватку человек должен видеть.
    assert "норматив обеспеченности ГлавАПУ" in page
    assert '"underground_manual_gns_sqm": 0' in page


def test_both_default_sets_carry_the_new_inputs():
    """Страница несёт свою копию умолчаний — разъезд копий уже кусал."""
    assert core.DEFAULT_INPUTS["underground_area_per_space_sqm"] == 35
    assert core.DEFAULT_INPUTS["underground_manual_gns_sqm"] == 0
    assert '"underground_area_per_space_sqm": 35' in core.PAGE


# --- отказ от подземного паркинга -------------------------------------------

def test_the_underground_can_be_dropped_entirely():
    """В области нормативную потребность закрывают наземным гаражом. Ноль в
    поле мест означает «по нормативу», поэтому отказ — отдельный признак:
    иначе импорт ГлавАПУ вернул бы паркинг при первом же пересчёте."""
    row = _calc({"_glavapu_import": _IMPORT, "underground_parking_disabled": True})
    assert row["units"] == pytest.approx(0)
    assert row["gns"] == pytest.approx(0)
    assert row["total_area"] == pytest.approx(0)


def test_the_opt_out_flag_is_inverse_on_purpose():
    """Признак назван отказом, а не включением, намеренно: чекбокс «включён»
    с умолчанием «Да» у сохранённого раньше проекта пришёл бы снятым и молча
    обнулил паркинг. Отсутствующий ключ обязан означать «паркинг на месте»."""
    assert core.DEFAULT_INPUTS["underground_parking_disabled"] is False
    row = _calc({"_glavapu_import": _IMPORT})  # ключа в наборе нет вовсе
    assert row["units"] == pytest.approx(28), "без признака паркинг остаётся"


def test_the_opt_out_beats_manual_numbers_too():
    """Отказ сильнее заданных вручную мест: иначе снятый флаг спорил бы с
    числом, оставшимся в поле от прежнего решения."""
    row = _calc({"underground_manual_spaces": 50,
                 "underground_parking_disabled": True})
    assert row["units"] == pytest.approx(0)
    assert row["gns"] == pytest.approx(0)


def test_the_page_explains_the_opt_out():
    page = core.PAGE
    assert "Отказ от подземного паркинга" in page
    assert "потребность закрывает наземный" in page
    # Наземные места идут в зачёт норматива, когда подземного нет.
    assert "off?above:0" in page
