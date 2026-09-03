"""Средняя квартира — один ответ с названным основанием, а не четыре числа.

«Пока руками, на самом деле рынок где-то в районе 60 и должен быть. Там где мы
сами вручную собираем, пусть будет 60, там где подгружаем из АПУ — как в АПУ,
если Подмосковье по кадастру или адресу — РНГП Подмосковья» (владелец,
03.09.2026).

Делителей было четыре и ни один не назывался: рынок соседей (36 м² на живом
примере), 58,75 без источника вовсе, норматив Москвы 69,3 и строка 5 выгрузки
ГлавАПУ. На 136 818 м² квартир это от 1 975 до 3 800 лотов, и на экране они
выглядели одинаково достоверно.

Норматив Москвы 33 × 2,1 из этого списка вычеркнут по существу: он меряет
НАСЕЛЕНИЕ — по нему считают жителей, соцнагрузку и машино-места, — а нарезку
лотов делает рынок. Число 58,75 не имело источника вообще.

Запуск: python3 -m pytest tests/test_the_average_flat_names_its_source.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402


def test_the_manual_yardstick_is_the_market_sixty():
    """Собираем сами — 60 м², и решение владельца названо прямо в основании."""
    value, basis = core.average_flat_sqm("manual")
    assert value == 60.0
    assert "рынок" in basis and "03.09.2026" in basis, basis


def test_the_region_yardstick_comes_from_the_regional_norms():
    """Подмосковье — РНГП области, а не число без источника: 28 × 2,1."""
    value, basis = core.average_flat_sqm("mo")
    assert value == pytest.approx(
        core.MO_NORMS_DEFAULT["living_space_per_person_sqm"] * 2.1, abs=0.01)
    assert "РНГП Московской области" in basis, basis
    # Размер домовладения РНГП области не называет — он взят из 2118-ПП, и это
    # сказано вслух: подставленное молча число из чужого документа неотличимо
    # от числа этого.
    assert "2118-ПП" in basis, basis


def test_an_unknown_source_falls_back_to_the_named_one():
    """Неизвестный источник — это ручная сборка с её основанием, а не молчание."""
    assert core.average_flat_sqm("что-то ещё") == core.average_flat_sqm("manual")


def test_the_number_without_a_source_is_gone():
    """58,75 стояло пятью литералами и ни одним основанием."""
    for path in (ROOT / "main_legacy.py",):
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("#", "//")))
        assert "58.75" not in code, f"{path.name}: литерал вернулся"


def test_the_page_takes_it_from_the_engine():
    """Копию негде обновлять, потому что копии нет: то же правило, что у VERSION."""
    page = core.PAGE
    assert core.AVERAGE_FLAT_PLACEHOLDER not in page, "плейсхолдер не подставлен"
    assert '"basis"' in page or "'basis'" in page
    assert str(core.AVERAGE_FLAT_MANUAL_SQM) in page


def test_the_free_form_tep_counts_flats_by_the_market():
    """Норматив Москвы меряет население; квартиры собранного руками ТЭП — рынок."""
    tep = core.build_freeform_tep("", {
        "site_area_ha": 5.0, "apartments_saleable_sqm": 136818.0})
    flat, basis = core.average_flat_sqm("manual")
    units = tep["tep"]["apartments"]["units"]
    assert units == pytest.approx(136818 / flat, abs=1.0), units
    # Прежний порядок дал бы 1 975 — норматив населения, а не рыночный лот.
    assert units != 1975
    said = " ".join(tep.get("calculated") or [])
    assert basis in said, said


def test_the_population_still_comes_from_the_city_norm():
    """33 м² на человека никуда не делись: соцнагрузка и места считаются ими."""
    tep = core.build_freeform_tep("", {
        "site_area_ha": 5.0, "apartments_saleable_sqm": 136818.0})
    said = " ".join(tep.get("calculated") or [])
    assert "33 м²" in said, said


def test_platon_knows_which_yardstick_is_whose():
    """Правило, которого нет у Платона, он выдумает — а выдумка выглядит как ответ."""
    rules = {item["id"]: item["rule"] for item in core._DevelopAid_METHODOLOGY}
    rule = rules["AVERAGE_FLAT"]
    for word in ("60", "ГлавАПУ", "РНГП", "58,8", "69,3", "НАСЕЛЕНИЯ"):
        assert word in rule, word
