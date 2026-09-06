"""Гараж отдельно стоящего объекта доезжает до очереди — и не удваивается там.

Владелец, 05.09.2026: «эти подземные и наземные при объекты будут видны в ТЭП
и в очередности рядом с основными параметрами оси?» ТЭП половину закрыла
правка 06.09; очередность — эта. Измерено до неё было вот что.

**Строка отчёта не несла полей гаража вовсе.** `tep_rows` собирается по списку
ключей, а `under_gns`, `parking_units` и `parking_saleable_units` в списке не
стояли: у атомарного расчёта они приходили `None`, а свод очередей складывает
именно строки отчётов — и на своде гараж выходил нулём при живом гараже в
каждой очереди.

**А число мест делилось по очередям как проектное — то есть не делилось.**
Места гаража задаёт человек полем проекта, и в карте деления его не было:
у офиса из 100 мест, разложенного пополам, КАЖДАЯ очередь строила и продавала
все 100 — 200 мест и 5 600 м² подземной части вместо 100 и 2 800. А это
двойной CAPEX подземной части и двойная выручка паркинга при верном на вид
ТЭП. Ровно так уже терялись гостевые места и решение по подземному паркингу
проекта: «поле, которого нет в карте деления, молча остаётся числом проекта».

Доля берётся у метров САМОГО объекта: у посаженного в очередь целиком — единица
в своей очереди и ноль в остальных, у разложенного долями — его доля, у
объявленного метрами очереди — доля объявленного. Второго правила размещения
здесь нет.

Запуск: python3 -m pytest tests/test_object_parking_reaches_the_queue.py -q
"""

from __future__ import annotations

import copy
import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402

# Сто мест в гараже офисника и шестьдесят у ОСЗ — числа человека. К1 и К2
# заданы затем, чтобы норматив ПОСЧИТАЛСЯ: без них московский расчёт
# отказывается, и проверка «норматив не подменяет заданное» не значила бы
# ничего.
HAND = dict(offices_enabled=True, retail_enabled=True,
            parking_k1=1.0, parking_k2=0.5,
            offices_parking_under_spaces=80, offices_parking_over_spaces=20,
            offices_parking_guest_pct=10,
            retail_parking_under_spaces=60, retail_parking_over_spaces=0)


def _inputs(**over) -> dict:
    x = dict(core.DEFAULT_INPUTS)
    x.update(HAND)
    x.update(over)
    return x


def _tep() -> dict:
    t = copy.deepcopy(core.TEP_DEFAULT)
    t["offices"].update(gns=10000, total_area=9400, saleable=6000)
    t["standalone_retail"].update(gns=10000, total_area=9400, saleable=6000)
    return t


def _phasing(count: int = 2, **over) -> dict:
    cfg = {
        "enabled": True, "phase_count": count, "phase_gap_months": 12,
        "phases": [{"name": f"О{i+1}", "start_offset_months": 12 * i,
                    "construction_months": 24} for i in range(count)],
        "social_objects": [],
        "discrete": {"offices": 1, "standalone_retail": 2},
    }
    cfg.update(over)
    return cfg


def _phased(inputs=None, phasing=None):
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=inputs or _inputs(), tep=_tep(), phasing=phasing or _phasing()))


def _row(result: dict, key: str) -> dict:
    for row in ((result.get("tep") or {}).get("rows") or []):
        if row.get("key") == key:
            return row
    raise AssertionError(f"строки {key} в отчёте нет")


# --- предохранитель -----------------------------------------------------------

def test_the_check_project_really_has_a_garage() -> None:
    """Не стало мест — тест говорит об этом, а не зеленеет впустую.

    В умолчаниях гаража объектов нет вовсе: без своих вводных этот файл
    проверял бы ноль на равенство нулю. Так однажды пережила 581 проверку
    ставка ПФ ниже специальной.
    """
    demand = core.apply_object_parking(_inputs(), _tep())
    assert demand["own_units"] == 160
    assert demand["own_saleable_units"] == 90
    assert demand["own_under_gns"] > 0


# --- строка отчёта ------------------------------------------------------------

def test_the_report_row_carries_the_garage() -> None:
    """Атомарный отчёт несёт поля гаража — до правки их там не было вовсе."""
    result = core.calculate(core.CalcRequest(inputs=_inputs(), tep=_tep(), rates=[]))
    offices = _row(result, "offices")
    assert offices["parking_units"] == 100
    assert offices["parking_saleable_units"] == 90
    assert offices["under_gns"] > 0
    # ТЦ строит места и не продаёт ни одного: «ты видел ТЦ, где покупатели
    # купили бы места?» (владелец, 06.09.2026).
    retail = _row(result, "standalone_retail")
    assert retail["parking_units"] == 60
    assert retail["parking_saleable_units"] == 0


def test_the_total_row_sums_the_garage_too() -> None:
    total = (core.calculate(core.CalcRequest(
        inputs=_inputs(), tep=_tep(), rates=[])).get("tep") or {}).get("total") or {}
    assert total.get("parking_units") == 160
    assert total.get("parking_saleable_units") == 90


# --- деление по очередям ------------------------------------------------------

def test_a_discrete_object_keeps_its_whole_garage_in_its_own_queue() -> None:
    bundle = _phased()
    offices = [_row(item["result"], "offices") for item in bundle["phases"]]
    assert [row["parking_units"] for row in offices] == [100.0, 0.0]
    retail = [_row(item["result"], "standalone_retail") for item in bundle["phases"]]
    assert [row["parking_units"] for row in retail] == [0.0, 60.0]


def test_a_shared_object_does_not_build_its_garage_twice() -> None:
    """Половина объекта — половина гаража, а не второй гараж.

    До правки обе очереди строили по 100 мест и по 2 800 м² подземной части.
    """
    bundle = _phased(phasing=_phasing(products={"offices": [50.0, 50.0]}))
    rows = [_row(item["result"], "offices") for item in bundle["phases"]]
    assert [row["parking_units"] for row in rows] == [50.0, 50.0]
    assert sum(row["under_gns"] for row in rows) == pytest.approx(
        core.apply_object_parking(_inputs(), _tep())["own"][0]["under_gns"])


@pytest.mark.parametrize("weights,expected", [
    ([50.0, 50.0], [50, 50]),
    ([40.0, 32.0, 28.0], [40, 32, 28]),
    ([2.0, 49.0, 49.0], [2, 49, 49]),
])
def test_the_places_of_the_queues_add_up_to_the_project(weights, expected) -> None:
    """Место неделимо: три очереди по трети от ста мест — это 34+33+33.

    Доли округляются нарастающим итогом, поэтому сумма по очередям равна
    проектной при любых весах, а не «около того».
    """
    bundle = _phased(phasing=_phasing(len(weights), products={"offices": weights},
                                      discrete={"standalone_retail": 1}))
    places = [int(_row(item["result"], "offices")["parking_units"])
              for item in bundle["phases"]]
    assert places == expected
    assert sum(places) == 100


def test_a_zero_share_of_hand_written_places_is_zero_not_the_norm() -> None:
    """Ноль мест по доле — это ноль, а не незаполненное поле.

    Пустое поле зовёт норматив, и очередь с нулевой долей получила бы его
    места вместо своей доли — сумма по очередям перестала бы сходиться с
    проектом при верной на вид каждой строке.
    """
    bundle = _phased(phasing=_phasing(products={"offices": [100.0, 0.0]},
                                      discrete={"standalone_retail": 1}))
    rows = [_row(item["result"], "offices") for item in bundle["phases"]]
    assert [row["parking_units"] for row in rows] == [100.0, 0.0]
    assert rows[1]["under_gns"] == 0.0


def test_an_unset_field_still_takes_the_norm_in_every_queue() -> None:
    """Норматив никуда не делся: не задал человек — ставит приложение 6.

    Разница с проектным счётом здесь есть и названа: норма округляется вверх
    в КАЖДОЙ очереди, поэтому сумма может превысить проектную на число
    очередей минус одна. Это свойство нормы, а не потеря деления.
    """
    inputs = _inputs(offices_parking_under_spaces=0, offices_parking_over_spaces=0,
                     retail_parking_under_spaces=0, retail_parking_over_spaces=0)
    project = core.apply_object_parking(dict(inputs), _tep())["own"]
    by_norm = {item["tep_key"]: item for item in project}
    assert by_norm["offices"]["by_norm"], "норматив не сработал — проверять нечего"
    bundle = _phased(inputs=inputs,
                     phasing=_phasing(3, products={"offices": [40.0, 32.0, 28.0]},
                                      discrete={"standalone_retail": 1}))
    places = [int(_row(item["result"], "offices")["parking_units"])
              for item in bundle["phases"]]
    assert all(p > 0 for p in places), places
    assert 0 <= sum(places) - by_norm["offices"]["units"] <= 2, places


# --- свод и таблица очередей --------------------------------------------------

def test_the_consolidated_tep_carries_the_garage() -> None:
    """Свод складывает строки отчётов — до правки гараж выходил там нулём."""
    bundle = _phased()
    rows = {row["key"]: row for row in bundle["consolidated"]["tep"]["rows"]}
    assert rows["offices"]["parking_units"] == 100
    assert rows["standalone_retail"]["parking_units"] == 60
    assert rows["offices"]["under_gns"] > 0


def test_the_comparison_names_the_garage_of_each_queue() -> None:
    bundle = _phased()
    got = [(item["object_parking_units"], item["object_parking_saleable_units"])
           for item in bundle["comparison"]]
    assert got == [(100.0, 90.0), (60.0, 0.0)]
    summary = bundle["consolidated"]["summary"]
    assert summary["object_parking_units"] == 160
    assert summary["object_parking_saleable_units"] == 90


def test_the_screen_prints_the_garage_and_does_not_count_it() -> None:
    """Экран печатает посчитанное движком: второй счёт разошёлся бы с первым."""
    body = re.search(r"\nfunction renderPhaseComparison\(.*?\n\}", core.PAGE, re.S)
    assert body, "функции сравнения очередей на странице нет"
    block = body.group(0)
    start = block.index("const objParkRows=[]")
    piece = block[start:block.index("const rows=[")]
    assert "object_parking_units" in piece
    assert "object_parking_saleable_units" in piece
    assert "object_parking_under_gns" in piece
    # Ни деления, ни умножения, ни сложения рядов: свод берётся у движка.
    for sign in ("reduce(", "*", "/", "+Number("):
        assert sign not in piece, f"в блоке паркинга очередей появилась арифметика: {sign}"


def test_the_share_is_taken_from_the_metres_not_from_a_second_rule() -> None:
    """Правило размещения одно — доля метров самого объекта."""
    source = inspect.getsource(core._calculate_phased_once)
    block = source[source.index("for tep_key, prefix, enabled_key, _sellable"):]
    block = block[:block.index("carried_list")]
    assert "_phase_object_share" in block
    assert "discrete" not in block, "размещение выводится здесь вторым правилом"


# --- подземная часть отчёта ---------------------------------------------------

def test_the_garage_of_an_object_counts_as_underground() -> None:
    """Гараж офисника — такая же подземная площадь, как гараж дома.

    В колонке «Подземная, м²» отчёта его не было вовсе, при том что в
    `summary.underground_gns_sqm` и в статье CAPEX он есть: две величины под
    одним именем. Наземная при этом не уменьшается — гараж и не стоял в
    `total.gns`.
    """
    result = core.calculate(core.CalcRequest(inputs=_inputs(), tep=_tep(), rates=[]))
    tep = result["tep"]
    garages = sum(float(row.get("under_gns") or 0.0) for row in tep["rows"])
    assert garages > 0, "проверять нечего: гаража объектов на этих вводных нет"
    assert core._underground_sqm(tep) == pytest.approx(
        float(tep["core_under_gns"]) + garages)
    assert core._underground_sqm(tep) == pytest.approx(
        result["summary"]["underground_gns_sqm"])
    assert core._above_ground_sqm(tep) == pytest.approx(
        result["summary"]["project_gns_sqm"])


def test_the_screen_shows_the_garage_in_the_underground_column() -> None:
    """Колонка читает поле строки, а итог берётся у движка."""
    start = core.PAGE.index(" const underGns=Number(r.tep.core_under_gns")
    piece = core.PAGE[start:core.PAGE.index("const REPORT_SECTIONS", start)]
    assert "objUnder(x)" in piece, "гараж объекта в колонке не показан"
    assert "r.summary.underground_gns_sqm" in piece, "итог собирается на экране"
    assert "num(underTotal)" in piece
