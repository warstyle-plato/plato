from __future__ import annotations

import math
import statistics
from typing import Any


def _percentile(values: list[int], q: float) -> int:
    if not values:
        raise ValueError("empty sample")
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return int(round(ordered[lo] * (1 - weight) + ordered[hi] * weight))


def _trim_outliers(values: list[int]) -> list[int]:
    """Robustly remove obvious price outliers without assuming a normal distribution."""
    if len(values) < 4:
        return values[:]
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations)
    if mad == 0:
        return values[:]
    limit = 3.5 * 1.4826 * mad
    trimmed = [value for value in values if abs(value - median) <= limit]
    return trimmed or values[:]


def market_recommendation(projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build a current market benchmark from geographically valid primary-market analogues.

    Official EISZhS confirmation increases confidence but is not a hard gate: a project can
    participate when it is geocoded inside the radius and has a usable indexed asking price.
    This avoids the recall collapse caused by treating search-index confirmation as discovery.

    Что действительно является условием — доказанная привязка цены к проекту.
    ``price_verified`` читается явно и не имеет умолчания: отсутствующий ключ
    здесь означает «не доказано», потому что неподтверждённое наблюдение в
    медиане неотличимо от подтверждённого и портит ориентир молча.
    """
    rows: list[dict[str, Any]] = []
    for project in projects:
        if not project.get("within_radius"):
            continue
        if project.get("geo_status") not in (None, "resolved"):
            continue
        if not project.get("price_verified"):
            continue
        price = project.get("market_price") or {}
        if not price.get("available") or not price.get("price_per_sqm"):
            continue
        # Официальная средняя ЕИСЖС — это среднее по зарегистрированным сделкам,
        # оно отстаёт от рынка предложения. Привязка к проекту у неё доказана,
        # поэтому показывать её честно, но подменять ею текущий ориентир нельзя:
        # «доказано, чьё это число» и «годится как основание» — разные вопросы.
        if price.get("basis") == "official_domrf_fallback":
            continue
        value = int(price["price_per_sqm"])
        if value <= 0:
            continue
        distance = max(float(project.get("distance_km") or 0.25), 0.25)
        confirmed = bool(project.get("confirmed"))
        source_count = max(int(project.get("market_source_count") or 1), 1)
        rows.append(
            {
                "name": str(project.get("name") or ""),
                "price": value,
                "distance": distance,
                "confirmed": confirmed,
                "source_count": source_count,
            }
        )

    if not rows:
        return None

    kept_values = set(_trim_outliers([row["price"] for row in rows]))
    filtered = [row for row in rows if row["price"] in kept_values]
    if not filtered:
        filtered = rows

    weighted_sum = 0.0
    total_weight = 0.0
    for row in filtered:
        distance_weight = 1.0 / row["distance"]
        confirmation_weight = 1.15 if row["confirmed"] else 1.0
        source_weight = min(1.0 + 0.08 * (row["source_count"] - 1), 1.24)
        weight = distance_weight * confirmation_weight * source_weight
        weighted_sum += weight * row["price"]
        total_weight += weight

    recommended = int(round(weighted_sum / total_weight))
    values = [row["price"] for row in filtered]
    median = int(round(statistics.median(values)))
    if len(values) >= 4:
        low = _percentile(values, 0.25)
        high = _percentile(values, 0.75)
    else:
        low = int(round(median * 0.925))
        high = int(round(median * 1.075))

    confidence_score = min(
        0.95,
        0.45
        + 0.08 * min(len(filtered), 4)
        + 0.05 * sum(1 for row in filtered if row["confirmed"])
        + 0.03 * sum(1 for row in filtered if row["source_count"] >= 2),
    )

    return {
        "price_per_sqm": recommended,
        "market_median_price_per_sqm": median,
        "corridor_low_price_per_sqm": low,
        "corridor_high_price_per_sqm": high,
        "analogue_count": len(filtered),
        "raw_analogue_count": len(rows),
        "confidence": round(confidence_score, 2),
        "method": "robust_distance_weighted_primary_market",
        "projects": [row["name"] for row in filtered],
        "note": "Текущий ориентир по первичному рынку. Официальное подтверждение повышает вес, но не является условием попадания в выборку.",
    }
