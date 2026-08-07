from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .yandex_search import SearchDoc, YandexSearchClient


_PRICE_M2_RE = re.compile(
    r"(?<!\d)(\d{2,3}(?:[\s\u00a0\u202f]\d{3}){1,2}|\d{5,7})\s*(?:₽|руб\.?)\s*/?\s*м(?:²|2)",
    flags=re.I,
)
_OFFERS_RE = re.compile(
    r"(?<!\d)(\d{1,4})\s+(?:квартир(?:а|ы)?|предложени(?:е|я|й)|объявлени(?:е|я|й))\b",
    flags=re.I,
)


@dataclass(frozen=True)
class PriceObservation:
    price_per_sqm: int
    source: str
    url: str
    title: str


class MarketPriceEnricher:
    """Extract asking-price observations from Yandex-indexed market pages.

    This intentionally does not call undocumented Domclick/portal endpoints. Search results are
    cached by YandexSearchClient, and every number returned to the UI keeps its source URL.
    """

    def __init__(self, search: YandexSearchClient):
        self.search = search

    def project_price(self, project_name: str, locality: str) -> dict[str, Any]:
        queries = [
            f'site:domclick.ru "{project_name}" {locality} "₽/м²"',
            f'site:realty.yandex.ru "{project_name}" {locality} новостройка',
        ]
        docs: list[SearchDoc] = []
        seen_urls: set[str] = set()
        for query in queries:
            for doc in self.search.search(query, groups_on_page=10):
                if doc.url in seen_urls:
                    continue
                seen_urls.add(doc.url)
                docs.append(doc)

        observations: list[PriceObservation] = []
        offers: list[int] = []
        for doc in docs:
            text = " ".join(part for part in (doc.title, doc.snippet) if part)
            if not self._mentions_project(text, project_name):
                continue
            source = self._source_name(doc)
            for raw in _PRICE_M2_RE.findall(text):
                value = self._to_int(raw)
                if 80_000 <= value <= 5_000_000:
                    observations.append(
                        PriceObservation(
                            price_per_sqm=value,
                            source=source,
                            url=doc.url,
                            title=doc.title,
                        )
                    )
            for raw_count in _OFFERS_RE.findall(text):
                try:
                    count = int(raw_count)
                except ValueError:
                    continue
                if 0 < count <= 5000:
                    offers.append(count)

        observations = self._dedupe_observations(observations)
        values = [item.price_per_sqm for item in observations]
        if not values:
            return {
                "available": False,
                "method": "indexed_asking_prices",
                "queries": queries,
                "observations": [],
                "offers_count": max(offers) if offers else None,
            }

        median = int(round(statistics.median(values)))
        sources = []
        seen_source_urls: set[str] = set()
        for item in observations:
            if item.url in seen_source_urls:
                continue
            seen_source_urls.add(item.url)
            sources.append(
                {
                    "source": item.source,
                    "url": item.url,
                    "title": item.title,
                }
            )

        return {
            "available": True,
            "method": "indexed_asking_prices",
            "price_per_sqm": median,
            "min_price_per_sqm": min(values),
            "max_price_per_sqm": max(values),
            "observation_count": len(values),
            "offers_count": max(offers) if offers else None,
            "sources": sources[:5],
            "observations": [
                {
                    "price_per_sqm": item.price_per_sqm,
                    "source": item.source,
                    "url": item.url,
                }
                for item in observations[:20]
            ],
            "note": "Индексируемые цены предложения; не цены фактических сделок",
        }

    @staticmethod
    def _mentions_project(text: str, project_name: str) -> bool:
        return MarketPriceEnricher._compact(project_name) in MarketPriceEnricher._compact(text)

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[^a-zа-яё0-9]+", "", str(value or "").lower().replace("ё", "е"))

    @staticmethod
    def _to_int(value: str) -> int:
        return int(re.sub(r"\D", "", value))

    @staticmethod
    def _source_name(doc: SearchDoc) -> str:
        try:
            host = (urlsplit(doc.url).hostname or "").lower()
        except ValueError:
            host = (doc.domain or "").lower()
        if "domclick.ru" in host:
            return "Домклик"
        if "realty.yandex.ru" in host:
            return "Яндекс Недвижимость"
        return doc.domain or host or "Рыночный источник"

    @staticmethod
    def _dedupe_observations(items: list[PriceObservation]) -> list[PriceObservation]:
        result: list[PriceObservation] = []
        seen: set[tuple[int, str]] = set()
        for item in items:
            key = (item.price_per_sqm, item.url)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result


def weighted_market_price(projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Distance-weighted mean for confirmed analogues with observable asking prices."""
    rows: list[tuple[float, int, str]] = []
    for project in projects:
        if not project.get("confirmed"):
            continue
        price = project.get("market_price") or {}
        if not price.get("available") or not price.get("price_per_sqm"):
            continue
        distance = max(float(project.get("distance_km") or 0.25), 0.25)
        rows.append((1.0 / distance, int(price["price_per_sqm"]), str(project.get("name") or "")))
    if not rows:
        return None
    total_weight = sum(weight for weight, _, _ in rows)
    weighted = int(round(sum(weight * value for weight, value, _ in rows) / total_weight))
    return {
        "price_per_sqm": weighted,
        "analogue_count": len(rows),
        "method": "inverse_distance_weighted_asking_price",
        "projects": [name for _, _, name in rows],
        "note": "Ориентир по ценам предложения подтверждённых аналогов; не цена сделки",
    }
