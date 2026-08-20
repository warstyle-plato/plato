"""Пересчёт под фактический ТЭП: соцнагрузка, машино-места, плата за ВРИ.

Калькулятор ГлавАПУ считает по НОРМАТИВНОМУ ТЭП — плотность на площадь участка.
У людей на руках бывает решение ГЗК, где метров в разы меньше: тогда ответ
калькулятора для этого проекта неверен, а правка ТЭП руками ничего не
пересчитывала — социалка, ВРИ и машино-места оставались нормативными и
завышенными кратно (владелец, 20.08.2026).

Формулы городские и сверены на выгрузке штатного калькулятора по участку
77:01:0004023 от 20.08.2026: население 2355, ДОО 104, школа 212, поликлиника
45, постоянные места 897, гостевые 90, приобъектные 12, плата за ВРИ
10 562,660 млн ₽.

Запуск: python3 -m pytest tests/test_recalc_under_the_approved_tep.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as wrapper  # noqa: E402

core = wrapper.core

# Основания квартала 77:01:0004023 с листа «Параметры территории».
K1, K2, RENT = 0.75, 0.2, 0.1497
BASE_MKD, BASE_TRADE = 287560.46, 194737.19
UPKS = 123876.46


@pytest.fixture()
def client():
    return TestClient(core.app)


def test_the_formulas_reproduce_the_city_export():
    """Сверка на нормативном расчёте: если не сходится здесь, спорить не о чем."""
    norms = core.tep_derived_norms(
        apartment_area_sqm=77696, residential_living_spp_sqm=119533,
        nonresidential_np_sqm=6867, k1=K1, k2=K2, upks_rub=UPKS)
    assert norms["population"] == 2355
    assert norms["kindergarten_places"] == 104
    assert norms["school_places"] == 212
    assert norms["clinic_capacity"] == 45
    assert norms["parking_permanent"] == 897
    assert norms["parking_guest"] == 90
    assert norms["parking_onsite"] == 12

    payment = core.vri_manual_payment(
        [{"type": "mkd", "spp_sqm": 127163, "base_cost_rub": BASE_MKD}], RENT)
    assert abs(payment["total_mln"] - 10562.660) / 10562.660 < 1e-4


def test_the_permanent_places_come_from_the_living_area():
    """Постоянные места считаются от НП жилой, а не от СПП жилых зданий.

    От полной СПП (119 533 + 7 630) выходит 954 места вместо 897 — разница не
    косметическая, а на 57 мест подземного гаража.
    """
    living = core.tep_derived_norms(apartment_area_sqm=77696,
                                    residential_living_spp_sqm=119533, k1=K1)
    whole = core.tep_derived_norms(apartment_area_sqm=77696,
                                   residential_living_spp_sqm=127163, k1=K1)
    assert living["parking_permanent"] == 897
    assert whole["parking_permanent"] == 954


def test_the_approved_tep_costs_less_than_the_norm(client):
    """Ради этого всё и затевалось: утверждённый ГЗК ТЭП дешевле норматива."""
    answer = client.post("/tep/derived", json={
        "apartment_area_sqm": 10621, "residential_living_spp_sqm": 17220,
        "nonresidential_np_sqm": 59433, "k1": K1, "k2": K2, "upks_rub": UPKS})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    # Решение ГЗК от 14.05.2026 № 14 п. 88.2 называет 15 / 30 / 7 — наши
    # 15 / 29 / 7 отличаются на единицу округления населения (322 против 327).
    assert data["kindergarten_places"] == 15
    assert data["school_places"] in (29, 30)
    assert data["clinic_capacity"] == 7
    assert data["parking_total"] == 243
    assert 480 < data["compensation_mln"] < 500
    assert data["jobs"] > 1000, "МПТ — основание льготы, и их тут много"


def test_a_missing_upks_is_not_a_free_compensation():
    """Без УПКС компенсация не считается, и ноль здесь означал бы «бесплатно»."""
    data = core.tep_derived_norms(apartment_area_sqm=10621,
                                  residential_living_spp_sqm=17220, k1=K1)
    assert data["compensation_mln"] == 0.0
    assert data["missing"], "молчаливый ноль хуже отсутствия ответа"


def test_the_manual_payment_is_charged_by_use_type(client):
    """Каждый тип использования — своя базовая стоимость, как в выгрузке."""
    answer = client.post("/vri/manual", json={"rent_coeff": RENT, "rows": [
        {"type": "mkd", "spp_sqm": 17220, "base_cost_rub": BASE_MKD},
        {"type": "trade", "spp_sqm": 65000, "base_cost_rub": BASE_TRADE}]})
    assert answer.status_code == 200, answer.text
    data = answer.json()
    assert [line["type"] for line in data["lines"]] == ["mkd", "trade"]
    assert abs(data["lines"][0]["payment_mln"] - 1430.356) < 0.01
    assert abs(data["total_mln"] - 5086.675) < 0.01
    assert "1,8964" in data["basis"] and "0,1497" in data["basis"]


def test_a_zero_base_is_free_and_a_missing_base_is_not():
    """У производства и соцобъектов базовая ноль — за них не платят. Пустая
    базовая — другое дело: это «не знаем», и строка уходит в missing."""
    free = core.vri_manual_payment(
        [{"type": "social", "spp_sqm": 5000, "base_cost_rub": 0}], RENT)
    assert free["total_mln"] == 0.0 and not free["missing"]

    unknown = core.vri_manual_payment([{"type": "office", "spp_sqm": 5000}], RENT)
    assert unknown["total_mln"] == 0.0 and unknown["missing"]


def test_the_page_asks_the_server_and_says_whose_answer_it_is():
    page = core.PAGE
    assert "Пересчитать под фактический ТЭП" in page
    assert "'/tep/derived'" in page and "'/vri/manual'" in page
    # Список типов использования подставляется из движка, копии на странице нет.
    assert "__DEVELOPAID_VRI_USE_TYPES__" not in page
    assert "Плата за ВРИ — свой расчёт" in page
    body = page[page.index("async function recalcFromTep("):]
    body = body[:body.index("\n}\n")]
    assert "не ответ калькулятора" in body, "чей это расчёт — сказано вслух"


def test_the_table_does_not_rebuild_itself_while_typing():
    """Перерисовка на каждой правке роняет фокус и теряет соседнюю ячейку —
    поймано браузером на этой же таблице."""
    page = core.PAGE
    body = page[page.index("function vriOwnEdit("):]
    body = body[:body.index("\n}\n")]
    assert "renderVriOwn" not in body, "правка ячейки не пересобирает таблицу"
