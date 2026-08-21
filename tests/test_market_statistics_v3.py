from fastapi import FastAPI
from fastapi.testclient import TestClient

from developaid_cost_structure import build_cost_structure_matrix
from statistics_feature_v2 import _correct_matrix
from statistics_feature_v3 import BUILDING_TOTAL_TO_GBA, _areas, build_normalized_matrix, install


def grodno_matrix():
    areas, fallback = _areas("22032,9", "13710", None, "3629", "", None)
    matrix = _correct_matrix(build_cost_structure_matrix(region="Москва", housing_class="business"))
    return areas, fallback, build_normalized_matrix(matrix, areas, fallback)


def test_project_areas_are_derived_without_duplicate_building_input():
    areas, fallback, _ = grodno_matrix()
    assert fallback is False
    assert areas["apartments_sqm"] == 13710
    assert areas["building_total_sqm"] == 22032.9 * BUILDING_TOTAL_TO_GBA
    assert areas["above_ground_gns_sqm"] == 22032.9 - 3629


def test_normalized_matrix_keeps_all_major_source_groups():
    _, _, payload = grodno_matrix()
    labels = {x["label"] for x in payload["groups"]}
    assert "Гродненская" in labels
    assert "CORE.XP" in labels
    assert "Москомэкспертиза / НЦСМ" in labels
    assert "АЦ Москвы / декларации" in labels
    assert "СИС / ЕРЗ" in labels


def test_sis_is_mapped_only_where_source_has_numeric_disclosure():
    _, _, payload = grodno_matrix()
    by_key = {x["key"]: x for x in payload["rows"]}

    tu = next(x for x in by_key["technical_connection"]["values"] if x["label"] == "СИС / ЕРЗ")
    combined = next(x for x in by_key["networks_landscaping"]["values"] if x["label"] == "СИС / ЕРЗ")
    ext = next(x for x in by_key["external_utilities"]["values"] if x["label"] == "СИС / ЕРЗ")
    landscaping = next(x for x in by_key["landscaping"]["values"] if x["label"] == "СИС / ЕРЗ")
    land = next(x for x in by_key["land"]["values"] if x["label"] == "СИС / ЕРЗ")
    full = next(x for x in by_key["full_development_cost"]["values"] if x["label"] == "СИС / ЕРЗ")

    assert tu["value"] is not None and tu["grade"] == "C"
    assert combined["value"] is not None and combined["grade"] == "C"
    assert land["value"] is not None and land["grade"] == "C"
    assert full["value"] is not None
    assert ext["value"] is None
    assert landscaping["value"] is None


def test_moscow_and_core_totals_are_visible_on_common_gns_row():
    _, _, payload = grodno_matrix()
    row = next(x for x in payload["rows"] if x["key"] == "construction_capex")
    values = {x["label"]: x for x in row["values"]}
    assert values["Гродненская"]["value"] is not None
    assert values["CORE.XP"]["value"] is not None
    assert values["Москомэкспертиза / НЦСМ"]["value"] is not None
    assert values["АЦ Москвы / декларации"]["value"] is not None
    assert values["Москомэкспертиза / НЦСМ"]["grade"] == "C"
    assert values["АЦ Москвы / декларации"]["grade"] == "C"
    assert row["n"] >= 4


def test_page_has_no_manual_building_area_and_is_not_blank_by_default():
    app = FastAPI()
    install(app)
    client = TestClient(app)
    response = client.get("/statistics")
    assert response.status_code == 200
    assert "Москомэкспертиза / НЦСМ" in response.text
    assert "СИС / ЕРЗ" in response.text
    assert "Наружные сети + благоустройство (совместно)" in response.text
    assert "Общая площадь здания</label>" not in response.text
    assert "22032.9" in response.text
    assert "13710" in response.text
    assert "3629" in response.text
    assert "На первом открытии подставлен тестовый пример" in response.text
