"""Authoritative beta-2 engine for DevelopAid non-residential economics.

The engine is intentionally independent from the residential model.  It models
office, retail and hotel projects with two realization strategies (income/hold
or direct sale) and two capital structures (equity or conventional debt +
equity).  Escrow is not used anywhere in this module.

The web layer in developaid_commercial.py delegates to calculate_v2(), so there
is one commercial source of arithmetic for the beta.
"""

from __future__ import annotations

from typing import Any

from developaid_commercial import (
    CommercialRequest,
    _f,
    _months,
    _pct,
    default_inputs,
)

_RETAIL_MIX = [
    {
        "name": "Anchor",
        "share_pct": 25.0,
        "base_rent_rub_sqm_month": 1_800,
        "sales_rub_sqm_month": 35_000,
        "turnover_rent_pct": 6.0,
        "occupancy_pct": 96.0,
    },
    {
        "name": "Fashion / inline",
        "share_pct": 35.0,
        "base_rent_rub_sqm_month": 5_200,
        "sales_rub_sqm_month": 70_000,
        "turnover_rent_pct": 8.0,
        "occupancy_pct": 95.0,
    },
    {
        "name": "F&B",
        "share_pct": 20.0,
        "base_rent_rub_sqm_month": 6_500,
        "sales_rub_sqm_month": 85_000,
        "turnover_rent_pct": 10.0,
        "occupancy_pct": 92.0,
    },
    {
        "name": "Services / entertainment",
        "share_pct": 20.0,
        "base_rent_rub_sqm_month": 4_000,
        "sales_rub_sqm_month": 45_000,
        "turnover_rent_pct": 8.0,
        "occupancy_pct": 93.0,
    },
]


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _irr_monthly(cashflows: list[float]) -> float | None:
    """Solve periodic monthly IRR by bisection.

    Commercial cash flows can contain several sign changes, so the result is
    the root in the practical search interval used by DevelopAid rather than a
    claim that every pathological series has a unique economic IRR.
    """
    if (
        not cashflows
        or not any(value < 0 for value in cashflows)
        or not any(value > 0 for value in cashflows)
    ):
        return None

    def npv(rate: float) -> float:
        return sum(
            value / ((1.0 + rate) ** index)
            for index, value in enumerate(cashflows)
        )

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


def _share(values: dict[str, Any], key: str, default: float = 0.0) -> float:
    return _clamp(_f(values, key, default) / 100.0, 0.0, 1.0)


def _s_curve_weights(months: int) -> list[float]:
    """Symmetric development S-curve, normalized to exactly one."""
    raw = [float(month * (months + 1 - month)) for month in range(1, months + 1)]
    total = sum(raw) or 1.0
    weights = [value / total for value in raw]
    # Numerical residual goes into the final month so spend reconciles exactly.
    weights[-1] += 1.0 - sum(weights)
    return weights


def _sales_weights(months: int, shape: str) -> list[float]:
    shape = str(shape or "bell").strip().lower()
    if shape == "flat":
        raw = [1.0] * months
    elif shape == "front_loaded":
        raw = [float(months + 1 - month) for month in range(1, months + 1)]
    elif shape == "back_loaded":
        raw = [float(month) for month in range(1, months + 1)]
    else:
        raw = [float(month * (months + 1 - month)) for month in range(1, months + 1)]
    total = sum(raw) or 1.0
    weights = [value / total for value in raw]
    weights[-1] += 1.0 - sum(weights)
    return weights


def _opening_occupancy(asset: str, values: dict[str, Any]) -> float:
    default = {"office": 55.0, "retail": 60.0, "hotel": 45.0}[asset]
    return _share(values, "opening_occupancy_pct", default)


def _stabilized_occupancy(values: dict[str, Any]) -> float:
    return _share(values, "occupancy_pct", 90.0)


def _occupancy(asset: str, values: dict[str, Any], months_open: int) -> float:
    stabilized = _stabilized_occupancy(values)
    opening = min(stabilized, _opening_occupancy(asset, values))
    stabilization_months = _months(values, "stabilization_months", 12)
    if months_open <= 0:
        return 0.0
    progress = _clamp(months_open / stabilization_months, 0.0, 1.0)
    return opening + (stabilized - opening) * progress


def _growth_factor(annual_rate: float, months_open: int) -> float:
    return (1.0 + max(-0.95, annual_rate)) ** (max(0, months_open - 1) / 12.0)


def _retail_mix(values: dict[str, Any]) -> list[dict[str, Any]]:
    supplied = values.get("tenant_mix")
    # Aggregate retail inputs remain authoritative until a user explicitly
    # supplies a tenant mix. This keeps the web form honest: changing its
    # rent / turnover assumptions must change the result.
    source = supplied if isinstance(supplied, list) and supplied else []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            continue
        rows.append({
            "name": str(item.get("name") or f"Segment {index + 1}"),
            "share_pct": max(0.0, float(item.get("share_pct", 0.0) or 0.0)),
            "base_rent_rub_sqm_month": max(
                0.0, float(item.get("base_rent_rub_sqm_month", 0.0) or 0.0)
            ),
            "sales_rub_sqm_month": max(
                0.0, float(item.get("sales_rub_sqm_month", 0.0) or 0.0)
            ),
            "turnover_rent_pct": max(
                0.0, float(item.get("turnover_rent_pct", 0.0) or 0.0)
            ),
            "occupancy_pct": _clamp(
                float(item.get("occupancy_pct", 100.0) or 100.0), 0.0, 100.0
            ),
        })
    total_share = sum(item["share_pct"] for item in rows)
    if total_share <= 0:
        return []
    for item in rows:
        item["share"] = item["share_pct"] / total_share
    return rows


def _office_month(values: dict[str, Any], months_open: int) -> dict[str, Any]:
    area = max(0.0, _f(values, "income_area_sqm"))
    occupancy = _occupancy("office", values, months_open)
    growth = _growth_factor(_pct(values, "rent_growth_pct", 0.0), months_open)
    rent = max(0.0, _f(values, "rent_rub_sqm_month")) * growth
    base_rent = area * rent * occupancy
    other_revenue = base_rent * _pct(values, "other_income_pct", 0.0)
    revenue = base_rent + other_revenue
    opex = revenue * min(0.95, _pct(values, "opex_pct", 18.0))
    leasing_cost = 0.0
    if months_open <= _months(values, "stabilization_months", 12):
        leasing_cost = base_rent * _pct(values, "leasing_cost_pct", 0.0)
    noi = revenue - opex - leasing_cost
    return {
        "occupancy": occupancy,
        "rent": rent,
        "base_rent": base_rent,
        "other_revenue": other_revenue,
        "revenue": revenue,
        "opex": opex,
        "leasing_cost": leasing_cost,
        "noi": noi,
    }


def _retail_month(values: dict[str, Any], months_open: int) -> dict[str, Any]:
    area = max(0.0, _f(values, "income_area_sqm"))
    overall_occupancy = _occupancy("retail", values, months_open)
    growth = _growth_factor(_pct(values, "rent_growth_pct", 0.0), months_open)
    mix = _retail_mix(values)

    if not mix:
        base_rent = (
            area
            * max(0.0, _f(values, "rent_rub_sqm_month"))
            * growth
            * overall_occupancy
        )
        turnover_rent = (
            area
            * max(0.0, _f(values, "sales_rub_sqm_month"))
            * growth
            * _pct(values, "turnover_rent_pct", 8.0)
            * overall_occupancy
        )
        revenue = max(base_rent, turnover_rent)
        segment_rows: list[dict[str, Any]] = []
    else:
        base_rent = 0.0
        turnover_rent = 0.0
        revenue = 0.0
        segment_rows = []
        for item in mix:
            segment_area = area * item["share"]
            segment_occupancy = min(
                overall_occupancy, item["occupancy_pct"] / 100.0
            )
            segment_base = (
                segment_area
                * item["base_rent_rub_sqm_month"]
                * growth
                * segment_occupancy
            )
            segment_turnover = (
                segment_area
                * item["sales_rub_sqm_month"]
                * growth
                * (item["turnover_rent_pct"] / 100.0)
                * segment_occupancy
            )
            segment_revenue = max(segment_base, segment_turnover)
            base_rent += segment_base
            turnover_rent += segment_turnover
            revenue += segment_revenue
            segment_rows.append({
                "name": item["name"],
                "area": segment_area,
                "occupancy": segment_occupancy,
                "base_rent": segment_base,
                "turnover_rent": segment_turnover,
                "revenue": segment_revenue,
            })

    expense_ratio = min(
        0.95,
        _pct(values, "opex_pct", 22.0) + _pct(values, "marketing_pct", 0.0),
    )
    opex = revenue * expense_ratio
    return {
        "occupancy": overall_occupancy,
        "revenue": revenue,
        "base_rent": base_rent,
        "turnover_rent": turnover_rent,
        "opex": opex,
        "noi": revenue - opex,
        "tenant_segments": segment_rows,
    }


def _hotel_month(values: dict[str, Any], months_open: int) -> dict[str, Any]:
    keys = max(0.0, _f(values, "keys"))
    occupancy = _occupancy("hotel", values, months_open)
    growth = _growth_factor(_pct(values, "adr_growth_pct", 0.0), months_open)
    adr = max(0.0, _f(values, "adr_rub")) * growth
    room_revenue = keys * adr * 365.0 / 12.0 * occupancy
    other_revenue = room_revenue * _pct(values, "other_revenue_pct", 25.0)
    revenue = room_revenue + other_revenue
    operating_expense = revenue * min(0.95, _pct(values, "opex_pct", 58.0))
    management_fee = revenue * min(0.25, _pct(values, "management_fee_pct", 3.0))
    ffe_reserve = revenue * min(0.25, _pct(values, "ffe_reserve_pct", 3.0))
    gop = revenue - operating_expense
    noi = gop - management_fee - ffe_reserve
    return {
        "occupancy": occupancy,
        "adr": adr,
        "revpar": adr * occupancy,
        "room_revenue": room_revenue,
        "other_revenue": other_revenue,
        "revenue": revenue,
        "opex": operating_expense,
        "management_fee": management_fee,
        "ffe_reserve": ffe_reserve,
        "gop": gop,
        "noi": noi,
        "gop_margin": gop / revenue if revenue else None,
        "noi_margin": noi / revenue if revenue else None,
    }


def _operating_month(
    asset: str, values: dict[str, Any], months_open: int
) -> dict[str, Any]:
    if asset == "office":
        return _office_month(values, months_open)
    if asset == "retail":
        return _retail_month(values, months_open)
    return _hotel_month(values, months_open)


def _sale_total(asset: str, values: dict[str, Any]) -> float:
    if asset == "hotel":
        return max(0.0, _f(values, "saleable_keys")) * max(
            0.0, _f(values, "sale_price_rub_key")
        )
    return max(0.0, _f(values, "saleable_area_sqm")) * max(
        0.0, _f(values, "sale_price_rub_sqm")
    )


def _npv_monthly(cashflows: list[float], annual_rate: float) -> float:
    """NPV on monthly cash flows using an effective annual hurdle rate."""
    monthly_rate = (1.0 + max(-0.95, annual_rate)) ** (1.0 / 12.0) - 1.0
    return sum(
        value / ((1.0 + monthly_rate) ** index)
        for index, value in enumerate(cashflows)
    )


def _payback_month(cashflows: list[float]) -> int | None:
    """First month after which cumulative cash flow never turns negative again."""
    cumulative_values: list[float] = []
    cumulative = 0.0
    for value in cashflows:
        cumulative += value
        cumulative_values.append(cumulative)
    if not any(value < 0 for value in cashflows):
        return 0 if cashflows else None
    for index, cumulative in enumerate(cumulative_values):
        if cumulative >= 0 and min(cumulative_values[index:]) >= 0:
            return index
    return None


def _annual_summary(monthly: dict[str, list[float]], horizon: int) -> list[dict[str, Any]]:
    additive = [
        "development_spend",
        "operating_revenue",
        "operating_cost",
        "selling_cost",
        "sale_revenue",
        "terminal_value",
        "disposition_cost",
        "project_cashflow",
        "interest",
        "loan_fees",
        "debt_draw",
        "debt_repayment",
        "equity_injection",
        "equity_distribution",
        "equity_cashflow",
    ]
    rows: list[dict[str, Any]] = []
    years = (horizon + 11) // 12
    for year in range(years):
        start = year * 12
        end = min(horizon, start + 12)
        row: dict[str, Any] = {"year": year + 1, "start_month": start, "end_month": end - 1}
        for key in additive:
            row[key] = sum(monthly[key][start:end])
        row["ending_debt"] = monthly["debt_balance"][end - 1]
        rows.append(row)
    return rows


def _validation(asset: str, values: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    gross_area = max(0.0, _f(values, "gross_area_sqm"))
    if asset in {"office", "retail"}:
        income_area = max(0.0, _f(values, "income_area_sqm"))
        if gross_area and income_area > gross_area:
            warnings.append("Доходная площадь выше ГНС: проверьте эффективность площадей.")
    if _f(values, "occupancy_pct", 0.0) > 100:
        warnings.append("Загрузка ограничена 100% в расчёте.")
    if _f(values, "debt_share_pct", 0.0) > 95:
        warnings.append("Доля кредита ограничена 95% development cost.")
    if _f(values, "exit_cap_rate_pct", 0.0) <= 0:
        warnings.append("Exit cap rate должен быть положительным; движок использует технический минимум.")
    if asset == "retail":
        supplied = values.get("tenant_mix")
        if isinstance(supplied, list) and supplied:
            total = sum(
                max(0.0, float(item.get("share_pct", 0.0) or 0.0))
                for item in supplied if isinstance(item, dict)
            )
            if abs(total - 100.0) > 0.1:
                warnings.append(
                    f"Доли tenant mix суммируются в {total:.1f}%; движок нормализовал их до 100%."
                )
    return warnings


def calculate_v2(req: CommercialRequest) -> dict[str, Any]:
    asset = req.asset_type
    values = default_inputs(asset)
    values.update(req.inputs or {})
    values["financing_mode"] = req.financing_mode

    construction_months = _months(values, "construction_months", 30)
    stabilization_months = _months(values, "stabilization_months", 12)
    hold_months = max(12, _months(values, "hold_years", 5) * 12)
    sale_start = max(0, int(round(_f(values, "sale_start_month", 18))))
    sale_months = _months(values, "sale_months", 24)
    if req.strategy == "income":
        horizon = construction_months + hold_months + 1
    else:
        horizon = max(construction_months + 1, sale_start + sale_months + 1)

    gross_area = max(0.0, _f(values, "gross_area_sqm"))
    land_cost = max(0.0, _f(values, "land_cost_rub"))
    hard_cost = gross_area * max(0.0, _f(values, "construction_cost_rub_sqm"))
    soft_cost = hard_cost * _pct(values, "soft_cost_pct", 12.0)
    contingency = hard_cost * _pct(values, "contingency_pct", 5.0)
    preopening_cost = (
        max(0.0, _f(values, "preopening_cost_rub")) if asset == "hotel" else 0.0
    )
    development_cost = (
        land_cost + hard_cost + soft_cost + contingency + preopening_cost
    )

    development_spend = [0.0] * horizon
    development_spend[0] = land_cost
    weights = _s_curve_weights(construction_months)
    base_build_cost = hard_cost + soft_cost + contingency
    for offset, weight in enumerate(weights, start=1):
        if offset < horizon:
            development_spend[offset] += base_build_cost * weight
    if preopening_cost and construction_months < horizon:
        development_spend[construction_months] += preopening_cost
    # Exact reconciliation protects financing against tiny floating residuals.
    development_spend[min(construction_months, horizon - 1)] += (
        development_cost - sum(development_spend)
    )

    operating_revenue = [0.0] * horizon
    operating_cost = [0.0] * horizon
    operating_noi = [0.0] * horizon
    occupancy = [0.0] * horizon
    rate_metric = [0.0] * horizon
    sale_revenue = [0.0] * horizon
    selling_cost = [0.0] * horizon
    terminal_value = [0.0] * horizon
    disposition_cost = [0.0] * horizon

    stabilized = _operating_month(
        asset, values, max(stabilization_months, 1)
    )

    if req.strategy == "income":
        for month in range(construction_months + 1, horizon):
            months_open = month - construction_months
            economics = _operating_month(asset, values, months_open)
            operating_revenue[month] = economics["revenue"]
            operating_noi[month] = economics["noi"]
            operating_cost[month] = economics["revenue"] - economics["noi"]
            occupancy[month] = economics.get("occupancy", 0.0)
            if asset == "hotel":
                rate_metric[month] = economics.get("adr", 0.0)
            elif asset == "office":
                rate_metric[month] = economics.get("rent", 0.0)
            else:
                revenue = economics.get("revenue", 0.0)
                area = max(0.0, _f(values, "income_area_sqm"))
                rate_metric[month] = (
                    revenue / area / max(economics.get("occupancy", 0.0), 1e-9)
                    if area else 0.0
                )

        exit_months_open = max(1, horizon - 1 - construction_months)
        exit_economics = _operating_month(asset, values, exit_months_open)
        cap_rate = max(0.0001, _pct(values, "exit_cap_rate_pct", 11.0))
        terminal_value[-1] = exit_economics["noi"] * 12.0 / cap_rate
        disposition_cost[-1] = (
            terminal_value[-1] * _pct(values, "exit_cost_pct", 1.0)
        )
    else:
        gross_sales = _sale_total(asset, values)
        weights = _sales_weights(sale_months, str(values.get("sales_curve", "bell")))
        sale_cost_pct = _pct(values, "selling_cost_pct", 2.0)
        sale_price_growth = _pct(values, "sale_price_growth_pct", 0.0)
        for index, quantity_weight in enumerate(weights):
            month = sale_start + index
            if month >= horizon:
                break
            growth = (1.0 + sale_price_growth) ** (index / 12.0)
            amount = gross_sales * quantity_weight * growth
            sale_revenue[month] = amount
            selling_cost[month] = amount * sale_cost_pct

    project_cashflow = [
        operating_revenue[i]
        + sale_revenue[i]
        + terminal_value[i]
        - development_spend[i]
        - operating_cost[i]
        - selling_cost[i]
        - disposition_cost[i]
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
    loan_fee_pct = (
        0.0
        if req.financing_mode == "equity"
        else _pct(values, "loan_fee_pct", 1.0)
    )
    sales_cash_sweep = min(1.0, _pct(values, "sales_cash_sweep_pct", 100.0))
    debt_limit = development_cost * debt_share

    debt_draw = [0.0] * horizon
    interest = [0.0] * horizon
    loan_fees = [0.0] * horizon
    debt_repayment = [0.0] * horizon
    debt_balance = [0.0] * horizon
    debt_before_repayment = [0.0] * horizon
    equity_injection = [0.0] * horizon
    equity_distribution = [0.0] * horizon
    equity_cashflow = [0.0] * horizon

    balance = 0.0
    cumulative_draw = 0.0
    for month in range(horizon):
        target_draw = development_spend[month] * debt_share
        draw = min(max(0.0, debt_limit - cumulative_draw), target_draw)
        cumulative_draw += draw
        debt_draw[month] = draw
        loan_fees[month] = draw * loan_fee_pct

        opening_balance = balance
        # Half-month convention on current draw is closer to a construction loan
        # than charging a full month on money received at the end of the period.
        interest[month] = (opening_balance + 0.5 * draw) * monthly_rate
        balance += draw
        debt_before_repayment[month] = balance

        if req.strategy == "sale" and balance > 0.0:
            net_sale_cash = max(0.0, sale_revenue[month] - selling_cost[month])
            debt_repayment[month] = min(
                balance, net_sale_cash * sales_cash_sweep
            )
        elif req.strategy == "income" and month == horizon - 1 and balance > 0.0:
            debt_repayment[month] = balance

        balance -= debt_repayment[month]
        debt_balance[month] = max(0.0, balance)

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

    # Direct-sale cases can finish with debt if sweep < 100% or sales are weak.
    # Remaining principal is an equity obligation at project close.
    residual_debt = debt_balance[-1] if debt_balance else 0.0
    if residual_debt > 0.01:
        debt_repayment[-1] += residual_debt
        equity_cashflow[-1] -= residual_debt
        if equity_distribution[-1] >= residual_debt:
            equity_distribution[-1] -= residual_debt
        else:
            shortfall = residual_debt - equity_distribution[-1]
            equity_distribution[-1] = 0.0
            equity_injection[-1] += shortfall
        debt_balance[-1] = 0.0

    financing_cost = sum(interest) + sum(loan_fees)
    total_revenue = sum(operating_revenue) + sum(sale_revenue) + sum(terminal_value)
    total_operating_cost = (
        sum(operating_cost) + sum(selling_cost) + sum(disposition_cost)
    )
    total_cost = development_cost + total_operating_cost + financing_cost
    profit_before_tax = total_revenue - total_cost
    equity_required = sum(equity_injection)
    equity_distributed = sum(equity_distribution)
    project_irr = _annualize_monthly(_irr_monthly(project_cashflow))
    equity_irr = _annualize_monthly(_irr_monthly(equity_cashflow))
    peak_debt = max(debt_before_repayment + [0.0])
    stabilized_noi_annual = (
        stabilized.get("noi", 0.0) * 12.0 if req.strategy == "income" else 0.0
    )
    yield_on_cost = (
        stabilized_noi_annual / development_cost
        if development_cost > 0 and stabilized_noi_annual
        else None
    )
    exit_value = sum(terminal_value)
    exit_cost = sum(disposition_cost)
    net_exit_proceeds = exit_value - exit_cost
    exit_noi_annual = (
        exit_value * max(0.0001, _pct(values, "exit_cap_rate_pct", 11.0))
        if req.strategy == "income" else 0.0
    )
    equity_multiple = (
        equity_distributed / equity_required if equity_required > 0 else None
    )
    invested_project_cash = -sum(value for value in project_cashflow if value < 0)
    returned_project_cash = sum(value for value in project_cashflow if value > 0)
    project_multiple = (
        returned_project_cash / invested_project_cash
        if invested_project_cash > 0 else None
    )
    ltc = peak_debt / development_cost if development_cost else None
    exit_debt = debt_balance[-2] if len(debt_balance) > 1 else 0.0
    exit_ltv = (
        exit_debt / exit_value
        if req.strategy == "income" and exit_value > 0 else None
    )
    annual_interest_at_peak = peak_debt * annual_rate
    interest_cover = (
        stabilized_noi_annual / annual_interest_at_peak
        if annual_interest_at_peak > 0 and stabilized_noi_annual else None
    )
    debt_yield = (
        stabilized_noi_annual / peak_debt
        if peak_debt > 0 and stabilized_noi_annual else None
    )

    project_discount_rate = _pct(values, "project_discount_rate_pct", 15.0)
    equity_hurdle_rate = _pct(values, "equity_hurdle_rate_pct", 20.0)
    project_npv = _npv_monthly(project_cashflow, project_discount_rate)
    equity_npv = _npv_monthly(equity_cashflow, equity_hurdle_rate)
    project_payback_month = _payback_month(project_cashflow)
    equity_payback_month = _payback_month(equity_cashflow)

    monthly = {
        "months": list(range(horizon)),
        "development_spend": development_spend,
        "operating_revenue": operating_revenue,
        "operating_cost": operating_cost,
        "selling_cost": selling_cost,
        "operating_noi": operating_noi,
        "occupancy": occupancy,
        "rate_metric": rate_metric,
        "sale_revenue": sale_revenue,
        "terminal_value": terminal_value,
        "disposition_cost": disposition_cost,
        "project_cashflow": project_cashflow,
        "debt_draw": debt_draw,
        "interest": interest,
        "loan_fees": loan_fees,
        "debt_repayment": debt_repayment,
        "debt_before_repayment": debt_before_repayment,
        "debt_balance": debt_balance,
        "equity_injection": equity_injection,
        "equity_distribution": equity_distribution,
        "equity_cashflow": equity_cashflow,
    }

    warnings = [
        "Beta: коммерческая экономика отделена от жилого движка; эскроу и льготная ставка ПФ не применяются.",
        "Продажная модель трактует поступления как прямой денежный поток проекта. Юридическую схему реализации нужно проверять отдельно для конкретного объекта и покупателя.",
    ]
    warnings.extend(_validation(asset, values))

    development_report = {
        "name": "Девелопмент",
        "metrics": {
            "Участок, ₽": land_cost,
            "Hard cost, ₽": hard_cost,
            "Soft costs, ₽": soft_cost,
            "Contingency, ₽": contingency,
            "Pre-opening, ₽": preopening_cost,
            "Development cost, ₽": development_cost,
        },
    }
    financing_report = {
        "name": "Финансирование",
        "metrics": {
            "Peak debt, ₽": peak_debt,
            "LTC": ltc,
            "Exit LTV": exit_ltv,
            "Interest cover": interest_cover,
            "Debt yield": debt_yield,
            "Financing cost, ₽": financing_cost,
            "Project NPV, ₽": project_npv,
            "Equity NPV, ₽": equity_npv,
        },
    }

    report: dict[str, Any] = {
        "title": {
            "office": "Офисная экономика",
            "retail": "Экономика торгового объекта",
            "hotel": "Гостиничная экономика",
        }[asset],
        "strategy": "Доходная модель" if req.strategy == "income" else "Продажа площадей / номеров",
        "financing": (
            "100% собственные средства"
            if req.financing_mode == "equity"
            else "Собственные средства + обычный кредит, без эскроу"
        ),
        "sections": [development_report],
    }

    if asset in {"office", "retail"}:
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
        metrics: dict[str, Any] = {
            "Стабилизированный NOI, ₽/год": stabilized_noi_annual,
            "Exit value gross, ₽": exit_value,
            "Расходы на выход, ₽": exit_cost,
            "Exit proceeds net, ₽": net_exit_proceeds,
            "NOI на выходе, ₽/год": exit_noi_annual,
            "Yield on cost": yield_on_cost,
        }
        if asset == "office":
            metrics.update({
                "Аренда, ₽/м²/мес.": stabilized.get("rent"),
                "Загрузка": stabilized.get("occupancy"),
            })
        elif asset == "retail":
            metrics.update({
                "Базовая аренда, ₽/мес.": stabilized.get("base_rent"),
                "Процент с оборота, ₽/мес.": stabilized.get("turnover_rent"),
                "Загрузка": stabilized.get("occupancy"),
            })
        else:
            metrics.update({
                "ADR, ₽": stabilized.get("adr"),
                "RevPAR, ₽": stabilized.get("revpar"),
                "GOP margin": stabilized.get("gop_margin"),
                "NOI margin": stabilized.get("noi_margin"),
            })
        report["sections"].append({"name": "Доход", "metrics": metrics})
    else:
        report["sections"].append({
            "name": "Продажи",
            "metrics": {
                "Валовая выручка, ₽": sum(sale_revenue),
                "Расходы на продажи, ₽": sum(selling_cost),
                "Чистые поступления, ₽": sum(sale_revenue) - sum(selling_cost),
                "Эскроу, ₽": 0.0,
            },
        })

    report["sections"].append(financing_report)

    return {
        "version": "commercial-beta-2",
        "asset_type": asset,
        "strategy": req.strategy,
        "financing_mode": req.financing_mode,
        "uses_escrow": False,
        "inputs": values,
        "kpi": {
            "development_cost": development_cost,
            "financing_cost": financing_cost,
            "total_cost": total_cost,
            "total_revenue": total_revenue,
            "profit_before_tax": profit_before_tax,
            "margin": profit_before_tax / total_revenue if total_revenue else None,
            "project_irr": project_irr,
            "project_multiple": project_multiple,
            "project_npv": project_npv,
            "project_payback_month": project_payback_month,
            "equity_irr": equity_irr,
            "equity_multiple": equity_multiple,
            "equity_npv": equity_npv,
            "equity_payback_month": equity_payback_month,
            "equity_required": equity_required,
            "equity_distributed": equity_distributed,
            "equity_return": equity_distributed - equity_required,
            "peak_debt": peak_debt,
            "ltc": ltc,
            "exit_ltv": exit_ltv,
            "interest_cover": interest_cover,
            "debt_yield": debt_yield,
            "stabilized_noi_annual": stabilized_noi_annual,
            "yield_on_cost": yield_on_cost,
            "exit_value": exit_value,
            "exit_cost": exit_cost,
            "net_exit_proceeds": net_exit_proceeds,
            "exit_noi_annual": exit_noi_annual,
        },
        "operating": stabilized,
        "monthly": monthly,
        "annual": _annual_summary(monthly, horizon),
        "report": report,
        "warnings": warnings,
        "checks": {
            "development_spend_reconciles": abs(sum(development_spend) - development_cost) < 0.01,
            "ending_debt_zero": abs(debt_balance[-1]) < 0.01,
            "peak_debt_within_limit": peak_debt <= debt_limit + 0.01,
            "project_cashflow_reconciles": abs(
                sum(project_cashflow)
                - (
                    total_revenue
                    - development_cost
                    - sum(operating_cost)
                    - sum(selling_cost)
                    - sum(disposition_cost)
                )
            ) < 0.01,
            "uses_escrow": False,
        },
    }
