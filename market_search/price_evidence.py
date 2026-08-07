"""Цена и экспозиция — только при доказанной привязке к сущности.

v5 брал любое число «₽/м²» из любого документа, где встретилось название, и это
включало районные каталоги, где в одном сниппете идут цены пяти разных ЖК. Так
цена одного проекта уезжала другому, а «экспозиция» вообще собиралась как
максимум любого «N квартир» по всем документам подряд.

Здесь наблюдение принимается, если документ — карточка проекта у известного
агрегатора и он опознан как карточка *этого* проекта: совпал внешний
идентификатор либо название в заголовке. Всё остальное уходит в отбракованные с
причиной, а не в медиану.

Экспозиция считается отдельно и честно: если точного числа нет, возвращается
`units=None, quality="unknown"`, а не переиспользованное число из чужого сниппета.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

from .documents import PROJECT_PAGE, classify_document, is_pricing_source
from .http import RemoteServiceError
from .normalize import canonical_key, cut_at_separator, name_similarity
from .price import _PRICE_M2_RE, MarketPriceEnricher
from .yandex_search import SearchDoc, YandexSearchClient


_MIN_PRICE = 80_000
_MAX_PRICE = 5_000_000

_INVENTORY_RE = re.compile(
    r"(?:в\s+продаже\s+)?(?<!\d)(\d{1,4})\s+(?:квартир[а-я]*|лот[а-ов]*|предложени[йея])\b"
    r"|\b(?:квартир|лотов|предложений)\s*[:—-]?\s*(\d{1,4})\b",
    flags=re.I,
)
_SECONDARY_RE = re.compile(r"\bвторичн(?:ая|ое|ый|ого|ые|ых)\b|\bперепродаж[аи]\b", flags=re.I)
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-я]*\s+(\d{4})",
    flags=re.I,
)
_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "май": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

MATCH_EXTERNAL_ID = "external_id"
MATCH_TITLE = "project_page_title"
MATCH_NONE = "unverified"


@dataclass(frozen=True)
class PriceObservation:
    price_per_sqm: int
    source: str
    url: str
    title: str
    method: str
    match: str
    observed_at: str | None

    @property
    def quality(self) -> str:
        return "high" if self.match == MATCH_EXTERNAL_ID else "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_per_sqm": self.price_per_sqm,
            "source": self.source,
            "url": self.url,
            "method": self.method,
            "match": self.match,
            "observed_at": self.observed_at,
            "quality": self.quality,
        }


def observed_date(text: str) -> str | None:
    match = _DATE_RE.search(str(text or ""))
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def document_matches_entity(entity, doc: SearchDoc) -> str:
    """Как именно документ доказан принадлежащим сущности."""
    ref = classify_document(doc.url, doc.title, doc.snippet)
    if not is_pricing_source(ref):
        return MATCH_NONE
    if ref.external_id and ref.external_id in entity.external_ids:
        return MATCH_EXTERNAL_ID
    title_name = cut_at_separator(doc.title)
    if not title_name:
        return MATCH_NONE
    names = [entity.canonical_name, *entity.aliases]
    for name in names:
        if not name:
            continue
        if canonical_key(title_name) == canonical_key(name):
            return MATCH_TITLE
        if name_similarity(title_name, name) >= 0.92:
            return MATCH_TITLE
    return MATCH_NONE


class VerifiedPriceEnricher:
    def __init__(self, search: YandexSearchClient, *, today: date | None = None):
        self.search = search
        self.today = today or date.today()

    def collect(self, entity, locality: str) -> dict[str, Any]:
        name = entity.canonical_name
        queries = [
            f'site:cian.ru "{name}" {locality} ЖК цены',
            f'site:realty.yandex.ru "{name}" {locality} новостройка цена',
            f'site:domclick.ru "{name}" {locality} ЖК цена',
            f'site:novostroy.ru "{name}" {locality} цены',
        ]
        docs: list[SearchDoc] = []
        seen: set[str] = set()
        errors: list[str] = []
        for query in queries:
            try:
                found = self.search.search(query, groups_on_page=10)
            except RemoteServiceError as exc:
                errors.append(str(exc))
                continue
            for doc in found:
                if doc.url in seen:
                    continue
                seen.add(doc.url)
                docs.append(doc)

        # Карточки самой сущности уже есть в выдаче discovery — их тоже
        # используем, повторный запрос за ними не нужен.
        for candidate in entity.candidates:
            if candidate.source_kind != PROJECT_PAGE or candidate.source_url in seen:
                continue
            seen.add(candidate.source_url)
            docs.append(
                SearchDoc(
                    title=candidate.source_title,
                    url=candidate.source_url,
                    domain=candidate.source_domain,
                    snippet=candidate.source_snippet,
                    rank=candidate.search_rank,
                )
            )

        observations: list[PriceObservation] = []
        rejected: list[dict[str, Any]] = []
        inventory: dict[str, Any] | None = None

        for doc in docs:
            text = " ".join(part for part in (doc.title, doc.snippet) if part)
            match = document_matches_entity(entity, doc)
            if match == MATCH_NONE:
                if _PRICE_M2_RE.search(text):
                    rejected.append({"url": doc.url, "reason": "entity_match_not_proven"})
                continue
            if _SECONDARY_RE.search(text):
                rejected.append({"url": doc.url, "reason": "secondary_market"})
                continue

            source = MarketPriceEnricher._source_name(doc)
            when = observed_date(text)
            for value in self._prices(text):
                observations.append(
                    PriceObservation(
                        price_per_sqm=value,
                        source=source,
                        url=doc.url,
                        title=doc.title,
                        method="explicit_per_sqm",
                        match=match,
                        observed_at=when,
                    )
                )
            if inventory is None:
                inventory = self._inventory(text, source, doc.url, match, when)

        observations = self._dedupe(observations)
        price = self._summarize(observations, queries, errors, rejected)
        return {
            "price": price,
            "inventory": inventory or self._unknown_inventory(),
            "rejected_observations": rejected[:10],
        }

    @staticmethod
    def _prices(text: str) -> list[int]:
        values: list[int] = []
        for match in _PRICE_M2_RE.finditer(text):
            value = MarketPriceEnricher._price_m2_match_to_int(match)
            if _MIN_PRICE <= value <= _MAX_PRICE:
                values.append(value)
        return values

    @staticmethod
    def _dedupe(items: list[PriceObservation]) -> list[PriceObservation]:
        seen: set[tuple[int, str]] = set()
        out: list[PriceObservation] = []
        for item in items:
            key = (item.price_per_sqm, item.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _summarize(
        self,
        observations: list[PriceObservation],
        queries: list[str],
        errors: list[str],
        rejected: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not observations:
            return {
                "available": False,
                "verified": False,
                "basis": "none",
                "reason": (
                    "Ни одно ценовое наблюдение не подтверждено принадлежностью проекту"
                    if rejected
                    else "Цена предложения не найдена в проиндексированных карточках проекта"
                ),
                "rejected_count": len(rejected),
                "queries": queries,
                "errors": errors[:3],
            }
        values = [item.price_per_sqm for item in observations]
        dates = sorted(item.observed_at for item in observations if item.observed_at)
        best = "high" if any(item.match == MATCH_EXTERNAL_ID for item in observations) else "medium"
        return {
            "available": True,
            "verified": True,
            "basis": "verified_project_page_asking",
            "price_per_sqm": int(round(statistics.median(values))),
            "price_per_sqm_min": min(values),
            "price_per_sqm_max": max(values),
            "price_per_sqm_avg": int(round(statistics.fmean(values))),
            "price_per_sqm_median": int(round(statistics.median(values))),
            "sample_count": len(values),
            "sources": sorted({item.source for item in observations}),
            "observed_at": dates[-1] if dates else None,
            "retrieved_at": self.today.isoformat(),
            "quality": best,
            "observations": [item.to_dict() for item in observations[:20]],
            "note": "Цены предложения с карточек проекта; не цены сделок",
        }

    @staticmethod
    def _unknown_inventory() -> dict[str, Any]:
        return {
            "units": None,
            "source": None,
            "observed_at": None,
            "quality": "unknown",
            "note": "Экспозиция не извлекается достоверно из поискового индекса",
        }

    def _inventory(
        self, text: str, source: str, url: str, match: str, when: str | None
    ) -> dict[str, Any] | None:
        found = _INVENTORY_RE.search(text)
        if not found:
            return None
        raw = found.group(1) or found.group(2)
        try:
            units = int(raw)
        except (TypeError, ValueError):
            return None
        if not 0 < units <= 5000:
            return None
        return {
            "units": units,
            "source": source,
            "url": url,
            "observed_at": when,
            "retrieved_at": self.today.isoformat(),
            "quality": "reported" if match == MATCH_EXTERNAL_ID else "low",
            "note": "Число лотов из сниппета карточки проекта; требует проверки на сайте источника",
        }
