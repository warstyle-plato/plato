from __future__ import annotations

import asyncio
import copy
import html
import importlib.util
import inspect
import os
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent
_RUNTIME_VERSION = "0.12.36"


def _load_core():
    spec = importlib.util.spec_from_file_location("developaid_core", _ROOT / "main_legacy.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("DevelopAid: cannot load main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = _load_core()
app = core.app
app.version = _RUNTIME_VERSION

_ORIGINAL_SEND_MESSAGE = core._telegram_send_message
_ORIGINAL_HANDLE_MESSAGE = core._telegram_handle_message
_ORIGINAL_HANDLE_UPDATE = core._telegram_handle_update

_STATE_LOCK = threading.RLock()
_PLATON_MODE: dict[int, str] = {}
_PLATON_LAST_SESSION: dict[int, str] = {}
_PLATON_LAST_URL: dict[int, str] = {}
_PLATON_HISTORY: dict[int, list[dict[str, Any]]] = {}
_PLATON_CONTEXT_BY_SESSION: dict[str, dict[str, Any]] = {}
_PLATON_PENDING: dict[int, dict[str, Any]] = {}


class TelegramContextRequest(BaseModel):
    session: str
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = Field(default_factory=list)
    phasing: dict[str, Any] = Field(default_factory=dict)
    selected_view: str = "all"


def _extract_message(update_or_message: dict[str, Any]) -> tuple[int, int, str]:
    message = update_or_message.get("message") if isinstance(update_or_message.get("message"), dict) else update_or_message
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = int(chat.get("id") or 0)
    user_id = int(sender.get("id") or chat_id)
    return chat_id, user_id, str(message.get("text") or "").strip()


def _extract_session_from_url(url: str) -> str:
    parsed = urlparse(str(url or ""))
    merged: dict[str, list[str]] = {}
    for source in (parsed.query, parsed.fragment):
        for key, values in parse_qs(source).items():
            merged.setdefault(key, []).extend(values)
    for key in ("telegram_session", "session", "manual_session", "token"):
        value = (merged.get(key) or [""])[0].strip()
        if value:
            return value
    return ""


def _remember_markup(chat_id: int, reply_markup: Any) -> None:
    if not isinstance(reply_markup, dict):
        return
    rows = reply_markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            if not isinstance(button, dict):
                continue
            web_app = button.get("web_app")
            if not isinstance(web_app, dict):
                continue
            url = str(web_app.get("url") or "").strip()
            if not url:
                continue
            session = _extract_session_from_url(url)
            with _STATE_LOCK:
                _PLATON_LAST_URL[chat_id] = url
                if session:
                    _PLATON_LAST_SESSION[chat_id] = session


def _add_platon_button(reply_markup: Any) -> Any:
    if not isinstance(reply_markup, dict):
        return reply_markup
    rows = reply_markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return reply_markup
    has_web_app = any(
        isinstance(button, dict) and isinstance(button.get("web_app"), dict)
        for row in rows if isinstance(row, list)
        for button in row
    )
    if not has_web_app:
        return reply_markup
    if any(
        isinstance(button, dict) and button.get("callback_data") == "ask_platon"
        for row in rows if isinstance(row, list)
        for button in row
    ):
        return reply_markup
    updated = copy.deepcopy(reply_markup)
    updated.setdefault("inline_keyboard", []).append([
        {"text": "Спросить Платона", "callback_data": "ask_platon"}
    ])
    return updated


def _send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> Any:
    _remember_markup(chat_id, reply_markup)
    return _ORIGINAL_SEND_MESSAGE(
        chat_id,
        text,
        reply_markup=_add_platon_button(reply_markup),
    )


core._telegram_send_message = _send_message


def _help_markup(chat_id: int) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
        [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "Спросить Платона", "callback_data": "ask_platon"}],
    ]
    try:
        rows.append([{
            "text": "Открыть мини-приложение DevelopAid",
            "web_app": {"url": core._telegram_web_app_url(chat_id, [])},
        }])
    except Exception:
        pass
    return {"inline_keyboard": rows}


def _send_help(chat_id: int) -> None:
    _send_message(
        chat_id,
        "<b>Как работать с DevelopAid</b>\n\n"
        "<b>1. Сформируйте ТЭП</b>\n"
        "• отправьте один или несколько кадастровых номеров московского участка;\n"
        "• для другого региона или проекта без кадастра ответьте на вопросы бота;\n"
        "• либо скачайте Excel-шаблон ТЭП и отправьте заполненный файл обратно.\n\n"
        "<b>2. Настройте проект в мини-приложении</b>\n"
        "Можно менять площади и продукты, цены и темпы продаж, себестоимость, сроки ИРД и строительства, "
        "ключевую ставку, БРИДЖ, проектное финансирование и социальную нагрузку. Для крупного проекта "
        "можно включить очередность и распределить ТЭП и расходы по очередям.\n\n"
        "<b>3. Получите инвестиционный вывод</b>\n"
        "DevelopAid считает выручку, CAPEX, EBITDA, чистую прибыль, NPV, LLCR, потребность в БРИДЖе и ПФ, "
        "динамику долга и эскроу, а также формирует PDF-отчёт.\n\n"
        "<b>4. Спросите Платона Сергеевича Федоскина</b>\n"
        "После отправки результата в Telegram Платон работает с текущей моделью: объясняет показатели, "
        "сравнивает сценарии и подбирает цену покупки, цены продаж, СМР и параметры финансирования.\n\n"
        "<i>Расчёт является предварительной инвестиционной моделью, а не отчётом оценщика и не решением банка.</i>",
        reply_markup=_help_markup(chat_id),
    )


def _status_message(chat_id: int, user_id: int) -> None:
    configured = bool(core._TELEGRAM_RUNTIME.get("configured"))
    with _STATE_LOCK:
        session = _PLATON_LAST_SESSION.get(chat_id, "")
        has_context = bool(session and session in _PLATON_CONTEXT_BY_SESSION)
    _send_message(
        chat_id,
        f"<b>DevelopAid bot:</b> {'подключён' if configured else 'запускается'}\n"
        f"Telegram ID: <code>{user_id}</code>\n"
        f"Версия: {_RUNTIME_VERSION}\n"
        f"Платон: {'контекст модели загружен' if has_context else 'ожидает новый расчёт'}",
    )


@app.post("/telegram/context")
def save_telegram_context(req: TelegramContextRequest) -> dict[str, Any]:
    session_data = core._telegram_verify_session(req.session)
    chat_id = int(session_data.get("chat_id") or 0)
    if not chat_id or not core._telegram_user_allowed(chat_id):
        raise HTTPException(status_code=403, detail="Доступ к боту закрыт")
    context = {
        "session": req.session,
        "chat_id": chat_id,
        "inputs": copy.deepcopy(req.inputs),
        "tep": copy.deepcopy(req.tep),
        "rates": copy.deepcopy(req.rates),
        "phasing": copy.deepcopy(req.phasing),
        "selected_view": str(req.selected_view or "all"),
        "session_data": copy.deepcopy(session_data),
    }
    with _STATE_LOCK:
        _PLATON_CONTEXT_BY_SESSION[req.session] = context
        _PLATON_LAST_SESSION[chat_id] = req.session
    return {"ok": True, "version": _RUNTIME_VERSION}


def _patch_page_context_upload() -> None:
    page = str(core.PAGE)
    if "/telegram/context" in page:
        return
    needle = "const response=await fetch('/telegram/result',{"
    if needle not in page:
        return
    injection = (
        "try{await fetch('/telegram/context',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({session:telegramSession,inputs,tep,rates,"
        "phasing:(typeof phasing!=='undefined'?phasing:{}),"
        "selected_view:(typeof reportView!=='undefined'?reportView:'all')})})}"
        "catch(e){console.warn('Telegram context:',e)}\n " + needle
    )
    core.PAGE = page.replace(needle, injection, 1)


_patch_page_context_upload()


def _answer_callback(query: dict[str, Any]) -> None:
    query_id = str(query.get("id") or "")
    if not query_id:
        return
    try:
        core._telegram_api("answerCallbackQuery", {"callback_query_id": query_id})
    except Exception:
        pass


def _platon_markup(chat_id: int, *, proposal: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if proposal:
        rows.append([{"text": "Применить в модель", "callback_data": "platon_apply"}])
        rows.append([{"text": "Не применять", "callback_data": "platon_discard"}])
    with _STATE_LOCK:
        url = _PLATON_LAST_URL.get(chat_id, "")
    if url:
        rows.append([{"text": "Открыть текущую модель", "web_app": {"url": url}}])
    rows.append([{"text": "Завершить диалог", "callback_data": "platon_stop"}])
    return {"inline_keyboard": rows}


def _start_platon(chat_id: int) -> None:
    with _STATE_LOCK:
        session = _PLATON_LAST_SESSION.get(chat_id, "")
        context = _PLATON_CONTEXT_BY_SESSION.get(session)
    if not session or not context:
        _send_message(
            chat_id,
            "<b>Платону пока не передана текущая модель.</b>\n\n"
            "Откройте Mini App, выполните новый расчёт и отправьте результат в Telegram. "
            "После этого нажмите «Спросить Платона» под итоговой карточкой.",
        )
        return
    with _STATE_LOCK:
        _PLATON_MODE[chat_id] = session
        _PLATON_HISTORY.setdefault(chat_id, [])
    _send_message(
        chat_id,
        "<b>Платон Сергеевич на связи</b>\n\n"
        "Задайте вопрос по текущему расчёту обычным сообщением. Например:\n"
        "• почему такой LLCR;\n"
        "• за сколько максимум можно купить проект;\n"
        "• что будет при росте СМР на 10%;\n"
        "• какая цена продаж нужна, чтобы проект проходил.\n\n"
        "Для выхода отправьте /cancel.",
        reply_markup=_platon_markup(chat_id),
    )


def _request_for_agent(chat_id: int) -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/telegram/platon",
        "raw_path": b"/telegram/platon",
        "query_string": b"",
        "headers": [],
        "client": ("telegram", int(chat_id)),
        "server": ("developaid", 443),
    }
    return Request(scope)


def _run_agent(chat_id: int, text: str) -> None:
    with _STATE_LOCK:
        session = _PLATON_MODE.get(chat_id) or _PLATON_LAST_SESSION.get(chat_id, "")
        context = copy.deepcopy(_PLATON_CONTEXT_BY_SESSION.get(session) or {})
        history = copy.deepcopy(_PLATON_HISTORY.get(chat_id) or [])
    if not context:
        _send_message(chat_id, "Контекст текущей модели потерян. Выполните новый расчёт и отправьте его в Telegram.")
        return

    history.append({"role": "user", "content": text})
    req = core.AgentChatRequest(
        message=text,
        inputs=context["inputs"],
        tep=context["tep"],
        rates=context.get("rates") or [],
        phasing=context.get("phasing") or {},
        history=history[-20:],
        selected_view=context.get("selected_view") or "all",
    )
    try:
        core._telegram_api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    except Exception:
        pass
    try:
        result = core.agent_chat(req, _request_for_agent(chat_id))
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        answer = str((result or {}).get("answer") or "Платон не вернул текстового ответа.").strip()
        proposals = (result or {}).get("proposals") or []
        proposal = proposals[-1] if proposals and isinstance(proposals[-1], dict) else None
        with _STATE_LOCK:
            _PLATON_HISTORY[chat_id] = (history + [{"role": "assistant", "content": answer}])[-20:]
            if proposal:
                _PLATON_PENDING[chat_id] = {"session": session, "proposal": copy.deepcopy(proposal)}
        safe = html.escape(answer)
        chunks = [safe[i:i + 3900] for i in range(0, len(safe), 3900)] or ["—"]
        for index, chunk in enumerate(chunks):
            _send_message(
                chat_id,
                chunk,
                reply_markup=_platon_markup(chat_id, proposal=bool(proposal)) if index == len(chunks) - 1 else None,
            )
    except Exception as exc:
        _send_message(
            chat_id,
            "<b>Платон не смог обработать текущий расчёт.</b>\n"
            + html.escape(f"{type(exc).__name__}: {exc}"),
            reply_markup=_platon_markup(chat_id),
        )


def _apply_proposal(chat_id: int) -> bool:
    with _STATE_LOCK:
        pending = copy.deepcopy(_PLATON_PENDING.get(chat_id) or {})
    proposal = pending.get("proposal") or {}
    patch = proposal.get("patch") if isinstance(proposal, dict) else None
    session = str(pending.get("session") or "")
    if not session or not isinstance(patch, dict) or not patch:
        return False
    with _STATE_LOCK:
        context = _PLATON_CONTEXT_BY_SESSION.get(session)
        if not context:
            return False
        context["inputs"].update(patch)
        session_data = copy.deepcopy(context.get("session_data") or {})
        overrides = copy.deepcopy(session_data.get("calc_overrides") or {})
        overrides.update(patch)
        new_url = core._telegram_web_app_url(
            chat_id,
            session_data.get("cad") or [],
            manual_tep=session_data.get("manual_tep"),
            calc_overrides=overrides,
            mode="edit",
        )
        _PLATON_LAST_URL[chat_id] = new_url
        _PLATON_PENDING.pop(chat_id, None)
    return True


def _handle_message(message: dict[str, Any]) -> None:
    chat_id, user_id, text = _extract_message(message)
    if not chat_id:
        return
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
    if command == "/status":
        _status_message(chat_id, user_id)
        return
    if command == "/help":
        _send_help(chat_id)
        return
    if command in {"/platon", "/платон"}:
        _start_platon(chat_id)
        return
    with _STATE_LOCK:
        active = chat_id in _PLATON_MODE
    if active and text:
        if command == "/cancel" or text.lower() in {"стоп", "отмена", "завершить"}:
            with _STATE_LOCK:
                _PLATON_MODE.pop(chat_id, None)
                _PLATON_PENDING.pop(chat_id, None)
            _send_message(chat_id, "Диалог с Платоном завершён.")
            return
        _run_agent(chat_id, text)
        return
    _ORIGINAL_HANDLE_MESSAGE(message)


def _handle_update(update: dict[str, Any]) -> None:
    query = update.get("callback_query") if isinstance(update, dict) else None
    if isinstance(query, dict):
        data = str(query.get("data") or "")
        message = query.get("message") or {}
        sender = query.get("from") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or sender.get("id") or 0)
        if data in {"ask_platon", "platon_stop", "platon_discard", "platon_apply", "show_help"}:
            _answer_callback(query)
            if data == "show_help":
                _send_help(chat_id)
            elif data == "ask_platon":
                _start_platon(chat_id)
            elif data == "platon_stop":
                with _STATE_LOCK:
                    _PLATON_MODE.pop(chat_id, None)
                    _PLATON_PENDING.pop(chat_id, None)
                _send_message(chat_id, "Диалог с Платоном завершён.")
            elif data == "platon_discard":
                with _STATE_LOCK:
                    _PLATON_PENDING.pop(chat_id, None)
                _send_message(chat_id, "Предложенные изменения не применены.", reply_markup=_platon_markup(chat_id))
            elif data == "platon_apply":
                if _apply_proposal(chat_id):
                    _send_message(
                        chat_id,
                        "Изменения применены к новой ссылке текущей модели.",
                        reply_markup=_platon_markup(chat_id),
                    )
                else:
                    _send_message(chat_id, "Не удалось применить предложенные изменения.", reply_markup=_platon_markup(chat_id))
            return
    message = update.get("message") if isinstance(update, dict) else None
    if isinstance(message, dict):
        _handle_message(message)
        return
    _ORIGINAL_HANDLE_UPDATE(update)


core._telegram_handle_message = _handle_message
core._telegram_handle_update = _handle_update


@app.on_event("startup")
def _configure_platon_command() -> None:
    if not core._telegram_token():
        return
    try:
        core._telegram_api("setMyCommands", {
            "commands": [
                {"command": "start", "description": "Главное меню"},
                {"command": "cadastre", "description": "ТЭП по кадастровым номерам"},
                {"command": "tep", "description": "Собрать ТЭП без кадастра"},
                {"command": "model", "description": "Открыть модель DevelopAid"},
                {"command": "platon", "description": "Спросить Платона"},
                {"command": "template", "description": "Скачать Excel-шаблон ТЭП"},
                {"command": "help", "description": "Инструкция по работе"},
                {"command": "status", "description": "Статус и версия"},
            ]
        })
    except Exception as exc:
        core._TELEGRAM_RUNTIME["last_error"] = str(exc)
