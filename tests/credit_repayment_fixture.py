"""Синтетические исходные данные «Кутузов Сити» для проверок погашения кредитов.

Не настоящие цифры проекта: суммы подобраны так, чтобы каждая проверка
видела свою величину. Все суммы — млн ₽, как в ТЗ.
"""
from __future__ import annotations

import copy
from typing import Any

import developaid_credit_repayment as credit

AS_OF = "2026-10-01"


def _months(first: str, last: str) -> list[str]:
    out, year, month = [], int(first[:4]), int(first[5:7])
    while f"{year}-{month:02d}" <= last:
        out.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def raw() -> dict[str, dict[str, Any]]:
    """Наборы в том виде, в каком их присылают на загрузку."""
    draw_2025 = [{"date": f"{m}-15", "amount": 2485.689 / 9} for m in _months("2026-10", "2027-06")]
    draw_2026 = [{"date": f"{m}-15", "amount": 925.0 / 12} for m in _months("2026-10", "2027-09")]
    return {
        "facts.nkl2025": {"debt": 3000.0, "drawn": 3000.0, "accrued_interest": 0.0,
                          "accrued_fee": 0.0, "operations": []},
        "facts.nkl2026": {"debt": 200.0, "drawn": 200.0, "accrued_interest": 0.0,
                          "accrued_fee": 0.0},
        "plan.nkl2025": {"draws": draw_2025, "prepayments": []},
        "plan.nkl2026": {"draws": draw_2026, "prepayments": []},
        "deferred.nkl2025": {"deferred": 400.0, "interest_on_deferred": 20.0},
        "deferred.nkl2026": {"deferred": 10.0, "interest_on_deferred": 0.0},
        "escrow": {"balance": 2500.0},
        "contracts": {"payments": [{"month": m, "amount": 150.0, "contract": f"ДДУ-{i % 40}"}
                                   for i, m in enumerate(_months("2026-09", "2028-06"))]},
        "sales": {"sales": [{"month": m, "amount": 100.0, "down_share": 0.5,
                             "installment_months": 2} for m in _months("2026-09", "2028-04")]},
        "refunds": {"payments": [{"date": "2027-03-10", "amount": 5.0}]},
        "disclosure": {"items": [
            {"date": "2027-09-20", "amount": 4000.0, "confirmed": True, "final": False},
            {"date": "2028-06-30", "amount": None, "confirmed": False, "final": True}]},
        "letters_of_credit": {"balance": 120.0, "by_loan": {"nkl2025": 80.0, "nkl2026": 40.0}},
        "free_cash": {"items": [{"date": "2026-12-01", "amount": 300.0}]},
        "extra": {"items": [{"date": "2027-09-01", "amount": 500.0, "confirmed": True,
                             "what": "заём акционера"},
                            {"date": "2027-09-01", "amount": 900.0, "confirmed": False,
                             "what": "переговоры с банком"}]},
        "key_rate": {"path": [{"from": "2026-01-01", "rate": 16.5},
                              {"from": "2027-01-01", "rate": 14.0},
                              {"from": "2028-01-01", "rate": 12.0}]},
    }


def inputs(changes: dict[str, Any] | None = None, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    """Нормализованные наборы; ``changes`` подменяет данные набора целиком."""
    data = raw()
    data.update(copy.deepcopy(changes or {}))
    datasets = {}
    for name, body in data.items():
        if name in drop:
            continue
        datasets[name] = credit.normalize(name, {
            "as_of": AS_OF, "source": "проверочные данные", "unit": "млн ₽", "data": body})
    return {"preset": "kutuzov_city", "datasets": datasets}
