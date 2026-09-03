"""Метры соцобъекта меряются одним ответом на всех поверхностях.

«Зачем движку площадь СОШ? она же в бюджет ложится по нормативу места»
(владелец, 03.09.2026) и его же решение по разбору: «логику, что бюджет
стройки берётся от места, а не от ГНС, сохраняем; ГНС нам нужен для контроля
общей площади». То есть у соцобъекта два разных числа: бюджет идёт от МЕСТ,
площадь — для контроля объёма застройки. Путать их нельзя, но и считать
площадь двумя способами тоже.

А считали именно двумя. Страница брала ступень РНГП по ёмкости здания
(ДОО 27/18/16, СОШ 18/15/13), движок очередей — зашитые 12 и 13 м²/место,
которые НИЖЕ городского минимума в любой ёмкости. Один и тот же садик получал
разный ТЭП в зависимости от того, считают проект одной очередью или
несколькими, и обе цифры выглядели одинаково достоверно. Ещё и ГНС соцстроки
в очереди был нулём — строительный объём очереди занижался ровно на объект,
который она строит.

Запуск: python3 -m pytest tests/test_the_social_area_is_measured_once.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as _wrapper  # noqa: E402

core = _wrapper.core


def test_the_answer_is_declared_once():
    """Одна функция на все поверхности, и поля соцобъекта перечислены при ней."""
    assert set(core.SOCIAL_TEP_FIELDS) == {"kindergarten", "school", "clinic"}
    assert core.SOCIAL_TEP_FIELDS["school"] == (
        "school_places", "social_school_gba_sqm", "social_school_norm_sqm")


def test_the_requirement_of_the_contract_beats_the_norm():
    """Договор КРТ задаёт площадь — и она сама себе норматив: 5 000 ÷ 225."""
    x = {**core.DEFAULT_INPUTS, "social_area_source": "manual",
         "kindergarten_places": 225, "social_dou_gba_sqm": 5000}
    assert core.social_area_per_place(x, "kindergarten") == pytest.approx(22.22, abs=0.01)


def test_an_empty_field_falls_back_to_the_city_step():
    """Пустое поле — «не знаем», и тогда отвечает ступень РНГП по ёмкости."""
    x = {**core.DEFAULT_INPUTS, "school_places": 1000, "social_school_norm_sqm": 0}
    assert core.social_area_per_place(x, "school") == 15.0
    x["school_places"] = 1001
    assert core.social_area_per_place(x, "school") == 13.0
    x["school_places"] = 550
    assert core.social_area_per_place(x, "school") == 18.0


def test_zero_means_we_do_not_know_it():
    """У поликлиники норматива города нет: пустое поле даёт ноль, а не догадку."""
    x = {**core.DEFAULT_INPUTS, "clinic_capacity": 100, "social_clinic_norm_sqm": 0}
    assert core.social_area_per_place(x, "clinic") == 0.0


def test_no_default_is_below_the_city_minimum():
    """12 и 13 м²/место были НИЖЕ минимума РНГП в любой ёмкости — их больше нет."""
    for kind, key in (("kindergarten", "social_dou_norm_sqm"),
                      ("school", "social_school_norm_sqm")):
        value = float(core.DEFAULT_INPUTS[key] or 0.0)
        if value <= 0:
            continue  # ноль — «считаем ступенью», а не заниженное число
        floor = min(step for _, step in core.MOSCOW_SOCIAL_AREA_PER_PLACE[kind])
        assert value >= floor, (kind, value, floor)


def test_the_engine_does_not_hardcode_the_norm():
    """Зашитое число рядом с полем норматива — это второй ответ на тот же вопрос."""
    src = (ROOT / "main_legacy.py").read_text(encoding="utf-8")
    for key in ("social_dou_norm_sqm", "social_school_norm_sqm", "social_clinic_norm_sqm"):
        stray = re.findall(rf'"{key}"\s*,\s*\d', src)
        assert stray == [], (key, stray)


def _phased(**extra):
    inputs = {**core.DEFAULT_INPUTS, "social_mode": "Строительство",
              "kindergarten_places": 250, "school_places": 1000,
              "clinic_capacity": 0, **extra}
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=core.TEP_DEFAULT, rates=[],
        phasing={"enabled": True, "user_enabled": True, "phase_count": 2,
                 "target_size_sqm": 70000, "phase_gap_months": 12,
                 "cost_inflation_pct": 0, "sales_price_inflation_pct": 0},
    )), inputs


def _social_row(bundle, kind):
    for phase in bundle["phases"]:
        row = (phase.get("tep") or {}).get(kind) or {}
        if float(row.get("units") or 0) > 0:
            return row
    return {}


def test_the_queue_measures_the_object_the_same_way():
    """Садик очереди — те же метры, что садик проекта: 250 × 18, а не 250 × 12."""
    bundle, inputs = _phased()
    row = _social_row(bundle, "kindergarten")
    per_place = core.social_area_per_place(inputs, "kindergarten")
    assert per_place == 18.0
    assert row["units"] == pytest.approx(250, abs=0.5)
    assert row["total_area"] == pytest.approx(250 * per_place, rel=1e-6)
    assert row["total_area"] > 250 * 12, "очередь снова считает по зашитым 12 м²/место"


def test_the_queue_object_has_its_own_gns():
    """Ноль в ГНС занижал строительный объём очереди ровно на объект, который она строит."""
    bundle, _ = _phased()
    row = _social_row(bundle, "school")
    share = float((core.TEP_RATIOS.get("apartments") or {}).get("total_of_gns") or 0.9)
    assert row["gns"] == pytest.approx(row["total_area"] / share, rel=1e-6)
    assert row["gns"] > row["total_area"]


def test_the_contract_requirement_reaches_the_queue():
    """Вписанная руками площадь доезжает до очереди, а не подменяется нормативом."""
    bundle, _ = _phased(social_area_source="manual", social_dou_gba_sqm=7000,
                        social_school_gba_sqm=0)
    row = _social_row(bundle, "kindergarten")
    assert row["total_area"] == pytest.approx(7000, rel=1e-6), row


def test_the_budget_still_comes_from_the_places():
    """Бюджет объекта — места × себестоимость места; площадь в него не входит."""
    small, _ = _phased(social_dou_gba_sqm=3000, social_area_source="manual")
    large, _ = _phased(social_dou_gba_sqm=9000, social_area_source="manual")

    def social_capex(bundle):
        return round(sum(
            float(((phase.get("result") or {}).get("summary") or {}).get("social_capex") or 0.0)
            for phase in bundle["phases"]), 2)

    assert social_capex(small) == social_capex(large), (
        "себестоимость соцобъекта поехала за площадью — она обязана идти от мест")
