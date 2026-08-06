from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    display_name: str
    provider: str
    precision: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


@dataclass(frozen=True)
class DomRfObject:
    object_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    distance_km: float
    status: str | None
    developer: str | None
    completion_date: str | None
    housing_class: str | None
    living_area_sqm: float | None
    apartments: int | None
    sold_out_pct: float | None
    average_price_sqm: float | None
    project_declaration_number: str | None
    project_declaration_url: str | None
    domrf_url: str
    source_updated_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
