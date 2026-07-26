from __future__ import annotations

import html
from typing import Any

from fastapi import HTTPException

VERSION = "0.12.43"


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = VERSION
    runtime.app.version = VERSION
    core = runtime.core

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        try:
            analysis = core.analyze_cadastral_territory(
                core.CadastralAnalysisRequest(cadastral_numbers=numbers)
            )
        except HTTPException as exc:
            if numbers and all(str(number).startswith("50:") for number in numbers):
                # The existing cadastral/EGRN lookup was attempted, but the external
                # territory service has no completed Moscow Region analysis. Preserve
                # the cadastral scope and continue through the existing TEP dialogue,
                # asking only for the missing territory area instead of aborting.
                core._telegram_dialog_save(chat_id, {
                    "step": "await_site_area",
                    "data": {
                        "cadastral_numbers": list(numbers),
                        "region": "Московская область",
                        "cadastral_lookup_error": str(exc.detail),
                    },
                })
                core._telegram_send_message(
                    chat_id,
                    "<b>Кадастровые номера приняты.</b>\n\n"
                    "Поиск сведений по участкам выполнен, но внешний сервис территории "
                    "не вернул готовый анализ для Московской области. Список участков сохранён.\n\n"
                    "<b>Укажите только общую площадь территории</b> — в гектарах или квадратных метрах, "
                    "например <code>12,4 га</code> или <code>124 000 м²</code>. "
                    "После этого DevelopAid продолжит расчёт ТЭП по существующему сценарию МО.",
                )
                return
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
            },
        }
        core._telegram_dialog_save(chat_id, dialog)
        core._telegram_send_message(
            chat_id,
            "<b>Территория сформирована</b>\n"
            f"Участков: <b>{int(territory.get('parcel_count') or len(recognized))}</b>\n"
            f"Площадь: <b>{core._telegram_number(territory.get('area_ha'), 4)} га</b>\n"
            f"Район: <b>{html.escape(district)}</b>\n"
            f"Кадастровый квартал: <b>{html.escape(str(territory.get('cadastral_quarter') or '—'))}</b>\n\n"
            "Перед расчётом выберите класс — он задаст базовые цены и СМР.",
        )
        core._telegram_cad_class_menu(chat_id, dialog)

    core._telegram_handle_cadastral_numbers = handle_cadastral_numbers
