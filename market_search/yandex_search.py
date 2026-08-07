from __future__ import annotations

import hashlib
import html
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json


_OFFICIAL_HOST = "xn--80az8a.xn--d1aqf.xn--p1ai"
_GENERIC_TITLES = {
    "новостройки",
    "новостройки москвы",
    "жилые комплексы",
    "жилые комплексы москвы",
    "квартиры в новостройках",
}


@dataclass(frozen=True)
class SearchDoc:
    title: str
    url: str
    domain: str
    snippet: str
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class YandexSearchClient:
    """Supported Yandex Search API v1 client. No scraping of Yandex SERP pages."""

    def __init__(self, data_dir: Path):
        self.cache_dir = data_dir / "yandex_search"
        self.api_key = os.getenv("YANDEX_SEARCH_API_KEY", "").strip()
        self.folder_id = os.getenv("YANDEX_SEARCH_FOLDER_ID", "").strip()
        self.cache_ttl = int(os.getenv("MARKET_SEARCH_CACHE_TTL_SECONDS", "86400"))
        self.endpoint = os.getenv("YANDEX_SEARCH_ENDPOINT", "https://yandex.ru/search/xml").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.folder_id)

    def search(self, query: str, *, groups_on_page: int = 10) -> list[SearchDoc]:
        query = " ".join(str(query or "").split())
        if not self.configured:
            raise RemoteServiceError(
                "Yandex Search API не настроен: нужны YANDEX_SEARCH_API_KEY и YANDEX_SEARCH_FOLDER_ID"
            )
        if not query:
            return []

        cache_key = hashlib.sha256(f"{groups_on_page}:{query}".encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        cached = load_json(cache_path) if fresh(cache_path, self.cache_ttl) else None
        if isinstance(cached, list):
            return [SearchDoc(**item) for item in cached if isinstance(item, dict)]

        request_xml = self._request_xml(query, groups_on_page)
        body = request_bytes(
            self.endpoint,
            params={"folderid": self.folder_id, "filter": "moderate", "l10n": "ru"},
            data=request_xml,
            method="POST",
            timeout=35,
            retries=2,
            headers={
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/xml; charset=UTF-8",
                "Accept": "application/xml, text/xml",
            },
        )
        docs = self._parse_response(body)
        save_json(cache_path, [doc.to_dict() for doc in docs])
        return docs

    @staticmethod
    def _request_xml(query: str, groups_on_page: int) -> bytes:
        root = ET.Element("request")
        ET.SubElement(root, "query").text = query
        ET.SubElement(root, "maxpassages").text = "3"
        ET.SubElement(root, "page").text = "0"
        groupings = ET.SubElement(root, "groupings")
        ET.SubElement(
            groupings,
            "groupby",
            {"attr": "d", "mode": "deep", "groups-on-page": str(max(1, min(groups_on_page, 50))), "docs-in-group": "1"},
        )
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @classmethod
    def _parse_response(cls, body: bytes) -> list[SearchDoc]:
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise RemoteServiceError("Yandex Search API вернул некорректный XML") from exc

        error = root.find(".//error")
        if error is not None:
            code = error.attrib.get("code") or "?"
            text = cls._element_text(error) or "неизвестная ошибка"
            raise RemoteServiceError(f"Yandex Search API: {code}: {text}")

        result: list[SearchDoc] = []
        for rank, doc in enumerate(root.findall(".//group/doc"), start=1):
            url = cls._element_text(doc.find("url"))
            if not url:
                continue
            title = cls._element_text(doc.find("title"))
            passages = [cls._element_text(node) for node in doc.findall("./passages/passage")]
            snippet = " ".join(part for part in passages if part)
            domain = cls._element_text(doc.find("domain")) or (urlsplit(url).hostname or "")
            result.append(
                SearchDoc(
                    title=html.unescape(title).strip(),
                    url=html.unescape(url).strip(),
                    domain=domain.lower().strip(),
                    snippet=html.unescape(snippet).strip(),
                    rank=rank,
                )
            )
        return result

    @staticmethod
    def _element_text(node: ET.Element | None) -> str:
        if node is None:
            return ""
        return "".join(node.itertext()).strip()


def extract_project_candidates(docs: list[SearchDoc]) -> list[dict[str, Any]]:
    """Extract named residential projects from normal web-search results."""
    found: dict[str, dict[str, Any]] = {}
    for doc in docs:
        text = " ".join(part for part in (doc.title, doc.snippet) if part)
        names: list[str] = []
        patterns = (
            r"\bЖК\s+[«\"']?([^|—–\n]{2,70}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+(?:Москве|Московской области)|\s+от\s+застройщика))",
            r"\bжил(?:ой|ого)\s+комплекс(?:а)?\s+[«\"']?([^|—–\n]{2,70}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+(?:Москве|Московской области)|\s+от\s+застройщика))",
        )
        for pattern in patterns:
            names.extend(match.group(1) for match in re.finditer(pattern, text, flags=re.I))

        host = (urlsplit(doc.url).hostname or "").lower()
        if "domclick.ru" in host:
            prefix = re.split(r"\s+[—–|]\s+|\s+-\s+", doc.title, maxsplit=1)[0]
            prefix = re.sub(r"^(?:ЖК|жилой комплекс)\s+", "", prefix, flags=re.I)
            if 2 < len(prefix) <= 70:
                names.append(prefix)

        for raw_name in names:
            name = clean_project_name(raw_name)
            if not name or name.lower() in _GENERIC_TITLES:
                continue
            key = re.sub(r"[^a-zа-яё0-9]+", "", name.lower())
            if len(key) < 3:
                continue
            current = found.get(key)
            candidate = {
                "name": name,
                "source_url": doc.url,
                "source_domain": doc.domain or host,
                "source_title": doc.title,
                "source_snippet": doc.snippet,
                "search_rank": doc.rank,
            }
            if current is None or doc.rank < current["search_rank"]:
                found[key] = candidate

    return sorted(found.values(), key=lambda item: item["search_rank"])


def clean_project_name(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = value.strip(" \t\r\n«»\"'()[]")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+(?:Москва|в Москве|официальный сайт|новостройка)$", "", value, flags=re.I)
    return value.strip(" ,.;:—–-")


def official_cards_from_docs(docs: list[SearchDoc]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in docs:
        host = (urlsplit(doc.url).hostname or "").encode("idna").decode("ascii").lower()
        if host != _OFFICIAL_HOST:
            continue
        path = unquote(urlsplit(doc.url).path)
        object_match = re.search(r"/(\d{4,12})(?:/)?$", path)
        object_id = object_match.group(1) if object_match else None
        key = object_id or doc.url
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "object_id": int(object_id) if object_id else None,
                "title": doc.title,
                "url": doc.url,
                "snippet": doc.snippet,
                "source": "Наш.Дом.РФ / ЕИСЖС",
            }
        )
    return result
