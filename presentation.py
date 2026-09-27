"""Модель представления проекта — одна на «Дашборд» книги и тизер PDF.

Слой ВЫБИРАЕТ и ПОДПИСЫВАЕТ величины, посчитанные движком, и не считает
ничего сам: ни единиц, ни долей, ни разностей. Первое «просто поделить на
миллион» здесь — вторая реализация экономики, и её запрещает тест, ищущий в
этом файле любую арифметику (как у `developaid_v2_result.py`). Числа в
миллионах приходят готовыми из движка (`presentation_numbers` в
`main_legacy`): там они и считаются, там же, где считает паритет книги.

Порядок и состав карточек объявлены здесь один раз — книга и тизер читают их
отсюда, иначе две поверхности разошлись бы составом молча.
"""

from __future__ import annotations

from typing import Any

# Ключ, подпись, единица. Первые шесть — карточки; все одиннадцать — таблица.
KPI_CATALOGUE: tuple[tuple[str, str, str], ...] = (
    ("revenue_mln", "Выручка", "млн ₽"),
    ("capex_mln", "CAPEX", "млн ₽"),
    ("ebitda_mln", "EBITDA", "млн ₽"),
    ("net_profit_mln", "Чистая прибыль", "млн ₽"),
    ("margin", "Маржинальность", "%"),
    ("llcr", "LLCR", "x"),
    ("peak_bridge_mln", "Пик БРИДЖа", "млн ₽"),
    ("peak_pf_mln", "Пик ПФ", "млн ₽"),
    ("financing_mln", "Стоимость финансирования", "млн ₽"),
    ("npv_mln", "NPV собственного капитала", "млн ₽"),
    ("term_months", "Срок проекта", "мес."),
)
CARD_COUNT = 6

# Величины моста «от выручки к чистой прибыли»: ключ величины и знак бара.
BRIDGE_STEPS: tuple[tuple[str, str, int], ...] = (
    ("revenue_mln", "Выручка", 1),
    ("capex_mln", "CAPEX", -1),
    ("commercial_mln", "Коммерческие расходы", -1),
    ("financing_mln", "Финансирование", -1),
    ("tax_mln", "Налог на прибыль", -1),
    ("vat_mln", "НДС", -1),
    ("net_profit_mln", "Чистая прибыль", 1),
)

# Авто-риски: ключ, подпись, ключ величины рядом (в млн или x).
RISK_CATALOGUE: tuple[tuple[str, str, str], ...] = (
    ("default_rve", "Дефолт в РВЭ: раскрытого эскроу не хватило", "rve_unpaid_mln"),
    ("pf_shortfall", "Одобренного лимита ПФ не хватило", "pf_shortfall_mln"),
    ("llcr_below_target", "LLCR ниже целевого уровня банка", "llcr"),
    ("ending_debt", "Долг не погашен на конец проекта", "ending_pf_mln"),
    ("weakest_phase", "Слабейшая очередь ниже 1,00x", "weakest_phase_llcr"),
)

PRODUCT_ORDER: tuple[str, ...] = (
    "apartments", "ground_commercial", "underground_parking", "storage",
    "offices", "standalone_retail", "above_parking", "sports", "object_parking",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_project_presentation(
    numbers: dict[str, Any],
    consolidated: dict[str, Any],
    phases: list[dict[str, Any]],
    inputs: dict[str, Any],
    origin: dict[str, Any],
    llcr_target: float,
    site: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать модель представления из посчитанного.

    `numbers` — величины в миллионах и долях, посчитанные движком
    (`presentation_numbers`); `consolidated` — свод расчёта; `phases` —
    очереди с их результатами; `origin` — происхождение расчёта
    (`calculation_id`, версия движка, время); `site` — участок, о котором
    посчитано (кадастровые номера, адрес), как его прислала страница.
    """
    summary = consolidated.get("summary") or {}
    finance = consolidated.get("finance") or {}
    report = consolidated.get("report") or {}
    dates = consolidated.get("dates") or {}

    kpi: list[dict[str, Any]] = []
    for key, label, unit in KPI_CATALOGUE:
        kpi.append({"key": key, "label": label, "unit": unit,
                    "value": _number(numbers.get(key))})

    products: list[dict[str, Any]] = []
    by_key = {str(p.get("key")): p for p in (report.get("products") or [])}
    product_numbers = numbers.get("products") or {}
    for key in PRODUCT_ORDER:
        product = by_key.get(key)
        if not product:
            continue
        products.append({
            "key": key,
            "label": _text(product.get("label")),
            "unit": _text(product.get("unit")),
            "quantity": _number(product.get("quantity")),
            "gns": _number(product.get("gns")),
            "saleable": _number(product.get("saleable")),
            "revenue_mln": _number((product_numbers.get(key) or {}).get("revenue_mln")),
            "cost_mln": _number((product_numbers.get(key) or {}).get("cost_mln")),
            "per_gns_th": _number((product_numbers.get(key) or {}).get("per_gns_th")),
            "per_saleable_th": _number((product_numbers.get(key) or {}).get("per_saleable_th")),
            "per_unit_th": _number((product_numbers.get(key) or {}).get("per_unit_th")),
            "pace_year": _number((product_numbers.get(key) or {}).get("pace_year")),
            "pace_month": _number(product.get("pace_pre")),
            "start_price_th": _number(product.get("start_price_th")),
            "share_before_rve": _number(product.get("share_before_rve")),
            "avg_price_th": _number(product.get("avg_price_th")),
            "sales_start": _text(product.get("sales_start")),
            "sales_end": _text(product.get("sales_end")),
        })

    tep_total = (consolidated.get("tep") or {}).get("total") or {}
    tep_rows = (consolidated.get("tep") or {}).get("rows") or []
    tep = {
        "project_gns_sqm": _number(summary.get("project_gns_sqm")),
        "underground_gns_sqm": _number(summary.get("underground_gns_sqm")),
        "construction_volume_sqm": _number(summary.get("construction_volume_sqm")),
        "saleable_sqm": _number(tep_total.get("saleable")),
        "apartment_saleable_sqm": _number(summary.get("apartment_saleable_sqm")),
        "transfer_sqm": _number(tep_total.get("transfer")),
        "total_area_sqm": _number(tep_total.get("total_area")),
        "units": _number(tep_total.get("units")),
        "parking_units": _number(tep_total.get("units")),
        "parking_saleable_units": _number(tep_total.get("saleable_units")),
        "residential_saleable_sqm": _number(_row(tep_rows, "apartments").get("saleable")),
        "commercial_saleable_sqm": _number(_row(tep_rows, "ground_commercial").get("saleable")),
        "apartments_count": _number(_row(tep_rows, "apartments").get("units")),
        "parking_required": _number((numbers.get("parking") or {}).get("required_total")),
        "parking_provision": _number((numbers.get("parking") or {}).get("provision")),
    }

    weakest = _weakest_phase(phases)
    risk_values = {
        "rve_unpaid_mln": _number(numbers.get("rve_unpaid_mln")),
        "pf_shortfall_mln": _number(numbers.get("pf_shortfall_mln")),
        "llcr": _number(numbers.get("llcr")),
        "ending_pf_mln": _number(numbers.get("ending_pf_mln")),
        "weakest_phase_llcr": weakest.get("llcr"),
    }
    llcr = risk_values["llcr"]
    flags = {
        "default_rve": (risk_values["rve_unpaid_mln"] or 0.0) > 0.5,
        "pf_shortfall": (risk_values["pf_shortfall_mln"] or 0.0) > 0.5,
        "llcr_below_target": llcr is not None and llcr < llcr_target,
        "ending_debt": (risk_values["ending_pf_mln"] or 0.0) > 0.5,
        "weakest_phase": (weakest.get("llcr") is not None
                          and float(weakest["llcr"]) < 1.0),
    }
    risks: list[dict[str, Any]] = []
    for key, label, value_key in RISK_CATALOGUE:
        if key == "weakest_phase" and not weakest:
            continue
        risks.append({
            "key": key, "label": label, "active": bool(flags[key]),
            "value_key": value_key, "value": risk_values.get(value_key),
            "detail": _risk_detail(key, finance, weakest),
        })

    return {
        "project_name": _text(inputs.get("project_name")) or "Проект DevelopAid",
        "kpi": kpi,
        "cards": kpi[:CARD_COUNT],
        "tep": tep,
        "products": products,
        "sales": {
            "start": _text(dates.get("sales_start")),
            "rve": _text(dates.get("rve")),
            "end": max((p["sales_end"] for p in products if p["sales_end"]), default=""),
        },
        "dates": {
            "project_start": _text(dates.get("project_start")),
            "permit": _text(dates.get("permit")),
            "rve": _text(dates.get("rve")),
        },
        "bridge": [{"key": key, "label": label, "sign": sign,
                    "value": _number(numbers.get(key))}
                   for key, label, sign in BRIDGE_STEPS],
        "risks": risks,
        "llcr_target": llcr_target,
        "phases": [{"name": _text(p.get("name")),
                    "llcr": _number(((p.get("result") or {}).get("summary") or {}).get("llcr")),
                    "dates": _phase_dates(p)}
                   for p in phases],
        "origin": dict(origin),
        # Разделы образца владельца (тизер + «Итог», 10.03.2026): всё ниже —
        # выбор и подпись величин движка, ни одного своего счёта.
        "site": _site_block(site or {}, inputs),
        "profile": _profile_block(inputs, dates),
        "land": _land_block(numbers, inputs),
        "financing": _financing_block(numbers, inputs),
        "efficiency": _efficiency_block(numbers),
        "sales_stats": _sales_block(numbers, dates, products),
        "unit_economics": list(numbers.get("unit_economics") or []),
        "construction_costs": list(numbers.get("construction_costs") or []),
        "expense_structure": list(numbers.get("expense_structure") or []),
        "taxes": {
            "vat_mln": _number(numbers.get("vat_mln")),
            "profit_tax_mln": _number(numbers.get("tax_mln")),
            "profit_before_tax_mln": _number((numbers.get("taxes") or {}).get("profit_before_tax_mln")),
            "profit_tax_rate": _number((numbers.get("taxes") or {}).get("profit_tax_rate")),
        },
        "chart_rows": list(numbers.get("chart_rows") or []),
    }


def _row(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next((r for r in rows if str(r.get("key")) == key), {})


def _phase_dates(phase: dict[str, Any]) -> dict[str, str]:
    dates = (phase.get("result") or {}).get("dates") or {}
    products = ((phase.get("result") or {}).get("report") or {}).get("products") or []
    return {
        "project_start": _text(dates.get("project_start")),
        "permit": _text(dates.get("permit")),
        "sales_start": _text(dates.get("sales_start")),
        "rve": _text(dates.get("rve")),
        "sales_end": max((_text(p.get("sales_end")) for p in products), default=""),
    }


CLASS_LABELS = {"comfort": "Комфорт", "business": "Бизнес", "elite": "Элитный"}
REGION_LABELS = {"msk": "Москва", "mo": "Московская область"}


LAND_RIGHT_LABELS = {"ownership": "Собственность", "lease": "Аренда"}


def _site_block(site: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Участок: что прислала страница и что ответил скрининг (`_teaser_site_facts`).
    Пустой скрининг — «не проверяли», а не «ограничений нет»."""
    numbers = [str(x) for x in (site.get("cadastral_numbers") or []) if x]
    verdict = site.get("verdict") or {}
    return {
        "cadastral_numbers": numbers,
        "address": _text(site.get("address")),
        "region": REGION_LABELS.get(_text(inputs.get("vri_region")), _text(inputs.get("vri_region"))),
        "land_right": LAND_RIGHT_LABELS.get(_text(inputs.get("land_right")), _text(inputs.get("land_right"))),
        "land_area_sqm": _number(site.get("land_area_sqm")),
        "land_area_ha": _number(site.get("land_area_ha")),
        "density_sqm_per_ha": _number(site.get("density_sqm_per_ha")),
        "permitted_use": _text(site.get("permitted_use")),
        "category": _text(site.get("category")),
        "screened": bool(site.get("screened")),
        "verdict_headline": _text(verdict.get("headline")),
        "verdict_status": _text(verdict.get("status")),
        "free_pct": _number(verdict.get("free_pct")),
        "findings": [{"name": _text(f.get("name")), "flag_class": _text(f.get("flag_class")),
                      "impact": _text(f.get("impact")), "coverage_pct": _number(f.get("coverage_pct"))}
                     for f in (site.get("findings") or [])],
        "parcels": [{"cadastral_number": _text(p.get("cadastral_number")),
                     "address": _text(p.get("address")), "area_sqm": _number(p.get("area_sqm"))}
                    for p in (site.get("parcels") or [])],
    }


def _profile_block(inputs: dict[str, Any], dates: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_class": CLASS_LABELS.get(_text(inputs.get("project_class")),
                                          _text(inputs.get("project_class"))),
        "purchase_price_mln": _number(inputs.get("purchase_price_mln")),
        "land_right": _text(inputs.get("land_right")),
        "project_start": _text(dates.get("project_start")),
        "permit": _text(dates.get("permit")),
        "rve": _text(dates.get("rve")),
        "scenario": _text(inputs.get("rate_scenario")),
    }


def _land_block(numbers: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    land = numbers.get("land") or {}
    return {
        "vri_required": bool(inputs.get("vri_required")),
        "vri_amount_mln": _number(land.get("vri_amount_mln")),
        "vri_relief_mln": _number(land.get("vri_relief_mln")),
        "vri_interest_mln": _number(land.get("vri_interest_mln")),
        "vri_payment_mode": _text(inputs.get("vri_payment_mode")),
        "land_rights_mln": _number(land.get("land_rights_mln")),
        "social_payment_mln": _number(land.get("social_payment_mln")),
        "social_payment_mode": _text(land.get("social_payment_mode")),
        "kindergarten_places": _number(inputs.get("kindergarten_places")),
        "school_places": _number(inputs.get("school_places")),
        "purchase_mln": _number(land.get("purchase_mln")),
        "purchase_per_saleable_th": _number(land.get("purchase_per_saleable_th")),
    }


def _financing_block(numbers: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    fin = numbers.get("financing") or {}
    return {
        "peak_bridge_mln": _number(numbers.get("peak_bridge_mln")),
        "bridge_interest_mln": _number(fin.get("bridge_interest_mln")),
        "bridge_fee_mln": _number(fin.get("bridge_fee_mln")),
        "peak_pf_mln": _number(numbers.get("peak_pf_mln")),
        "pf_interest_mln": _number(fin.get("pf_interest_mln")),
        "pf_limit_fee_mln": _number(fin.get("pf_limit_fee_mln")),
        "pf_reservation_fee_mln": _number(fin.get("pf_reservation_fee_mln")),
        "pf_limit_required_mln": _number(fin.get("pf_limit_required_mln")),
        "pf_limit_mln": _number(fin.get("pf_limit_mln")),
        "pf_limit_approved_mln": _number(fin.get("pf_limit_approved_mln")),
        "own_funds_mln": _number(fin.get("own_funds_mln")),
        "peak_uncovered_pf_mln": _number(fin.get("peak_uncovered_pf_mln")),
        "peak_escrow_mln": _number(fin.get("peak_escrow_mln")),
        "rve_escrow_release_mln": _number(fin.get("rve_escrow_release_mln")),
        "interest_and_fees_mln": _number(fin.get("interest_and_fees_mln")),
        "financing_mln": _number(numbers.get("financing_mln")),
        "avg_pf_effective_rate": _number(fin.get("avg_pf_effective_rate")),
        "avg_bridge_rate": _number(fin.get("avg_bridge_rate")),
        "current_key_rate": _number(fin.get("current_key_rate")),
        "bridge_spread": _number(fin.get("bridge_spread")),
        "pf_spread_pp": _number(inputs.get("pf_spread_pp")),
        "pf_special_rate": _number(fin.get("pf_special_rate")),
    }


def _efficiency_block(numbers: dict[str, Any]) -> dict[str, Any]:
    eff = numbers.get("efficiency") or {}
    return {
        "ebitda_mln": _number(numbers.get("ebitda_mln")),
        "net_profit_mln": _number(numbers.get("net_profit_mln")),
        "margin": _number(numbers.get("margin")),
        "irr_equity": _number(eff.get("irr_equity")),
        "npv_mln": _number(numbers.get("npv_mln")),
        "term_months": _number(numbers.get("term_months")),
        "llcr": _number(numbers.get("llcr")),
        "full_project_cost_mln": _number(eff.get("full_project_cost_mln")),
        "commercial_mln": _number(numbers.get("commercial_mln")),
        "revenue_mln": _number(numbers.get("revenue_mln")),
        "capex_mln": _number(numbers.get("capex_mln")),
        "financing_mln": _number(numbers.get("financing_mln")),
        "tax_mln": _number(numbers.get("tax_mln")),
        "vat_mln": _number(numbers.get("vat_mln")),
    }


def _sales_block(numbers: dict[str, Any], dates: dict[str, Any],
                 products: list[dict[str, Any]]) -> dict[str, Any]:
    sales = numbers.get("sales") or {}
    return {
        "pace_sqm_month": _number(sales.get("apartment_pace_sqm_month")),
        "pace_sqm_year": _number(sales.get("apartment_pace_sqm_year")),
        "share_before_rve": _number(sales.get("apartment_share_before_rve")),
        "avg_unit_sqm": _number(sales.get("avg_unit_sqm")),
        "avg_unit_price_mln": _number(sales.get("avg_unit_price_mln")),
        "units_total": _number(sales.get("units_total")),
        "sales_start": _text(dates.get("sales_start")),
        "rve": _text(dates.get("rve")),
        "sales_end": max((p["sales_end"] for p in products if p["sales_end"]), default=""),
    }


def _weakest_phase(phases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {"name": _text(p.get("name")),
         "llcr": _number(((p.get("result") or {}).get("summary") or {}).get("llcr"))}
        for p in phases
    ]
    rows = [row for row in rows if row["llcr"] is not None]
    if len(rows) < 2:
        return {}
    return min(rows, key=lambda row: row["llcr"])


def _risk_detail(key: str, finance: dict[str, Any], weakest: dict[str, Any]) -> str:
    if key == "default_rve":
        return _text(finance.get("default_date"))
    if key == "pf_shortfall":
        return _text(finance.get("pf_shortfall_month"))
    if key == "weakest_phase":
        return _text(weakest.get("name"))
    return ""
