"""Bounded official catalogue observation; never refreshes an application store."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlsplit

import httpx2

from market_search.krt_registry import parse_catalogue
from trusted_roots import trust_context

PURPOSE = "krt_origin_catalogue_v1"
ORIGIN = "https://api.krt.mos.ru/projects/"
MAX_BYTES = 4 * 1024 * 1024
MAX_SECONDS = 45.0
MAX_PAGES = 100
MAX_ROWS = 4000
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_STATUS_OBSERVATIONS = 8
HEADERS = {
    "User-Agent": "DevelopAid-Market-Discovery/0.2 (+https://developaid.ru)",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Accept": "text/html",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
CACHE_HEADERS = ("date", "age", "etag", "last-modified", "cache-control", "expires")


class InputError(ValueError):
    pass


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InputError("invalid_request")
        value[key] = item
    return value


def validate_request(raw: bytes) -> None:
    if not isinstance(raw, bytes) or len(raw) > 16384:
        raise InputError("invalid_request")
    try:
        value = json.loads(raw, object_pairs_hook=_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError("invalid_request") from exc
    if not isinstance(value, dict) or set(value) - {"key", "session", "purpose"}:
        raise InputError("invalid_request")
    if value.get("purpose") != PURPOSE:
        raise InputError("invalid_purpose")
    for key in ("key", "session"):
        if key in value and (not isinstance(value[key], str) or len(value[key]) > 4096):
            raise InputError("invalid_request")


def _runtime(value):
    if (not isinstance(value, dict) or set(value) != {"commit", "version"}
            or not isinstance(value["commit"], str)
            or not re.fullmatch(r"[a-f0-9]{40}", value["commit"])
            or not isinstance(value["version"], str)
            or not re.fullmatch(r"\d+\.\d+\.\d+", value["version"])):
        raise InputError("invalid_runtime")
    return dict(value)


def _new_client():
    # No inherited proxy credentials, cookies, auth, redirects or retry transport.
    return httpx2.AsyncClient(
        verify=trust_context(), trust_env=False, follow_redirects=False,
        timeout=httpx2.Timeout(MAX_SECONDS), headers=HEADERS,
        limits=httpx2.Limits(max_connections=1, max_keepalive_connections=1),
    )


class _SourceMarkers(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.project_slugs = set()
        self.named_projects = []
        self.status_observations = []
        self._occurrence_index = None
        self._text = text
        self._line = 1
        self._line_start = 0
        self._named_anchor = None

    def _offset(self):
        line, column = self.getpos()
        while self._line < line:
            self._line_start = self._text.index("\n", self._line_start) + 1
            self._line += 1
        return self._line_start + column

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "show_more" in (values.get("class") or ""):
            self.links.append(values.get("data-url"))
        if tag == "a":
            self._named_anchor = None
            href = values.get("href") or ""
            try:
                parts = urlsplit(href)
            except ValueError:
                return
            if (not parts.scheme and not parts.netloc or
                    parts.scheme == "https" and parts.netloc.lower() == "api.krt.mos.ru"):
                project = re.fullmatch(r"/projects/([^/?#]+)/?", parts.path)
                if project:
                    self.project_slugs.add(project[1])
                    self._named_anchor = (project[1], self._offset())

    def handle_data(self, data):
        text = " ".join(data.split())
        if self._named_anchor and text and text.lower() != "подробнее":
            self.named_projects.append(self._named_anchor)
            self.status_observations.append([])
            self._occurrence_index = len(self.named_projects) - 1
            self._named_anchor = None
            return
        if self._occurrence_index is not None and ":" in text:
            label, value = text.split(":", 1)
            if label.strip().lower() == "статус":
                observations = self.status_observations[self._occurrence_index]
                value = value.strip()
                if value not in observations and len(observations) <= MAX_STATUS_OBSERVATIONS:
                    observations.append(value)

    def handle_endtag(self, tag):
        if tag == "a":
            self._named_anchor = None


def _next_url(value):
    """Only the server's native numeric pagination on the fixed origin/path."""
    if not isinstance(value, str) or len(value) > 256:
        return None
    try:
        parts = urlsplit(value)
        query = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    if (parts.scheme != "https" or parts.netloc.lower() != "api.krt.mos.ru"
            or parts.path != "/projects/" or parts.fragment
            or len(query) != 1 or query[0][0] != "PAGEN_1"
            or not re.fullmatch(r"[1-9][0-9]{0,5}", query[0][1])):
        return None
    return ORIGIN + "?PAGEN_1=" + query[0][1]


def _page_rows(raw):
    try:
        text = raw.decode("utf-8")
        rows, next_url = parse_catalogue(text)
        markers = _SourceMarkers(text)
        markers.feed(text)
        markers.close()
    except (ValueError, UnicodeError, RecursionError):
        return [], None, "unrecognized_catalogue"
    if not rows:
        return [], None, "unrecognized_catalogue"
    # The native parser coalesces adjacent links with the same slug. Observe
    # each named project occurrence separately, still using that pure parser;
    # image-only and "Подробнее" links do not create another occurrence.
    if markers.named_projects:
        rows = []
        for index, (slug, start) in enumerate(markers.named_projects):
            end = (markers.named_projects[index + 1][1]
                   if index + 1 < len(markers.named_projects) else len(text))
            try:
                occurrence, _ = parse_catalogue(text[start:end])
            except (ValueError, UnicodeError, RecursionError):
                return [], None, "unrecognized_catalogue"
            if len(occurrence) != 1 or occurrence[0].slug != slug:
                return [], None, "project_identity_coverage_incomplete"
            rows.extend(occurrence)
    if markers.project_slugs != {row.slug for row in rows}:
        return [], None, "project_identity_coverage_incomplete"
    if markers.links and (len(markers.links) != 1 or not markers.links[0] or not next_url):
        return [], None, "invalid_next_link"
    if next_url is not None:
        next_url = _next_url(next_url)
        if next_url is None:
            return [], None, "invalid_next_link"
    projected = []
    for index, row in enumerate(rows):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", row.slug or ""):
            return [], None, "invalid_slug"
        status = row.status
        if status is not None:
            status = " ".join(status.split())
            if len(status) > 160 or any(ord(char) < 32 for char in status):
                return [], None, "invalid_status"
        item = {"slug": row.slug, "status": status}
        observed_statuses = markers.status_observations[index]
        if len(observed_statuses) > MAX_STATUS_OBSERVATIONS:
            return [], None, "status_observation_limit"
        if any(len(value) > 160 or any(ord(char) < 32 for char in value) for value in observed_statuses):
            return [], None, "invalid_status"
        statuses = list(dict.fromkeys(observed_statuses + [status]))
        if len(statuses) > 1:
            item["status_observations"] = statuses
        projected.append(item)
    return projected, next_url, None


async def capture(*, runtime: dict) -> dict:
    """One bounded walk, in memory; the caller has already admitted the owner."""
    runtime = _runtime(runtime)
    started = time.monotonic()
    result = {
        "purpose": PURPOSE, "scope": "current_official_catalogue_response_not_historical",
        "runtime": runtime,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": ORIGIN, "complete": False, "walk_complete": False,
        "pages": [], "roster": [], "roster_grain": "observed_named_project_anchor_occurrence",
        "gaps": [], "quality_gaps": [], "bytes": 0, "source_updated_at": None,
        "observed_occurrence_count": 0, "observed_unique_slug_count": 0,
        "observed_duplicate_occurrence_count": 0, "occurrence_identity_ambiguous": False,
        "conflicting_status_observations": [], "output_truncated": False,
        "http_headers_are_not_source_dates": True,
        "origin_cache_revalidation": "requested_not_attested",
        "historical_period_proven": False, "production_acceptance": False,
        "source_files_written": False,
    }

    def gap(code):
        if code not in result["gaps"]:
            result["gaps"].append(code)

    def quality_gap(code):
        gap(code)
        if code not in result["quality_gaps"]:
            result["quality_gaps"].append(code)

    seen_urls, seen_bodies = set(), set()
    statuses_by_slug = {}
    url = ORIGIN
    try:
        async with asyncio.timeout(MAX_SECONDS):
            async with _new_client() as client:
                for index in range(MAX_PAGES):
                    if url in seen_urls:
                        gap("repeated_next_link")
                        break
                    seen_urls.add(url)
                    page = {"url": url, "status": None, "bytes": 0,
                            "sha256": None, "body_complete": False, "cache_headers": {}}
                    result["pages"].append(page)
                    # A Set-Cookie on one public page must not become a credential
                    # on the next; this is an observation, not a browsing session.
                    client.cookies.clear()
                    async with client.stream("GET", url) as response:
                        page["status"] = response.status_code
                        page["cache_headers"] = {
                            key: response.headers[key][:256]
                            for key in CACHE_HEADERS if key in response.headers
                        }
                        if 300 <= response.status_code < 400:
                            gap("redirect_refused")
                            break
                        if response.status_code != 200:
                            gap("http_status")
                            break
                        if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                            gap("unsupported_content_encoding")
                            break
                        data = bytearray()
                        digest = hashlib.sha256()
                        async for chunk in response.aiter_raw():
                            remaining = MAX_BYTES - result["bytes"]
                            if len(chunk) > remaining:
                                # The receipt explicitly binds only the bounded prefix.
                                data.extend(chunk[:remaining])
                                digest.update(chunk[:remaining])
                                page["bytes"] += remaining
                                result["bytes"] += remaining
                                page["sha256"] = digest.hexdigest()
                                gap("body_limit")
                                break
                            data.extend(chunk)
                            digest.update(chunk)
                            page["bytes"] += len(chunk)
                            result["bytes"] += len(chunk)
                            page["sha256"] = digest.hexdigest()
                        if "body_limit" in result["gaps"]:
                            break
                        page["body_complete"] = True
                        page["sha256"] = digest.hexdigest()
                    if page["sha256"] in seen_bodies:
                        gap("repeated_page")
                        break
                    seen_bodies.add(page["sha256"])
                    rows, next_url, problem = _page_rows(bytes(data))
                    if time.monotonic() - started >= MAX_SECONDS:
                        gap("total_time_limit")
                        break
                    if problem:
                        gap(problem)
                        break
                    page["observed_occurrence_count"] = len(rows)
                    if len(result["roster"]) + len(rows) > MAX_ROWS:
                        result["output_truncated"] = True
                        gap("roster_limit")
                        break
                    for row in rows:
                        statuses = statuses_by_slug.setdefault(row["slug"], set())
                        if statuses:
                            quality_gap("duplicate_slug")
                        observations = row.get("status_observations", [row["status"]])
                        if "status_observations" in row:
                            quality_gap("ambiguous_status_within_occurrence")
                        if len(set(observations)) > 1 or statuses and set(observations) - statuses:
                            quality_gap("conflicting_status")
                        statuses.update(observations)
                    result["roster"].extend(rows)
                    page["has_next"] = next_url is not None
                    if next_url is None:
                        result["walk_complete"] = True
                        break
                    if next_url in seen_urls:
                        gap("repeated_next_link")
                        break
                    if next_url != ORIGIN + "?PAGEN_1=" + str(index + 2):
                        gap("nonsequential_next_link")
                        break
                    url = next_url
                else:
                    gap("page_limit")
    except TimeoutError:
        gap("total_time_limit")
    except httpx2.TimeoutException:
        gap("transport_timeout")
    except (httpx2.HTTPError, httpx2.StreamError):
        gap("transport_error")
    except (OSError, ValueError):
        gap("transport_unavailable")
    if any(code not in result["quality_gaps"] for code in result["gaps"]):
        result["walk_complete"] = False
    result["complete"] = result["walk_complete"] and not result["gaps"]
    result["observed_occurrence_count"] = len(result["roster"])
    result["observed_unique_slug_count"] = len(statuses_by_slug)
    result["observed_duplicate_occurrence_count"] = (
        result["observed_occurrence_count"] - result["observed_unique_slug_count"])
    result["occurrence_identity_ambiguous"] = bool(result["observed_duplicate_occurrence_count"])
    result["conflicting_status_observations"] = [
        {"slug": slug, "statuses": sorted(statuses, key=lambda value: (value is not None, value or ""))}
        for slug, statuses in statuses_by_slug.items() if len(statuses) > 1
    ]
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["roster_sha256"] = hashlib.sha256(
        json.dumps(result["roster"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES:
        result["roster"] = []
        result["conflicting_status_observations"] = []
        result["roster_sha256"] = None
        result["complete"] = False
        result["walk_complete"] = False
        result["output_truncated"] = True
        gap("output_limit")
    return result
