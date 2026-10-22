"""Разбор присланного документа: тизер, решение ГЗК, справка по участку.

Половина работы аналитика — переписать в модель числа с чужого листа. Тизер
несёт кадастровые номера, площадь и ППМ; справка по участку — СПП, статус АГР и
обязательства; решение ГЗК приходит сканом. Всё это сейчас вбивается руками, и
ошибка переписывания неотличима от расчёта.

Разбор устроен в три хода, и это не украшение:

1. **Что написано в документе.** Ставится как есть, и рядом — цитата строки,
   откуда взято. Значение без цитаты не применяется вовсе: модель, которой
   нечего процитировать, вспоминает, а не читает.
2. **Что из этого следует.** Считает движок и по своим правилам. Модель не
   делает арифметики — ни единиц, ни долей: первое «просто поделить на тысячу»
   становится второй реализацией экономики. Тот же запрет, что у адаптера
   результата `/v2`.
3. **Чего в документе нет.** Спрашивается у человека, а не додумывается.
   Тизер никогда не содержит всего, что нужно модели, и угаданная за человека
   цена входа выглядит на экране ровно так же, как прочитанная.

Отсюда же правило про обязательства (владелец, 24.08.2026): «инфраструктурный
договор 400 млн, не оплачен» — это либо цена сделки, либо социальная нагрузка,
и своего поля под него не заводится. Куда именно — из документа не следует,
поэтому это ВОПРОС, а не догадка: цена сделки платится на входе из БРИДЖа, а
соцкомпенсация идёт по своей дате и может попасть в лимит банка.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

import pdf_ocr


# Сколько страниц вообще читаем. Тизер — три страницы, справка — две, решение
# ГЗК — четыре. Двадцать пять с запасом; всё, что длиннее, почти наверняка не
# документ по участку, а том проектной документации.
MAX_PAGES = 25
# Порог, ниже которого страница считается картинкой. Скан отдаёт единицы
# символов колонтитула — и «мало текста» надо отличать от «текста нет».
MIN_CHARS_PER_PAGE = 40
# Сколько страниц распознаём. Своё число, меньше MAX_PAGES: чтение текстового
# слоя стоит миллисекунды, а распознавание — секунды на страницу, и человек
# ждёт ответа в окне. Восемь закрывают тизер, справку и решение ГЗК целиком;
# что не поместилось — называется вслух, как и обрезка по знакам.
OCR_MAX_PAGES = 8


def extract_text(data: bytes, filename: str = "",
                 recognize: bool = True) -> dict[str, Any]:
    """Текст документа и честный ответ, если его там нет.

    Скан без текстового слоя — это не пустой документ. Молча вернуть пустую
    строку значит выдать «не смогли прочитать» за «в документе ничего нет».
    Поэтому у скана есть второй ход: страницы распознаются (`pdf_ocr`, тот же
    tesseract, которым читаются распоряжения о торгах). Распознанный текст —
    это ТЕКСТ, но не дословный: буквы восстановлены по картинке, и цитата из
    него ручается за смысл, а не за написание. Признак `recognized` едет
    дальше, чтобы это было сказано и модели, и человеку.

    Распознавания нет в образе — остаётся прежний отказ со своей причиной:
    «не смогли» и «нечем» — разные ответы.
    """
    name = str(filename or "").strip()
    if not data:
        return {"text": "", "pages": 0, "scanned": False, "recognized": False,
                "reason": "пустой файл"}
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        # Наружу — класс ошибки, текст и стек разборщика — в журнал: причина
        # названа, а внутренности библиотеки в ответ не уходят.
        logging.warning("document_intake: PDF не открылся", exc_info=True)
        return {"text": "", "pages": 0, "scanned": False, "recognized": False,
                "reason": f"не удалось открыть PDF ({type(exc).__name__}) — "
                          "файл повреждён или это не PDF"}
    pages = len(reader.pages)
    chunks = []
    for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
        try:
            chunks.append(f"[стр. {index}]\n" + (page.extract_text() or ""))
        except Exception:  # noqa: BLE001
            chunks.append(f"[стр. {index}]\n")
    text = "\n\n".join(chunks).strip()
    read_pages = min(pages, MAX_PAGES)
    scanned = read_pages > 0 and len(re.sub(r"\s", "", text)) < MIN_CHARS_PER_PAGE * read_pages
    result = {
        "filename": name, "text": text, "pages": pages,
        "pages_read": read_pages, "scanned": scanned, "recognized": False,
        "reason": "",
    }
    if scanned and recognize:
        result = _recognized(result, data, pages)
    elif scanned:
        result["reason"] = _SCAN_REFUSAL
    if pages > result["pages_read"]:
        result["reason"] = (result["reason"] + "; " if result["reason"] else "") + \
            f"прочитаны первые {result['pages_read']} страниц из {pages}"
    return result


# Отказ прежний и остаётся: распознавания в образе может не быть (бот живёт на
# Render, и наш Dockerfile там не собирается).
_SCAN_REFUSAL = (
    "в документе нет текстового слоя — это скан, а распознать его здесь нечем: "
    "читать придётся глазами или прислать страницы картинками")


def _recognized(result: dict[str, Any], data: bytes, pages: int) -> dict[str, Any]:
    """Второй ход по скану: распознать страницы и сказать, что они распознаны."""
    limit = min(pages, OCR_MAX_PAGES)
    try:
        text = pdf_ocr.text(data, pages=limit)
    except pdf_ocr.Unavailable as exc:
        return {**result, "reason": f"{_SCAN_REFUSAL} ({getattr(exc, 'public_message', '')})"}
    except Exception as exc:  # noqa: BLE001
        # Сорвалось — это «не смогли», а не «в документе пусто».
        logging.warning("document_intake: распознавание сорвалось", exc_info=True)
        return {**result, "reason": f"{_SCAN_REFUSAL}; распознавание сорвалось "
                                    f"({type(exc).__name__})"}
    if len(re.sub(r"\s", "", text)) < MIN_CHARS_PER_PAGE:
        return {**result, "reason": f"{_SCAN_REFUSAL}; распознавание не нашло букв"}
    return {**result, "text": text.strip(), "recognized": True,
            "pages_read": limit,
            "reason": "текст получен распознаванием скана: буквы и цифры "
                      "восстановлены по картинке, цитаты не дословны — числа "
                      "сверьте с документом"}


# Что документ вообще может принести. Ключи — настоящие поля движка; всё, чего
# в этом списке нет, разбор отдаёт вопросом, а не подставляет. Список короткий
# намеренно: тизер приносит участок и ТЭП, а цены, сроки и класс — предпосылки
# аналитика, и брать их из рекламного листа нельзя.
INTAKE_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "cadastral_numbers", "label": "Кадастровые номера участков",
     "unit": "список", "target": "land", "origin": "document"},
    {"key": "site_area_ha", "label": "Площадь участка", "unit": "га",
     "target": "land", "origin": "egrn"},
    {"key": "purchase_price_mln", "label": "Цена сделки / цена входа",
     "unit": "млн ₽", "target": "inputs", "origin": "document"},
    {"key": "social_compensation_mln", "label": "Денежная соцкомпенсация",
     "unit": "млн ₽", "target": "inputs", "origin": "glavapu"},
    {"key": "land_rights_cost_mln", "label": "Плата за смену ВРИ",
     "unit": "млн ₽", "target": "inputs", "origin": "glavapu"},
    # Льгота по плате за смену ВРИ (МПТ и иные основания). Поле в модели было,
    # а в этом перечне — нет: тизер «Светлый 4» называл «Льгота МПТ – 2,57 млрд
    # руб.», и Платону некуда было её положить — он советовал вписать её руками
    # (владелец, 22.10.2026). Сумма из документа — то, что ЗАЯВЛЕНО: без ручной
    # суммы модель считает льготу МПТ по 1874-ПП сама, поэтому строка приходит
    # без галочки (решение владельца) и ложится только по явному выбору.
    {"key": "vri_relief_mln", "label": "Льгота по плате за смену ВРИ (МПТ и иные)",
     "unit": "млн ₽", "target": "inputs", "origin": "document", "unchecked": True,
     "hint": ("заявлено в документе; без этой суммы модель считает льготу МПТ "
              "по 1874-ПП сама — отметьте, если берёте сумму документа")},
    {"key": "resettlement_cost_mln", "label": "Расселение", "unit": "млн ₽",
     "target": "inputs", "origin": "document"},
    {"key": "demolition_area_sqm", "label": "Площадь сносимого", "unit": "м²",
     "target": "inputs", "origin": "document"},
    {"key": "apartments_gns_sqm", "label": "ГНС квартир (без коммерции 1 этажа)",
     "unit": "м²", "target": "tep", "origin": "glavapu"},
    # Жилой дом целиком — квартиры вместе с коммерцией первого этажа. Тизер
    # «Светлый 4» писал «жилой комплекс – 82 840 м2», число легло в квартиры, а
    # коммерция встала сверху: дом вырос до 92 504 м² (владелец, 22.10.2026).
    # Дом делится тем же правилом, что и потенциал участка (`MKD_SPP_SPLIT`).
    {"key": "residential_spp_sqm",
     "label": "СПП жилого дома целиком (квартиры и коммерция 1 этажа)",
     "unit": "м²", "target": "tep", "origin": "glavapu"},
    {"key": "offices_gba_sqm", "label": "Офисы — общая площадь", "unit": "м²",
     "target": "inputs", "origin": "project"},
    {"key": "retail_gba_sqm", "label": "ТЦ / ОСЗ — общая площадь", "unit": "м²",
     "target": "inputs", "origin": "project"},
    {"key": "underground_manual_spaces", "label": "Машино-места подземные",
     "unit": "шт.", "target": "inputs", "origin": "glavapu"},
    {"key": "kindergarten_places", "label": "ДОО — мест", "unit": "мест",
     "target": "inputs", "origin": "glavapu"},
    {"key": "school_places", "label": "СОШ — мест", "unit": "мест",
     "target": "inputs", "origin": "glavapu"},
    {"key": "clinic_capacity", "label": "Поликлиника — мощность",
     "unit": "пос./смену", "target": "inputs", "origin": "glavapu"},
)
INTAKE_KEYS = {row["key"] for row in INTAKE_FIELDS}
INTAKE_LABELS = {row["key"]: row["label"] for row in INTAKE_FIELDS}
INTAKE_UNITS = {row["key"]: row["unit"] for row in INTAKE_FIELDS}

# Почему поля нет в вопросах. Спрашивать о том, что мы считаем сами, — значит
# просить у человека догадку там, где есть источник, и заводить второй ответ на
# один вопрос: его число и число калькулятора разошлись бы, и оба выглядели бы
# верными (владелец, 29.08.2026 — по разбору тизера на Тимирязевской бот задал
# десять вопросов, из которых семь считает город).
NOT_ASKED = {
    "glavapu": ("считает штатный калькулятор ГлавАПУ по кадастровому номеру — "
                "нормативный ТЭП, плату за ВРИ, соцнагрузку и машино-места"),
    "egrn": "берётся из ЕГРН по кадастровому номеру",
    "project": ("решение проекта: в документе не упомянуто, значит принимаем нулём — "
                "поправьте во вкладке «Вводные», если это не так"),
}
ASKABLE_KEYS = {row["key"] for row in INTAKE_FIELDS if row["origin"] == "document"}

# Вопрос без ключа тоже надо узнать: модель нередко ставит `key` пустым, а
# спрашивает ровно о том, что считает город. Слова подобраны узкие — ловить
# «сад» внутри «садовое товарищество» дороже, чем пропустить один вопрос.
QUESTION_MARKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("land_rights_cost_mln", ("смена ври", "смену ври", "платы за ври", "плата за ври",
                              "изменение ври", "вида разрешённого использования")),
    ("social_compensation_mln", ("соцкомпенсац", "размер социальной нагрузк")),
    ("kindergarten_places", ("доо", "детского сада", "детский сад", "детском саду")),
    ("school_places", ("сош", "школ",)),
    ("clinic_capacity", ("поликлиник",)),
    ("underground_manual_spaces", ("машино-мест", "машиномест", "парковочных мест")),
    ("offices_gba_sqm", ("офис",)),
    ("retail_gba_sqm", ("тц ", "тц/", "тц,", "осз", "торгового центра", "торговый центр")),
    ("apartments_gns_sqm", ("спп", "гнс")),
    ("site_area_ha", ("площадь участка",)),
)


def question_origin(item: dict[str, Any]) -> str:
    """Кто отвечает на этот вопрос: документ, город или проект.

    Ключ надёжнее слов, но слова — единственное, что есть у вопроса без ключа.
    """
    text = str(item.get("question") or "").lower()
    said = " ".join([text] + [str(option).lower() for option in (item.get("options") or [])])
    # Куда отнести обязательство — вопрос по построению, и снимать его нельзя.
    # Он ГОВОРИТ про соцнагрузку, потому что она один из двух его ответов:
    # первая версия отбора сняла именно тот вопрос, ради которого написана.
    if "цен" in said and ("нагрузк" in said or "соцкомпенсац" in said):
        return "document"
    key = str(item.get("key") or "").strip()
    row = next((field for field in INTAKE_FIELDS if field["key"] == key), None)
    if row:
        return str(row["origin"])
    for candidate, marks in QUESTION_MARKS:
        if any(mark in text for mark in marks):
            return str(next(field["origin"] for field in INTAKE_FIELDS
                            if field["key"] == candidate))
    # Обязательство, у которого два законных места в модели, ключа не имеет и
    # иметь не может — это и есть настоящий вопрос.
    return "document"



# Обязательство, у которого в модели два законных места. Своего поля не
# заводим — решение владельца; выбор делает человек, потому что из документа он
# не следует.
OBLIGATION_TARGETS = (
    {"key": "purchase_price_mln",
     "label": "В цену сделки — платится на входе, несёт БРИДЖ"},
    {"key": "social_compensation_mln",
     "label": "В соцнагрузку — идёт своей датой и может попасть в лимит банка"},
)


# Сколько знаков документа помещается в задание. Предел вопроса Платону — это
# предел ЧЕЛОВЕЧЕСКОГО вопроса; машинное задание с документом им мерить нельзя:
# одна шапка задания занимает больше двух с половиной тысяч знаков, и на
# документ от четырёх тысяч оставалось 1 484 — меньше одной страницы делового
# PDF. Тизер поэтому отклонялся ВСЕГДА, а человек читал «Вопрос слишком
# длинный», то есть претензию к себе (владелец, 04.09.2026: «Платон на сайте не
# принимает тизеры, пишет что слишком большой запрос»).
DOCUMENT_TEXT_BUDGET = 48_000


def intake_text(document: dict[str, Any], budget: int = DOCUMENT_TEXT_BUDGET) -> dict[str, Any]:
    """Текст документа в пределах бюджета — и сколько его прочитано.

    Обрезка называется вслух: непрочитанный хвост, о котором не сказано,
    читается как «в документе этого нет».
    """
    text = str(document.get("text") or "")
    if len(text) <= budget:
        return {"text": text, "read_chars": len(text), "total_chars": len(text),
                "trimmed": False}
    return {"text": text[:budget], "read_chars": budget, "total_chars": len(text),
            "trimmed": True}


def intake_prompt(document: dict[str, Any], budget: int = DOCUMENT_TEXT_BUDGET) -> str:
    """Задание модели: прочитать и процитировать, а не посчитать."""
    portion = intake_text(document, budget)
    catalogue = "\n".join(
        f"- {row['key']} — {row['label']} ({row['unit']})" for row in INTAKE_FIELDS)
    ours = "\n".join(
        f"- {row['label']}" for row in INTAKE_FIELDS if row["origin"] != "document")
    return f"""Ты разбираешь документ по земельному участку: тизер, справку, решение ГЗК
или выписку. Твоя задача — ВЫПИСАТЬ то, что в нём написано, и назвать то, чего
в нём нет. Считать нельзя.

Строгие правила:
1. Каждое значение сопровождай дословной цитатой из документа (поле quote).
   Не нашёл цитаты — не выписывай значение вовсе.
2. Не переводи единицы, не складывай, не делай долей и процентов. Пиши число
   ровно так, как оно стоит в документе, и укажи его единицу в поле unit.
3. Чего в документе нет — не угадывай. Значение без цитаты не выписывай.
4. Обязательства (инфраструктурный договор, плата за подключение, платёж
   городу, передача метров) в модели могут лечь в цену сделки ИЛИ
   в социальную нагрузку — из документа это не следует. Задавай вопрос
   с этими двумя вариантами.
5. НЕ ЗАДАВАЙ вопросов о том, что мы считаем сами. Вот это мы считаем по
   кадастровому номеру участка и спрашивать об этом нельзя:
{ours}
   Спросить о них значит просить догадку там, где есть источник: ответ
   человека и расчёт города разошлись бы, и оба выглядели бы верными.
   Вопрос уместен только о том, чего не знает ни документ, ни город: цена
   сделки, расселение, снос и то, куда отнести обязательство.
   Вопрос о поле модели несёт его имя в key. У варианта value — число в
   единице unit, если вариант сам его называет (снос всего здания — его
   площадь, «не требуется» — 0), и null, если число впишет человек.
   Сумму обязательства пиши в тексте вопроса так, как в документе, с её
   единицей («2,55 млрд руб.»), и график оплаты рядом («49% оплачено,
   остаток 51% в феврале 2028»): число ответа берётся оттуда.
6. Льгота по плате за смену ВРИ (МПТ и иные основания) — поле vri_relief_mln,
   суммой с единицей, как в документе. Долю покрытия («на 65%») назови в notes.
7. underground_manual_spaces — ТОЛЬКО места подземного паркинга жилья:
   постоянные и гостевые одним числом, как оно стоит в документе. Итог
   «машино-мест», в который входят приобъектные или места остановки
   (кратковременные), сюда не выписывай: они в подземный паркинг не идут.
   В калькуляторе ГлавАПУ это строка 42 «Места хранения и паркирования,
   в т.ч.»; гараж — строки 42.1 и 42.2.
   Назови такой итог и его состав в notes.

Поля, которые модель понимает:
{catalogue}

Верни ТОЛЬКО JSON такого вида, без пояснений вокруг:
{{"fields": [{{"key": "...", "value": "как в документе", "unit": "...",
   "quote": "дословная строка"}}],
 "questions": [{{"key": "поле модели или пусто", "question": "...",
   "options": [{{"label": "подпись варианта", "value": "число или null",
                "unit": "единица числа"}}]}}],
 "notes": ["что важно, но в поля модели не ложится"]}}

Документ «{document.get('filename') or 'без имени'}», страниц: {document.get('pages')}.
{"ВНИМАНИЕ: текст получен РАСПОЗНАВАНИЕМ скана. Буквы и цифры восстановлены по картинке и могут быть прочитаны неверно. Цитируй так, как стоит в тексте. Если цифры числа читаются неуверенно (разорваны, слиплись, соседствуют с мусором), НЕ выписывай значение вовсе — угаданное число выглядит на экране так же, как прочитанное." if document.get("recognized") else ""}
{"ВНИМАНИЕ: документ прочитан не целиком — %d знаков из %d. О том, чего нет в прочитанной части, вопросов не задавай: скажи, что документ длиннее." % (portion["read_chars"], portion["total_chars"]) if portion["trimmed"] else ""}
--- начало документа ---
{portion["text"]}
--- конец документа ---"""


# Документ в разговоре. После разбора человек спрашивает дальше («а какая там
# IRR?», «что с ВРИ?»), и без документа Платон отвечает по пустому месту:
# разбор уходил отдельным путём, а в историю диалога не попадал (владелец:
# «если Платону сгружаешь тизер для разбора, он не ведёт дальше диалог в
# контексте»). Бюджет меньше бюджета разбора: документ едет с КАЖДЫМ вопросом,
# и навсегда раздувать им разговор нельзя.
DOCUMENT_CONTEXT_BUDGET = 12_000


def chat_context(document: dict[str, Any], extraction: dict[str, Any] | None = None,
                 budget: int = DOCUMENT_CONTEXT_BUDGET) -> dict[str, Any]:
    """Документ для продолжения разговора: что выписано и сам текст в пределе.

    Один источник для сайта и бота: оба кладут в разговор одно и то же.
    Пусто — когда в документе нет текста: в разговор нечего класть.
    """
    text = str(document.get("text") or "")
    if not text.strip():
        return {}
    got = extraction or {}
    lines = []
    for item in got.get("fields") or []:
        label = INTAKE_LABELS.get(str(item.get("key") or ""), str(item.get("key") or ""))
        unit = f" {item['unit']}" if item.get("unit") else ""
        lines.append(f"- {label}: {item.get('value')}{unit} — «{str(item.get('quote') or '')[:200]}»")
    for note in got.get("notes") or []:
        lines.append(f"- примечание разбора: {str(note)[:300]}")
    head = ("Выписано разбором:\n" + "\n".join(lines) + "\n\n") if lines else ""
    room = max(budget - len(head), 0)
    excerpt = text[:room]
    filename = str(document.get("filename") or "без имени")
    return {
        "filename": filename,
        "summary": chat_summary(filename, got),
        "pages": document.get("pages"),
        "recognized": bool(document.get("recognized")),
        "text": head + "Текст документа:\n" + excerpt,
        "read_chars": len(excerpt),
        "total_chars": len(text),
        "trimmed": len(excerpt) < len(text),
    }


def context_prompt(context: dict[str, Any] | None,
                   budget: int = DOCUMENT_CONTEXT_BUDGET) -> str:
    """Документ в разговоре — так, как его видит модель. Пусто — документа нет.

    Предел ставится и здесь: контекст приходит со страницы, и раздуть им
    вопрос мимо бюджета нельзя.
    """
    if not isinstance(context, dict):
        return ""
    text = str(context.get("text") or "").strip()
    if not text:
        return ""
    text = text[: budget + 200]
    flags = []
    if context.get("recognized"):
        flags.append("текст получен распознаванием скана — цифры могут быть прочитаны неверно")
    if context.get("trimmed"):
        flags.append(f"в разговоре первые {context.get('read_chars')} знаков из "
                     f"{context.get('total_chars')} — о непрочитанном так и скажи")
    return (f"ДОКУМЕНТ В КОНТЕКСТЕ РАЗГОВОРА: «{context.get('filename') or 'без имени'}»"
            + (f", страниц: {context.get('pages')}" if context.get("pages") else "")
            + ".\nПользователь прислал его на разбор и спрашивает дальше. На вопросы о "
              "документе отвечай по нему с цитатой; чего в нём нет — так и скажи. "
              "Числа документа — это написанное в документе, а не расчёт модели."
            + ("\n" + "; ".join(flags) + "." if flags else "")
            + "\n--- документ ---\n" + text + "\n--- конец документа ---")


def chat_summary(filename: str, extraction: dict[str, Any] | None = None) -> str:
    """Ответ разбора одной репликой для истории диалога."""
    got = extraction or {}
    fields = got.get("fields") or []
    names = [INTAKE_LABELS.get(str(item.get("key") or ""), str(item.get("key") or ""))
             + f": {item.get('value')}" + (f" {item['unit']}" if item.get("unit") else "")
             for item in fields]
    said = ("Выписал: " + "; ".join(names) + ".") if names else "Полей модели в нём не нашлось."
    if got.get("reason"):
        said = f"Разбор не сложился: {got['reason']}."
    return (f"Разобрал документ «{filename or 'без имени'}». {said} "
            "Документ остаётся в разговоре — спрашивайте по нему.")


_WHOLE_HOUSE_MARKS = ("жилой комплекс", "жилого комплекса", "жилой дом", "жилого дома",
                      "жилая часть", "жилой части", "жк ", "жк–", "жк -", "мкд")


def _names_whole_house(quote: str) -> bool:
    text = f" {quote} ".lower().replace("\u00a0", " ")
    return "квартир" not in text and any(mark in text for mark in _WHOLE_HOUSE_MARKS)


def parse_intake(answer: str) -> dict[str, Any]:
    """Разбор ответа модели. Не разобралось — это отказ, а не пустой результат."""
    text = str(answer or "").strip()
    if not text:
        return {"fields": [], "questions": [], "not_asked": [], "notes": [],
                "reason": "модель не ответила"}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"fields": [], "questions": [], "not_asked": [], "notes": [],
                "reason": "в ответе модели нет JSON"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"fields": [], "questions": [], "not_asked": [], "notes": [],
                "reason": (f"ответ модели не разобрался: {exc.msg} "
                           f"(строка {exc.lineno}, столбец {exc.colno})")}
    if not isinstance(data, dict):
        return {"fields": [], "questions": [], "not_asked": [], "notes": [],
                "reason": "ответ модели не объект"}
    fields, dropped = [], []
    for item in data.get("fields") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if key not in INTAKE_KEYS:
            dropped.append(f"{key or '—'}: поля с таким именем в модели нет")
            continue
        if not quote:
            # Значение без цитаты — воспоминание, а не чтение.
            dropped.append(f"{key}: нет цитаты из документа")
            continue
        if key == "apartments_gns_sqm" and _names_whole_house(quote):
            # Цитата называет дом, а не квартиры: в квартиры такое число
            # положило бы коммерцию первого этажа дважды.
            key = "residential_spp_sqm"
        row = next(field for field in INTAKE_FIELDS if field["key"] == key)
        fields.append({"key": key, "label": row["label"], "value": item.get("value"),
                       "unit": str(item.get("unit") or ""), "quote": quote,
                       "checked": not row.get("unchecked"),
                       **({"hint": row["hint"]} if row.get("hint") else {})})
    # Модель иногда возвращает каждый кадастровый номер отдельной строкой с
    # одним и тем же key. Дальше бот выбирает поле кадастров один раз и такой
    # ответ схлопывался до первого участка. Для документа это одна территория:
    # собираем повторяющиеся строки в одно поле, сохраняя порядок и цитаты.
    cadastral_positions = [
        index for index, row in enumerate(fields)
        if row.get("key") == "cadastral_numbers"
    ]
    if len(cadastral_positions) > 1:
        numbers: list[str] = []
        quotes: list[str] = []
        unit = ""
        for index in cadastral_positions:
            row = fields[index]
            unit = unit or str(row.get("unit") or "")
            value = row.get("value")
            values = value if isinstance(value, (list, tuple, set)) else [value]
            for one in values:
                written = str(one or "").strip()
                if not written:
                    continue
                found = re.findall(r"(?<!\\d)\\d{2}:\\d{2}:\\d{6,8}:\\d+(?!\\d)", written)
                candidates = found or [written]
                for candidate in candidates:
                    if candidate not in numbers:
                        numbers.append(candidate)
            quote = str(row.get("quote") or "").strip()
            if quote and quote not in quotes:
                quotes.append(quote)
        first = cadastral_positions[0]
        fields = [row for row in fields if row.get("key") != "cadastral_numbers"]
        fields.insert(first, {
            "key": "cadastral_numbers",
            "value": numbers,
            "unit": unit or "список",
            "quote": " | ".join(quotes),
        })

    # Вопрос задаётся только о том, чего нельзя ни прочитать, ни посчитать.
    # Остальное не выбрасывается молча: молча снятый вопрос читается как
    # «об этом не подумали», а тут наоборот — об этом есть кому ответить.
    questions, not_asked = [], []
    for row in (data.get("questions") or []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("question") or "").strip()
        if not text:
            continue
        # Вариант приходит строкой или объектом с числом. Подписи остаются
        # строками — их читают бот и отбор вопросов; число едет рядом.
        choices = [option if isinstance(option, dict) else {"label": str(option)}
                   for option in (row.get("options") or []) if option is not None]
        item = {"key": str(row.get("key") or ""), "question": text,
                "options": [str(option.get("label") or option.get("value") or "")
                            for option in choices],
                "choices": choices}
        origin = question_origin(item)
        if origin == "document":
            questions.append(item)
        else:
            not_asked.append({**item, "origin": origin, "why": NOT_ASKED[origin]})
    return {
        "fields": fields,
        "questions": questions,
        "not_asked": not_asked,
        "notes": [str(note) for note in (data.get("notes") or [])],
        "dropped": dropped,
        "reason": "",
    }


_NUMBER_RE = re.compile(r"-?\d[\d\s ]*(?:[.,]\d+)?")


def to_number(value: Any) -> float | None:
    """Число из того, как его пишет документ: «11 385,6», «400 млн. руб.»."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _NUMBER_RE.search(str(value or ""))
    if not match:
        return None
    text = match.group(0).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


# Единица — часть числа, и принятое без неё значение это другое число.
# «Стоимость 1 650 000 000 ₽» выписывается моделью как есть — так и велено, —
# а поле модели меряет МИЛЛИОНАМИ рублей: подставленное как было, оно давало
# 1,65 квадриллиона ₽ и выглядело на экране обычным числом. Поэтому единица
# читается и приводится, а неназванная единица у денег и площадей — это отказ,
# а не догадка: у «1650» без слова «млн» два прочтения, различающиеся в
# миллион раз.
_MONEY_SCALE = (("млрд", 1_000.0), ("миллиард", 1_000.0),
                ("млн", 1.0), ("миллион", 1.0),
                ("тыс", 0.001), ("тысяч", 0.001))
_AREA_SCALE = (("га", 10_000.0), ("гект", 10_000.0), ("м2", 1.0), ("м²", 1.0),
               ("кв.м", 1.0), ("кв. м", 1.0), ("кв м", 1.0))
_MONEY_FIELDS = {"purchase_price_mln", "social_compensation_mln",
                 "land_rights_cost_mln", "resettlement_cost_mln", "vri_relief_mln"}
_AREA_SQM_FIELDS = {"demolition_area_sqm", "apartments_gns_sqm", "residential_spp_sqm",
                    "offices_gba_sqm", "retail_gba_sqm"}


def to_field_number(key: str, value: Any, unit: str = "") -> tuple[float | None, str]:
    """Число в единицах поля модели и причина отказа, если привести нечем."""
    number = to_number(value)
    if number is None:
        return None, "значение не читается числом"
    said = f"{value} {unit}".lower().replace("\u00a0", " ")
    if key in _MONEY_FIELDS:
        for mark, scale in _MONEY_SCALE:
            if mark in said:
                return number * scale, ""
        if "руб" in said or "₽" in said:
            # Рубли без порядка — это рубли: миллионы называются словом.
            return number / 1_000_000.0, ""
        return None, ("единица не названа — «млн ₽», «₽» или «тыс ₽»? "
                      "Разница в миллион раз, поэтому не подставляем")
    if key == "site_area_ha":
        if "га" in said or "гект" in said:
            return number, ""
        if "м2" in said or "м²" in said or "кв" in said:
            return number / 10_000.0, ""
        return None, "единица площади не названа — «га» или «м²»?"
    if key in _AREA_SQM_FIELDS:
        for mark, scale in _AREA_SCALE:
            if mark in said:
                return number * scale, ""
        # Метры без подписи — метры. Отказ здесь был бы отказом на ровном
        # месте: площадь участка документы пишут и в гектарах, и в метрах, а
        # СПП, ГНС и площадь сносимого — только в метрах. Требование единицы
        # стоит там, где два прочтения одинаково обычны, а не везде.
        return number, ""
    # Мест, машино-мест, посещений за смену: у счётных величин второй единицы
    # не бывает, и требовать её значило бы отказывать на ровном месте.
    return number, ""


# Подземный паркинг МКД — постоянные и гостевые. Приобъектные и места
# остановки 945-ПП размещает на плоскостных парковках и в УДС (п. 6.1.2.3,
# 6.1.2.4), а выгрузка ГлавАПУ держит их отдельными строками (42.3, 43). Итог,
# который их содержит, положенный в поле гаража, строил бы асфальт под землёй:
# метры × 35, СМР и места в выручке.
# Строка 42 калькулятора ГлавАПУ — «Места хранения и паркирования, в т.ч.» —
# итог ВМЕСТЕ с приобъектными (42.3): у Нагатино 3 286 = 2 902 + 291 + 93.
# Слова «приобъектные» в её цитате нет, поэтому узнаётся она по своей подписи.
OUTSIDE_GARAGE_MARKS = ("приобъект", "кратковрем", "остановк",
                        "хранения и паркирования")
OUTSIDE_GARAGE_REASON = (
    "в цитате названы приобъектные или места остановки — они в подземный паркинг "
    "МКД не входят (945-ПП п. 6.1.2.3–6.1.2.4); в поле гаража идут только "
    "постоянные и гостевые")


def _counts_outside_garage(item: dict[str, Any]) -> bool:
    text = f"{item.get('quote') or ''} {item.get('value') or ''}".lower()
    return any(mark in text for mark in OUTSIDE_GARAGE_MARKS)


# Площадь нежилого объекта и его включатель с продаваемой — те же вводные,
# что пишет страница (`NONRES_TARGET_INPUTS`).
_OBJECT_SWITCH = {"offices_gba_sqm": ("offices_enabled", "offices_saleable_sqm"),
                  "retail_gba_sqm": ("retail_enabled", "retail_saleable_sqm")}


def apply_intake(
    extraction: dict[str, Any],
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    *,
    accept: list[str] | None = None,
    spp_split: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Подставить принятые человеком значения. Ничего не применяется молча.

    `accept` — список ключей, которые человек подтвердил. Пустой список значит
    «ничего»: разбор показывает таблицу, а применение — отдельное действие.
    Найденные числа, изменившиеся значения и отказы возвращаются списком, чтобы
    на экране было видно, что именно поменялось.
    """
    wanted = set(accept or [])
    new_inputs = dict(inputs or {})
    new_tep = {key: dict(value) for key, value in (tep or {}).items()}
    applied, refused = [], []
    for item in extraction.get("fields") or []:
        key = item.get("key")
        if key not in wanted:
            continue
        if key == "cadastral_numbers":
            # Номер ложится в поле участка (вкладка «Проект» → «Участок»), а
            # сведения ЕГРН и ТЭП по нему — отдельным действием: здесь только
            # то, что написано. Прежде окно получало «применяется запросом
            # ЕГРН» и не делало ничего — номер в проект не попадал вовсе.
            applied.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "value": item.get("value"), "target": "land",
                            "note": "записан в поле участка; сведения ЕГРН и ТЭП — "
                                    "кнопкой «Получить ТЭП»"})
            continue
        if key == "underground_manual_spaces" and _counts_outside_garage(item):
            refused.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "value": item.get("value"), "reason": OUTSIDE_GARAGE_REASON})
            continue
        number, why = to_field_number(key, item.get("value"), item.get("unit") or "")
        if number is None:
            refused.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "value": item.get("value"), "reason": why})
            continue
        as_written = f"{item.get('value')} {item.get('unit') or ''}".strip()
        if key == "residential_spp_sqm":
            if not spp_split:
                refused.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                                "value": item.get("value"),
                                "reason": "не задано деление дома на квартиры и коммерцию"})
                continue
            for part in ("apartments", "ground_commercial"):
                row = new_tep.setdefault(part, {})
                was = row.get("gns")
                row["gns"] = round(number * float(spp_split.get(part) or 0.0), 2)
                applied.append({"key": f"{part}_gns_sqm", "path": f"tep.{part}.gns",
                                "label": ("ГНС квартир" if part == "apartments"
                                          else "ГНС коммерции 1 этажа"),
                                "was": was, "now": row["gns"], "target": "tep",
                                "unit": "м²", "as_written": as_written,
                                "read_as": (f"{round(float(spp_split.get(part) or 0) * 100):g}% "
                                            f"от дома {_fmt_mln(number)} м²")})
            continue
        if key == "apartments_gns_sqm":
            row = new_tep.setdefault("apartments", {})
            was = row.get("gns")
            row["gns"] = number
            applied.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "was": was, "now": number, "target": "tep",
                            "unit": INTAKE_UNITS.get(key, ""), "as_written": as_written})
            continue
        if key == "site_area_ha":
            was = new_inputs.get("site_area_ha")
            new_inputs["site_area_ha"] = number
            applied.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "was": was, "now": number, "target": "inputs",
                            "unit": INTAKE_UNITS.get(key, ""), "as_written": as_written})
            continue
        was = new_inputs.get(key)
        new_inputs[key] = number
        applied.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                        "was": was, "now": number, "target": "inputs",
                        "unit": INTAKE_UNITS.get(key, ""), "as_written": as_written})
        if key in _OBJECT_SWITCH and number > 0:
            # Площадь выключенного объекта в расчёт не идёт: офисы «Светлого 4»
            # легли в выключенный объект и из модели пропали (владелец,
            # 22.10.2026). Продаваемая обнуляется — её пересчитают доли
            # объекта, как при «Положить потенциал в объект».
            flag, sale = _OBJECT_SWITCH[key]
            if not new_inputs.get(flag):
                applied.append({"key": flag, "label": f"{INTAKE_LABELS.get(key, key)} — объект",
                                "was": new_inputs.get(flag), "now": True, "target": "inputs",
                                "unit": "", "shown": "включён"})
            new_inputs[flag] = True
            if new_inputs.get(sale):
                applied.append({"key": sale, "label": "Продаваемая площадь объекта",
                                "was": new_inputs.get(sale), "now": 0, "target": "inputs",
                                "unit": "м²", "shown": "пересчитается долями объекта"})
            new_inputs[sale] = 0
        if key == "vri_relief_mln" and number > 0:
            # Сумма льготы действует только в режиме «Фиксированная сумма» —
            # то же правило, что у предложения Платона (`vri_relief_mln`).
            was_mode = new_inputs.get("vri_relief_mode")
            new_inputs["vri_relief_mode"] = "amount"
            applied.append({"key": "vri_relief_mode", "label": "Льгота по плате — режим",
                            "was": was_mode, "now": "amount", "target": "inputs",
                            "unit": "", "shown": "фиксированная сумма"})
    return {"inputs": new_inputs, "tep": new_tep,
            "applied": applied, "refused": refused}


# ---------------------------------------------------------------------------
# Вопросы по документу — по одному, и ответ ложится в поле модели.
#
# Разбор отдавал вопросы списком, и окно печатало их подряд, каждый со своими
# вариантами, а ответить было некуда: варианты были подписями, не кнопками, и
# ни один ответ до полей модели не доходил (владелец, 18.10.2026: «задаёт все
# вопросы подряд, вместо того чтобы дожидаться ответа пошагово… реальной
# передачи данных в движок не происходит»). Карточка вопроса несёт для каждого
# варианта поле модели и число в его единицах — или причину, почему числа нет.

# Число в конце варианта после тире: «Снос всего здания — 2863,7 м²»,
# «Расселение не требуется — 0». Только хвост после тире: число внутри подписи
# («ООО «Народного 29 (СЗ)»») — часть имени, а не ответ.
_OPTION_TAIL_RE = re.compile(
    r"[—–-]\s*(-?\d[\d\s ]*(?:[.,]\d+)?)\s*([^\d—–-]{0,16})$")


def obligation_target(label: str) -> str:
    """Куда вариант относит обязательство — по своим словам, иначе никуда."""
    said = str(label or "").lower()
    if "нагрузк" in said or "соцкомпенс" in said:
        return "social_compensation_mln"
    if "цен" in said and ("сделк" in said or "вход" in said):
        return "purchase_price_mln"
    return ""


def _option_number(target: str, value: Any, unit: str) -> tuple[float | None, str]:
    if value is None or str(value).strip() == "":
        return None, "в варианте нет числа — впишите значение"
    if to_number(value) == 0:
        # Ноль — ноль в любой единице; отказывать ему за неназванную единицу
        # значило бы не принять «расселение не требуется».
        return 0.0, ""
    return to_field_number(target, value, unit)


# Сумма, названная в самом вопросе: «Платёж 2,55 млрд руб. за SPV…». Вариант
# «В цену сделки» числа не несёт, и человек вписывал его сам — в поле с
# подписью «млн ₽», глядя на «2,55 млрд»: в модель легло 2,55 млн ₽ вместо
# 2 550 (владелец, 22.10.2026, «Светлый 4»). Число вопроса — ответ документа:
# вариант берёт его сам, а вписанное число, совпавшее с ним, читается в его
# единице.
_AMOUNT_RE = re.compile(
    r"(?<![\d.,])(\d[\d\s\u00a0]*(?:[.,]\d+)?)\s*"
    r"(млрд|миллиард\w*|млн|миллион\w*|тыс\.?|тысяч\w*)\s*(?:руб\w*\.?|₽)?",
    re.I)


def question_amounts(text: str) -> list[dict[str, Any]]:
    """Денежные суммы вопроса в миллионах рублей, с тем, как они написаны."""
    out = []
    for match in _AMOUNT_RE.finditer(str(text or "")):
        written = match.group(0).strip()
        number, _why = to_field_number("purchase_price_mln", match.group(1), match.group(2))
        if number is not None:
            out.append({"mln": number, "number": to_number(match.group(1)),
                        "written": written})
    return out


_MONTHS = (("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5),
           ("мае", 5), ("май", 5), ("июн", 6), ("июл", 7), ("август", 8),
           ("сентябр", 9), ("октябр", 10), ("ноябр", 11), ("декабр", 12))
_MONTH_YEAR_RE = re.compile(r"([а-яё]+)\s+(20\d\d)", re.I)
_SHARE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PAID_MARKS = ("оплачен", "уплачен", "внесен", "внесён", "выплачен", "перечислен")


def _month_of(text: str) -> tuple[int, int] | None:
    for match in _MONTH_YEAR_RE.finditer(text.lower()):
        for stem, month in _MONTHS:
            if match.group(1).startswith(stem):
                return int(match.group(2)), month
    return None


def payment_schedule(text: str, project_start: Any) -> tuple[list[tuple[float, int]], str]:
    """Доли платежа и месяцы от начала проекта из слов документа.

    «49% оплачено, остаток 51% в феврале 2028» → [(49, 0), (51, 13)] при
    начале проекта в январе 2027. Уже оплаченное — месяц 0: деньги ушли до
    начала расчёта. Чего нельзя прочитать — причина, а не догадка.
    """
    said = str(text or "")
    shares = list(_SHARE_RE.finditer(said))
    if not shares:
        return [], ""
    try:
        start = date.fromisoformat(str(project_start or "")[:10])
    except ValueError:
        return [], "начало проекта не задано — месяцы графика не от чего отсчитать"
    out = []
    for i, match in enumerate(shares):
        before = said[(shares[i - 1].end() if i else 0):match.start()].lower()
        after = said[match.end():(shares[i + 1].start() if i + 1 < len(shares) else len(said))]
        when = _month_of(after)
        if when is not None:
            month = max(0, (when[0] - start.year) * 12 + when[1] - start.month)
        elif any(mark in after.lower() or mark in before for mark in _PAID_MARKS):
            month = 0
        elif _month_of(before) is not None:
            year, mon = _month_of(before)
            month = max(0, (year - start.year) * 12 + mon - start.month)
        else:
            return [], f"у доли {match.group(0)} не названа дата платежа"
        out.append((float(match.group(1).replace(",", ".")), month))
    total = sum(share for share, _ in out)
    if abs(total - 100.0) > 0.5:
        return [], f"доли платежа дают {total:g}%, а не 100%"
    return out, ""


def _fmt_mln(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")


def question_card(item: dict[str, Any]) -> dict[str, Any]:
    """Вопрос с вариантами, у каждого варианта — поле модели и число.

    Поле берётся из ключа вопроса, а у вопроса без ключа (куда отнести
    обязательство) — из слов варианта. Поля нет — ответ записывается в
    разговор и честно называется неприменённым.
    """
    key = str(item.get("key") or "").strip()
    field = key if key in ASKABLE_KEYS and key != "cadastral_numbers" else ""
    amounts = question_amounts(str(item.get("question") or ""))
    options = []
    for raw in item.get("choices") or item.get("options") or []:
        if isinstance(raw, dict) and "value" in raw:
            label = str(raw.get("label") or raw.get("value") or "").strip()
            value, unit = raw.get("value"), str(raw.get("unit") or "")
        else:
            label = str((raw.get("label") if isinstance(raw, dict) else raw) or "").strip()
            tail = _OPTION_TAIL_RE.search(label)
            value, unit = (tail.group(1), tail.group(2).strip()) if tail else (None, "")
        if not label:
            continue
        target = field or obligation_target(label)
        number, why = (_option_number(target, value, unit) if target
                       else (None, "у ответа нет поля в модели — записан в разговор"))
        from_question = ""
        if not field and target and number is None and len(amounts) == 1:
            # Обязательство без своего числа — сумма вопроса, в единицах поля.
            number, why, from_question = amounts[0]["mln"], "", amounts[0]["written"]
        options.append({"label": label, "target": target, "value": number,
                        "unit": INTAKE_UNITS.get(target, ""), "why": why,
                        **({"from_question": from_question} if from_question else {})})
    return {"question": str(item.get("question") or ""), "key": field,
            "label": INTAKE_LABELS.get(field, ""), "unit": INTAKE_UNITS.get(field, ""),
            # Обязательство складывается с тем, что уже стоит в поле: три
            # обязательства «в соцнагрузку» — три слагаемых, а не три замены.
            "adds": not field,
            "options": options}


def _typed_number(card: dict[str, Any], target: str, said: str) -> tuple[float | None, str, str]:
    """Вписанное человеком число в единицах поля: (число, причина отказа, как прочтено).

    Число без единицы — в единице поля («млн ₽» стоит в подсказке), кроме
    одного случая: оно совпало с суммой из текста вопроса. «2,55» под
    вопросом «Платёж 2,55 млрд руб.» — это 2,55 млрд, а не 2,55 млн.
    """
    unit = INTAKE_UNITS.get(target, "")
    bare = not re.search(r"[a-zа-яё₽]", said.lower())
    if bare and target in _MONEY_FIELDS:
        typed = to_number(said)
        for amount in question_amounts(str(card.get("question") or "")):
            if typed is not None and amount["number"] == typed and amount["mln"] != typed:
                return (amount["mln"], "",
                        f"вписано «{said}» — в вопросе «{amount['written']}», "
                        f"значит {_fmt_mln(amount['mln'])} {unit}")
    number, why = to_field_number(target, said, unit)
    return number, why, ""


def _part_label(question: str) -> str:
    text = re.split(r"\s[—–-]\s|\?", str(question or ""), maxsplit=1)[0].strip()
    return text if len(text) <= 90 else text[:87].rstrip() + "…"


def _schedule_text(payments: list[tuple[float, int]]) -> str:
    merged: dict[int, float] = {}
    for amount, month in payments:
        merged[month] = merged.get(month, 0.0) + amount
    return "; ".join(f"{round(amount, 3):g}@{month}" for month, amount in sorted(merged.items())
                     if amount > 0)


def answer_card(card: dict[str, Any], inputs: dict[str, Any],
                tep: dict[str, dict[str, Any]], *, choice: int = -1,
                typed: str = "", ledger: dict[str, Any] | None = None,
                mode: str = "") -> dict[str, Any]:
    """Применить ответ на один вопрос — тем же писателем, что и таблица разбора.

    `choice` — номер варианта, `typed` — значение, вписанное человеком в
    единицах поля. Ничего не применилось — причина называется, а ответ всё
    равно записывается: человек его дал.

    Обязательство (`card["adds"]`) складывается с прежними ответами того же
    документа: `ledger` — их книга, она живёт в очереди на диске. Три ответа
    «в соцнагрузку» писали одно поле по очереди, и в модели оставался
    последний — 100 вместо 765 (владелец, 22.10.2026). Если в поле уже стоит
    своё число, сперва спрашиваем: прибавить к нему или заменить (`mode`).
    """
    options = card.get("options") or []
    option = options[choice] if 0 <= choice < len(options) else None
    target = (option or {}).get("target") or card.get("key") or ""
    said = str(typed or "").strip()
    answer = " — ".join(part for part in (
        (option or {}).get("label") or "", said) if part)
    read_as = ""
    if said and target:
        number, why, read_as = _typed_number(card, target, said)
    elif option is not None:
        number, why = option.get("value"), option.get("why") or ""
        if option.get("from_question") and number is not None:
            read_as = f"сумма из вопроса: «{option['from_question']}»"
    else:
        number, why = None, "ответа нет"
    new_inputs = dict(inputs or {})
    if not target or number is None:
        return {"answer": answer, "inputs": new_inputs,
                "tep": {k: dict(v) for k, v in (tep or {}).items()}, "applied": [],
                "refused": [{"key": target, "label": INTAKE_LABELS.get(target, target)
                             or "ответ", "value": answer,
                             "reason": why or "у ответа нет поля в модели"}]}
    entry: dict[str, Any] | None = None
    write = number
    if card.get("adds") and ledger is not None:
        entry = ledger.get(target)
        if entry is None:
            current = to_number(new_inputs.get(target)) or 0.0
            if current and mode not in ("add", "replace"):
                origin = ((new_inputs.get("_field_origin") or {})
                          .get(f"inputs.{target}") or {})
                return {"answer": answer, "inputs": new_inputs,
                        "tep": {k: dict(v) for k, v in (tep or {}).items()},
                        "applied": [], "refused": [],
                        "confirm": {"key": target, "label": INTAKE_LABELS.get(target, target),
                                    "unit": INTAKE_UNITS.get(target, ""),
                                    "current": current, "adding": number,
                                    "origin": str(origin.get("text") or "")}}
            entry = {"base": current if mode == "add" else 0.0, "parts": [],
                     "base_origin": str(((new_inputs.get("_field_origin") or {})
                                         .get(f"inputs.{target}") or {}).get("text") or ""),
                     "schedule_was": str(new_inputs.get("purchase_schedule") or "")}
        entry = {**entry, "parts": list(entry.get("parts") or []) + [
            {"label": _part_label(card.get("question")), "value": number}]}
        write = float(entry["base"]) + sum(float(part["value"]) for part in entry["parts"])
    got = apply_intake(
        {"fields": [{"key": target, "value": write,
                     "unit": INTAKE_UNITS.get(target, ""), "quote": card.get("question")}]},
        new_inputs, tep, accept=[target])
    # «В документе: …» здесь неправда — это ответ человека, и окно печатает
    # его само строкой «Ответ: …».
    for row in got["applied"]:
        row.pop("as_written", None)
        if row["key"] != target:
            continue
        if read_as:
            row["read_as"] = read_as
        if entry is not None:
            row["parts"] = entry["parts"]
            row["base"] = entry["base"]
            row["base_origin"] = entry.get("base_origin") or ""
    if entry is not None and target == "purchase_price_mln":
        _apply_purchase_schedule(card, number, entry, got)
    if entry is not None:
        ledger[target] = entry
    return {"answer": answer, **got}


def _apply_purchase_schedule(card: dict[str, Any], number: float,
                             entry: dict[str, Any], got: dict[str, Any]) -> None:
    """График платежа покупки из слов вопроса — в `purchase_schedule`, суммами.

    Суммы, а не доли: цена сделки складывается из нескольких ответов и
    прежнего значения, и доли одного платежа не доли всей цены.
    """
    shares, why = payment_schedule(card.get("question") or "", got["inputs"].get("project_start"))
    payments = list(entry.get("payments") or [])
    if shares:
        payments += [(number * share / 100.0, month) for share, month in shares]
    else:
        payments.append((number, 0))
    entry["payments"] = payments
    if why:
        got["refused"].append({"key": "purchase_schedule", "label": "График платежей за покупку",
                               "value": card.get("question"), "reason": why})
    if not any(month for _amount, month in payments):
        return
    if entry["base"] and entry.get("schedule_was"):
        got["refused"].append({
            "key": "purchase_schedule", "label": "График платежей за покупку",
            "value": card.get("question"),
            "reason": ("в проекте уже задан свой график покупки — платёж документа в него "
                       "не вписан; поправьте график во вкладке «Вводные»")})
        return
    text = _schedule_text([(float(entry["base"]), 0)] + payments)
    was = got["inputs"].get("purchase_schedule")
    got["inputs"]["purchase_schedule"] = text
    got["applied"].append({"key": "purchase_schedule", "label": "График платежей за покупку",
                           "was": was, "now": text, "target": "inputs", "unit": "",
                           "shown": "; ".join(
                               f"{_fmt_mln(amount)} млн ₽ — "
                               + ("в начале проекта" if month == 0 else f"через {month} мес.")
                               for amount, month in sorted(
                                   ((a, m) for m, a in _merge(payments, entry["base"]).items()),
                                   key=lambda pair: pair[1]))})


def _merge(payments: list[tuple[float, int]], base: float) -> dict[int, float]:
    merged: dict[int, float] = {0: float(base)} if base else {}
    for amount, month in payments:
        merged[month] = merged.get(month, 0.0) + amount
    return merged
