"""Preliminary KRT screening through the authoritative DevelopAid model.

The public KRT catalogue has enough data for a product/scale screen, but not
for an investment decision: acquisition price, land-rights/VRI payments and
the complete investor obligations are absent.  This module therefore builds a
transparent zero-entry scenario, runs the existing model, and reports both the
result and the missing inputs.  It deliberately does not create a second
financial calculator.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from market_search.segments import BUSINESS, COMFORT, ECONOMY, ELITE, PREMIUM, normalize_segment


TARGET_PHASE_SALEABLE_SQM = 70_000.0
MAX_PHASES = 5
PHASE_GAP_MONTHS = 12
TARGET_LLCR = 1.20
PARKING_GNS_PER_SPACE = 100.0
PARKING_GUEST_SHARE = 0.10
UNDERGROUND_AREA_PER_SPACE = 35.0

_CLASS_MAP = {
    ECONOMY: ("comfort", "Комфорт", "Эконом сопоставлен с ближайшим доступным пресетом «Комфорт»"),
    COMFORT: ("comfort", "Комфорт", None),
    BUSINESS: ("business", "Бизнес", None),
    PREMIUM: ("elite", "Элитный", "Премиум сопоставлен с ближайшим доступным пресетом «Элитный»"),
    ELITE: ("elite", "Элитный", None),
}

_TEP_FIELDS = ("gns", "total_area", "useful", "saleable", "transfer", "units")


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ru_number(value: Any, digits: int = 0) -> str:
    return f"{_number(value):,.{digits}f}".replace(",", " ")


def _queue_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "очередь"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "очереди"
    return "очередей"


def _verdict(report: dict[str, Any]) -> dict[str, Any]:
    analysis = report.get("analysis") or {}
    return analysis.get("site") or analysis.get("overall") or {}


def _empty_tep(core: Any) -> dict[str, dict[str, Any]]:
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for row in tep.values():
        for field in _TEP_FIELDS:
            row[field] = 0.0
    return tep


def _market_inputs(report: dict[str, Any]) -> tuple[str | None, float, float, str]:
    verdict = _verdict(report)
    hint = report.get("price_hint") or {}
    segment = normalize_segment(verdict.get("segment"))
    market_price = _number(verdict.get("price_per_sqm") or hint.get("price_per_sqm"))
    entry_price = _number(hint.get("entry_per_sqm"))
    if entry_price > 0:
        return segment, entry_price, market_price, "медиана входных цен соседних проектов"
    return segment, market_price, market_price, "медиана действующих прайсов рекомендованного класса"


def _phase_configuration(saleable_sqm: float, construction_months: int) -> dict[str, Any]:
    count = max(1, min(MAX_PHASES, math.ceil(saleable_sqm / TARGET_PHASE_SALEABLE_SQM)))
    return {
        "enabled": count > 1,
        "user_enabled": False,
        "automatic": True,
        "phase_count": count,
        "target_size_sqm": TARGET_PHASE_SALEABLE_SQM,
        "phase_gap_months": PHASE_GAP_MONTHS,
        "cost_inflation_pct": 8.0,
        "sales_price_inflation_pct": 8.0,
        "phases": [
            {
                "name": f"О{index + 1}",
                "start_offset_months": index * PHASE_GAP_MONTHS,
                "construction_months": construction_months,
                "products": {},
            }
            for index in range(count)
        ],
    }


def _snapshot(core: Any, result: dict[str, Any]) -> dict[str, Any]:
    if hasattr(core, "_result_snapshot"):
        return core._result_snapshot(result)
    summary = result.get("summary") or {}
    finance = result.get("finance") or {}
    return {
        "revenue_mln": round(_number(summary.get("revenue")) / 1e6, 2),
        "capex_mln": round(_number(summary.get("capex")) / 1e6, 2),
        "net_profit_mln": round(_number(summary.get("net_profit")) / 1e6, 2),
        "margin_pct": round(_number(summary.get("margin")) * 100, 2),
        "llcr_x": round(_number(summary.get("llcr")), 4),
        "peak_bridge_mln": round(_number(finance.get("peak_bridge")) / 1e6, 2),
        "peak_pf_mln": round(_number(finance.get("peak_pf")) / 1e6, 2),
    }


def _phase_rows(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in bundle.get("phases") or []:
        summary = (item.get("result") or {}).get("summary") or {}
        rows.append({
            "name": item.get("name") or f"О{len(rows) + 1}",
            "saleable_sqm": round(_number(summary.get("monetizable_saleable_sqm"))),
            "llcr_x": round(_number(summary.get("llcr")), 3),
            "margin_pct": round(_number(summary.get("margin")) * 100, 1),
        })
    return rows


def _goal_seek_entry_capacity(
    core: Any,
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    phasing: dict[str, Any],
    bundle: dict[str, Any],
) -> dict[str, Any] | None:
    if not all(hasattr(core, name) for name in ("AgentChatRequest", "_tool_goal_seek")):
        return None
    request = core.AgentChatRequest(
        message="Предварительный скрининг КРТ",
        inputs=inputs,
        tep=tep,
        rates=[],
        phasing=phasing,
        selected_view="all",
    )
    scope = "weakest_phase" if bundle.get("mode") == "phased" else "consolidated"
    result = core._tool_goal_seek(
        request,
        bundle,
        "purchase_price_mln",
        "llcr",
        TARGET_LLCR,
        "at_least",
        "maximum_variable",
        scope,
        0.0,
        None,
    )
    if not result.get("available"):
        return {"available": False, "reason": result.get("reason")}
    solution = result.get("solution") or {}
    return {
        "available": True,
        "amount_mln": round(_number(solution.get("variable")), 1),
        "llcr_x": round(_number(solution.get("metric")), 3),
        "scope": result.get("scope"),
        "phase_llcr": result.get("phase_llcr_at_solution") or [],
        "meaning": (
            "Предельный резерв по переменной «цена входа» при целевом LLCR 1,20x. "
            "Это не оценка участка: цена, ВРИ и обязательства делят это пространство, "
            "а иной график их оплаты изменит результат."
        ),
    }


def _traffic_light(weakest_llcr: float, net_profit_mln: float) -> dict[str, Any]:
    if net_profit_mln <= 0 or weakest_llcr < 1.0:
        return {"tone": "bad", "label": "Не проходит даже до цены входа", "score": 25}
    if weakest_llcr < TARGET_LLCR:
        return {"tone": "warn", "label": "Ниже целевого LLCR", "score": 55}
    return {"tone": "ok", "label": "Операционный сценарий проходит", "score": 85}


def build_krt_model_screening(
    project: dict[str, Any] | None,
    market_report: dict[str, Any],
    core: Any,
) -> dict[str, Any]:
    """Run an on-demand, explicitly preliminary KRT scenario in DevelopAid."""
    if not project:
        return {"available": False, "reason": "Проект КРТ не найден в официальном каталоге"}
    housing_gfa = _number(project.get("housing_gfa_sqm"))
    if housing_gfa <= 0:
        return {
            "available": False,
            "reason": "В официальном каталоге нет жилого объёма для расчёта жилого продукта",
        }

    segment, start_price, market_price, price_basis = _market_inputs(market_report)
    if not segment or segment not in _CLASS_MAP:
        return {"available": False, "reason": "Маркетинг пока не определил класс продукта"}
    if start_price <= 0:
        return {"available": False, "reason": "Маркетинг пока не дал ценового ориентира"}

    model_class, class_label, class_note = _CLASS_MAP[segment]
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    preset = copy.deepcopy(core.PROJECT_CLASS_PRESETS[model_class])
    inputs.update({key: value for key, value in preset.items() if key != "label"})
    inputs.update({
        "project_class": model_class,
        "apartment_price_th": start_price / 1000.0,
        "purchase_price_mln": 0.0,
        "land_rights_cost_mln": 0.0,
        "vri_required": False,
        "vri_security_cost_mln": 0.0,
        "social_mode": "Денежная компенсация",
        "social_compensation_mln": 0.0,
        "kindergarten_places": 0.0,
        "school_places": 0.0,
        "clinic_capacity": 0.0,
        "social_dou_gba_sqm": 0.0,
        "social_school_gba_sqm": 0.0,
        "social_clinic_gba_sqm": 0.0,
        "offices_enabled": False,
        "retail_enabled": False,
        "above_parking_enabled": False,
    })

    tep = _empty_tep(core)
    apartment_ratios = core.TEP_RATIOS["apartments"]
    saleable = housing_gfa * _number(apartment_ratios.get("saleable_of_gns"))
    total_area = housing_gfa * _number(apartment_ratios.get("total_of_gns"))
    verdict = _verdict(market_report)
    lot_area = _number(verdict.get("sold_lot_avg"))
    if lot_area <= 0:
        default_apartments = core.TEP_DEFAULT.get("apartments") or {}
        lot_area = (
            _number(default_apartments.get("saleable")) / _number(default_apartments.get("units"))
            if _number(default_apartments.get("units")) > 0 else 58.7
        )
    tep["apartments"].update({
        "gns": housing_gfa,
        "total_area": total_area,
        "useful": saleable,
        "saleable": saleable,
        "units": saleable / lot_area,
    })

    parking_spaces = math.ceil(housing_gfa / PARKING_GNS_PER_SPACE)
    parking_spaces += math.ceil(parking_spaces * PARKING_GUEST_SHARE)
    parking_gns = parking_spaces * UNDERGROUND_AREA_PER_SPACE
    tep["underground_parking"].update({
        "gns": parking_gns,
        "total_area": parking_gns,
        "units": parking_spaces,
    })
    inputs["underground_manual_spaces"] = parking_spaces
    inputs["underground_manual_gns_sqm"] = parking_gns
    inputs["underground_parking_disabled"] = False

    phasing = _phase_configuration(saleable, int(_number(inputs.get("construction_months")) or 24))
    units_total = saleable / lot_area
    observed_pace = _number(verdict.get("units_per_month"))
    absorption: dict[str, Any] = {"available": False}
    if observed_pace > 0:
        units_per_phase = units_total / phasing["phase_count"]
        construction_months = int(_number(inputs.get("construction_months")) or 24)
        sold_before_rve = min(units_per_phase, observed_pace * construction_months)
        share_before_rve = sold_before_rve / units_per_phase * 100 if units_per_phase else 100.0
        residual_months = math.ceil(max(0.0, units_per_phase - sold_before_rve) / observed_pace)
        inputs["share_before_rve_pct"] = share_before_rve
        inputs["residual_sales_months"] = residual_months
        absorption = {
            "available": True,
            "market_units_per_month": round(observed_pace, 1),
            "estimated_units_per_phase": round(units_per_phase),
            "sellout_months_per_phase": math.ceil(units_per_phase / observed_pace),
            "share_before_rve_pct": round(share_before_rve, 1),
            "residual_sales_months": residual_months,
            "basis": "Медианный темп ДДУ рекомендованного класса принят на одну очередь.",
        }
    bundle = core._run_authoritative_model(inputs, tep, [], phasing)
    consolidated = bundle["consolidated"]
    metrics = _snapshot(core, consolidated)
    phases = _phase_rows(bundle)
    weakest_llcr = min((row["llcr_x"] for row in phases), default=_number(metrics.get("llcr_x")))
    traffic = _traffic_light(weakest_llcr, _number(metrics.get("net_profit_mln")))
    entry_capacity = _goal_seek_entry_capacity(core, inputs, tep, phasing, bundle)
    capped_at_five = (
        phasing["phase_count"] == MAX_PHASES
        and saleable > TARGET_PHASE_SALEABLE_SQM * MAX_PHASES
    )

    queue_text = (
        f"объём автоматически разделён на {phasing['phase_count']} "
        f"{_queue_word(phasing['phase_count'])}"
        if phasing["enabled"] else "объём помещается в одну очередь"
    )
    text = (
        f"Маркетинг рекомендует класс «{segment}»; в модель поставлена стартовая цена "
        f"{_ru_number(start_price)} ₽/м². {queue_text.capitalize()}. "
        f"До цены входа и неизвестных обязательств модель даёт LLCR слабейшей очереди "
        f"{weakest_llcr:.2f}x и маржу {metrics.get('margin_pct', 0):.1f}%."
    )

    assumptions = [
        f"Жилой объём krt.mos.ru {_ru_number(housing_gfa)} м² принят за ГНС; продаваемая площадь — {_ru_number(saleable)} м² по действующей пропорции DevelopAid 65%.",
        f"Стартовая цена {_ru_number(start_price)} ₽/м² взята из маркетинга: {price_basis}.",
        f"Себестоимость основного строительства взята из пресета «{class_label}»: "
        f"{_ru_number(preset.get('main_above_th_per_sqm'))} тыс. ₽/м² наземной и "
        f"{_ru_number(preset.get('main_under_th_per_sqm'))} тыс. ₽/м² подземной части.",
        f"Квартирография: средний продаваемый лот {_ru_number(lot_area, 1)} м²; расчётно {_ru_number(saleable / lot_area)} квартир.",
        f"Паркинг рассчитан по методике импорта DevelopAid: {_ru_number(parking_spaces)} мест по {_ru_number(UNDERGROUND_AREA_PER_SPACE)} м² ГНС; "
        f"цена места — {_ru_number(_number(preset.get('parking_price_th')) / 1000, 1)} млн ₽ из классового пресета.",
        "Рост цены принят по базовым вводным модели: 1,5% в месяц до РВЭ и 0,25% после РВЭ; "
        "для очередей дополнительно применены 8% в год к затратам и их стартовой цене.",
    ]
    if absorption["available"]:
        assumptions.append(
            f"Темп рынка {_ru_number(absorption['market_units_per_month'], 1)} ДДУ/мес. принят на одну очередь: "
            f"{_ru_number(absorption['share_before_rve_pct'], 1)}% продаж до РВЭ и "
            f"{absorption['residual_sales_months']} мес. остаточных продаж."
        )
    else:
        assumptions.append(
            "Темп ДДУ в маркетинге не определён; график продаж оставлен по базовым вводным DevelopAid."
        )
    if capped_at_five:
        assumptions.append(
            "Объём превышает пять очередей по целевым 70 000 продаваемых м²; "
            "скрининг упёрся в штатный предел модели, поэтому средняя очередь крупнее цели."
        )
    exclusions = [
        "Цена приобретения / входа принята равной нулю.",
        "Плата за ВРИ и оформление земельных правоотношений не включены.",
        "Социальные объекты, переселение, специальные внеплощадочные сети и иные обязательства КРТ не включены, пока их нет в исходных документах.",
        "Нежилой и общественно-деловой объём не включён в жилую модель: для него нужно подтвердить продукт и отдельные цены/затраты.",
    ]
    if class_note:
        assumptions.append(class_note + ".")

    return {
        "available": True,
        "preliminary": True,
        "traffic_light": traffic,
        "headline": traffic["label"],
        "text": text,
        "market": {
            "recommended_segment": segment,
            "model_class": model_class,
            "model_class_label": class_label,
            "start_price_rub_sqm": round(start_price),
            "market_price_rub_sqm": round(market_price) if market_price > 0 else None,
            "price_basis": price_basis,
        },
        "phasing": {
            "automatic": True,
            "count": phasing["phase_count"],
            "target_saleable_sqm": TARGET_PHASE_SALEABLE_SQM,
            "gap_months": PHASE_GAP_MONTHS,
            "saleable_sqm": round(saleable),
            "average_saleable_sqm": round(saleable / phasing["phase_count"]),
            "capped_at_five": capped_at_five,
            "phases": phases,
        },
        "absorption": absorption,
        "metrics": {**metrics, "weakest_phase_llcr_x": round(weakest_llcr, 3)},
        "entry_capacity": entry_capacity,
        "assumptions": assumptions,
        "exclusions": exclusions,
        "criterion": (
            "Светофор модели проверяет положительную прибыль и LLCR слабейшей очереди; "
            "целевой ориентир DevelopAid — 1,20x. Это фильтр для углублённой проверки, не решение о покупке."
        ),
    }
