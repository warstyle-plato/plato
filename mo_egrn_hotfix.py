from __future__ import annotations

import concurrent.futures
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException

VERSION = "0.12.47"
_NSPD_SEARCH_URL = "https://nspd.gov.ru/api/geoportal/v2/search/geoportal"
_NSPD_REQUEST_TIMEOUT = 8
_NSPD_TOTAL_TIMEOUT = 20


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


def _matching_cadastral(record: dict[str, Any], requested: str) -> bool:
    requested_compact = requested.replace(" ", "")
    for key in (
        "cad_num", "cadastral_number", "cadastralNumber", "cadNumber",
        "cn", "object_cad_number", "quarter_cad_number",
    ):
        if key in record:
            value = str(_scalar(record.get(key)) or "").replace(" ", "")
            if value == requested_compact:
                return True
    for key in ("title", "name", "label", "descr"):
        value = str(_scalar(record.get(key)) or "")
        if requested_compact in value.replace(" ", ""):
            return True
    return False


def _extract_area_sqm(record: dict[str, Any]) -> float | None:
    for key in (
        "specified_area", "land_record_area", "area_value", "area_value_m2",
        "area_sqm", "square", "area", "params_area",
    ):
        if key not in record:
            continue
        value = _number(record.get(key))
        if value is None or value <= 0:
            continue
        unit_text = " ".join(
            str(_scalar(record.get(unit_key)) or "")
            for unit_key in ("unit", "area_unit", "measurement_unit", "unit_name")
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


def _nspd_parcel(number: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"thematicSearchId": "1", "query": number})
    request = urllib.request.Request(
        _NSPD_SEARCH_URL + "?" + query,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://nspd.gov.ru/map?thematic=PKK",
            "Origin": "https://nspd.gov.ru",
            "User-Agent": "Mozilla/5.0 DevelopAid/0.12.47",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_NSPD_REQUEST_TIMEOUT) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"НСПД недоступна для {number}: {exc}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError(f"НСПД вернула слишком большой ответ для {number}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"НСПД вернула некорректный ответ для {number}") from exc

    matching = [record for record in _walk_dicts(payload) if _matching_cadastral(record, number)]
    for record in matching:
        for candidate in _walk_dicts(record):
            area_sqm = _extract_area_sqm(candidate)
            if area_sqm:
                merged = dict(record)
                merged.update(candidate)
                return {
                    "cadastral_number": number,
                    "area_sqm": round(area_sqm, 2),
                    "area_ha": round(area_sqm / 10_000.0, 4),
                    "address": _extract_text(merged, ("readable_address", "address", "address_readable_address")),
                    "permitted_use": _extract_text(merged, ("permitted_use", "land_record_permitted_use", "utilization", "use")),
                    "category": _extract_text(merged, ("land_category", "category", "category_name")),
                }
    raise RuntimeError(f"НСПД не вернула площадь участка {number}")


def _nspd_parcels_concurrent(numbers: list[str]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    parcels: list[dict[str, Any]] = []
    missing: list[str] = []
    errors: list[str] = []
    workers = min(8, max(1, len(numbers)))
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)
    futures = {executor.submit(_nspd_parcel, number): number for number in numbers}
    try:
        done, not_done = concurrent.futures.wait(
            futures,
            timeout=_NSPD_TOTAL_TIMEOUT,
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
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    order = {number: i for i, number in enumerate(numbers)}
    parcels.sort(key=lambda item: order.get(str(item.get("cadastral_number")), 10**9))
    missing = sorted(set(missing), key=lambda number: order.get(number, 10**9))
    return parcels, missing, errors


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
    core = runtime.core

    original_recognize = core._recognize_freeform_tep_text
    cadastral_token_re = re.compile(r"(?<!\d)\d{2}:\d{2}:\d{6,8}:\d+(?!\d)")
    explicit_area_re = re.compile(
        r"(?:площад(?:ь|и)\s+(?:территории|участка)|территори(?:я|и)|участок)"
        r"[^\n,;]{0,60}?\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?\s*(?:га|гектар(?:а|ов)?|м(?:²|2)|кв\.?\s*м)"
        r"|\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?\s*(?:га|гектар(?:а|ов)?)",
        re.IGNORECASE,
    )

    def recognize_without_cadastral_area(text: str) -> dict[str, Any]:
        source_text = str(text or "")
        recognized = original_recognize(cadastral_token_re.sub(" ", source_text))
        if not explicit_area_re.search(source_text):
            recognized["site_area_ha"] = None
        return recognized

    core._recognize_freeform_tep_text = recognize_without_cadastral_area
    original_analyze = core.analyze_cadastral_territory

    def analyze_with_nspd_fallback(req: Any) -> dict[str, Any]:
        numbers = core._parse_cadastral_numbers(req.cadastral_numbers)
        try:
            return original_analyze(req)
        except HTTPException as glavapu_error:
            if not numbers or not all(str(number).startswith("50:") for number in numbers):
                raise

            parcels, missing, errors = _nspd_parcels_concurrent(numbers)
            if not parcels:
                detail = (
                    "ГлавАПУ не сформировал территорию, а НСПД не вернула площади участков за 20 секунд. "
                    + ("; ".join(errors[:3]) if errors else str(glavapu_error.detail))
                )
                raise HTTPException(status_code=502, detail=detail) from glavapu_error

            recognized = [parcel["cadastral_number"] for parcel in parcels]
            total_area_ha = round(sum(float(parcel["area_ha"]) for parcel in parcels), 4)
            categories = sorted({str(parcel.get("category") or "") for parcel in parcels if parcel.get("category")})
            uses = sorted({str(parcel.get("permitted_use") or "") for parcel in parcels if parcel.get("permitted_use")})
            warnings = [
                "ГлавАПУ не сформировал готовый анализ Московской области; площади получены из публичных данных НСПД и автоматически суммированы.",
                "ТЭП Московской области является предварительным: ВРИ, ПЗЗ, ограничения и стоимостные коэффициенты необходимо подтвердить.",
            ]
            if missing:
                warnings.append("Не получены сведения по участкам: " + ", ".join(missing) + ".")

            return {
                "requested": numbers,
                "recognized": recognized,
                "missing": missing,
                "parcels": parcels,
                "territory": {
                    "parcel_count": len(parcels),
                    "area_ha": total_area_ha,
                    "district": "",
                    "administrative_district": "",
                    "cadastral_quarter": numbers[0].rsplit(":", 1)[0] if numbers else "",
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
                    "service": "НСПД / публичная кадастровая карта",
                    "search_endpoint": "nspd.gov.ru/api/geoportal/v2/search/geoportal",
                    "calculated_at": core.date.today().isoformat(),
                    "glavapu_error": str(glavapu_error.detail),
                },
                "route": "moscow_region",
            }

    core.analyze_cadastral_territory = analyze_with_nspd_fallback
    for route in runtime.app.routes:
        if getattr(route, "path", None) == "/cadastral/analyze":
            route.endpoint = analyze_with_nspd_fallback
            if hasattr(route, "dependant"):
                route.dependant.call = analyze_with_nspd_fallback

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        core._telegram_send_message(
            chat_id,
            f"<b>Проверяю {len(numbers)} участков.</b> Сначала запрашиваю ГлавАПУ; для Московской области при необходимости получу площади из НСПД. Обычно это занимает до 20 секунд.",
        )
        try:
            analysis = analyze_with_nspd_fallback(
                core.CadastralAnalysisRequest(cadastral_numbers=numbers)
            )
        except HTTPException as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\n" + html.escape(str(exc.detail)),
            )
            return
        except Exception as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\nВнутренняя ошибка: " + html.escape(str(exc)),
            )
            return

        recognized = analysis.get("recognized") or numbers
        territory = analysis.get("territory") or {}
        district = " · ".join(
            str(value) for value in (
                territory.get("administrative_district"), territory.get("district")
            ) if value
        ) or "—"
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
        title = (
            "<b>Территория Московской области сформирована</b>"
            if analysis.get("route") == "moscow_region"
            else "<b>Территория сформирована</b>"
        )
        core._telegram_send_message(
            chat_id,
            title + "\n"
            f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
            f"Площадь: <b>{core._telegram_number(territory.get('area_ha'), 4)} га</b>\n"
            f"Район: <b>{html.escape(district)}</b>\n"
            f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
            "Площадь рассчитана автоматически по кадастровым сведениям. Перед расчётом выберите класс — он задаст базовые цены и СМР.",
        )
        core._telegram_cad_class_menu(chat_id, dialog)

    core._telegram_handle_cadastral_numbers = handle_cadastral_numbers
