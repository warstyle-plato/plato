"""Тесты единого ввода кадастрового номера.

Поле одно на всю страну: методику выбирает маршрутизатор, а не пользователь.
Кадастр 50:* может быть Новой Москвой, поэтому префикс ничего не решает —
сначала ГлавАПУ. Справочники УПКС и Кср зашиты в поставку.
Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core


def test_page_has_one_cadastral_input():
    """Один вход на всю страну: отдельных полей для Москвы и области нет."""
    page = main.PAGE
    assert page.count('id="cadastralNumbers"') == 1
    assert 'id="moQuery"' not in page
    assert 'id="landQuery"' not in page
    assert 'id="moCalcButton"' not in page
    assert 'id="landLookupButton"' not in page
    assert 'onclick="obtainTep()"' in page


def test_router_tries_glavapu_before_the_region():
    page = main.PAGE
    assert "async function obtainTep()" in page
    # Префикс 50: сам по себе не выбирает область — сначала ГлавАПУ.
    assert "const insideMoscow=!!((analysis||{}).territory||{}).inside_moscow;" in page
    assert "if(insideMoscow)return obtainCadastralTep(analysis);" in page
    assert "if(regionOnly)return calculateMo(raw);" in page


def test_ksr_reference_is_built_in_and_not_uploaded():
    """Справочник Кср зашит в поставку, грузить его пользователю не нужно."""
    page = main.PAGE
    assert 'id="moPriceFile"' not in page
    assert 'id="moPricePeriod"' not in page
    assert "uploadMoPrices" not in page
    reference = main.mo_reference()["market_price"]
    assert reference["count"] == 56
    assert reference["region_average"] > 0
    assert "114-Р" in reference["document"]


def test_region_parameters_are_reference_values_and_editable():
    page = main.PAGE
    assert 'id="moParamsBox"' in page
    assert "справочно" in page
    for field in ("moDensity", "moDistrict", "moPrice", "moKd", "moFlat", "moArea"):
        assert f'id="{field}"' in page
    # Ответ сервера возвращается в поля, чтобы было видно подставленное.
    assert "function syncMoParams(data)" in page


def test_ksr_comes_from_the_reference_without_being_passed_in():
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=6.6667, district="Мытищи"))
    assert result["vri"]["market_price_rub_per_sqm"] == pytest.approx(238052.0)
    assert result["territory"]["district"] == "Городской округ Мытищи"


def test_explicit_price_still_wins_over_the_reference():
    result = main.mo_calculate(main.MoCalculateRequest(
        site_area_ha=6.6667, district="Мытищи", market_price_rub_per_sqm=300000
    ))
    assert result["vri"]["market_price_rub_per_sqm"] == pytest.approx(300000.0)
