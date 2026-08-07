from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .yandex_search import SearchDoc, clean_project_name, extract_project_candidates


_BAD_DOC_RE = re.compile(
    r"\b(?:бизнес[-\s]?центр|office\s+center|апарт[-\s]?(?:отель|комплекс)|вторичный\s+рынок|аренда)\b",
    flags=re.I,
)
_BAD_TITLE_RE = re.compile(
    r"^(?:купить|продажа|прода[её]тся|снять|аренда|квартира|апартаменты|студия)\b",
    flags=re.I,
)


def _key(name: str) -> str:
    normalized = re.sub(
        r"^(?:жк|жилой\s+комплекс|клубный\s+дом|клубный\s+квартал|жилой\s+квартал)\s+",
        "",
        name.lower(),
        flags=re.I,
    )
    return re.sub(r"[^a-zа-яё0-9]+", "", normalized)


def _trusted_project_page(doc: SearchDoc) -> bool:
    try:
        split = urlsplit(doc.url)
    except ValueError:
        return False
    host = (split.hostname or "").lower()
    path = split.path.lower()
    return bool(
        ("realty.yandex.ru" in host and "/novostrojka/" in path)
        or ("domclick.ru" in host and re.search(r"/(?:complex|complexes)/", path))
        or ("cian.ru" in host and (host.startswith("zhk-") or "zhiloy-kompleks" in path or "/novostroyki" in path))
        or ("novostroy.ru" in host and "/buildings/" in path)
    )


def _title_project_name(title: str) -> str | None:
    title = " ".join(str(title or "").split())
    if not title or _BAD_TITLE_RE.search(title):
        return None

    prefix = re.split(r"\s+[—–|]\s+|\s+-\s+", title, maxsplit=1)[0]
    prefix = re.sub(r"^(?:ЖК|жилой\s+комплекс)\s+", "", prefix, flags=re.I)
    prefix = re.sub(
        r"\s+(?:в\s+Москве|Москва|от\s+застройщика|официальный\s+сайт|ЦИАН)$",
        "",
        prefix,
        flags=re.I,
    )
    name = clean_project_name(prefix)
    if not _valid_name(name):
        return None
    return name


def _valid_name(name: str) -> bool:
    value = clean_project_name(name)
    low = value.lower()
    if len(value) < 3 or len(value) > 80:
        return False
    if _BAD_TITLE_RE.search(value):
        return False
    if low in {"новостройки", "жилые комплексы", "квартиры в новостройках"}:
        return False
    if re.search(r"\b(?:улица|ул\.?|проспект|проезд|шоссе|набережная|наб\.?)\b", low) and re.search(
        r"\b\d+[а-яa-z0-9/\-]*\b", low
    ):
        return False
    if re.search(r"\b\d+[,.]?\d*\s*м[²2]\b", low):
        return False
    return True


def _phrase_names(doc: SearchDoc) -> list[str]:
    text = " ".join(part for part in (doc.title, doc.snippet) if part)
    names: list[str] = []
    patterns = (
        r"\b(?:клубный\s+квартал|клубный\s+дом|жилой\s+квартал)\s+[«\"']?([^|—–\n,]{2,60}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+Москве|\s+от\s+застройщика))",
        r"\b(?:премиальный|элитный|делюкс)\s+жилой\s+комплекс\s+[«\"']?([^|—–\n,]{2,60}?)(?:[»\"']?(?:\s*[—–|,:]|\s+в\s+Москве|\s+от\s+застройщика))",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            value = clean_project_name(match.group(1))
            if _valid_name(value):
                names.append(value)
    return names


def extract_project_candidates_v5(docs: list[SearchDoc]) -> list[dict[str, Any]]:
    """High-recall residential project extraction for v5.

    v4 only extracted explicit ``ЖК`` / ``жилой комплекс`` text and Domclick complex URLs.
    Premium projects often omit the ``ЖК`` prefix entirely (for example, branded club houses),
    so v5 also trusts explicit project pages on major new-build aggregators while retaining
    conservative filters against listings, offices, apartments and bare postal addresses.
    """
    found: dict[str, dict[str, Any]] = {}

    def add(name: str, doc: SearchDoc, evidence: str) -> None:
        cleaned = clean_project_name(name)
        if not _valid_name(cleaned):
            return
        key = _key(cleaned)
        if len(key) < 3:
            return
        candidate = {
            "name": cleaned,
            "source_url": doc.url,
            "source_domain": doc.domain,
            "source_title": doc.title,
            "source_snippet": doc.snippet,
            "search_rank": doc.rank,
            "extraction_evidence": evidence,
            "discovery_sources": [doc.domain] if doc.domain else [],
        }
        current = found.get(key)
        if current is None:
            found[key] = candidate
            return
        domains = set(current.get("discovery_sources") or [])
        if doc.domain:
            domains.add(doc.domain)
        current["discovery_sources"] = sorted(domains)
        if doc.rank < int(current.get("search_rank") or 10_000):
            candidate["discovery_sources"] = current["discovery_sources"]
            found[key] = candidate

    legacy = extract_project_candidates(docs)
    docs_by_url = {doc.url: doc for doc in docs}
    for item in legacy:
        doc = docs_by_url.get(str(item.get("source_url") or ""))
        if doc is None:
            continue
        add(str(item.get("name") or ""), doc, "explicit_residential_project")

    for doc in docs:
        text = " ".join(part for part in (doc.title, doc.snippet) if part)
        if _BAD_DOC_RE.search(text):
            continue
        for name in _phrase_names(doc):
            add(name, doc, "premium_residential_phrase")
        if _trusted_project_page(doc):
            name = _title_project_name(doc.title)
            if name:
                add(name, doc, "trusted_newbuild_project_page")

    return sorted(found.values(), key=lambda item: (item["search_rank"], item["name"].lower()))
