from __future__ import annotations

from pathlib import Path
from typing import Any

from .candidates_v5 import extract_project_candidates_v5
from .geocoder import GeoPoint
from .http import RemoteServiceError
from .recommendation import market_recommendation
from .service import MarketDiscoveryService as LegacyMarketDiscoveryService, haversine_km
from .yandex_search import official_cards_from_docs


class MarketDiscoveryService(LegacyMarketDiscoveryService):
    """Market discovery v5.

    The v4 mistake was using an official EISZhS card as a hard gate. v5 separates
    discovery, geography, market enrichment and official confirmation. A project can
    therefore stay in the comparable set when it is geographically valid and has
    observable primary-market pricing even if Yandex has not indexed its EISZhS card.
    """

    def __init__(self, data_dir: Path):
        super().__init__(data_dir)

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
        seen_urls: set[str] = set()
        for query in queries:
            for doc in self.search.search(query, groups_on_page=15):
                if doc.url in seen_urls:
                    continue
                seen_urls.add(doc.url)
                docs.append(doc)

        candidates = extract_project_candidates_v5(docs)
        projects: list[dict[str, Any]] = []
        max_candidates = min(max(limit * 4, 16), 40)

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
            try:
                official_docs = self.search.search(official_query, groups_on_page=8)
            except RemoteServiceError:
                official_docs = []
            raw_cards = official_cards_from_docs(official_docs)
            cards = [
                card
                for card in raw_cards
                if self._official_card_matches(
                    candidate["name"], address_hint, card, locality=locality
                )
            ]

            try:
                asking_price = self.prices.project_price(candidate["name"], locality)
            except RemoteServiceError as exc:
                asking_price = {
                    "available": False,
                    "method": "indexed_asking_prices",
                    "error": str(exc),
                }

            if cards:
                try:
                    official_price = self.official_prices.project_price(
                        candidate["name"], locality, cards
                    )
                except RemoteServiceError as exc:
                    official_price = {
                        "available": False,
                        "method": "official_domrf_average",
                        "error": str(exc),
                    }
            else:
                official_price = {
                    "available": False,
                    "method": "official_domrf_average",
                    "note": "Официальная карточка через поисковый индекс не найдена",
                }

            price_info = self._combine_price_sources(official_price, asking_price)
            source_domains = {
                str(domain or "").strip().lower()
                for domain in (candidate.get("discovery_sources") or [])
            }
            source_domains.add(str(candidate.get("source_domain") or "").strip().lower())
            for source in asking_price.get("sources") or []:
                name = str(source.get("source") or "").strip().lower()
                if name:
                    source_domains.add(name)
            source_domains.discard("")

            priced = bool(price_info.get("available") and price_info.get("price_per_sqm"))
            confirmed = bool(cards)
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
                    "market_source_count": max(len(source_domains), 1),
                    "extraction_evidence": candidate.get("extraction_evidence"),
                    "official_cards": cards,
                    "confirmed": confirmed,
                    "eligible_analogue": priced,
                    "evidence": (
                        "official_and_market"
                        if confirmed and priced
                        else "official_only"
                        if confirmed
                        else "market_only"
                        if priced
                        else "discovery_only"
                    ),
                    "confirmation": (
                        "Карточка Наш.Дом.РФ сопоставлена по проекту и географии"
                        if confirmed
                        else "Карточка Наш.Дом.РФ не найдена через индекс; объект не исключается автоматически"
                    ),
                    "market_price": price_info,
                }
            )

        projects.sort(
            key=lambda item: (
                not item.get("eligible_analogue", False),
                item["distance_km"],
                not item["confirmed"],
            )
        )
        projects = projects[:limit]

        confirmed_count = sum(1 for item in projects if item["confirmed"])
        priced_count = sum(1 for item in projects if item.get("eligible_analogue"))
        price_summary = market_recommendation(projects)

        return {
            "query": {
                "address": address,
                "radius_km": radius_km,
                "limit": limit,
                "district": district,
            },
            "location": subject.to_dict(),
            "source": {
                "discovery": "Yandex Search API across indexed market/developer sources",
                "confirmation": "Наш.Дом.РФ / ЕИСЖС через поисковый индекс Яндекса",
                "pricing": "Наш.Дом.РФ + ЦИАН + Домклик + Яндекс Недвижимость",
                "mode": "multi_source_search_v5",
            },
            "projects": projects,
            "count": len(projects),
            "confirmed_count": confirmed_count,
            "priced_count": priced_count,
            "eligible_count": priced_count,
            "price_summary": price_summary,
            "warning": self._warning_v5(projects, price_summary),
            "diagnostics": {
                "search_queries": queries,
                "raw_search_documents": len(docs),
                "project_names_extracted": len(candidates),
                "candidates_geofiltered": len(projects),
            },
        }

    @staticmethod
    def _discovery_queries(address: str, locality: str, district: str | None) -> list[str]:
        clean = " ".join(address.split())
        area = district or clean
        queries = [
            f'новостройки рядом с "{clean}" {locality}',
            f'жилые комплексы "{area}" {locality} от застройщика',
            f'клубный дом "{area}" {locality}',
            f'site:cian.ru новостройки "{area}" {locality}',
            f'site:domclick.ru новостройки "{area}" {locality}',
            f'site:realty.yandex.ru новостройки "{area}" {locality}',
            f'элитные новостройки "{area}" {locality}',
            f'премиальные новостройки "{area}" {locality} девелопер',
        ]
        if district:
            queries.append(f'строящиеся жилые комплексы "{district}" {locality}')
        return queries

    @staticmethod
    def _warning_v5(
        projects: list[dict[str, Any]],
        price_summary: dict[str, Any] | None,
    ) -> str | None:
        if not projects:
            return "В заданном радиусе не найдено проектов, которые удалось уверенно геокодировать"
        if not price_summary:
            return "Проекты найдены, но пригодных рыночных наблюдений цены за м² пока нет"
        confirmed = sum(1 for item in projects if item.get("confirmed"))
        if confirmed == 0:
            return "Рыночные аналоги найдены и оценены; официальные карточки Наш.Дом.РФ через индекс пока не сопоставлены"
        return None
