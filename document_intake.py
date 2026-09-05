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
import re
from typing import Any


# Сколько страниц вообще читаем. Тизер — три страницы, справка — две, решение
# ГЗК — четыре. Двадцать пять с запасом; всё, что длиннее, почти наверняка не
# документ по участку, а том проектной документации.
MAX_PAGES = 25
# Порог, ниже которого страница считается картинкой. Скан отдаёт единицы
# символов колонтитула — и «мало текста» надо отличать от «текста нет».
MIN_CHARS_PER_PAGE = 40


def extract_text(data: bytes, filename: str = "") -> dict[str, Any]:
    """Текст документа и честный ответ, если его там нет.

    Скан без текстового слоя — это не пустой документ. Молча вернуть пустую
    строку значит выдать «не смогли прочитать» за «в документе ничего нет».
    """
    name = str(filename or "").strip()
    if not data:
        return {"text": "", "pages": 0, "scanned": False,
                "reason": "пустой файл"}
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        return {"text": "", "pages": 0, "scanned": False,
                "reason": f"не удалось открыть PDF: {exc}"}
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
        "pages_read": read_pages, "scanned": scanned, "reason": "",
    }
    if scanned:
        result["reason"] = (
            "в документе нет текстового слоя — это скан. Распознать его здесь "
            "нечем: читать придётся глазами или прислать страницы картинками")
    if pages > MAX_PAGES:
        result["reason"] = (result["reason"] + "; " if result["reason"] else "") + \
            f"прочитаны первые {MAX_PAGES} страниц из {pages}"
    return result


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
    {"key": "resettlement_cost_mln", "label": "Расселение", "unit": "млн ₽",
     "target": "inputs", "origin": "document"},
    {"key": "demolition_area_sqm", "label": "Площадь сносимого", "unit": "м²",
     "target": "inputs", "origin": "document"},
    {"key": "apartments_gns_sqm", "label": "СПП / ГНС жилой части", "unit": "м²",
     "target": "tep", "origin": "glavapu"},
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

Поля, которые модель понимает:
{catalogue}

Верни ТОЛЬКО JSON такого вида, без пояснений вокруг:
{{"fields": [{{"key": "...", "value": "как в документе", "unit": "...",
   "quote": "дословная строка"}}],
 "questions": [{{"key": "...", "question": "...", "options": ["...", "..."]}}],
 "notes": ["что важно, но в поля модели не ложится"]}}

Документ «{document.get('filename') or 'без имени'}», страниц: {document.get('pages')}.
{"ВНИМАНИЕ: документ прочитан не целиком — %d знаков из %d. О том, чего нет в прочитанной части, вопросов не задавай: скажи, что документ длиннее." % (portion["read_chars"], portion["total_chars"]) if portion["trimmed"] else ""}
--- начало документа ---
{portion["text"]}
--- конец документа ---"""


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
                "reason": f"ответ модели не разобрался: {exc}"}
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
        fields.append({"key": key, "value": item.get("value"),
                       "unit": str(item.get("unit") or ""), "quote": quote})
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
        item = {"key": str(row.get("key") or ""), "question": text,
                "options": [str(option) for option in (row.get("options") or [])]}
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
                 "land_rights_cost_mln", "resettlement_cost_mln"}
_AREA_SQM_FIELDS = {"demolition_area_sqm", "apartments_gns_sqm",
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


def apply_intake(
    extraction: dict[str, Any],
    inputs: dict[str, Any],
    tep: dict[str, dict[str, Any]],
    *,
    accept: list[str] | None = None,
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
            applied.append({"key": key, "value": item.get("value"),
                            "note": "участок применяется отдельным запросом ЕГРН"})
            continue
        number, why = to_field_number(key, item.get("value"), item.get("unit") or "")
        if number is None:
            refused.append({"key": key, "label": INTAKE_LABELS.get(key, key),
                            "value": item.get("value"), "reason": why})
            continue
        as_written = f"{item.get('value')} {item.get('unit') or ''}".strip()
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
    return {"inputs": new_inputs, "tep": new_tep,
            "applied": applied, "refused": refused}
