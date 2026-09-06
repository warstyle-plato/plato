from __future__ import annotations

import asyncio
import copy
import html
import json
import re
import importlib.util
import inspect
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

_ROOT = Path(__file__).resolve().parent


def _load_core():
    spec = importlib.util.spec_from_file_location("developaid_core", _ROOT / "main_legacy.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("DevelopAid: cannot load main_legacy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


core = _load_core()
# Версия объявлена в движке и берётся оттуда: своя копия здесь уже разъезжалась
# с движковой, и тогда `/status` бота показывал одно, а страница и `/health` —
# другое, из-за чего выкаченная версия выглядела невыкаченной.
_RUNTIME_VERSION = core.VERSION
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

# Сервис работает в несколько воркеров, и память у них раздельная: страница
# отправляет контекст в один процесс, а нажатие «Спросить Платона» приходит
# вебхуком в другой — и тот отвечает «проект не передан» по свежему расчёту.
# Поэтому контекст дублируется на диск: словари остаются быстрым кешем, диск —
# общей памятью воркеров.
_STATE_DIR = Path(os.getenv("PLATON_STATE_DIR", "").strip() or (_ROOT / "data" / "platon_state"))
_STATE_TTL_SECONDS = 3 * 24 * 3600


def _state_file(name: str) -> Path:
    import hashlib
    return _STATE_DIR / (hashlib.sha256(name.encode("utf-8")).hexdigest()[:32] + ".json")


def _state_write(name: str, payload: dict[str, Any]) -> None:
    import json
    import time
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = _state_file(name)
        # Пишем через временный файл: соседний воркер не должен прочитать
        # половину записи.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        cutoff = time.time() - _STATE_TTL_SECONDS
        for stale in _STATE_DIR.glob("*.json"):
            try:
                if stale.stat().st_mtime < cutoff:
                    stale.unlink()
            except OSError:
                pass
    except Exception:
        # Диск — подстраховка, а не единственный источник: молча продолжаем.
        pass


def _state_read(name: str) -> dict[str, Any]:
    import json
    try:
        path = _state_file(name)
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

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
            # Только адрес кнопки. Сессию отсюда брать нельзя: каждая кнопка
            # «Открыть и изменить расчёт» подписывается заново, и её токен
            # отличается от того, под которым мини-приложение сдало контекст.
            # Пока эта строка перезаписывала указатель чата, карточка результата
            # тут же уводила Платона на сессию, у которой контекста нет вовсе.
            with _STATE_LOCK:
                changed = _PLATON_LAST_URL.get(chat_id) != url
                _PLATON_LAST_URL[chat_id] = url
            if changed:
                # Адрес нужен и соседнему воркеру: нажатие придёт в любой из них.
                pointer = _state_read(f"chat:{chat_id}")
                pointer["url"] = url
                _state_write(f"chat:{chat_id}", pointer)


def _resolve_context(chat_id: int) -> tuple[str, dict[str, Any]]:
    """Контекст для Платона: полный расчёт мини-приложения, иначе ТЭП от бота.

    Ищем по чату, а не по токену сессии. Токен подписывается заново под каждую
    кнопку «Открыть и изменить расчёт», поэтому он не опознаёт проект: расчёт
    сдан под одним токеном, а вопрос Платону приходит позже и уже под другим.
    Полный расчёт может лежать и в памяти соседнего воркера, поэтому диск
    проверяется наравне с памятью. Грубый ТЭП от бота — последняя очередь: это
    прикидка на умолчаниях, где ни класс жилья, ни цены не те, что в модели.
    """
    pointer = _state_read(f"chat:{chat_id}")
    with _STATE_LOCK:
        session = _PLATON_MODE.get(chat_id) or _PLATON_LAST_SESSION.get(chat_id, "")
        context = _PLATON_CONTEXT_BY_SESSION.get(session) if session else None
        if context:
            return session, copy.deepcopy(context)

    if session:
        stored = _state_read(f"session:{session}")
        if stored:
            with _STATE_LOCK:
                _PLATON_CONTEXT_BY_SESSION[session] = stored
                _PLATON_LAST_SESSION[chat_id] = session
            return session, copy.deepcopy(stored)

    stored = pointer.get("context")
    if not stored:
        pointer_session = str(pointer.get("session") or "")
        stored = _state_read(f"session:{pointer_session}") if pointer_session else {}
    if stored:
        session = str(stored.get("session") or pointer.get("session") or "")
        with _STATE_LOCK:
            if session:
                _PLATON_CONTEXT_BY_SESSION[session] = stored
                _PLATON_LAST_SESSION[chat_id] = session
        return session, copy.deepcopy(stored)

    with _STATE_LOCK:
        tep_context = _PLATON_TEP_CONTEXT.get(chat_id)
    if tep_context:
        return "", copy.deepcopy(tep_context)
    tep_context = pointer.get("tep_context")
    if tep_context:
        with _STATE_LOCK:
            _PLATON_TEP_CONTEXT[chat_id] = tep_context
        return "", copy.deepcopy(tep_context)
    return "", {}


def _dialog_start(chat_id: int, session: str) -> None:
    """Открывает диалог с Платоном и запоминает это на диске.

    Флаг жил только в памяти воркера, а следующее сообщение приходит вебхуком
    в любой из них. Сосед про диалог не знал и отправлял реплику искать участок
    в ЕГРН — «Участок по этому адресу не найден» в ответ на замечание по очереди.
    """
    with _STATE_LOCK:
        _PLATON_MODE[chat_id] = session
        _PLATON_HISTORY.setdefault(chat_id, [])
    pointer = _state_read(f"chat:{chat_id}")
    pointer["dialog"] = True
    _state_write(f"chat:{chat_id}", pointer)


def _dialog_stop(chat_id: int) -> None:
    with _STATE_LOCK:
        _PLATON_MODE.pop(chat_id, None)
        _PLATON_PENDING.pop(chat_id, None)
    pointer = _state_read(f"chat:{chat_id}")
    if pointer.pop("dialog", None) is not None:
        _state_write(f"chat:{chat_id}", pointer)


def _dialog_active(chat_id: int) -> bool:
    with _STATE_LOCK:
        if chat_id in _PLATON_MODE:
            return True
    if not _state_read(f"chat:{chat_id}").get("dialog"):
        return False
    # Диалог открыл сосед: подхватываем его и здесь, чтобы не читать диск
    # на каждое сообщение.
    with _STATE_LOCK:
        _PLATON_MODE.setdefault(chat_id, _PLATON_LAST_SESSION.get(chat_id, ""))
        _PLATON_HISTORY.setdefault(chat_id, [])
    return True


def _has_model_context(chat_id: int) -> bool:
    return bool(_resolve_context(chat_id)[1])


def _context_label(context: dict[str, Any]) -> str:
    return (
        "ТЭП, собранный ботом"
        if str(context.get("origin") or "") == "tep"
        else "полный расчёт из мини-приложения"
    )


def _proxy_configured() -> bool:
    return bool(
        os.getenv("PLATO_AI_URL", "").strip()
        and os.getenv("PLATO_AI_PROXY_SECRET", "").strip()
    )


def _agent_ready() -> bool:
    """Готовность считается по маршруту, а не по одному ключу.

    На ядре Яндекса OPENAI_API_KEY отсутствует намеренно, и прежняя проверка
    объявляла Платона отключённым при исправно настроенном прокси на Render.
    """
    return _proxy_configured() or bool(os.getenv("OPENAI_API_KEY", "").strip())


def _agent_unready_reason() -> str:
    """Чего именно не хватает — ответ разный для ядра и для Render."""
    if os.getenv("PLATO_AI_URL", "").strip():
        return "не задан <code>PLATO_AI_PROXY_SECRET</code>"
    return "не заданы <code>PLATO_AI_URL</code> и <code>PLATO_AI_PROXY_SECRET</code>"


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
    # Мини-приложение закрывается сразу после расчёта, поэтому до кнопки
    # «Скачать модель (ZIP)» внутри уже не добраться: путь к модели должен
    # быть в чате.
    if _has_model_context(chat_id) and not _has_callback(rows, "send_model"):
        keyboard.append([{"text": "Скачать модель (Excel)", "callback_data": "send_model"}])
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
    if context:
        pointer = _state_read(f"chat:{chat_id}")
        pointer["tep_context"] = context
        _state_write(f"chat:{chat_id}", pointer)
    try:
        _ORIGINAL_SEND_TEP_REVIEW(chat_id, parsed, dialog_mode=dialog_mode)
    finally:
        with _STATE_LOCK:
            _TEP_REVIEW_CHATS.discard(chat_id)


core._telegram_send_tep_review = _send_tep_review


def _start_vritep(chat_id: int) -> None:
    _send_message(
        chat_id,
        "<b>Посчитать стоимость ВРИ и ТЭП</b>\n"
        "Выберите регион участка:",
        reply_markup={"inline_keyboard": [
            [{"text": "Москва", "callback_data": "vritep_msk"}],
            [{"text": "Московская область", "callback_data": "vritep_mo"}],
        ]},
    )


def _vritep_ask_input(chat_id: int, region: str) -> None:
    pointer = _state_read(f"chat:{chat_id}")
    # МО начинается с плотности: калькулятор ГлавАПУ ведёт её в тыс. м²
    # поэтажной площади на гектар, и без явного вопроса пользователи получали
    # расчёт на зашитом умолчании, не подозревая об этом.
    pointer["vritep"] = "mo_density" if region == "mo" else region
    pointer.pop("vritep_density", None)
    _state_write(f"chat:{chat_id}", pointer)
    if region == "mo":
        _send_message(
            chat_id,
            "<b>Московская область.</b> Какая плотность застройки?\n"
            "Пришлите число в тыс. м² поэтажной площади на га — "
            "по умолчанию <b>35</b> (≈ 21 400 м² квартир/га).\n"
            "Метрика РНГП тоже понимается: <code>квартир 8700</code> — "
            "это м² квартир на га.\n"
            "Можно сразу прислать участок — тогда возьмётся умолчание 35.",
        )
    else:
        _send_message(
            chat_id,
            "<b>Москва.</b> Пришлите кадастровый номер или адрес участка — "
            "территорию и коэффициенты определит анализ ГлавАПУ.",
        )


# 35 тыс. м² СПП/га умолчания ГлавАПУ: квартиры из СПП — 94% жилой доли и
# 65% выхода продаваемой площади, то есть ≈ 21 385 м² квартир на гектар.
_VRITEP_MO_DENSITY_DEFAULT = 35 * 1000 * 0.94 * 0.65


def _vritep_mo_density(text: str) -> float | None:
    """Число из ответа на вопрос о плотности: до 1000 — тыс. м² СПП/га
    (метрика ГлавАПУ), больше — уже м² квартир/га (метрика РНГП)."""
    stripped = text.strip()
    apartments = re.search(r"квартир\w*\s*[:=]?\s*([\d\s.,]+)", stripped, re.IGNORECASE)
    if apartments:
        return float(apartments.group(1).replace(" ", "").replace(",", "."))
    if not re.fullmatch(r"[\d\s.,]+", stripped):
        return None
    value = float(stripped.replace(" ", "").replace(",", "."))
    if value <= 0:
        return None
    return value * 1000 * 0.94 * 0.65 if value <= 1000 else value


def _vritep_region(chat_id: int) -> str:
    return str(_state_read(f"chat:{chat_id}").get("vritep") or "")


def _vritep_clear(chat_id: int) -> None:
    pointer = _state_read(f"chat:{chat_id}")
    removed = pointer.pop("vritep", None) is not None
    removed = pointer.pop("vritep_density", None) is not None or removed
    if removed:
        _state_write(f"chat:{chat_id}", pointer)


def _vritep_handle_text(chat_id: int, text: str) -> bool:
    region = _vritep_region(chat_id)
    if not region or not text:
        return False
    saved_density = None
    if region == "mo_density":
        density_answer = _vritep_mo_density(text)
        if density_answer is not None:
            pointer = _state_read(f"chat:{chat_id}")
            pointer["vritep"] = "mo"
            pointer["vritep_density"] = density_answer
            _state_write(f"chat:{chat_id}", pointer)
            _send_message(
                chat_id,
                f"Плотность принята: <b>{density_answer:,.0f}".replace(",", " ")
                + " м² квартир/га</b>.\n"
                "Теперь пришлите кадастровый номер участка — площадь возьмётся "
                "из ЕГРН.\nБез кадастра можно так: "
                "<code>10,5 га Городской округ Мытищи</code>.",
            )
            return True
        # Пришёл сразу участок — плотность остаётся умолчанием ГлавАПУ.
        region = "mo"
        saved_density = _VRITEP_MO_DENSITY_DEFAULT
    elif region == "mo":
        raw = _state_read(f"chat:{chat_id}").get("vritep_density")
        try:
            saved_density = float(raw) if raw else None
        except (TypeError, ValueError):
            saved_density = None
        if not saved_density:
            saved_density = _VRITEP_MO_DENSITY_DEFAULT
    _vritep_clear(chat_id)
    _send_message(chat_id, "<i>Считаю ВРИ и ТЭП…</i>")
    query, area, district, density = text.strip(), None, None, saved_density
    if region == "mo":
        # «плотность 8700» в любом месте сообщения — м² квартир на гектар.
        density_match = re.search(r"плотн\w*\s*[:=]?\s*([\d\s.,]+)", text, re.IGNORECASE)
        if density_match:
            density = float(density_match.group(1).replace(" ", "").replace(",", "."))
            text = text[:density_match.start()] + text[density_match.end():]
            query = text.strip()
        # «10,5 га Городской округ Мытищи» — площадь руками, остаток — округ.
        match = re.search(r"([\d.,]+)\s*га\s*(.*)", text, re.IGNORECASE)
        if match and not re.search(r"\d{2}:\d{2}:", text):
            area = float(match.group(1).replace(",", "."))
            district = match.group(2).strip() or None
            query = ""
    try:
        if region == "msk":
            # Москва идёт тем же путём, что и сайт: `/cadastral/tep-server`
            # пересылает запрос на ядро, там штатный калькулятор ГлавАПУ, а
            # формулы — фолбэк. Прежде кнопка звала формулы напрямую, и на
            # Render, где браузера нет, другого ответа не бывало вовсе.
            # Подмосковья это не касается: `mo_calculate` на ядро уже
            # пересылает сам.
            result = core.vri_tep_moscow(query)
        else:
            result = core.vri_tep_quick(region, query, site_area_ha=area,
                                        district=district,
                                        density_sqm_per_ha=density)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or core._error_location(exc)
        _send_message(
            chat_id,
            "<b>Расчёт ВРИ и ТЭП не получился.</b>\n"
            f"<i>{html.escape(str(detail)[:300])}</i>",
        )
        return True
    _send_message(chat_id, result["card"])
    try:
        core._telegram_send_document_bytes(
            chat_id, result["file"], result["filename"],
            caption="Файл в формате калькулятора ГлавАПУ — его можно "
                    "загрузить в DevelopAid как обычный ТЭП.")
        if result.get("template_file"):
            core._telegram_send_document_bytes(
                chat_id, result["template_file"], result["template_filename"],
                caption="Тот же расчёт в шаблоне DevelopAid — поправьте "
                        "значения и отправьте файл обратно боту.")
    except Exception as exc:
        core._TELEGRAM_RUNTIME["last_error"] = "ВРИ/ТЭП файл: " + str(exc)
    return True


def _help_markup(chat_id: int) -> dict[str, Any]:
    # Те же решения и в том же порядке, что в приветствии и в списке команд:
    # три меню на один продукт говорили тремя словарями (решение владельца,
    # 18.08.2026). «Прокомментировать ТЭП» — второй уровень Платона, а не
    # отдельное решение, и живёт в его меню.
    rows: list[list[dict[str, Any]]] = [
        [{"text": "Расчёт модели", "callback_data": "calc_menu"}],
    ]
    try:
        rows.append([{
            "text": "Открыть готовую модель",
            "web_app": {"url": core._telegram_web_app_url(chat_id, [])},
        }])
    except Exception:
        pass
    rows.append([{"text": "Расчёт ВРИ и ТЭП", "callback_data": "vritep_start"}])
    rows.append([{"text": "Платон Сергеевич", "callback_data": "ask_platon"}])
    rows.append([{"text": "Оценить DevelopAid", "callback_data": "fb_start"}])
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
        "и <b>90_Детализация</b> — помесячная и поквартальная разбивка, график платежей ВРИ и диаграммы.\n"
        "Если модель нужна ещё раз или не пришла — кнопка «Скачать модель (Excel)» или команда /model.\n\n"

        "<b>Шаг 5. Спросите Платона Сергеевича Федоскина</b>\n"
        "«Прокомментировать ТЭП» (или /comment) — разбор состава и плотности, экономики при текущих "
        "ценах, рисков и того, что уточнить до сделки. Работает сразу после карточки ТЭП.\n"
        "«Спросить Платона» — диалог по текущей модели: объясняет показатели, сравнивает сценарии, "
        "подбирает цену покупки, цены продаж, СМР и параметры финансирования.\n\n"

        + _commands_block() +

        "<i>Расчёт является предварительной инвестиционной моделью, а не отчётом оценщика "
        "и не решением банка. Сведения ЕГРН справочные: для сделки нужна выписка Росреестра.</i>",
        reply_markup=_help_markup(chat_id),
    )


def _commands_block() -> str:
    """Команды, которых нет в меню, — здесь их единственное упоминание.

    Меню Telegram плоское, и тринадцать строк в нём читались простынёй, где всё
    одинаково важно. Меню сведено к пяти решениям, но остальные команды
    работают по-прежнему; не назвав их тут, мы бы просто их спрятали.
    """
    menu = getattr(core, "TELEGRAM_BOT_COMMANDS", []) or []
    extra = getattr(core, "TELEGRAM_EXTRA_COMMANDS", []) or []
    lines = ["<b>Команды</b>", "В меню — пять: " +
             ", ".join(f"/{item['command']}" for item in menu) + ".", "Работают и остальные:"]
    lines += [f"• /{item['command']} — {item['description']}" for item in extra]
    return "\n".join(lines) + "\n\n"


def _state_health(chat_id: int) -> str:
    """Что именно лежит в общей памяти воркеров — видно из чата, без доступа к серверу.

    Воркеров несколько, память у них раздельная, и «проект не передан» выглядит
    одинаково при недоступном диске, непришедшем расчёте и потерянном указателе.
    Разбирать это по логам хостинга долго, поэтому /status отвечает сам.
    """
    import time
    probe = _STATE_DIR / ".probe"
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text(str(time.time()), encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        return f"диск недоступен ({type(exc).__name__}) — расчёт живёт только в одном воркере"
    pointer = _state_read(f"chat:{chat_id}")
    if not pointer:
        return "диск доступен, расчёт из мини-приложения ещё не приходил"
    parts = []
    if pointer.get("context"):
        parts.append("полный расчёт")
    if pointer.get("tep_context"):
        parts.append("ТЭП бота")
    return "диск доступен, сохранено: " + (", ".join(parts) if parts else "только ссылка на сессию")


def _stale_reference_line() -> str:
    """Строка о справочниках, которым пора на обновление. Пусто — всё свежее."""
    try:
        stale = core.stale_references()
    except Exception:
        return ""
    if not stale:
        return ""
    return ("\n<b>Пора обновить справочники:</b>\n"
            + "\n".join(f"• {html.escape(item['title'])} — {html.escape(item['current'])}"
                        for item in stale))


def _glavapu_status_line() -> str:
    """Состояние связки со штатным калькулятором ГлавАПУ — с предупреждением.

    Сбой связки (предохранитель, выключенный headless, недоступное ядро) до
    этой строки был виден только в предупреждении карточки ТЭП: расчёт уходил
    на формулы, владелец узнавал об этом из расхождения с сайтом. /status
    смотрят, когда что-то проверяют, — здесь сбой и должен кричать.
    """
    try:
        state = core.glavapu_health()
    except Exception as exc:
        return f"\n⚠️ ГлавАПУ: состояние не проверить ({html.escape(str(exc)[:120])})"
    label = str(state.get("state") or "?")
    where = str(state.get("where") or "")
    counters = ""
    if state.get("runs") or state.get("fallbacks"):
        counters = (f" · запусков {int(state.get('runs') or 0)}, "
                    f"фолбэков {int(state.get('fallbacks') or 0)}")
    if label == "готов":
        return f"\nГлавАПУ: штатный калькулятор готов ({html.escape(where)}){counters}"
    detail = " ".join(filter(None, [
        str(state.get("hint") or ""),
        f"Ошибка: {state.get('last_error')}" if state.get("last_error") else "",
    ]))
    return (f"\n⚠️ <b>ГлавАПУ: {html.escape(label)}</b> — ТЭП считается запасными "
            f"формулами. {html.escape(detail[:300])}{counters}")


def _core_disk_line() -> str:
    """Сколько места осталось на ядре — раньше, чем это станет поведением.

    Диск кончается молча: выкатка падает на распаковке образа, а вход через
    бота начинает отвечать ошибкой без объяснения, потому что коды входа
    пишутся файлами. Ядро говорит остаток в `/health`, но смотреть туда некому:
    страница живёт на ядре, а спрашивают бота. 20.08.2026 в потолок упёрлись
    второй раз — значит, цифра должна попадаться на глаза сама.
    """
    remote = core._projects_remote_url("/health")
    try:
        if remote:
            with urllib.request.urlopen(remote, timeout=6) as answer:
                data = json.loads(answer.read().decode("utf-8"))
        else:
            data = core.health()
    except Exception:
        return ""
    free = data.get("disk_free_mb")
    if free is None:
        return ""
    free = int(free)
    where = "ядро" if remote else "этот хост"
    if data.get("disk_low") or free < 8192:
        # Порог тот же, что у выкатки: образ два-три гигабайта, и рядом со
        # старым он должен и скачаться, и распаковаться.
        return (f"\nМесто на диске ({where}): <b>{free} МБ</b> — мало для выкатки. "
                f"Уборка: <code>sh scripts/plato-disk-guard.sh --force</code>")
    return f"\nМесто на диске ({where}): {free} МБ"


def _status_message(chat_id: int, user_id: int) -> None:
    configured = bool(core._TELEGRAM_RUNTIME.get("configured"))
    _, context = _resolve_context(chat_id)
    if context:
        platon_state = "контекст загружен · " + _context_label(context)
    else:
        platon_state = "ожидает ТЭП или расчёт"
    if not _agent_ready():
        platon_state += " · AI-прокси Render не настроен"
    platon_state += " · маршрут: " + ("Render" if _proxy_configured() else "этот сервер")
    _send_message(
        chat_id,
        f"<b>DevelopAid bot:</b> {'подключён' if configured else 'запускается'}\n"
        f"Telegram ID: <code>{user_id}</code>\n"
        f"Версия: {_RUNTIME_VERSION}\n"
        f"Платон: {platon_state}\n"
        f"Память расчётов: {_state_health(chat_id)}"
        + _core_disk_line()
        + _glavapu_status_line()
        # Справочник устаревает тихо: расчёт идёт, числа выглядят как обычно,
        # а под ними прошлогодний тариф. Напоминание тут потому, что /status
        # смотрят, когда что-то проверяют.
        + _stale_reference_line()
        # Сборка PDF и Excel-модели идёт в фоне отправки карточки, и её отказ
        # виден только здесь. Без этой строки «модель не пришла» неотличимо
        # от «модель не собралась».
        + (f"\nПоследняя ошибка: <i>{html.escape(str(last_error)[:200])}</i>"
           if (last_error := core._TELEGRAM_RUNTIME.get("last_error")) else ""),
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
        # Диалог уже открыт — переводим его на свежий расчёт, иначе Платон
        # продолжит отвечать по цифрам, которые человек только что переделал.
        if chat_id in _PLATON_MODE:
            _PLATON_MODE[chat_id] = req.session
        # Пришёл полный расчёт — грубый ТЭП на умолчаниях больше не нужен и не
        # должен всплыть, если ссылка на сессию потеряется.
        _PLATON_TEP_CONTEXT.pop(chat_id, None)
    _state_write(f"session:{req.session}", context)
    pointer = _state_read(f"chat:{chat_id}")
    pointer["session"] = req.session
    # Расчёт кладём в указатель чата целиком. Чат — единственная устойчивая
    # величина: токен сессии живёт одно сообщение, а вопрос Платону приходит
    # позже и уже с другим токеном.
    pointer["context"] = context
    pointer.pop("tep_context", None)
    _state_write(f"chat:{chat_id}", pointer)
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
    if not url:
        # Адрес модели живёт в памяти одного воркера, а нажатие приходит
        # в любой. Без диска кнопка просто пропадала — «никакой ссылки».
        url = str(_state_read(f"chat:{chat_id}").get("url") or "")
        if url:
            with _STATE_LOCK:
                _PLATON_LAST_URL[chat_id] = url
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
            f"AI-прокси Render не настроен: {_agent_unready_reason()} — без него бот не может "
            "комментировать расчёт. Ключ <code>OPENAI_API_KEY</code> задаётся только на Render, "
            "на ядре он не нужен. Добавьте переменные в настройках сервиса и перезапустите его.",
        )
        return
    if intro:
        _send_message(chat_id, intro)

    # Вопрос к Платону — отдельное событие: по нему видно, о чём спрашивают, а
    # не только сколько раз нажали кнопку. Разбор ТЭП — не вопрос человека, и
    # складывать его в один ряд с вопросами значило бы завысить их число.
    if text == _TEP_COMMENT_REQUEST:
        core.usage_track("tep_comment", chat_id=chat_id, user_id=chat_id,
                         text="(разбор ТЭП кнопкой)")
    else:
        core.usage_track("question", chat_id=chat_id, user_id=chat_id, text=text)

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
        # Не `agent_chat`: тот отдаёт «работа принята» через двадцать секунд, и
        # забирать результат браузер идёт опросом. Боту забирать неоткуда — он
        # ждёт ответ в своём потоке, и никто это ожидание не рвёт.
        result = core.plato_answer(req, _request_for_agent(chat_id))
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


def _applied_message(applied: dict[str, Any]) -> str:
    """Отчёт о применении. «Применены к новой ссылке» человеку ничего не говорит.

    Кнопка называется одинаково до и после, поэтому по одному её виду не понять,
    сменились вводные или нет. Перечисляем, что поменялось и на что.
    """
    if not applied:
        return (
            "<b>Не удалось применить изменения.</b>\n"
            "Предложение устарело — переспросите Платона, и он подготовит его заново."
        )
    lines = []
    for change in applied.get("changes") or []:
        label = str(change.get("label") or change.get("variable") or "").strip()
        if not label:
            continue
        lines.append(f"• {html.escape(label)}: {core._telegram_number(change.get('old'), 2)}"
                     f" → <b>{core._telegram_number(change.get('new'), 2)}</b>")
    if applied.get("error"):
        return (
            "<b>Вводные изменены, но ссылку пересобрать не вышло.</b>\n"
            + ("\n".join(lines) + "\n\n" if lines else "")
            + f"<i>{html.escape(str(applied['error'])[:200])}</i>\n"
            "Кнопка «Открыть текущую модель» ведёт на прежний расчёт. "
            "Откройте модель заново из карточки результата."
        )
    return (
        "<b>Изменения применены.</b>\n"
        + ("\n".join(lines) + "\n\n" if lines else "\n")
        + "Кнопка <b>«Открыть текущую модель»</b> ниже уже ведёт на расчёт с новыми вводными — "
        "модель пересчитается при открытии. Прежняя ссылка осталась со старыми значениями."
    )


def _apply_proposal(chat_id: int) -> dict[str, Any]:
    """Применяет правку Платона и возвращает то, о чём надо отчитаться человеку.

    Пустой словарь — не применилось. Ключ "error" — вводные поменялись, а ссылку
    пересобрать не вышло: об этом надо сказать прямо, а не рапортовать успех.
    """
    with _STATE_LOCK:
        pending = copy.deepcopy(_PLATON_PENDING.get(chat_id) or {})
    proposal = pending.get("proposal") or {}
    patch = proposal.get("patch") if isinstance(proposal, dict) else None
    session = str(pending.get("session") or "")
    if not isinstance(patch, dict) or not patch:
        return {}
    changes = [c for c in (proposal.get("changes") or []) if isinstance(c, dict)]
    error = ""
    with _STATE_LOCK:
        # Правка ложится либо в контекст мини-приложения, либо в ТЭП бота.
        context = _PLATON_CONTEXT_BY_SESSION.get(session) if session else _PLATON_TEP_CONTEXT.get(chat_id)
        if not context:
            return {}
        # Имена в patch — это переменные Платона, а не всегда поля модели.
        # «Основное строительство» одно, а полей два (наземное и подземное), и
        # простой update() записывал в inputs ключ, которого движок не читает:
        # бот рапортовал о применении, а СМР оставалась прежней.
        before = copy.deepcopy(context["inputs"])
        for variable, value in patch.items():
            core._apply_patch_value(context["inputs"], variable, value)
        real_patch = {key: value for key, value in context["inputs"].items()
                      if before.get(key) != value}
        session_data = copy.deepcopy(context.get("session_data") or {})
        overrides = copy.deepcopy(session_data.get("calc_overrides") or {})
        overrides.update(real_patch)
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
            error = str(exc)
        if new_url:
            _PLATON_LAST_URL[chat_id] = new_url
        _PLATON_PENDING.pop(chat_id, None)
        persisted = copy.deepcopy(context)
    # Правку надо донести до диска: иначе соседний воркер ответит по вводным,
    # которые Платон уже пересчитал, а кнопку «Открыть текущую модель» покажет
    # со старым адресом или не покажет вовсе — ссылка жила только в его памяти.
    if session:
        _state_write(f"session:{session}", persisted)
    pointer = _state_read(f"chat:{chat_id}")
    if session:
        pointer["context"] = persisted
    else:
        pointer["tep_context"] = persisted
    if new_url:
        pointer["url"] = new_url
    _state_write(f"chat:{chat_id}", pointer)
    return {"changes": changes, "url": new_url, "error": error}


def _send_model_archive(chat_id: int) -> None:
    """Собирает Excel-модель по последнему расчёту чата и присылает её.

    Сборка идёт следом за карточкой, и её отказ раньше оставлял человека вовсе
    без модели: мини-приложение закрывается сразу после расчёта, и до кнопки
    «Скачать модель (ZIP)» внутри уже не добраться.
    """
    _, context = _resolve_context(chat_id)
    if not context:
        _send_message(
            chat_id,
            "<b>Собирать пока нечего.</b>\n"
            "Сначала посчитайте проект: отправьте кадастровые номера, адрес "
            "или заполненный Excel-шаблон.",
        )
        return
    _send_message(chat_id, "<i>Собираю Excel-модель…</i>")
    try:
        model_bytes, model_filename, model_meta = core.build_project_workbook(
            context.get("inputs") or {},
            context.get("tep") or {},
            context.get("rates") or [],
            context.get("phasing") or {},
            project_name=str(context.get("project_name") or ""),
        )
    except Exception as exc:
        core._TELEGRAM_RUNTIME["last_error"] = "Модель: " + core._error_location(exc)
        _send_message(
            chat_id,
            "<b>Excel-модель не собралась.</b>\n"
            f"<i>{html.escape(core._error_location(exc)[:300])}</i>",
        )
        return
    if model_meta.get("missing"):
        core._TELEGRAM_RUNTIME["last_error"] = "Книга v4, без соответствия: " + "; ".join(
            str(item) for item in model_meta["missing"][:6])
    core._telegram_send_document_bytes(
        chat_id, model_bytes, model_filename,
        caption=("<b>Полная модель DevelopAid</b> · Excel считает формулами "
                 "из текущих вводных"
                 + (" · очереди на листе «Вводные»" if model_meta.get("phased") else "")),
        content_type=core._XLSX_MEDIA_TYPE,
    )


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


def _sender_name(message: dict[str, Any]) -> str:
    sender = (message.get("message") if isinstance(message.get("message"), dict) else message).get("from") or {}
    username = str(sender.get("username") or "").strip()
    if username:
        return "@" + username
    return " ".join(part for part in (str(sender.get("first_name") or "").strip(),
                                      str(sender.get("last_name") or "").strip()) if part)


def _remote_summaries(days: int) -> dict | None:
    """Свод с ядра: сайт живёт там, и анкеты, заполненные на сайте, лежат там же.

    Журнал пишется на том хосте, который обслужил запрос. Бот на Render видел
    только свою половину, и ответы людей с сайта не показывались никому
    (18.08.2026). Подпись — общим токеном бота, как у подтверждения входа.
    """
    remote = core._projects_remote_url("/internal/usage/summary")
    if not remote:
        return None
    try:
        return core._core_post(remote, {
            "days": int(days),
            "sign": core._web_login_sign("usage-summary", int(days)),
        }, 30.0)
    except Exception:
        # Свод — удобство: молчание лучше отказа вместо своей половины.
        return None


def _when(at: Any) -> str:
    """Время события коротко. Журнал ведётся в UTC — так и подписано."""
    try:
        moment = datetime.fromtimestamp(float(at or 0), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return ""
    return moment.strftime("%d.%m %H:%M")


def _note_line(note: dict) -> str:
    """Комментарий с автором: кто, когда, о чём и что именно написал.

    Раньше строка начиналась с роли, а роль в боте пустая, — получалось
    «— : не верю числам», и переспросить было некого.
    """
    who = html.escape(str(note.get("who") or note.get("role") or "аноним"))
    when = _when(note.get("at"))
    head = f"<b>{who}</b>" + (f" · {when}" if when else "")
    group = html.escape(str(note.get("group") or ""))
    return f"{head} · <i>{group}</i>: " + html.escape(str(note.get("text") or "")[:400])


def _respondents_block(data: dict) -> list[str]:
    """Поимённо: кто отвечал, что поставил и где просел.

    Свод средних говорит о сервисе, а этот список — о людях: анкета не
    анонимная, и владельцу нужно знать, к кому вернуться с вопросом.
    """
    people = data.get("respondents") or []
    if not people:
        return []
    lines = ["", "<b>Кто отвечал</b>"]
    for person in people[:15]:
        who = html.escape(str(person.get("who") or "аноним"))
        when = _when(person.get("at"))
        rated = int(person.get("rated") or 0)
        head = f"• <b>{who}</b>" + (f" · {when}" if when else "")
        if rated:
            head += f" · {rated} оц., средняя {person.get('avg')}"
        else:
            head += " · без оценок"
        chat = int(person.get("chat") or 0)
        if chat:
            head += f" · <code>{chat}</code>"
        lines.append(head)
        weak = [f"{html.escape(str(row['label']))} {row['score']}"
                for row in (person.get("lowest") or []) if int(row["score"]) <= 3]
        if weak:
            lines.append("   ниже всего: " + " · ".join(weak))
        for text in (person.get("texts") or [])[:3]:
            lines.append("   «" + html.escape(str(text)[:400]) + "»")
    if len(people) > 15:
        lines.append(f"<i>…и ещё {len(people) - 15} чел.</i>")
    return lines


def _when_day(stamp: str) -> str:
    """Дата знакомства по-человечески. Не разобралась — не показываем вовсе."""
    try:
        return datetime.fromisoformat(str(stamp)).strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _users_block(days: int) -> list[str]:
    """Сколько у нас пользователей. Реестр лежит на ядре и переживает выкатку.

    Два числа рядом, а не одно: «всего» — все, кого мы видели; «за окно» — те,
    кто пришёл впервые. Знакомство считается отдельным блоком ниже: нажать
    Start и представиться — разные вещи, и разница между ними это воронка.
    """
    users = (_remote_summaries(days) or {}).get("users")
    if not isinstance(users, dict):
        try:
            users = core.users_registry_summary(days)
        except Exception:
            return []
    if not users.get("total"):
        return []
    lines = ["", f"<b>Пользователей всего: {users['total']}</b> "
                 f"<i>(впервые за {days} дн. — {users.get('new_in_window', 0)}, "
                 f"заходили — {users.get('active_in_window', 0)})</i>"]
    for person in (users.get("recent") or [])[:10]:
        who = html.escape(str(person.get("name") or "")) or f"chat {person.get('chat')}"
        kinds = person.get("kinds") or {}
        what = " · ".join(f"{html.escape(str(k))} {v}" for k, v in
                          sorted(kinds.items(), key=lambda kv: -kv[1])[:4])
        lines.append(f"• <b>{who}</b> — {_when_day(_iso(person.get('first_seen')))}"
                     + (f" · {what}" if what else "")
                     + f" · <code>{person.get('chat')}</code>")
    return lines


def _iso(at: Any) -> str:
    try:
        return datetime.fromtimestamp(float(at or 0), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _registry_block(days: int) -> list[str]:
    """Кто зарегистрировался на портале — по знакомствам на ядре.

    Считаем по профилям, а не по журналу: журнал у каждого хоста свой и на
    Render живёт до следующей выкатки, а профиль лежит файлом на ядре и
    переживает и выкатку, и пересоздание контейнера.
    """
    registry = (_remote_summaries(days) or {}).get("registry")
    if not isinstance(registry, dict):
        # Локальный ответ — на случай, когда ядра нет: тогда профили здесь.
        try:
            registry = core.profile_registry_summary(days)
        except Exception:
            return []
    if not registry.get("total"):
        return ["", "<b>Регистраций пока нет.</b> Знакомство спрашивается "
                    "один раз после входа."]
    lines = ["", f"<b>Зарегистрировано: {registry['total']}</b> "
                 f"<i>(за {days} дн. — {registry.get('window', 0)})</i>"]
    if registry.get("by_source"):
        lines.append("Откуда узнали: " + " · ".join(
            f"{html.escape(str(name))} {count}"
            for name, count in registry["by_source"]))
    for person in (registry.get("recent") or [])[:10]:
        when = _when_day(str(person.get("created") or ""))
        who = html.escape(str(person.get("name") or "без имени"))
        company = html.escape(str(person.get("company") or ""))
        role = html.escape(str(person.get("role") or ""))
        tail = " · ".join(part for part in (company, role, when) if part)
        line = f"• <b>{who}</b>" + (f" — {tail}" if tail else "")
        chat = int(person.get("chat") or 0)
        if chat:
            line += f" · <code>{chat}</code>"
        lines.append(line)
    # Имя и компанию человек написал сам, и подтвердить их нечем: телеграм
    # доказывает аккаунт, а не место работы.
    lines.append("<i>Имя и компанию люди указывают сами — это их слова.</i>")
    return lines


def _survey_block(data: dict, title: str) -> list[str]:
    lines = [f"<b>{title}</b>", f"Анкет заполнено: <b>{data.get('answers', 0)}</b>"]
    groups = [g for g in (data.get("groups") or []) if g.get("count")]
    if groups:
        lines.append("Средние по разделам: " + " · ".join(
            f"{html.escape(str(g['label']))} {g['avg']}" for g in groups))
    for note in (data.get("notes") or [])[-10:]:
        lines.append("• " + _note_line(note))
    lines.extend(_respondents_block(data))
    return lines


def _survey_message(chat_id: int, user_id: int, argument: str) -> None:
    """Свод теста: откуда пришли, докуда дошли, как оценили, что написали.

    Доступ — как у статистики: свободные тексты людей чужим не показываем.
    """
    admins = core.usage_admin_ids()
    if not admins or user_id not in admins:
        _send_message(chat_id, "<b>Свод закрыт.</b> "
                      + (f"Задайте <code>DEVELOPAID_ADMIN_IDS</code>: ваш ID "
                         f"<code>{user_id}</code>." if not admins
                         else "Ваш Telegram ID не в списке администраторов."))
        return
    days = 30
    for piece in (argument or "").split():
        if piece.isdigit():
            days = max(1, min(365, int(piece)))
    data = core.survey_summary(days)

    lines = [f"<b>Тест платформы за {days} дн.</b>", ""]
    # Воронка целиком, включая нули: пустая строка «выгрузили PDF: 0» говорит
    # больше, чем её отсутствие.
    lines.append("<b>Воронка</b> (людей)")
    for label, count in data["funnel"].items():
        lines.append(f"• {html.escape(label)}: <b>{count}</b>")
    if data["by_source"]:
        lines.append("")
        lines.append("<b>Откуда пришли:</b> " + " · ".join(
            f"{html.escape(str(name))} {count}" for name, count in data["by_source"]))

    lines.append("")
    lines.append(f"<b>Анкет заполнено: {data['answers']}</b>")
    if data["groups"] and any(g["count"] for g in data["groups"]):
        lines.append("")
        lines.append("<b>Средние по разделам</b>")
        for group in data["groups"]:
            if not group["count"]:
                continue
            lines.append(f"• {html.escape(group['label'])}: <b>{group['avg']}</b> "
                         f"<i>({group['count']} оц.)</i>")
    if data["weakest"]:
        lines.append("")
        lines.append("<b>Слабее всего</b>")
        for item in data["weakest"]:
            lines.append(f"• {html.escape(item['label'])}: <b>{item['avg']}</b> "
                         f"<i>({item['count']})</i>")
    if data["notes"]:
        lines.append("")
        lines.append("<b>Что написали</b> <i>(время UTC)</i>")
        for note in data["notes"][-20:]:
            lines.append("• " + _note_line(note))
    else:
        lines.append("")
        lines.append("<i>Свободных комментариев пока нет.</i>")
    lines.extend(_respondents_block(data))
    # Вторая половина ответов — на ядре: сайт обслуживает оно, и его журнал
    # боту не виден. Показываем отдельным блоком, а не подмешиваем в средние:
    # смешивать две выборки в одно число значит выдумывать третье.
    remote = _remote_summaries(days)
    remote_survey = (remote or {}).get("survey") or {}
    if remote_survey.get("answers"):
        lines.append("")
        lines.extend(_survey_block(remote_survey, "Анкеты с сайта (ядро)"))
    elif remote is None and core._projects_remote_url("/internal/usage/summary"):
        lines.append("")
        lines.append("<i>Свод с ядра не получен — показана только половина бота.</i>")
    _send_message(chat_id, "\n".join(lines))


def _stats_message(chat_id: int, user_id: int, argument: str) -> None:
    """Кто пользуется ботом и о чём спрашивает.

    Список чужих вопросов открыт не всем: без `DEVELOPAID_ADMIN_IDS` команда
    отвечает отказом и говорит, чей номер вписать — свой человек видит его в
    `/status`.
    """
    admins = core.usage_admin_ids()
    if not admins or user_id not in admins:
        _send_message(
            chat_id,
            "<b>Статистика закрыта.</b>\n"
            + ("Задайте <code>DEVELOPAID_ADMIN_IDS</code> в переменных сервиса: "
               f"ваш Telegram ID <code>{user_id}</code>."
               if not admins else "Ваш Telegram ID не в списке администраторов."),
        )
        return

    argument = (argument or "").strip().lower()
    days = 30
    for piece in argument.split():
        if piece.isdigit():
            days = max(1, min(365, int(piece)))
    if "csv" in argument:
        try:
            # Выгрузка собирается из обеих половин. Своя приходила пустой после
            # каждой выкатки — диск Render живёт до следующей, — и пустая
            # таблица читалась как «людей не было», хотя людей просто некому
            # было записать: сайт обслуживает ядро, и его журнал цел.
            remote = _remote_summaries(days) or {}
            events = list(core.usage_events(days))
            mine = len(events)
            events.extend(event for event in (remote.get("events") or [])
                          if isinstance(event, dict))
            caption = (f"Журнал обращений за {days} дн.\n"
                       f"Бот: {mine} · ядро (сайт): {len(events) - mine}")
            if not remote and core._projects_remote_url("/internal/usage/summary"):
                caption += "\nЯдро не ответило — в файле только половина бота."
            core._telegram_send_document_bytes(
                chat_id, core.usage_csv(days, events),
                f"developaid-usage-{days}d.csv",
                caption=caption, content_type="text/csv")
        except Exception as exc:
            _send_message(chat_id, "<b>Выгрузка не собралась.</b>\n"
                          + html.escape(f"{type(exc).__name__}: {exc}"))
        return

    s = core.usage_summary(days)
    if not s["enabled"]:
        _send_message(chat_id, "<b>Журнал обращений выключен</b> переменной "
                               "<code>DEVELOPAID_USAGE_JOURNAL</code>.")
        return

    def listing(pairs: list[tuple[str, int]]) -> str:
        return " · ".join(f"{html.escape(str(name))} {count}" for name, count in pairs) or "—"

    lines = [
        f"<b>Обращения за {days} дн.</b>",
        f"Пользователей: сегодня <b>{s['users_today']}</b> · "
        f"за 7 дн. <b>{s['users_7d']}</b> · за 30 дн. <b>{s['users_30d']}</b>",
        f"За период: <b>{s['users_window']}</b> человек, из них новых <b>{s['new_users_window']}</b>",
        f"Событий: {s['events_window']} · вопросов Платону: "
        f"{s['questions_bot']} в боте, {s['questions_site']} на сайте",
        "",
        "<b>Команды:</b> " + listing(s["top_commands"]),
        "<b>Кнопки:</b> " + listing(s["top_buttons"]),
    ]
    if s["last_questions"]:
        lines.append("")
        lines.append("<b>Последние вопросы:</b>")
        for event in reversed(s["last_questions"]):
            when = datetime.fromtimestamp(float(event.get("at") or 0),
                                          tz=timezone.utc).strftime("%d.%m %H:%M")
            who = str(event.get("name") or event.get("user") or "—")
            where = "сайт" if event.get("surface") == "site" else "бот"
            lines.append(f"• <i>{when} · {html.escape(who)} · {where}</i>\n"
                         f"{html.escape(str(event.get('text') or '')[:180])}")
    # Регистрации живут на ядре: знакомство — единственная запись, которая
    # переживает выкатку, а журнал бота на Render с ней кончается. Вопрос
    # «сколько зарегистрировалось» задают боту, отвечать на него журналом
    # нельзя — он покажет ноль там, где людей полсотни.
    lines.extend(_users_block(days))
    lines.extend(_registry_block(days))
    reminder = _stale_reference_line()
    if reminder:
        lines.append(reminder)
    lines.append("")
    lines.append(f"<i>Журнал бота хранится {s['keep_days']} дн. и обнуляется при "
                 f"выкатке — на ядре он цел. Выгрузка обеих половин: "
                 f"<code>/stats csv</code>, период: <code>/stats 7</code>.</i>")
    _send_message(chat_id, "\n".join(lines))


def _usage_digest_hour() -> int:
    raw = os.getenv("DEVELOPAID_USAGE_DIGEST_HOUR", "6").strip()
    return min(23, max(0, int(raw))) if raw.lstrip("-").isdigit() else 6


def _usage_digest_due() -> bool:
    """Раз в сутки — сводка администраторам, если её ещё не отправляли.

    Диск под ботом живёт до следующей выкатки, и журнал вместе с ним. Сводка,
    ушедшая в чат, переживает и выкатку, и пересоздание контейнера — поэтому
    отслеживание не сводится к файлу, который в любой момент может исчезнуть.

    Отправляет только тот хост, что держит вебхук: второй экземпляр с тем же
    токеном обязан молчать. Отметка создаётся исключительным созданием файла —
    воркеров два, и оба доходят сюда одновременно.
    """
    if not core.usage_admin_ids() or not core._telegram_webhook_enabled():
        return False
    now = datetime.now(timezone.utc)
    if now.hour < _usage_digest_hour():
        return False
    try:
        core._USAGE_DIR.mkdir(parents=True, exist_ok=True)
        (core._USAGE_DIR / f"digest-{now:%Y-%m-%d}.done").open("x").close()
    except FileExistsError:
        return False
    except OSError:
        return False
    return True


def _usage_digest_loop() -> None:
    while True:
        try:
            if _usage_digest_due():
                for admin in sorted(core.usage_admin_ids()):
                    _stats_message(admin, admin, "1")
        except Exception:
            pass  # сводка — удобство: молчание лучше падения фонового потока
        try:
            _deliver_profile_announcements()
        except Exception:
            pass
        try:
            _deliver_krt_announcements()
        except Exception:
            pass  # рассылка — удобство: молчание лучше падения фонового потока
        time.sleep(900)


def _deliver_profile_announcements() -> None:
    """Знакомства с ядра — в чат владельцу.

    Анкета сохраняется на ядре (данные людей живут в России), а до
    api.telegram.org достаёт только этот хост. Ядро складывает знакомство в
    очередь, мы забираем её и объявляем — иначе «новая регистрация» не дошла бы
    ни до кого (18.08.2026).
    """
    admins = core.usage_admin_ids()
    if not admins or not core._telegram_token() or not core._telegram_webhook_enabled():
        return
    remote = core._projects_remote_url("/internal/profile/announcements")
    if remote:
        payload = {"code": "profile-announcements", "chat_id": 0,
                   "sign": core._web_login_sign("profile-announcements", 0)}
        data = core._core_post(remote, payload, 30.0)
        records = list(data.get("announcements") or [])
    else:
        # Один хост на всё — очередь та же, только идти за ней некуда.
        records = core._profile_take_announcements()
    for record in records:
        core._telegram_send_profile_card(record, admins)


def _krt_take_announcements() -> tuple[list[dict], list[int]]:
    """Новинки каталога КРТ и подписчики — с ядра или из своей очереди.

    Каталог читается на ядре, а до api.telegram.org достаём только мы: тот же
    приём, что у знакомств. Подписчики приезжают ТЕМ ЖЕ ответом — два запроса
    ради одного сообщения дали бы два места, где список разъедется с рассылкой.
    """
    remote = core._projects_remote_url("/internal/krt/announcements")
    if remote:
        payload = {"code": "krt-announcements", "chat_id": 0,
                   "sign": core._web_login_sign("krt-announcements", 0)}
        data = core._core_post(remote, payload, 30.0)
    else:
        take = getattr(core.app.state, "krt_announcements_take", None)
        if take is None:
            return [], []
        data = {"announcements": take(), "subscribers": core._krt_subscribers()}
    return list(data.get("announcements") or []), [int(x) for x in (data.get("subscribers") or [])]


def _deliver_krt_announcements() -> None:
    """Новые площадки КРТ — в чат подписчикам.

    Список отсортирован по баллу, и площадка, появившаяся на этой неделе,
    стоит где придётся: глазами её не найти. Плашка «новое» отвечает тому, кто
    и так открыл каталог; сообщение — тому, кто не открывал.

    Владелец получает их всегда: подписка — для остальных, а он и есть тот,
    ради кого каталог читается.
    """
    if not core._telegram_token() or not core._telegram_webhook_enabled():
        return
    records, subscribers = _krt_take_announcements()
    if not records:
        return
    targets = sorted(set(subscribers) | set(core.usage_admin_ids()))
    if not targets:
        return
    for chat_id in targets:
        try:
            core._telegram_send_message(chat_id, _krt_announcement_text(records))
        except Exception:
            # Один недоставленный адресат не отменяет рассылку остальным.
            continue


def _krt_announcement_text(records: list[dict]) -> str:
    """Одно сообщение на всю пачку, а не письмо на площадку.

    Каталог обновляется раз в неделю и приносит новинки скопом: двенадцать
    сообщений подряд читаются как поломка бота, а не как новость.
    """
    import html as _html

    names = [str(r.get("name") or r.get("slug") or "").strip() for r in records]
    names = [name for name in names if name]
    head = ("В каталоге КРТ новая площадка" if len(names) == 1
            else f"В каталоге КРТ новых площадок: {len(names)}")
    lines = [f"<b>{_html.escape(head)}</b>"]
    for name in names[:12]:
        lines.append("— " + _html.escape(name))
    if len(names) > 12:
        lines.append(f"…и ещё {len(names) - 12}")
    lines.append("")
    # Адрес берём у движка, а не пишем словами: команды «/torgi» в боте нет, и
    # ссылка на несуществующее — та же ложь, что подпись под чужим числом.
    base = str(getattr(core, "_TELEGRAM_WEB_APP_BASE_URL", "") or "").rstrip("/")
    where = f'<a href="{base}/auctions">каталог площадок КРТ</a>' if base else "вкладку «Площадки КРТ»"
    lines.append(f"Открыть {where} — новинки помечены плашкой «новое».")
    lines.append("Отписаться — /krt выкл")
    return "\n".join(lines)


def _krt_subscription(chat_id: int, wanted: bool | None = None) -> bool:
    """Состояние подписки. `wanted=None` — только прочитать, ничего не меняя.

    Читать записью нельзя: переключатель, который сперва отписывает, чтобы
    узнать состояние, оставит человека отписанным, если второй запрос не дойдёт.
    """
    remote = core._projects_remote_url("/internal/krt/subscribe")
    payload = {"chat_id": int(chat_id), "on": wanted,
               "sign": core._web_login_sign("krt-subscribe", int(chat_id))}
    if remote:
        return bool(core._core_post(remote, payload, 20.0).get("subscribed"))
    if wanted is None:
        return int(chat_id) in core._krt_subscribers()
    return bool(core._krt_subscribe(int(chat_id), bool(wanted)))


# --- анкета в боте -----------------------------------------------------------
# На сайте анкета — двадцать пунктов с оценками; в чате столько никто не
# заполнит. Но одной оценки мало (владелец, 19.08.2026): «ничего страшного,
# если пять раз оценку поставят, как на сайте, и в конце комментарий напишу».
# Поэтому спрашиваем по разделам — кнопками, по одному вопросу за сообщение, —
# а в конце берём одну строку словами.
#
# Список вопросов не пишется здесь второй раз: разделы берутся из
# `core.FEEDBACK_GROUPS`, оценка ложится в тот же журнал (`survey`) под ключом
# ведущего подпункта раздела — того самого, что показывает свод. Свод `/survey`
# и сводка владельцу считают сайт и бота вместе, раздельно по поверхности.
#
# Записей на анкету две, и это осознанно: оценки уходят в журнал сразу, как
# кончились вопросы, — брошенный на комментарии человек всё равно посчитан, —
# а комментарий приезжает второй записью без оценок. Иначе либо оценки
# теряются, либо каждая считается дважды и портит средние.
_FEEDBACK_STATE = "feedback"


def _feedback_questions() -> list[tuple[str, str, str]]:
    """Вопросы бота: раздел анкеты, ключ оценки, из чего раздел состоит."""
    questions: list[tuple[str, str, str]] = []
    for group in getattr(core, "FEEDBACK_GROUPS", []):
        members = list(group[2] or [])
        if not members:
            continue
        # Ключ — ведущий подпункт раздела: он стоит первым не случайно, и свод
        # показывает оценки по тем же ключам, что приходят с сайта.
        questions.append((str(group[1]), str(members[0][0]),
                          ", ".join(str(item[1]) for item in members)))
    return questions


def _feedback_state(chat_id: int) -> dict[str, Any]:
    return _state_read(f"{_FEEDBACK_STATE}:{chat_id}") or {}


def _feedback_remember(chat_id: int, payload: dict[str, Any]) -> None:
    _state_write(f"{_FEEDBACK_STATE}:{chat_id}", payload)


def _feedback_forget(chat_id: int) -> None:
    _state_write(f"{_FEEDBACK_STATE}:{chat_id}", {})


def _feedback_start(chat_id: int, name: str = "") -> None:
    # Имя автора кладётся в состояние: анкета длинная, а событие с именем
    # приходит только в начале. Без него в своде остаётся голый chat_id —
    # владелец видел «— : не верю числам» и не знал, кого переспросить.
    _feedback_remember(chat_id, {"stage": "rate", "index": 0, "ratings": {},
                                 "name": str(name or "")})
    total = len(_feedback_questions())
    _send_message(
        chat_id,
        "<b>Оцените DevelopAid</b>\n"
        f"{total} вопросов кнопками и одна строка словами в конце. "
        "Чем не пользовались — пропускайте: пропуск это не единица.")
    _feedback_ask(chat_id)


def _feedback_ask(chat_id: int) -> None:
    """Очередной вопрос. Кончились — переходим к комментарию."""
    state = _feedback_state(chat_id)
    questions = _feedback_questions()
    index = int(state.get("index") or 0)
    if index >= len(questions):
        _feedback_finish(chat_id)
        return
    title, _key, members = questions[index]
    _send_message(
        chat_id,
        f"<b>{html.escape(title)}</b> · вопрос {index + 1} из {len(questions)}\n"
        f"<i>{html.escape(members)}</i>\n"
        "1 — плохо, 5 — отлично.",
        reply_markup={"inline_keyboard": [
            # Номер вопроса — в самой кнопке: воркеров два, состояние лежит на
            # диске, и кнопка позавчерашнего вопроса не должна отвечать за
            # сегодняшний.
            [{"text": str(score), "callback_data": f"fb_r{index}_{score}"}
             for score in range(1, 6)],
            [{"text": "Не пользовался", "callback_data": f"fb_s{index}"},
             {"text": "Закончить", "callback_data": "fb_done"}],
        ]})


def _feedback_answer(chat_id: int, index: int, score: int | None) -> None:
    """Ответ на вопрос под номером. Чужой номер — эхо старой кнопки, молчим."""
    state = _feedback_state(chat_id)
    if str(state.get("stage") or "") != "rate":
        return
    if int(state.get("index") or 0) != int(index):
        return
    questions = _feedback_questions()
    if not 0 <= index < len(questions):
        return
    if score is not None and 1 <= score <= 5:
        ratings = dict(state.get("ratings") or {})
        ratings[questions[index][1]] = int(score)
        state["ratings"] = ratings
    state["index"] = index + 1
    _feedback_remember(chat_id, state)
    _feedback_ask(chat_id)


def _user_to_core(chat_id: int, name: str, kind: str) -> None:
    """Человек из чата — в реестр на ядре, а не только на диск Render.

    `usage_track` пишет реестр там, где обслужен запрос. Бот обслуживает
    вебхук на Render, где диск кончается вместе с контейнером, — и «сколько у
    нас пользователей» обнулялось каждой выкаткой (замечание владельца,
    23.08.2026). Отправка фоновая и молчаливая: учёт не имеет права задерживать
    ответ человеку и не имеет права его ронять.
    """
    chat = int(chat_id or 0)
    if not chat:
        return
    remote = core._projects_remote_url("/internal/user/touch")
    if not remote:
        return

    def send() -> None:
        try:
            core._core_post(remote, {
                "chat": chat, "name": name, "surface": "telegram", "kind": kind,
                "sign": core._web_login_sign("user-touch", chat),
            }, 15.0)
        except Exception as exc:
            core._PLATON_LOG.warning("Пользователь не доехал до ядра: %s: %s",
                                     type(exc).__name__, exc)

    threading.Thread(target=send, daemon=True).start()


def _survey_to_core(chat_id: int, name: str, **fields: Any) -> None:
    """Анкета из чата — в хранилище на ядре, а не только в журнал Render.

    Журнал бота живёт до следующей выкатки, а анкета должна лежать вечно
    (решение владельца, 23.08.2026: «нам нужны анкеты и юзеры»). Пишем обеими
    руками: журнал даёт воронку и остаётся как был, хранилище — сами ответы.
    Неответ ядра не молчит: без него анкета уцелеет только до выкатки, и это
    надо знать.
    """
    core.usage_track("survey", surface="telegram", chat_id=chat_id,
                     user_id=chat_id, name=name, **fields)
    remote = core._projects_remote_url("/internal/survey/save")
    if not remote:
        return
    record = {"at": time.time(), "surface": "telegram", "kind": "survey",
              "chat": int(chat_id), "user": int(chat_id), "name": name, **fields}
    try:
        core._core_post(remote, {
            "record": record,
            "sign": core._web_login_sign("survey-save", int(chat_id)),
        }, 20.0)
    except Exception as exc:
        # Человеку об этом говорить незачем — он своё дело сделал. Но и молчать
        # нельзя: анкета осталась только в журнале Render и не переживёт
        # выкатку, поэтому след остаётся в логе и в самом журнале.
        core._PLATON_LOG.warning("Анкета не доехала до ядра: %s: %s",
                                 type(exc).__name__, exc)
        core.usage_track("survey_lost", surface="telegram", chat_id=chat_id,
                         user_id=chat_id, name=name,
                         text=f"{type(exc).__name__}: {exc}"[:200])


def _feedback_finish(chat_id: int) -> None:
    """Вопросы кончились: оценки в журнал, дальше ждём комментарий.

    Зовётся из двух мест — сам, когда вопросы кончились, и по кнопке
    «Закончить», которая остаётся висеть под последним вопросом. Владелец
    прошёл анкету и получил подряд «Оценок записано: 7» и «Ни одной оценки»
    (23.08.2026): второй вызов читал уже перезаписанное состояние. Воркеров
    к тому же два, и гонка дала бы не только два сообщения, но и две записи
    оценок — то есть удвоенные средние. Поэтому завершение идемпотентно: этап
    уже сменился — молчим.
    """
    state = _feedback_state(chat_id)
    if str(state.get("stage") or "") != "rate":
        return
    ratings = {key: int(value) for key, value in (state.get("ratings") or {}).items()
               if isinstance(value, (int, float)) and 1 <= int(value) <= 5}
    if ratings:
        _survey_to_core(chat_id, str(state.get("name") or ""),
                        text="", ratings=ratings, problems={},
                        impression="", mistakes="", role="", region="",
                        projects=[], source="")
    _feedback_remember(chat_id, {"stage": "text", "rated": len(ratings),
                                 "name": str(state.get("name") or "")})
    if ratings:
        _send_message(
            chat_id,
            f"Оценок записано: {len(ratings)}. Спасибо.\n"
            "Последнее: напишите одной строкой, что улучшить. "
            "Нечего добавить — просто не отвечайте.")
    else:
        _send_message(
            chat_id,
            "Ни одной оценки — ничего страшного. Если есть что сказать, "
            "напишите одной строкой.")


def _feedback_save(chat_id: int, text: str) -> None:
    """Комментарий отдельной записью: оценки уже посчитаны, второй раз нельзя."""
    text = str(text or "").strip()
    if not text:
        return
    _survey_to_core(chat_id, str(_feedback_state(chat_id).get("name") or ""),
                    text=text, ratings={}, problems={}, impression=text,
                    mistakes="", role="", region="", projects=[], source="")
    _feedback_forget(chat_id)
    _send_message(chat_id, "Записал, спасибо. Это доходит до владельца сервиса.")


def _feedback_pending_text(chat_id: int, text: str) -> bool:
    """Свободный текст после анкеты. Возвращает True, если он был её частью."""
    state = _feedback_state(chat_id)
    if str(state.get("stage") or "") != "text" or not text:
        return False
    _feedback_save(chat_id, text)
    return True


def _handle_message(message: dict[str, Any]) -> None:
    chat_id, user_id, text = _extract_message(message)
    if not chat_id:
        return
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
    # Учёт до разбора: сюда сходятся все сообщения бота, и считать их дальше по
    # веткам значило бы потерять те, что уходят в движок.
    core.usage_track("command" if command else "message", chat_id=chat_id, user_id=user_id,
                     name=_sender_name(message), text=text)
    _user_to_core(chat_id, _sender_name(message), "command" if command else "message")
    if command == "/status":
        _status_message(chat_id, user_id)
        return
    if command == "/help":
        _send_help(chat_id)
        return
    if command in {"/krt", "/крт"}:
        _krt_command(chat_id, text)
        return
    if command in {"/feedback", "/оценить"}:
        _feedback_start(chat_id, _sender_name(message))
        return
    if command in {"/survey", "/анкета"}:
        _survey_message(chat_id, user_id, text.split(maxsplit=1)[1] if " " in text else "")
        return
    if command in {"/stats", "/статистика"}:
        _stats_message(chat_id, user_id, text.split(maxsplit=1)[1] if " " in text else "")
        return
    if command in {"/platon", "/платон"}:
        _start_platon(chat_id)
        return
    if command in {"/comment", "/тэп_комментарий"}:
        _comment_tep(chat_id)
        return
    if command in {"/model", "/модель"}:
        _send_model_archive(chat_id)
        return
    if command in {"/vritep", "/vri", "/ври"}:
        _start_vritep(chat_id)
        return
    # Ответ на анкету идёт раньше разбора адресов и вопросов: «дорого и
    # непонятно» — это комментарий, а не кадастровый номер.
    if text and not command and _feedback_pending_text(chat_id, text):
        return
    if text and not command and _vritep_handle_text(chat_id, text):
        return
    if _dialog_active(chat_id) and text:
        if command == "/cancel" or text.lower() in {"стоп", "отмена", "завершить"}:
            _dialog_stop(chat_id)
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
        core.usage_track("button", chat_id=chat_id,
                         user_id=int(sender.get("id") or chat_id or 0),
                         name=_sender_name({"from": sender}), text=data)
        _user_to_core(chat_id, _sender_name({"from": sender}), "button")
        if data in {"vritep_start", "vritep_msk", "vritep_mo"}:
            _answer_callback(query)
            if data == "vritep_start":
                _start_vritep(chat_id)
            else:
                _vritep_ask_input(chat_id, "msk" if data == "vritep_msk" else "mo")
            return
        if data.startswith("fb_"):
            _answer_callback(query)
            if data == "fb_start":
                _feedback_start(chat_id, _sender_name({"from": sender}))
            elif data == "fb_skip":
                _feedback_forget(chat_id)
                _send_message(chat_id, "Хорошо, спрошу в другой раз.")
            elif data == "fb_done":
                _feedback_finish(chat_id)
            elif data.startswith("fb_r"):
                number, _, score = data[len("fb_r"):].partition("_")
                if number.isdigit() and score.isdigit():
                    _feedback_answer(chat_id, int(number), int(score))
            elif data.startswith("fb_s"):
                number = data[len("fb_s"):]
                if number.isdigit():
                    _feedback_answer(chat_id, int(number), None)
            return
        if data in {"ask_platon", "platon_tep", "platon_stop", "platon_discard",
                    "platon_apply", "show_help", "send_model"}:
            _answer_callback(query)
            if data == "show_help":
                _send_help(chat_id)
            elif data == "send_model":
                _send_model_archive(chat_id)
            elif data == "ask_platon":
                _start_platon(chat_id)
            elif data == "platon_tep":
                _comment_tep(chat_id)
            elif data == "platon_stop":
                _dialog_stop(chat_id)
                _send_message(chat_id, "Диалог с Платоном завершён.")
            elif data == "platon_discard":
                with _STATE_LOCK:
                    _PLATON_PENDING.pop(chat_id, None)
                _send_message(chat_id, "Предложенные изменения не применены.", reply_markup=_platon_markup(chat_id))
            elif data == "platon_apply":
                _send_message(chat_id, _applied_message(_apply_proposal(chat_id)),
                              reply_markup=_platon_markup(chat_id))
            return
    message = update.get("message") if isinstance(update, dict) else None
    if isinstance(message, dict):
        _handle_message(message)
        return
    _ORIGINAL_HANDLE_UPDATE(update)


core._telegram_handle_message = _handle_message
core._telegram_handle_update = _handle_update


@app.on_event("startup")
def _start_usage_digest() -> None:
    """Сводка сама приходит раз в сутки — иначе «отслеживать» означает не
    забывать спрашивать."""
    threading.Thread(target=_usage_digest_loop, name="usage-digest", daemon=True).start()


@app.on_event("startup")
def _configure_platon_command() -> None:
    # Список команд — один, живёт в движке (TELEGRAM_BOT_COMMANDS): у обёртки
    # был свой, движок ставил свой при настройке вебхука, и побеждал
    # последний — /vritep из меню пропадал, хотя команда работала.
    if not core._telegram_token():
        return
    try:
        core._telegram_api("setMyCommands", {"commands": core.TELEGRAM_BOT_COMMANDS})
    except Exception as exc:
        core._TELEGRAM_RUNTIME["last_error"] = str(exc)


def _krt_command(chat_id: int, text: str) -> None:
    """Подписка на новые площадки КРТ.

    Состояние называется всегда — и когда его меняли, и когда просто спросили:
    «подписка включена» после повторного «подписаться» и после первого выглядят
    одинаково намеренно. Иначе человек жмёт второй раз, чтобы убедиться, и
    снимает подписку.
    """
    argument = text.split(maxsplit=1)[1].strip().lower() if " " in text.strip() else ""
    try:
        if argument in {"вкл", "on", "подписаться", "да"}:
            state = _krt_subscription(chat_id, True)
        elif argument in {"выкл", "off", "отписаться", "нет", "стоп"}:
            state = _krt_subscription(chat_id, False)
        else:
            # Без аргумента — переключатель: одна команда вместо двух, которые
            # надо помнить. Что получилось, сказано следующей строкой.
            state = _krt_subscription(chat_id, not _krt_subscription(chat_id))
    except Exception as exc:
        _send_message(chat_id, f"Подписку изменить не удалось: {exc}")
        return
    if state:
        _send_message(chat_id, "Подписка на новые площадки КРТ включена. "
                       "Каталог обновляется раз в неделю; сообщу, когда появится новая. "
                       "Выключить — /krt выкл")
    else:
        _send_message(chat_id, "Подписка на новые площадки КРТ выключена. Включить — /krt вкл")
