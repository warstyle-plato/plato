from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .yandex_search import SearchDoc, YandexSearchClient


_PRICE_M2_RE = re.compile(
    r"(?<!\d)(?P<value>\d{2,3}(?:[\s\u00a0\u202f]\d{3}){1,2}|\d{5,7}|\d{2,4}(?:[.,]\d{1,2})?)\s*"
    r"(?P<thousand>тыс\.?)?\s*(?:₽|руб\.?)\s*/?\s*м(?:²|2)",
    flags=re.I,
)
_OFFERS_RE = re.compile(
    r"(?<!\d)(\d{1,4})\s+(?:квартир(?:а|ы)?|предложени(?:е|я|й)|объявлени(?:е|я|й))\b",
    flags=re.I,
)
_AREA_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:м²|м2|кв\.?\s*м)", flags=re.I)
_TOTAL_MLN_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{1,2})?)\s*млн\.?\s*(?:₽|руб\.?)", flags=re.I)
_TOTAL_RUB_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[\s\u00a0\u202f]\d{3}){2})\s*(?:₽|руб\.?)",
    flags=re.I,
)
_ROMAN_OR_NUMBER = re.compile(r"^(?:[ivxlcdm]+|\d+)$", flags=re.I)


@dataclass(frozen=True)
class PriceObservation:
    price_per_sqm: int
    source: str
    url: str
    title: str
    method: str = "explicit_per_sqm"


class MarketPriceEnricher:
    """Extract asking-price observations from Yandex-indexed market pages.

    No undocumented portal endpoints are called. Every figure returned to the UI keeps the
    indexed source URL. When a page exposes total price and area but not price per sqm, the
    latter is derived from those two values.
    """

    def __init__(self, search: YandexSearchClient):
        self.search = search

    def project_price(self, project_name: str, locality: str) -> dict[str, Any]:
        queries = [
            f'site:cian.ru "{project_name}" {locality} "цена за м²"',
            f'site:cian.ru "{project_name}" {locality} ЖК квартиры',
            f'site:domclick.ru "{project_name}" {locality} квартира цена м²',
            f'site:realty.yandex.ru "{project_name}" {locality} новостройка цена',
        ]
        docs: list[SearchDoc] = []
        seen_urls: set[str] = set()
        for query in queries:
            for doc in self.search.search(query, groups_on_page=12):
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

            for match in _PRICE_M2_RE.finditer(text):
                value = self._price_m2_match_to_int(match)
                if 80_000 <= value <= 5_000_000:
                    observations.append(
                        PriceObservation(
                            price_per_sqm=value,
                            source=source,
                            url=doc.url,
                            title=doc.title,
                            method="explicit_per_sqm",
                        )
                    )

            for value in self._derived_prices_from_area_and_total(text):
                if 80_000 <= value <= 5_000_000:
                    observations.append(
                        PriceObservation(
                            price_per_sqm=value,
                            source=source,
                            url=doc.url,
                            title=doc.title,
                            method="derived_total_div_area",
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
            "sources": sources[:8],
            "observations": [
                {
                    "price_per_sqm": item.price_per_sqm,
                    "source": item.source,
                    "url": item.url,
                    "method": item.method,
                }
                for item in observations[:30]
            ],
            "note": "Индексируемые цены предложения; не цены фактических сделок",
        }

    @classmethod
    def _mentions_project(cls, text: str, project_name: str) -> bool:
        text_tokens = cls._words(text)
        name_tokens = cls._words(project_name)
        if not name_tokens or len(name_tokens) > len(text_tokens):
            return False
        name_has_suffix = bool(_ROMAN_OR_NUMBER.fullmatch(name_tokens[-1]))
        for index in range(len(text_tokens) - len(name_tokens) + 1):
            if text_tokens[index:index + len(name_tokens)] != name_tokens:
                continue
            next_index = index + len(name_tokens)
            if not name_has_suffix and next_index < len(text_tokens):
                next_token = text_tokens[next_index]
                if _ROMAN_OR_NUMBER.fullmatch(next_token):
                    # "Петровский парк" must not silently absorb "Петровский парк II".
                    continue
            return True
        return False

    @staticmethod
    def _words(value: str) -> list[str]:
        return re.findall(r"[a-zа-яё0-9]+", str(value or "").lower().replace("ё", "е"))

    @staticmethod
    def _price_m2_match_to_int(match: re.Match[str]) -> int:
        raw = match.group("value").replace("\u00a0", " ").replace("\u202f", " ").strip()
        if match.group("thousand"):
            numeric = float(raw.replace(" ", "").replace(",", "."))
            return int(round(numeric * 1000))
        return int(re.sub(r"\D", "", raw))

    @classmethod
    def _derived_prices_from_area_and_total(cls, text: str) -> list[int]:
        areas: list[tuple[int, float]] = []
        totals: list[tuple[int, int]] = []
        for match in _AREA_RE.finditer(text):
            try:
                area = float(match.group(1).replace(",", "."))
            except ValueError:
                continue
            if 15 <= area <= 500:
                areas.append((match.start(), area))
        for match in _TOTAL_MLN_RE.finditer(text):
            try:
                total = int(round(float(match.group(1).replace(",", ".")) * 1_000_000))
            except ValueError:
                continue
            if 3_000_000 <= total <= 1_500_000_000:
                totals.append((match.start(), total))
        for match in _TOTAL_RUB_RE.finditer(text):
            total = int(re.sub(r"\D", "", match.group(1)))
            if 3_000_000 <= total <= 1_500_000_000:
                totals.append((match.start(), total))

        derived: list[int] = []
        used_pairs: set[tuple[int, int]] = set()
        for area_pos, area in areas:
            nearby = sorted(
                ((abs(total_pos - area_pos), total_pos, total) for total_pos, total in totals),
                key=lambda row: row[0],
            )
            for distance, total_pos, total in nearby:
                if distance > 180:
                    break
                pair = (area_pos, total_pos)
                if pair in used_pairs:
                    continue
                used_pairs.add(pair)
                value = int(round(total / area))
                if 80_000 <= value <= 5_000_000:
                    derived.append(value)
                    break
        return derived

    @staticmethod
    def _source_name(doc: SearchDoc) -> str:
        try:
            host = (urlsplit(doc.url).hostname or "").lower()
        except ValueError:
            host = (doc.domain or "").lower()
        if "cian.ru" in host:
            return "ЦИАН"
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
