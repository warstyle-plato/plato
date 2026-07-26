from __future__ import annotations

import concurrent.futures
import html
import http.cookiejar
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException

VERSION = "0.12.49"
ENGINE = "nspd-quarter-first"
_NSPD_SEARCH_URL = "https://nspd.gov.ru/api/geoportal/v2/search/geoportal"
_REQUEST_TIMEOUT = 12
_TOTAL_TIMEOUT = 45
_MAX_WORKERS = 2

_CADASTRAL_TOKEN_RE = re.compile(r"(?<!\d)\d{2}:\d{2}:\d{6,8}:\d+(?!\d)")
_EXPLICIT_AREA_RE = re.compile(
    r"(?:площад(?:ь|и)\s+(?:территории|участка)|территори(?:я|и)|участок)"
    r"[^\n,;]{0,60}?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?\s*(?:га|гектар(?:а|ов)?|м(?:²|2)|кв\.?\s*м)"
    r"|\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?\s*(?:га|гектар(?:а|ов)?)",
    re.IGNORECASE,
)


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "text", "name", "label"):
            if key in value:
                return _scalar(value[key])
        return None
    return value


def _number(value: Any) -> float | None:
    value = _scalar(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\u00a0", " ").replace("\u202f", " ")
    match = re.search(r"[-+]?\d[\d\s]*(?:[.,]\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _record_cadastral(record: dict[str, Any]) -> str:
    for key in (
        "cad_num", "cadastral_number", "cadastralNumber", "cadNumber", "cn",
        "object_cad_number", "quarter_cad_number", "externalKey", "external_key",
    ):
        value = str(_scalar(record.get(key)) or "").strip().replace(" ", "")
        if _CADASTRAL_TOKEN_RE.fullmatch(value):
            return value
    for key in ("title", "name", "label", "descr", "description"):
        text = str(_scalar(record.get(key)) or "")
        match = _CADASTRAL_TOKEN_RE.search(text)
        if match:
            return match.group(0)
    return ""


def _extract_area_sqm(record: dict[str, Any]) -> float | None:
    for key in (
        "specified_area", "land_record_area", "area_value", "area_value_m2",
        "area_sqm", "square", "area", "params_area", "areaValue", "area_value_sqm",
    ):
        if key not in record:
            continue
        value = _number(record.get(key))
        if value is None or value <= 0:
            continue
        unit_text = " ".join(
            str(_scalar(record.get(unit_key)) or "")
            for unit_key in ("unit", "area_unit", "measurement_unit", "unit_name", "areaUnit")
        ).lower()
        if "га" in unit_text or "hect" in unit_text or key.endswith("_ha"):
            value *= 10_000.0
        if 1.0 <= value <= 10_000_000_000.0:
            return value
    return None


def _extract_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _scalar(record.get(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _features(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("features"), list):
        return [item for item in data["features"] if isinstance(item, dict)]
    if isinstance(payload.get("features"), list):
        return [item for item in payload["features"] if isinstance(item, dict)]
    return []


def _parcel_from_feature(feature: dict[str, Any], requested: str | None = None) -> dict[str, Any] | None:
    properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    candidates = [properties, feature]
    candidates.extend(item for item in _walk_dicts(feature) if isinstance(item, dict))
    cadastral = _record_cadastral(properties) or _record_cadastral(feature) or (requested or "")
    if requested and cadastral and cadastral != requested:
        return None
    for candidate in candidates:
        area_sqm = _extract_area_sqm(candidate)
        if not area_sqm:
            continue
        merged = dict(feature)
        merged.update(properties)
        merged.update(candidate)
        return {
            "cadastral_number": cadastral or requested or "",
            "area_sqm": round(area_sqm, 2),
            "area_ha": round(area_sqm / 10_000.0, 4),
            "address": _extract_text(merged, ("readable_address", "address", "address_readable_address")),
            "permitted_use": _extract_text(merged, ("permitted_use", "land_record_permitted_use", "utilization", "use")),
            "category": _extract_text(merged, ("land_category", "category", "category_name")),
        }
    return None


def _new_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    context = ssl.create_default_context()
    https_handler = urllib.request.HTTPSHandler(context=context)
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar), https_handler)


def _request_json(params: dict[str, str]) -> dict[str, Any]:
    opener = _new_opener()
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        "Referer": "https://nspd.gov.ru/map?thematic=PKK",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    }
    # Establish a portal session first. Failure here is non-fatal: the API may still answer.
    try:
        opener.open(urllib.request.Request("https://nspd.gov.ru/map?thematic=PKK", headers=headers), timeout=5).close()
    except Exception:
        pass
    url = _NSPD_SEARCH_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=_REQUEST_TIMEOUT) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"НСПД HTTP {exc.code}: {body or exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(f"НСПД недоступна: {type(exc).__name__}: {exc}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError("НСПД вернула слишком большой ответ")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("НСПД вернула некорректный JSON") from exc


def _query_payload(query: str) -> dict[str, Any]:
    errors: list[str] = []
    variants = (
        {"thematicSearchId": "1", "query": query},
        {"layersId": "36048", "query": query},
    )
    for params in variants:
        try:
            return _request_json(params)
        except RuntimeError as exc:
            errors.append(str(exc))
    raise RuntimeError("; ".join(errors))


def _lookup_exact(number: str) -> dict[str, Any]:
    payload = _query_payload(number)
    for feature in _features(payload):
        parcel = _parcel_from_feature(feature, number)
        if parcel:
            return parcel
    for record in _walk_dicts(payload):
        if not isinstance(record, dict):
            continue
        cadastral = _record_cadastral(record)
        if cadastral != number:
            continue
        parcel = _parcel_from_feature(record, number)
        if parcel:
            return parcel
    raise RuntimeError(f"НСПД не вернула площадь участка {number}")


def _lookup_batch(numbers: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    started = time.monotonic()
    requested = set(numbers)
    found: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    # Most user batches belong to one cadastral quarter. One quarter request is
    # substantially more reliable than a burst of dozens of requests from Render.
    quarters: list[str] = []
    for number in numbers:
        quarter = number.rsplit(":", 1)[0]
        if quarter not in quarters:
            quarters.append(quarter)
    for quarter in quarters:
        if time.monotonic() - started >= _TOTAL_TIMEOUT:
            break
        try:
            payload = _query_payload(quarter)
            for feature in _features(payload):
                parcel = _parcel_from_feature(feature)
                if parcel and parcel.get("cadastral_number") in requested:
                    found[str(parcel["cadastral_number"])] = parcel
        except RuntimeError as exc:
            errors.append(f"квартал {quarter}: {exc}")

    remaining = [number for number in numbers if number not in found]
    budget = max(1.0, _TOTAL_TIMEOUT - (time.monotonic() - started))
    if remaining and budget > 1:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(remaining)))
        futures = {executor.submit(_lookup_exact, number): number for number in remaining}
        try:
            done, not_done = concurrent.futures.wait(futures, timeout=budget)
            for future in done:
                number = futures[future]
                try:
                    found[number] = future.result()
                except Exception as exc:
                    errors.append(f"{number}: {exc}")
            for future in not_done:
                number = futures[future]
                future.cancel()
                errors.append(f"{number}: истекло время ожидания")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    parcels = [found[number] for number in numbers if number in found]
    missing = [number for number in numbers if number not in found]
    return parcels, missing, errors


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
    core = runtime.core

    original_recognize = core._recognize_freeform_tep_text

    def recognize_without_cadastral_area(text: str) -> dict[str, Any]:
        source_text = str(text or "")
        recognized = original_recognize(_CADASTRAL_TOKEN_RE.sub(" ", source_text))
        if not _EXPLICIT_AREA_RE.search(source_text):
            recognized["site_area_ha"] = None
        return recognized

    core._recognize_freeform_tep_text = recognize_without_cadastral_area
    original_analyze = core.analyze_cadastral_territory

    def analyze_cadastral(req: Any) -> dict[str, Any]:
        numbers = core._parse_cadastral_numbers(req.cadastral_numbers)
        try:
            result = original_analyze(req)
            result.setdefault("source", {})["engine_version"] = VERSION
            result["route"] = "glavapu"
            return result
        except HTTPException as glavapu_error:
            if not numbers or not all(number.startswith("50:") for number in numbers):
                raise

        parcels, missing, errors = _lookup_batch(numbers)
        if not parcels:
            detail = "ГлавАПУ не сформировал территорию, а кадастровый источник не вернул площади."
            if errors:
                detail += " " + "; ".join(errors[:3])
            raise HTTPException(status_code=502, detail=detail)

        total_area_ha = round(sum(float(parcel["area_ha"]) for parcel in parcels), 4)
        categories = sorted({str(parcel.get("category") or "") for parcel in parcels if parcel.get("category")})
        uses = sorted({str(parcel.get("permitted_use") or "") for parcel in parcels if parcel.get("permitted_use")})
        warnings = [
            "ГлавАПУ не сформировал готовый анализ Московской области; площади участков получены из публичных кадастровых сведений и автоматически суммированы.",
            "ТЭП Московской области является предварительным: ВРИ, ПЗЗ и ограничения необходимо подтвердить по официальным документам.",
        ]
        if missing:
            warnings.append("Не получены сведения по участкам: " + ", ".join(missing) + ".")
        return {
            "requested": numbers,
            "recognized": [parcel["cadastral_number"] for parcel in parcels],
            "missing": missing,
            "parcels": parcels,
            "territory": {
                "parcel_count": len(parcels),
                "area_ha": total_area_ha,
                "district": "",
                "administrative_district": "",
                "cadastral_quarter": numbers[0].rsplit(":", 1)[0],
                "inside_moscow": False,
                "inside_ttc": False,
                "categories": categories,
                "permitted_uses": uses,
                "center": {"lat": None, "lng": None},
            },
            "coefficients": {},
            "calculator_url": "",
            "warnings": warnings,
            "source": {
                "service": "НСПД / публичные кадастровые сведения",
                "engine": ENGINE,
                "engine_version": VERSION,
                "calculated_at": core.date.today().isoformat(),
            },
            "route": "moscow_region",
        }

    core.analyze_cadastral_territory = analyze_cadastral
    for route in runtime.app.routes:
        if getattr(route, "path", None) == "/cadastral/analyze":
            route.endpoint = analyze_cadastral
            if hasattr(route, "dependant"):
                route.dependant.call = analyze_cadastral

    @runtime.app.get("/cadastral/runtime")
    def cadastral_runtime() -> dict[str, Any]:
        return {
            "version": VERSION,
            "engine": ENGINE,
            "request_timeout_seconds": _REQUEST_TIMEOUT,
            "total_timeout_seconds": _TOTAL_TIMEOUT,
            "workers": _MAX_WORKERS,
        }

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        core._telegram_send_message(
            chat_id,
            f"<b>Проверяю {len(numbers)} участков.</b> Сначала запрашиваю ГлавАПУ; для Московской области при необходимости получу и сложу площади по кадастровым сведениям. Обработка занимает до {_TOTAL_TIMEOUT} секунд.",
        )
        try:
            analysis = analyze_cadastral(core.CadastralAnalysisRequest(cadastral_numbers=numbers))
        except HTTPException as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\n" + html.escape(str(exc.detail)),
            )
            return
        except Exception as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\nВнутренняя ошибка: " + html.escape(f"{type(exc).__name__}: {exc}"),
            )
            return

        recognized = analysis.get("recognized") or numbers
        territory = analysis.get("territory") or {}
        dialog = {
            "step": "choose_cad_class",
            "data": {
                "cadastral_numbers": list(recognized),
                "territory": territory,
                "cadastral_analysis": analysis,
                "site_area_ha": territory.get("area_ha"),
                "region": "Московская область" if analysis.get("route") == "moscow_region" else "",
            },
        }
        core._telegram_dialog_save(chat_id, dialog)
        district = " · ".join(
            str(value) for value in (territory.get("administrative_district"), territory.get("district")) if value
        ) or "—"
        title = "<b>Территория Московской области сформирована</b>" if analysis.get("route") == "moscow_region" else "<b>Территория сформирована</b>"
        missing = analysis.get("missing") or []
        partial = f"\nНе найдено: <b>{len(missing)}</b>" if missing else ""
        core._telegram_send_message(
            chat_id,
            title + "\n"
            f"Участков учтено: <b>{int(territory.get('parcel_count') or len(recognized))}</b>{partial}\n"
            f"Площадь: <b>{core._telegram_number(territory.get('area_ha'), 4)} га</b>\n"
            f"Район: <b>{html.escape(district)}</b>\n"
            f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
            "Площадь рассчитана автоматически. Перед расчётом выберите класс — он задаст базовые цены и СМР.",
        )
        core._telegram_cad_class_menu(chat_id, dialog)

    core._telegram_handle_cadastral_numbers = handle_cadastral_numbers
