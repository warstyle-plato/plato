"""Регрессии ошибок, найденных при ревизии движка 25.09.2026.

Проверяются только четыре отдельные находки этой ветки:
- повторное применение паркинга не возвращает устаревший ТЭП;
- F/F2 и I(v2) не смешиваются с обычным покрытием эскроу;
- договорная отсрочка процентов заканчивается заданной датой и далее платит
  квартально;
- источник карточки 945-ПП соответствует последней указанной поправке.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main_legacy as core  # noqa: E402
import normatives_registry as registry  # noqa: E402


def _tep() -> dict:
    return {key: copy.deepcopy(value) for key, value in core.TEP_DEFAULT.items()}


def test_object_parking_cache_accepts_a_new_tep_on_the_same_dict() -> None:
    """Новый ТЭП между двумя проходами сильнее внутреннего parking-base."""
    tep = _tep()
    tep["offices"].update(
        gns=10_000.0, total_area=9_400.0, useful=6_000.0, saleable=6_000.0)
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(
        offices_enabled=True,
        offices_parking_under_spaces=40,
        offices_parking_over_spaces=40,
        object_parking_over_area_per_space_sqm=25,
        _parking_by_hand=["offices"],
    )

    core.apply_object_parking(inputs, tep)
    assert tep["offices"]["saleable"] == pytest.approx(5_400.0)

    # Внешний пересчёт ТЭП на той же структуре словаря. Старый код видел
    # служебный _object_parking_base_saleable и молча возвращал 6 000.
    tep["offices"].update(
        gns=12_000.0, total_area=11_280.0, useful=7_200.0, saleable=7_200.0)

    core.apply_object_parking(inputs, tep)

    # 40 мест × 25 м² = 1 000 м²; остаётся 11/12 новой GBA.
    assert tep["offices"]["saleable"] == pytest.approx(7_200.0 * 11 / 12)
    assert tep["offices"]["_object_parking_base_saleable"] == pytest.approx(7_200.0)


def _finance_result(**overrides) -> tuple[dict, dict]:
    inputs = dict(core.DEFAULT_INPUTS)
    inputs.update(
        apartment_price_th=650,
        commercial_price_th=650,
        parking_price_th=5_000,
    )
    inputs.update(overrides)
    result = core.calculate(core.CalcRequest(inputs=inputs, tep=_tep(), rates=[]))
    return inputs, result


def test_scheme2_uses_f_plus_half_f2_for_the_iv_ladder_and_iv2_for_its_slice() -> None:
    """F2 меняет и покрытие лестницы I(v), и ставку своего куска долга."""
    inputs, result = _finance_result(
        pf_escrow_scheme1_housing_share_pct=10,
        pf_escrow_scheme2_housing_share_pct=40,
        pf_special_v2_pct=13.30,
    )
    rows = [
        row for row in result["finance"]["rows"]
        if float(row.get("pf_balance") or 0) > 1
        and float(row.get("escrow") or 0) > 1
        and float(row.get("pf_iv2_principal") or 0) > 1
    ]
    assert rows, "проект не дошёл до ПФ с F2 — проверять нечего"
    row = rows[len(rows) // 2]

    debt = float(row["pf_balance"])
    escrow = float(row["escrow"])
    f = float(row["escrow_f"])
    f2 = float(row["escrow_f2"])
    iv2 = float(row["pf_iv2_principal"])

    assert f == pytest.approx(escrow * 0.50)
    assert f2 == pytest.approx(escrow * 0.40)
    assert float(row["coverage"]) == pytest.approx((f + 0.5 * f2) / debt)
    assert iv2 == pytest.approx(min(f2, debt))
    assert float(row["pf_special_v2_rate"]) == pytest.approx(0.133)

    ordinary = max(debt - iv2, 0.0)
    ordinary_weight = min(f, ordinary) / ordinary if ordinary > 0 else 0.0
    base = float(row["key_rate"]) + float(inputs["pf_spread_pp"]) / 100.0
    special = core.pf_special_rate_at(
        float(row["coverage"]),
        core.pf_special_steps(inputs["pf_special_steps"]),
        float(inputs["pf_special_pct"]) / 100.0,
    )
    ordinary_rate = base * (1 - ordinary_weight) + special * ordinary_weight
    expected = (
        ordinary * ordinary_rate + iv2 * float(inputs["pf_special_v2_pct"]) / 100.0
    ) / debt
    assert float(row["pf_rate"]) == pytest.approx(expected, rel=1e-10)


def test_scheme_housing_shares_cannot_exceed_all_escrow() -> None:
    with pytest.raises(ValueError, match="превышать 100%"):
        _finance_result(
            pf_escrow_scheme1_housing_share_pct=70,
            pf_escrow_scheme2_housing_share_pct=40,
        )


def test_interest_deferral_pays_in_deadline_month_then_quarterly() -> None:
    """До дедлайна платёж нулевой; затем — декабрь и квартальные месяцы."""
    _inputs, result = _finance_result(
        pf_interest_deferral_until="2028-12-31",
        pf_interest_payment_mode="quarterly_28",
    )
    rows = {core.d(row["month"]): row for row in result["finance"]["rows"]}

    dec = next(month for month in rows if month.year == 2028 and month.month == 12)
    jan = next(month for month in rows if month.year == 2029 and month.month == 1)
    feb = next(month for month in rows if month.year == 2029 and month.month == 2)
    mar = next(month for month in rows if month.year == 2029 and month.month == 3)

    assert float(rows[dec]["interest_payment"]) > 0
    assert float(rows[jan]["interest_payment"]) == pytest.approx(0.0)
    assert float(rows[feb]["interest_payment"]) == pytest.approx(0.0)
    assert float(rows[mar]["interest_payment"]) > 0

    before = [
        row for month, row in rows.items()
        if month < dec and float(row.get("pf_interest") or 0) > 1
    ]
    assert before, "до договорного дедлайна проценты не начислялись"
    assert all(float(row.get("interest_payment") or 0) == 0 for row in before)


def test_945_card_sources_the_amendment_it_calls_current() -> None:
    item = {row["id"]: row for row in registry._load_registry()}["moscow-945-pp"]
    assert "2118-ПП" in item["latest_amendment"]
    assert "2118-ПП" in item["source_label"]
    assert "2025" not in item["source_url"]
