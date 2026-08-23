"""Места объекта принадлежат объекту, а не общей куче.

Правило владельца (24.08.2026). Норматив порождает ОБЪЕКТ: у офисника в
третьей очереди своя потребность, у ТЦ во второй — своя. Прибавлять их к общей
потребности проекта нельзя: общая куча разносится по очередям своими правилами
и приезжает не туда — сегодня `discrete.above_parking` по умолчанию вторая
очередь, а `discrete.offices` третья, и паркинг офисника построился бы за год
до офисника.

Второе правило оттуда же: офисник или ТЦ без парковки — это не «ноль мест», а
незаданный вопрос. Поэтому потребность считается всегда.

Запуск: python3 -m pytest tests/test_parking_belongs_to_the_object.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_legacy as core  # noqa: E402
import parking_norms as pn  # noqa: E402


def _inputs(**over):
    got = dict(core.DEFAULT_INPUTS)
    got.update({"parking_k1": 0.75, "parking_k2": 0.5})
    got.update(over)
    return got


TEP = {
    "ground_commercial": {"label": "Коммерция 1 эт.", "gns": 10_000},
    "offices": {"label": "Офисы", "gns": 100_000},
    "standalone_retail": {"label": "Коммерция ОСЗ", "gns": 50_000},
}


def test_every_nonresidential_object_gets_its_own_line() -> None:
    got = core.parking_demand(_inputs(), TEP)
    assert [row["tep_key"] for row in got["rows"]] == [
        "ground_commercial", "offices", "standalone_retail"]


def test_moscow_uses_the_act_for_standalone_objects() -> None:
    got = core.parking_demand(_inputs(), TEP)
    by_key = {row["tep_key"]: row for row in got["rows"]}
    assert by_key["offices"]["x2"] == 63.0
    assert by_key["offices"]["required_spaces"] == 596
    assert by_key["standalone_retail"]["x2"] == 54.0


def test_built_in_commerce_keeps_the_line_that_reproduces_the_city() -> None:
    got = core.parking_demand(_inputs(), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "ground_commercial")
    assert row["x2"] == pn.MOSCOW_BUILT_IN_X2


def test_the_base_is_the_above_ground_area_of_the_object() -> None:
    """Сноска 2 приложения 1: нежилая наземная площадь. В нашем ТЭП это gns."""
    got = core.parking_demand(_inputs(), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "offices")
    assert row["input_value"] == 100_000
    assert row["input_unit"] == pn.UNIT_ABOVE_NONRES_SQM


def test_places_go_underground_by_default() -> None:
    got = core.parking_demand(_inputs(), TEP)
    assert got["to_surface"] == 0
    assert got["to_underground"] == got["required_total"]


def test_the_switch_moves_only_its_own_object() -> None:
    """Один переключатель на проект отправил бы наверх и чужие места."""
    got = core.parking_demand(_inputs(offices_parking_surface=True), TEP)
    offices = next(r for r in got["rows"] if r["tep_key"] == "offices")
    retail = next(r for r in got["rows"] if r["tep_key"] == "standalone_retail")
    assert offices["placement"] == "surface"
    assert retail["placement"] == "underground"
    assert got["to_surface"] == offices["required_spaces"]


def test_a_lost_switch_means_underground_not_a_silent_move() -> None:
    """Поле называется «в наземный» ровно поэтому.

    Чекбокс рисуется по `!!inputs[id]`, и поля, которого нет в сохранённом
    проекте, приходит явным `false`. При имени «под землёй» такая потеря
    переносила бы чужие места наверх молча.
    """
    stripped = {key: value for key, value in _inputs().items()
                if "parking_surface" not in key}
    got = core.parking_demand(stripped, TEP)
    assert got["to_surface"] == 0


def test_moscow_oblast_finally_counts_nonresidential() -> None:
    """До этого офисник в подмосковном проекте получал ноль мест."""
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    by_key = {row["tep_key"]: row for row in got["rows"]}
    assert by_key["offices"]["required_spaces_min"] == 1667
    assert by_key["offices"]["required_spaces_max"] == 2000
    assert by_key["standalone_retail"]["required_spaces"] > 0


def test_moscow_oblast_has_no_moscow_coefficients() -> None:
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    for row in got["rows"]:
        assert "k1" not in row and "k2" not in row


def test_moscow_oblast_built_in_uses_the_confirmed_rule() -> None:
    """774-ПП называет встроенно-пристроенные помещения первых этажей прямо."""
    got = core.parking_demand(_inputs(vri_region="mo"), TEP)
    row = next(r for r in got["rows"] if r["tep_key"] == "ground_commercial")
    assert row["required_spaces"] == 200        # 10 000 / 50
    assert row["source_confirmed"] is True


def test_missing_coefficients_are_reported_not_silently_zero() -> None:
    got = core.parking_demand(_inputs(parking_k1=0, parking_k2=0), TEP)
    assert got["missing"]
    assert got["required_total"] == 0


def test_the_demand_reaches_the_calculation_result() -> None:
    inputs = _inputs(offices_enabled=True, retail_enabled=True)
    tep = core.tep_from_defaults() if hasattr(core, "tep_from_defaults") else None
    if tep is None:
        import copy
        tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices"]["gns"] = 100_000
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=tep, rates=[]))
    assert "parking" in result
    assert result["parking"]["rows"]


def test_the_fields_are_declared_once_in_the_engine() -> None:
    """Страница берёт поля у движка — копии на странице быть не должно."""
    for key in ("parking_k1", "parking_k2", "parking_design_mode",
                "offices_parking_surface", "retail_parking_surface",
                "ground_commercial_parking_surface"):
        assert key in core.DEFAULT_INPUTS, key
    names = {group[0] for group in core.FIELD_GROUPS}
    assert "Приобъектная парковка нежилья" in names


def test_the_norm_is_not_reimplemented_in_the_engine() -> None:
    """Вторая реализация нормы — это то, ради чего заведён модуль."""
    import inspect
    source = inspect.getsource(core.parking_demand)
    assert "63" not in source and "54" not in source and "/ 50" not in source
