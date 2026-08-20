from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "statistics"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CLASS_ALIASES = {"типовой":"standard","стандарт":"standard","standard":"standard","комфорт":"comfort","comfort":"comfort","бизнес":"business","business":"business","премиум":"premium","premium":"premium","элитный":"elite","элита":"elite","elite":"elite"}

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
        denominator = {"gba":self.gba_m2,"apartments":self.apartment_area_m2,"sellable":self.sellable_area_m2}.get(unit)
        if denominator is None or denominator <= 0 or self.planned_cost_rub <= 0: return None
        return self.planned_cost_rub / denominator

@dataclass(frozen=True)
class ExternalBenchmark:
    source: str; region: str; reference_date: str; value_rub_m2: float; unit: str; scope: str; source_url: str | None = None

@dataclass(frozen=True)
class BenchmarkResult:
    region: str; city: str | None; housing_class: str; unit: str; n: int
    p25: float | None; median: float | None; p75: float | None; mean: float | None
    confidence: str; recommended: float | None; external_benchmarks: list[dict[str, Any]]; filters_relaxed: list[str]
    methodology_version: str = "1.0"

def normalize_class(value: str | None) -> str:
    text=(value or "").strip().lower(); return CLASS_ALIASES.get(text,text or "unknown")

def _percentile(values:list[float],p:float)->float|None:
    if not values:return None
    values=sorted(values)
    if len(values)==1:return values[0]
    pos=(len(values)-1)*p; lo=math.floor(pos); hi=math.ceil(pos)
    if lo==hi:return values[lo]
    return values[lo]*(hi-pos)+values[hi]*(pos-lo)

def _confidence(n:int)->str:
    return "high" if n>=20 else "medium" if n>=10 else "limited" if n>=5 else "insufficient"

def _iqr_filter(values:list[float])->list[float]:
    if len(values)<8:return values
    q1=_percentile(values,.25); q3=_percentile(values,.75)
    if q1 is None or q3 is None:return values
    iqr=q3-q1; lo,hi=q1-1.5*iqr,q3+1.5*iqr
    return [v for v in values if lo<=v<=hi]

def load_observations(path:Path|None=None)->list[ConstructionObservation]:
    target=path or DATA_DIR/"observations.jsonl"
    if not target.exists():return []
    result=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        row=json.loads(line); row["housing_class"]=normalize_class(row.get("housing_class")); result.append(ConstructionObservation(**row))
    return result

def load_external_benchmarks(path:Path|None=None)->list[ExternalBenchmark]:
    target=path or DATA_DIR/"external_benchmarks.json"
    if not target.exists():return []
    return [ExternalBenchmark(**row) for row in json.loads(target.read_text(encoding="utf-8"))]

def build_benchmark(observations:Iterable[ConstructionObservation],external:Iterable[ExternalBenchmark],*,region:str,housing_class:str,city:str|None=None,unit:str="gba",floors_min:int|None=None,floors_max:int|None=None,construction_type:str|None=None,underground_parking:bool|None=None,min_sample:int=5)->BenchmarkResult:
    target_class=normalize_class(housing_class)
    base=[x for x in observations if x.region==region and normalize_class(x.housing_class)==target_class and x.quality>=.5]
    filters_relaxed=[]
    def filtered(relax:set[str]):
        rows=base
        if city and "city" not in relax: rows=[x for x in rows if x.city==city]
        if (floors_min is not None or floors_max is not None) and "floors" not in relax:
            rows=[x for x in rows if x.floors is not None]
            if floors_min is not None: rows=[x for x in rows if x.floors>=floors_min]
            if floors_max is not None: rows=[x for x in rows if x.floors<=floors_max]
        if construction_type and "construction_type" not in relax: rows=[x for x in rows if (x.construction_type or "").lower()==construction_type.lower()]
        if underground_parking is not None and "parking" not in relax: rows=[x for x in rows if x.underground_parking is underground_parking]
        return rows
    relaxed=set(); rows=filtered(relaxed)
    for key in ["parking","construction_type","floors","city"]:
        if len(rows)>=min_sample:break
        relaxed.add(key); filters_relaxed.append(key); rows=filtered(relaxed)
    values=_iqr_filter([v for x in rows if (v:=x.cost_per_m2(unit)) is not None])
    p25=_percentile(values,.25); med=statistics.median(values) if values else None; p75=_percentile(values,.75); mean=statistics.fmean(values) if values else None
    refs=[asdict(x) for x in external if x.region==region]
    return BenchmarkResult(region,city,target_class,unit,len(values),p25,med,p75,mean,_confidence(len(values)),med,refs,filters_relaxed)

def result_to_dict(result:BenchmarkResult)->dict[str,Any]:
    payload=asdict(result)
    for key in ("p25","median","p75","mean","recommended"):
        if payload[key] is not None: payload[key]=round(payload[key])
    return payload
