"""Кд вне таблицы 3 к 1745-ПП не угадывается.

Коэффициент доходности задан таблицей 3 постановления Правительства Московской
области от 19.12.2025 № 1745-ПП по округам (10 / 5 / 1 %). Для округов, которых
в таблице нет (Дзержинский, Протвино, Пущино, Электрогорск), код подставлял
0,1 «по умолчанию» — числа без источника, которое умножает плату на миллиарды.
Решение владельца (16.10.2026, docs/normative_audit_msk_mo_2026-10.md §6 п. 4):
не считать — «Кд не установлен» с причиной и просьбой вписать руками; запас
0,1 убрать. Ручной Кд и округа из таблицы считаются как прежде.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core

SITE_HA = 6.6667


def _calc(district: str, **extra):
    return main.mo_calculate(main.MoCalculateRequest(site_area_ha=SITE_HA, district=district, **extra))


@pytest.mark.parametrize("district", ["Пущино", "Городской округ Протвино", "Дзержинский", "Электрогорск"])
def test_district_outside_table_3_gets_no_payment_and_a_named_reason(district):
    result = _calc(district)
    vri = result["vri"]
    assert vri["kd"] is None
    assert vri["kd_basis"] == "округа нет в таблице 3"
    # Платы нет — поля пустые, а не ноль: ноль выглядел бы ответом источника.
    assert vri["payment_rub"] is None
    assert vri["payment_direct_rub"] is None
    assert vri["payment_used_rub"] is None
    assert vri["payment_used_mln"] is None
    assert vri["payment_basis"] == "Кд не установлен"
    # Вводные не несут нулевую плату: страница не должна затереть вписанную сумму.
    assert "land_rights_cost_mln" not in result["inputs"]
    reasons = [text for text in result["warnings"] if "Кд не установлен" in text]
    assert len(reasons) == 1, result["warnings"]
    reason = reasons[0]
    assert "таблице 3" in reason and "1745" in reason
    assert district.replace("Городской округ ", "") in reason
    assert "вручную" in reason and "vri_kd" in reason
    # Старого запаса 0,1 нет ни в числах, ни в словах.
    assert not any("по умолчанию" in text for text in result["warnings"])


def test_manual_kd_still_computes_for_a_district_outside_table_3():
    result = _calc("Пущино", vri_kd=0.05)
    vri = result["vri"]
    assert vri["kd"] == pytest.approx(0.05)
    assert vri["kd_basis"] == "задан вручную"
    assert vri["payment_used_rub"] is not None and vri["payment_used_rub"] > 0
    assert vri["payment_used_rub"] == pytest.approx(
        vri["market_price_rub_per_sqm"] * result["social"]["apartments_sqm"] * 0.05, rel=1e-6
    )
    assert result["inputs"]["land_rights_cost_mln"] == pytest.approx(vri["payment_used_mln"])
    assert not any("Кд не установлен" in text for text in result["warnings"])


def test_district_from_table_3_is_computed_as_before():
    result = _calc("Мытищи")
    vri = result["vri"]
    assert vri["kd"] == pytest.approx(0.10)
    assert vri["kd_basis"] == "округ"
    assert vri["payment_used_rub"] is not None and vri["payment_used_rub"] > 0
    assert result["inputs"]["land_rights_cost_mln"] == pytest.approx(vri["payment_used_mln"])
    assert not any("Кд не установлен" in text for text in result["warnings"])


def test_the_default_norms_hold_no_kd():
    """Единственные владельцы Кд — таблица 3 и поле `vri_kd` запроса."""
    assert "vri_kd" not in main.MO_NORMS_DEFAULT
    assert "vri_kd" not in main.mo_reference()["norms"]


def test_mo_vri_payment_without_kd_names_the_cause():
    reference = main._mo_district_upks("Городской округ Мытищи")
    result = main.mo_vri_payment(
        [],
        upks_target=reference["upks_land_residential"],
        upks_average_oks=reference["upks_oks_mkd"],
        apartments_sqm=100000,
        market_price_rub_per_sqm=200000,
        kd=None,
    )
    assert result["kd"] is None
    assert result["payment_used_rub"] is None
    assert result["payment_basis"] == "Кд не установлен"
    assert any("Кд не установлен" in text and "vri_kd" in text for text in result["warnings"])
