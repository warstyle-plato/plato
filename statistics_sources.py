from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.request
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from developaid_statistics import ConstructionObservation, DATA_DIR, ExternalBenchmark, normalize_class

EISZH_API_BASE = os.getenv("EISZH_API_BASE", "").strip()
EISZH_API_TOKEN = os.getenv("EISZH_API_TOKEN", "").strip()

# These are source landing pages, not hidden/private endpoints. Concrete file/API
# URLs are discovered/configured explicitly so a silent site redesign cannot
# corrupt the benchmark pipeline.
ROSSTAT_PRICE_PAGE = "https://rosstat.gov.ru/statistics/price"
ERZ_REFERENCE_PAGE = "https://erzrf.ru/publikacii/srednyaya-stoimost-stroitelstva-mkd-massovogo-sprosa-i-sredniye-tseny-na-rynke-nedvizhimosti-po-regionam-rf-na-aprel-2026-goda"


def _http_json(url: str, token: str = "", timeout: int = 30) -> Any:
    headers = {"User-Agent": "DevelopAid-Statistics/0.1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def eiszh_status() -> dict[str, Any]:
    return {
        "configured": bool(EISZH_API_BASE and EISZH_API_TOKEN),
        "api_base_configured": bool(EISZH_API_BASE),
        "token_configured": bool(EISZH_API_TOKEN),
        "purpose": "object-level project declaration observations",
    }


def map_eiszh_record(row: dict[str, Any]) -> ConstructionObservation | None:
    """Map an already-authorized EISZH record to our canonical observation.

    Field names differ between API versions/exports, therefore the adapter uses
    a small alias map and rejects rows without cost/region instead of guessing.
    """
    def pick(*names):
        for name in names:
            value = row.get(name)
            if value not in (None, ""):
                return value
        return None

    cost = pick("plannedCost", "planned_cost", "objPrice", "constructionCost")
    region = pick("region", "regionName", "subjectName")
    if not cost or not region:
        return None
    try:
        cost_f = float(str(cost).replace(" ", "").replace(",", "."))
    except ValueError:
        return None

    def number(*names):
        value = pick(*names)
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    floors = number("maxFloor", "floors", "floorCount")
    return ConstructionObservation(
        source="eiszh",
        external_id=str(pick("id", "objectId", "objId") or ""),
        region=str(region).strip(),
        city=(str(pick("city", "cityName", "locality") or "").strip() or None),
        housing_class=normalize_class(str(pick("class", "objLkClassDesc", "housingClass") or "unknown")),
        reference_date=str(pick("pdDate", "declarationDate", "lastUpdate") or date.today().isoformat())[:10],
        planned_cost_rub=cost_f,
        gba_m2=number("totalArea", "gba", "objectArea"),
        apartment_area_m2=number("livingArea", "apartmentArea", "residentialArea"),
        sellable_area_m2=number("sellableArea", "saleArea"),
        floors=int(floors) if floors is not None else None,
        construction_type=(str(pick("constructionType", "wallMaterial") or "").strip() or None),
        underground_parking=None,
        source_url=(str(pick("url", "sourceUrl") or "").strip() or None),
        quality=1.0,
    )


def import_eiszh_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else payload.get("data") or payload.get("items") or payload.get("results") or []
    mapped = [x for row in rows if isinstance(row, dict) and (x := map_eiszh_record(row)) is not None]
    target = DATA_DIR / "observations.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(json.dumps(asdict(x), ensure_ascii=False) for x in mapped) + ("\n" if mapped else ""), encoding="utf-8")
    return {"input": len(rows), "accepted": len(mapped), "target": str(target)}


def import_external_benchmark_csv(path: str | Path, source: str) -> dict[str, Any]:
    """Import legally obtained CSV/XLSX-converted source table.

    Required CSV headers: region, reference_date, value_rub_m2, unit, scope.
    Optional: source_url.
    """
    rows: list[ExternalBenchmark] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                rows.append(ExternalBenchmark(
                    source=source,
                    region=row["region"].strip(),
                    reference_date=row["reference_date"].strip(),
                    value_rub_m2=float(row["value_rub_m2"].replace(" ", "").replace(",", ".")),
                    unit=row["unit"].strip(),
                    scope=row["scope"].strip(),
                    source_url=(row.get("source_url") or "").strip() or None,
                ))
            except (KeyError, ValueError):
                continue
    target = DATA_DIR / "external_benchmarks.json"
    target.write_text(json.dumps([asdict(x) for x in rows], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"accepted": len(rows), "target": str(target)}


def source_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "eiszh",
            "name": "ЕИСЖС / наш.дом.рф",
            "mode": "api_or_official_export",
            "status": eiszh_status(),
            "role": "primary_object_sample",
            "refresh": "daily",
        },
        {
            "id": "rosstat",
            "name": "Росстат",
            "mode": "official_xlsx",
            "landing_page": ROSSTAT_PRICE_PAGE,
            "role": "price_indexation",
            "refresh": "monthly",
        },
        {
            "id": "sis_erz",
            "name": "СИС / ЕРЗ",
            "mode": "licensed_export_or_publication_table",
            "landing_page": ERZ_REFERENCE_PAGE,
            "role": "external_reference",
            "refresh": "on_publication",
        },
        {
            "id": "developaid_fact",
            "name": "DevelopAid plan/fact",
            "mode": "internal_anonymized",
            "role": "future_actual_cost_layer",
            "refresh": "on_project_update",
        },
    ]
