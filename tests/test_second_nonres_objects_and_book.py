"""Вторые нежилые объекты — самостоятельные объекты очередей и книги v4.

Проверяется именно незаконченный хвост работы 13.09.2026: строка реестра должна
доехать не только до веб-движка, но и до Excel. Второй офис, второй ТЦ/ОСЗ и
второй наземный паркинг не являются долями первого объекта: у них свои
вводные, календарь и очередь финансирования.

Запуск:
    python3 -m pytest tests/test_second_nonres_objects_and_book.py -q
"""

from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def _scenario():
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    # Убираем штатную соцнагрузку умолчаний: тест отвечает только за ОСЗ.
    inputs.update(
        kindergarten_places=0,
        school_places=0,
        clinic_capacity=0,
        social_compensation_mln=0,
        land_rights_cost_mln=0,
        offices2_enabled=True,
        offices2_gba_sqm=24000.0,
        offices2_saleable_sqm=15000.0,
        offices2_parking_under_spaces=100,
        offices2_parking_over_spaces=20,
        offices2_parking_guest_pct=10,
        retail2_enabled=True,
        retail2_gba_sqm=18000.0,
        retail2_saleable_sqm=11000.0,
        retail2_parking_under_spaces=80,
        retail2_parking_over_spaces=0,
        above_parking2_enabled=True,
        above_parking2_spaces=300,
    )
    tep = copy.deepcopy(core.TEP_DEFAULT)
    tep["offices2"].update(
        gns=24000.0, total_area=22560.0, useful=15000.0, saleable=15000.0)
    tep["retail2"].update(
        gns=18000.0, total_area=16920.0, useful=11000.0, saleable=11000.0)
    # Наземный паркинг — штучный объект: метры обязан вывести сам движок.
    tep["above_parking2"].update(gns=0.0, total_area=0.0, units=0.0)

    phasing = {
        "enabled": True,
        "phase_count": 4,
        "phase_gap_months": 12,
        "cost_inflation_pct": 8,
        "sales_price_inflation_pct": 8,
        "financing_strategy": "independent",
        "phases": [
            {"name": f"О{i + 1}", "start_offset_months": i * 12,
             "construction_months": 24, "products": {}}
            for i in range(4)
        ],
        "products": {
            key: [25.0, 25.0, 25.0, 25.0]
            for key in ("apartments", "ground_commercial",
                        "underground_parking", "storage")
        },
        "social_objects": [],
        "discrete": {
            "offices2": 4,
            "retail2": 3,
            "above_parking2": 2,
        },
    }
    return inputs, tep, phasing


def _bundle():
    inputs, tep, phasing = _scenario()
    return core.calculate_phased(core.PhasedCalcRequest(
        inputs=copy.deepcopy(inputs),
        tep=copy.deepcopy(tep),
        rates=[],
        phasing=copy.deepcopy(phasing),
    ))


def test_second_objects_exist_as_optional_registry_objects():
    by_key = {obj.key: obj for obj in core.STANDALONE_OBJECTS}
    assert {"offices2", "retail2", "above_parking2"} <= set(by_key)
    assert by_key["offices2"].clone_of == "offices"
    assert by_key["retail2"].clone_of == "standalone_retail"
    assert by_key["above_parking2"].clone_of == "above_parking"
    for key in ("offices2", "retail2", "above_parking2"):
        obj = by_key[key]
        assert core.DEFAULT_INPUTS[obj.enabled_key] is False
        assert key in core.TEP_DEFAULT
        assert any(group[0] == obj.group_label for group in core.FIELD_GROUPS)


def test_each_second_object_lands_only_in_its_own_queue():
    bundle = _bundle()
    assert bundle["mode"] == "phased"
    wanted = {"offices2": 4, "retail2": 3, "above_parking2": 2}
    assert core._v4_object_phase_by_result(bundle["phases"]) == wanted

    by_queue = {
        index + 1: (item.get("result") or {}).get("capex") or {}
        for index, item in enumerate(bundle["phases"])
    }
    for key, queue in wanted.items():
        assert float(by_queue[queue].get(key) or 0.0) > 0, (key, queue)
        for other in range(1, 5):
            if other != queue:
                assert float(by_queue[other].get(key) or 0.0) == 0.0, (key, other)


def test_second_ground_parking_gets_metres_from_its_own_inputs():
    bundle = _bundle()
    phase = bundle["phases"][1]["result"]  # above_parking2 assigned to O2
    rows = {row["key"]: row for row in phase["tep"]["rows"]}
    row = rows["above_parking2"]
    assert row["units"] == 300
    assert row["gns"] == 300 * float(
        core.DEFAULT_INPUTS["above_parking2_area_per_space_sqm"])
    assert row["gns"] > 0


def test_excel_v4_contains_second_objects_and_their_queue_cells():
    inputs, tep, phasing = _scenario()
    bundle = _bundle()
    hints = core._v4_finance_hints(bundle)
    content, _name, meta = core.build_project_workbook(
        copy.deepcopy(inputs),
        copy.deepcopy(tep),
        [],
        copy.deepcopy(phasing),
        project_name="Вторые ОСЗ",
        finance_hints=hints,
    )
    book = openpyxl.load_workbook(io.BytesIO(content), data_only=False)
    objects = book["ОБЪЕКТЫ"]
    tep_sheet = book["ТЭП"]
    report = book["ОТЧЕТ"]

    # Блоки не просто подписаны: очередь, выручка и CAPEX имеют свои формулы.
    for title_cell, queue_cell, revenue_cell, capex_cell, label in (
        ("A154", "B156", "B172", "B176", "МФОЦ / ОФИСЫ 2"),
        ("A182", "B184", "B200", "B204", "ТЦ / КОММЕРЦИЯ ОСЗ 2"),
        ("A210", "B212", "B228", "B232", "НАЗЕМНЫЙ ПАРКИНГ 2"),
    ):
        assert str(objects[title_cell].value or "").upper() == label
        assert str(objects[queue_cell].value or "").startswith("=")
        assert str(objects[revenue_cell].value or "").startswith("=")
        assert str(objects[capex_cell].value or "").startswith("=")

    assert tep_sheet["B45"].value == "Офисы 2"
    assert tep_sheet["B46"].value == "Коммерция ОСЗ 2"
    assert tep_sheet["B47"].value == "Наземный паркинг 2"
    assert report["A200"].value == "МФОЦ / офисный центр 2"
    assert report["A201"].value == "Торговый центр / ОСЗ 2"
    assert report["A202"].value == "Наземный паркинг 2"

    bad = [
        str(item) for item in (meta.get("missing") or [])
        if any(mark in str(item) for mark in (
            "offices2", "retail2", "above_parking2",
            "аллокация по очередям", "налоговая база не знает"))
    ]
    assert not bad, bad