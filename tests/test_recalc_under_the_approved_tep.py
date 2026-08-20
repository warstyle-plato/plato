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
    assert "Пересчитать по параметрам исходного расчёта" in page
    assert "'/tep/recalc-from-baseline'" in page and "'/vri/manual'" in page
    # Список типов использования подставляется из движка, копии на странице нет.
    assert "__DEVELOPAID_VRI_USE_TYPES__" not in page
    assert "Плата за ВРИ — свой расчёт" in page
    body = page[page.index("async function recalcFromTep("):]
    body = body[:body.index("\n}\n")]
    assert "исходного расчёта" in body, "чей это расчёт — сказано вслух"


def test_the_table_does_not_rebuild_itself_while_typing():
    """Перерисовка на каждой правке роняет фокус и теряет соседнюю ячейку —
    поймано браузером на этой же таблице."""
    page = core.PAGE
    body = page[page.index("function vriOwnEdit("):]
    body = body[:body.index("\n}\n")]
    assert "renderVriOwn" not in body, "правка ячейки не пересобирает таблицу"


def test_the_base_costs_come_from_the_export():
    """«Откуда взять базовую стоимость» — первый вопрос человека, и правильный
    ответ на него не объяснение, а заполненное поле.

    Таблица «УПКС и базовые стоимости по типам использования» лежит на листе
    «Параметры территории» выгрузки калькулятора; читали из неё только
    отдельную строку «Базовая стоимость МКД», которой там нет вовсе.
    """
    rows = [
        ["Параметр", "Значение", "Ед.изм."],
        ["Коэффициент аренды", "0,1497", "—"],
        ["УПКС и базовые стоимости по типам использования", "", ""],
        ["Тип использования", "УПКС, руб/м²", "Базовая, тыс.руб/м²"],
        ["МКД (многоэтажный жилой дом)", "123 876,46", "287 560,46"],
        ["Торговля и многофункц.", "111 369,28", "194 737,19"],
        ["Офисы", "103 409,92", "187 578,99"],
        ["Производство", "36 210,4", "0"],
        ["Социальные объекты", "37 575,29", "0"],
    ]
    bases = core._glavapu_base_costs(rows)
    assert bases["mkd"] == 287560.46
    assert bases["trade"] == 194737.19
    assert bases["office"] == 187578.99
    # Ноль здесь осмысленный: за производство и соцобъекты не платят.
    assert bases["industry"] == 0.0 and bases["social"] == 0.0


def test_the_mkd_base_is_found_even_without_its_own_line():
    """Отдельной строки «Базовая стоимость МКД» в выгрузке нет — значение
    берётся из таблицы, иначе основание платы молчит при живых числах."""
    rows = [
        ["Параметр", "Значение", "Ед.изм."],
        ["Тип использования", "УПКС, руб/м²", "Базовая, тыс.руб/м²"],
        ["МКД (многоэтажный жилой дом)", "123 876,46", "287 560,46"],
    ]
    assert core._glavapu_base_costs(rows).get("mkd") == 287560.46


def test_the_page_says_where_the_base_costs_live():
    page = core.PAGE
    assert "Параметры территории" in page
    body = page[page.index("function renderVriOwn("):]
    body = body[:body.index("\n}\n")]
    assert "vriOwnSource" in body
    # Коэффициент аренды — доля; двузначное число завышает плату в сотни раз.
    assert "похож на проценты" in body


def test_a_percent_looking_rent_is_not_calculated_silently():
    page = core.PAGE
    body = page[page.index("async function calcVriOwn("):]
    body = body[:body.index("\n}\n")]
    assert "rent>1" in body
    assert "Не задана базовая стоимость ни по одному типу" in body


def test_an_impossible_rent_coefficient_is_refused_not_confirmed():
    """25 в поле коэффициента аренды дало 238 млрд ₽ платы, и они уехали в
    модель (владелец, 20.08.2026). Коэффициента больше единицы в таблице 2
    приложения 8 не бывает — это не «подтвердите», это отказ."""
    page = core.PAGE
    body = page[page.index("async function calcVriOwn("):]
    body = body[:body.index("\n}\n")]
    assert "if(rent>1){" in body
    assert "не делается" in body
    # И потолок здравого смысла на результат: плата за метр выше базовой
    # стоимости метра означает перепутанный множитель.
    assert "perSqm>500000" in body and "не подставлен" in body


# --- пересчёт по параметрам исходного расчёта -------------------------------
# Второй калькулятор строить не нужно: территория уже посчитана, при правке ТЭП
# меняется количественная база. Ставки снимаются с самой выгрузки — у них нет
# срока годности, и вводить коэффициенты руками (25 вместо 0,1497 дали 238 млрд)
# больше негде.

BASELINE = {
    "residential_spp_sqm": 119533.0, "ground_commercial_spp_sqm": 7630.0,
    "residential_np_sqm": 107580.0, "ground_commercial_np_sqm": 6867.0,
    "apartment_area_sqm": 77696.0, "population": 2355,
    "required_kindergarten_places": 104, "required_school_places": 212,
    "required_clinic_capacity": 45,
    "parking_permanent": 897, "parking_guest": 90, "parking_attached": 12,
    "change_vri_mln": 10562.660,
    "social_compensation_kindergarten_mln": 1140.096,
    "social_compensation_school_mln": 1763.587,
    "social_compensation_clinic_mln": 533.794,
    "vri_base_costs_by_use": {"mkd": 287560.46, "trade": 194737.19,
                              "office": 187578.99, "industry": 0.0, "social": 0.0},
}

APPROVED = {  # решение ГЗК от 14.05.2026 № 14 п. 88.2
    "apartment_area_sqm": 10621.0, "residential_living_spp_sqm": 17220.0,
    "ground_commercial_spp_sqm": 0.0, "nonresidential_np_sqm": 59433.0,
    "nonres_spp_by_use": {"office": 65000.0},
}


def test_the_method_reproduces_the_baseline_on_its_own_tep():
    """Самопроверка обратным ходом: на исходных метрах пересчёт обязан дать
    исходные числа. Не даёт — это расхождение с базой, а не результат."""
    out = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    check = out["self_check"]
    assert check["matches_baseline"] is True, check["mismatch"]
    names = {row["name"]: row for row in check["checked"]}
    # Проверяем то, что считается своей формулой против числа города. Плата за
    # ВРИ и постоянные места по ставке воспроизводят базу тождественно — такая
    # «проверка» ничего не значит, и её тут нет.
    assert names["население"]["recalculated"] == 2355
    assert names["места ДОО"]["recalculated"] == 104
    assert names["места школы"]["recalculated"] == 212
    assert names["мощность поликлиники"]["recalculated"] == 45
    assert names["гостевые машино-места"]["recalculated"] == 90


def test_a_baseline_that_does_not_reproduce_is_named_out_loud():
    """Город сменил методику — ставка базы перестала воспроизводить базу.
    Молча пересчитывать по ней нельзя."""
    # Норматив школ у города стал другим — наша формула это увидит.
    broken = dict(BASELINE, required_school_places=260)
    out = core.recalculate_from_glavapu_baseline(broken, APPROVED)
    assert out["self_check"]["matches_baseline"] is False
    assert any("школы" in text for text in out["self_check"]["mismatch"])
    assert out["warnings"]

    # И правило гостевых мест: десятая часть постоянных.
    broken = dict(BASELINE, parking_guest=200)
    out = core.recalculate_from_glavapu_baseline(broken, APPROVED)
    assert out["self_check"]["matches_baseline"] is False


def test_the_rates_come_from_the_baseline_not_from_constants():
    """Ставки территории снимаются с выгрузки: у зашитых УУПСС свой срок
    годности, и на этом участке они дают 486,9 млн вместо 497,0."""
    out = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    rates = out["rates"]
    assert abs(rates["vri_mln_per_sqm"] - 10562.660 / 127163) < 1e-9
    assert abs(rates["social_mln_per_place"]["kindergarten"] - 1140.096 / 104) < 1e-9
    assert abs(rates["parking_permanent_per_sqm"] - 897 / 107580) < 1e-12


def test_the_mixed_use_payment_is_split_by_function():
    """Общую ставку к нежилому применять нельзя: было 127 163 всё жильё, стало
    17 220 жилья и 65 000 нежилого. Раскладываем по базовым стоимостям базы."""
    out = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    lines = {line["type"]: line for line in out["vri_lines"]}
    assert abs(lines["mkd"]["payment_mln"] - 1430.4) < 1.0
    assert abs(lines["office"]["payment_mln"] - 3521.9) < 1.0
    assert abs(out["vri_total_mln"] - 4952.3) < 1.0
    assert out["vri_total_mln"] < out["baseline"]["vri_mln"]


def test_an_unknown_function_is_not_quietly_an_office():
    """Функции нет в базе — плату по ней разложить не из чего, и молчать нельзя."""
    out = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(APPROVED, nonres_spp_by_use={"hotel": 20000.0}))
    assert any("hotel" in text for text in out["warnings"]), out["warnings"]
    assert all(line["type"] != "hotel" for line in out["vri_lines"])


def test_everything_falls_together_on_the_approved_tep():
    out = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    assert out["population"] == 322
    assert out["places"] == {"kindergarten": 15, "school": 29, "clinic": 7}
    assert 480 < out["compensation_mln"] < 500
    # По 2118-ПП постоянные считаются от площади квартир, а не от наземной
    # жилой: 10 621 / (33 × 2,1) × 0,8 = 123.
    assert out["parking"]["permanent"] == 123
    assert out["parking"]["guest"] == 13
    assert out["parking"]["total"] == out["parking"]["permanent"] + out["parking"]["guest"] + out["parking"]["attached"]
    # Было в исходном расчёте — рядом, чтобы разница была видна.
    assert out["baseline"]["parking_total"] == 999
    assert out["baseline"]["vri_mln"] == 10562.66


def test_the_page_calls_the_baseline_recalculation():
    page = core.PAGE
    assert "Пересчитать по параметрам исходного расчёта" in page
    assert "'/tep/recalc-from-baseline'" in page
    body = page[page.index("async function recalcFromTep("):]
    body = body[:body.index("\n}\n")]
    assert "matches_baseline===false" in body, "несходимость с базой останавливает показ"
    assert "было" in body and "стало" in body


# --- места постоянного размещения по 2118-ПП --------------------------------
# Приложение 5 к 945-ПП изложено в новой редакции постановлением 2118-ПП от
# 05.08.2026. Прежняя наша строка (НП жилая / 90 × К1) на выгрузке давала те же
# 897 мест — и это было совпадением: другой driver и лишний множитель.

def test_the_permanent_places_follow_2118():
    """Пункт 1: Nп = S / (S₁ × 2,1) × D. На выгрузке 77 696 м² квартир — 897."""
    assert core.moscow_permanent_parking_2118(77696) == 897
    assert core.moscow_permanent_parking_2118(10621) == 123
    assert core.moscow_permanent_parking_2118(0) == 0


def test_the_apartment_mix_is_the_second_stage():
    """Пункт 2: F₁×0,8 + F₂×1,2 + F₃×1,6 — когда известен состав квартир."""
    assert core.moscow_permanent_parking_by_mix(158, 0, 0) == 127
    assert core.moscow_permanent_parking_by_mix(100, 40, 18) == 157
    assert core.moscow_permanent_parking_by_mix(0, 0, 0) == 0


def test_the_old_formula_was_right_by_accident():
    """Прежняя строка совпала на базе и разошлась на утверждённом ТЭП.

    НП жилая / 90 × К1 даёт 897 на исходных метрах и 130 на новых; по 2118-ПП
    новых мест 123. Зелёная сверка на одной точке ничего не доказывала.
    """
    import math
    old_on_baseline = math.ceil(107580 / 90 * 0.75)
    old_on_approved = math.ceil(17220 * 0.9 / 90 * 0.75)
    assert old_on_baseline == 897 == core.moscow_permanent_parking_2118(77696)
    assert old_on_approved == 130
    assert core.moscow_permanent_parking_2118(10621) == 123


def test_the_self_check_now_covers_the_permanent_places():
    out = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    names = {row["name"]: row for row in out["self_check"]["checked"]}
    assert names["постоянные машино-места"]["recalculated"] == 897
    assert out["self_check"]["matches_baseline"] is True
    assert out["parking"]["permanent"] == 123
    assert out["parking"]["guest"] == 13
    assert "2118-ПП" in out["parking"]["basis"]


def test_a_baseline_counted_by_the_old_rules_is_named():
    """База, посчитанная по прежней редакции, не воспроизводится новой
    формулой — и это надо сказать, а не пересчитать молча."""
    broken = dict(BASELINE, parking_permanent=672)  # как если бы применили К1
    out = core.recalculate_from_glavapu_baseline(broken, APPROVED)
    assert out["self_check"]["matches_baseline"] is False
    assert any("постоянные" in text for text in out["self_check"]["mismatch"])


def test_the_transition_regime_is_explicit_not_guessed():
    """Переходные положения 2118-ПП (разрешение на строительство, свидетельство
    АГР, одобренная 3D-модель на 05.08.2026, ввод до 01.01.2028) — это выбор
    человека, а не догадка по дате."""
    legacy = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(APPROVED, parking_norm_regime="legacy_945"))
    assert legacy["parking"]["regime"] == "legacy_945"
    assert legacy["parking"]["permanent"] == 130, "прежняя ставка базы"
    assert "945-ПП" in legacy["parking"]["basis"]

    unknown = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(APPROVED, parking_norm_regime="что-то своё"))
    assert unknown["parking"]["regime"] == "2118_2026"
    assert any("режим" in text for text in unknown["warnings"])


def test_a_leased_plot_does_not_get_the_ownership_rate():
    """Ставка снята с расчёта для собственности: калькулятор считает плату
    именно так. Аренда городской земли — другой режим (273-ПП, приложение 8,
    своя повышенная составляющая первого года), и переносить на неё ставку
    собственности нельзя."""
    leased = core.recalculate_from_glavapu_baseline(
        BASELINE, dict(APPROVED, land_right="lease"))
    assert leased["vri_available"] is False
    assert leased["vri_total_mln"] == 0.0
    assert not leased["vri_lines"]
    assert any("аренда" in text for text in leased["warnings"])
    # Соцнагрузка и парковка от права не зависят — их считаем как обычно.
    assert leased["parking"]["permanent"] == 123
    assert 480 < leased["compensation_mln"] < 500

    owned = core.recalculate_from_glavapu_baseline(BASELINE, APPROVED)
    assert owned["vri_available"] is True and owned["vri_total_mln"] > 0


def test_the_page_does_not_substitute_a_refused_payment():
    page = core.PAGE
    body = page[page.index("async function recalcFromTep("):]
    body = body[:body.index("\n}\n")]
    assert "land_right:String(inputs.land_right" in body
    assert "vri_available===false" in body, "отказ виден в списке «было → стало»"
    assert "d.vri_available!==false&&d.vri_total_mln>0" in body, "и не подставляется"
