from __future__ import annotations

import asyncio
import copy
import importlib.util
import inspect
import json
import sys
import threading
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints
from urllib.parse import parse_qs, urlparse

_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_PATH = _ROOT / "main.py"
_SPEC = importlib.util.spec_from_file_location("developaid_legacy", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("DevelopAid: не удалось загрузить основное приложение")
legacy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = legacy
_SPEC.loader.exec_module(legacy)

app = legacy.app
app.version = "0.12.36"

_PLATON_MODE: dict[int, dict[str, Any]] = {}
_PLATON_LAST_SESSION: dict[int, str] = {}
_PLATON_LAST_URL: dict[int, str] = {}
_PLATON_HISTORY: dict[int, list[dict[str, str]]] = {}
_PLATON_PENDING: dict[int, dict[str, Any]] = {}

_ORIGINAL_SEND_MESSAGE = legacy._telegram_send_message
_ORIGINAL_HANDLE_MESSAGE = legacy._telegram_handle_message


def _message_parts(update: dict[str, Any]) -> tuple[int, int, str, dict[str, Any] | None]:
    callback = update.get("callback_query") if isinstance(update, dict) else None
    if callback is None and isinstance(update, dict) and "data" in update and "message" in update:
        callback = update
    if isinstance(callback, dict):
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        sender = callback.get("from") or {}
        return int(chat.get("id") or 0), int(sender.get("id") or 0), "", callback

    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        message = update if isinstance(update, dict) else {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    return (
        int(chat.get("id") or 0),
        int(sender.get("id") or 0),
        str(message.get("text") or "").strip(),
        None,
    )


def _remember_web_app(chat_id: int, reply_markup: Any) -> None:
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
            _PLATON_LAST_URL[chat_id] = url
            query = parse_qs(urlparse(url).query)
            for key in ("session", "telegram_session", "manual_session", "token"):
                value = (query.get(key) or [""])[0].strip()
                if value:
                    _PLATON_LAST_SESSION[chat_id] = value
                    break


def _with_platon_button(reply_markup: Any) -> Any:
    if not isinstance(reply_markup, dict):
        return reply_markup
    rows = reply_markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return reply_markup
    for row in rows:
        if isinstance(row, list):
            for button in row:
                if isinstance(button, dict) and button.get("callback_data") == "ask_platon":
                    return reply_markup
    updated = copy.deepcopy(reply_markup)
    updated.setdefault("inline_keyboard", []).append([
        {"text": "Спросить Платона", "callback_data": "ask_platon"}
    ])
    return updated


def _send_message(chat_id: int, text: str, *args: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(_ORIGINAL_SEND_MESSAGE)
    bound = signature.bind_partial(chat_id, text, *args, **kwargs)
    reply_markup = bound.arguments.get("reply_markup")
    _remember_web_app(chat_id, reply_markup)
    if isinstance(reply_markup, dict):
        bound.arguments["reply_markup"] = _with_platon_button(reply_markup)
    return _ORIGINAL_SEND_MESSAGE(*bound.args, **bound.kwargs)


def _answer_callback(callback: dict[str, Any]) -> None:
    callback_id = str(callback.get("id") or "")
    if not callback_id:
        return
    try:
        legacy._telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
    except Exception:
        pass


def _current_session(chat_id: int) -> str:
    direct = _PLATON_LAST_SESSION.get(chat_id, "")
    if direct:
        return direct
    for name, value in vars(legacy).items():
        if "SESSION" not in name.upper() or not isinstance(value, dict):
            continue
        for key, record in reversed(list(value.items())):
            if not isinstance(record, dict):
                continue
            record_chat = record.get("chat_id") or record.get("telegram_chat_id")
            if str(record_chat or "") != str(chat_id):
                continue
            token = record.get("session") or record.get("token") or key
            if isinstance(token, str) and token:
                _PLATON_LAST_SESSION[chat_id] = token
                return token
    return ""


def _session_context(session: str) -> dict[str, Any]:
    verifier = getattr(legacy, "_telegram_verify_session", None)
    if not callable(verifier) or not session:
        return {}
    try:
        value = verifier(session)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _agent_route() -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == "/agent/chat":
            return route
    raise RuntimeError("Серверный агент /agent/chat не найден")


def _default_for_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (list, tuple, set):
        return []
    if origin is dict:
        return {}
    if origin is not None and type(None) in args:
        return None
    if annotation is str:
        return ""
    if annotation is bool:
        return False
    if annotation in (int, float):
        return 0
    return {}


def _build_agent_request(endpoint: Any, message: str, session: str, context: dict[str, Any], history: list[dict[str, str]]) -> tuple[list[Any], dict[str, Any]]:
    signature = inspect.signature(endpoint)
    try:
        hints = get_type_hints(endpoint, vars(legacy), vars(legacy))
    except Exception:
        hints = {}
    args: list[Any] = []
    kwargs: dict[str, Any] = {}

    for parameter in signature.parameters.values():
        annotation = hints.get(parameter.name, parameter.annotation)
        fields = getattr(annotation, "model_fields", None)
        if isinstance(fields, dict):
            payload: dict[str, Any] = {}
            for field_name, field in fields.items():
                lower = field_name.lower()
                if lower in {"message", "question", "prompt", "text", "query"}:
                    payload[field_name] = message
                elif lower in {"session", "session_id", "telegram_session"}:
                    payload[field_name] = session
                elif lower in {"history", "messages", "chat_history"}:
                    payload[field_name] = history
                elif lower in {"context", "session_context", "project_context"}:
                    payload[field_name] = context
                elif field_name in context:
                    payload[field_name] = context[field_name]
                elif lower == "calc_overrides":
                    payload[field_name] = context.get("calc_overrides", {})
                elif lower in {"tep", "manual_tep"}:
                    payload[field_name] = context.get("tep") or context.get("manual_tep") or {}
                elif lower in {"inputs", "model_inputs", "overrides"}:
                    payload[field_name] = context.get("calc_overrides") or context.get("inputs") or {}
                elif lower in {"summary", "calculation", "calc"}:
                    payload[field_name] = context.get("summary") or context.get("calculation") or {}
                elif getattr(field, "is_required", lambda: False)():
                    payload[field_name] = _default_for_annotation(getattr(field, "annotation", Any))
            value: Any = annotation(**payload)
        elif parameter.name in {"message", "question", "prompt", "text", "query"}:
            value = message
        elif parameter.name in {"session", "session_id"}:
            value = session
        elif parameter.name in {"context", "session_context"}:
            value = context
        elif parameter.default is not inspect._empty:
            continue
        else:
            value = _default_for_annotation(annotation)

        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(value)
        else:
            kwargs[parameter.name] = value
    return args, kwargs


def _run_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    box: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(value)
        except BaseException as exc:
            error["value"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=120)
    if thread.is_alive():
        raise TimeoutError("Платон не ответил за 120 секунд")
    if "value" in error:
        raise error["value"]
    return box.get("value")


def _normalize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    elif hasattr(result, "body"):
        body = getattr(result, "body", b"")
        if isinstance(body, bytes):
            try:
                result = json.loads(body.decode("utf-8"))
            except Exception:
                result = {"answer": body.decode("utf-8", errors="replace")}
    if isinstance(result, str):
        return {"answer": result}
    if isinstance(result, dict):
        return result
    return {"answer": str(result)}


def _answer_text(data: dict[str, Any]) -> str:
    for key in ("answer", "reply", "response", "message", "text", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _answer_text(value)
            if nested:
                return nested
    return "Платон выполнил расчёт, но не вернул текстового пояснения."


def _proposed_changes(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("proposed_changes", "changes", "calc_overrides", "overrides", "patch"):
        value = data.get(key)
        if isinstance(value, dict) and value:
            return value
    for value in data.values():
        if isinstance(value, dict):
            nested = _proposed_changes(value)
            if nested:
                return nested
    return {}


def _split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _open_model_markup(chat_id: int, include_decision: bool = False) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    if include_decision:
        rows.extend([
            [{"text": "Применить в модель", "callback_data": "platon_apply"}],
            [{"text": "Не применять", "callback_data": "platon_discard"}],
        ])
    url = _PLATON_LAST_URL.get(chat_id, "")
    if url:
        rows.append([{"text": "Открыть текущий расчёт", "web_app": {"url": url}}])
    rows.append([{"text": "Завершить диалог", "callback_data": "platon_stop"}])
    return {"inline_keyboard": rows}


def _start_platon(chat_id: int) -> None:
    session = _current_session(chat_id)
    if not session:
        _send_message(chat_id, "Сначала выполните расчёт или загрузите ТЭП. После появления итоговой карточки Платон сможет работать с текущей моделью.")
        return
    _PLATON_MODE[chat_id] = {"session": session}
    _PLATON_HISTORY.setdefault(chat_id, [])
    _send_message(
        chat_id,
        "<b>Платон Сергеевич на связи</b>\n\n"
        "Задайте вопрос по текущему расчёту обычным текстом. Например:\n"
        "• почему такой LLCR;\n"
        "• за сколько максимум можно купить проект;\n"
        "• какая цена продаж нужна;\n"
        "• что изменится при росте СМР на 10%;\n"
        "• подбери параметры, чтобы проект проходил.\n\n"
        "Для выхода отправьте /cancel.",
        reply_markup=_open_model_markup(chat_id),
    )


def _ask_platon(chat_id: int, text: str) -> None:
    mode = _PLATON_MODE.get(chat_id) or {}
    session = str(mode.get("session") or _current_session(chat_id))
    if not session:
        _send_message(chat_id, "Текущая расчётная сессия не найдена. Выполните расчёт заново.")
        _PLATON_MODE.pop(chat_id, None)
        return
    history = _PLATON_HISTORY.setdefault(chat_id, [])
    context = _session_context(session)
    history.append({"role": "user", "content": text})
    try:
        route = _agent_route()
        args, kwargs = _build_agent_request(route.endpoint, text, session, context, history)
        data = _normalize_result(_run_awaitable(route.endpoint(*args, **kwargs)))
        answer = _answer_text(data)
        changes = _proposed_changes(data)
        history.append({"role": "assistant", "content": answer})
        if len(history) > 20:
            del history[:-20]
        if changes:
            _PLATON_PENDING[chat_id] = {"session": session, "changes": changes}
        parts = _split_message(answer)
        for index, part in enumerate(parts):
            markup = _open_model_markup(chat_id, include_decision=bool(changes)) if index == len(parts) - 1 else None
            _send_message(chat_id, part, reply_markup=markup)
    except Exception as exc:
        _send_message(chat_id, "Платон не смог обработать вопрос через текущий расчёт: " + str(exc), reply_markup=_open_model_markup(chat_id))


def _apply_pending(chat_id: int) -> bool:
    pending = _PLATON_PENDING.get(chat_id)
    if not pending:
        return False
    session = str(pending.get("session") or "")
    changes = pending.get("changes")
    if not isinstance(changes, dict):
        return False
    applied = False
    context = _session_context(session)
    overrides = context.get("calc_overrides")
    if isinstance(overrides, dict):
        overrides.update(changes)
        applied = True
    for name, store in vars(legacy).items():
        if "SESSION" not in name.upper() or not isinstance(store, dict):
            continue
        record = store.get(session)
        if isinstance(record, dict):
            target = record.setdefault("calc_overrides", {})
            if isinstance(target, dict):
                target.update(changes)
                applied = True
    if applied:
        _PLATON_PENDING.pop(chat_id, None)
    return applied


def _handle_message(update: dict[str, Any]) -> None:
    chat_id, _user_id, text, callback = _message_parts(update)
    if callback is not None:
        data = str(callback.get("data") or "")
        if data == "ask_platon":
            _answer_callback(callback)
            _start_platon(chat_id)
            return
        if data == "platon_stop":
            _answer_callback(callback)
            _PLATON_MODE.pop(chat_id, None)
            _PLATON_PENDING.pop(chat_id, None)
            _send_message(chat_id, "Диалог с Платоном завершён.")
            return
        if data == "platon_discard":
            _answer_callback(callback)
            _PLATON_PENDING.pop(chat_id, None)
            _send_message(chat_id, "Предложенные изменения не применены.", reply_markup=_open_model_markup(chat_id))
            return
        if data == "platon_apply":
            _answer_callback(callback)
            if _apply_pending(chat_id):
                _send_message(chat_id, "Изменения применены к текущей сессии.", reply_markup=_open_model_markup(chat_id))
            else:
                _send_message(chat_id, "Автоматически применить изменения к этой сессии не удалось. Откройте текущий расчёт и внесите их через модель.", reply_markup=_open_model_markup(chat_id))
            return

    if text.lower() in {"/platon", "/платон"}:
        _start_platon(chat_id)
        return
    if chat_id in _PLATON_MODE and text:
        if text.lower() in {"/cancel", "отмена", "стоп", "завершить"}:
            _PLATON_MODE.pop(chat_id, None)
            _PLATON_PENDING.pop(chat_id, None)
            _send_message(chat_id, "Диалог с Платоном завершён.")
            return
        _ask_platon(chat_id, text)
        return
    _ORIGINAL_HANDLE_MESSAGE(update)

legacy._telegram_send_message = _send_message
legacy._telegram_handle_message = _handle_message

for _name, _value in vars(legacy).items():
    if _name not in globals():
        globals()[_name] = _value
