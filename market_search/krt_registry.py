"""Public Moscow KRT catalogue (krt.mos.ru) with a disk-backed snapshot.

The catalogue is discovery evidence, not a source of parcel geometry.  A
project is therefore resolved to an explicitly approximate geocoded point;
official decision geometry can be attached later without changing callers.
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from .http import RemoteServiceError, fresh, load_json, request_bytes, save_json
from .krt_requirements import (
    decision_search_urls,
    document_attachments_url,
    document_detail_url,
    is_planned_project,
    merge_decision_requirements,
    parse_decision_requirements,
    parse_project_requirements,
    pdf_text,
    select_pdf_attachment,
    select_project_decision,
)


BASE_URL = "https://api.krt.mos.ru"
CATALOGUE_URL = BASE_URL + "/projects/"
JINA_PREFIX = "https://r.jina.ai/"
CACHE_SCHEMA_VERSION = 2
REQUIREMENTS_CACHE_SCHEMA_VERSION = 2
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


_MARKDOWN_CARD = re.compile(
    r"\[([^\]\n]+?)\s*Подробнее\]\(https?://(?:api\.)?krt\.mos\.ru/projects/([^/?#)]+)\)"
)


def parse_catalogue_markdown(markdown: str) -> list[KrtTerritory]:
    """Parse the official page as rendered by the read-only transport fallback."""
    matches = list(_MARKDOWN_CARD.finditer(markdown))
    rows: list[KrtTerritory] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        block = markdown[match.end():end]
        fields: dict[str, str] = {}
        for line in block.splitlines():
            text = _SPACE.sub(" ", line).strip().strip("*")
            if ":" in text:
                key, value = text.split(":", 1)
                fields[key.strip().lower()] = value.strip()
        slug, name = match.group(2), match.group(1).strip()
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
    return rows


class KrtRegistry:
    def __init__(self, data_dir: Path, *, fetch: Callable[[str], bytes] | None = None) -> None:
        self.path = Path(data_dir) / "krt" / "catalogue.json"
        self.requirements_dir = Path(data_dir) / "krt" / "requirements"
        self.fetch = fetch or (lambda url: request_bytes(url, timeout=15, retries=1))
        self.ttl_seconds = 24 * 60 * 60
        self._refreshing = False
        self._refresh_lock = threading.Lock()

    def projects(self, *, refresh: bool = False, max_pages: int = 100) -> list[KrtTerritory]:
        cached = load_json(self.path)
        if (self._cache_current(cached) and not refresh and fresh(self.path, self.ttl_seconds)
                and cached.get("complete", True)):
            return self._decode(cached)
        rows: list[KrtTerritory] = []
        seen_urls: set[str] = set()
        seen_slugs: set[str] = set()

        def persist(*, complete: bool) -> None:
            if not rows:
                return
            save_json(self.path, {
                "schema_version": CACHE_SCHEMA_VERSION,
                "source": CATALOGUE_URL, "retrieved_at": int(time.time()),
                "complete": complete, "projects": [row.to_dict() for row in rows],
            })

        # The official host is primary. It occasionally drops all TCP traffic;
        # failure then switches the public catalogue only to a read-only page
        # renderer. User requests never wait for either path (see catalogue()).
        direct_complete = False
        try:
            url = CATALOGUE_URL
            for _ in range(max_pages):
                if not url or url in seen_urls:
                    direct_complete = True
                    break
                seen_urls.add(url)
                page, url = parse_catalogue(self.fetch(url).decode("utf-8", errors="replace"))
                if not page:
                    direct_complete = True
                    break
                new_rows = [row for row in page if row.slug not in seen_slugs]
                rows.extend(new_rows)
                seen_slugs.update(row.slug for row in new_rows)
                persist(complete=False)
        except (RemoteServiceError, OSError, UnicodeError):
            pass
        if rows and direct_complete:
            persist(complete=True)
            return rows

        # The renderer preserves the official page text and links. Pagination
        # has no reliable final-page marker, so a repeated page is the stop.
        try:
            for page_number in range(1, max_pages + 1):
                suffix = "" if page_number == 1 else f"?PAGEN_1={page_number}"
                document = self.fetch(JINA_PREFIX + CATALOGUE_URL + suffix).decode(
                    "utf-8", errors="replace"
                )
                page = parse_catalogue_markdown(document)
                new_rows = [row for row in page if row.slug not in seen_slugs]
                if not page or not new_rows:
                    persist(complete=bool(rows))
                    return rows
                rows.extend(new_rows)
                seen_slugs.update(row.slug for row in new_rows)
                persist(complete=False)
        except (RemoteServiceError, OSError, UnicodeError):
            pass
        persist(complete=False)
        return rows or (self._decode(cached) if cached else [])

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

    @staticmethod
    def _cache_current(payload: Any) -> bool:
        return bool(
            isinstance(payload, dict)
            and payload.get("schema_version") == CACHE_SCHEMA_VERSION
        )

    def find(self, query: str) -> dict[str, Any] | None:
        text = _SPACE.sub(" ", str(query or "")).strip()
        slug = text[4:] if text.lower().startswith("krt:") else None
        low = text.casefold()
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        if (not self._cache_current(cached) or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
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
        rows = self._decode(cached) if cached else []
        if (not self._cache_current(cached) or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
            self.refresh_in_background()
        ranked = [row for row in rows if needle in row.name.casefold()
                  or needle in (row.district or "").casefold()]
        ranked.sort(key=lambda row: (not row.name.casefold().startswith(needle), row.name))
        return [row.to_dict() for row in ranked[:limit]]

    def catalogue(self) -> list[dict[str, Any]]:
        """Return the snapshot immediately; all network work stays off-thread."""
        cached = load_json(self.path)
        rows = self._decode(cached) if cached else []
        if (not self._cache_current(cached) or not fresh(self.path, self.ttl_seconds)
                or not cached.get("complete", True)):
            self.refresh_in_background()
        return [row.to_dict() for row in rows]

    def requirements(self, slug: str, *, refresh: bool = False) -> dict[str, Any] | None:
        """Read one planned KRT card and its official project-decision PDF."""
        clean_slug = str(slug or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", clean_slug):
            return None
        project = next(
            (item for item in self.catalogue() if item.get("slug") == clean_slug), None)
        if not project:
            return None
        if not is_planned_project(project):
            return {
                "schema_version": REQUIREMENTS_CACHE_SCHEMA_VERSION,
                "slug": clean_slug,
                "name": project.get("name"),
                "status": project.get("status"),
                "available": False,
                "skipped": True,
                "warning": "Документы читаются только для планируемых КРТ.",
            }
        cache_path = self.requirements_dir / f"{clean_slug}.json"
        cached = load_json(cache_path)
        if (not refresh and fresh(cache_path, self.ttl_seconds)
                and isinstance(cached, dict)
                and cached.get("schema_version") == REQUIREMENTS_CACHE_SCHEMA_VERSION):
            return cached

        source_url = str(project.get("url") or f"{BASE_URL}/projects/{clean_slug}")
        document = ""
        transport = "official_host"
        errors: list[str] = []
        # The KRT host currently presents a certificate chain that standard
        # server trust stores reject.  The renderer transports the same public
        # page and returns in seconds; the official host remains a fallback.
        # The legally relevant PDF below is always downloaded directly from
        # mos.ru and never through the renderer.
        for url, label in ((JINA_PREFIX + source_url, "read_only_renderer"),
                           (source_url, "official_host")):
            try:
                document = self.fetch(url).decode("utf-8", errors="replace")
            except (RemoteServiceError, OSError, UnicodeError) as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                continue
            if document.strip():
                transport = label
                break
        result = parse_project_requirements(document, project)
        result["status"] = project.get("status")

        def remote_json(url: str, label: str) -> Any | None:
            try:
                return json.loads(self.fetch(url).decode("utf-8"))
            except (RemoteServiceError, OSError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
                return None

        decision = None
        for index, search_url in enumerate(decision_search_urls(project), start=1):
            payload = remote_json(search_url, f"mos_search_{index}")
            decision = select_project_decision(payload, project)
            if decision:
                break

        decision_meta: dict[str, Any] | None = None
        if decision:
            document_id = str(decision.get("id") or "").strip()
            detail = remote_json(document_detail_url(document_id), "mos_document_detail")
            institution_id = (detail or {}).get("institution_id")
            if institution_id is not None:
                attachments = remote_json(
                    document_attachments_url(document_id, institution_id),
                    "mos_document_attachments",
                )
                pdf_url = select_pdf_attachment(attachments)
                if pdf_url:
                    try:
                        pdf_data = self.fetch(pdf_url)
                        if len(pdf_data) > 35 * 1024 * 1024:
                            raise RuntimeError("PDF проекта решения превышает 35 МБ")
                        facts = parse_decision_requirements(pdf_text(pdf_data))
                        decision_meta = {
                            "id": document_id,
                            "title": decision.get("title"),
                            "page_url": decision.get("url"),
                            "pdf_url": pdf_url,
                            "published_at": (detail or {}).get("date_published"),
                        }
                        result = merge_decision_requirements(result, facts, decision_meta)
                    except (RemoteServiceError, OSError, RuntimeError) as exc:
                        errors.append(f"mos_decision_pdf: {type(exc).__name__}: {exc}")
                else:
                    errors.append("mos_document_attachments: PDF не опубликован")
            else:
                errors.append("mos_document_detail: не указан орган публикации")

        if decision_meta is None:
            result["decision_available"] = False
            result["warning"] = (
                "В официальном поиске mos.ru не найден читаемый проект решения для этой "
                "карточки. Показаны только ТЭП и текст krt.mos.ru; отсутствие сведений "
                "о сносе или расселении не означает, что их нет."
            )
        else:
            result["decision_available"] = True
        result.update({
            "schema_version": REQUIREMENTS_CACHE_SCHEMA_VERSION,
            "available": True,
            "retrieved_at": int(time.time()),
            "transport": transport,
            "errors": errors[:3],
        })
        save_json(cache_path, result)
        return result

    def status(self) -> dict[str, bool]:
        cached = load_json(self.path)
        return {
            "complete": bool(
                self._cache_current(cached) and cached.get("complete", True)
            ),
            "refreshing": self._refreshing,
        }

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
