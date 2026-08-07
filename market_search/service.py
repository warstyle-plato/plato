from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .geocoder import AddressGeocoder, GeoPoint, GeocodingError
from .http import RemoteServiceError
from .price import MarketPriceEnricher, weighted_market_price
from .yandex_search import YandexSearchClient, extract_project_candidates, official_cards_from_docs


class MarketDiscoveryService:
    def __init__(self, data_dir: Path):
        self.geocoder = AddressGeocoder(data_dir)
        self.search = YandexSearchClient(data_dir)
        self.prices = MarketPriceEnricher(self.search)

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

        locality = self._locality_hint(f"{address or ''} {subject.display_name}")
        district = self._district_hint(subject.display_name)
        queries = self._discovery_queries(address or subject.display_name, locality, district)
        docs = []
        for query in queries:
            docs.extend(self.search.search(query, groups_on_page=12))

        candidates = extract_project_candidates(docs)
        projects: list[dict[str, Any]] = []
        max_candidates = min(max(limit * 2, 6), 20)
        for candidate in candidates[:max_candidates]:
            project_point = self._geocode_project(candidate, locality)
            if project_point is None:
                continue

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

            source_text = " ".join(
                str(candidate.get(key) or "")
                for key in ("source_title", "source_snippet")
            )
            address_hint = self._address_hint(source_text)
            official_query = f'site:наш.дом.рф "{candidate["name"]}" {address_hint or locality}'
            official_docs = self.search.search(official_query, groups_on_page=8)
            raw_cards = official_cards_from_docs(official_docs)
            cards = [
                card
                for card in raw_cards
                if self._official_card_matches(candidate["name"], address_hint, card)
            ]

            price_info: dict[str, Any] = {
                "available": False,
                "method": "indexed_asking_prices",
                "note": "Цена запрашивается только для подтверждённых аналогов",
            }
            if cards:
                try:
                    price_info = self.prices.project_price(candidate["name"], locality)
                except RemoteServiceError as exc:
                    price_info = {
                        "available": False,
                        "method": "indexed_asking_prices",
                        "error": str(exc),
                    }

            projects.append(
                {
                    "name": candidate["name"],
                    "distance_km": distance,
                    "within_radius": True,
                    "coordinates": {
                        "latitude": project_point.latitude,
                        "longitude": project_point.longitude,
                        "display_name": project_point.display_name,
                        "provider": project_point.provider,
                    },
                    "market_source": {
                        "url": candidate["source_url"],
                        "domain": candidate["source_domain"],
                        "title": candidate["source_title"],
                    },
                    "official_cards": cards,
                    "confirmed": bool(cards),
                    "confirmation": (
                        "Официальная карточка Наш.Дом.РФ сопоставлена"
                        if cards
                        else "Официальная карточка пока не подтверждена по названию или адресу"
                    ),
                    "market_price": price_info,
                }
            )
            if len(projects) >= limit:
                break

        projects.sort(key=lambda item: (item["distance_km"], not item["confirmed"]))
        confirmed_count = sum(1 for item in projects if item["confirmed"])
        price_summary = weighted_market_price(projects)
        return {
            "query": {
                "address": address,
                "radius_km": radius_km,
                "limit": limit,
                "district": district,
            },
            "location": subject.to_dict(),
            "source": {
                "discovery": "Yandex Search API",
                "confirmation": "Наш.Дом.РФ / ЕИСЖС через поисковый индекс Яндекса",
                "pricing": "ЦИАН; Домклик; Яндекс Недвижимость через поисковый индекс",
                "mode": "supported_search_api",
            },
            "projects": projects,
            "count": len(projects),
            "confirmed_count": confirmed_count,
            "price_summary": price_summary,
            "warning": self._warning(projects, confirmed_count),
            "diagnostics": {
                "search_queries": queries,
                "raw_search_documents": len(docs),
                "project_names_extracted": len(candidates),
            },
        }

    def _geocode_project(self, candidate: dict[str, Any], locality: str) -> GeoPoint | None:
        name = candidate["name"]
        snippet = " ".join(
            str(candidate.get(key) or "")
            for key in ("source_title", "source_snippet")
        )
        address_hint = self._address_hint(snippet)
        attempts = []
        if address_hint:
            attempts.append(address_hint)
        attempts.extend([f"ЖК {name}, {locality}", f"{name}, {locality}"])
        for query in attempts:
            try:
                return self.geocoder.geocode(query)
            except GeocodingError:
                continue
        return None

    @staticmethod
    def _address_hint(value: str) -> str | None:
        match = re.search(
            r"(?:Москва|Московская область)[,.:\s]+([^.;]{3,90}?(?:ул\.?|улица|проспект|проезд|шоссе|ш\.|наб\.?|набережная)[^.;]{2,80}?\d+[А-Яа-яA-Za-z0-9/\-]*)",
            value,
            flags=re.I,
        )
        if not match:
            return None
        return "Москва, " + " ".join(match.group(1).split())

    @classmethod
    def _official_card_matches(
        cls,
        project_name: str,
        address_hint: str | None,
        card: dict[str, Any],
    ) -> bool:
        haystack = " ".join(
            str(card.get(key) or "")
            for key in ("title", "snippet")
        )
        hay_norm = cls._compact(haystack)
        name_norm = cls._compact(project_name)
        if len(name_norm) >= 4 and name_norm in hay_norm:
            return True

        if address_hint:
            address_tokens = cls._address_match_tokens(address_hint)
            hay_tokens = set(cls._words(haystack))
            number_tokens = [token for token in address_tokens if any(ch.isdigit() for ch in token)]
            street_tokens = [token for token in address_tokens if token not in number_tokens]
            if number_tokens and street_tokens:
                number_ok = any(token in hay_tokens for token in number_tokens)
                street_ok = any(token in hay_tokens for token in street_tokens)
                if number_ok and street_ok:
                    return True
        return False

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-zа-яё0-9]+", "", str(value or "").lower().replace("ё", "е"))

    @staticmethod
    def _words(value: str) -> list[str]:
        return re.findall(r"[a-zа-яё0-9/\-]+", str(value or "").lower().replace("ё", "е"))

    @classmethod
    def _address_match_tokens(cls, value: str) -> list[str]:
        stop = {
            "москва", "московская", "область", "город", "улица", "ул", "шоссе", "ш",
            "проспект", "проезд", "набережная", "наб", "дом", "д", "корпус", "корп",
        }
        tokens = []
        for token in cls._words(value):
            clean = token.strip("-/")
            if not clean or clean in stop:
                continue
            if any(ch.isdigit() for ch in clean) or len(clean) >= 4:
                tokens.append(clean)
        return tokens

    @staticmethod
    def _district_hint(value: str) -> str | None:
        match = re.search(r"([^,]{2,50}\s+район)", value, flags=re.I)
        if not match:
            return None
        district = " ".join(match.group(1).split())
        district = re.sub(r"^(?:внутригородская территория|муниципальный округ)\s+", "", district, flags=re.I)
        return district

    @staticmethod
    def _locality_hint(value: str) -> str:
        low = value.lower()
        if "московск" in low and "област" in low and "москва" not in low.replace("московская область", ""):
            return "Московская область"
        return "Москва"

    @staticmethod
    def _discovery_queries(address: str, locality: str, district: str | None) -> list[str]:
        clean = " ".join(address.split())
        queries = [f'новостройки рядом с "{clean}" {locality}']
        if district:
            queries.extend(
                [
                    f'новостройки "{district}" {locality}',
                    f'site:domclick.ru новостройки "{district}" {locality}',
                    f'site:cian.ru новостройки "{district}" {locality}',
                    f'site:cian.ru "ЖК" "{district}" {locality} "от застройщика"',
                ]
            )
        else:
            queries.extend(
                [
                    f'site:domclick.ru новостройки "{clean}" {locality}',
                    f'site:cian.ru новостройки "{clean}" {locality}',
                ]
            )
        return queries

    @staticmethod
    def _warning(projects: list[dict[str, Any]], confirmed_count: int) -> str | None:
        if not projects:
            return "Поисковый индекс не дал проектов, которые удалось уверенно привязать к заданному радиусу"
        if confirmed_count == 0:
            return "Кандидаты найдены в радиусе, но ни один пока не подтверждён карточкой Наш.Дом.РФ"
        if not any((item.get("market_price") or {}).get("available") for item in projects if item.get("confirmed")):
            return "Аналоги подтверждены, но индекс пока не вернул пригодные наблюдения цены за м²"
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))
