from fastapi import FastAPI
from fastapi.testclient import TestClient

from statistics_feature_v2 import (
    GRODNO_UNDERGROUND_RUB_M2,
    _areas_from_query,
    _correct_matrix,
    _parse_area,
    install,
)
from developaid_cost_structure import build_cost_structure_matrix


def test_blank_and_russian_decimal_area_inputs_are_safe():
    assert _parse_area("") is None
    assert _parse_area("   ") is None
    assert _parse_area("0,02") == 0.02
    assert _parse_area("22 032,9") == 22032.9


def test_above_ground_area_is_inferred_when_blank():
    areas = _areas_from_query("22032,9", "13710", "3629", "")
    assert areas["above_ground_gns_sqm"] == 18403.9


def test_grodno_underground_rate_is_corrected_to_fm_basis():
    matrix = _correct_matrix(build_cost_structure_matrix(region="Москва", housing_class="business"))
    grodno = next(x for x in matrix["sources"] if x["source_id"] == "developaid-grodnenskaya-structure-2026-07")
    assert grodno["cells"]["main_under"]["value_rub_m2"] == GRODNO_UNDERGROUND_RUB_M2


def test_statistics_page_accepts_blank_above_ground_and_renders_normalized_matrix():
    app = FastAPI()
    install(app)
    client = TestClient(app)
    response = client.get(
        "/statistics",
        params={
            "region": "Москва",
            "class": "business",
            "gba_sqm": "22032,9",
            "sellable_sqm": "13710",
            "underground_gns_sqm": "3629",
            "above_ground_gns_sqm": "",
        },
    )
    assert response.status_code == 200
    assert "Нормализованная таблица" in response.text
    assert "18 403,9" in response.text
    assert "210,0" in response.text
