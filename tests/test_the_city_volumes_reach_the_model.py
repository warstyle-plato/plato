"""Объёмы города доезжают до модели целиком, а не одним жильём.

Город даёт три слагаемых — жилое, нежилое и общественно-деловое, — и их сумма
равна общему объёму (проверено на карточках Кунцева и Магистральных улиц).
Скрининг брал из них только жильё: нежилое уходило строкой «не включено», и
площадка считалась заведомо беднее, чем есть. Требование владельца (02.09.2026):
соцобъекты — из решения, когда город их назвал, иначе по нормативу; остаток
нежилого за вычетом соцобъектов — ОСЗ и ТЦ; общественно-деловое — офисы.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auction_search.krt_screening import build_krt_model_screening  # noqa: E402
from market_search.krt_requirements import social_objects_from_decision  # noqa: E402


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("developaid_core", ROOT / "main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["developaid_core"] = module
    spec.loader.exec_module(module)
    return module


def market():
    return {
        "analysis": {"site": {
            "segment": "Бизнес", "price_per_sqm": 450000,
            "sold_lot_avg": 58, "units_per_month": 25,
        }},
        "price_hint": {},
    }


def site(**over):
    project = {
        "slug": "test", "name": "Тестовая площадка", "district": "Хорошёво-Мнёвники",
        "area_ha": 24.5, "total_gfa_sqm": 500_000, "housing_gfa_sqm": 350_000,
        "nonresidential_gfa_sqm": 150_000, "business_gfa_sqm": 0.0,
    }
    project.update(over)
    return project


def test_the_nonresidential_volume_becomes_products(core):
    """Арифметика владельца: 500 всего, 350 жильё, 150 нежилое минус соцобъекты."""
    result = build_krt_model_screening(site(), market(), core, requirements={"available": True})
    programme = result["programme"]
    inputs = result["model_inputs"]["inputs"]
    tep = result["model_inputs"]["tep"]

    assert programme["social_gba_sqm"] > 0
    assert programme["commercial_gba_sqm"] == pytest.approx(
        150_000 - programme["social_gba_sqm"], abs=1.0)
    assert inputs["retail_enabled"] is True
    assert inputs["retail_gba_sqm"] == pytest.approx(programme["commercial_gba_sqm"], abs=1.0)
    # Метры объекта обязаны быть и в ТЭП: иначе ГНС проекта их не считает, и
    # все удельные показатели делятся не на ту площадь.
    assert tep["standalone_retail"]["gns"] == pytest.approx(inputs["retail_gba_sqm"], abs=1.0)
    assert programme["balance"]["matches"] is True


def test_the_business_volume_becomes_offices(core):
    result = build_krt_model_screening(
        site(total_gfa_sqm=700_000, business_gfa_sqm=200_000),
        market(), core, requirements={"available": True})
    inputs = result["model_inputs"]["inputs"]
    assert inputs["offices_enabled"] is True
    assert inputs["offices_gba_sqm"] == pytest.approx(200_000, abs=1.0)
    assert result["model_inputs"]["tep"]["offices"]["gns"] == pytest.approx(200_000, abs=1.0)


def test_the_decision_beats_the_norm(core):
    """Названное городом число мест сильнее нашей формулы."""
    requirements = {
        "available": True, "decision_available": True,
        "construction": [
            "Обеспечить строительство дошкольной образовательной организации на 350 мест.",
        ],
    }
    result = build_krt_model_screening(site(), market(), core, requirements=requirements)
    rows = {row["kind"]: row for row in result["programme"]["social"]}
    assert rows["kindergarten"]["source"] == "decision"
    assert rows["kindergarten"]["places"] == pytest.approx(350)
    assert rows["kindergarten"]["by_norm_places"] != 350
    assert rows["kindergarten"]["quotes"]
    # Школу город не называл — она осталась нормативом, а не исчезла.
    assert rows["school"]["source"] == "norm"
    assert result["model_inputs"]["inputs"]["kindergarten_places"] == pytest.approx(350)
    assert result["model_inputs"]["inputs"]["social_mode"] == "Строительство"


def test_an_object_named_without_capacity_still_gets_counted(core):
    """Объект назван, мощность нет: считаем нормативом и говорим, что число наше."""
    requirements = {
        "available": True, "decision_available": True,
        "construction": ["Предусмотреть строительство общеобразовательной организации."],
    }
    result = build_krt_model_screening(site(), market(), core, requirements=requirements)
    rows = {row["kind"]: row for row in result["programme"]["social"]}
    assert rows["school"]["source"] == "norm_after_named"
    assert rows["school"]["places"] > 0
    assert any("мощность" in text for text in result["assumptions"])


def test_a_negative_remainder_is_a_finding_not_a_zero(core):
    """Соцобъекты больше нежилого — это находка, а не ноль."""
    result = build_krt_model_screening(
        site(nonresidential_gfa_sqm=1_000, total_gfa_sqm=351_000),
        market(), core, requirements={"available": True})
    programme = result["programme"]
    assert programme["commercial_negative"] is True
    assert programme["commercial_gba_sqm"] < 0
    assert result["model_inputs"]["inputs"]["retail_enabled"] is False
    assert any("больше всего нежилого" in text for text in result["exclusions"])


def test_the_sum_that_does_not_match_is_named(core):
    result = build_krt_model_screening(
        site(total_gfa_sqm=900_000), market(), core, requirements={"available": True})
    assert result["programme"]["balance"]["matches"] is False
    assert any("не сходятся" in text for text in result["exclusions"])


def test_the_site_area_travels_with_the_model(core):
    result = build_krt_model_screening(site(), market(), core, requirements={"available": True})
    assert result["model_inputs"]["inputs"]["site_area_ha"] == pytest.approx(24.5)


def test_a_kindergarten_is_not_read_as_a_school():
    """«дошкольн» содержит «школ» подстрокой — садик обязан проверяться первым."""
    found = social_objects_from_decision([
        "Дошкольная образовательная организация на 125 мест.",
    ])
    assert [item["kind"] for item in found] == ["kindergarten"]


def test_machine_places_are_not_school_places():
    found = social_objects_from_decision([
        "Общеобразовательная организация и подземный паркинг на 250 машино-мест.",
    ])
    assert found and found[0]["kind"] == "school"
    assert found[0]["places"] is None


def test_a_playground_is_not_a_kindergarten():
    assert social_objects_from_decision(["Благоустройство детских игровых площадок."]) == []


def test_the_norm_is_declared_once(core):
    """Норматив мест на тысячу берётся у движка, а не копируется в модуль."""
    assert core.moscow_social_places("school", 1000, zone_two=False) == pytest.approx(90.0)
    assert core.moscow_social_places("school", 1000, zone_two=True) == pytest.approx(124.0)
    source = (ROOT / "auction_search" / "krt_screening.py").read_text(encoding="utf-8")
    for number in ("44", "63", "90", "124"):
        assert f"{number} *" not in source


def test_the_area_per_place_is_a_step_not_a_number(core):
    """РНГП: площадь на место — ступень по ёмкости здания (редакция 2579-ПП)."""
    assert core.moscow_social_area_per_place("kindergarten", 100) == 27.0
    assert core.moscow_social_area_per_place("kindergarten", 200) == 18.0
    assert core.moscow_social_area_per_place("kindergarten", 400) == 16.0
    assert core.moscow_social_area_per_place("school", 300) == 18.0
    assert core.moscow_social_area_per_place("school", 900) == 15.0
    assert core.moscow_social_area_per_place("school", 1200) == 13.0
    # Поликлиники в документе нет: «не знаем» и «нормы не существует» — разные
    # ответы, и выдавать одно за другое нельзя.
    assert core.moscow_social_area_per_place("clinic", 300) is None


def test_the_city_norm_beats_the_flat_input(core):
    """Поле вводных несёт одно число на любую ёмкость — норматив города сильнее."""
    result = build_krt_model_screening(site(), market(), core, requirements={"available": True})
    rows = {row["kind"]: row for row in result["programme"]["social"]}
    inputs = result["model_inputs"]["inputs"]
    school = rows["school"]
    assert school["norm_is_the_citys"] is True
    assert school["norm_sqm_per_place"] == core.moscow_social_area_per_place(
        "school", school["places"])
    # Норматив записан в то же поле: страница обязана показывать, чем посчитано.
    assert inputs["social_school_norm_sqm"] == school["norm_sqm_per_place"]
    assert school["gba_sqm"] == pytest.approx(school["places"] * school["norm_sqm_per_place"], abs=1)
    # У поликлиники норматива города нет — остаётся вводное поле, и это сказано.
    assert rows["clinic"]["norm_is_the_citys"] is False


def test_a_district_written_without_yo_is_still_zone_two(core):
    """Город пишет «Бирюлево», список хранился с «ё» — район терял свою зону."""
    assert core.district_zone_two("Бирюлево Восточное") is True
    assert core.district_zone_two("Бирюлёво Восточное") is True
    assert core.district_zone_two("Кунцево") is False
    dense = build_krt_model_screening(
        site(district="Бирюлево Восточное"), market(), core, requirements={"available": True})
    plain = build_krt_model_screening(
        site(district="Кунцево"), market(), core, requirements={"available": True})
    assert dense["programme"]["city"]["zone_two"] is True
    school_two = next(r for r in dense["programme"]["social"] if r["kind"] == "school")
    school_one = next(r for r in plain["programme"]["social"] if r["kind"] == "school")
    assert school_two["places"] > school_one["places"]
