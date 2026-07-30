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
_RUNTIME_VERSION = "0.12.84"


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
_ORIGINAL_SEND_TEP_REVIEW = core._telegram_send_tep_review

_STATE_LOCK = threading.RLock()
_PLATON_MODE: dict[int, str] = {}
_PLATON_LAST_SESSION: dict[int, str] = {}
_PLATON_LAST_URL: dict[int, str] = {}
_PLATON_HISTORY: dict[int, list[dict[str, Any]]] = {}
_PLATON_CONTEXT_BY_SESSION: dict[str, dict[str, Any]] = {}
_PLATON_PENDING: dict[int, dict[str, Any]] = {}
# ТЭП, собранный самим ботом (кадастр, Excel-шаблон или диалог), до открытия
# мини-приложения. Позволяет Платону комментировать расчёт сразу.
_PLATON_TEP_CONTEXT: dict[int, dict[str, Any]] = {}
_TEP_REVIEW_CHATS: set[int] = set()

_TEP_COMMENT_REQUEST = (
    "Прокомментируй ТЭП текущего проекта как инвестиционный консультант девелопера. "
    "Ответ строго по структуре, без markdown-разметки, числа с единицами измерения:\n"
    "1. Состав ТЭП: совокупная ГНС, продаваемые площади, соотношение жилья и нежилья, "
    "паркинг, социальные объекты — что показывает баланс площадей.\n"
    "2. Посадка и плотность: плотность СПП на гектар, население, обеспеченность паркингом "
    "и социальной инфраструктурой относительно нормативной потребности.\n"
    "3. Экономика этого ТЭП при текущих ценах и себестоимости: выручка, CAPEX, EBITDA, "
    "чистая прибыль, маржинальность, NPV, LLCR, потребность в БРИДЖе и ПФ.\n"
    "4. Риски и слабые места именно ТЭП: что выглядит завышенным или заниженным, "
    "какие показатели надо перепроверить до сделки.\n"
    "5. Что уточнить дальше: от трёх до пяти конкретных пунктов."
)


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


def _resolve_context(chat_id: int) -> tuple[str, dict[str, Any]]:
    """Контекст для Платона: полный расчёт мини-приложения, иначе ТЭП от бота."""
    with _STATE_LOCK:
        session = _PLATON_MODE.get(chat_id) or _PLATON_LAST_SESSION.get(chat_id, "")
        context = _PLATON_CONTEXT_BY_SESSION.get(session)
        if context:
            return session, copy.deepcopy(context)
        tep_context = _PLATON_TEP_CONTEXT.get(chat_id)
        if tep_context:
            return "", copy.deepcopy(tep_context)
    return "", {}


def _has_model_context(chat_id: int) -> bool:
    return bool(_resolve_context(chat_id)[1])


def _context_label(context: dict[str, Any]) -> str:
    return (
        "ТЭП, собранный ботом"
        if str(context.get("origin") or "") == "tep"
        else "полный расчёт из мини-приложения"
    )


def _agent_ready() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _has_callback(rows: Any, callback: str) -> bool:
    return any(
        isinstance(button, dict) and button.get("callback_data") == callback
        for row in rows if isinstance(row, list)
        for button in row
    )


def _add_platon_button(chat_id: int, reply_markup: Any) -> Any:
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
    updated = copy.deepcopy(reply_markup)
    keyboard = updated.setdefault("inline_keyboard", [])
    # Карточка ТЭП и итоговая карточка расчёта: Платон может прокомментировать
    # их сразу, без открытия мини-приложения и без формулировки вопроса.
    with _STATE_LOCK:
        tep_review = chat_id in _TEP_REVIEW_CHATS
    if (tep_review or _has_model_context(chat_id)) and not _has_callback(rows, "platon_tep"):
        keyboard.append([{"text": "Прокомментировать ТЭП", "callback_data": "platon_tep"}])
    if not _has_callback(rows, "ask_platon"):
        keyboard.append([{"text": "Спросить Платона", "callback_data": "ask_platon"}])
    return updated


def _send_message(chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> Any:
    _remember_markup(chat_id, reply_markup)
    return _ORIGINAL_SEND_MESSAGE(
        chat_id,
        text,
        reply_markup=_add_platon_button(chat_id, reply_markup),
    )


core._telegram_send_message = _send_message


def _model_context_from_tep(chat_id: int, parsed: dict[str, Any]) -> dict[str, Any]:
    """ТЭП бота -> полный контекст модели, как его собирает мини-приложение."""
    inputs = copy.deepcopy(core.DEFAULT_INPUTS)
    inputs.update(parsed.get("inputs") or {})
    tep = copy.deepcopy(core.TEP_DEFAULT)
    for key, values in (parsed.get("tep") or {}).items():
        if key in tep and isinstance(values, dict):
            tep[key].update(values)
    manual_session = {
        "project_name": parsed.get("project_name") or "",
        "site_area_ha": parsed.get("site_area_ha") or 0,
        "source": parsed.get("source") or {},
        "inputs": copy.deepcopy(parsed.get("inputs") or {}),
        "tep": copy.deepcopy(parsed.get("tep") or {}),
    }
    return {
        "session": "",
        "chat_id": chat_id,
        "inputs": inputs,
        "tep": tep,
        "rates": [],
        "phasing": {},
        "selected_view": "all",
        "origin": "tep",
        "session_data": {"cad": [], "manual_tep": manual_session},
        "tep_summary": copy.deepcopy(parsed.get("summary") or {}),
        "project_name": str(parsed.get("project_name") or ""),
    }


def _send_tep_review(chat_id: int, parsed: dict[str, Any], *, dialog_mode: bool) -> None:
    try:
        context = _model_context_from_tep(chat_id, parsed)
    except Exception as exc:
        context = {}
        core._TELEGRAM_RUNTIME["last_error"] = "Платон/ТЭП: " + str(exc)
    with _STATE_LOCK:
        if context:
            _PLATON_TEP_CONTEXT[chat_id] = context
            _PLATON_HISTORY.pop(chat_id, None)
            _PLATON_PENDING.pop(chat_id, None)
        _TEP_REVIEW_CHATS.add(chat_id)
    try:
        _ORIGINAL_SEND_TEP_REVIEW(chat_id, parsed, dialog_mode=dialog_mode)
    finally:
        with _STATE_LOCK:
            _TEP_REVIEW_CHATS.discard(chat_id)


core._telegram_send_tep_review = _send_tep_review


def _help_markup(chat_id: int) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = [
        [{"text": "Расчёт по кадастровым номерам", "callback_data": "flow_cad_yes"}],
        [{"text": "Собрать ТЭП без кадастра", "callback_data": "flow_cad_no"}],
        [{"text": "Прокомментировать ТЭП", "callback_data": "platon_tep"}],
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
        "Отправьте кадастровый номер, адрес или координаты — одним сообщением. "
        "Выбирать методику не нужно: DevelopAid сам определит, где участок, и посчитает "
        "по правилам, которые к нему применимы.\n\n"

        "<b>Шаг 1. Отправьте участок</b>\n"
        "• кадастровый номер: <code>77:02:0016009:1934</code>;\n"
        "• несколько номеров сразу — через запятую или с новой строки, они соберутся в одну территорию;\n"
        "• адрес: <i>Московская область, г. Мытищи, ул. Мира, 1</i>;\n"
        "• координаты: <code>55.910500, 37.736500</code>.\n\n"

        "<b>Шаг 2. Бот определит территорию и методику</b>\n\n"
        "<b>Москва</b> — считает калькулятор нормативных ТЭП ГлавАПУ.\n"
        "Территория формируется по кадастровым номерам, открывается штатный расчёт, "
        "таблица ТЭП переносится в модель целиком. Сюда же относятся Троицкий и Новомосковский "
        "округа: у них кадастровые номера начинаются с 50, но это Москва, и считаются они "
        "по московским правилам.\n\n"

        "<b>Московская область</b> — считает формула из нормативных документов.\n"
        "Площадь участка берётся из ЕГРН, площадь квартир — по плотности, дальше нормативы РНГП "
        "Московской области дают население, ДОО, школу, поликлинику, паркинг, озеленение и "
        "нежилые помещения. Плата за смену ВРИ считается по УПКС кадастрового квартала и средней "
        "рыночной стоимости 1 м² из распоряжения Комитета по ценам и тарифам МО № 114-Р. "
        "Все справочники внутри — загружать ничего не надо.\n\n"

        "<b>Другой регион</b> — экспертная оценка.\n"
        "Нормативных калькуляторов для остальных регионов нет, поэтому ТЭП не рассчитывается "
        "автоматически. Бот покажет сведения ЕГРН по участку — площадь, категорию, ВРИ, "
        "кадастровую стоимость — и предложит два пути: ответить на вопросы бота или скачать "
        "Excel-шаблон ТЭП, заполнить и отправить обратно. Экономика дальше считается так же "
        "полно, как для Москвы и области.\n\n"

        "<b>Шаг 3. Проверьте карточку и откройте мини-приложение</b>\n"
        "Перед применением показывается сводка: площади, население, социальные объекты, плата за ВРИ. "
        "В мини-приложении меняются цены и темпы продаж, себестоимость, сроки, ключевая ставка, "
        "БРИДЖ, проектное финансирование, социальная нагрузка и условия платы за ВРИ — рассрочка, "
        "льгота, источники оплаты. Для крупного проекта включается очередность.\n\n"

        "<b>Шаг 4. Заберите результат</b>\n"
        "Бот присылает карточку с показателями, PDF-отчёт и ZIP с моделью. В архиве два файла: "
        "<b>00_Модель</b> — живая книга на формулах, где правка вводной пересчитывает весь расчёт, "
        "и <b>90_Детализация</b> — помесячная и поквартальная разбивка, график платежей ВРИ и диаграммы.\n\n"

        "<b>Шаг 5. Спросите Платона Сергеевича Федоскина</b>\n"
        "«Прокомментировать ТЭП» (или /comment) — разбор состава и плотности, экономики при текущих "
        "ценах, рисков и того, что уточнить до сделки. Работает сразу после карточки ТЭП.\n"
        "«Спросить Платона» — диалог по текущей модели: объясняет показатели, сравнивает сценарии, "
        "подбирает цену покупки, цены продаж, СМР и параметры финансирования.\n\n"

        "<i>Расчёт является предварительной инвестиционной моделью, а не отчётом оценщика "
        "и не решением банка. Сведения ЕГРН справочные: для сделки нужна выписка Росреестра.</i>",
        reply_markup=_help_markup(chat_id),
    )


def _status_message(chat_id: int, user_id: int) -> None:
    configured = bool(core._TELEGRAM_RUNTIME.get("configured"))
    _, context = _resolve_context(chat_id)
    if context:
        platon_state = "контекст загружен · " + _context_label(context)
    else:
        platon_state = "ожидает ТЭП или расчёт"
    if not _agent_ready():
        platon_state += " · OPENAI_API_KEY не настроен"
    _send_message(
        chat_id,
        f"<b>DevelopAid bot:</b> {'подключён' if configured else 'запускается'}\n"
        f"Telegram ID: <code>{user_id}</code>\n"
        f"Версия: {_RUNTIME_VERSION}\n"
        f"Платон: {platon_state}",
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
    session, context = _resolve_context(chat_id)
    if not context:
        _send_message(
            chat_id,
            "<b>Платону пока не передан проект.</b>\n\n"
            "Соберите ТЭП — отправьте кадастровые номера, заполненный Excel-шаблон "
            "или ответьте на вопросы бота. Платон подключится сразу после карточки ТЭП. "
            "Полный расчёт он получит после того, как вы отправите результат из мини-приложения.",
        )
        return
    with _STATE_LOCK:
        _PLATON_MODE[chat_id] = session
        _PLATON_HISTORY.setdefault(chat_id, [])
    _send_message(
        chat_id,
        "<b>Платон Сергеевич на связи</b>\n"
        f"<i>Контекст: {_context_label(context)}.</i>\n\n"
        "Задайте вопрос по текущему расчёту обычным сообщением. Например:\n"
        "• почему такой LLCR;\n"
        "• за сколько максимум можно купить проект;\n"
        "• что будет при росте СМР на 10%;\n"
        "• какая цена продаж нужна, чтобы проект проходил.\n\n"
        "Готовый разбор ТЭП — кнопка «Прокомментировать ТЭП» или команда /comment.\n"
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


def _run_agent(chat_id: int, text: str, *, intro: str = "") -> None:
    session, context = _resolve_context(chat_id)
    with _STATE_LOCK:
        history = copy.deepcopy(_PLATON_HISTORY.get(chat_id) or [])
    if not context:
        _send_message(
            chat_id,
            "Контекст проекта потерян. Соберите ТЭП заново или отправьте расчёт из мини-приложения.",
        )
        return
    if not _agent_ready():
        _send_message(
            chat_id,
            "<b>Платон отключён на сервере.</b>\n"
            "Не задан ключ <code>OPENAI_API_KEY</code> — без него бот не может комментировать расчёт. "
            "Добавьте переменную окружения в настройках сервиса и перезапустите его.",
        )
        return
    if intro:
        _send_message(chat_id, intro)

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
    if not isinstance(patch, dict) or not patch:
        return False
    with _STATE_LOCK:
        # Правка ложится либо в контекст мини-приложения, либо в ТЭП бота.
        context = _PLATON_CONTEXT_BY_SESSION.get(session) if session else _PLATON_TEP_CONTEXT.get(chat_id)
        if not context:
            return False
        context["inputs"].update(patch)
        session_data = copy.deepcopy(context.get("session_data") or {})
        overrides = copy.deepcopy(session_data.get("calc_overrides") or {})
        overrides.update(patch)
        try:
            new_url = core._telegram_web_app_url(
                chat_id,
                session_data.get("cad") or [],
                manual_tep=session_data.get("manual_tep"),
                calc_overrides=overrides,
                mode="edit",
            )
        except Exception as exc:
            core._TELEGRAM_RUNTIME["last_error"] = "Платон/применение: " + str(exc)
            new_url = ""
        if new_url:
            _PLATON_LAST_URL[chat_id] = new_url
        _PLATON_PENDING.pop(chat_id, None)
    return True


def _comment_tep(chat_id: int) -> None:
    """Готовый разбор ТЭП без формулировки вопроса пользователем."""
    _, context = _resolve_context(chat_id)
    if not context:
        _send_message(
            chat_id,
            "<b>Комментировать пока нечего.</b>\n\n"
            "Сначала соберите ТЭП: отправьте кадастровые номера московского участка, "
            "заполненный Excel-шаблон или ответьте на вопросы бота.",
        )
        return
    # Разбор ТЭП не переводит чат в режим диалога: обычный текст по-прежнему
    # обрабатывает основной сценарий бота, а вопросы — кнопка «Спросить Платона».
    project = str(context.get("project_name") or "").strip()
    intro = (
        "<b>Платон Сергеевич разбирает ТЭП</b>\n"
        + (f"Проект: <b>{html.escape(project)}</b>\n" if project else "")
        + f"<i>Источник: {_context_label(context)}. Считает движок модели, комментирует Платон.</i>"
    )
    _run_agent(chat_id, _TEP_COMMENT_REQUEST, intro=intro)


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
    if command in {"/comment", "/тэп_комментарий"}:
        _comment_tep(chat_id)
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
    # Вопрос по посчитанному проекту — это вопрос Платону Сергеевичу, а не адрес
    # участка. Раньше «Какая цена объекта оптимальна?» уходило искать в ЕГРН и
    # возвращалось с «участок не найден».
    if text and not command and core._looks_like_question(text) and _has_model_context(chat_id):
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
        if data in {"ask_platon", "platon_tep", "platon_stop", "platon_discard", "platon_apply", "show_help"}:
            _answer_callback(query)
            if data == "show_help":
                _send_help(chat_id)
            elif data == "ask_platon":
                _start_platon(chat_id)
            elif data == "platon_tep":
                _comment_tep(chat_id)
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
                {"command": "comment", "description": "Комментарий Платона к ТЭП"},
                {"command": "template", "description": "Скачать Excel-шаблон ТЭП"},
                {"command": "help", "description": "Инструкция по работе"},
                {"command": "status", "description": "Статус и версия"},
            ]
        })
    except Exception as exc:
        core._TELEGRAM_RUNTIME["last_error"] = str(exc)
