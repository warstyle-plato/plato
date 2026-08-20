from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "statistics"
REFERENCE_DATA_DIR = ROOT / "reference_data" / "statistics"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CLASS_ALIASES = {
    "типовой": "standard",
    "стандарт": "standard",
    "standard": "standard",
    "массовый": "mass_market",
    "mass": "mass_market",
    "mass_market": "mass_market",
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

UNIT_LABELS = {
    "gba": "₽/м² ГНС",
    "apartments": "₽/м² общей площади квартир",
    "building_total": "₽/м² общей площади здания",
    "sellable": "₽/м² продаваемой площади",
}

METRIC_LABELS = {
    "main_construction": "Основное строительство",
    "construction_plus_landscaping": "Строительство + благоустройство",
    "construction_normative": "Норматив стоимости строительства",
    "declared_construction_cost": "Заявленная стоимость строительства",
    "full_construction_cost": "Полная стоимость строительства застройщика",
    "full_project_cost": "Полная себестоимость проекта",
}

SCOPE_LABELS = {
    "above_ground_main": "Наземная часть / основные СМР",
    "construction_plus_landscaping": "СМР + благоустройство",
    "building_normative": "Норматив строительства здания",
    "declared_project_construction": "Стоимость по проектным декларациям",
    "developer_full_cost": "Земля + строительство + сети + благоустройство + ТУ + ввод + прочие затраты",
    "full_project": "Полная себестоимость проекта",
}

INDEX_SOURCES = [
    {
        "source": "Росстат",
        "region": "Российская Федерация",
        "dataset": "Индексы цен производителей на строительную продукцию",
        "published_at": "2026-07-31",
        "source_url": "https://www.rosstat.gov.ru/statistics/price/",
        "role": "date_indexer",
        "automatic": False,
        "notes": "Используется только для приведения дат. Абсолютную себестоимость из этого ряда не выводить.",
    },
    {
        "source": "Мосстат",
        "region": "Москва",
        "dataset": "Индексы цен на продукцию (затраты, услуги) инвестиционного назначения за январь-июнь 2026 г.",
        "published_at": "2026-08-12",
        "source_url": "https://77.rosstat.gov.ru/folder/64640?print=1",
        "role": "date_indexer",
        "automatic": False,
        "notes": "Источник московского ряда подключен. Автоиндексация включается только после загрузки числового ряда и теста направления индекса.",
    },
]


@dataclass(frozen=True)
class ConstructionObservation:
    """Legacy object-level observation kept for backward compatibility."""

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
class NormalizedBenchmark:
    """One benchmark point with explicit semantics.

    Values with different unit, metric_type or cost_scope are never averaged.
    """

    source: str
    source_kind: str
    external_id: str
    region: str
    city: str | None
    housing_class: str
    reference_date: str
    value_rub_m2: float
    unit: str
    metric_type: str
    cost_scope: str
    source_url: str | None = None
    quality: float = 1.0
    active: bool = True
    notes: str = ""
    publication_date: str | None = None
    value_low_rub_m2: float | None = None
    value_high_rub_m2: float | None = None
    provenance: str = ""


@dataclass(frozen=True)
class BenchmarkResult:
    region: str
    city: str | None
    housing_class: str
    unit: str
    metric_type: str
    cost_scope: str | None
    n: int
    p25: float | None
    median: float | None
    p75: float | None
    mean: float | None
    confidence: str
    recommended: float | None
    comparable_points: list[dict[str, Any]]
    external_benchmarks: list[dict[str, Any]]
    filters_relaxed: list[str]
    methodology_version: str = "2.1"


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


def _confidence(n: int, source_kinds: Iterable[str] = ()) -> str:
    kinds = set(source_kinds)
    if n >= 20:
        return "high"
    if n >= 10:
        return "medium"
    if n >= 5:
        return "limited"
    if n >= 1 and "internal_project" in kinds:
        return "pilot"
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
    return [ExternalBenchmark(**row) for row in json.loads(target.read_text(encoding="utf-8"))]


def load_normalized_benchmarks(path: Path | None = None) -> list[NormalizedBenchmark]:
    if path is not None:
        target = path
    else:
        # Curated reference points are packaged with the image and must not be
        # hidden by the writable /app/data volume used in preview/production.
        target = REFERENCE_DATA_DIR / "normalized_benchmarks.json"
        if not target.exists():
            target = DATA_DIR / "normalized_benchmarks.json"
    if not target.exists():
        return []
    rows = json.loads(target.read_text(encoding="utf-8"))
    result: list[NormalizedBenchmark] = []
    for row in rows:
        item = dict(row)
        item["housing_class"] = normalize_class(item.get("housing_class"))
        result.append(NormalizedBenchmark(**item))
    return result


def _point_dict(point: NormalizedBenchmark) -> dict[str, Any]:
    payload = asdict(point)
    payload["unit_label"] = UNIT_LABELS.get(point.unit, point.unit)
    payload["metric_label"] = METRIC_LABELS.get(point.metric_type, point.metric_type)
    payload["scope_label"] = SCOPE_LABELS.get(point.cost_scope, point.cost_scope)
    return payload


def _curated_result(
    points: Iterable[NormalizedBenchmark],
    *,
    region: str,
    housing_class: str,
    city: str | None,
    unit: str,
    metric_type: str,
    cost_scope: str | None,
) -> BenchmarkResult | None:
    target_class = normalize_class(housing_class)
    active = [p for p in points if p.active and p.quality >= 0.5 and p.region == region]

    comparable = [
        p
        for p in active
        if normalize_class(p.housing_class) == target_class
        and p.unit == unit
        and p.metric_type == metric_type
        and (cost_scope is None or p.cost_scope == cost_scope)
        and (city is None or p.city in (None, city))
    ]
    values = _iqr_filter([p.value_rub_m2 for p in comparable if p.value_rub_m2 > 0])

    if not comparable:
        recommended = None
        p25 = median = p75 = mean = None
    else:
        p25 = _percentile(values, 0.25)
        median = statistics.median(values) if values else None
        p75 = _percentile(values, 0.75)
        mean = statistics.fmean(values) if values else None
        internal_values = [
            p.value_rub_m2
            for p in comparable
            if p.source_kind == "internal_project" and p.value_rub_m2 > 0
        ]
        recommended = statistics.median(internal_values) if internal_values else median

    refs = [
        _point_dict(p)
        for p in active
        if p not in comparable
        and (
            normalize_class(p.housing_class) in {target_class, "mass_market", "unknown"}
            or p.source_kind in {"official_normative", "industry_benchmark", "industry_case"}
        )
    ]
    refs.sort(key=lambda p: (p["reference_date"], p["source"]), reverse=True)

    if not comparable and not refs:
        return None

    resolved_scope = cost_scope
    if resolved_scope is None and comparable:
        scopes = {p.cost_scope for p in comparable}
        if len(scopes) == 1:
            resolved_scope = next(iter(scopes))

    return BenchmarkResult(
        region=region,
        city=city,
        housing_class=target_class,
        unit=unit,
        metric_type=metric_type,
        cost_scope=resolved_scope,
        n=len(values),
        p25=p25,
        median=median,
        p75=p75,
        mean=mean,
        confidence=_confidence(len(values), (p.source_kind for p in comparable)),
        recommended=recommended,
        comparable_points=[_point_dict(p) for p in comparable],
        external_benchmarks=refs,
        filters_relaxed=[],
    )


def build_benchmark(
    observations: Iterable[ConstructionObservation],
    external: Iterable[ExternalBenchmark],
    *,
    region: str,
    housing_class: str,
    city: str | None = None,
    unit: str = "gba",
    metric_type: str = "main_construction",
    cost_scope: str | None = None,
    floors_min: int | None = None,
    floors_max: int | None = None,
    construction_type: str | None = None,
    underground_parking: bool | None = None,
    min_sample: int = 5,
    normalized: Iterable[NormalizedBenchmark] | None = None,
) -> BenchmarkResult:
    curated = _curated_result(
        list(normalized) if normalized is not None else load_normalized_benchmarks(),
        region=region,
        housing_class=housing_class,
        city=city,
        unit=unit,
        metric_type=metric_type,
        cost_scope=cost_scope,
    )
    if curated is not None:
        return curated

    target_class = normalize_class(housing_class)
    base = [
        x
        for x in observations
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

    relaxed: set[str] = set()
    rows = filtered(relaxed)
    for key in ["parking", "construction_type", "floors", "city"]:
        if len(rows) >= min_sample:
            break
        relaxed.add(key)
        filters_relaxed.append(key)
        rows = filtered(relaxed)

    values = _iqr_filter([v for x in rows if (v := x.cost_per_m2(unit)) is not None])
    p25 = _percentile(values, 0.25)
    median = statistics.median(values) if values else None
    p75 = _percentile(values, 0.75)
    mean = statistics.fmean(values) if values else None
    refs = [asdict(x) for x in external if x.region == region]
    return BenchmarkResult(
        region=region,
        city=city,
        housing_class=target_class,
        unit=unit,
        metric_type=metric_type,
        cost_scope=cost_scope,
        n=len(values),
        p25=p25,
        median=median,
        p75=p75,
        mean=mean,
        confidence=_confidence(len(values)),
        recommended=median,
        comparable_points=[],
        external_benchmarks=refs,
        filters_relaxed=filters_relaxed,
    )


def source_catalog(points: Iterable[NormalizedBenchmark] | None = None) -> list[dict[str, Any]]:
    rows = list(points) if points is not None else load_normalized_benchmarks()
    return [_point_dict(p) for p in rows if p.active]


def index_source_catalog() -> list[dict[str, Any]]:
    return [dict(row) for row in INDEX_SOURCES]


def result_to_dict(result: BenchmarkResult) -> dict[str, Any]:
    payload = asdict(result)
    for key in ("p25", "median", "p75", "mean", "recommended"):
        if payload[key] is not None:
            payload[key] = round(payload[key])
    payload["unit_label"] = UNIT_LABELS.get(result.unit, result.unit)
    payload["metric_label"] = METRIC_LABELS.get(result.metric_type, result.metric_type)
    payload["scope_label"] = SCOPE_LABELS.get(result.cost_scope or "", result.cost_scope or "")
    return payload
