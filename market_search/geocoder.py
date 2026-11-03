from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .http import RemoteServiceError, fresh, get_json, load_json, save_json


class GeocodingError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    display_name: str
    provider: str
    precision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AddressGeocoder:
    """Yandex Geocoder when configured; cached Nominatim fallback for low-volume preview."""

    _nominatim_lock = threading.Lock()
    _last_nominatim_request = 0.0

    def __init__(self, data_dir: Path):
        self.cache_dir = data_dir / "geocoding"
        self.yandex_key = os.getenv("YANDEX_GEOCODER_API_KEY", "").strip()
        self.nominatim_url = os.getenv(
            "NOMINATIM_SEARCH_URL", "https://nominatim.openstreetmap.org/search"
        ).strip()
        self.cache_ttl = int(os.getenv("MARKET_GEOCODE_CACHE_TTL_SECONDS", "2592000"))

    def geocode(self, query: str) -> GeoPoint:
        query = " ".join(str(query or "").split())
        if len(query) < 3:
            raise GeocodingError("Слишком короткий поисковый запрос")

        key = hashlib.sha256(query.lower().encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{key}.json"
        cached = load_json(cache_path) if fresh(cache_path, self.cache_ttl) else None
        if isinstance(cached, dict):
            return GeoPoint(**cached)

        errors: list[str] = []
        if self.yandex_key:
            try:
                point = self._yandex(query)
                save_json(cache_path, point.to_dict())
                return point
            except (GeocodingError, RemoteServiceError) as exc:
                errors.append(f"Yandex: {exc}")

        try:
            point = self._nominatim(query)
            save_json(cache_path, point.to_dict())
            return point
        except (GeocodingError, RemoteServiceError) as exc:
            errors.append(f"Nominatim: {exc}")

        raise GeocodingError("; ".join(errors) or "Место не найдено")

    def _yandex(self, query: str) -> GeoPoint:
        payload = get_json(
            "https://geocode-maps.yandex.ru/1.x/",
            params={
                "apikey": self.yandex_key,
                "geocode": query,
                "format": "json",
                "results": 1,
                "lang": "ru_RU",
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
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeocodingError("место не найдено") from exc

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
            raise GeocodingError("место не найдено")
        item = payload[0]
        try:
            return GeoPoint(
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
                display_name=str(item.get("display_name") or query),
                provider="nominatim",
                precision=str(item.get("addresstype") or item.get("type") or "unknown"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GeocodingError("геокодер вернул неполный ответ") from exc
