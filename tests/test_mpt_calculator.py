"""Расчёт льготы МПТ по действующей редакции 1874-ПП.

Таблица 1 приложения 3 задаёт 0,7 для офисов за ТТК, 0,8 для
производства, спорта, культуры и частного образования. Таблица 2
содержит 99 приоритетных кадастровых кварталов с Кмест 0,8 для офисов.
Коэффициент срока реализации в формуле постановления отсутствует.
"""

from datetime import date

import pytest

from mpt_calculator import (
    ALL_DISTRICTS,
    HOTEL_ROOMS_MIN_SHARE,
    KMEST_GROUPS,
    KZATR_DEFAULT,
    PRIORITY_CADASTRAL_QUARTERS,
    MIXED_USE_MIN_AREA_SQM,
    MptCalculationError,
    MptInput,
    calculate_mpt_benefit,
    canonical_district,
    cadastral_quarter,
    kmest_for,
    kzatr_for_quarter,
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
    expected = 1000.0 * 10_000.0 * KZATR_DEFAULT * 0.7
    assert result.benefit_rub == pytest.approx(expected)
    assert "Ксрок" not in result.formula


def test_the_ons_factor_applies_once():
    """П. 1.14.2: × (1 − Кгт/100), один раз."""
    result = calc(mode="ons", ons_readiness_pct=25,
                  ons_registered_before_2019_11_01=True)
    assert result.readiness_factor == 0.75
    assert result.benefit_rub == pytest.approx(
        1000.0 * 10_000.0 * 0.75 * KZATR_DEFAULT * 0.7)


def test_the_ons_needs_registration_before_november_2019():
    with pytest.raises(MptCalculationError):
        calc(mode="ons", ons_readiness_pct=10)


def test_the_kzatr_is_an_input_because_the_decree_does_not_set_it():
    """П. 1.14.1 отсылает к правовому акту ДИиПП: по тексту постановления
    значение не проверяется, поэтому его можно задать."""
    result = calc(kzatr=200.0)
    assert result.kzatr == 200.0
    assert result.benefit_rub == pytest.approx(1000.0 * 10_000.0 * 200.0 * 0.7)
    assert any("ДИиПП" in warning for warning in calc().warnings)


# --- Кмест по приложению 3 ----------------------------------------------------

@pytest.mark.parametrize("district,business,industrial", [
    ("Арбат", 0.0, 0.0),
    ("Тверской", 0.0, 0.0),
    ("Басманный", 0.7, 0.8),
    ("Хамовники", 0.7, 0.8),
    ("Академический", 0.7, 0.8),
    ("Южнопортовый", 0.7, 0.8),
    ("Раменки", 0.7, 0.8),
    ("Щукино", 0.7, 0.8),
    ("Ясенево", 0.7, 0.8),
    ("Марьино", 0.7, 0.8),
    ("Солнцево", 0.7, 0.8),
    ("Ломоносовский", 0.7, 0.8),
    ("Щербинка", 0.7, 0.8),
    ("Вороново", 0.7, 0.8),
    ("Коммунарка", 0.7, 0.8),
])
def test_kmest_matches_the_current_table(district, business, industrial):
    assert kmest_for("office", district)[0] == business
    assert kmest_for("industrial", district)[0] == industrial
    assert kmest_for("social", district)[0] == 0.3
    assert kmest_for("mededu", district)[0] == 0.3
    assert kmest_for("private_education", district)[0] == 0.8
    assert kmest_for("sport", district)[0] == 0.8
    assert kmest_for("culture", district)[0] == 0.8
    assert kmest_for("hotel", district)[0] == 0.5


def test_the_table_has_three_current_rows_and_separate_category_rates():
    """Действующая таблица 1 делит Москву на три группы, а не шесть."""
    assert len(KMEST_GROUPS) == 3
    assert [values["business"] for values, _names in KMEST_GROUPS] == [0.0, 0.7, 0.7]
    assert [values["industrial"] for values, _names in KMEST_GROUPS] == [0.0, 0.8, 0.8]
    assert all(values["social"] == 0.3 for values, _names in KMEST_GROUPS)
    assert all(values["hotel"] == 0.5 for values, _names in KMEST_GROUPS)


def test_priority_table_contains_all_99_cadastral_quarters():
    assert len(PRIORITY_CADASTRAL_QUARTERS) == 99
    assert "77:07:0012002" in PRIORITY_CADASTRAL_QUARTERS
    assert "77:01:0004042" in PRIORITY_CADASTRAL_QUARTERS


def test_priority_cadastral_quarter_overrides_the_office_district_rate():
    value, source, column = kmest_for("office", "Раменки", "77:07:0012002:123")
    assert value == 0.8
    assert column == "business"
    assert "таблица 2" in source
    assert "77:07:0012002" in source


def test_priority_cadastral_quarter_does_not_override_other_categories():
    assert kmest_for("social", "Раменки", "77:07:0012002:123")[0] == 0.3
    assert kmest_for("industrial", "Раменки", "77:07:0012002:123")[0] == 0.8


def test_solntsevo_regular_quarter_keeps_the_standard_office_rate():
    assert cadastral_quarter("77:07:0015002:42") == "77:07:0015002"
    assert kmest_for("office", "Солнцево", "77:07:0015002:42")[0] == 0.7


@pytest.mark.parametrize("number", ["77:07", "50:07:0012002", "77:07:0012002:abc"])
def test_malformed_cadastral_numbers_are_rejected(number):
    with pytest.raises(MptCalculationError):
        kmest_for("office", "Солнцево", number)


def test_akademichesky_office_uses_the_indexed_q3_value():
    result = calc(district="Академический", area_sqm=32_800,
                  kzatr=kzatr_for_quarter("2026-Q3"), kzatr_quarter="2026-Q3")
    assert result.kzatr == pytest.approx(170.03746)
    assert result.kmest == 0.7
    assert result.benefit_rub == pytest.approx(3_904_060_081.60)


def test_solntsevo_office_benefit_for_125000_square_metres():
    result = calc(district="Солнцево", area_sqm=125_000,
                  kzatr=170.03746, kzatr_quarter="2026-Q3")
    assert result.kmest == 0.7
    assert result.benefit_rub == pytest.approx(14_878_277_750)


def test_priority_office_benefit_uses_the_08_cadastral_rate():
    result = calc(district="Раменки", area_sqm=10_000,
                  cadastral_number="77:07:0012002:123",
                  kzatr=170.03746, kzatr_quarter="2026-Q3")
    assert result.kmest == 0.8
    assert result.benefit_rub == pytest.approx(1_360_299_680)


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
    assert canonical_district("Вороновское") == "Вороново"
    assert kmest_for("office", "Вороновское")[0] == 0.7


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
    result = calc(category="industrial", area_sqm=4_000,
                  area_business_sqm=3_000, area_social_sqm=1_000)
    assert result.minimum_area_sqm == 5_000.0
    assert result.eligible_for_status is False


# --- пропорция по графам 2 и 3 ------------------------------------------------

def test_the_kmest_is_weighted_by_area_across_columns():
    """Примечание к таблице приложения 3: при назначении по нескольким ВРИ
    коэффициенты применяются пропорционально площади с соответствующим видом
    использования. В Ясеневе графа 3 даёт 0,7, графа 4 — 0,3."""
    result = calc(area_sqm=10_000, area_business_sqm=6_000, area_social_sqm=4_000)
    assert result.kmest == pytest.approx((6_000 * 0.7 + 4_000 * 0.3) / 10_000)
    assert result.benefit_rub == pytest.approx(1000.0 * 10_000.0 * KZATR_DEFAULT * result.kmest)


def test_a_single_column_split_equals_the_plain_lookup():
    """Вся площадь по одной графе — то же, что и без разбивки: пропорция не
    должна незаметно менять ответ обычному объекту."""
    plain = calc(area_sqm=10_000)
    split = calc(area_sqm=10_000, area_business_sqm=10_000)
    assert split.kmest == plain.kmest
    assert split.benefit_rub == pytest.approx(plain.benefit_rub)


def test_the_split_must_add_up_to_the_area():
    """Иначе часть площади осталась бы без графы, а льгота — заниженной или
    завышенной ровно на неё."""
    with pytest.raises(MptCalculationError):
        calc(area_sqm=10_000, area_business_sqm=6_000, area_social_sqm=1_000)


def test_the_exclusions_shrink_both_columns_proportionally():
    """Парковка вычитается из Sмпт, а к какой графе относится её площадь,
    постановление не говорит: снимаем пропорционально, иначе выбор «откуда
    вычесть» менял бы льготу."""
    result = calc(area_sqm=10_000, parking_sqm=2_000,
                  area_business_sqm=5_000, area_social_sqm=5_000)
    assert result.eligible_area_sqm == 8_000
    assert result.kmest == pytest.approx((0.7 + 0.3) / 2)
    columns = {column: area for column, area, _value in result.kmest_mix}
    assert columns["business"] == pytest.approx(4_000)
    assert columns["social"] == pytest.approx(4_000)


def test_the_source_line_keeps_its_punctuation():
    """Разделитель тысяч ставился глобальной заменой запятых — она съедала и
    запятые предложения: «Приложение 3  примечание: … 0.7  графа 4»."""
    result = calc(area_sqm=10_000, area_business_sqm=6_000, area_social_sqm=4_000)
    assert result.kmest_source.startswith("Приложение 3, примечание:")
    assert "6 000 м²" in result.kmest_source
    assert ", графа 4" in result.kmest_source


def test_a_hotel_is_not_split_between_columns():
    """Гостиница — графа 5 целиком."""
    with pytest.raises(MptCalculationError):
        calc(category="hotel", ttk_position=None, area_sqm=10_000,
             area_business_sqm=5_000, area_social_sqm=5_000)


# --- Кзатр и его квартал ------------------------------------------------------

def test_the_kzatr_without_a_quarter_is_flagged():
    """Приказ от 10.03.2026: 166,23078 с 01.01.2026, а со второго квартала
    2026 года — корректировка каждый квартал. Зашитое число протухает молча."""
    result = calc()
    assert result.kzatr_quarter == "2026-Q3"
    assert any("квартал" in warning for warning in result.warnings)


def test_a_stale_quarter_is_named():
    result = calc(kzatr=166.23078, kzatr_quarter="2026-Q2")
    assert result.kzatr_quarter == "2026-Q2"
    assert any("2026-Q2" in warning and "2026-Q3" in warning for warning in result.warnings)


def test_the_current_quarter_passes_without_a_warning():
    result = calc(kzatr_quarter="2026-Q3")
    assert not any("квартал" in warning for warning in result.warnings)


def test_before_the_indexation_starts_the_value_needs_no_checking():
    """Индексация начинается со второго квартала 2026 года: до неё значение
    установлено приказом прямо, и требовать сверки не за что."""
    early = calculate_mpt_benefit(
        MptInput(category="office", district="Ясенево", area_sqm=10_000.0,
                 ttk_position="outside"),
        today=date(2026, 2, 1),
    )
    assert early.kzatr_quarter == "2026-Q1"
    assert not any("квартал" in warning for warning in early.warnings)


def test_an_agreement_signed_earlier_freezes_the_coefficient():
    """Переходное положение приказа от 10.03.2026: по ранее заключённому
    соглашению квартальная корректировка не применяется, кроме прироста
    площади и только в его части."""
    result = calc(kzatr_fixed_by_agreement=True)
    assert not any("сверьте действующее значение" in warning for warning in result.warnings)
    frozen = [w for w in result.warnings if "зафиксированным" in w]
    assert frozen and "прироста такой площади" in frozen[0]


def test_the_base_value_comes_from_the_current_edition():
    assert KZATR_DEFAULT == 166.23078
    assert metadata()["kzatr_base"] == 166.23078
    assert metadata()["kzatr_base_from"] == "2026-01-01"
    assert metadata()["kzatr_indexation_from_quarter"] == "2026-Q2"
    assert "10.03.2026" in metadata()["kzatr_source"]
    assert "декабрю 2025" in metadata()["kzatr_source"]


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
    """Графа 6 исключает склады и складские площадки."""
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
