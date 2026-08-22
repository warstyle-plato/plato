"""Public Moscow KRT catalogue (krt.mos.ru) with a disk-backed snapshot.

The catalogue is discovery evidence, not a source of parcel geometry.  A
project is therefore resolved to an explicitly approximate geocoded point;
official decision geometry can be attached later without changing callers.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json


BASE_URL = "https://krt.mos.ru"
CATALOGUE_URL = BASE_URL + "/projects/"
_SPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class KrtTerritory:
    slug: str
    name: str
    url: str
    area_ha: float | None = None
    okrug: str | None = None
    district: str | None = None
    status: str | None = None
    total_gfa_sqm: float | None = None
    housing_gfa_sqm: float | None = None
    nonresidential_gfa_sqm: float | None = None
    business_gfa_sqm: float | None = None
    jobs: float | None = None
    source: str = "krt.mos.ru"

    @property
    def query(self) -> str:
        return "krt:" + self.slug

    @property
    def geocode_query(self) -> str:
        return ", ".join(filter(None, ("Москва", self.district, self.name)))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "query": self.query, "geocode_query": self.geocode_query,
                "geometry_status": "not_published_in_catalogue"}


class _CatalogueParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, list[str]]] = []
        self._slug: str | None = None
        self._name = ""
        self._parts: list[str] = []
        self._capture_link = False
        self.next_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        href = values.get("href") or ""
        classes = values.get("class") or ""
        if tag == "a" and re.fullmatch(r"/projects/[^/?#]+/?", href):
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            if self._slug and slug != self._slug:
                self._flush()
            self._slug = slug
            self._capture_link = True
        if "show_more" in classes and values.get("data-url"):
            self.next_url = urljoin(BASE_URL, values["data-url"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_link = False

    def handle_data(self, data: str) -> None:
        text = _SPACE.sub(" ", data).strip()
        if not text or not self._slug:
            return
        if self._capture_link and text.lower() != "подробнее" and not self._name:
            self._name = text
        elif ":" in text:
            self._parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self._slug and self._name:
            self.rows.append((self._slug, self._name, list(dict.fromkeys(self._parts))))
        self._slug, self._name, self._parts = None, "", []


def _number(text: str) -> float | None:
    found = _NUMBER.search(text.replace(" ", ""))
    return float(found.group(0).replace(",", ".")) if found else None


def parse_catalogue(html: str) -> tuple[list[KrtTerritory], str | None]:
    parser = _CatalogueParser()
    parser.feed(html)
    parser.close()
    rows: list[KrtTerritory] = []
    for slug, name, parts in parser.rows:
        fields = {p.split(":", 1)[0].strip().lower(): p.split(":", 1)[1].strip() for p in parts}
        rows.append(KrtTerritory(
            slug=slug, name=name, url=f"{BASE_URL}/projects/{slug}",
            area_ha=_number(fields.get("площадь", "")),
            okrug=fields.get("округ"), district=fields.get("район"), status=fields.get("статус"),
            total_gfa_sqm=_number(fields.get("общий объем застройки", "")),
            housing_gfa_sqm=_number(fields.get("жилое назначение", "")),
            nonresidential_gfa_sqm=_number(fields.get("нежилое назначение", "")),
            business_gfa_sqm=_number(fields.get("общественно-деловое назначение", "")),
            jobs=_number(fields.get("прирост рабочих мест", "")),
        ))
    return rows, parser.next_url


class KrtRegistry:
    def __init__(self, data_dir: Path, *, fetch: Callable[[str], bytes] | None = None) -> None:
        self.path = Path(data_dir) / "krt" / "catalogue.json"
        self.fetch = fetch or (lambda url: request_bytes(url, timeout=15, retries=1))
        self.ttl_seconds = 24 * 60 * 60
        self._refreshing = False
        self._refresh_lock = threading.Lock()

    def projects(self, *, refresh: bool = False, max_pages: int = 100) -> list[KrtTerritory]:
        cached = load_json(self.path)
        if cached and not refresh and fresh(self.path, self.ttl_seconds):
            return self._decode(cached)
        try:
            rows, seen, url = [], set(), CATALOGUE_URL
            for _ in range(max_pages):
                if not url or url in seen:
                    break
                seen.add(url)
                page, url = parse_catalogue(self.fetch(url).decode("utf-8", errors="replace"))
                rows.extend(page)
            unique = {row.slug: row for row in rows}
            if unique:
                payload = {"source": CATALOGUE_URL, "retrieved_at": int(time.time()),
                           "projects": [row.to_dict() for row in unique.values()]}
                save_json(self.path, payload)
                return list(unique.values())
        except (RemoteServiceError, OSError, UnicodeError):
            pass
        return self._decode(cached) if cached else []

    @staticmethod
    def _decode(payload: Any) -> list[KrtTerritory]:
        out = []
        for raw in (payload or {}).get("projects", []):
            clean = {key: raw.get(key) for key in KrtTerritory.__dataclass_fields__}
            try:
                out.append(KrtTerritory(**clean))
            except (TypeError, ValueError):
                continue
        return out

    def find(self, query: str) -> dict[str, Any] | None:
        text = _SPACE.sub(" ", str(query or "")).strip()
        slug = text[4:] if text.lower().startswith("krt:") else None
        low = text.casefold()
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        # Ordinary addresses pass through this resolver too. Never turn an
        # unrelated market report into a synchronous crawl of krt.mos.ru.
        if slug and not rows:
            rows = self.projects(max_pages=1)
            self.refresh_in_background()
        for item in rows:
            if (slug and item.slug == slug) or (not slug and item.name.casefold() == low):
                return item.to_dict()
        return None

    def suggest(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        needle = _SPACE.sub(" ", str(query or "")).strip().casefold()
        if len(needle) < 2:
            return []
        cached = load_json(self.path)
        # A cold autocomplete request may read one page, but never walks the
        # whole Bitrix catalogue while a person is typing.  The full snapshot
        # continues in a daemon thread and the previous snapshot stays usable.
        rows = self._decode(cached) if cached else self.projects(max_pages=1)
        if not cached or not fresh(self.path, self.ttl_seconds):
            self.refresh_in_background()
        ranked = [row for row in rows if needle in row.name.casefold()
                  or needle in (row.district or "").casefold()]
        ranked.sort(key=lambda row: (not row.name.casefold().startswith(needle), row.name))
        return [row.to_dict() for row in ranked[:limit]]

    def catalogue(self) -> list[dict[str, Any]]:
        """Fast UI snapshot; complete a cold/stale catalogue off-thread."""
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else self.projects(max_pages=1)
        if not cached or not fresh(self.path, self.ttl_seconds):
            self.refresh_in_background()
        return [row.to_dict() for row in rows]

    def refresh_in_background(self) -> bool:
        with self._refresh_lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def run() -> None:
            try:
                self.projects(refresh=True)
            finally:
                with self._refresh_lock:
                    self._refreshing = False

        threading.Thread(target=run, name="krt-catalogue-refresh", daemon=True).start()
        return True
