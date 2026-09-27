"""DevelopAid Desktop — beta economics for non-residential projects.

This module is intentionally separate from the residential engine. It does not
reuse escrow, residential project-finance discounts or apartment sales curves.
Commercial projects are modelled as either:

* income / hold — lease or hotel operations followed by a terminal sale;
* sale — direct sale of areas / hotel units ("future thing" economics), with
  sale proceeds available to the project rather than blocked on escrow.

Financing is either 100% equity or equity + a conventional loan. The loan is
funded pro-rata against development costs, accrues ordinary interest and is
repaid from sale proceeds (sale strategy) or at exit (income strategy).

The formulas here are a beta underwriting layer. They are deliberately kept
out of `main_legacy` so the residential model remains untouched while the
commercial product is validated.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

AssetType = Literal["office", "retail", "hotel"]
Strategy = Literal["income", "sale"]
FinancingMode = Literal["equity", "equity_debt"]

_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}

COMMON_DEFAULTS: dict[str, Any] = {
    "land_cost_rub": 1_500_000_000,
    "gross_area_sqm": 30_000,
    "construction_cost_rub_sqm": 180_000,
    "soft_cost_pct": 12.0,
    "contingency_pct": 5.0,
    "construction_months": 30,
    "stabilization_months": 12,
    "hold_years": 5,
    "exit_cap_rate_pct": 11.0,
    "sale_start_month": 18,
    "sale_months": 24,
    "selling_cost_pct": 2.0,
    "financing_mode": "equity_debt",
    "debt_share_pct": 60.0,
    "debt_rate_pct": 18.0,
    "loan_fee_pct": 1.0,
    "sales_cash_sweep_pct": 100.0,
}

ASSET_DEFAULTS: dict[str, dict[str, Any]] = {
    "office": {
        "income_area_sqm": 22_000,
        "rent_rub_sqm_month": 4_500,
        "occupancy_pct": 92.0,
        "opex_pct": 18.0,
        "saleable_area_sqm": 22_000,
        "sale_price_rub_sqm": 420_000,
    },
    "retail": {
        "income_area_sqm": 18_000,
        "rent_rub_sqm_month": 3_800,
        "occupancy_pct": 94.0,
        "sales_rub_sqm_month": 55_000,
        "turnover_rent_pct": 8.0,
        "opex_pct": 22.0,
        "saleable_area_sqm": 18_000,
        "sale_price_rub_sqm": 360_000,
    },
    "hotel": {
        "keys": 180,
        "adr_rub": 14_000,
        "occupancy_pct": 72.0,
        "other_revenue_pct": 25.0,
        "opex_pct": 58.0,
        "ffe_reserve_pct": 3.0,
        "saleable_keys": 180,
        "sale_price_rub_key": 28_000_000,
    },
}

FIELD_LABELS: dict[str, tuple[str, str]] = {
    "land_cost_rub": ("Стоимость участка", "₽"),
    "gross_area_sqm": ("ГНС", "м²"),
    "construction_cost_rub_sqm": ("Строительство", "₽/м² ГНС"),
    "soft_cost_pct": ("Проектирование и soft costs", "% hard cost"),
    "contingency_pct": ("Резерв", "% hard cost"),
    "construction_months": ("Срок строительства", "мес."),
    "stabilization_months": ("Выход на стабилизацию", "мес."),
    "hold_years": ("Горизонт после ввода", "лет"),
    "exit_cap_rate_pct": ("Exit cap rate", "%"),
    "sale_start_month": ("Старт продаж", "мес. от старта"),
    "sale_months": ("Период продаж", "мес."),
    "selling_cost_pct": ("Расходы на продажи", "% выручки"),
    "debt_share_pct": ("Доля кредита", "% затрат"),
    "debt_rate_pct": ("Ставка кредита", "% годовых"),
    "loan_fee_pct": ("Комиссия за кредит", "% лимита"),
    "sales_cash_sweep_pct": ("Погашение долга из продаж", "% поступлений"),
    "income_area_sqm": ("Арендопригодная площадь", "м²"),
    "rent_rub_sqm_month": ("Базовая аренда", "₽/м²/мес."),
    "occupancy_pct": ("Стабилизированная загрузка", "%"),
    "opex_pct": ("Операционные расходы", "% выручки"),
    "saleable_area_sqm": ("Продаваемая площадь", "м²"),
    "sale_price_rub_sqm": ("Цена продажи", "₽/м²"),
    "sales_rub_sqm_month": ("Оборот арендаторов", "₽/м²/мес."),
    "turnover_rent_pct": ("Процент с оборота", "%"),
    "keys": ("Номерной фонд", "ключей"),
    "adr_rub": ("ADR", "₽/номер/сутки"),
    "other_revenue_pct": ("Прочая выручка", "% room revenue"),
    "ffe_reserve_pct": ("FF&E reserve", "% выручки"),
    "saleable_keys": ("Продаваемые номера", "шт."),
    "sale_price_rub_key": ("Цена продажи номера", "₽/номер"),
}


class CommercialRequest(BaseModel):
    asset_type: AssetType = "office"
    strategy: Strategy = "income"
    financing_mode: FinancingMode = "equity_debt"
    inputs: dict[str, Any] = Field(default_factory=dict)


def _f(values: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(values.get(key, default))
    except (TypeError, ValueError):
        value = default
    if not isfinite(value):
        return default
    return value


def _pct(values: dict[str, Any], key: str, default: float = 0.0) -> float:
    return max(0.0, _f(values, key, default)) / 100.0


def _months(values: dict[str, Any], key: str, default: int, minimum: int = 1) -> int:
    return max(minimum, int(round(_f(values, key, default))))


def default_inputs(asset_type: str) -> dict[str, Any]:
    if asset_type not in ASSET_DEFAULTS:
        raise KeyError(asset_type)
    values = deepcopy(COMMON_DEFAULTS)
    values.update(deepcopy(ASSET_DEFAULTS[asset_type]))
    return values


def form_description() -> dict[str, Any]:
    return {
        "asset_types": [
            {"value": "office", "label": "Офис"},
            {"value": "retail", "label": "Торговля"},
            {"value": "hotel", "label": "Гостиница"},
        ],
        "strategies": [
            {"value": "income", "label": "Доходная модель"},
            {"value": "sale", "label": "Продажа площадей / номеров"},
        ],
        "financing_modes": [
            {"value": "equity", "label": "100% собственные средства"},
            {"value": "equity_debt", "label": "Собственные средства + кредит"},
        ],
        "defaults": {key: default_inputs(key) for key in ASSET_DEFAULTS},
        "fields": [
            {"key": key, "label": label, "unit": unit}
            for key, (label, unit) in FIELD_LABELS.items()
        ],
        "beta_note": (
            "Коммерческий контур не использует эскроу. Продажная модель считает "
            "прямые поступления по реализации площадей/номеров; доходная — NOI и "
            "терминальную стоимость. Кредит обычный, без эскроу-дисконта."
        ),
    }


def _asset_income(asset_type: str, values: dict[str, Any], occupancy_factor: float = 1.0) -> dict[str, float]:
    occupancy = min(1.0, _pct(values, "occupancy_pct", 90.0) * occupancy_factor)
    opex = min(0.95, _pct(values, "opex_pct", 20.0))

    if asset_type == "office":
        area = max(0.0, _f(values, "income_area_sqm"))
        rent = max(0.0, _f(values, "rent_rub_sqm_month"))
        gross = area * rent * occupancy
        operating = gross * opex
        return {"revenue": gross, "opex": operating, "noi": gross - operating}

    if asset_type == "retail":
        area = max(0.0, _f(values, "income_area_sqm"))
        base = area * max(0.0, _f(values, "rent_rub_sqm_month")) * occupancy
        turnover = (
            area
            * max(0.0, _f(values, "sales_rub_sqm_month"))
            * min(1.0, _pct(values, "turnover_rent_pct", 8.0))
            * occupancy
        )
        gross = max(base, turnover)
        operating = gross * opex
        return {
            "revenue": gross,
            "base_rent": base,
            "turnover_rent": turnover,
            "opex": operating,
            "noi": gross - operating,
        }

    keys = max(0.0, _f(values, "keys"))
    adr = max(0.0, _f(values, "adr_rub"))
    room_revenue = keys * adr * 365.0 / 12.0 * occupancy
    other_revenue = room_revenue * _pct(values, "other_revenue_pct", 25.0)
    gross = room_revenue + other_revenue
    operating = gross * opex
    ffe = gross * min(0.25, _pct(values, "ffe_reserve_pct", 3.0))
    return {
        "revenue": gross,
        "room_revenue": room_revenue,
        "other_revenue": other_revenue,
        "opex": operating,
        "ffe_reserve": ffe,
        "noi": gross - operating - ffe,
        "revpar": adr * occupancy,
    }


def _sale_total(asset_type: str, values: dict[str, Any]) -> float:
    if asset_type == "hotel":
        return max(0.0, _f(values, "saleable_keys")) * max(0.0, _f(values, "sale_price_rub_key"))
    return max(0.0, _f(values, "saleable_area_sqm")) * max(0.0, _f(values, "sale_price_rub_sqm"))


def _irr_monthly(cashflows: list[float]) -> float | None:
    if not cashflows or not any(x < 0 for x in cashflows) or not any(x > 0 for x in cashflows):
        return None

    def npv(rate: float) -> float:
        return sum(value / ((1.0 + rate) ** index) for index, value in enumerate(cashflows))

    low, high = -0.95, 10.0
    left, right = npv(low), npv(high)
    if left == 0:
        return low
    if right == 0:
        return high
    if left * right > 0:
        return None
    for _ in range(180):
        mid = (low + high) / 2.0
        value = npv(mid)
        if abs(value) < 0.01:
            return mid
        if left * value <= 0:
            high, right = mid, value
        else:
            low, left = mid, value
    return (low + high) / 2.0


def _annualize_monthly(rate: float | None) -> float | None:
    if rate is None:
        return None
    try:
        return (1.0 + rate) ** 12.0 - 1.0
    except (OverflowError, ValueError):
        return None


def calculate(req: CommercialRequest) -> dict[str, Any]:
    if req.asset_type not in ASSET_DEFAULTS:
        raise ValueError("Неизвестный тип коммерческого объекта")

    values = default_inputs(req.asset_type)
    values.update(req.inputs or {})
    values["financing_mode"] = req.financing_mode

    gross_area = max(0.0, _f(values, "gross_area_sqm"))
    hard_cost = gross_area * max(0.0, _f(values, "construction_cost_rub_sqm"))
    soft_cost = hard_cost * _pct(values, "soft_cost_pct", 12.0)
    contingency = hard_cost * _pct(values, "contingency_pct", 5.0)
    land_cost = max(0.0, _f(values, "land_cost_rub"))
    development_cost = land_cost + hard_cost + soft_cost + contingency

    construction_months = _months(values, "construction_months", 30)
    sale_start = max(0, int(round(_f(values, "sale_start_month", 18))))
    sale_months = _months(values, "sale_months", 24)
    hold_months = max(12, _months(values, "hold_years", 5) * 12)
    stabilization_months = _months(values, "stabilization_months", 12)

    horizon = (
        max(construction_months + 1, sale_start + sale_months + 1)
        if req.strategy == "sale"
        else construction_months + hold_months + 1
    )

    development_spend = [0.0 for _ in range(horizon)]
    development_spend[0] += land_cost
    monthly_build = (hard_cost + soft_cost + contingency) / construction_months
    for month in range(1, construction_months + 1):
        if month < horizon:
            development_spend[month] += monthly_build

    operating_revenue = [0.0 for _ in range(horizon)]
    operating_opex = [0.0 for _ in range(horizon)]
    sale_revenue = [0.0 for _ in range(horizon)]
    selling_cost = [0.0 for _ in range(horizon)]
    terminal_value = [0.0 for _ in range(horizon)]
    stabilized = _asset_income(req.asset_type, values, 1.0)

    if req.strategy == "sale":
        total_sales = _sale_total(req.asset_type, values)
        monthly_sales = total_sales / sale_months
        sale_cost_pct = _pct(values, "selling_cost_pct", 2.0)
        for month in range(sale_start, min(horizon, sale_start + sale_months)):
            sale_revenue[month] = monthly_sales
            selling_cost[month] = monthly_sales * sale_cost_pct
    else:
        for month in range(construction_months + 1, horizon):
            months_open = month - construction_months
            ramp = min(1.0, 0.5 + 0.5 * months_open / stabilization_months)
            economics = _asset_income(req.asset_type, values, ramp)
            operating_revenue[month] = economics["revenue"]
            operating_opex[month] = economics["revenue"] - economics["noi"]
        cap_rate = max(0.0001, _pct(values, "exit_cap_rate_pct", 11.0))
        terminal_value[-1] = stabilized["noi"] * 12.0 / cap_rate

    project_cashflow = [
        operating_revenue[i]
        + sale_revenue[i]
        + terminal_value[i]
        - development_spend[i]
        - operating_opex[i]
        - selling_cost[i]
        for i in range(horizon)
    ]

    debt_share = (
        0.0
        if req.financing_mode == "equity"
        else min(0.95, _pct(values, "debt_share_pct", 60.0))
    )
    annual_rate = (
        0.0
        if req.financing_mode == "equity"
        else _pct(values, "debt_rate_pct", 18.0)
    )
    monthly_rate = annual_rate / 12.0
    fee_pct = 0.0 if req.financing_mode == "equity" else _pct(values, "loan_fee_pct", 1.0)
    cash_sweep = min(1.0, _pct(values, "sales_cash_sweep_pct", 100.0))

    debt_draw = [0.0 for _ in range(horizon)]
    interest = [0.0 for _ in range(horizon)]
    debt_repayment = [0.0 for _ in range(horizon)]
    debt_balance = [0.0 for _ in range(horizon)]
    loan_fees = [0.0 for _ in range(horizon)]
    equity_cashflow = [0.0 for _ in range(horizon)]
    equity_injection = [0.0 for _ in range(horizon)]
    equity_distribution = [0.0 for _ in range(horizon)]

    balance = 0.0
    for month in range(horizon):
        draw = development_spend[month] * debt_share
        debt_draw[month] = draw
        loan_fees[month] = draw * fee_pct
        opening = balance
        interest[month] = opening * monthly_rate
        balance += draw

        if req.strategy == "sale" and balance > 0.0:
            debt_repayment[month] = min(balance, sale_revenue[month] * cash_sweep)
        elif req.strategy == "income" and month == horizon - 1 and balance > 0.0:
            debt_repayment[month] = balance
        balance -= debt_repayment[month]
        debt_balance[month] = balance

        cash_after_finance = (
            project_cashflow[month]
            + debt_draw[month]
            - interest[month]
            - loan_fees[month]
            - debt_repayment[month]
        )
        if cash_after_finance < 0:
            equity_injection[month] = -cash_after_finance
        else:
            equity_distribution[month] = cash_after_finance
        equity_cashflow[month] = cash_after_finance

    if balance > 0.01:
        debt_repayment[-1] += balance
        equity_cashflow[-1] -= balance
        if equity_distribution[-1] >= balance:
            equity_distribution[-1] -= balance
        else:
            equity_injection[-1] += balance - equity_distribution[-1]
            equity_distribution[-1] = 0.0
        balance = 0.0
        debt_balance[-1] = 0.0

    financing_cost = sum(interest) + sum(loan_fees)
    total_revenue = sum(operating_revenue) + sum(sale_revenue) + sum(terminal_value)
    total_operating_cost = sum(operating_opex) + sum(selling_cost)
    total_cost = development_cost + total_operating_cost + financing_cost
    profit = total_revenue - total_cost
    equity_required = sum(equity_injection)
    equity_return = sum(equity_distribution) - equity_required
    project_irr = _annualize_monthly(_irr_monthly(project_cashflow))
    equity_irr = _annualize_monthly(_irr_monthly(equity_cashflow))
    peak_debt = max(debt_balance + debt_draw + [0.0])

    stabilized_noi_annual = (
        stabilized.get("noi", 0.0) * 12.0 if req.strategy == "income" else 0.0
    )
    yield_on_cost = (
        stabilized_noi_annual / development_cost
        if development_cost > 0 and stabilized_noi_annual
        else None
    )
    exit_value = sum(terminal_value)

    report: dict[str, Any] = {
        "title": {
            "office": "Офисная экономика",
            "retail": "Экономика торгового объекта",
            "hotel": "Гостиничная экономика",
        }[req.asset_type],
        "strategy": "Доходная модель" if req.strategy == "income" else "Продажа площадей / номеров",
        "financing": (
            "100% собственные средства"
            if req.financing_mode == "equity"
            else "Собственные средства + обычный кредит, без эскроу"
        ),
        "sections": [],
    }
    if req.asset_type in {"office", "retail"}:
        report["sections"].append({
            "name": "Площади",
            "metrics": {
                "ГНС": gross_area,
                "Доходная площадь": _f(values, "income_area_sqm"),
                "Продаваемая площадь": _f(values, "saleable_area_sqm"),
            },
        })
    else:
        report["sections"].append({
            "name": "Номерной фонд",
            "metrics": {
                "Ключи": _f(values, "keys"),
                "Продаваемые номера": _f(values, "saleable_keys"),
            },
        })

    if req.strategy == "income":
        income_metrics: dict[str, Any] = {
            "Стабилизированный NOI, ₽/год": stabilized_noi_annual,
            "Exit value, ₽": exit_value,
        }
        if req.asset_type == "hotel":
            income_metrics["RevPAR, ₽"] = stabilized.get("revpar")
        report["sections"].append({"name": "Доход", "metrics": income_metrics})
    else:
        report["sections"].append({
            "name": "Продажи",
            "metrics": {
                "Валовая выручка, ₽": sum(sale_revenue),
                "Эскроу, ₽": 0.0,
            },
        })

    return {
        "version": "commercial-beta-1",
        "asset_type": req.asset_type,
        "strategy": req.strategy,
        "financing_mode": req.financing_mode,
        "uses_escrow": False,
        "inputs": values,
        "kpi": {
            "development_cost": development_cost,
            "financing_cost": financing_cost,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "profit_before_tax": profit,
            "margin": profit / total_revenue if total_revenue else None,
            "project_irr": project_irr,
            "equity_irr": equity_irr,
            "equity_required": equity_required,
            "equity_return": equity_return,
            "peak_debt": peak_debt,
            "stabilized_noi_annual": stabilized_noi_annual,
            "yield_on_cost": yield_on_cost,
            "exit_value": exit_value,
        },
        "operating": stabilized,
        "monthly": {
            "development_spend": development_spend,
            "operating_revenue": operating_revenue,
            "sale_revenue": sale_revenue,
            "terminal_value": terminal_value,
            "operating_cost": [
                operating_opex[i] + selling_cost[i] for i in range(horizon)
            ],
            "project_cashflow": project_cashflow,
            "debt_draw": debt_draw,
            "interest": interest,
            "debt_repayment": debt_repayment,
            "debt_balance": debt_balance,
            "equity_injection": equity_injection,
            "equity_distribution": equity_distribution,
            "equity_cashflow": equity_cashflow,
        },
        "report": report,
        "warnings": [
            "Beta: коммерческая экономика отделена от жилого движка; эскроу и льготная ставка ПФ не применяются.",
            "Продажная модель трактует поступления как прямой денежный поток проекта. Юридическую схему реализации нужно проверять отдельно для конкретного объекта и покупателя.",
        ],
    }


def install(app: FastAPI) -> None:
    @app.get("/api/v2/commercial/form")
    def commercial_form() -> JSONResponse:
        return JSONResponse(form_description(), headers=_NO_STORE)

    @app.post("/api/v2/commercial/calculate")
    def commercial_calculate(req: CommercialRequest) -> JSONResponse:
        try:
            payload = calculate(req)
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers=_NO_STORE)
