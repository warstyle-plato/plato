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
) -> dict[str, Any]:
    """Собрать модель представления из посчитанного.

    `numbers` — величины в миллионах и долях, посчитанные движком
    (`presentation_numbers`); `consolidated` — свод расчёта; `phases` —
    очереди с их результатами; `origin` — происхождение расчёта
    (`calculation_id`, версия движка, время).
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
            "avg_price_th": _number(product.get("avg_price_th")),
            "sales_start": _text(product.get("sales_start")),
            "sales_end": _text(product.get("sales_end")),
        })

    tep_total = (consolidated.get("tep") or {}).get("total") or {}
    tep = {
        "project_gns_sqm": _number(summary.get("project_gns_sqm")),
        "underground_gns_sqm": _number(summary.get("underground_gns_sqm")),
        "construction_volume_sqm": _number(summary.get("construction_volume_sqm")),
        "saleable_sqm": _number(tep_total.get("saleable")),
        "apartment_saleable_sqm": _number(summary.get("apartment_saleable_sqm")),
        "transfer_sqm": _number(tep_total.get("transfer")),
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
                    "llcr": _number(((p.get("result") or {}).get("summary") or {}).get("llcr"))}
                   for p in phases],
        "origin": dict(origin),
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
