"""Регрессия пресета КРТ Варшавское / Нагатинская."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import project_preset


PRESET = Path(__file__).resolve().parent.parent / "presets" / "КРТ_Варшавское_Нагатинская.json"


def preview() -> dict:
    return project_preset.build_preview(json.loads(PRESET.read_text(encoding="utf-8")))


def test_glavapu_split_keeps_ground_floor_commercial() -> None:
    tep = preview()["tep"]
    assert tep["apartments"]["gns"] == pytest.approx(229490 * 0.94)
    assert tep["apartments"]["saleable"] == pytest.approx(229490 * 0.94 * 0.65)
    assert tep["ground_commercial"]["gns"] == pytest.approx(229490 * 0.06)
    assert tep["ground_commercial"]["total_area"] == pytest.approx(229490 * 0.06 * 0.90)
    assert tep["ground_commercial"]["saleable"] == pytest.approx(229490 * 0.06 * 0.90)


def test_business_part_is_a_shopping_center_and_an_office() -> None:
    data = preview()
    assert data["tep"]["standalone_retail"]["gns"] == pytest.approx(92730)
    assert data["tep"]["standalone_retail"]["saleable"] == pytest.approx(52299.72)
    assert data["tep"]["standalone_retail"]["total_area"] == pytest.approx(87166.2)
    assert data["tep"]["offices"]["gns"] == pytest.approx(92730)
    assert data["tep"]["offices"]["saleable"] == pytest.approx(52299.72)
    assert data["tep"]["offices"]["total_area"] == pytest.approx(87166.2)
    assert data["inputs"]["retail_enabled"] is True
    assert data["phasing"]["discrete"] == {"standalone_retail": 2, "offices": 4}


def test_project_parking_is_imported_instead_of_becoming_zero() -> None:
    data = preview()
    assert data["tep"]["underground_parking"]["units"] == 2906
    assert data["tep"]["underground_parking"]["gns"] == pytest.approx(101710)
    assert data["inputs"]["underground_manual_spaces"] == 2906
    assert data["inputs"]["underground_manual_gns_sqm"] == pytest.approx(101710)


def test_preschool_is_in_phase_two_and_school_in_phase_three() -> None:
    social = {item["type"]: item["phase"] for item in preview()["phasing"]["social_objects"]}
    assert social == {"school": 3, "kindergarten": 2}


def test_mass_products_have_the_agreed_four_phase_distribution() -> None:
    products = preview()["phasing"]["products"]
    assert products["apartments"] == [25, 25, 25, 25]
    assert products["ground_commercial"] == [25, 25, 25, 25]
    assert products["underground_parking"] == pytest.approx([
        15.34755677907777,
        36.16655196145905,
        15.313145216792842,
        33.17274604267034,
    ])
    # Нулевой продукт не должен появляться в таблице очередности.
    assert "storage" not in products
