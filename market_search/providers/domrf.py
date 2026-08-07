from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Iterable

from ..http import RemoteServiceError, fresh, get_json, load_json, save_json
from ..models import DomRfObject, GeoPoint


_DOMRF_HOST = os.getenv("DOMRF_PUBLIC_HOST", "https://xn--80az8a.xn--d1aqf.xn--p1ai").rstrip("/")
_MAP_ENDPOINT = f"{_DOMRF_HOST}/сервисы/api/kn/object/map"
_DETAIL_ENDPOINT = f"{_DOMRF_HOST}/сервисы/api/object"
_PUBLIC_OBJECT_BASE = f"{_DOMRF_HOST}/сервисы/каталог-новостроек/объект"


class DomRfProvider:
    """Reads the same public JSON endpoints that back the official catalogue UI."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir / "domrf"
        self.map_cache = self.data_dir / "map.json"
        self.map_ttl = int(os.getenv("DOMRF_MAP_CACHE_TTL_SECONDS", "43200"))
        self.detail_ttl = int(os.getenv("DOMRF_DETAIL_CACHE_TTL_SECONDS", "86400"))
        self.place = os.getenv("DOMRF_MAP_PLACE", "").strip() or None

    def nearby(self, point: GeoPoint, radius_km: float, limit: int) -> list[DomRfObject]:
        markers = self._map_objects()
        ranked: list[tuple[float, dict[str, Any]]] = []
        for marker in markers:
            coords = self._coordinates(marker)
            if coords is None:
                continue
            lat, lon = coords
            distance = haversine_km(point.latitude, point.longitude, lat, lon)
            if distance <= radius_km:
                ranked.append((distance, marker))
        ranked.sort(key=lambda pair: pair[0])

        result: list[DomRfObject] = []
        for distance, marker in ranked[:limit]:
            object_id = self._integer(marker, "objId", "id", "objectId")
            if object_id is None:
                continue
            detail = self._detail(object_id)
            result.append(self._normalise(marker, detail, distance, object_id))
        return result

    def _map_objects(self) -> list[dict[str, Any]]:
        cached = load_json(self.map_cache) if fresh(self.map_cache, self.map_ttl) else None
        if isinstance(cached, dict) and isinstance(cached.get("items"), list):
            return [item for item in cached["items"] if isinstance(item, dict)]

        params = {"place": self.place} if self.place else {}
        payload = get_json(_MAP_ENDPOINT, params=params, timeout=60, retries=3)
        items = self._extract_list(payload)
        if not items:
            raise RemoteServiceError("Наш.Дом.РФ вернул пустую карту объектов")
        save_json(self.map_cache, {"items": items})
        return items

    def _detail(self, object_id: int) -> dict[str, Any]:
        path = self.data_dir / "objects" / f"{object_id}.json"
        cached = load_json(path) if fresh(path, self.detail_ttl) else None
        if isinstance(cached, dict):
            return cached
        payload = get_json(f"{_DETAIL_ENDPOINT}/{object_id}", timeout=30, retries=2)
        detail = payload.get("data", payload) if isinstance(payload, dict) else {}
        if not isinstance(detail, dict):
            detail = {}
        save_json(path, detail)
        return detail

    def _normalise(
        self,
        marker: dict[str, Any],
        detail: dict[str, Any],
        distance: float,
        object_id: int,
    ) -> DomRfObject:
        data = {**marker, **detail}
        lat, lon = self._coordinates(data) or self._coordinates(marker) or (0.0, 0.0)
        declaration_url = self._text(data, "rpdPdfLink", "projectDeclarationUrl", "pdPdfLink")
        return DomRfObject(
            object_id=object_id,
            name=self._text(data, "nameObj", "objName", "name") or f"Объект {object_id}",
            address=self._text(data, "address", "objAddr", "objectAddress") or "Адрес не указан",
            latitude=lat,
            longitude=lon,
            distance_km=round(distance, 3),
            status=self._text(data, "objStatusDesc", "objReadyDesc", "status"),
            developer=self._nested_text(data, ("developer", "devShortCleanNm"), ("developer", "devShortNm"))
            or self._text(data, "devShortCleanNm", "developerName"),
            completion_date=self._text(data, "objReady100PercDt", "objTransferPlanDt", "completionDate"),
            housing_class=self._text(data, "objLkClassDesc", "housingClass"),
            living_area_sqm=self._number(data, "objSquareLiving", "objFlatSq", "livingArea"),
            apartments=self._integer(data, "objElemLivingCnt", "objFlatCnt", "apartments"),
            sold_out_pct=self._number(data, "soldOutPerc", "soldPercent"),
            average_price_sqm=self._number(data, "objPriceAvg", "averagePrice"),
            project_declaration_number=self._text(data, "rpdNum", "projectDeclarationNumber"),
            project_declaration_url=declaration_url,
            domrf_url=f"{_PUBLIC_OBJECT_BASE}/{object_id}",
            source_updated_at=self._text(data, "loadDttm", "rpdIssueDttm", "updatedAt"),
        )

    @staticmethod
    def _extract_list(payload: Any) -> list[dict[str, Any]]:
        candidates: Iterable[Any] = ()
        if isinstance(payload, list):
            candidates = payload
        elif isinstance(payload, dict):
            data = payload.get("data", payload)
            if isinstance(data, dict):
                candidates = data.get("list") or data.get("items") or data.get("objects") or ()
            elif isinstance(data, list):
                candidates = data
        return [item for item in candidates if isinstance(item, dict)]

    @classmethod
    def _coordinates(cls, item: dict[str, Any]) -> tuple[float, float] | None:
        lat = cls._number(item, "objLkLatitude", "latitude", "lat")
        lon = cls._number(item, "objLkLongitude", "longitude", "lon", "lng")
        if lat is None or lon is None:
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon

    @staticmethod
    def _text(item: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _nested_text(item: dict[str, Any], *paths: tuple[str, ...]) -> str | None:
        for path in paths:
            value: Any = item
            for key in path:
                if not isinstance(value, dict):
                    value = None
                    break
                value = value.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _number(item: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = item.get(key)
            if value in (None, ""):
                continue
            try:
                return float(str(value).replace(" ", "").replace(",", "."))
            except ValueError:
                continue
        return None

    @classmethod
    def _integer(cls, item: dict[str, Any], *keys: str) -> int | None:
        value = cls._number(item, *keys)
        return int(value) if value is not None else None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
