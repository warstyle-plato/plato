"""Нормативная ёмкость участка: сколько квартир туда помещается по РНГП МО.

Расчёт отвечает на вопрос покупки — «сколько метров жилья выдерживает эта
площадка» — и делает это формулой самого норматива, без генплана и геометрии.
Проверяется он единственной сверкой, которая у нас есть: официальным примером
в приложении 7 к 713/30, где даны и исходные данные, и ответы.

Отдельно сторожится главное свойство — односторонность. Дефицит есть, резерва
нет. Норматив не знает ни формы участка, ни пожарных разрывов, ни инсоляции, и
«помещается» он подтвердить не может, сколько бы земли ни осталось.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import mo_land_capacity as cap  # noqa: E402
import mo_rngp_reference as ref  # noqa: E402


# --- сверка с официальным примером -------------------------------------------------

def test_the_official_example_reproduces():
    """Участок 38 400 м², шесть этажей, 54 640 м² квартир — норматив даёт
    S_min 38 083,5 и профицит +316,5.

    Допуск в тридцать метров — округление документа: он считает население по
    каждому дому отдельно (929 + 713 + 311 = 1953), а мы делим общую площадь
    квартир (54 640 ÷ 28 = 1951,4). Подгонять свою формулу под чужое округление
    нельзя, поэтому расхождение объявлено, а не спрятано."""
    result = cap.land_capacity(38400, storeys=6.0, flat_area_sqm=54640)
    assert result["kud_sqm_per_person"] == pytest.approx(19.50)
    assert result["population"] == pytest.approx(1953, abs=2)
    assert result["s_min_sqm"] == pytest.approx(38083.5, abs=35)
    assert result["balance_sqm"] > 0
    assert result["deficit_sqm"] == 0.0


def test_the_storeys_follow_the_norm_definition():
    """Средняя этажность — поэтажная площадь, делённая на пятно застройки.
    В примере 38 757 ÷ 6 459 = 6,00 при объявленных 6,0."""
    assert cap.average_storeys(38757, 6459) == pytest.approx(6.0, abs=0.01)
    assert cap.average_storeys(81332, 13589) == pytest.approx(6.0, abs=0.02)
    assert cap.average_storeys(1000, 0) == 0.0


@pytest.mark.parametrize("storeys,column", [
    (3, "≤3"), (3.0, "≤3"), (4, "4-5"), (5, "4-5"), (6, "6-7"), (17, "6-7")])
def test_the_column_follows_the_storeys(storeys, column):
    assert cap.storeys_column(storeys) == column


# --- этажность двигает ответ в полтора раза ----------------------------------------

def test_the_storeys_change_the_capacity():
    """Подставить 19,50 всем — та же ошибка, что московские нормы под видом
    областных: на трёх этажах участок держит в полтора раза меньше жилья."""
    low = cap.land_capacity(40000, storeys="≤3")["max_flat_area_sqm"]
    mid = cap.land_capacity(40000, storeys="4-5")["max_flat_area_sqm"]
    high = cap.land_capacity(40000, storeys="6-7")["max_flat_area_sqm"]
    assert low < mid < high
    assert high / low == pytest.approx(1.47, abs=0.02)


def test_an_unknown_storeys_value_is_refused():
    with pytest.raises(ValueError):
        cap.land_capacity(40000, storeys="десять")


# --- вывод односторонний -----------------------------------------------------------

def test_a_tight_site_reports_a_deficit():
    """Обязательный минимум больше участка — строгий вывод, его и показываем."""
    result = cap.land_capacity(20000, storeys="6-7", flat_area_sqm=60000)
    assert result["deficit_sqm"] > 0
    assert result["balance_sqm"] < 0


def test_a_roomy_site_reports_no_reserve():
    """Свободная земля есть, но «резерва» в ответе нет и быть не должно:
    норматив не проверял ни разрывы, ни инсоляцию."""
    result = cap.land_capacity(100000, storeys="6-7", flat_area_sqm=20000)
    assert result["deficit_sqm"] == 0.0
    assert not any("резерв" in key for key in result)
    assert any("не означает" in note for note in result["warnings"])


def test_the_answer_says_what_it_did_not_count():
    """Школа и поликлиника нормируются на уровне жилого района. Промолчать об
    этом значит дать человеку решить, что они посчитаны."""
    warnings = " ".join(cap.land_capacity(40000)["warnings"])
    assert "квартала" in warnings
    assert "Школа" in warnings and "поликлиника" in warnings


# --- границы применимости ----------------------------------------------------------

def test_a_big_town_is_out_of_the_table():
    """Таблица № 13 — для городов 15–50 тысяч. Мытищи в неё не попадают, и
    расчёт обязан сказать это первым словом, а не сноской."""
    result = cap.land_capacity(40000, settlement_population=250_000)
    assert result["applicable"] is False
    assert "Таблица № 13" in result["warnings"][0]


def test_a_town_inside_the_range_is_fine():
    result = cap.land_capacity(40000, settlement_population=28_000)
    assert result["applicable"] is True


def test_an_unknown_population_still_warns():
    """Молчание про численность опаснее ошибки: расчёт применят где попало."""
    result = cap.land_capacity(40000)
    assert result["applicable"] is True
    assert any("Численность" in note for note in result["warnings"])


# --- парковка по действующей редакции ----------------------------------------------

def test_the_parking_comes_from_the_population():
    """В области машино-места считаются от населения, а не от площади квартир
    через московские 90 м² на автомобиль."""
    result = cap.land_capacity(40000, storeys="6-7")
    assert result["parking_permanent"] == pytest.approx(
        result["population"] * 0.3204, rel=1e-9)
    assert result["parking_temporary"] == pytest.approx(
        result["population"] * 0.030, rel=1e-9)
    assert result["parking_permanent_in_quarter_min"] == pytest.approx(
        result["parking_permanent"] * 0.40, rel=1e-9)


# --- арифметика живёт здесь, а справочник остаётся справочником ---------------------

def test_the_reference_stays_free_of_arithmetic():
    """Первое «просто поделить» в справочнике — это вторая реализация методики.
    Тот же сторож, что стоит над адаптером результата 2.0."""
    source = (ROOT / "mo_rngp_reference.py").read_text(encoding="utf-8")
    body = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    # Единственное вычисление, которое справочнику позволено, — сложение строк
    # своей же таблицы в kud_for_quarter: иначе К_уд пришлось бы хранить копией.
    body = body.replace("sum(LAND_TABLE_13[\"value\"][row][column] for row in _KUD_ROWS)", "")
    for forbidden in (" / 1000", " * 1000", "/ 1e", "* 1e"):
        assert forbidden not in body, f"в справочнике появилась арифметика: {forbidden}"


def test_the_numbers_come_from_the_reference():
    """Ни одна норма не задана в расчётном модуле — все читаются из справочника."""
    source = (ROOT / "mo_land_capacity.py").read_text(encoding="utf-8")
    for magic in ("19.5", "28.0", "320.4", "22.5", "356"):
        assert magic not in source, f"норма {magic} зашита вместо чтения справочника"
    assert ref.LAND_TABLE_13["point_table"] == cap.land_capacity(1000)["source"]["point_table"]
