"""Physical driver for the single CAPEX article «Благоустройство».

The financial model historically stores landscaping as a rate per core GNS.
That contract remains the fallback so old projects are unchanged.  When a
physical landscaping area and a rate per square metre of that territory are
both known, the physical quantity becomes authoritative; the result is still
normalised back to core GNS for legacy Excel templates and comparability.

«Озеленение» is deliberately not a separate CAPEX article here.  It is a
component/metadata field inside the same landscaping article.
"""

from __future__ import annotations

from typing import Any


_CORE_GNS_KEYS = ("apartments", "ground_commercial", "underground_parking", "storage")


def _number(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number and abs(number) != float("inf") else 0.0


def core_gns_sqm(tep: dict[str, dict[str, Any]] | None) -> float:
    """The exact denominator used by the legacy landscaping formula."""
    rows = tep or {}
    return sum(max(0.0, _number((rows.get(key) or {}).get("gns"))) for key in _CORE_GNS_KEYS)


def project_gns_sqm(tep: dict[str, dict[str, Any]] | None) -> float:
    """All project GNS, used only to allocate a site-level quantity by phases."""
    return sum(max(0.0, _number((row or {}).get("gns"))) for row in (tep or {}).values())


def basis(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the physical landscaping area without inventing geometry.

    Priority:
    1. explicit/source landscaping_area_sqm;
    2. site area minus an explicitly known above-ground building footprint;
    3. unresolved.

    A greening requirement never becomes the whole landscaping area by itself:
    greening is only one component of landscaping.
    """
    x = inputs or {}
    site_area_sqm = max(0.0, _number(x.get("site_area_ha")) * 10000.0)
    footprint_sqm = max(0.0, _number(x.get("building_footprint_sqm")))
    explicit_area_sqm = max(0.0, _number(x.get("landscaping_area_sqm")))
    green_area_sqm = max(0.0, _number(x.get("landscaping_green_area_sqm")))
    warnings: list[str] = []

    if explicit_area_sqm > 0:
        area_sqm = explicit_area_sqm
        source = "explicit"
        if site_area_sqm > 0 and area_sqm > site_area_sqm + 1e-6:
            warnings.append(
                "Площадь благоустройства больше площади участка; проверьте, "
                "включено ли внешнее благоустройство за границами участка."
            )
    elif site_area_sqm > 0 and footprint_sqm > 0:
        if footprint_sqm >= site_area_sqm:
            area_sqm = 0.0
            source = "unresolved"
            warnings.append(
                "Пятно наземной застройки не меньше площади участка; "
                "площадь благоустройства автоматически не определена."
            )
        else:
            area_sqm = site_area_sqm - footprint_sqm
            source = "site_minus_footprint"
    else:
        area_sqm = 0.0
        source = "unresolved"

    if green_area_sqm > 0 and area_sqm > 0 and green_area_sqm > area_sqm + 1e-6:
        warnings.append(
            "Площадь озеленения больше площади благоустройства; "
            "проверьте периметр нормативного показателя."
        )

    green_share_pct = (green_area_sqm / area_sqm * 100.0) if area_sqm > 0 else None
    return {
        "site_area_sqm": site_area_sqm,
        "building_footprint_sqm": footprint_sqm,
        "landscaping_area_sqm": area_sqm,
        "green_area_sqm": green_area_sqm,
        "green_share_pct": green_share_pct,
        "basis_source": source,
        "warnings": warnings,
    }


def calculate(inputs: dict[str, Any] | None, core_gns: float) -> dict[str, Any]:
    """Calculate the one landscaping CAPEX article with a strict legacy fallback."""
    x = inputs or {}
    resolved = basis(x)
    core = max(0.0, _number(core_gns))
    legacy_rate = max(0.0, _number(x.get("landscaping_th_per_sqm")))
    physical_rate = max(0.0, _number(x.get("landscaping_site_th_per_sqm")))
    area = float(resolved["landscaping_area_sqm"] or 0.0)
    warnings = list(resolved["warnings"])

    if physical_rate > 0 and area > 0:
        mode = "physical"
        amount_rub = area * physical_rate * 1000.0
    else:
        mode = "legacy_gns"
        amount_rub = core * legacy_rate * 1000.0
        if physical_rate > 0 and area <= 0:
            warnings.append(
                "Задана ставка благоустройства на территорию, но физическая "
                "площадь не определена; сохранён расчёт по ГНС."
            )
        elif area > 0 and physical_rate <= 0:
            warnings.append(
                "Физическая площадь благоустройства определена, но ставка на "
                "территорию не задана; сохранён расчёт по ГНС."
            )

    equivalent = amount_rub / core / 1000.0 if core > 0 else None
    return {
        **resolved,
        "mode": mode,
        "amount_rub": amount_rub,
        "legacy_rate_th_per_gns_sqm": legacy_rate,
        "physical_rate_th_per_site_sqm": physical_rate,
        "equivalent_gns_th_per_sqm": equivalent,
        "warnings": warnings,
    }


def materialize_area(inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Copy inputs and materialise a derived landscaping area for exports."""
    out = dict(inputs or {})
    resolved = basis(out)
    if _number(out.get("landscaping_area_sqm")) <= 0 and resolved["landscaping_area_sqm"] > 0:
        out["landscaping_area_sqm"] = resolved["landscaping_area_sqm"]
    return out


def legacy_template_inputs(
    inputs: dict[str, Any] | None,
    tep: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt physical costing to an old workbook that only knows RUB/core-GNS."""
    out = materialize_area(inputs)
    calc = calculate(out, core_gns_sqm(tep))
    equivalent = calc.get("equivalent_gns_th_per_sqm")
    if calc["mode"] == "physical" and equivalent is not None:
        out["landscaping_th_per_sqm"] = equivalent
    return out, calc
