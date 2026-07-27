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


# --- Кср определяется округом, а не вводится руками -------------------------

def test_reference_carries_ksr_for_every_district():
    """Интерфейс должен показать Кср сразу при выборе округа, без расчёта."""
    districts = main.mo_reference()["districts"]
    assert len(districts) == 60
    assert all(item["market_price_rub_per_sqm"] for item in districts)
    by_name = {item["name"]: item for item in districts}
    assert by_name["Городской округ Мытищи"]["market_price_rub_per_sqm"] == pytest.approx(238052.0)
    assert by_name["Богородский городской округ"]["market_price_rub_per_sqm"] == pytest.approx(131783.0)
    assert by_name["Городской округ Серебряные Пруды"]["market_price_rub_per_sqm"] == pytest.approx(77041.0)


def test_district_without_a_decree_row_falls_back_to_the_region_average():
    prices = {item["name"]: item for item in main.mo_reference()["districts"]}
    region = [item for item in prices.values() if item["market_price_basis"] != "округ"]
    for item in region:
        assert item["market_price_rub_per_sqm"] == pytest.approx(198907.0)


def test_ksr_field_is_read_only_with_an_explicit_override():
    page = main.PAGE
    assert 'id="moPrice" value="" step="1000" readonly' in page
    assert 'id="moPriceManual"' in page
    assert "function syncMoPrice()" in page
    assert "function toggleMoPrice()" in page
    # В расчёт цена уходит только когда её задали руками.
    assert "(document.getElementById('moPriceManual')||{}).checked" in page


# --- коэффициент доходности Кд ---------------------------------------------

def test_kd_comes_from_table_3_of_decree_1745():
    """Три группы округов: 10, 5 и 1 процент."""
    assert main._mo_vri_kd_for("Городской округ Мытищи")[0] == pytest.approx(0.10)
    assert main._mo_vri_kd_for("Городской округ Восход (ЗАТО)")[0] == pytest.approx(0.05)
    assert main._mo_vri_kd_for("Богородский городской округ")[0] == pytest.approx(0.01)
    assert main._mo_vri_kd_table()["values"].__len__() == 56


def test_kd_reference_is_exposed_per_district():
    districts = {item["name"]: item for item in main.mo_reference()["districts"]}
    assert districts["Городской округ Химки"]["vri_kd"] == pytest.approx(0.10)
    assert districts["Городской округ Истра"]["vri_kd"] == pytest.approx(0.05)
    assert districts["Городской округ Шатура"]["vri_kd"] == pytest.approx(0.01)
    assert "1745" in main.mo_reference()["vri_kd"]["document"]


def test_district_missing_from_table_3_is_not_guessed():
    """Подставлять чужую группу нельзя: Кд умножает плату на миллиарды."""
    kd, _document, basis = main._mo_vri_kd_for("Городской округ Пущино")
    assert kd is None
    assert basis == "округа нет в таблице 3"
    result = main.mo_calculate(main.MoCalculateRequest(site_area_ha=6.6667, district="Пущино"))
    assert any("1745" in text for text in result["warnings"])
    assert result["vri"]["kd_basis"] == "округа нет в таблице 3"


def test_kd_changes_the_payment():
    mytishchi = main.mo_calculate(main.MoCalculateRequest(site_area_ha=6.6667, district="Мытищи"))
    voskhod = main.mo_calculate(main.MoCalculateRequest(site_area_ha=6.6667, district="Восход"))
    assert mytishchi["vri"]["kd"] == pytest.approx(0.10)
    assert voskhod["vri"]["kd"] == pytest.approx(0.05)


def test_explicit_kd_wins_over_the_table():
    result = main.mo_calculate(main.MoCalculateRequest(
        site_area_ha=6.6667, district="Мытищи", vri_kd=0.03
    ))
    assert result["vri"]["kd"] == pytest.approx(0.03)
    assert result["vri"]["kd_basis"] == "задан вручную"


def test_kd_field_is_read_only_with_an_explicit_override():
    page = main.PAGE
    assert 'id="moKd" value="" step="0.01" readonly' in page
    assert 'id="moKdManual"' in page
    assert "function syncMoKd()" in page
    assert "(document.getElementById('moKdManual')||{}).checked" in page
