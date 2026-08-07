from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json


_OFFICIAL_HOST = "xn--80az8a.xn--d1aqf.xn--p1ai"
_SEARCH_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"
_GENERIC_TITLES = {
    "новостройки",
    "новостройки москвы",
    "жилые комплексы",
    "жилые комплексы москвы",
    "квартиры в новостройках",
}
_LISTING_PREFIXES = (
    "купить ",
    "продажа ",
    "продается ",
    "продаётся ",
    "снять ",
    "аренда ",
    "квартира ",
    "апартаменты ",
    "студия ",
)
_COMMERCIAL_PROJECT_RE = re.compile(
    r"\b(?:бц|бизнес[-\s]?центр|деловой\s+центр|офисн(?:ый|ое|ого|ом|ые|ых)\s+(?:центр|здание|комплекс)|"
    r"коммерческая\s+недвижимость|office\s+center|business\s+center)\b",
    flags=re.I,
)
_APART_PROJECT_RE = re.compile(
    r"\b(?:апарт[-\s]?(?:отель|комплекс)|комплекс\s+апартаментов|апартаменты)\b",
    flags=re.I,
)
_SECONDARY_RE = re.compile(
    r"\b(?:вторичн(?:ая|ое|ый|ом|ого|ые|ых)|вторичный\s+рынок|перепродаж[аи])\b",
    flags=re.I,
)
_COMPLETED_RE = re.compile(
    r"\b(?:дом\s+сдан|сдан(?:ный|а|о|ы)?|введ[её]н\s+в\s+эксплуатацию|готовый\s+дом)\b",
    flags=re.I,
)
_ACTIVE_PRIMARY_RE = re.compile(
    r"\b(?:от\s+застройщика|строит(?:ся|ельство)|срок\s+сдачи|старт\s+продаж|в\s+продаже|дду|новостройк)\b",
    flags=re.I,
)


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
    """Current Yandex Search API v2 synchronous Web Search client."""

    def __init__(self, data_dir: Path):
        self.cache_dir = data_dir / "yandex_search"
        self.api_key = os.getenv("YANDEX_SEARCH_API_KEY", "").strip()
        self.folder_id = os.getenv("YANDEX_SEARCH_FOLDER_ID", "").strip()
        self.cache_ttl = int(os.getenv("MARKET_SEARCH_CACHE_TTL_SECONDS", "86400"))
        self.endpoint = os.getenv("YANDEX_SEARCH_ENDPOINT", _SEARCH_ENDPOINT).strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.folder_id)

    def search(self, query: str, *, groups_on_page: int = 10) -> list[SearchDoc]:
        query = " ".join(str(query or "").split())
        if not self.configured:
            raise RemoteServiceError(
                "Yandex Search API не настроен: нужны YANDEX_SEARCH_API_KEY и YANDEX_SEARCH_FOLDER_ID"
            )
        if not self.api_key.isascii():
            raise RemoteServiceError(
                "YANDEX_SEARCH_API_KEY содержит посторонние Unicode-символы. "
                "Скопируйте полный API-ключ из Yandex Cloud заново и пересохраните .env"
            )
        if not self.folder_id.isascii():
            raise RemoteServiceError(
                "YANDEX_SEARCH_FOLDER_ID содержит посторонние символы; пересохраните идентификатор каталога"
            )
        if not query:
            return []

        groups = max(1, min(int(groups_on_page), 100))
        cache_key = hashlib.sha256(f"v2:{groups}:{query}".encode("utf-8")).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        cached = load_json(cache_path) if fresh(cache_path, self.cache_ttl) else None
        if isinstance(cached, list):
            return [SearchDoc(**item) for item in cached if isinstance(item, dict)]

        request_body = {
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": query,
                "familyMode": "FAMILY_MODE_MODERATE",
                "page": "0",
                "fixTypoMode": "FIX_TYPO_MODE_ON",
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_DEEP",
                "groupsOnPage": str(groups),
                "docsInGroup": "1",
            },
            "maxPassages": "3",
            "region": "225",
            "l10N": "LOCALIZATION_RU",
            "folderId": self.folder_id,
            "responseFormat": "FORMAT_XML",
            "userAgent": "DevelopAid-Market-Discovery/0.4",
        }
        body = request_bytes(
            self.endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            timeout=35,
            retries=2,
            headers={
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        xml_body = self._decode_rest_response(body)
        docs = self._parse_response(xml_body)
        save_json(cache_path, [doc.to_dict() for doc in docs])
        return docs

    @staticmethod
    def _decode_rest_response(body: bytes) -> bytes:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteServiceError("Yandex Search API вернул некорректный JSON") from exc

        if not isinstance(payload, dict):
            raise RemoteServiceError("Yandex Search API вернул неожиданный формат ответа")
        raw_data = payload.get("rawData")
        if not raw_data:
            message = payload.get("message") or payload.get("error") or payload.get("code")
            if message:
                raise RemoteServiceError(f"Yandex Search API: {message}")
            raise RemoteServiceError("Yandex Search API не вернул rawData")
        try:
            return base64.b64decode(raw_data, validate=True)
        except (ValueError, TypeError) as exc:
            raise RemoteServiceError("Yandex Search API вернул повреждённый rawData") from exc

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
            try:
                hostname = urlsplit(url).hostname or ""
            except ValueError:
                hostname = ""
            domain = cls._element_text(doc.find("domain")) or hostname
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
    """Extract named active residential-primary projects, never listings, apartments or offices."""
    found: dict[str, dict[str, Any]] = {}
    for doc in docs:
        if not _looks_like_residential_primary_doc(doc):
            continue

        text = " ".join(part for part in (doc.title, doc.snippet) if part)
        names: list[str] = []
        patterns = (
            r"\bЖК\s+[«\"']?([^|—–\n]{2,70}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+(?:Москве|Московской области)|\s+от\s+застройщика))",
            r"\bжил(?:ой|ого)\s+комплекс(?:а)?\s+[«\"']?([^|—–\n]{2,70}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+(?:Москве|Московской области)|\s+от\s+застройщика))",
        )
        for pattern in patterns:
            names.extend(match.group(1) for match in re.finditer(pattern, text, flags=re.I))

        try:
            split = urlsplit(doc.url)
            host = (split.hostname or "").lower()
            path = split.path.lower()
        except ValueError:
            host = ""
            path = ""

        # Domclick search results include both project pages and thousands of flat listings.
        # A title-only fallback is allowed exclusively for an explicit project URL.
        if "domclick.ru" in host and re.search(r"/(?:complex|complexes)/", path):
            prefix = re.split(r"\s+[—–|]\s+|\s+-\s+", doc.title, maxsplit=1)[0]
            prefix = re.sub(r"^(?:ЖК|жилой комплекс)\s+", "", prefix, flags=re.I)
            if 2 < len(prefix) <= 70:
                names.append(prefix)

        for raw_name in names:
            name = clean_project_name(raw_name)
            if not _looks_like_project_name(name):
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


def _looks_like_residential_primary_doc(doc: SearchDoc) -> bool:
    title = " ".join(str(doc.title or "").split())
    text = " ".join(part for part in (doc.title, doc.snippet) if part)

    # A project explicitly presented as offices/business centre is not a housing analogue.
    if _COMMERCIAL_PROJECT_RE.search(title):
        return False
    if _COMMERCIAL_PROJECT_RE.search(text) and not re.search(r"\b(?:жилой\s+комплекс|жилой\s+дом|квартир[а-я]*)\b", text, flags=re.I):
        return False

    # Apartment/hotel projects are legally and economically different from an apartment house.
    if _APART_PROJECT_RE.search(title):
        return False
    if _APART_PROJECT_RE.search(text) and not re.search(r"\bквартир[а-я]*\b", text, flags=re.I):
        return False

    # Explicit secondary-market pages never form the development-primary comparable set.
    if _SECONDARY_RE.search(text):
        return False

    # A completed old building is retained only if the same result explicitly shows active
    # primary-market/developer sales; otherwise it is stale stock/resale rather than competition.
    if _COMPLETED_RE.search(text) and not _ACTIVE_PRIMARY_RE.search(text):
        return False

    return True


def _looks_like_project_name(value: str) -> bool:
    name = clean_project_name(value)
    low = name.lower()
    if not name or low in _GENERIC_TITLES:
        return False
    if any(low.startswith(prefix) for prefix in _LISTING_PREFIXES):
        return False
    if re.match(r"^(?:ул\.?|улица|проспект|проезд|шоссе|наб\.?|набережная)\b", low):
        return False
    # Bare postal/address titles such as "Башиловская улица, 23 к4" are not projects.
    if re.search(r"\b(?:улица|ул\.?|проспект|проезд|шоссе|набережная|наб\.?)\b", low) and re.search(
        r"\b\d+[а-яa-z0-9/\-]*\b", low
    ):
        return False
    if re.search(r"\b(?:\d+[,.]?\d*)\s*м[²2]\b", low):
        return False
    return 2 < len(name) <= 70


def clean_project_name(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = value.strip(" \t\r\n«»\"'()[]")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s+(?:Москва|в Москве|официальный сайт|новостройка)$", "", value, flags=re.I)
    return value.strip(" ,.;:—–-«»\"'")


def official_cards_from_docs(docs: list[SearchDoc]) -> list[dict[str, Any]]:
    """Return only concrete EISZhS construction-object cards with a stable numeric id."""
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for doc in docs:
        try:
            split = urlsplit(doc.url)
            host = (split.hostname or "").encode("idna").decode("ascii").lower()
            path = unquote(split.path)
        except (ValueError, UnicodeError):
            continue
        if host != _OFFICIAL_HOST:
            continue

        object_match = re.search(r"/(\d{4,12})(?:/)?$", path)
        if object_match is None:
            continue
        object_id = int(object_match.group(1))
        if object_id in seen:
            continue
        seen.add(object_id)
        result.append(
            {
                "object_id": object_id,
                "title": doc.title,
                "url": doc.url,
                "snippet": doc.snippet,
                "source": "Наш.Дом.РФ / ЕИСЖС",
            }
        )
    return result
