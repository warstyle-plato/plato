"""Investment score v2 for the KRT laboratory.

The lab score has one fixed methodology.  A user may change only the price
target; changing it changes the price component, not the financial model.

The module also contains one auditable live case (Nagatino) assembled from the
committed auction notice + EGRN extracts + the existing DevelopAid engine.
It deliberately does not create a second financial model.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

TARGET_LLCR = 1.20
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


def llcr_points(value: Any) -> float | None:
    """0..40. Below 1.00 the project has no LLCR points."""
    return _piece(value, LLCR_STOPS)


def price_points(market_rub_sqm: Any, target_rub_sqm: Any) -> float | None:
    """0..20 relative to the user's current price target."""
    market = _number(market_rub_sqm)
    target = _number(target_rub_sqm)
    if market is None or target is None or target <= 0:
        return None
    ratio = market / target
    return _piece(ratio, PRICE_RATIO_STOPS)


def absorption_points(local_sqm_month: Any, benchmark_sqm_month: Any) -> float | None:
    """0..20. Both measures are square metres/month, never DDU/month."""
    local = _number(local_sqm_month)
    benchmark = _number(benchmark_sqm_month)
    if local is None or benchmark is None or benchmark <= 0:
        return None
    ratio = local / benchmark
    return _piece(ratio, [(0.50, 0.0), (0.75, 5.0), (1.00, 10.0),
                          (1.25, 15.0), (1.50, 20.0)])


def burden_points(burden_pct: Any) -> float | None:
    """0..20. KRT burden as a share of ordinary project CAPEX."""
    value = _number(burden_pct)
    if value is None:
        return None
    return _piece(value, [(0.0, 20.0), (5.0, 18.0), (10.0, 14.0),
                          (15.0, 9.0), (20.0, 5.0), (25.0, 2.0), (30.0, 0.0)])


def score(
    *,
    status_kind: str,
    llcr: Any,
    market_rub_sqm: Any,
    target_rub_sqm: Any,
    local_sqm_month: Any = None,
    benchmark_sqm_month: Any = None,
    burden_pct: Any = None,
) -> dict[str, Any]:
    """Return fixed 40/20/20/20 score.

    Running KRT stays visible but is never scored.  Missing facts are not
    renormalised: a 0..100 score exists only when all four components exist.
    """
    components = {
        "llcr": {"points": llcr_points(llcr), "max": 40.0},
        "price": {"points": price_points(market_rub_sqm, target_rub_sqm), "max": 20.0},
        "absorption": {
            "points": absorption_points(local_sqm_month, benchmark_sqm_month), "max": 20.0
        },
        "burden": {"points": burden_points(burden_pct), "max": 20.0},
    }
    known = sum(v["max"] for v in components.values() if v["points"] is not None)
    coverage = known
    missing = [k for k, v in components.items() if v["points"] is None]
    rankable = str(status_kind or "") != "running"
    total = None
    reason = ""
    if not rankable:
        reason = "В реализации — балл не присваивается"
    elif missing:
        reason = "Не хватает данных: " + ", ".join(missing)
    else:
        total = round(sum(float(v["points"]) for v in components.values()), 1)
    return {
        "score": total,
        "coverage_pct": round(coverage, 1),
        "rankable": rankable,
        "reason": reason,
        "components": components,
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
                "llcr_points": llcr_points(metrics.get("llcr_x")),
                "purchase_right_mln": 0.0,
                "cadastral_buyout_mln": cadastral_mln,
            },
            "ordinary_capex_mln": None if ordinary_capex is None else round(ordinary_capex, 1),
            "burden_pct": None if burden_pct is None else round(burden_pct, 2),
            "burden_points": burden_points(burden_pct),
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
