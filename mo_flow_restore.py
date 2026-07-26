from __future__ import annotations

import copy
import ssl
from typing import Any

import mo_egrn_hotfix as egrn

VERSION = "0.12.50"


def apply(runtime: Any) -> None:
    """Restore the existing MO calculator as the primary flow for cadastral numbers 50:*.

    The NSPD client is used only to obtain cadastral data and its relaxed SSL context is
    scoped to that client. Moscow Region numbers do not go through GlavAPU.
    """
    core = runtime.core

    # Yandex Cloud test showed that NSPD is reachable, but certificate validation can
    # fail in the VM image. Keep this exception strictly inside the NSPD opener.
    def nspd_opener():
        import http.cookiejar
        import urllib.request

        cookie_jar = http.cookiejar.CookieJar()
        context = ssl._create_unverified_context()
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPSHandler(context=context),
        )

    egrn._new_opener = nspd_opener

    current_analyze = core.analyze_cadastral_territory

    def analyze_without_glavapu_for_mo(req: Any) -> dict[str, Any]:
        numbers = core._parse_cadastral_numbers(req.cadastral_numbers)
        if not numbers or not all(str(number).startswith("50:") for number in numbers):
            return current_analyze(req)

        parcels, missing, errors = egrn._lookup_batch(numbers)
        if not parcels:
            detail = "Кадастровый источник не вернул площади участков Московской области."
            if errors:
                detail += " " + "; ".join(errors[:3])
            from fastapi import HTTPException
            raise HTTPException(status_code=502, detail=detail)

        total_area_ha = round(sum(float(parcel["area_ha"]) for parcel in parcels), 4)
        categories = sorted({str(parcel.get("category") or "") for parcel in parcels if parcel.get("category")})
        uses = sorted({str(parcel.get("permitted_use") or "") for parcel in parcels if parcel.get("permitted_use")})
        warnings = [
            "Площади участков получены из публичных кадастровых сведений и автоматически суммированы.",
            "ТЭП и ВРИ Московской области являются предварительными и требуют проверки по ПЗЗ и официальным документам.",
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
                "site_area_ha": total_area_ha,
                "district": "",
                "administrative_district": "",
                "cadastral_quarter": numbers[0].rsplit(":", 1)[0],
                "quarter": numbers[0].rsplit(":", 1)[0],
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
                "engine": egrn.ENGINE,
                "engine_version": VERSION,
                "calculated_at": core.date.today().isoformat(),
            },
            "route": "moscow_region",
        }

    core.analyze_cadastral_territory = analyze_without_glavapu_for_mo
    for route in runtime.app.routes:
        if getattr(route, "path", None) == "/cadastral/analyze":
            route.endpoint = analyze_without_glavapu_for_mo
            if hasattr(route, "dependant"):
                route.dependant.call = analyze_without_glavapu_for_mo

    # The legacy core already contains the complete MO calculation and TEP review.
    # The previous hotfix replaced this handler with a territory-only card; restore it.
    mo_handler = getattr(core, "_telegram_handle_mo_numbers", None)
    fallback_handler = core._telegram_handle_cadastral_numbers

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        if numbers and all(str(number).startswith("50:") for number in numbers) and callable(mo_handler):
            core._telegram_send_message(
                chat_id,
                f"<b>Рассчитываю ТЭП и ВРИ Московской области по {len(numbers)} участкам.</b> "
                "Площади будут получены автоматически; ГлавАПУ не используется.",
            )
            mo_handler(chat_id, numbers)
            return
        fallback_handler(chat_id, numbers)

    core._telegram_handle_cadastral_numbers = handle_cadastral_numbers

    # For the MO TEP card, make the action explicit: it applies the calculated values
    # to Inputs and TEP when the mini-app opens with the generated manual session.
    original_review = getattr(core, "_telegram_send_tep_review", None)
    if callable(original_review):
        def send_tep_review(chat_id: int, parsed: dict[str, Any], *, dialog_mode: bool) -> None:
            if (parsed.get("source") or {}).get("type") != "mo_calculator":
                original_review(chat_id, parsed, dialog_mode=dialog_mode)
                return
            original_send = core._telegram_send_message

            def send_with_apply_label(target_chat_id: int, text: str, *, reply_markup=None):
                markup = copy.deepcopy(reply_markup)
                if isinstance(markup, dict):
                    for row in markup.get("inline_keyboard") or []:
                        for button in row if isinstance(row, list) else []:
                            if isinstance(button, dict) and button.get("text") == "Подтвердить и открыть DevelopAid":
                                button["text"] = "Применить к Вводным и ТЭП"
                return original_send(target_chat_id, text, reply_markup=markup)

            core._telegram_send_message = send_with_apply_label
            try:
                original_review(chat_id, parsed, dialog_mode=dialog_mode)
            finally:
                core._telegram_send_message = original_send

        core._telegram_send_tep_review = send_tep_review

    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
