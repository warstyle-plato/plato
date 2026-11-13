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
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.project_slugs = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "show_more" in (values.get("class") or ""):
            self.links.append(values.get("data-url"))
        if tag == "a":
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
        markers = _SourceMarkers()
        markers.feed(text)
        markers.close()
    except (ValueError, UnicodeError, RecursionError):
        return [], None, "unrecognized_catalogue"
    if not rows:
        return [], None, "unrecognized_catalogue"
    if markers.project_slugs != {row.slug for row in rows}:
        return [], None, "project_identity_coverage_incomplete"
    if markers.links and (len(markers.links) != 1 or not markers.links[0] or not next_url):
        return [], None, "invalid_next_link"
    if next_url is not None:
        next_url = _next_url(next_url)
        if next_url is None:
            return [], None, "invalid_next_link"
    projected = []
    for row in rows:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,180}", row.slug or ""):
            return [], None, "invalid_slug"
        status = row.status
        if status is not None:
            status = " ".join(status.split())
            if len(status) > 160 or any(ord(char) < 32 for char in status):
                return [], None, "invalid_status"
        projected.append({"slug": row.slug, "status": status})
    return projected, next_url, None


async def capture(*, runtime: dict) -> dict:
    """One bounded walk, in memory; the caller has already admitted the owner."""
    runtime = _runtime(runtime)
    started = time.monotonic()
    result = {
        "purpose": PURPOSE, "scope": "current_official_catalogue_response_not_historical",
        "runtime": runtime,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": ORIGIN, "complete": False, "pages": [], "roster": [],
        "gaps": [], "bytes": 0, "source_updated_at": None,
        "http_headers_are_not_source_dates": True,
        "origin_cache_revalidation": "requested_not_attested",
        "historical_period_proven": False, "production_acceptance": False,
        "source_files_written": False,
    }

    def gap(code):
        if code not in result["gaps"]:
            result["gaps"].append(code)

    seen_urls, seen_slugs, seen_bodies = set(), set(), set()
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
                        if result["gaps"]:
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
                    page["rows"] = len(rows)
                    if len(result["roster"]) + len(rows) > MAX_ROWS:
                        gap("roster_limit")
                        break
                    slugs = [row["slug"] for row in rows]
                    if len(set(slugs)) != len(slugs) or any(slug in seen_slugs for slug in slugs):
                        gap("duplicate_slug")
                        break
                    result["roster"].extend(rows)
                    seen_slugs.update(slugs)
                    page["has_next"] = next_url is not None
                    if next_url is None:
                        result["complete"] = True
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
    if result["gaps"]:
        result["complete"] = False
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["roster_sha256"] = hashlib.sha256(
        json.dumps(result["roster"], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_OUTPUT_BYTES:
        result["roster"] = []
        result["roster_sha256"] = None
        result["complete"] = False
        gap("output_limit")
    return result
