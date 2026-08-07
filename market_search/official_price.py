from __future__ import annotations

import html
import re
import statistics
from typing import Any
from urllib.parse import unquote, urlsplit

from .http import RemoteServiceError, request_bytes
from .yandex_search import SearchDoc, YandexSearchClient

_OFFICIAL_HOST = "xn--80az8a.xn--d1aqf.xn--p1ai"
_LABEL_PRICE_RE = re.compile(
    r"средн(?:яя|ей)\s+цена\s+за\s+1\s*(?:м(?:²|2)|кв\.?\s*м)"
    r"[^0-9]{0,100}(?P<value>\d{2,3}(?:[\s\u00a0\u202f]\d{3}){1,2}|\d{5,7}|\d{2,4}(?:[.,]\d{1,2})?)"
    r"\s*(?P<thousand>тыс\.?)?\s*(?:₽|руб\.?)",
    flags=re.I,
)
_PRICE_M2_RE = re.compile(
    r"(?<!\d)(?P<value>\d{2,3}(?:[\s\u00a0\u202f]\d{3}){1,2}|\d{5,7}|\d{2,4}(?:[.,]\d{1,2})?)\s*"
    r"(?P<thousand>тыс\.?)?\s*(?:₽|руб\.?)\s*/?\s*м(?:²|2)",
    flags=re.I,
)


class OfficialPriceEnricher:
    """Read the official average price exposed on public Наш.Дом.РФ project cards.

    No private EISZhS API is used. Public card HTML is attempted first; Yandex Search index is
    used as a fallback. Only URLs of already matched official cards are accepted when possible.
    """

    def __init__(self, search: YandexSearchClient):
        self.search = search

    def project_price(
        self,
        project_name: str,
        locality: str,
        cards: list[dict[str, Any]],
    ) -> dict[str, Any]:
        card_ids = {
            int(card["object_id"])
            for card in cards
            if card.get("object_id") is not None and str(card.get("object_id")).isdigit()
        }
        observations: list[dict[str, Any]] = []

        # First parse text already returned with official search cards.
        for card in cards:
            text = " ".join(str(card.get(key) or "") for key in ("title", "snippet"))
            for value in self._extract_prices(text):
                observations.append(
                    {
                        "price_per_sqm": value,
                        "url": str(card.get("url") or ""),
                        "object_id": card.get("object_id"),
                        "method": "official_card_search_snippet",
                    }
                )

        # Public card pages are allowed; the blocked private /api/ endpoint is never called.
        for card in cards[:6]:
            url = str(card.get("url") or "")
            if not url:
                continue
            try:
                raw = request_bytes(url, timeout=15, retries=0)
            except RemoteServiceError:
                continue
            text = self._html_to_text(raw)
            for value in self._extract_prices(text):
                observations.append(
                    {
                        "price_per_sqm": value,
                        "url": url,
                        "object_id": card.get("object_id"),
                        "method": "official_public_card_html",
                    }
                )

        # Search-index fallback is important for JS-rendered card pages.
        queries = [
            f'site:наш.дом.рф "{project_name}" {locality} "Средняя цена за 1 м²"',
            f'site:наш.дом.рф "{project_name}" {locality} "цена за 1 м²"',
        ]
        for query in queries:
            try:
                docs = self.search.search(query, groups_on_page=12)
            except RemoteServiceError:
                continue
            for doc in docs:
                if not self._is_allowed_official_doc(doc, project_name, card_ids):
                    continue
                text = " ".join(part for part in (doc.title, doc.snippet) if part)
                for value in self._extract_prices(text):
                    observations.append(
                        {
                            "price_per_sqm": value,
                            "url": doc.url,
                            "object_id": self._object_id_from_url(doc.url),
                            "method": "official_search_index",
                        }
                    )

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()
        for row in observations:
            value = int(row["price_per_sqm"])
            if not 80_000 <= value <= 5_000_000:
                continue
            key = (value, str(row.get("url") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)

        if not deduped:
            return {
                "available": False,
                "method": "official_domrf_average",
                "queries": queries,
                "observations": [],
            }

        values = [int(row["price_per_sqm"]) for row in deduped]
        return {
            "available": True,
            "method": "official_domrf_average",
            "price_per_sqm": int(round(statistics.median(values))),
            "min_price_per_sqm": min(values),
            "max_price_per_sqm": max(values),
            "observation_count": len(values),
            "observations": deduped[:20],
            "source": "Наш.Дом.РФ",
            "note": "Официальная средняя цена за 1 м² из публичной карточки проекта",
        }

    @classmethod
    def _extract_prices(cls, value: str) -> list[int]:
        text = html.unescape(str(value or "")).replace("\\u00a0", " ").replace("\\u202f", " ")
        result: list[int] = []
        for pattern in (_LABEL_PRICE_RE, _PRICE_M2_RE):
            for match in pattern.finditer(text):
                raw = match.group("value").replace("\u00a0", " ").replace("\u202f", " ").strip()
                if match.group("thousand"):
                    numeric = float(raw.replace(" ", "").replace(",", "."))
                    price = int(round(numeric * 1000))
                else:
                    price = int(re.sub(r"\D", "", raw))
                if 80_000 <= price <= 5_000_000:
                    result.append(price)
        return result

    @staticmethod
    def _html_to_text(raw: bytes) -> str:
        text = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(html.unescape(text).split())

    @classmethod
    def _is_allowed_official_doc(
        cls,
        doc: SearchDoc,
        project_name: str,
        card_ids: set[int],
    ) -> bool:
        try:
            host = (urlsplit(doc.url).hostname or "").encode("idna").decode("ascii").lower()
        except (ValueError, UnicodeError):
            return False
        if host != _OFFICIAL_HOST:
            return False
        object_id = cls._object_id_from_url(doc.url)
        if object_id is not None and object_id in card_ids:
            return True
        return cls._mentions_project(" ".join((doc.title, doc.snippet)), project_name)

    @staticmethod
    def _object_id_from_url(url: str) -> int | None:
        try:
            path = unquote(urlsplit(url).path)
        except ValueError:
            return None
        match = re.search(r"/(\d{4,12})(?:/)?$", path)
        return int(match.group(1)) if match else None

    @classmethod
    def _mentions_project(cls, text: str, project_name: str) -> bool:
        hay = re.sub(r"[^a-zа-яё0-9]+", "", str(text or "").lower().replace("ё", "е"))
        needle = re.sub(r"[^a-zа-яё0-9]+", "", str(project_name or "").lower().replace("ё", "е"))
        return len(needle) >= 4 and needle in hay
