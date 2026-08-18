"""Оценка рынка конкурентов в боте.

Коммерческому блоку рынок нужен раньше модели: «что рядом строят и почём» —
самостоятельный вопрос, ответ на который принимают до того, как считать
экономику. В боте он живёт отдельной командой, а не пунктом внутри расчёта.

Считает тот же ``assessment.assess``, что и панель с Платоном: правило
«поверхности считают один раз» здесь не формальность — бот и сайт уже
расходились числами там, где каждый считал своё.

Поиск ходит в Yandex Search API десятками запросов и геокодирует каждый
найденный проект. Внутри обработчика вебхука такому места нет — Telegram ждёт
ответ, а не работу: карточка уходит фоном, как фото территории.
"""

from __future__ import annotations

import copy
import html
import threading
from typing import Any

from .assessment import ASKING, OFFICIAL, assess

MENU_TEXT = "📈 Рынок конкурентов"
COMMAND = "/market"
CALLBACK = "market_start"
_STEP = "market_await_address"

_ASK = (
    "<b>Оценка рынка конкурентов</b>\n\n"
    "Пришлите адрес площадки одним сообщением — например, "
    "<code>Москва, ул. Мишина, 46</code>.\n\n"
    "Я найду строящиеся и продающиеся рядом жилые комплексы, покажу их цены за м², "
    "класс, застройщика и темп продаж и предложу цену для поля «Цена квартир»."
)


def _num(value: Any, digits: int = 0) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    text = f"{number:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def _rub_m2(value: Any) -> str:
    return "—" if not value else f"{_num(round(float(value)))} ₽/м²"


def _analogue_line(item: dict[str, Any]) -> str:
    head = f"• <b>{html.escape(str(item.get('name') or '—'))}</b>"
    facts = []
    if item.get("distance_km") is not None:
        facts.append(f"{_num(item['distance_km'], 1)} км")
    if item.get("segment"):
        facts.append(html.escape(str(item["segment"])))
    if item.get("developer"):
        facts.append(html.escape(str(item["developer"])))
    line = head + (" — " + " · ".join(facts) if facts else "")

    if item.get("price_per_sqm") and item.get("price_basis") == ASKING:
        price = f"\n  {_rub_m2(item['price_per_sqm'])}"
        if item.get("sample_count"):
            price += f" · наблюдений {int(item['sample_count'])}"
        if item.get("price_sources"):
            price += " · " + html.escape(", ".join(str(one) for one in item["price_sources"][:3]))
    elif item.get("price_per_sqm") and item.get("price_basis") == OFFICIAL:
        price = f"\n  средняя по сделкам ЕИСЖС {_rub_m2(item['price_per_sqm'])} — не цена предложения"
    else:
        price = "\n  " + html.escape(str(item.get("price_reason") or "проверенной цены нет"))
    line += price

    tail = []
    if item.get("sales_per_month") is not None:
        tail.append(f"продажи {int(item['sales_per_month'])} ДДУ/мес")
    if item.get("inventory_units") is not None:
        tail.append(f"экспозиция {int(item['inventory_units'])} лот.")
    if tail:
        line += "\n  " + " · ".join(tail)
    return line


def card(assessment: dict[str, Any]) -> str:
    """Карточка оценки для чата.

    Показывает то же, что панель, и теми же словами: основание цены названо
    прямо, карантин виден числом. Скрытая потеря кандидата выглядит как хороший
    результат — в чате это тем более так, там нет вкладки «диагностика».
    """
    if not assessment.get("available"):
        return (
            "<b>Оценка рынка не выполнена</b>\n"
            + html.escape(str(assessment.get("reason") or "причина неизвестна"))
        )

    lines = [
        "<b>Рынок конкурентов</b>",
        html.escape(str(assessment.get("address") or "—")),
    ]
    where = []
    if assessment.get("radius_km"):
        where.append(f"радиус {_num(assessment['radius_km'], 1)} км")
    if assessment.get("district"):
        where.append(html.escape(str(assessment["district"])))
    if assessment.get("segment"):
        where.append("класс " + html.escape(str(assessment["segment"])))
    if where:
        lines.append(" · ".join(where))
    lines.append("")

    price = assessment.get("price_per_sqm")
    if price and assessment.get("price_basis") == ASKING:
        lines.append(f"<b>Ориентир по ценам предложения: {_rub_m2(price)}</b>")
        low, high = assessment.get("corridor_low_per_sqm"), assessment.get("corridor_high_per_sqm")
        if low and high:
            lines.append(f"Коридор {_rub_m2(low)} — {_rub_m2(high)}")
        lines.append(
            f"Аналогов в расчёте: {int(assessment.get('analogue_count') or 0)}"
            + (f" · уверенность {assessment['confidence']}" if assessment.get("confidence") else "")
        )
    elif price and assessment.get("price_basis") == OFFICIAL:
        lines.append("<b>Цен предложения не найдено.</b>")
        lines.append(
            f"Среднее по зарегистрированным сделкам ЕИСЖС: {_rub_m2(price)}. "
            "Оно отстаёт от рынка — проверьте перед применением."
        )
    else:
        lines.append("<b>Ориентир не посчитан:</b> ни у одного аналога нет доказанной цены.")

    lines.append("")
    lines.append(
        f"Найдено проектов: {int(assessment.get('found_count') or 0)} · "
        f"с проверенной ценой: {int(assessment.get('priced_count') or 0)} · "
        f"в карантине: {int(assessment.get('quarantine_count') or 0)}"
    )
    summary = assessment.get("quarantine_summary") or []
    if summary:
        lines.append(
            "Карантин: "
            + " · ".join(
                f"{html.escape(str(item['label']))} — {int(item['count'])}" for item in summary[:5]
            )
        )

    analogues = assessment.get("analogues") or []
    if analogues:
        lines.append("")
        lines.append("<b>Аналоги</b>")
        lines.extend(_analogue_line(item) for item in analogues[:8])

    if assessment.get("warning"):
        lines.append("")
        lines.append("<i>" + html.escape(str(assessment["warning"])) + "</i>")
    return "\n".join(lines)


def _markup(base: Any, chat_id: int, assessment: dict[str, Any]) -> dict[str, Any] | None:
    """Кнопка открывает модель с посчитанной ценой в поле «Цена квартир».

    Только по ценам предложения. Официальную среднюю ЕИСЖС применять кнопкой
    нельзя: она не цена предложения, и подпись под кнопкой этого не удержит.
    """
    price_th = assessment.get("price_th_per_sqm")
    if not price_th or assessment.get("price_basis") != ASKING:
        return None
    try:
        url = base.core._telegram_web_app_url(
            chat_id, [], calc_overrides={"apartment_price_th": float(price_th)}
        )
    except Exception:
        return None
    return {"inline_keyboard": [[{
        "text": f"Открыть модель с ценой {_num(price_th, 1)} тыс. ₽/м²",
        "web_app": {"url": url},
    }]]}


def _run(base: Any, service: Any, chat_id: int, address: str) -> None:
    send = base.core._telegram_send_message
    try:
        assessment = assess(service, address=address)
        send(chat_id, card(assessment), reply_markup=_markup(base, chat_id, assessment))
    except Exception as exc:  # noqa: BLE001 — хостинг закрыт, причина доносится в чат
        send(
            chat_id,
            "<b>Оценка рынка не выполнена</b>\n" + html.escape(f"{type(exc).__name__}: {exc}"[:400]),
        )


def _start(base: Any, service: Any, chat_id: int, address: str) -> None:
    if not address:
        base.core._telegram_dialog_save(chat_id, {"step": _STEP, "data": {}})
        base.core._telegram_send_message(chat_id, _ASK)
        return
    base.core._telegram_dialog_clear(chat_id)
    base.core._telegram_send_message(
        chat_id,
        "<b>Ищу конкурентов рядом с адресом</b>\n"
        + html.escape(address)
        + "\n\nЭто занимает до минуты: поиск обходит каталоги и реестр ЕИСЖС, "
        "а каждый найденный проект геокодируется по собственному адресу.",
    )
    threading.Thread(
        target=_run, args=(base, service, chat_id, address), name="market-assessment", daemon=True
    ).start()


def _ensure_command(core: Any) -> None:
    commands = getattr(core, "TELEGRAM_BOT_COMMANDS", None)
    if not isinstance(commands, list):
        return
    name = COMMAND.lstrip("/")
    if any(isinstance(item, dict) and str(item.get("command") or "") == name for item in commands):
        return
    anchor = str(getattr(core, "TELEGRAM_MENU_EXTENSION_ANCHOR", "") or "")
    position = next(
        (index for index, item in enumerate(commands)
         if isinstance(item, dict) and str(item.get("command") or "") == anchor),
        len(commands),
    )
    commands.insert(position, {"command": name, "description": "Оценка рынка конкурентов"})


def _help_with_market(markup: Any) -> Any:
    if not isinstance(markup, dict):
        return markup
    rows = markup.get("inline_keyboard")
    if not isinstance(rows, list):
        return markup
    for row in rows:
        for button in row if isinstance(row, list) else []:
            if isinstance(button, dict) and str(button.get("callback_data") or "") == CALLBACK:
                return markup
    # Пункт принадлежит только главному меню, узнаваемому по расчёту ВРИ/ТЭП.
    # Временные клавиатуры одного шага остаются нетронутыми.
    if not any(
        isinstance(button, dict) and str(button.get("callback_data") or "") == "vritep_start"
        for row in rows if isinstance(row, list)
        for button in row
    ):
        return markup
    updated = copy.deepcopy(markup)
    updated["inline_keyboard"].insert(3, [{"text": MENU_TEXT, "callback_data": CALLBACK}])
    return updated


def install(base: Any, service: Any) -> None:
    if getattr(base, "_MARKET_BOT_INSTALLED", False):
        return
    core = base.core
    _ensure_command(core)

    previous_help_markup = getattr(base, "_help_markup", None)
    if callable(previous_help_markup):
        def help_markup(chat_id: int) -> Any:
            return _help_with_market(previous_help_markup(chat_id))
        base._help_markup = help_markup

    previous_handle_update = core._telegram_handle_update

    def handle_update(update: dict[str, Any]) -> None:
        if isinstance(update, dict) and _intercept(base, service, update):
            return
        previous_handle_update(update)

    core._telegram_handle_update = handle_update
    base._MARKET_BOT_INSTALLED = True


def _intercept(base: Any, service: Any, update: dict[str, Any]) -> bool:
    """Взять на себя своё и только своё.

    Шаг ожидания адреса разбирается здесь же: движок про него не знает, и без
    перехвата адрес уехал бы в разбор кадастровых номеров.
    """
    query = update.get("callback_query")
    if isinstance(query, dict) and str(query.get("data") or "") == CALLBACK:
        message = query.get("message") or {}
        sender = query.get("from") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or sender.get("id") or 0)
        if not chat_id:
            return False
        query_id = str(query.get("id") or "")
        if query_id:
            try:
                base.core._telegram_api("answerCallbackQuery", {"callback_query_id": query_id})
            except Exception:
                # Часы ожидания на кнопке — косметика; оценка важнее.
                pass
        _start(base, service, chat_id, "")
        return True

    message = update.get("message")
    if not isinstance(message, dict):
        return False
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = int(chat.get("id") or sender.get("id") or 0)
    if not chat_id or str(chat.get("type") or "private") != "private":
        return False
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""

    if command == COMMAND or text == MENU_TEXT:
        argument = text.split(maxsplit=1)[1].strip() if command and " " in text else ""
        _start(base, service, chat_id, argument)
        return True

    dialog = base.core._telegram_dialog_get(chat_id) or {}
    if str(dialog.get("step") or "") != _STEP:
        return False
    if command:
        # Любая другая команда прерывает ожидание адреса: она и есть решение
        # человека уйти из этого шага, а молча съеденная команда выглядит как
        # зависший бот.
        base.core._telegram_dialog_clear(chat_id)
        return False
    if not text:
        return False
    _start(base, service, chat_id, text)
    return True
