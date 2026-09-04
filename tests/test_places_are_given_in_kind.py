"""Переданное в натуре: машино-места отдают штуками, а не метрами.

Владелец, 04.09.2026: «отдаём мы конкретные машиноместа, а не метры никакие»,
и «при передаче в КРТ ВРИ то вообще нет» — натура это часть КОММЕРЧЕСКИХ
условий сделки, а не льгота по плате за смену ВРИ.

Метровые продукты уже умели: колонка «передаваемая» вычитает метры из
продаваемой площади. У паркинга и кладовых продаётся ШТУКА, и метры про них
ничего не говорят: гараж, отданный городу, уменьшил бы площадь, а места
продолжили бы продаваться все. Механизм «строим, но не продаём» у паркинга уже
есть — гостевые места, — и переданные идут той же дорогой.

Запуск: python3 -m pytest tests/test_places_are_given_in_kind.py -q
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _tep() -> dict[str, dict[str, float]]:
    tep = {key: dict(value) for key, value in core.TEP_DEFAULT.items()}
    tep["underground_parking"].update({"units": 400, "guest_units": 40, "gns": 14000,
                                       "total_area": 14000})
    tep["storage"].update({"units": 100, "gns": 500, "total_area": 500})
    return tep


def test_a_transferred_place_is_built_but_not_sold() -> None:
    """Переданные места уходят из продаваемых, как гостевые."""
    row = dict(_tep()["underground_parking"])
    assert core.underground_saleable_spaces(row) == 360
    row["transfer_units"] = 25
    assert core.underground_saleable_spaces(row) == 335
    # Построенные места на месте: их строят и за них платят.
    assert core.n(row, "units") == 400
    storage = {"units": 100, "transfer_units": 12}
    assert core.storage_saleable_spaces(storage) == 88
    assert core.storage_saleable_spaces({"units": 100}) == 100


def test_the_revenue_drops_by_the_transferred_places() -> None:
    """Выручка меньше ровно на переданные места, CAPEX — тот же."""
    tep = _tep()
    inputs = {**core.DEFAULT_INPUTS, "parking_price_th": 3000, "storage_price_th": 1000}
    before = core.calculate(core.CalcRequest(inputs=dict(inputs), tep=copy.deepcopy(tep), rates=[]))
    given = copy.deepcopy(tep)
    given["underground_parking"]["transfer_units"] = 25
    after = core.calculate(core.CalcRequest(inputs=dict(inputs), tep=given, rates=[]))
    parking_before = before["revenue"]["underground_parking"]
    parking_after = after["revenue"]["underground_parking"]
    assert parking_after < parking_before
    # 25 мест из 360 продаваемых — доля выручки паркинга совпадает до процента.
    assert abs(parking_after / parking_before - 335 / 360) < 0.01
    assert abs(after["summary"]["capex"] - before["summary"]["capex"]) < 1.0
    row = next(r for r in after["tep"]["rows"] if r["key"] == "underground_parking")
    assert row["units"] == 400 and row["transfer_units"] == 25
    assert row["saleable_units"] == 335


def test_a_queue_gets_its_own_share_of_guest_and_given_places() -> None:
    """Гостевые и переданные делятся по очередям, а не остаются числом проекта.

    Поле, которого нет в списке деления, молча остаётся значением ПРОЕКТА в
    каждой очереди: сорок гостевых мест вычитались из каждой четверти паркинга
    вместо своей доли, и продаваемых мест выходило меньше на три четверти
    гостевых.
    """
    tep = _tep()
    tep["underground_parking"]["transfer_units"] = 40
    rows, _weights = core._phase_tep_product_rows(
        tep, {"products": {"underground_parking": [50, 50]}}, 2)
    got = [row["underground_parking"] for row in rows]
    assert [core.n(r, "units") for r in got] == [200, 200]
    assert sum(core.n(r, "guest_units") for r in got) == 40
    assert sum(core.n(r, "transfer_units") for r in got) == 40
    for row in got:
        assert core.underground_saleable_spaces(row) == 160


def test_the_queue_may_name_its_own_given_places() -> None:
    """Приоритет у очереди: вписанное в её строку сильнее общей доли."""
    tep = _tep()
    p_tep = {"underground_parking": dict(tep["underground_parking"], units=200)}
    p_inputs: dict[str, object] = {}
    core._apply_explicit_phase_products(
        p_tep, p_inputs, {"products": {"underground_parking": {"transfer_units": 30}}})
    assert core.n(p_tep["underground_parking"], "transfer_units") == 30
