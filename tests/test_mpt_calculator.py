"""Расчёт льготы МПТ — по тексту 1874-ПП, а не по неизвестному источнику.

Прежняя версия множила льготу на «Ксрок» 1,00–1,10, брала Кмест 0,7 для офиса
и 0,8 для производства и переопределяла его таблицей из 99 кадастровых
кварталов. Ни Ксрока, ни таких коэффициентов, ни кварталов в постановлении
нет: поиск `77:\\d\\d:\\d{6}` по всем 37 страницам даёт ноль совпадений, слова
«Ксрок» и «срок реализации» не встречаются. Откуда взялись прежние числа,
установить не удалось.

На спальном районе это завышало льготу вдвое: офис в Ясеневе шёл с Кмест 0,7,
хотя приложение 3 даёт 0,75 по графе 2 — но ещё и Ксрок сверху, а главное,
такие проекты внутри ТТК вообще не получают статуса.

Здесь проверяется то, что можно показать пальцем в документе.

Запуск: python3 -m pytest tests -q
"""

from datetime import date

import pytest

from mpt_calculator import (
    ALL_DISTRICTS,
    HOTEL_ROOMS_MIN_SHARE,
    KMEST_GROUPS,
    KZATR_DEFAULT,
    MIXED_USE_MIN_AREA_SQM,
    MptCalculationError,
    MptInput,
    calculate_mpt_benefit,
    canonical_district,
    kmest_for,
    metadata,
)

TODAY = date(2026, 8, 8)


def calc(**kwargs):
    base = dict(category="office", district="Ясенево", area_sqm=10_000.0,
                ttk_position="outside")
    return calculate_mpt_benefit(MptInput(**{**base, **kwargs}), today=TODAY)


# --- формула -----------------------------------------------------------------

def test_the_formula_has_no_kterm():
    """П. 1.14.1: Льгота = 1000 × Sмпт × Кзатр × Кмест. Множителя срока нет."""
    result = calc()
    expected = 1000.0 * 10_000.0 * KZATR_DEFAULT * 0.75
    assert result.benefit_rub == pytest.approx(expected)
    assert "Ксрок" not in result.formula


def test_the_ons_factor_applies_once():
    """П. 1.14.2: × (1 − Кгт/100), один раз."""
    result = calc(mode="ons", ons_readiness_pct=25,
                  ons_registered_before_2019_11_01=True)
    assert result.readiness_factor == 0.75
    assert result.benefit_rub == pytest.approx(
        1000.0 * 10_000.0 * 0.75 * KZATR_DEFAULT * 0.75)


def test_the_ons_needs_registration_before_november_2019():
    with pytest.raises(MptCalculationError):
        calc(mode="ons", ons_readiness_pct=10)


def test_the_kzatr_is_an_input_because_the_decree_does_not_set_it():
    """П. 1.14.1 отсылает к правовому акту ДИиПП: по тексту постановления
    значение не проверяется, поэтому его можно задать."""
    result = calc(kzatr=200.0)
    assert result.kzatr == 200.0
    assert result.benefit_rub == pytest.approx(1000.0 * 10_000.0 * 200.0 * 0.75)
    assert any("ДИиПП" in warning for warning in calc().warnings)


# --- Кмест по приложению 3 ----------------------------------------------------

@pytest.mark.parametrize("district,business,social,hotel", [
    ("Арбат", 0.0, 0.0, 0.5),
    ("Тверской", 0.0, 0.0, 0.5),
    ("Басманный", 0.0, 0.0, 0.5),
    ("Хамовники", 0.0, 0.0, 0.5),
    ("Академический", 0.33, 0.3, 0.5),
    ("Южнопортовый", 0.33, 0.3, 0.5),
    ("Раменки", 0.5, 0.3, 0.5),
    ("Щукино", 0.5, 0.3, 0.5),
    ("Ясенево", 0.75, 0.3, 0.5),
    ("Марьино", 0.75, 0.3, 0.5),
    ("Щербинка", 0.9, 0.3, 0.5),
    ("Вороновское", 0.9, 0.3, 0.5),
])
def test_kmest_matches_the_table(district, business, social, hotel):
    assert kmest_for("office", district)[0] == business
    assert kmest_for("industrial", district)[0] == business
    assert kmest_for("sport", district)[0] == social
    assert kmest_for("hotel", district)[0] == hotel


def test_the_table_has_six_rows_and_rises_outwards():
    """Ряд по графе 2 монотонно растёт от центра к ТиНАО — по нему и была
    восстановлена разбивка строк, разорванных переносом страниц в PDF."""
    business = [values["business"] for values, _names in KMEST_GROUPS]
    assert business == [0.0, 0.0, 0.33, 0.5, 0.75, 0.9]
    assert all(values["hotel"] == 0.5 for values, _names in KMEST_GROUPS)


def test_every_district_belongs_to_exactly_one_row():
    seen: dict[str, int] = {}
    for index, (_values, names) in enumerate(KMEST_GROUPS):
        for name in names:
            assert name not in seen, (name, seen.get(name), index)
            seen[name] = index
    assert len(seen) == len(ALL_DISTRICTS)


def test_an_unknown_district_is_refused():
    with pytest.raises(MptCalculationError):
        kmest_for("office", "Атлантида")


def test_legacy_settlement_names_still_resolve():
    """Прежняя версия звала поселения ТиНАО по-районному. Сохранённый проект
    не должен падать — но и считаться по другой строке тоже."""
    assert canonical_district("Вороново") == "Вороновское"
    assert kmest_for("office", "Вороново")[0] == 0.9


# --- ТТК как условие, а не коэффициент ----------------------------------------

def test_inside_the_ttk_there_is_no_status():
    """П. 1.2 и 3.5: статус присваивается за внешними границами ТТК."""
    result = calc(ttk_position="inside")
    assert result.eligible_for_status is False
    assert result.benefit_rub == 0.0
    assert any("внутри ТТК" in blocker for blocker in result.blockers)


def test_the_ttk_position_is_required():
    with pytest.raises(MptCalculationError):
        calc(ttk_position=None)


def test_a_hotel_is_the_exception():
    """Единственное исключение из требования по ТТК — гостиницы."""
    result = calc(category="hotel", ttk_position=None, area_sqm=10_000,
                  hotel_rooms_sqm=8_000)
    assert result.eligible_for_status is True
    assert result.benefit_rub > 0


# --- пороги -------------------------------------------------------------------

@pytest.mark.parametrize("category,minimum", [
    ("industrial", 2_000.0), ("social", 2_000.0), ("sport", 2_000.0),
    ("office", 5_000.0), ("hotel", 3_000.0),
])
def test_minimum_areas_follow_the_decree(category, minimum):
    """Пп. 3.1.1, 3.1.2 и 4.2."""
    assert metadata()["minimum_area_sqm"][category] == minimum


def test_mixed_use_raises_the_threshold_to_five_thousand():
    """П. 3.1.3: назначение сразу по нескольким ВРИ из 3.1.1 и 3.1.2."""
    assert MIXED_USE_MIN_AREA_SQM == 5_000.0
    result = calc(category="industrial", area_sqm=4_000, mixed_use=True)
    assert result.minimum_area_sqm == 5_000.0
    assert result.eligible_for_status is False


def test_below_the_minimum_the_benefit_is_zero_but_the_math_is_visible():
    """Прежде недобор порога был предупреждением, а не отказом: объект на
    4 000 м² при пороге 5 000 показывал полмиллиарда рублей."""
    result = calc(area_sqm=4_000)
    assert result.eligible_for_minimum is False
    assert result.benefit_rub == 0.0
    assert result.potential_benefit_rub > 0
    assert any("ниже минимума" in blocker for blocker in result.blockers)


# --- гостиница ----------------------------------------------------------------

def test_a_hotel_needs_three_quarters_of_rooms():
    """П. 4.2: доля номерного фонда не менее 75%."""
    assert HOTEL_ROOMS_MIN_SHARE == 0.75
    result = calc(category="hotel", ttk_position=None, area_sqm=10_000,
                  hotel_rooms_sqm=5_000)
    assert result.eligible_for_status is False
    assert any("Номерной фонд" in blocker for blocker in result.blockers)


def test_a_hotel_without_the_room_figure_is_warned_not_refused():
    result = calc(category="hotel", ttk_position=None, area_sqm=10_000)
    assert result.eligible_for_status is True
    assert any("номерного фонда" in warning for warning in result.warnings)


def test_a_hotel_excludes_only_parking_and_garages():
    result = calc(category="hotel", ttk_position=None, area_sqm=5_000,
                  parking_sqm=200, garages_sqm=100,
                  warehouse_inside_sqm=400, warehouse_yard_sqm=600,
                  hotel_rooms_sqm=4_000)
    assert result.eligible_area_sqm == 4_700
    assert result.warehouse_excluded_sqm == 0


# --- производство и склады ----------------------------------------------------

def test_industrial_warehouse_cap_and_exclusions():
    """Графа 2 исключает склады и складские площадки."""
    result = calc(category="industrial", area_sqm=10_000,
                  parking_sqm=500, garages_sqm=250,
                  warehouse_inside_sqm=3_000, warehouse_yard_sqm=0)
    assert result.warehouse_counted_sqm == 2_500
    assert result.warehouse_excluded_sqm == 500
    assert result.eligible_area_sqm == 8_750


@pytest.mark.parametrize("warehouse,eligible", [(0, 10_000), (2_500, 10_000), (4_000, 8_500)])
def test_the_twenty_five_percent_boundary(warehouse, eligible):
    result = calc(category="industrial", area_sqm=10_000, warehouse_inside_sqm=warehouse)
    assert result.eligible_area_sqm == eligible


def test_a_non_industrial_warehouse_is_excluded_entirely():
    result = calc(category="social", area_sqm=5_000, warehouse_inside_sqm=500)
    assert result.eligible_area_sqm == 4_500
    assert result.warehouse_excluded_sqm == 500


# --- нечисла ------------------------------------------------------------------

@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_numbers_are_refused(value):
    with pytest.raises(MptCalculationError):
        calc(area_sqm=value)
    with pytest.raises(MptCalculationError):
        calc(parking_sqm=value)
