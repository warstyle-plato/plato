"""Что нашла ревизия перед выкладкой калькулятора МПТ.

Три вещи, каждая проверена на живом приложении, а не на пересказе.

1. `?section=mpt` — единственный вход из Telegram — открывал пустой экран.
   Панель монтировалась в первую попавшуюся `.panel` («Вводные»), а скрипт
   вслепую жал вкладку «ВРИ»; вкладка переключалась, панель оставалась на
   скрытой. Chromium показывал `hostId: inputs`, `activeTab: ВРИ`,
   `hostVisible: false`.

2. `Infinity` в площади проходил проверку «больше нуля», расчёт давал `inf`,
   FastAPI сериализовал его как `null` — интерфейс показывал «0 ₽» с видом
   обычного ответа. `NaN` валил уже сам обработчик ошибки: он клал `nan` в
   тело 422 и получал 500 без объяснения.

3. Объект ниже минимальной площади показывал положительную льготу с
   предупреждением мелким шрифтом: офис 1 000 м² при пороге 5 000 — 116 млн ₽.
   Статуса МПТ такой объект не получает, значит и льготы не создаёт.

Запуск: python3 -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main_registry  # noqa: E402
from mpt_calculator import MptCalculationError, MptInput, calculate_mpt_benefit  # noqa: E402
from mpt_extension import _MPT_FRAGMENT  # noqa: E402


@pytest.fixture(scope="module")
def client():
    return TestClient(main_registry.app, raise_server_exceptions=False)


def calc(**kwargs):
    base = dict(category="office", district="Ясенево", area_sqm=10_000.0,
                ttk_position="outside")
    return calculate_mpt_benefit(MptInput(**{**base, **kwargs}))


# --- вход из Telegram --------------------------------------------------------

def test_the_panel_mounts_into_the_vri_tab_by_name():
    """Перебор `.panel` находил первую попавшуюся — «Вводные»."""
    assert "document.getElementById('vri')" in _MPT_FRAGMENT


def test_the_script_opens_the_tab_that_holds_the_panel():
    """Слепой клик по «ВРИ» переключал вкладку, а панель оставалась на другой."""
    assert "function revealHost()" in _MPT_FRAGMENT
    assert "clickVriTab" not in _MPT_FRAGMENT
    assert "panel.closest('.panel" in _MPT_FRAGMENT


def test_a_hidden_panel_says_so_instead_of_showing_a_blank_screen():
    """Если вкладку открыть не удалось, человек должен узнать причину, а не
    смотреть на пустое место."""
    assert "hostVisible()" in _MPT_FRAGMENT
    assert "которая сейчас скрыта" in _MPT_FRAGMENT


# --- нечисла -----------------------------------------------------------------

def test_infinity_is_refused_not_served_as_zero(client):
    response = client.post(
        "/api/mpt/calculate",
        content='{"category":"office","district":"Ясенево","area_sqm":Infinity,"ttk_position":"outside"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "не число" in response.json()["detail"]


def test_nan_is_refused_without_a_500(client):
    response = client.post(
        "/api/mpt/calculate",
        content='{"category":"office","district":"Ясенево","area_sqm":NaN,"ttk_position":"outside"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "не число" in response.json()["detail"]


def test_broken_json_is_named(client):
    response = client.post("/api/mpt/calculate", content="{не json",
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert "JSON" in response.json()["detail"]


def test_validation_errors_stay_readable(client):
    response = client.post("/api/mpt/calculate",
                           json={"category": "office", "district": "Ясенево", "area_sqm": -1,
                                 "ttk_position": "outside"})
    assert response.status_code == 400
    assert "area_sqm" in response.json()["detail"]


def test_the_calculator_itself_refuses_non_numbers():
    """Защита стоит и в расчёте: сравнение с NaN всегда ложно, поэтому
    проверка «меньше нуля» его пропускала."""
    for value in (float("nan"), float("inf")):
        with pytest.raises(MptCalculationError):
            calc(area_sqm=value)
        with pytest.raises(MptCalculationError):
            calc(parking_sqm=value)


# --- минимальная площадь ------------------------------------------------------

def test_below_the_minimum_the_benefit_is_zero():
    """Офис 1 000 м² при пороге 5 000 показывал 116 361 546 ₽."""
    result = calc(area_sqm=1_000)
    assert result.eligible_for_minimum is False
    assert result.benefit_rub == 0.0


def test_the_formula_still_shows_what_it_would_have_been():
    """Ноль должен читаться как недобор порога, а не как поломка расчёта."""
    result = calc(area_sqm=1_000)
    assert result.potential_benefit_rub > 0
    assert "условия присвоения статуса не выполнены" in result.formula
    assert any("ниже минимума" in blocker for blocker in result.blockers)


def test_above_the_minimum_nothing_changed():
    result = calc(area_sqm=10_000)
    assert result.eligible_for_minimum is True
    assert result.benefit_rub == result.potential_benefit_rub
    assert result.benefit_rub == pytest.approx(1_000.0 * 10_000.0 * 166.23078 * 0.75)
