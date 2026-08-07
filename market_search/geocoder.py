from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any

from .http import RemoteServiceError, fresh, get_json, load_json, save_json
from .models import GeoPoint


class GeocodingError(RuntimeError):
    pass


class AddressGeocoder:
    """Yandex first when configured; public Nominatim only as cached MVP fallback."""

    _nominatim_lock = threading.Lock()
    _last_nominatim_request = 0.0

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.cache_dir = data_dir / "geocoding"
        self.yandex_key = os.getenv("YANDEX_GEOCODER_API_KEY", "").strip()
        self.nominatim_url = os.getenv(
            "NOMINATIM_SEARCH_URL", "https://nominatim.openstreetmap.org/search"
        ).strip()
        self.cache_ttl = int(os.getenv("MARKET_GEOCODE_CACHE_TTL_SECONDS", "2592000"))

    def geocode(self, address: str) -> GeoPoint:
        query = " ".join(str(address or "").split())
        if len(query) < 5:
            raise GeocodingError("Введите полный адрес с номером дома")

        key = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{key}.json"
        cached = load_json(cache_path) if fresh(cache_path, self.cache_ttl) else None
        if isinstance(cached, dict):
            return self._from_cache(cached)

        errors: list[str] = []
        if self.yandex_key:
            try:
                point = self._yandex(query)
                save_json(cache_path, self._cache_payload(point))
                return point
            except (GeocodingError, RemoteServiceError) as exc:
                errors.append(f"Yandex: {exc}")

        try:
            point = self._nominatim(query)
            save_json(cache_path, self._cache_payload(point))
            return point
        except (GeocodingError, RemoteServiceError) as exc:
            errors.append(f"Nominatim: {exc}")

        raise GeocodingError("; ".join(errors) or "Адрес не найден")

    def _yandex(self, query: str) -> GeoPoint:
        payload = get_json(
            "https://geocode-maps.yandex.ru/1.x/",
            params={
                "apikey": self.yandex_key,
                "geocode": query,
                "format": "json",
                "results": 1,
                "lang": "ru_RU",
                "bbox": "35.0,54.0~41.5,57.2",
                "rspn": 0,
            },
        )
        try:
            geo = payload["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]
            lon, lat = (float(v) for v in geo["Point"]["pos"].split())
            metadata = geo.get("metaDataProperty", {}).get("GeocoderMetaData", {})
            return GeoPoint(
                latitude=lat,
                longitude=lon,
                display_name=str(metadata.get("text") or geo.get("name") or query),
                provider="yandex",
                precision=metadata.get("precision"),
                raw=geo,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeocodingError("адрес не найден") from exc

    def _nominatim(self, query: str) -> GeoPoint:
        with self._nominatim_lock:
            wait = 1.05 - (time.monotonic() - self._last_nominatim_request)
            if wait > 0:
                time.sleep(wait)
            payload = get_json(
                self.nominatim_url,
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                    "countrycodes": "ru",
                    "viewbox": "35.0,57.2,41.5,54.0",
                },
                retries=1,
            )
            self.__class__._last_nominatim_request = time.monotonic()
        if not isinstance(payload, list) or not payload:
            raise GeocodingError("адрес не найден")
        item = payload[0]
        try:
            return GeoPoint(
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
                display_name=str(item.get("display_name") or query),
                provider="nominatim",
                precision=str(item.get("addresstype") or item.get("type") or "unknown"),
                raw=item,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocodingError("геокодер вернул неполный ответ") from exc

    @staticmethod
    def _cache_payload(point: GeoPoint) -> dict[str, Any]:
        return {
            "latitude": point.latitude,
            "longitude": point.longitude,
            "display_name": point.display_name,
            "provider": point.provider,
            "precision": point.precision,
        }

    @staticmethod
    def _from_cache(payload: dict[str, Any]) -> GeoPoint:
        return GeoPoint(
            latitude=float(payload["latitude"]),
            longitude=float(payload["longitude"]),
            display_name=str(payload["display_name"]),
            provider=str(payload["provider"]),
            precision=payload.get("precision"),
        )
