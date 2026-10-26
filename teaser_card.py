"""Карточка разбора тизера — один источник для сайта и бота.

Путь владельца (25.10.2026), одинаковый на сайте и в Telegram:

1. Разбор показывает КАРТОЧКУ и ничего не спрашивает: что найдено в тизере
   (у каждого числа страница), что именно уйдёт в расчёт (поле движка и
   значение с происхождением) и чего не хватает — что тогда возьмётся по
   умолчанию, по норме или посчитается по участку.
2. Потом вопросы — только о недостающем, по одному. Ответ меняет карточку, а
   не модель.
3. Расчёт — только кнопкой «Всё верно, считать», и движок получает ровно то,
   что стоит в карточке.

Прежде всё шло сразу: таблица разбора и первый вопрос приходили вместе, каждый
ответ тут же писался в модель и пересчитывал её, а числа таблицы без отдельной
кнопки не доходили до движка вовсе — и было непонятно, что ушло в расчёт.

Карточка — функция состояния, а не накопленный итог: модель до тизера плюс
найденное плюс ответы. Поэтому её можно собрать заново в любом воркере и по
любым текущим вводным, и сайт с ботом показывают одно и то же.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import document_intake as di

# Найденное в тизере ложится в модель только через `di.apply_intake` — тот же
# писатель, что и прежде; здесь он зовётся по одному полю, чтобы у каждой
# записанной строки было своё происхождение (страница и цитата).

CLASS_KEYS = ("apartment_price_th", "commercial_price_th", "parking_price_th",
              "main_above_th_per_sqm", "main_under_th_per_sqm")
CLASS_LABELS = {
    "project_class": ("Класс жилья", ""),
    "apartment_price_th": ("Цена продажи квартир", "тыс. ₽ за м²"),
    "commercial_price_th": ("Цена продажи нежилых помещений", "тыс. ₽ за м²"),
    "parking_price_th": ("Цена машино-места", "тыс. ₽ за место"),
    "main_above_th_per_sqm": ("Стоимость строительства наземной части", "тыс. ₽ за м²"),
    "main_under_th_per_sqm": ("Стоимость строительства подземной части", "тыс. ₽ за м²"),
}

# Подписи карточки для посетителя (`docs/plain_language.md`): без «ГНС»,
# «СПП», «ДОО» и прочего внутреннего языка. Ключи и единицы — из
# `di.INTAKE_FIELDS`, здесь только слова.
PLAIN_LABELS = {
    "cadastral_numbers": "Кадастровые номера участка",
    "site_area_ha": "Площадь участка",
    "purchase_price_mln": "Цена покупки участка или проекта",
    "social_compensation_mln": "Выплата городу вместо строительства школ и детских садов",
    "land_rights_cost_mln": "Плата за смену разрешённого использования участка",
    "vri_relief_mln": "Льгота по плате за смену разрешённого использования",
    "resettlement_cost_mln": "Расселение жильцов и арендаторов",
    "demolition_area_sqm": "Площадь зданий под снос",
    "apartments_gns_sqm": "Площадь квартир",
    "residential_spp_sqm": "Площадь жилого дома целиком, с магазинами первого этажа",
    "offices_gba_sqm": "Площадь офисов",
    "retail_gba_sqm": "Площадь торгового центра",
    "underground_manual_spaces": "Машино-места в подземном паркинге",
    "kindergarten_places": "Детский сад, мест",
    "school_places": "Школа, мест",
    "clinic_capacity": "Поликлиника, посещений в смену",
}
PLAIN_UNITS = {"пос./смену": "посещений", "шт.": "мест", "список": ""}


def plain_label(key: str) -> str:
    return PLAIN_LABELS.get(key) or di.INTAKE_LABELS.get(key, key)


# Подписи полей, которые пишет разбор помимо своих ключей.
EXTRA_LABELS = {
    "tep.apartments.gns": ("Площадь квартир", "м²"),
    "tep.ground_commercial.gns": ("Площадь магазинов на первом этаже", "м²"),
    "inputs.offices_enabled": ("Офисы в расчёте", ""),
    "inputs.retail_enabled": ("Торговый центр в расчёте", ""),
    "inputs.offices_saleable_sqm": ("Продаваемая площадь офисов", "м²"),
    "inputs.retail_saleable_sqm": ("Продаваемая площадь торгового центра", "м²"),
    "inputs.vri_relief_mode": ("Как считать льготу по плате за ВРИ", ""),
    "inputs.purchase_schedule": ("График оплаты покупки", ""),
}

# Пути, которые разбор обнуляет, чтобы их пересчитал расчёт (продаваемая
# площадь включённого объекта — долями объекта). Их число в карточке —
# «посчитается», а не значение, и сверка с расчётом его не сравнивает.
DERIVED_PATHS = {"inputs.offices_saleable_sqm", "inputs.retail_saleable_sqm"}

# Что сказать о расчёте участка, когда он не московский.
PARCEL_REGION_NOTES = {
    "other": ("Участок не в Москве и не в Московской области. Норм этого региона у нас нет, "
              "поэтому считаем по нашим умолчаниям: они видны в разделе 3."),
    "mo": "Участок в Московской области: расчёт пойдёт по нормам области.",
    "mixed": ("В тизере участки из разных регионов. Посчитать их одним расчётом нельзя: "
              "пришлите номера одного региона."),
    "unknown": ("Не удалось определить, Новая Москва это или Московская область: калькулятор "
                "ГлавАПУ не ответил. Угадывать по номеру не будем, поэтому кнопки расчёта пока "
                "нет. Нажмите «Проверить участок ещё раз»."),
}

RELIEF_KEY = "vri_relief_mln"
CLASS_CARD_KIND = "class"
RELIEF_CARD_KIND = "relief"


# --- страница источника ------------------------------------------------------

_PAGE_MARK_RE = re.compile(r"\[стр\. (\d+)\]")


def _squash(text: str) -> str:
    return re.sub(r"[\s  ]+", " ", str(text or "")).strip().lower()


def quote_page(text: str, quote: str) -> int | None:
    """Номер страницы, на которой стоит цитата, по меткам `[стр. N]` текста.

    Страницу называет текст документа, а не модель: цитата ищется в тексте, и
    страница — ближайшая метка перед ней. Не нашлась — None, а не догадка.
    """
    body = str(text or "")
    marks = [(m.start(), int(m.group(1))) for m in _PAGE_MARK_RE.finditer(body)]
    if not marks:
        return None
    flat = _squash(body)
    # Позиции в сжатом тексте не совпадают с исходными — сжимаем каждую
    # страницу отдельно и ищем цитату в ней.
    bounds = [start for start, _ in marks] + [len(body)]
    parts = [str(quote or "")]
    # Склеенная цитата нескольких строк («… | …») ищется по первой части.
    parts += [part for part in str(quote or "").split("|") if part.strip()]
    for part in parts:
        needle = _squash(part)
        if len(needle) < 4 or needle not in flat:
            continue
        for index, (_, page) in enumerate(marks):
            if needle in _squash(body[bounds[index]:bounds[index + 1]]):
                return page
    return None


def locate_pages(fields: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Страница у каждой найденной строки: по тексту, иначе по словам разбора."""
    out = []
    for item in fields:
        row = dict(item)
        page = quote_page(text, str(row.get("quote") or ""))
        if page is not None:
            row["page"], row["page_checked"] = page, True
        else:
            said = row.get("page")
            row["page"] = int(said) if isinstance(said, int) or str(said or "").isdigit() else None
            row["page_checked"] = False
        out.append(row)
    return out


def page_text(row: dict[str, Any]) -> str:
    """«стр. 3», «стр. 3 по словам разбора» или «страница не найдена»."""
    page = row.get("page")
    if page is None:
        return "страница не найдена: цитаты нет в тексте документа"
    if row.get("page_checked") is False:
        return f"стр. {page} (по словам разбора — цитата в тексте не найдена)"
    return f"стр. {page}"


# --- состояние: найденное и вопросы -------------------------------------------

def class_presets(presets: dict[str, dict[str, Any]],
                  profile: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Профили классов для карточки: базовые и, поверх, числа страницы.

    Страница знает, что класс поставит в ЭТОМ проекте: регион, личные
    настройки класса, вид проекта (`classValue`). Она присылает эти числа, и
    карточка показывает их, а не московскую базу. Бот присылает пусто — у
    него класс ставится базой, как в экспресс-расчёте.
    """
    out = {key: dict(value) for key, value in presets.items()}
    for key, values in (profile or {}).items():
        if key not in out or not isinstance(values, dict):
            continue
        for name in CLASS_KEYS:
            try:
                number = float(values[name])
            except (KeyError, TypeError, ValueError):
                continue
            if number == number:  # не NaN
                out[key][name] = number
    return out


def class_question(presets: dict[str, dict[str, Any]], current: str) -> dict[str, Any]:
    options = []
    for key, preset in presets.items():
        label = str(preset.get("label") or key)
        options.append({"label": label + (" — как сейчас в модели" if key == current else ""),
                        "target": "project_class", "value": key, "unit": "", "why": ""})
    return {"kind": CLASS_CARD_KIND, "key": "project_class", "label": "Класс жилья",
            "question": ("Какой класс жилья считать? В тизере класс не назван, а от него "
                         "зависят цены продаж и стоимость строительства."),
            "unit": "", "adds": False, "options": options}


def relief_question(field: dict[str, Any]) -> dict[str, Any]:
    said = f"{field.get('value')} {field.get('unit') or ''}".strip()
    return {"kind": RELIEF_CARD_KIND, "key": RELIEF_KEY,
            "label": di.INTAKE_LABELS[RELIEF_KEY],
            "question": (f"В тизере названа льгота по плате за смену ВРИ: {said}. Взять эту "
                         "сумму или пусть модель посчитает льготу сама по постановлению 1874-ПП?"),
            "unit": "млн ₽", "adds": False,
            "options": [{"label": "Пусть модель посчитает сама", "target": "", "value": None,
                         "unit": "", "why": ""},
                        {"label": f"Взять сумму тизера — {said}", "target": RELIEF_KEY,
                         "value": None, "unit": "млн ₽", "why": ""}]}


def start(extraction: dict[str, Any], document: dict[str, Any], filename: str,
          *, presets: dict[str, dict[str, Any]], current_class: str) -> dict[str, Any]:
    """Состояние разбора: найденное (со страницами) и очередь вопросов.

    Вопросы — только о том, чего в тизере нет. Вопрос модели о поле, которое
    тизер уже назвал, снимается: на него ответил документ. Неотмеченное
    разбором (льгота МПТ — заявление продавца) становится вопросом, а не
    галочкой в таблице. Класс жилья тизер не называет — он спрашивается
    последним.
    """
    fields = locate_pages(list(extraction.get("fields") or []), str(document.get("text") or ""))
    found = {row["key"] for row in fields}
    cards, answered_by_document = [], []
    for item in extraction.get("questions") or []:
        key = str(item.get("key") or "").strip()
        if key and key in found:
            answered_by_document.append(str(item.get("question") or ""))
            continue
        cards.append(di.question_card(item))
    relief = next((row for row in fields if row["key"] == RELIEF_KEY), None)
    if relief is not None:
        cards.append(relief_question(relief))
    cards.append(class_question(presets, current_class))
    return {
        "filename": filename,
        "pages": document.get("pages"),
        "recognized": bool(document.get("recognized")),
        "fields": fields,
        "not_asked": list(extraction.get("not_asked") or []),
        "answered_by_document": answered_by_document,
        "notes": [str(note) for note in (extraction.get("notes") or [])],
        "dropped": list(extraction.get("dropped") or []),
        "reason": str(extraction.get("reason") or ""),
        "cards": cards, "index": 0, "answers": [],
    }


# --- значения: модель до тизера + найденное + ответы ---------------------------

def _path_of(row: dict[str, Any]) -> str:
    if row.get("path"):
        return str(row["path"])
    if row.get("key") == "apartments_gns_sqm":
        return "tep.apartments.gns"
    return "inputs." + str(row.get("key"))


def _quote(text: Any, limit: int = 140) -> str:
    said = re.sub(r"\s+", " ", str(text or "")).strip()
    return said if len(said) <= limit else said[:limit - 1].rstrip() + "…"


def replay(state: dict[str, Any], inputs: dict[str, Any], tep: dict[str, dict[str, Any]],
           *, spp_split: dict[str, float] | None,
           presets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Вводные, которые получит движок: текущие вводные + тизер + ответы.

    Возвращает вводные и ТЭП, происхождение каждого записанного пути
    (`origins`) и то, что найдено, но не записано (`refused`, с причиной).
    """
    filename = str(state.get("filename") or "документ")
    new_inputs = copy.deepcopy(dict(inputs or {}))
    new_tep = copy.deepcopy({key: dict(value) for key, value in (tep or {}).items()})
    origins: dict[str, dict[str, Any]] = {}
    refused: list[dict[str, Any]] = []
    land: list[str] = []

    def note(row: dict[str, Any], origin: dict[str, Any]) -> None:
        path = _path_of(row)
        label, unit = EXTRA_LABELS.get(path, (
            PLAIN_LABELS.get(str(row.get("key"))) or row.get("label") or row.get("key"),
            PLAIN_UNITS.get(str(row.get("unit") or ""), row.get("unit") or "")))
        read_as = row.get("read_as") or ""
        parts = row.get("parts") or []
        if len(parts) > 1 or (parts and row.get("base")):
            # Сумма обязательств — из чего она сложилась, а не одно число.
            read_as = "сумма: " + " + ".join(
                ([_fmt(row["base"]) + " уже стояло в проекте"] if row.get("base") else [])
                + [_fmt(part.get("value")) for part in parts]) + (f", {read_as}" if read_as else "")
        origins[path] = {"label": label, "unit": unit, "shown": row.get("shown") or "",
                         "read_as": read_as,
                         # Ноль-сигнал «пересчитай»: число посчитает расчёт
                         # долями объекта, и карточка так и пишет.
                         "derived": path in DERIVED_PATHS, **origin}

    for field in state.get("fields") or []:
        key = field["key"]
        if key == RELIEF_KEY:
            continue  # льгота ложится только ответом на свой вопрос
        source = {"source": "document", "field": key, "page": field.get("page"),
                  "page_checked": field.get("page_checked"),
                  "text": (f"тизер «{filename}», {page_text(field)}: "
                           f"«{_quote(field.get('quote'))}»")}
        if key == "cadastral_numbers":
            got = di.apply_intake({"fields": [field]}, {}, {}, accept=[key])
            if got["applied"]:
                raw = field.get("value")
                land = [str(one) for one in raw] if isinstance(raw, (list, tuple)) else [str(raw)]
                origins["land.cadastral_numbers"] = {
                    "label": "Кадастровые номера участка", "unit": "", "shown": ", ".join(land),
                    "read_as": "", **source}
            continue
        got = di.apply_intake({"fields": [field]}, new_inputs, new_tep, accept=[key],
                              spp_split=spp_split)
        new_inputs, new_tep = got["inputs"], got["tep"]
        for row in got["applied"]:
            note(row, source)
        for row in got["refused"]:
            refused.append({**row, "page": field.get("page"), "quote": field.get("quote")})

    cards = state.get("cards") or []
    ledger: dict[str, Any] = {}
    kept: list[dict[str, Any]] = []
    for answer in state.get("answers") or []:
        if answer.get("action") != "answer":
            continue
        index = int(answer.get("index") or 0)
        if not 0 <= index < len(cards):
            continue
        card = cards[index]
        choice = int(answer.get("choice") if answer.get("choice") is not None else -1)
        option = (card.get("options") or [])[choice] if 0 <= choice < len(card.get("options") or []) else None
        said = str(answer.get("answer") or "")
        mine = {"source": "document",
                "text": f"ваш ответ на вопрос по тизеру «{filename}»: «{_quote(said, 90)}»"}
        if card.get("kind") == CLASS_CARD_KIND:
            key = str((option or {}).get("value") or "")
            if key not in presets:
                continue
            new_inputs["project_class"] = key
            note({"path": "inputs.project_class", "label": "Класс жилья",
                  "shown": str(presets[key].get("label") or key)}, mine)
            # Вписанное руками класс не меняет — так же, как смена класса на
            # странице (`_class_manual`); карточка называет его отдельно.
            by_hand = set(new_inputs.get("_class_manual") or [])
            for name in CLASS_KEYS:
                if name in by_hand:
                    label, unit = CLASS_LABELS[name]
                    kept.append({"key": name, "path": "inputs." + name, "label": label,
                                 "value": new_inputs.get(name), "unit": unit})
                    continue
                if name in presets[key]:
                    new_inputs[name] = float(presets[key][name])
                    label, unit = CLASS_LABELS[name]
                    note({"path": "inputs." + name, "label": label, "unit": unit},
                         {"source": "document",
                          "text": f"по умолчанию класса «{presets[key].get('label') or key}» — "
                                  "его выбрали в ответе"})
            continue
        if card.get("kind") == RELIEF_CARD_KIND:
            if not option or not option.get("target"):
                continue
            field = next((row for row in state.get("fields") or [] if row["key"] == RELIEF_KEY), None)
            if field is None:
                continue
            got = di.apply_intake({"fields": [field]}, new_inputs, new_tep, accept=[RELIEF_KEY])
            new_inputs, new_tep = got["inputs"], got["tep"]
            for row in got["applied"]:
                note(row, {"source": "document", "field": RELIEF_KEY, "page": field.get("page"),
                           "page_checked": field.get("page_checked"),
                           "text": (f"тизер «{filename}», {page_text(field)}: "
                                    f"«{_quote(field.get('quote'))}» — взято вашим ответом")})
            for row in got["refused"]:
                refused.append({**row, "page": field.get("page"), "quote": field.get("quote")})
            continue
        got = di.answer_card(card, new_inputs, new_tep, choice=choice,
                             typed=str(answer.get("value") or ""), ledger=ledger,
                             mode=str(answer.get("mode") or ""))
        if got.get("confirm"):
            refused.append({"key": got["confirm"]["key"], "label": got["confirm"]["label"],
                            "value": said, "reason": "не решено, прибавить или заменить"})
            continue
        new_inputs, new_tep = got["inputs"], got["tep"]
        for row in got["applied"]:
            note(row, mine)
        refused.extend(got["refused"])
    return {"inputs": new_inputs, "tep": new_tep, "origins": origins,
            "refused": refused, "land": land, "ledger": ledger, "kept": kept}


def answer(state: dict[str, Any], inputs: dict[str, Any], tep: dict[str, dict[str, Any]], *,
           index: int, action: str, choice: int = -1, value: str = "", mode: str = "",
           spp_split: dict[str, float] | None, presets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Ответ на текущий вопрос. Меняет состояние разбора, а не модель.

    Возвращает {"stale"} для чужого номера вопроса, {"confirm"} — если в поле
    уже своё число и надо решить, прибавить или заменить; иначе ответ
    записан, и `state["index"]` указывает на следующий вопрос.
    """
    cards = state.get("cards") or []
    current = int(state.get("index") or 0)
    if index != current or current >= len(cards):
        return {"stale": True}
    card = cards[current]
    action = action if action in ("answer", "skip", "stop") else "answer"
    record: dict[str, Any] = {"index": current, "action": action, "question": card.get("question")}
    if action == "answer":
        options = card.get("options") or []
        option = options[choice] if 0 <= choice < len(options) else None
        said = " — ".join(part for part in ((option or {}).get("label") or "",
                                            str(value or "").strip()) if part)
        record.update(choice=choice, value=str(value or "").strip(), mode=mode, answer=said)
        if card.get("kind") not in (CLASS_CARD_KIND, RELIEF_CARD_KIND):
            # Прибавить или заменить решает человек — до записи ответа.
            before = replay(state, inputs, tep, spp_split=spp_split, presets=presets)
            probe = di.answer_card(card, before["inputs"], before["tep"], choice=choice,
                                   typed=str(value or ""), ledger=before["ledger"], mode=mode)
            if probe.get("confirm"):
                return {"confirm": probe["confirm"], "answer": said}
            record["refused"] = probe.get("refused") or []
            record["applied"] = probe.get("applied") or []
        elif option is None:
            record["refused"] = [{"key": card.get("key"), "label": card.get("label"),
                                  "value": said, "reason": "выберите вариант"}]
    state["answers"] = list(state.get("answers") or []) + [record]
    state["index"] = len(cards) if action == "stop" else current + 1
    return {"answer": record}


# --- карточка ----------------------------------------------------------------

def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
        return text.replace(",", " ").replace(".", ",")
    return str(value)


def _value_at(path: str, inputs: dict[str, Any], tep: dict[str, dict[str, Any]],
              land: list[str]) -> Any:
    parts = path.split(".")
    if parts[0] == "inputs":
        return inputs.get(parts[1])
    if parts[0] == "tep" and len(parts) == 3:
        return (tep.get(parts[1]) or {}).get(parts[2])
    if path == "land.cadastral_numbers":
        return list(land)
    return None


def _model_origin(path: str, value: Any, base_inputs: dict[str, Any],
                  defaults: dict[str, Any]) -> str:
    """Откуда в модели значение, которого тизер не дал."""
    origin = ((base_inputs.get("_field_origin") or {}).get(path) or {})
    if origin.get("text"):
        return str(origin["text"])
    if value is None or value == "":
        # Пустое поле — не ноль и не решение: так и говорим.
        return "В модели не задано"
    key = path.split(".", 1)[1] if path.startswith("inputs.") else ""
    if key and key in defaults and defaults.get(key) == value:
        return "По умолчанию модели DevelopAid"
    return "Уже стоит в проекте"


def build(state: dict[str, Any], inputs: dict[str, Any], tep: dict[str, dict[str, Any]], *,
          spp_split: dict[str, float] | None, presets: dict[str, dict[str, Any]],
          defaults: dict[str, Any], by_parcel: bool = False,
          parcel_region: str = "moscow") -> dict[str, Any]:
    """Карточка: найдено / уйдёт в расчёт / не хватает — и текущий вопрос.

    `by_parcel` — расчёт сам посчитает участок по кадастровому номеру
    (мини-приложение бота). Тогда то, что считают нормы, до расчёта числа не
    имеет и так и показывается, а не нулём. `parcel_region` — чьи это нормы:
    «moscow» (калькулятор ГлавАПУ), «mo» (нормы Московской области), «other»
    (норм региона у нас нет — наши умолчания), «mixed» (участки разных
    регионов — расчёта нет), «unknown» (50:… без ответа ГлавАПУ: Новая Москва
    или область — неизвестно, и это не угадывается).
    """
    got = replay(state, inputs, tep, spp_split=spp_split, presets=presets)
    origins, pending_inputs, pending_tep = got["origins"], got["inputs"], got["tep"]
    land = got["land"]
    cards = state.get("cards") or []
    index = int(state.get("index") or 0)
    pending_keys = {str(card.get("key") or "") for card in cards[index:]}

    found = []
    refused_by_key = {str(row.get("key")): row for row in got["refused"]}
    for field in state.get("fields") or []:
        key = field["key"]
        paths = [path for path, origin in origins.items() if origin.get("field") == key]
        if key == RELIEF_KEY and not paths:
            status = ("Спрошу ниже, взять ли эту сумму"
                      if RELIEF_KEY in pending_keys else
                      "В расчёт не идёт: модель считает льготу сама")
        elif key in refused_by_key and not paths:
            status = "В расчёт не идёт: " + str(refused_by_key[key].get("reason") or "")
        elif paths:
            status = "Идёт в расчёт"
        else:
            status = "В расчёт не идёт"
        found.append({"key": key, "label": plain_label(key),
                      "value": field.get("value"),
                      "unit": PLAIN_UNITS.get(str(field.get("unit") or ""), field.get("unit") or ""),
                      "quote": _quote(field.get("quote"), 200), "page": field.get("page"),
                      "page_text": page_text(field), "status": status, "used": bool(paths)})

    to_engine = []
    for path, origin in origins.items():
        value = _value_at(path, pending_inputs, pending_tep, land)
        shown = origin.get("shown") or (_fmt(value) + (f" {origin['unit']}" if origin.get("unit") else ""))
        if origin.get("read_as"):
            shown += f" ({origin['read_as']})"
        to_engine.append({"path": path, "label": origin["label"], "value": value,
                          "unit": origin.get("unit") or "", "shown": shown,
                          "source": origin.get("source") or "document",
                          "derived": bool(origin.get("derived")),
                          "origin": origin.get("text") or "", "page": origin.get("page")})

    missing = []
    has_parcel = bool(land)
    for row in di.INTAKE_FIELDS:
        key = row["key"]
        if key in ("cadastral_numbers", RELIEF_KEY, "residential_spp_sqm"):
            continue
        path = "tep.apartments.gns" if key == "apartments_gns_sqm" else "inputs." + key
        if path in origins:
            continue
        unit = PLAIN_UNITS.get(row["unit"], row["unit"])
        value = _value_at(path, pending_inputs, pending_tep, land)
        if key in pending_keys:
            how, text = "ask", "Спрошу ниже."
        elif (row["origin"] in ("glavapu", "egrn") and by_parcel and has_parcel
              and parcel_region == "other" and key not in ("site_area_ha", "apartments_gns_sqm")):
            # Другой регион считается, но не нашими нормами: плата за смену
            # ВРИ — ноль, остальное — умолчания модели (решение владельца
            # 19.10.2026, `applyOtherRegion` страницы).
            if key == "land_rights_cost_mln":
                how, value = "region", 0.0
                text = ("Участок не в Москве и не в Московской области: плату за смену "
                        "разрешённого использования ставим нулём.")
            else:
                how, value = "region", defaults.get(key)
                text = ("Норм этого региона у нас нет, поэтому берём умолчание модели "
                        "DevelopAid. Поправьте его под свой участок.")
        elif row["origin"] in ("glavapu", "egrn") and by_parcel and has_parcel:
            how = "parcel"
            value = None
            if row["origin"] == "egrn":
                text = "Возьмётся из ЕГРН по кадастровому номеру участка."
            elif parcel_region == "other":
                text = ("Посчитается по плотности застройки. Для другого региона это наше "
                        "допущение, поправьте его в модели.")
            elif parcel_region == "mo":
                text = "Посчитается по кадастровому номеру по нормам Московской области."
            elif parcel_region == "unknown":
                text = ("Посчитается по кадастровому номеру, когда станет ясно, Москва это "
                        "или Московская область.")
            else:
                text = "Посчитается по кадастровому номеру участка калькулятором ГлавАПУ."
        elif row["origin"] == "project" and not pending_inputs.get(
                {"offices_gba_sqm": "offices_enabled", "retail_gba_sqm": "retail_enabled"}[key]):
            how, text = "absent", "В тизере не назван, поэтому такого объекта в расчёте нет."
        else:
            how = "default"
            text = _model_origin(path, value, inputs, defaults).rstrip(".") + "."
            if row["origin"] in ("glavapu", "egrn") and has_parcel:
                text += (" По участку число можно получить кнопкой «Получить ТЭП» "
                         "после расчёта.")
        shown = "при расчёте" if how == "parcel" else "нет" if how == "absent" else (
            "не задано" if value is None or value == "" else f"{_fmt(value)} {unit}".strip())
        missing.append({"key": key, "path": path, "label": plain_label(key), "value": value,
                        "unit": unit, "shown": shown, "how": how, "origin": text})
    for row in got["kept"]:
        missing.append({**row, "how": "manual",
                        "shown": f"{_fmt(row['value'])} {row['unit']}".strip(),
                        "origin": "Вписано вручную, класс его не меняет."})
    if "inputs.project_class" not in origins:
        current = str(pending_inputs.get("project_class") or "")
        label = str((presets.get(current) or {}).get("label") or current or "—")
        asked = "project_class" in pending_keys
        missing.append({"key": "project_class", "path": "inputs.project_class",
                        "label": "Класс жилья", "value": current, "unit": "",
                        "shown": label, "how": "ask" if asked else "default",
                        "origin": ("Спрошу ниже." if asked else
                                   _model_origin("inputs.project_class", current, inputs,
                                                 defaults).rstrip(".")
                                   + ". Цены продаж и стоимость строительства — по этому классу.")})

    question = cards[index] if index < len(cards) else None
    return {
        "filename": state.get("filename") or "",
        "pages": state.get("pages"),
        "recognized": bool(state.get("recognized")),
        "found": found,
        "to_engine": to_engine,
        "missing": missing,
        "refused": got["refused"],
        "not_asked": state.get("not_asked") or [],
        "answered_by_document": state.get("answered_by_document") or [],
        "notes": state.get("notes") or [],
        "dropped": state.get("dropped") or [],
        "reason": state.get("reason") or "",
        "region_note": (PARCEL_REGION_NOTES.get(parcel_region, "") if by_parcel and land else ""),
        "cadastral_numbers": land,
        "questions": {"index": index, "total": len(cards), "card": question,
                      "answers": [{"question": a.get("question"),
                                   "answer": a.get("answer") or "",
                                   "action": a.get("action")}
                                  for a in state.get("answers") or []]},
        "ready": question is None,
        "inputs": pending_inputs,
        "tep": pending_tep,
    }


def calc_overrides(card: dict[str, Any]) -> dict[str, Any]:
    """Вводные для расчёта в мини-приложении бота — ровно строки «уйдёт в расчёт».

    Вводные идут своими именами, ТЭП — в `_tep`, происхождение — в
    `_field_origin`: значение тизера после расчёта не должно выглядеть ручным.
    """
    out: dict[str, Any] = {}
    tep: dict[str, dict[str, Any]] = {}
    origin: dict[str, dict[str, str]] = {}
    for row in card.get("to_engine") or []:
        path = str(row["path"])
        parts = path.split(".")
        if parts[0] == "inputs":
            out[parts[1]] = row["value"]
        elif parts[0] == "tep" and len(parts) == 3:
            tep.setdefault(parts[1], {})[parts[2]] = row["value"]
        else:
            continue
        origin[path] = {"source": "document", "text": _quote(row.get("origin"), 160)}
    if tep:
        out["_tep"] = tep
    if origin:
        out["_field_origin"] = origin
    return out
