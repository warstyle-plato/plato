from __future__ import annotations

from datetime import date, datetime
from typing import Any

from developaid_cost_structure import UNIT_LABELS, build_cost_structure_matrix

# The recommendation layer targets the exact denominators used by the model.
# Common project articles are per total GNS, while above-ground and underground
# construction have their own GNS denominators.
COMPONENT_UNITS: dict[str, str] = {
    "preparation": "gba",
    "design": "gba",
    "main_above": "above_ground",
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

MODEL_KEYS: dict[str, str] = {
    "preparation": "preparation_th_per_sqm",
    "main_above": "main_above_th_per_sqm",
    "main_under": "main_under_th_per_sqm",
    "external_utilities": "utilities_th_per_sqm",
    "landscaping": "landscaping_th_per_sqm",
    "commissioning": "commissioning_th_per_sqm",
    "site_maintenance": "site_maintenance_th_per_sqm",
}

UNIT_AREA_KEYS: dict[str, str] = {
    "gba": "gba_sqm",
    "above_ground": "above_ground_gns_sqm",
    "underground": "underground_gns_sqm",
    "sellable": "sellable_sqm",
    "apartments": "apartments_sqm",
    "building_total": "building_total_sqm",
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
CLASS_RANK = {"standard": 0, "comfort": 1, "business": 2, "premium": 3, "elite": 4}

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


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_target_areas(target_areas: dict[str, Any] | None) -> dict[str, float]:
    raw = target_areas or {}
    clean: dict[str, float] = {}
    for key in UNIT_AREA_KEYS.values():
        value = _positive(raw.get(key))
        if value is not None:
            clean[key] = value
    if "above_ground_gns_sqm" not in clean and "gba_sqm" in clean and "underground_gns_sqm" in clean:
        above = clean["gba_sqm"] - clean["underground_gns_sqm"]
        if above > 0:
            clean["above_ground_gns_sqm"] = above
    return clean


def _convert_rate(
    value: float | None,
    actual_unit: str | None,
    expected_unit: str | None,
    target_areas: dict[str, float],
) -> tuple[float | None, float | None]:
    if value is None or actual_unit is None or expected_unit is None:
        return None, None
    if actual_unit == expected_unit:
        return float(value), 1.0
    actual_area_key = UNIT_AREA_KEYS.get(actual_unit)
    expected_area_key = UNIT_AREA_KEYS.get(expected_unit)
    actual_area = target_areas.get(actual_area_key or "")
    expected_area = target_areas.get(expected_area_key or "")
    if actual_area in (None, 0) or expected_area in (None, 0):
        return None, None
    factor = float(actual_area) / float(expected_area)
    return float(value) * factor, factor


def _weighted_mean(points: list[dict[str, Any]], value_key: str = "value_rub_m2") -> float | None:
    valid = [p for p in points if p.get("weight", 0) > 0 and p.get(value_key) is not None]
    if not valid:
        return None
    weight = sum(float(p["weight"]) for p in valid)
    if weight <= 0:
        return None
    return sum(float(p[value_key]) * float(p["weight"]) for p in valid) / weight


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


def _cell_value(cell: dict[str, Any], key: str = "value_rub_m2") -> float | None:
    adjusted_key = f"adjusted_{key}"
    value = cell.get(adjusted_key, cell.get(key))
    return None if value is None else float(value)


def _candidate_from_cell(
    source: dict[str, Any],
    component_key: str,
    cell: dict[str, Any],
    *,
    as_of: date,
    target_areas: dict[str, float] | None = None,
) -> dict[str, Any]:
    areas = _normalize_target_areas(target_areas)
    expected_unit = COMPONENT_UNITS.get(component_key)
    status = cell.get("status", "not_disclosed")
    source_name = source.get("source")
    source_id = source.get("source_id")
    source_kind = source.get("source_kind")
    published = source.get("published", {})
    actual_unit = cell.get("unit")
    value: float | None = None
    low_value: float | None = None
    high_value: float | None = None
    grade = "D"
    reason = "Источник не раскрывает сопоставимое значение этой статьи."
    normalization_steps: list[str] = []
    conversion_factor: float | None = None

    raw_value = _cell_value(cell)
    raw_low = _cell_value(cell, "value_low_rub_m2")
    raw_high = _cell_value(cell, "value_high_rub_m2")
    class_adjusted = bool(cell.get("class_adjusted"))
    if class_adjusted:
        normalization_steps.append(f"класс ×{cell.get('class_adjustment_ratio', 1):.2f}")

    direct_status = status in {"value", "separate_denominator"}
    if direct_status and raw_value is not None:
        if raw_value <= 0:
            reason = "Нулевое/отрицательное значение конкретного проекта не является рыночным benchmark."
        else:
            converted, factor = _convert_rate(raw_value, actual_unit, expected_unit, areas)
            if converted is not None:
                value = converted
                conversion_factor = factor
                low_value = _convert_rate(raw_low, actual_unit, expected_unit, areas)[0] if raw_low is not None else value
                high_value = _convert_rate(raw_high, actual_unit, expected_unit, areas)[0] if raw_high is not None else value
                if factor != 1.0:
                    grade = "B"
                    normalization_steps.append(
                        f"база площади {UNIT_LABELS.get(actual_unit, actual_unit)} → {UNIT_LABELS.get(expected_unit, expected_unit)}"
                    )
                    reason = "Статья совпадает; знаменатель механически приведён по ТЭП целевого проекта."
                else:
                    grade = "B" if class_adjusted else "A"
                    reason = "Статья и база площади совпадают с параметром DevelopAid."
            elif actual_unit and expected_unit and actual_unit != expected_unit:
                reason = (
                    f"Для перевода {UNIT_LABELS.get(actual_unit, actual_unit)} → "
                    f"{UNIT_LABELS.get(expected_unit, expected_unit)} нужны площади целевого проекта."
                )

    elif status == "source_aggregate" and component_key == "construction_capex":
        scope = cell.get("scope") or published.get("scope")
        if scope != "construction_capex":
            reason = f"Итог источника имеет scope «{scope or 'не указан'}», а не Construction CAPEX DevelopAid."
        elif raw_value is not None and raw_value > 0:
            converted, factor = _convert_rate(raw_value, actual_unit, expected_unit, areas)
            if converted is not None:
                value = converted
                conversion_factor = factor
                low_value = _convert_rate(raw_low, actual_unit, expected_unit, areas)[0] if raw_low is not None else value
                high_value = _convert_rate(raw_high, actual_unit, expected_unit, areas)[0] if raw_high is not None else value
                grade = "B" if class_adjusted or factor != 1.0 else "A"
                if factor != 1.0:
                    normalization_steps.append("база площади по ТЭП")
                reason = "Итог совпадает по scope с Construction CAPEX DevelopAid."

    elif status == "share":
        parent = source.get("published_adjusted_value_rub_m2")
        share = cell.get("share_pct")
        parent_unit = published.get("unit")
        if parent is not None and share is not None:
            decomposed = float(parent) * float(share) / 100.0
            converted, factor = _convert_rate(decomposed, parent_unit, expected_unit, areas)
            if converted is not None and converted > 0:
                value = converted
                low_value = value
                high_value = value
                conversion_factor = factor
                grade = "C"
                normalization_steps.append("декомпозиция раскрытой доли")
                if factor != 1.0:
                    normalization_steps.append("база площади по ТЭП")
                reason = "Абсолютная статья оценена из раскрытой доли источника; это не прямое наблюдение."
            else:
                reason = "Доля раскрыта, но для перевода родительского знаменателя нужны ТЭП целевого проекта."

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
        "source_group": source.get("source_group") or source_id,
        "source": source_name,
        "source_kind": source_kind,
        "base_class": source.get("base_class"),
        "target_class": source.get("target_class"),
        "reference_date": source.get("reference_date"),
        "price_basis_date": source.get("price_basis_date") or source.get("reference_date"),
        "vat_included": source.get("vat_included"),
        "source_url": source.get("source_url"),
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "source_unit": actual_unit,
        "source_unit_label": UNIT_LABELS.get(actual_unit, actual_unit),
        "value_rub_m2": _round_money(value),
        "low_rub_m2": _round_money(low_value),
        "high_rub_m2": _round_money(high_value),
        "unit": expected_unit,
        "unit_label": UNIT_LABELS.get(expected_unit, expected_unit),
        "conversion_factor": None if conversion_factor is None else round(conversion_factor, 6),
        "weight": round(weight, 4),
        "freshness_weight": round(freshness, 4),
        "source_weight": round(source_weight, 4),
        "comparability_weight": round(comparability, 4),
        "normalization": " + ".join(normalization_steps) if normalization_steps else "не требуется",
        "reason": reason,
        "included": grade != "D" and value is not None and value > 0 and weight > 0,
    }


def _class_distance(source_class: str | None, target_class: str | None) -> int:
    if source_class not in CLASS_RANK or target_class not in CLASS_RANK:
        return 99
    return abs(CLASS_RANK[source_class] - CLASS_RANK[target_class])


def _dedupe_correlated_sources(candidates: list[dict[str, Any]], target_class: str) -> list[dict[str, Any]]:
    """Keep one observation per study/source_group for a given article.

    CORE.XP, for example, publishes comfort/business/premium cuts from one study.
    They are three class slices, not three independent market observations.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        if not candidate.get("included"):
            continue
        grouped.setdefault(candidate.get("source_group") or candidate.get("source_id"), []).append(candidate)

    for group, rows in grouped.items():
        if len(rows) <= 1:
            continue
        rows.sort(
            key=lambda row: (
                0 if row.get("base_class") == target_class else 1,
                _class_distance(row.get("base_class"), target_class),
                -float(row.get("weight", 0)),
            )
        )
        keep = rows[0]
        for row in rows[1:]:
            row["included"] = False
            row["weight"] = 0.0
            row["reason"] = (
                f"Не участвует повторно: та же выборка «{group}». Для класса {target_class} выбран "
                f"ближайший срез «{keep.get('source')}»."
            )
    return candidates


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
    target_areas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize source articles to DevelopAid model bases and aggregate them.

    A source may be visible in the audit matrix yet excluded from a particular
    recommendation.  Area-basis conversion is allowed only when target project
    TEPs provide both denominators; hidden scope decomposition is forbidden.
    """

    effective_date = as_of or date.today()
    areas = _normalize_target_areas(target_areas)
    matrix = build_cost_structure_matrix(region=region, housing_class=housing_class)
    target_class = matrix.get("housing_class", housing_class)
    recommendations: list[dict[str, Any]] = []

    for component in matrix.get("components", []):
        key = component.get("key")
        expected_unit = COMPONENT_UNITS.get(key)
        if expected_unit is None:
            continue

        candidates = [
            _candidate_from_cell(
                source,
                key,
                source.get("cells", {}).get(key, {}),
                as_of=effective_date,
                target_areas=areas,
            )
            for source in matrix.get("sources", [])
        ]
        _dedupe_correlated_sources(candidates, target_class)
        included = [c for c in candidates if c["included"]]
        excluded = [c for c in candidates if not c["included"]]

        recommended = _weighted_mean(included)
        range_low = _weighted_mean(included, "low_rub_m2")
        range_high = _weighted_mean(included, "high_rub_m2")
        p25 = _weighted_quantile(included, 0.25)
        p75 = _weighted_quantile(included, 0.75)

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

        model_key = MODEL_KEYS.get(key)
        recommendations.append(
            {
                "key": key,
                "model_key": model_key,
                "label": component.get("label"),
                "unit": expected_unit,
                "unit_label": UNIT_LABELS.get(expected_unit, expected_unit),
                "recommended_rub_m2": _round_money(recommended),
                "range_low_rub_m2": _round_money(range_low),
                "range_high_rub_m2": _round_money(range_high),
                "p25_rub_m2": _round_money(p25),
                "p75_rub_m2": _round_money(p75),
                "baseline_rub_m2": _round_money(baseline),
                "delta_to_baseline_pct": None if delta_pct is None else round(delta_pct, 1),
                "source_count": len(included),
                "confidence": _confidence(included),
                "grade_counts": {g: sum(1 for c in included if c["grade"] == g) for g in ("A", "B", "C")},
                "included_sources": included,
                "excluded_sources": excluded,
                "applyable": model_key is not None and recommended is not None,
            }
        )

    applyable = [r for r in recommendations if r["applyable"]]
    model_parameters = {
        r["model_key"]: round(float(r["recommended_rub_m2"]) / 1000.0, 3)
        for r in applyable
        if r.get("model_key") and r.get("recommended_rub_m2") is not None
    }
    missing_area_inputs = [
        key for key in ("gba_sqm", "sellable_sqm", "above_ground_gns_sqm", "underground_gns_sqm") if key not in areas
    ]

    return {
        "methodology_version": "3.2",
        "region": region,
        "housing_class": target_class,
        "housing_class_label": matrix.get("housing_class_label", housing_class),
        "as_of": effective_date.isoformat(),
        "target_areas": areas,
        "missing_area_inputs": missing_area_inputs,
        "recommendations": recommendations,
        "applyable_recommendations": applyable,
        "applyable_count": len(applyable),
        "model_parameters_th_rub_m2": model_parameters,
        "rules": [
            "Агрегация идёт по каждой статье отдельно, а не по опубликованным итогам разных scope.",
            "Наземное СМР нормализуется к м² наземной ГНС, подземное — к м² подземной ГНС, общепроектные статьи — к общей ГНС.",
            "Sellable/apartments/building-total переводятся в базу DevelopAid только через реальные ТЭП целевого проекта.",
            "Вес = качество нормализации × свежесть × тип источника × методологическая сопоставимость.",
            "A — прямое совпадение; B — прозрачная нормализация; C — оценочная декомпозиция; D — только справочно.",
            "Срезы классов одного исследования считаются одной выборкой и не получают несколько голосов в агрегате.",
            "Рекомендация — взвешенный consensus; диапазон учитывает опубликованные low/high каждого допущенного источника.",
            "Дата цены пока не переиндексируется автоматически: она показана отдельно и влияет на вес свежести. Для полной временной нормализации нужен верифицированный ряд индексов Мосстата.",
        ],
    }
