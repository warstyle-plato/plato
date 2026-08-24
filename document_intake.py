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
     "unit": "список", "target": "land"},
    {"key": "site_area_ha", "label": "Площадь участка", "unit": "га", "target": "land"},
    {"key": "purchase_price_mln", "label": "Цена сделки / цена входа",
     "unit": "млн ₽", "target": "inputs"},
    {"key": "social_compensation_mln", "label": "Денежная соцкомпенсация",
     "unit": "млн ₽", "target": "inputs"},
    {"key": "land_rights_cost_mln", "label": "Плата за смену ВРИ",
     "unit": "млн ₽", "target": "inputs"},
    {"key": "resettlement_cost_mln", "label": "Расселение", "unit": "млн ₽",
     "target": "inputs"},
    {"key": "demolition_area_sqm", "label": "Площадь сносимого", "unit": "м²",
     "target": "inputs"},
    {"key": "apartments_gns_sqm", "label": "СПП / ГНС жилой части", "unit": "м²",
     "target": "tep"},
    {"key": "offices_gba_sqm", "label": "Офисы — общая площадь", "unit": "м²",
     "target": "inputs"},
    {"key": "retail_gba_sqm", "label": "ТЦ / ОСЗ — общая площадь", "unit": "м²",
     "target": "inputs"},
    {"key": "underground_manual_spaces", "label": "Машино-места подземные",
     "unit": "шт.", "target": "inputs"},
    {"key": "kindergarten_places", "label": "ДОО — мест", "unit": "мест",
     "target": "inputs"},
    {"key": "school_places", "label": "СОШ — мест", "unit": "мест", "target": "inputs"},
    {"key": "clinic_capacity", "label": "Поликлиника — мощность",
     "unit": "пос./смену", "target": "inputs"},
)
INTAKE_KEYS = {row["key"] for row in INTAKE_FIELDS}

# Обязательство, у которого в модели два законных места. Своего поля не
# заводим — решение владельца; выбор делает человек, потому что из документа он
# не следует.
OBLIGATION_TARGETS = (
    {"key": "purchase_price_mln",
     "label": "В цену сделки — платится на входе, несёт БРИДЖ"},
    {"key": "social_compensation_mln",
     "label": "В соцнагрузку — идёт своей датой и может попасть в лимит банка"},
)


def intake_prompt(document: dict[str, Any]) -> str:
    """Задание модели: прочитать и процитировать, а не посчитать."""
    catalogue = "\n".join(
        f"- {row['key']} — {row['label']} ({row['unit']})" for row in INTAKE_FIELDS)
    return f"""Ты разбираешь документ по земельному участку: тизер, справку, решение ГЗК
или выписку. Твоя задача — ВЫПИСАТЬ то, что в нём написано, и назвать то, чего
в нём нет. Считать нельзя.

Строгие правила:
1. Каждое значение сопровождай дословной цитатой из документа (поле quote).
   Не нашёл цитаты — не выписывай значение вовсе.
2. Не переводи единицы, не складывай, не делай долей и процентов. Пиши число
   ровно так, как оно стоит в документе, и укажи его единицу в поле unit.
3. Чего в документе нет — не угадывай. Ставь вопрос в questions.
4. Обязательства (инфраструктурный договор, плата за подключение, платёж
   городу) в модели могут лечь в цену сделки ИЛИ в социальную нагрузку. Из
   документа это не следует — задавай вопрос с этими двумя вариантами.

Поля, которые модель понимает:
{catalogue}

Верни ТОЛЬКО JSON такого вида, без пояснений вокруг:
{{"fields": [{{"key": "...", "value": "как в документе", "unit": "...",
   "quote": "дословная строка"}}],
 "questions": [{{"key": "...", "question": "...", "options": ["...", "..."]}}],
 "notes": ["что важно, но в поля модели не ложится"]}}

Документ «{document.get('filename') or 'без имени'}», страниц: {document.get('pages')}.

--- начало документа ---
{document.get('text') or ''}
--- конец документа ---"""


def parse_intake(answer: str) -> dict[str, Any]:
    """Разбор ответа модели. Не разобралось — это отказ, а не пустой результат."""
    text = str(answer or "").strip()
    if not text:
        return {"fields": [], "questions": [], "notes": [],
                "reason": "модель не ответила"}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"fields": [], "questions": [], "notes": [],
                "reason": "в ответе модели нет JSON"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {"fields": [], "questions": [], "notes": [],
                "reason": f"ответ модели не разобрался: {exc}"}
    if not isinstance(data, dict):
        return {"fields": [], "questions": [], "notes": [],
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
    questions = [
        {"key": str(row.get("key") or ""), "question": str(row.get("question") or ""),
         "options": [str(option) for option in (row.get("options") or [])]}
        for row in (data.get("questions") or []) if isinstance(row, dict)
        and str(row.get("question") or "").strip()
    ]
    return {
        "fields": fields,
        "questions": questions,
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
        number = to_number(item.get("value"))
        if number is None:
            refused.append({"key": key, "reason": "значение не читается числом"})
            continue
        if key == "apartments_gns_sqm":
            row = new_tep.setdefault("apartments", {})
            was = row.get("gns")
            row["gns"] = number
            applied.append({"key": key, "was": was, "now": number, "target": "tep"})
            continue
        if key == "site_area_ha":
            was = new_inputs.get("site_area_ha")
            new_inputs["site_area_ha"] = number
            applied.append({"key": key, "was": was, "now": number, "target": "inputs"})
            continue
        was = new_inputs.get(key)
        new_inputs[key] = number
        applied.append({"key": key, "was": was, "now": number, "target": "inputs"})
    return {"inputs": new_inputs, "tep": new_tep,
            "applied": applied, "refused": refused}
