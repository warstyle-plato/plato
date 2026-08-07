"""Telegram menu adapter for the isolated MPT calculator.

This module changes presentation/navigation only. It does not touch VRI/TEP or
financial calculation logic. The existing /help inline menu receives one extra
WebApp button and Telegram's slash-command menu receives /mpt.
"""

from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_MENU_TEXT = "🏗 Льгота МПТ — Москва"


def _with_query(url: str, **values: str) -> str:
    parts = urlsplit(str(url or ""))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _mpt_url(base: Any, chat_id: int) -> str:
    return _with_query(base.core._telegram_web_app_url(chat_id, []), section="mpt")


def _has_mpt_button(markup: Any) -> bool:
    if not isinstance(markup, dict):
        return False
    for row in markup.get("inline_keyboard") or []:
        if not isinstance(row, list):
            continue
        for button in row:
            if not isinstance(button, dict):
                continue
            if str(button.get("text") or "") == _MENU_TEXT:
                return True
            web_app = button.get("web_app") or {}
            if isinstance(web_app, dict) and "section=mpt" in str(web_app.get("url") or ""):
                return True
    return False


def _help_with_mpt(base: Any, chat_id: int, markup: Any) -> Any:
    if not isinstance(markup, dict) or _has_mpt_button(markup):
        return markup
    rows = markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return markup
    # The extra entry belongs only to the main DevelopAid help/menu, identified
    # by the existing VRI/TEP action. Temporary inline keyboards stay untouched.
    has_vri_entry = any(
        isinstance(button, dict)
        and (
            str(button.get("callback_data") or "") == "vritep_start"
            or "ВРИ" in str(button.get("text") or "").upper()
            or "ТЭП" in str(button.get("text") or "").upper()
        )
        for row in rows if isinstance(row, list)
        for button in row
    )
    if not has_vri_entry:
        return markup
    try:
        url = _mpt_url(base, chat_id)
    except Exception:
        # The application can be imported in CI/diagnostic mode without a
        # configured Telegram token. The existing help menu must still work.
        return markup
    updated = copy.deepcopy(markup)
    updated["inline_keyboard"].append([{
        "text": _MENU_TEXT,
        "web_app": {"url": url},
    }])
    return updated


def _ensure_command(core: Any) -> None:
    commands = getattr(core, "TELEGRAM_BOT_COMMANDS", None)
    if not isinstance(commands, list):
        return
    if any(isinstance(item, dict) and str(item.get("command") or "") == "mpt" for item in commands):
        return
    commands.append({"command": "mpt", "description": "Льгота МПТ — Москва"})


def install(base: Any) -> None:
    if getattr(base, "_MPT_BOT_MENU_INSTALLED", False):
        return

    original_help_markup = getattr(base, "_help_markup", None)
    if callable(original_help_markup):
        def help_markup(chat_id: int) -> Any:
            return _help_with_mpt(base, chat_id, original_help_markup(chat_id))
        base._help_markup = help_markup

    _ensure_command(base.core)
    base._MPT_BOT_MENU_INSTALLED = True
