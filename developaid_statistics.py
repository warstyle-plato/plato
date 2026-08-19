from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "statistics"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CLASS_ALIASES = {
    "типовой": "standard",
    "стандарт": "standard",
    "standard": "standard",
    "комфорт": "comfort",
    "comfort": "comfort",
    "бизнес": "business",
    "business": "business",
    "премиум": "premium",
    "premium": "premium",
    "элитный": "elite",
    "элита": "elite",
    "elite": "elite",
}


@dataclass(frozen=True)
class ConstructionObservation:
    source: str
    external_id: str
    region: str
    city: str | None
    housing_class: str
    reference_date: str
    planned_cost_rub: float
    gba_m2: float | None = None
    apartment_area_m2: float | None = None
    sellable_area_m2: float | None = None
    floors: int | None = None
    construction_type: str | None = None
    underground_parking: bool | None = None
    source_url: str | None = None
    quality: float = 1.0

    def cost_per_m2(self, unit: str = "gba") -> float | None:
        denominator = {
            "gba": self.gba_m2,
            "apartments": self.apartment_area_m2,
            "sellable": self.sellable_area_m2,
        }.get(unit)
        if denominator is None or denominator <= 0 or self.planned_cost_rub <= 0:
            return None
        return self.planned_cost_rub / denominator


@dataclass(frozen=True)
class ExternalBenchmark:
    source: str
    region: str
    reference_date: str
    value_rub_m2: float
    unit: str
    scope: str
    source_url: str | None = None


@dataclass(frozen=True)
class BenchmarkResult:
    region: str
    city: str | None
    housing_class: str
    unit: str
    n: int
    p25: float | None
    median: float | None
    p75: float | None
    mean: float | None
    confidence: str
    recommended: float | None
    external_benchmarks: list[dict[str, Any]]
    filters_relaxed: list[str]
    methodology_version: str = "1.0"


def normalize_class(value: str | None) -> str:
    text = (value or "").strip().lower()
    return CLASS_ALIASES.get(text, text or "unknown")


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * p
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def _confidence(n: int) -> str:
    if n >= 20:
        return "high"
    if n >= 10:
        return "medium"
    if n >= 5:
        return "limited"
    return "insufficient"


def _iqr_filter(values: list[float]) -> list[float]:
    if len(values) < 8:
        return values
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    if q1 is None or q3 is None:
        return values
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [v for v in values if lo <= v <= hi]


def save_observations(items: Iterable[ConstructionObservation], path: Path | None = None) -> Path:
    target = path or DATA_DIR / "observations.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
    return target


def load_observations(path: Path | None = None) -> list[ConstructionObservation]:
    target = path or DATA_DIR / "observations.jsonl"
    if not target.exists():
        return []
    result: list[ConstructionObservation] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["housing_class"] = normalize_class(row.get("housing_class"))
        result.append(ConstructionObservation(**row))
    return result


def load_external_benchmarks(path: Path | None = None) -> list[ExternalBenchmark]:
    target = path or DATA_DIR / "external_benchmarks.json"
    if not target.exists():
        return []
    payload = json.loads(target.read_text(encoding="utf-8"))
    return [ExternalBenchmark(**row) for row in payload]


def build_benchmark(
    observations: Iterable[ConstructionObservation],
    external: Iterable[ExternalBenchmark],
    *,
    region: str,
    housing_class: str,
    city: str | None = None,
    unit: str = "gba",
    floors_min: int | None = None,
    floors_max: int | None = None,
    construction_type: str | None = None,
    underground_parking: bool | None = None,
    min_sample: int = 5,
) -> BenchmarkResult:
    target_class = normalize_class(housing_class)
    base = [
        x for x in observations
        if x.region == region and normalize_class(x.housing_class) == target_class and x.quality >= 0.5
    ]

    filters_relaxed: list[str] = []

    def filtered(relax: set[str]) -> list[ConstructionObservation]:
        rows = base
        if city and "city" not in relax:
            rows = [x for x in rows if x.city == city]
        if (floors_min is not None or floors_max is not None) and "floors" not in relax:
            rows = [x for x in rows if x.floors is not None]
            if floors_min is not None:
                rows = [x for x in rows if x.floors >= floors_min]
            if floors_max is not None:
                rows = [x for x in rows if x.floors <= floors_max]
        if construction_type and "construction_type" not in relax:
            rows = [x for x in rows if (x.construction_type or "").lower() == construction_type.lower()]
        if underground_parking is not None and "parking" not in relax:
            rows = [x for x in rows if x.underground_parking is underground_parking]
        return rows

    relax_order = ["parking", "construction_type", "floors", "city"]
    relaxed: set[str] = set()
    rows = filtered(relaxed)
    for key in relax_order:
        if len(rows) >= min_sample:
            break
        relaxed.add(key)
        filters_relaxed.append(key)
        rows = filtered(relaxed)

    values = [v for x in rows if (v := x.cost_per_m2(unit)) is not None]
    values = _iqr_filter(values)

    p25 = _percentile(values, 0.25)
    med = statistics.median(values) if values else None
    p75 = _percentile(values, 0.75)
    mean = statistics.fmean(values) if values else None

    refs = [asdict(x) for x in external if x.region == region]

    # Рекомендация пока консервативно равна медиане собственной выборки.
    # Внешние источники показываются рядом и не смешиваются арифметически:
    # их методология/знаменатель часто отличаются от ЕИСЖС.
    recommended = med

    return BenchmarkResult(
        region=region,
        city=city,
        housing_class=target_class,
        unit=unit,
        n=len(values),
        p25=p25,
        median=med,
        p75=p75,
        mean=mean,
        confidence=_confidence(len(values)),
        recommended=recommended,
        external_benchmarks=refs,
        filters_relaxed=filters_relaxed,
    )


def result_to_dict(result: BenchmarkResult) -> dict[str, Any]:
    payload = asdict(result)
    for key in ("p25", "median", "p75", "mean", "recommended"):
        if payload[key] is not None:
            payload[key] = round(payload[key])
    return payload
