from __future__ import annotations

import copy
import html
import re
from typing import Any

from fastapi import HTTPException

VERSION = "0.12.45"


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
    core = runtime.core

    # A cadastral number such as 50:12:... must never be interpreted by the
    # free-form TEP recognizer as a site area of 50 hectares.
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
        cleaned_text = cadastral_token_re.sub(" ", source_text)
        recognized = original_recognize(cleaned_text)
        if not explicit_area_re.search(source_text):
            recognized["site_area_ha"] = None
        return recognized

    core._recognize_freeform_tep_text = recognize_without_cadastral_area

    original_analyze = core.analyze_cadastral_territory

    def analyze_with_mo_parcel_fallback(req: Any) -> dict[str, Any]:
        """Run the normal ГлавАПУ analysis first.

        For Moscow Region batches the external service can reject the combined
        territory even though it can still resolve the cadastral parcels one by
        one. In that case resolve every parcel separately, sum cadastral areas and
        return one combined territory object. No manual area input is requested.
        """
        numbers = core._parse_cadastral_numbers(req.cadastral_numbers)
        try:
            return original_analyze(req)
        except HTTPException as batch_error:
            if not numbers or not all(str(number).startswith("50:") for number in numbers):
                raise

            parcel_results: list[dict[str, Any]] = []
            recognized: list[str] = []
            missing: list[str] = []
            warnings: list[str] = []
            first_territory: dict[str, Any] = {}

            for number in numbers:
                try:
                    single = original_analyze(
                        core.CadastralAnalysisRequest(cadastral_numbers=[number])
                    )
                except HTTPException:
                    missing.append(number)
                    continue

                single_parcels = single.get("parcels") or []
                if not single_parcels:
                    missing.append(number)
                    continue

                for parcel in single_parcels:
                    cad = str(parcel.get("cadastral_number") or number)
                    try:
                        area_ha = float(parcel.get("area_ha") or 0.0)
                    except (TypeError, ValueError):
                        area_ha = 0.0
                    if area_ha <= 0:
                        continue
                    if cad not in recognized:
                        recognized.append(cad)
                        parcel_results.append({
                            "cadastral_number": cad,
                            "area_ha": round(area_ha, 4),
                        })

                if not first_territory:
                    first_territory = copy.deepcopy(single.get("territory") or {})
                warnings.extend(str(item) for item in (single.get("warnings") or []) if item)

            if not parcel_results:
                raise batch_error

            total_area_ha = round(
                sum(float(parcel.get("area_ha") or 0.0) for parcel in parcel_results),
                4,
            )
            territory = first_territory
            territory.update({
                "parcel_count": len(parcel_results),
                "area_ha": total_area_ha,
                "inside_moscow": False,
            })

            combined_warnings = [
                "ГлавАПУ не сформировал готовый анализ Московской области; площади участков получены по кадастровым сведениям и автоматически суммированы.",
                "ТЭП Московской области рассчитывается модулем DevelopAid и требует проверки ВРИ, ПЗЗ и ограничений по официальным источникам.",
            ]
            if missing:
                combined_warnings.append(
                    "Не удалось получить площадь по участкам: " + ", ".join(missing) + "."
                )
            for warning in warnings:
                if warning not in combined_warnings and "только для территории Москвы" not in warning:
                    combined_warnings.append(warning)

            return {
                "requested": numbers,
                "recognized": recognized,
                "missing": missing,
                "parcels": parcel_results,
                "territory": territory,
                "coefficients": {},
                "calculator_url": "",
                "warnings": combined_warnings,
                "source": {
                    "service": "DevelopAid cadastral parcel fallback",
                    "calculated_at": core.date.today().isoformat(),
                    "batch_error": str(batch_error.detail),
                },
                "route": "moscow_region",
            }

    core.analyze_cadastral_territory = analyze_with_mo_parcel_fallback

    # FastAPI stores the original endpoint callable when the route is created.
    # Replace it as well so the web version and Telegram use identical logic.
    for route in runtime.app.routes:
        if getattr(route, "path", None) == "/cadastral/analyze":
            route.endpoint = analyze_with_mo_parcel_fallback
            if hasattr(route, "dependant"):
                route.dependant.call = analyze_with_mo_parcel_fallback

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        try:
            analysis = analyze_with_mo_parcel_fallback(
                core.CadastralAnalysisRequest(cadastral_numbers=numbers)
            )
        except HTTPException as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\n" + html.escape(str(exc.detail)),
            )
            return

        recognized = analysis.get("recognized") or numbers
        territory = analysis.get("territory") or {}
        district = " · ".join(
            str(value) for value in (
                territory.get("administrative_district"),
                territory.get("district"),
            ) if value
        ) or "—"
        dialog = {
            "step": "choose_cad_class",
            "data": {
                "cadastral_numbers": list(recognized),
                "territory": territory,
                "cadastral_analysis": analysis,
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
