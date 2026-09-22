"""KRT investment rating defined by GitHub issue #485.

This module is the single backend source of truth for the preview rating.
There are four independent 0..100 components with equal weight.  The UI must
render the returned breakdown and must not duplicate these formulas in JS.

The live Nagatino case reuses the existing authoritative DevelopAid financial
engine / goal-seek; this module does not implement a second financial model.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

TARGET_LLCR = 1.20
DEFAULT_PRICE_TARGET_RUB_SQM = 600_000.0

LLCR_STOPS = [(1.00, 0.0), (1.10, 25.0), (1.20, 75.0), (1.30, 100.0)]
PRICE_RATIO_STOPS = [(0.70, 0.0), (0.85, 50.0), (1.00, 100.0)]
ABSORPTION_RATIO_STOPS = [
    (0.50, 0.0), (0.70, 25.0), (0.85, 50.0),
    (1.00, 75.0), (1.10, 90.0), (1.20, 100.0),
]
BURDEN_PCT_STOPS = [
    (0.0, 100.0), (5.0, 90.0), (10.0, 70.0),
    (15.0, 45.0), (20.0, 25.0), (30.0, 0.0),
]

ROOT = Path(__file__).resolve().parent.parent
NAGATINO_PRESET = ROOT / "presets" / "КРТ_Нагатино.json"


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _piece(value: Any, stops: list[tuple[float, float]]) -> float | None:
    """Linear interpolation with endpoint clamping."""
    x = _number(value)
    if x is None:
        return None
    if x <= stops[0][0]:
        return float(stops[0][1])
    for (x1, y1), (x2, y2) in zip(stops, stops[1:]):
        if x <= x2:
            part = (x - x1) / (x2 - x1 or 1.0)
            return float(y1 + (y2 - y1) * part)
    return float(stops[-1][1])


def llcr_score(value: Any) -> float | None:
    return _piece(value, LLCR_STOPS)


def price_score(market_rub_sqm: Any, target_rub_sqm: Any) -> float | None:
    market = _number(market_rub_sqm)
    target = _number(target_rub_sqm)
    if market is None or target is None or target <= 0:
        return None
    return _piece(market / target, PRICE_RATIO_STOPS)


def absorption_score(local_sqm_month: Any, benchmark_sqm_month: Any) -> float | None:
    local = _number(local_sqm_month)
    benchmark = _number(benchmark_sqm_month)
    if local is None or benchmark is None or benchmark <= 0:
        return None
    return _piece(local / benchmark, ABSORPTION_RATIO_STOPS)


def burden_score(burden_pct: Any) -> float | None:
    return _piece(burden_pct, BURDEN_PCT_STOPS)


def _component(
    *,
    name: str,
    value: Any,
    benchmark: Any,
    ratio: Any,
    score_value: Any,
    unit: str,
    scale: list[tuple[float, float]],
    formula: str,
    missing_reason: str = "",
    source: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    score_num = _number(score_value)
    result = {
        "name": name,
        "value": _number(value),
        "benchmark": _number(benchmark),
        "ratio": _number(ratio),
        "score": None if score_num is None else round(score_num, 2),
        "unit": unit,
        "scale": [[x, y] for x, y in scale],
        "formula": formula,
        "missing_reason": "" if score_num is not None else (missing_reason or "нет исходных данных"),
        "source": source,
    }
    if extra:
        result.update(extra)
    return result


def methodology() -> dict[str, Any]:
    """Machine-readable methodology from issue #485."""
    return {
        "version": "issue-485-krt-rating-4x100-v1",
        "issue": 485,
        "price_target_default_rub_sqm": DEFAULT_PRICE_TARGET_RUB_SQM,
        "target_llcr_x": TARGET_LLCR,
        "weights": None,
        "components_equal": True,
        "formula": "rating = (llcr_score + price_score + absorption_score + burden_score) / 4",
        "linear_interpolation": "y = y1 + (x-x1)/(x2-x1) * (y2-y1)",
        "llcr_stops": LLCR_STOPS,
        "price_ratio_stops": PRICE_RATIO_STOPS,
        "absorption_ratio_stops": ABSORPTION_RATIO_STOPS,
        "burden_pct_stops": BURDEN_PCT_STOPS,
        "rules": {
            "running": "visible_unscored",
            "missing": "no_total_score_no_renormalisation",
            "coverage_step_pct": 25,
            "buyout": "non_moscow_cadastral_value_land_and_buildings_no_duplicates",
            "moscow_property": "zero_buyout",
            "missing_cadastral_value": "unknown_not_zero",
            "absorption_unit": "sqm_per_month",
            "entry_capacity": "shown_separately_not_in_rating",
            "only_user_scenario_parameter": "price_target_rub_sqm",
        },
        "explanations": {
            "coverage": (
                "Каждый известный блок даёт 25 п.п. coverage. При 25/50/75% "
                "известные оценки показываются, но итоговый рейтинг остаётся «—»: "
                "три известных блока нельзя перенормировать в 100."
            ),
            "running": (
                "Площадка со статусом «В реализации» остаётся в каталоге и фильтрах, "
                "но инвестиционный рейтинг ей не присваивается: «— · В реализации · без балла»."
            ),
            "entry_capacity": (
                "Предельная цена права при LLCR=1.20 — отдельный денежный показатель. "
                "Она показывается рядом с LLCR, но не входит ни в один из четырёх score."
            ),
            "burden": (
                "Нагрузка включает кадастровый выкуп частных ЗУ и ОКС без дублей, "
                "снос, оценённое расселение, обязательные соцобъекты, сети и иные "
                "денежно оценённые обязательства. Собственность Москвы = 0 ₽; "
                "неизвестная кадастровая стоимость остаётся unknown, а не нулём."
            ),
        },
        "examples": {
            "llcr": "LLCR 1.24: 75 + (1.24-1.20)/(1.30-1.20)×(100-75) = 85",
            "price": "570000 / 600000 = 95%; 50 + (0.95-0.85)/(1.00-0.85)×50 = 83.3",
            "absorption": "8300 / 6640 = 125% медианы → 100",
            "burden": "4300 / 43000 = 10% → 70",
        },
    }


def score(
    *,
    status_kind: str,
    llcr: Any,
    market_rub_sqm: Any,
    target_rub_sqm: Any = DEFAULT_PRICE_TARGET_RUB_SQM,
    local_sqm_month: Any = None,
    benchmark_sqm_month: Any = None,
    burden_pct: Any = None,
    burden_mln: Any = None,
    ordinary_capex_mln: Any = None,
    housing_gfa_sqm: Any = None,
    entry_capacity_mln: Any = None,
    sources: dict[str, str] | None = None,
    missing_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Four equal 0..100 components; any missing component makes total null."""
    sources = sources or {}
    missing_reasons = missing_reasons or {}

    llcr_n = _number(llcr)
    market = _number(market_rub_sqm)
    target = _number(target_rub_sqm)
    local = _number(local_sqm_month)
    benchmark = _number(benchmark_sqm_month)
    burden = _number(burden_pct)
    burden_m = _number(burden_mln)
    ordinary = _number(ordinary_capex_mln)
    housing = _number(housing_gfa_sqm)

    llcr_s = llcr_score(llcr_n)
    price_ratio = market / target if market is not None and target and target > 0 else None
    price_s = price_score(market, target)
    abs_ratio = local / benchmark if local is not None and benchmark and benchmark > 0 else None
    abs_s = absorption_score(local, benchmark)
    burden_s = burden_score(burden)
    burden_per_housing = (
        burden_m * 1_000_000.0 / housing
        if burden_m is not None and housing and housing > 0 else None
    )

    components = {
        "llcr": _component(
            name="LLCR", value=llcr_n, benchmark=TARGET_LLCR, ratio=None,
            score_value=llcr_s, unit="x", scale=LLCR_STOPS,
            formula="LLCR authoritative DevelopAid engine, цена права КРТ = 0; линейная интерполяция по шкале",
            missing_reason=missing_reasons.get("llcr", "authoritative LLCR не получен"),
            source=sources.get("llcr", "authoritative DevelopAid engine"),
            extra={"entry_capacity_mln": _number(entry_capacity_mln),
                   "entry_capacity_note": "Предельная цена права при LLCR=1.20; в рейтинг не входит."},
        ),
        "price": _component(
            name="Цена рынка", value=market, benchmark=target, ratio=price_ratio,
            score_value=price_s, unit="₽/м²", scale=PRICE_RATIO_STOPS,
            formula="цена окружения / ценовой ориентир; линейная интерполяция по доле",
            missing_reason=missing_reasons.get("price", "цена окружения не получена"),
            source=sources.get("price", "рыночное окружение"),
        ),
        "absorption": _component(
            name="Поглощение", value=local, benchmark=benchmark, ratio=abs_ratio,
            score_value=abs_s, unit="м²/мес.", scale=ABSORPTION_RATIO_STOPS,
            formula="локальная медиана м²/мес. / медиана Москвы по соответствующему классу",
            missing_reason=missing_reasons.get(
                "absorption", "нет пары локальная медиана и медиана Москвы в м²/мес."),
            source=sources.get("absorption", "рыночный отчёт"),
        ),
        "burden": _component(
            name="Нагрузка КРТ", value=burden_m, benchmark=ordinary,
            ratio=(burden / 100.0 if burden is not None else None),
            score_value=burden_s, unit="млн ₽", scale=BURDEN_PCT_STOPS,
            formula="дополнительная нагрузка КРТ / ordinary CAPEX аналогичного проекта",
            missing_reason=missing_reasons.get(
                "burden", "денежная нагрузка КРТ или ordinary CAPEX не определены полностью"),
            source=sources.get("burden", "ЕГРН + обязательства КРТ + authoritative model"),
            extra={
                "burden_pct": burden,
                "rub_per_housing_sqm": None if burden_per_housing is None else round(burden_per_housing),
            },
        ),
    }

    known = [item for item in components.values() if item["score"] is not None]
    coverage = len(known) * 25
    missing = [key for key, item in components.items() if item["score"] is None]
    rankable = str(status_kind or "").strip().lower() != "running"
    total = None
    reason = ""
    arithmetic = ""
    if not rankable:
        reason = "В реализации · без балла"
    elif missing:
        reason = "Не хватает данных: " + ", ".join(missing)
    else:
        values = [float(components[k]["score"]) for k in ("llcr", "price", "absorption", "burden")]
        total = sum(values) / 4.0
        arithmetic = (
            f"({values[0]:.1f} + {values[1]:.1f} + {values[2]:.1f} + {values[3]:.1f}) "
            f"/ 4 = {total:.1f} → {round(total):.0f}"
        )

    return {
        "score": None if total is None else round(total, 2),
        "display_score": None if total is None else round(total),
        "coverage_pct": coverage,
        "rankable": rankable,
        "reason": reason,
        "missing": missing,
        "components": components,
        "arithmetic": arithmetic,
        "price_target_rub_sqm": target,
        "methodology": methodology(),
    }


def _nagatino_cost_stack() -> dict[str, Any]:
    """Known KRT-specific burden from the real Nagatino source set."""
    from auction_search import nagatino_parcels
    import project_preset

    preset = json.loads(NAGATINO_PRESET.read_text(encoding="utf-8"))
    preview = project_preset.build_preview(preset)
    view = nagatino_parcels.territory()
    buy = nagatino_parcels.buyout(view=view)

    # Methodology decision: every non-Moscow cadastral value is acquisition
    # burden; Moscow-owned property is zero.  Missing value remains unknown.
    rows = list(view.get("lands") or []) + list(view.get("objects") or [])
    non_city = [
        row for row in rows
        if str(((row.get("owner") or {}).get("group") or "")) != "moscow"
    ]
    unknown_value = [
        str(row.get("cadastral_number") or "")
        for row in non_city if _number(row.get("cadastral_value_rub")) is None
    ]
    cadastral_rub = (
        float((buy.get("others") or {}).get("land_value_rub") or 0.0)
        + float((buy.get("others") or {}).get("objects_value_rub") or 0.0)
    )
    city_excluded_rub = (
        float((buy.get("city") or {}).get("land_value_rub") or 0.0)
        + float((buy.get("city") or {}).get("objects_value_rub") or 0.0)
    )

    inputs = preview.get("inputs") or {}
    school_places = float(inputs.get("school_places") or 0.0)
    kindergarten_places = float(inputs.get("kindergarten_places") or 0.0)
    clinic_units = float(inputs.get("clinic_capacity") or 0.0)
    social_mln = (
        school_places * float(inputs.get("school_cost_mln_per_place") or 0.0)
        + kindergarten_places * float(inputs.get("kindergarten_cost_mln_per_place") or 0.0)
        + clinic_units * float(inputs.get("clinic_cost_mln_per_unit") or 0.0)
    )
    demolition = preset.get("demolition") or {}
    demolition_mln = float(
        demolition.get("cost_high_mln")
        or demolition.get("cost_mln")
        or inputs.get("social_compensation_mln")
        or 0.0
    )
    resettlement_mln = float((preset.get("resettlement") or {}).get("cost_mln") or 0.0)
    cadastral_mln = cadastral_rub / 1_000_000.0
    total_known_mln = cadastral_mln + demolition_mln + social_mln + resettlement_mln

    housing_gfa = 0.0
    for item in (preset.get("planning") or {}).get("objects") or []:
        if str(item.get("id") or "") == "RES":
            housing_gfa = float(item.get("gfa_m2") or 0.0)
            break
    per_housing = total_known_mln * 1_000_000.0 / housing_gfa if housing_gfa else None

    return {
        "preset": preset,
        "preview": preview,
        "territory": view,
        "cadastral_buyout_mln": round(cadastral_mln, 3),
        "cadastral_complete": not unknown_value,
        "cadastral_unknown_count": len(unknown_value),
        "cadastral_unknown_numbers": unknown_value[:30],
        "moscow_cadastral_excluded_mln": round(city_excluded_rub / 1_000_000.0, 3),
        "demolition_mln": round(demolition_mln, 3),
        "social_mln": round(social_mln, 3),
        "resettlement_mln": round(resettlement_mln, 3),
        "total_known_mln": round(total_known_mln, 3),
        "housing_gfa_sqm": round(housing_gfa, 1),
        "rub_per_housing_sqm": None if per_housing is None else round(per_housing),
        "buyout": buy,
    }


def _merge_model(core: Any, preview: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(copy.deepcopy(preview.get("inputs") or {}))
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, row in (preview.get("tep") or {}).items():
        tep.setdefault(key, {}).update(copy.deepcopy(row))
    return inputs, tep, copy.deepcopy(preview.get("phasing") or {})


def _ordinary_capex(core: Any, inputs: dict[str, Any], tep: dict[str, Any],
                    phasing: dict[str, Any]) -> float | None:
    """Same product programme with KRT-specific burden removed.

    This is the denominator for the lab burden share.  It is intentionally a
    model scenario, not a hand-built cost rate.
    """
    from auction_search.krt_screening import _snapshot

    base_inputs = copy.deepcopy(inputs)
    base_tep = copy.deepcopy(tep)
    base_phasing = copy.deepcopy(phasing)
    base_inputs["purchase_price_mln"] = 0.0
    base_inputs["social_compensation_mln"] = 0.0
    for key in ("school_places", "kindergarten_places", "clinic_capacity",
                "social_school_gba_sqm", "social_dou_gba_sqm", "social_clinic_gba_sqm"):
        if key in base_inputs:
            base_inputs[key] = 0.0
    for key in ("school", "kindergarten", "clinic", "other_mandatory"):
        row = base_tep.get(key)
        if isinstance(row, dict):
            for field, value in list(row.items()):
                if isinstance(value, (int, float)):
                    row[field] = 0.0
    if isinstance(base_phasing, dict):
        base_phasing["social_objects"] = []
        for phase in base_phasing.get("phases") or []:
            products = phase.get("products") if isinstance(phase, dict) else None
            if isinstance(products, dict):
                for key in ("school", "kindergarten", "clinic", "other_mandatory"):
                    products.pop(key, None)
    bundle = core._run_authoritative_model(base_inputs, base_tep, [], base_phasing)
    value = _number(_snapshot(core, bundle["consolidated"]).get("capex_mln"))
    return value


def nagatino_live_example(core: Any) -> dict[str, Any]:
    """Real-data test case: cadastral buyout -> LLCR -> max KRT-right price."""
    from auction_search.krt_screening import (
        _goal_seek_entry_capacity,
        _snapshot,
        model_at_asking_price,
    )

    stack = _nagatino_cost_stack()
    preset = stack.pop("preset")
    preview = stack.pop("preview")
    stack.pop("territory", None)
    inputs, tep, phasing = _merge_model(core, preview)

    # The KRT right itself is zero in the baseline.  Cadastral buyout is a real
    # acquisition outflow and therefore occupies purchase-price capacity.
    cadastral_mln = float(stack["cadastral_buyout_mln"])
    inputs["purchase_price_mln"] = cadastral_mln

    result: dict[str, Any] = {
        "name": "КРТ Нагатино",
        "source": "59 выписок ЕГРН + извещение торгов + пресет DevelopAid",
        "cost_stack": stack,
        "method_note": (
            "Кадастровый выкуп проведён как часть acquisition cash-out. "
            "Цена самого права КРТ в базовом LLCR равна нулю."
        ),
    }
    try:
        bundle = core._run_authoritative_model(inputs, tep, [], phasing)
        metrics = _snapshot(core, bundle["consolidated"])
        capacity = _goal_seek_entry_capacity(core, inputs, tep, phasing, bundle)
        total_capacity = (
            _number((capacity or {}).get("amount_mln"))
            if isinstance(capacity, dict) and capacity.get("available") else None
        )
        right_capacity = None if total_capacity is None else total_capacity - cadastral_mln

        start_rub = _number((preset.get("transaction") or {}).get("start_price_rub"))
        if start_rub is None:
            start_rub = _number((preset.get("transaction") or {}).get("acquisition_price_rub"))
        start_mln = None if start_rub is None else start_rub / 1_000_000.0
        at_start = None
        if start_mln is not None:
            at_start = model_at_asking_price(
                core, inputs, tep, phasing, cadastral_mln + start_mln
            )
        ordinary_capex = _ordinary_capex(core, inputs, tep, phasing)
        burden_pct = (
            100.0 * float(stack["total_known_mln"]) / ordinary_capex
            if ordinary_capex and ordinary_capex > 0 else None
        )
        result.update({
            "available": True,
            "baseline": {
                "project_llcr_x": _number(metrics.get("llcr_x")),
                "llcr_score": llcr_score(metrics.get("llcr_x")),
                "purchase_right_mln": 0.0,
                "cadastral_buyout_mln": cadastral_mln,
            },
            "ordinary_capex_mln": None if ordinary_capex is None else round(ordinary_capex, 1),
            "burden_pct": None if burden_pct is None else round(burden_pct, 2),
            "burden_score": burden_score(burden_pct),
            "entry_capacity": {
                "total_acquisition_capacity_mln": None if total_capacity is None else round(total_capacity, 1),
                "max_krt_right_price_mln": None if right_capacity is None else round(max(0.0, right_capacity), 1),
                "reserve_after_cadastral_mln": None if right_capacity is None else round(right_capacity, 1),
                "target_llcr_x": TARGET_LLCR,
            },
            "auction": {
                "start_price_mln": None if start_mln is None else round(start_mln, 1),
                "llcr_at_start_x": None if not at_start else at_start.get("project_llcr_x"),
                "passes_1_20": None if not at_start else at_start.get("passes"),
                "reserve_to_limit_mln": (
                    None if start_mln is None or right_capacity is None
                    else round(right_capacity - start_mln, 1)
                ),
            },
        })
    except Exception as exc:  # noqa: BLE001
        result.update({
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
        })
    return result
