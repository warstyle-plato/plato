"""Очереди делят проект, а не размножают его.

На Мытищах подземный паркинг задан 2 723 машино-места. При трёх очередях свод
показывал 8 169 и 285 915 м² подземной ГНС — ровно втрое. Делёж при этом
работал верно: `_phase_tep_product_rows` раздавала 1089 / 871 / 763 целыми
местами. Ломалось следующим шагом: `p_inputs` уносила в каждую очередь общее
решение по машино-местам (`underground_manual_spaces`), а атомарный движок
считает это поле главнее ТЭП и перетирал долю полным итогом проекта.

Рядом жила вторая такая же: при денежной компенсации очередям обнулялись места
ДОУ и школы, а строки ТЭП оставались целиком в каждой. Денег это не стоило —
в этом режиме соцобъекты не строятся, — но ГНС проекта росла на 29 220 м² из
воздуха, а по ней считаются все удельные показатели.

Общее правило одно: **сумма очередей равна исходному ТЭП**. Тест проверяет его
на всех строках сразу, а не на одном паркинге, — иначе следующий продукт с
собственным полем во вводных повторит ту же историю молча.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

PARKING_SPACES = 2723.0
PARKING_GNS = 95305.0


def phasing(count: int) -> dict:
    return {"enabled": True, "mode": "phased", "phase_count": count, "user_enabled": True,
            "phase_gap_months": 12,
            "phases": [{"name": f"О{i+1}", "start_offset_months": 12 * i,
                        "construction_months": 30} for i in range(count)]}


@pytest.fixture
def project():
    """Проект с заданным решением по паркингу и денежной соцнагрузкой."""
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(purchase_price_mln=700, apartment_price_th=650, commercial_price_th=650,
                  parking_price_th=5000, social_mode="Денежная компенсация",
                  social_compensation_mln=575.0, social_dou_gba_sqm=6510,
                  social_school_gba_sqm=8100, kindergarten_places=465, school_places=675,
                  underground_manual_spaces=PARKING_SPACES,
                  underground_manual_gns_sqm=PARKING_GNS)
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["underground_parking"].update(units=PARKING_SPACES, gns=PARKING_GNS,
                                      total_area=PARKING_GNS)
    tep["kindergarten"].update(gns=6510, total_area=6510, transfer=6510, units=465)
    tep["school"].update(gns=8100, total_area=8100, transfer=8100, units=675)
    return inputs, tep


def phase_rows(bundle) -> dict[str, dict[str, float]]:
    """Сумма строк ТЭП по всем очередям."""
    total: dict[str, dict[str, float]] = {}
    for phase in bundle["phases"]:
        for row in phase["result"]["tep"]["rows"]:
            bucket = total.setdefault(row["key"], {})
            for field in ("gns", "total_area", "saleable", "units"):
                bucket[field] = bucket.get(field, 0.0) + float(row.get(field) or 0.0)
    return total


# --- паркинг ---------------------------------------------------------------------

@pytest.mark.parametrize("count", [2, 3, 4])
def test_the_parking_total_survives_the_split(project, count):
    """2 723 остаются 2 723 при любом числе очередей."""
    inputs, tep = project
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    parking = phase_rows(bundle)["underground_parking"]
    assert parking["units"] == pytest.approx(PARKING_SPACES)
    assert parking["gns"] == pytest.approx(PARKING_GNS, rel=1e-6)


def test_each_queue_gets_a_share_not_the_whole(project):
    """Каждая очередь получает долю: доля, равная итогу, — и есть та ошибка."""
    inputs, tep = project
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(3)))
    shares = [next(row["units"] for row in phase["result"]["tep"]["rows"]
                   if row["key"] == "underground_parking")
              for phase in bundle["phases"]]
    assert all(0 < share < PARKING_SPACES for share in shares), shares
    assert sum(shares) == pytest.approx(PARKING_SPACES)


def test_the_places_stay_whole(project):
    """Машино-место неделимо: движок раздаёт их целыми."""
    inputs, tep = project
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(3)))
    for phase in bundle["phases"]:
        units = next(row["units"] for row in phase["result"]["tep"]["rows"]
                     if row["key"] == "underground_parking")
        assert units == int(units), units


def test_the_consolidated_report_shows_the_project_total(project):
    """Свод — это проект, а не сумма трёх проектов."""
    inputs, tep = project
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(3)))
    parking = next(item for item in bundle["consolidated"]["report"]["products"]
                   if item["key"] == "underground_parking")
    assert parking["quantity"] == pytest.approx(PARKING_SPACES)


# --- то же самое для всех остальных строк ----------------------------------------

@pytest.mark.parametrize("count", [2, 3])
def test_no_product_is_multiplied_by_the_number_of_queues(project, count):
    """Главная проверка: ни одна строка ТЭП не размножается очередями.

    Именно она ловит следующий продукт с собственным полем во вводных —
    не только паркинг, ради которого тест написан."""
    inputs, tep = project
    single = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    master = {row["key"]: row for row in single["tep"]["rows"]}
    total = phase_rows(core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count))))
    for key, row in master.items():
        for field in ("gns", "units"):
            expected = float(row.get(field) or 0.0)
            assert total.get(key, {}).get(field, 0.0) == pytest.approx(expected, abs=1.0), \
                f"{key}.{field}: очереди дают {total.get(key, {}).get(field)}, ТЭП {expected}"


@pytest.mark.parametrize("count", [2, 3, 4])
def test_the_project_area_does_not_grow_with_queues(project, count):
    """ГНС проекта — знаменатель всех удельных показателей: раздуйся она, и
    себестоимость метра поедет вслед за числом очередей."""
    inputs, tep = project
    single = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(count)))
    assert bundle["consolidated"]["summary"]["project_gns_sqm"] == pytest.approx(
        single["summary"]["project_gns_sqm"], rel=1e-6)


def test_the_social_rows_are_counted_once(project):
    """Денежная компенсация: соцобъекты не строятся, но в ТЭП проекта они есть —
    и должны быть там ровно один раз."""
    inputs, tep = project
    total = phase_rows(core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(3))))
    assert total["kindergarten"]["total_area"] == pytest.approx(6510, abs=1.0)
    assert total["school"]["total_area"] == pytest.approx(8100, abs=1.0)


# --- деньги от правки не поехали --------------------------------------------------

def test_the_money_is_unchanged_by_the_area_fix(project):
    """Строки ТЭП соцобъектов в денежном режиме на расходы не влияют: правка
    трогает знаменатель, а не экономику."""
    inputs, tep = project
    bare = copy.deepcopy(tep)
    for key in ("kindergarten", "school", "clinic"):
        for field in ("gns", "total_area", "transfer", "units"):
            bare[key][field] = 0
    with_social = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    without = core.calculate(core.CalcRequest(inputs=inputs, tep=bare, rates=[]))
    assert with_social["summary"]["total_expenses"] == pytest.approx(
        without["summary"]["total_expenses"], rel=1e-9)


def test_a_single_queue_is_not_a_split(project):
    """Одна очередь — не деление: свод обязан совпасть с расчётом без очередей.

    Список очередей при `phase_count=1` пуст — движок считает атомарно по сырому
    ТЭП, — поэтому сверяемся со сводом, а не с суммой фаз."""
    inputs, tep = project
    single = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    bundle = core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs, tep=tep, rates=[], phasing=phasing(1)))
    parking = next(item for item in bundle["consolidated"]["report"]["products"]
                   if item["key"] == "underground_parking")
    master = next(item for item in single["report"]["products"]
                  if item["key"] == "underground_parking")
    assert parking["quantity"] == pytest.approx(float(master["quantity"]))
