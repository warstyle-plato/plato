"""DevelopAid 2.0 — beta economics for non-residential projects.

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
from developaid_commercial_form import field_groups, field_keys, field_limits

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
    "exit_cost_pct": 1.0,
    "project_discount_rate_pct": 15.0,
    "equity_hurdle_rate_pct": 20.0,
    "sale_start_month": 18,
    "sale_months": 24,
    "sales_curve": "bell",
    "sale_price_growth_pct": 0.0,
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
        "opening_occupancy_pct": 55.0,
        "occupancy_pct": 92.0,
        "rent_growth_pct": 5.0,
        "other_income_pct": 4.0,
        "opex_pct": 18.0,
        "leasing_cost_pct": 4.0,
        "saleable_area_sqm": 22_000,
        "sale_price_rub_sqm": 420_000,
    },
    "retail": {
        "income_area_sqm": 18_000,
        "rent_rub_sqm_month": 3_800,
        "opening_occupancy_pct": 60.0,
        "occupancy_pct": 94.0,
        "sales_rub_sqm_month": 55_000,
        "turnover_rent_pct": 8.0,
        "rent_growth_pct": 5.0,
        "opex_pct": 22.0,
        "marketing_pct": 2.0,
        "saleable_area_sqm": 18_000,
        "sale_price_rub_sqm": 360_000,
    },
    "hotel": {
        "keys": 180,
        "adr_rub": 14_000,
        "opening_occupancy_pct": 45.0,
        "occupancy_pct": 72.0,
        "other_revenue_pct": 25.0,
        "adr_growth_pct": 5.0,
        "opex_pct": 58.0,
        "management_fee_pct": 3.0,
        "ffe_reserve_pct": 3.0,
        "preopening_cost_rub": 180_000_000,
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
    "exit_cost_pct": ("Расходы на выход / продажу актива", "% exit value"),
    "project_discount_rate_pct": ("Ставка дисконтирования проекта", "% годовых"),
    "equity_hurdle_rate_pct": ("Требуемая доходность equity", "% годовых"),
    "sale_start_month": ("Старт продаж", "мес. от старта"),
    "sale_months": ("Период продаж", "мес."),
    "sales_curve": ("Кривая продаж", "bell / flat / front_loaded / back_loaded"),
    "sale_price_growth_pct": ("Рост цены продажи", "%/год"),
    "selling_cost_pct": ("Расходы на продажи", "% выручки"),
    "debt_share_pct": ("Доля кредита", "% затрат"),
    "debt_rate_pct": ("Ставка кредита", "% годовых"),
    "loan_fee_pct": ("Комиссия за кредит", "% лимита"),
    "sales_cash_sweep_pct": ("Погашение долга из продаж", "% поступлений"),
    "income_area_sqm": ("Арендопригодная площадь", "м²"),
    "rent_rub_sqm_month": ("Базовая аренда", "₽/м²/мес."),
    "opening_occupancy_pct": ("Загрузка при открытии", "%"),
    "occupancy_pct": ("Стабилизированная загрузка", "%"),
    "rent_growth_pct": ("Индексация аренды / ставок", "%/год"),
    "other_income_pct": ("Прочая выручка офиса", "% аренды"),
    "opex_pct": ("Операционные расходы", "% выручки"),
    "leasing_cost_pct": ("Leasing / TI / LC", "% базовой аренды lease-up"),
    "marketing_pct": ("Маркетинг / promotion", "% выручки"),
    "saleable_area_sqm": ("Продаваемая площадь", "м²"),
    "sale_price_rub_sqm": ("Цена продажи", "₽/м²"),
    "sales_rub_sqm_month": ("Оборот арендаторов", "₽/м²/мес."),
    "turnover_rent_pct": ("Процент с оборота", "%"),
    "keys": ("Номерной фонд", "ключей"),
    "adr_rub": ("ADR", "₽/номер/сутки"),
    "adr_growth_pct": ("Рост ADR", "%/год"),
    "other_revenue_pct": ("Прочая выручка", "% room revenue"),
    "management_fee_pct": ("Management fee", "% выручки"),
    "ffe_reserve_pct": ("FF&E reserve", "% выручки"),
    "preopening_cost_rub": ("Pre-opening", "₽"),
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
        "groups": {f"{a}/{s}/{f}": field_groups(a, s, f)
                   for a in ASSET_DEFAULTS for s in ("income", "sale")
                   for f in ("equity", "equity_debt")},
        "fields": [
            {"key": key, "label": label, "unit": unit, **field_limits(key)}
            for key, (label, unit) in FIELD_LABELS.items()
        ],
        "beta_note": (
            "Коммерческий контур не использует эскроу. Продажная модель считает "
            "прямые поступления по реализации площадей/номеров; доходная — NOI и "
            "терминальную стоимость. Кредит обычный, без эскроу-дисконта."
        ),
    }


def calculate(req: CommercialRequest) -> dict[str, Any]:
    """Run the authoritative commercial beta-2 engine.

    Routes, UI and exporters keep importing this public function.  The actual
    arithmetic lives in one engine module so the web screen and future Excel
    cannot silently diverge.
    """
    from developaid_commercial_engine import calculate_v2

    return calculate_v2(req)

def install(app: FastAPI) -> None:
    if getattr(app.state, "commercial_installed", False):
        return
    app.state.commercial_installed = True
    @app.get("/api/commercial/form")
    @app.get("/api/v2/commercial/form")
    def commercial_form() -> JSONResponse:
        return JSONResponse(form_description(), headers=_NO_STORE)

    @app.post("/api/commercial/calculate")
    @app.post("/api/v2/commercial/calculate")
    def commercial_calculate(req: CommercialRequest) -> JSONResponse:
        try:
            for key in field_keys(req.asset_type, req.strategy, req.financing_mode):
                if key not in req.inputs:
                    continue
                value = req.inputs[key]
                if key == "sales_curve":
                    if value not in {"bell", "flat", "front_loaded", "back_loaded"}:
                        raise ValueError("Неизвестная кривая продаж")
                    continue
                bounds = field_limits(key)
                number = float(value)
                if not isfinite(number) or not bounds['min'] <= number <= bounds['max']:
                    raise ValueError(f"{FIELD_LABELS[key][0]}: допустимо от {bounds['min']} до {bounds['max']}")
                if bounds['step'] == 1 and number != int(number):
                    raise ValueError(f"{FIELD_LABELS[key][0]}: требуется целое число")
            payload = calculate(req)
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload, headers=_NO_STORE)

