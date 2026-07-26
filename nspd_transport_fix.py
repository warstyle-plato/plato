from __future__ import annotations

import concurrent.futures
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import mo_egrn_hotfix as mo

VERSION = "0.12.48"
_REQUEST_TIMEOUT = 7
_TOTAL_TIMEOUT = 35


def _nspd_parcel(number: str) -> dict[str, Any]:
    # Match the request currently used by the maintained rosreestr2coord NSPD client:
    # thematic search 1 (real-estate objects) and an explicit output CRS.
    query = urllib.parse.urlencode({
        "thematicSearchId": "1",
        "query": number,
        "CRS": "EPSG:4326",
    })
    request = urllib.request.Request(
        mo._NSPD_SEARCH_URL + "?" + query,
        headers={
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://nspd.gov.ru/map?thematic=PKK",
            "Origin": "https://nspd.gov.ru",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
        },
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT, context=context) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"НСПД HTTP {exc.code} для {number}: {body or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"НСПД недоступна для {number}: {exc}") from exc

    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError(f"НСПД вернула слишком большой ответ для {number}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"НСПД вернула некорректный ответ для {number}") from exc

    # The current NSPD response shape is data.features. Keep the generic walker as a
    # fallback because the portal occasionally changes nesting without notice.
    features = ((payload.get("data") or {}).get("features") or []) if isinstance(payload, dict) else []
    candidates = list(features) + [
        record for record in mo._walk_dicts(payload)
        if mo._matching_cadastral(record, number)
    ]
    for record in candidates:
        properties = record.get("properties") if isinstance(record, dict) else None
        nested = [record]
        if isinstance(properties, dict):
            nested.insert(0, properties)
        nested.extend(mo._walk_dicts(record))
        for candidate in nested:
            if not isinstance(candidate, dict):
                continue
            area_sqm = mo._extract_area_sqm(candidate)
            if not area_sqm:
                continue
            merged = dict(record) if isinstance(record, dict) else {}
            if isinstance(properties, dict):
                merged.update(properties)
            merged.update(candidate)
            return {
                "cadastral_number": number,
                "area_sqm": round(area_sqm, 2),
                "area_ha": round(area_sqm / 10_000.0, 4),
                "address": mo._extract_text(merged, ("readable_address", "address", "address_readable_address")),
                "permitted_use": mo._extract_text(merged, ("permitted_use", "land_record_permitted_use", "utilization", "use")),
                "category": mo._extract_text(merged, ("land_category", "category", "category_name")),
            }
    raise RuntimeError(f"НСПД не вернула площадь участка {number}")


def _nspd_parcels_concurrent(numbers: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    parcels: list[dict[str, Any]] = []
    missing: list[str] = []
    errors: list[str] = []
    order = {number: index for index, number in enumerate(numbers)}

    # Eight simultaneous requests caused NSPD to throttle the Render host. Three
    # workers keep the batch quick without creating a burst against the public portal.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, max(1, len(numbers)))) as executor:
        futures = {executor.submit(_nspd_parcel, number): number for number in numbers}
        done, not_done = concurrent.futures.wait(
            futures,
            timeout=_TOTAL_TIMEOUT,
            return_when=concurrent.futures.ALL_COMPLETED,
        )
        for future in done:
            number = futures[future]
            try:
                parcels.append(future.result())
            except Exception as exc:
                missing.append(number)
                errors.append(str(exc))
        for future in not_done:
            number = futures[future]
            future.cancel()
            missing.append(number)
            errors.append(f"Истекло время ожидания НСПД для {number}")

    parcels.sort(key=lambda item: order.get(str(item.get("cadastral_number")), 10**9))
    missing = sorted(set(missing), key=lambda number: order.get(number, 10**9))
    return parcels, missing, errors


def apply(runtime: Any) -> None:
    mo._nspd_parcel = _nspd_parcel
    mo._nspd_parcels_concurrent = _nspd_parcels_concurrent
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
