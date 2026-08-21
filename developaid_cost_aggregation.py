from __future__ import annotations

from datetime import date, datetime
from typing import Any

from developaid_cost_structure import UNIT_LABELS, build_cost_structure_matrix

# A recommendation is only allowed when the source can be translated to the
# exact input basis used by DevelopAid.  Different area denominators remain
# visible in the source matrix, but do not get averaged just because both say
# "руб./м²".
COMPONENT_UNITS: dict[str, str] = {
    "preparation": "gba",
    "design": "gba",
    "main_above": "gba",
    "main_under": "underground",
    "external_utilities": "gba",
    "landscaping": "gba",
    "technical_connection": "gba",
    "commissioning": "gba",
    "site_maintenance": "gba",
    "tech_customer": "gba",
    "project_management": "gba",
    "reserve": "gba",
    "construction_capex": "gba",
}

APPLYABLE_COMPONENTS = {
    "preparation",
    "design",
    "main_above",
    "main_under",
    "external_utilities",
    "landscaping",
    "technical_connection",
    "commissioning",
    "site_maintenance",
    "tech_customer",
    "project_management",
    "reserve",
}

GRADE_WEIGHTS = {"A": 1.0, "B": 0.80, "C": 0.50, "D": 0.0}
SOURCE_WEIGHTS = {
    "internal_project": 1.00,
    "official_normative": 0.95,
    "industry_benchmark": 0.80,
    "industry_case": 0.65,
}
COMPARABILITY_WEIGHTS = {
    "exact_da": 1.00,
    "direct": 0.95,
    "contextual": 0.70,
    "partial": 0.50,
}

GRADE_LABELS = {
    "A": "прямое совпадение",
    "B": "нормализовано",
    "C": "оценочная декомпозиция",
    "D": "только справочно",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _freshness_weight(reference_date: str | None, as_of: date) -> float:
    observed = _parse_date(reference_date)
    if observed is None:
        return 0.45
    months = max(0.0, (as_of - observed).days / 30.4375)
    if months <= 12:
        return 1.00
    if months <= 24:
        return 0.85
    if months <= 36:
        return 0.65
    return 0.40


def _weighted_quantile(points: list[dict[str, Any]], q: float) -> float | None:
    positive = [p for p in points if p.get("weight", 0) > 0 and p.get("value_rub_m2") is not None]
    if not positive:
        return None
    ordered = sorted(positive, key=lambda p: float(p["value_rub_m2"]))
    total = sum(float(p["weight"]) for p in ordered)
    target = total * q
    running = 0.0
    for point in ordered:
        running += float(point["weight"])
        if running >= target:
            return float(point["value_rub_m2"])
    return float(ordered[-1]["value_rub_m2"])


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _candidate_from_cell(
    source: dict[str, Any],
    component_key: str,
    cell: dict[str, Any],
    *,
    as_of: date,
) -> dict[str, Any]:
    expected_unit = COMPONENT_UNITS.get(component_key)
    status = cell.get("status", "not_disclosed")
    source_name = source.get("source")
    source_id = source.get("source_id")
    source_kind = source.get("source_kind")
    published = source.get("published", {})
    actual_unit = cell.get("unit")
    value: float | None = None
    grade = "D"
    reason = "Источник не раскрывает сопоставимое значение этой статьи."
    normalization = "не участвует"

    # A direct article on the exact DevelopAid denominator is the strongest
    # evidence.  A class adjustment is intentionally downgraded to B: it is a
    # transparent normalization layer, not an observed value for target class.
    if status == "value" and actual_unit == expected_unit:
        value = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
        grade = "B" if cell.get("class_adjusted") else "A"
        normalization = "класс" if cell.get("class_adjusted") else "не требуется"
        reason = "Статья и база площади совпадают с параметром DevelopAid."
    elif status == "separate_denominator" and actual_unit == expected_unit:
        value = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
        grade = "B" if cell.get("class_adjusted") else "A"
        normalization = "класс" if cell.get("class_adjusted") else "не требуется"
        reason = "Отдельная база площади является штатной базой этой статьи DevelopAid."
    elif status == "source_aggregate" and component_key == "construction_capex" and actual_unit == expected_unit:
        # Only a total explicitly stated on GBA may become the DA construction
        # total.  Building/apartment/sellable denominators stay references.
        value = cell.get("adjusted_value_rub_m2", cell.get("value_rub_m2"))
        grade = "B" if cell.get("class_adjusted") else "A"
        normalization = "класс" if cell.get("class_adjusted") else "не требуется"
        reason = "Итог источника совпадает по scope и базе с Construction CAPEX DevelopAid."
    elif status == "share" and published.get("unit") == expected_unit:
        parent = source.get("published_adjusted_value_rub_m2")
        share = cell.get("share_pct")
        if parent is not None and share is not None:
            value = float(parent) * float(share) / 100.0
            grade = "C"
            normalization = "декомпозиция доли"
            reason = "Абсолютное значение оценено из раскрытой доли источника; это не прямое наблюдение."
    elif actual_unit and expected_unit and actual_unit != expected_unit:
        reason = (
            f"Знаменатель {UNIT_LABELS.get(actual_unit, actual_unit)} не совпадает с "
            f"{UNIT_LABELS.get(expected_unit, expected_unit)}; без исходных площадей конвертация запрещена."
        )
    elif status == "combined_share":
        reason = "Источник раскрывает совместную долю группы статей; искусственно делить её между статьями нельзя."
    elif status in {"included_in_aggregate", "included_in_broader_total", "included_residual", "unallocated_remainder"}:
        reason = "Статья входит в более широкий итог, но отдельно не раскрыта; значение не выдумывается."
    elif status == "outside_scope":
        reason = "Статья находится вне scope опубликованного показателя."

    freshness = _freshness_weight(source.get("reference_date"), as_of)
    source_weight = SOURCE_WEIGHTS.get(source_kind, 0.65)
    comparability = COMPARABILITY_WEIGHTS.get(source.get("comparability"), 0.60)
    weight = GRADE_WEIGHTS[grade] * freshness * source_weight * comparability

    return {
        "source_id": source_id,
        "source": source_name,
        "source_kind": source_kind,
        "reference_date": source.get("reference_date"),
        "source_url": source.get("source_url"),
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "value_rub_m2": _round_money(value),
        "unit": expected_unit,
        "unit_label": UNIT_LABELS.get(expected_unit, expected_unit),
        "weight": round(weight, 4),
        "freshness_weight": round(freshness, 4),
        "source_weight": round(source_weight, 4),
        "comparability_weight": round(comparability, 4),
        "normalization": normalization,
        "reason": reason,
        "included": grade != "D" and value is not None and weight > 0,
    }


def _confidence(included: list[dict[str, Any]]) -> str:
    if not included:
        return "insufficient"
    grades = [p["grade"] for p in included]
    if len(included) >= 5 and grades.count("A") >= 2:
        return "high"
    if len(included) >= 3 and all(g in {"A", "B"} for g in grades):
        return "medium"
    if len(included) >= 2:
        return "limited"
    return "pilot"


def build_cost_recommendation(
    region: str = "Москва",
    housing_class: str = "business",
    *,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Normalize every source to DevelopAid article bases and aggregate.

    The function is deliberately conservative.  A source can be shown in the
    matrix while being excluded from a particular article recommendation.  The
    output therefore explains both the included evidence and the exclusions.
    """

    effective_date = as_of or date.today()
    matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
    recommendations: list[dict[str, Any]] = []

    for component in matrix.get("components", []):
        key = component.get("key")
        expected_unit = COMPONENT_UNITS.get(key)
        if expected_unit is None:
            continue

        candidates = [
            _candidate_from_cell(source, key, source.get("cells", {}).get(key, {}), as_of=effective_date)
            for source in matrix.get("sources", [])
        ]
        included = [c for c in candidates if c["included"]]
        excluded = [c for c in candidates if not c["included"]]
        recommended = _weighted_quantile(included, 0.50)
        p25 = _weighted_quantile(included, 0.25)
        p75 = _weighted_quantile(included, 0.75)

        # The internal project source is an anchor, not a privileged answer: it
        # is displayed separately and still participates with its normal weight.
        baseline = next(
            (
                c["value_rub_m2"]
                for c in included
                if c.get("source_kind") == "internal_project" and c.get("value_rub_m2") is not None
            ),
            None,
        )
        delta_pct = None
        if baseline not in (None, 0) and recommended is not None:
            delta_pct = (float(recommended) / float(baseline) - 1.0) * 100.0

        recommendations.append(
            {
                "key": key,
                "label": component.get("label"),
                "unit": expected_unit,
                "unit_label": UNIT_LABELS.get(expected_unit, expected_unit),
                "recommended_rub_m2": _round_money(recommended),
                "p25_rub_m2": _round_money(p25),
                "p75_rub_m2": _round_money(p75),
                "baseline_rub_m2": _round_money(baseline),
                "delta_to_baseline_pct": None if delta_pct is None else round(delta_pct, 1),
                "source_count": len(included),
                "confidence": _confidence(included),
                "grade_counts": {g: sum(1 for c in included if c["grade"] == g) for g in ("A", "B", "C")},
                "included_sources": included,
                "excluded_sources": excluded,
                "applyable": key in APPLYABLE_COMPONENTS and recommended is not None,
            }
        )

    applyable = [r for r in recommendations if r["applyable"]]
    return {
        "methodology_version": "3.1",
        "region": region,
        "housing_class": matrix.get("housing_class", housing_class),
        "housing_class_label": matrix.get("housing_class_label", housing_class),
        "as_of": effective_date.isoformat(),
        "recommendations": recommendations,
        "applyable_recommendations": applyable,
        "applyable_count": len(applyable),
        "rules": [
            "Агрегация идёт по каждой статье отдельно, а не по опубликованным итогам разных scope.",
            "Вес = качество нормализации × свежесть × тип источника × методологическая сопоставимость.",
            "A — прямое совпадение; B — прозрачная нормализация; C — оценочная декомпозиция; D — только справочно.",
            "Разные знаменатели площади не конвертируются без исходных площадей; D не участвует в рекомендации.",
            "Рекомендация — взвешенная медиана; P25–P75 считаются по тем же весам.",
        ],
    }
