from __future__ import annotations

from pathlib import Path
from typing import Any

from .geocoder import AddressGeocoder
from .models import GeoPoint
from .providers import DomRfProvider


class MarketDiscoveryService:
    def __init__(self, data_dir: Path):
        self.geocoder = AddressGeocoder(data_dir)
        self.domrf = DomRfProvider(data_dir)

    def discover(
        self,
        *,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
        radius_km: float,
        limit: int,
    ) -> dict[str, Any]:
        if latitude is not None and longitude is not None:
            point = GeoPoint(
                latitude=latitude,
                longitude=longitude,
                display_name=address or f"{latitude:.6f}, {longitude:.6f}",
                provider="manual_coordinates",
                precision="exact",
            )
        else:
            point = self.geocoder.geocode(address or "")

        objects = self.domrf.nearby(point, radius_km=radius_km, limit=limit)
        return {
            "query": {
                "address": address,
                "radius_km": radius_km,
                "limit": limit,
            },
            "location": point.to_dict(),
            "source": {
                "name": "ЕИСЖС / Наш.Дом.РФ",
                "mode": "public_catalogue",
                "unit": "корпус",
            },
            "objects": [item.to_dict() for item in objects],
            "count": len(objects),
            "warning": None if objects else "В заданном радиусе корпуса не найдены",
        }
