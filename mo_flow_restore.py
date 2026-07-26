from __future__ import annotations

import copy
import ssl
from typing import Any

from fastapi import HTTPException

import mo_egrn_hotfix as egrn

VERSION = "0.12.51"


def apply(runtime: Any) -> None:
    """Use GlavAPU first for every cadastral number, including 50:*.

    A cadastral number beginning with 50 may belong to New Moscow. Therefore the
    prefix alone must never select Moscow Region rules. Only when GlavAPU does not
    form a Moscow territory do we use NSPD and the existing Moscow Region TEP/VRI
    calculator.
    """
    core = runtime.core

    # Keep relaxed certificate validation strictly inside the NSPD client.
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

    # mo_egrn_hotfix already implements the required routing:
    # GlavAPU first; NSPD fallback only when all numbers begin with 50:.
    routed_analyze = core.analyze_cadastral_territory
    standard_handler = core._telegram_handle_cadastral_numbers
    mo_handler = getattr(core, "_telegram_handle_mo_numbers", None)

    def handle_cadastral_numbers(chat_id: int, numbers: list[str]) -> None:
        all_50 = bool(numbers) and all(str(number).startswith("50:") for number in numbers)
        if not all_50:
            standard_handler(chat_id, numbers)
            return

        core._telegram_send_message(
            chat_id,
            f"<b>Проверяю {len(numbers)} участков.</b> Сначала запрашиваю ГлавАПУ, "
            "поскольку кадастр 50: может относиться к Новой Москве. Если ГлавАПУ не сформирует "
            "территорию Москвы, автоматически запущу расчёт ТЭП и ВРИ Московской области.",
        )
        try:
            analysis = routed_analyze(core.CadastralAnalysisRequest(cadastral_numbers=numbers))
        except HTTPException as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\n" + core.html.escape(str(exc.detail)),
            )
            return
        except Exception as exc:
            core._telegram_send_message(
                chat_id,
                "<b>Не удалось сформировать территорию.</b>\nВнутренняя ошибка: "
                + core.html.escape(f"{type(exc).__name__}: {exc}"),
            )
            return

        if analysis.get("route") == "moscow_region" and callable(mo_handler):
            core._telegram_send_message(
                chat_id,
                "<b>ГлавАПУ не подтвердил территорию Москвы.</b> "
                "Запускаю расчёт ТЭП и ВРИ Московской области.",
            )
            mo_handler(chat_id, numbers)
            return

        # ГлавАПУ found the territory, including any New Moscow parcel. Use the
        # normal Moscow flow and its official TEP without applying MO rules.
        standard_handler(chat_id, numbers)

    core._telegram_handle_cadastral_numbers = handle_cadastral_numbers

    # Make the MO action explicit in the review card.
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
