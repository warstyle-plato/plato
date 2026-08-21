from fastapi import FastAPI
from fastapi.testclient import TestClient

from developaid_cost_structure import build_cost_structure_matrix
from statistics_feature_v2 import _correct_matrix
from statistics_feature_v3 import _areas, build_normalized_matrix, install


def grodno_matrix():
    areas, fallback = _areas("22032,9", "13710", "13429", "3629", "", "")
    matrix = _correct_matrix(build_cost_structure_matrix(region="Москва", housing_class="business"))
    return areas, fallback, build_normalized_matrix(matrix, areas, fallback)


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

    assert tu["value"] is not None and tu["grade"] == "C"
    assert combined["value"] is not None and combined["grade"] == "C"
    assert ext["value"] is None
    assert landscaping["value"] is None


def test_moscow_ncsm_appears_as_comparable_control_total():
    _, _, payload = grodno_matrix()
    row = next(x for x in payload["rows"] if x["key"] == "building_control")
    mke = next(x for x in row["values"] if x["label"] == "Москомэкспертиза / НЦСМ")
    assert mke["value"] is not None
    assert mke["grade"] in {"A", "B"}


def test_page_explains_normalized_table_not_audit_log():
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
            "apartments_sqm": "13429",
            "underground_gns_sqm": "3629",
            "above_ground_gns_sqm": "",
        },
    )
    assert response.status_code == 200
    assert "Москомэкспертиза / НЦСМ" in response.text
    assert "СИС / ЕРЗ" in response.text
    assert "Наружные сети + благоустройство (совместно)" in response.text
    assert "Пусто =" not in response.text
