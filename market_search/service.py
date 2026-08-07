from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .geocoder import AddressGeocoder, GeoPoint, GeocodingError
from .yandex_search import YandexSearchClient, extract_project_candidates, official_cards_from_docs


class MarketDiscoveryService:
    def __init__(self, data_dir: Path):
        self.geocoder = AddressGeocoder(data_dir)
        self.search = YandexSearchClient(data_dir)

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
            subject = GeoPoint(
                latitude=latitude,
                longitude=longitude,
                display_name=address or f"{latitude:.6f}, {longitude:.6f}",
                provider="manual_coordinates",
                precision="exact",
            )
        else:
            subject = self.geocoder.geocode(address or "")

        locality = self._locality_hint(address or subject.display_name)
        queries = self._discovery_queries(address or subject.display_name, locality)
        docs = []
        for query in queries:
            docs.extend(self.search.search(query, groups_on_page=12))

        candidates = extract_project_candidates(docs)
        projects: list[dict[str, Any]] = []
        max_candidates = min(max(limit, 3), 8)
        for candidate in candidates[:max_candidates]:
            project_point = self._geocode_project(candidate["name"], locality)
            distance = None
            if project_point is not None:
                distance = round(
                    haversine_km(
                        subject.latitude,
                        subject.longitude,
                        project_point.latitude,
                        project_point.longitude,
                    ),
                    3,
                )
                if distance > radius_km:
                    continue

            official_query = f'site:наш.дом.рф "{candidate["name"]}" {locality}'
            official_docs = self.search.search(official_query, groups_on_page=8)
            cards = official_cards_from_docs(official_docs)

            projects.append(
                {
                    "name": candidate["name"],
                    "distance_km": distance,
                    "within_radius": distance is not None and distance <= radius_km,
                    "coordinates": (
                        {
                            "latitude": project_point.latitude,
                            "longitude": project_point.longitude,
                            "display_name": project_point.display_name,
                            "provider": project_point.provider,
                        }
                        if project_point is not None
                        else None
                    ),
                    "market_source": {
                        "url": candidate["source_url"],
                        "domain": candidate["source_domain"],
                        "title": candidate["source_title"],
                    },
                    "official_cards": cards,
                    "confirmed": bool(cards),
                    "confirmation": (
                        "Официальная карточка Наш.Дом.РФ найдена"
                        if cards
                        else "Официальная карточка пока не сопоставлена"
                    ),
                }
            )
            if len(projects) >= limit:
                break

        projects.sort(
            key=lambda item: (
                item["distance_km"] is None,
                item["distance_km"] if item["distance_km"] is not None else 9999,
                not item["confirmed"],
            )
        )
        confirmed_count = sum(1 for item in projects if item["confirmed"])
        return {
            "query": {"address": address, "radius_km": radius_km, "limit": limit},
            "location": subject.to_dict(),
            "source": {
                "discovery": "Yandex Search API",
                "confirmation": "Наш.Дом.РФ / ЕИСЖС через поисковый индекс Яндекса",
                "mode": "supported_search_api",
            },
            "projects": projects,
            "count": len(projects),
            "confirmed_count": confirmed_count,
            "warning": self._warning(projects, confirmed_count),
            "diagnostics": {
                "search_queries": queries,
                "raw_search_documents": len(docs),
                "project_names_extracted": len(candidates),
            },
        }

    def _geocode_project(self, name: str, locality: str) -> GeoPoint | None:
        attempts = [f"ЖК {name}, {locality}", f"{name}, {locality}"]
        for query in attempts:
            try:
                return self.geocoder.geocode(query)
            except GeocodingError:
                continue
        return None

    @staticmethod
    def _locality_hint(value: str) -> str:
        low = value.lower()
        if "московск" in low and "област" in low:
            return "Московская область"
        return "Москва"

    @staticmethod
    def _discovery_queries(address: str, locality: str) -> list[str]:
        clean = " ".join(address.split())
        return [
            f'новостройки рядом с "{clean}" {locality}',
            f'site:domclick.ru новостройки "{clean}" {locality}',
        ]

    @staticmethod
    def _warning(projects: list[dict[str, Any]], confirmed_count: int) -> str | None:
        if not projects:
            return "Поисковый индекс не дал проектов, которые удалось привязать к заданному радиусу"
        if confirmed_count == 0:
            return "Кандидаты найдены, но ни один пока не подтверждён ссылкой Наш.Дом.РФ"
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
