"""Печатная форма выписки ЕГРН → та же запись, что даёт XML. Второй записи нет.

Росэлторг публикует выписки лотовой документации ПЕЧАТНОЙ формой, а не машинным
КУВИ: измерено 13.09.2026 на пяти живых КРТ-лотах — 32 PDF и ни одного XML, а в
архиве лота 33444 четырнадцать файлов «ЕГРН 1021.pdf … ЕГРН 2054.pdf». Пока
читателя у формы не было, архив открывался, записей выходило ноль, и на экране
это неотличимо от «в документе владельцев нет».

Запись здесь та же, что у `egrn_extracts.read`, и это главное правило модуля:
поверхности (свод лота, блок площадки, книга) читают ОДНУ форму записи, иначе
один и тот же объект показывается по-разному в зависимости от того, какой архив
приехал, и обе картинки выглядят верными.

Четыре правила, выведенные на живых формах.

**Имя правообладателя эта форма не раскрывает, и это не наш пробел.** У 13 из
14 выписок раздел прав объявлен отсутствующим («Сведения, необходимые для
заполнения разделов: 2 — Сведения о зарегистрированных правах … отсутствуют»),
у четырнадцатой раздел есть, вид права стоит — «Собственность
77-77/005-77/009/277/2016-603/2 от 23.12.2016», — а клетка «Правообладатель»
ПУСТА: проверено отрисовкой страницы, там нет ни текста, ни картинки. Выписка
«об объекте недвижимости» ФИО и наименование не раскрывает по своему виду.
Поэтому «право не зарегистрировано» и «право есть, а имени форма не даёт» —
РАЗНЫЕ ответы, и запись несёт оба (`rights_section`, `holder_withheld`):
свёрнутые в один пустой список, они выдают вид документа за молчание реестра.

**Значение читают по подписи, а не по номеру строки.** Форма печатается
таблицей, и в текстовом слое подпись стоит строкой, а значение — следующей;
подпись при этом переносится по словам («Кадастровые номера иных объектов
недвижимости, в пределах\\nкоторых расположен объект недвижимости:»). Поэтому
подписи объявлены образцами со свободным пробелом, а значение берётся до
следующей подписи или до служебной строки листа.

**«Данные отсутствуют» — ответ реестра, а не пустая клетка.** Строка стоит у
половины полей, и принять её за значение значит написать это словами в отчёте.

**Вид объекта форма называет сама** («Здание», «Земельный участок») — угадывать
его по набору заполненных полей нельзя: у здания и участка общие подписи
площади и адреса, а различаются те, которых в этой форме может не быть вовсе.

Что НЕ измерено и потому названо вслух: живой печатной формы по ЗЕМЕЛЬНОМУ
участку в руках не было. Подписи участка взяты из того же шаблона выписки;
разойдись они — соответствующие поля придут пустыми, а номер, адрес, площадь,
стоимость и права прочитаются как у здания. Пустое поле — это «не прочитали», и
оно называется; подставить в него чужое значение неоткуда.

Запуск проверок: python3 -m pytest tests/test_the_print_form_is_read.py -q
"""

from __future__ import annotations

import re
from typing import Any

import pdf_ocr

# Сколько знаков текстового слоя считаем ответом. Пустой слой у скана даёт ноль,
# но лист с одной служебной шапкой даёт сотни — а полей в нём нет. Порог взят по
# живым формам: самая короткая (7 страниц) несёт 6 332 знака.
MIN_TEXT_LAYER_CHARS = 1200
# Сколько страниц распознаём у скана. Раздел 1 и раздел 2 стоят в начале — у
# семистраничной формы права лежат на третьем листе, — а распознавание стоит до
# минуты на страницу: у формы в 426 листов распознать всё нельзя, и предел здесь
# назван числом, а не подразумевается.
OCR_PAGES = 6

class NoTextLayer(ValueError):
    """Скан без текстового слоя. Это не пустой документ и не чужой формат.

    Названо своим родом затем, чтобы вызывающий мог отличить «распознавание не
    по бюджету» от «файл негодный»: у первого лечение есть — распознать, — а
    у второго нет, и одним сообщением они неразличимы.
    """


_CAD = re.compile(r"\d+:\d+:\d+:\d+")
_ABSENT = re.compile(r"^\s*(данные отсутствуют|не зарегистрировано|отсутствуют?)\s*$", re.I)
# Служебные строки листа: шапка, подвал, отметка об электронной подписи. Они
# стоят между подписью и значением на разрыве страницы, и без них значение
# собирает в себя чужой лист.
_SERVICE = re.compile(
    r"^\s*(?:"
    r"Лист\s*№?\s*\d*|Лист\s+\d+|Всего\s+(?:листов|разделов)\b.*|Раздел\s+\d+.*"
    r"|полное наименование.*|инициалы, фамилия|подпись|М\.П\.|вид объекта недвижимости"
    r"|ДОКУМЕНТ\s+ПОДПИСАН|ЭЛЕКТРОННОЙ\s+ПОДПИСЬЮ|Сертификат:.*|Владелец:.*"
    r"|Действителен:.*|Выписка из Единого государственного реестра.*"
    r"|Сведения о характеристиках объекта.*|Сведения о зарегистрированных правах"
    r"|На\s+основании запроса.*|\d{2}\.\d{2}\.\d{4}\s*г\.\s*№.*"
    r"|Здание|Сооружение|Земельный участок|Помещение|Машино-место"
    r")\s*$")
# Нумерация пунктов: «1.1» стоит между подписью и значением, «1», «2», «3» —
# перед подписью. Выбрасывать её ПО ВСЕМУ листу нельзя: образец номера совпадает
# с обычным дробным числом, и «942.4» в площади, «30292232.3» в кадастровой
# стоимости — это те самые значения, ради которых читатель и написан (девять
# площадей из четырнадцати и ВСЕ стоимости так и пропали в первом заходе).
# Нумерация живёт только в разделе прав, и снимается она у тех подписей, чьё
# значение числом не бывает.
_NUMBERING = re.compile(r"^\s*\d+(?:\.\d+)*\s*$")
# Подписи, у которых значение не бывает числом: у них одинокий номер пункта —
# нумерация, а не ответ.
_NUMBERED_FIELDS = {"right_text", "holder_text"}

# Вид объекта форма называет сама — строкой перед «вид объекта недвижимости».
_KINDS = {
    "здание": "build", "сооружение": "build", "помещение": "build",
    "машино-место": "build", "объект незавершённого строительства": "build",
    "объект незавершенного строительства": "build",
    "земельный участок": "land",
}


def _label(words: str) -> re.Pattern[str]:
    """Образец подписи: пробел свободный, потому что подпись переносится."""
    return re.compile(
        r"^\s*" + r"\s+".join(re.escape(w) for w in words.split()) + r"\s*:?\s*$",
        re.I)


# Подписи полей. Ключ записи — тот же, что у XML-разбора: поверхности читают
# одну форму записи, а не две.
_FIELDS: list[tuple[str, str]] = [
    ("cadastral_number", "Кадастровый номер"),
    ("quarter", "Номер кадастрового квартала"),
    ("address", "Адрес"),
    ("area_text", "Площадь, м²"),
    ("purpose", "Назначение"),
    ("name", "Наименование"),
    ("floors_text", "Количество этажей, в том числе подземных этажей"),
    ("year_built", "Год ввода в эксплуатацию по завершении строительства"),
    ("value_text", "Кадастровая стоимость, руб."),
    ("lands_text",
     "Кадастровые номера иных объектов недвижимости, в пределах которых "
     "расположен объект недвижимости"),
    ("rooms_text",
     "Кадастровые номера помещений, машино-мест, расположенных в здании или "
     "сооружении"),
    ("status", "Статус записи об объекте недвижимости"),
    ("special_notes", "Особые отметки"),
    ("right_text", "Вид, номер, дата и время государственной регистрации права"),
    ("holder_text", "Правообладатель (правообладатели)"),
    # Участок. Подписи взяты из того же шаблона и на живой форме не сверены:
    # разойдись они — поле придёт пустым, а не чужим значением.
    ("category", "Категория земель"),
    ("permitted_use", "Виды разрешенного использования"),
    ("objects_text",
     "Кадастровые номера расположенных в пределах земельного участка объектов "
     "недвижимости"),
]
# Имена групп регулярного выражения — латиница, а ключи записи бывают с
# подчёркиванием: соответствие держится картой, а не совпадением написания.
_GROUP_FIELD = {f"f{index}": key for index, (key, _) in enumerate(_FIELDS)}
_ALL_LABELS = re.compile(
    "|".join(f"(?P<f{index}>(?:^|\n)\\s*" + r"\s+".join(re.escape(w) for w in words.split())
             + r"\s*:)"
             for index, (key, words) in enumerate(_FIELDS)),
    re.I)


def _values(lines: list[str]) -> dict[str, list[str]]:
    """Подпись → её значения.

    Подпись переносится по словам, поэтому искать её строкой нельзя: у
    «Кадастровые номера иных объектов недвижимости, в пределах\nкоторых
    расположен объект недвижимости:» первая строка не подпись и вторая не
    подпись. Служебные строки листа выбрасываются ДО поиска — на разрыве
    страницы они стоят между подписью и значением, — а значение кончается
    следующей подписью: нашей из списка или чужой, опознанной двоеточием.
    """
    clean = [line.strip() for line in lines
             if line.strip() and not _SERVICE.match(line)]
    text = "\n".join(clean)
    found: dict[str, list[str]] = {}
    hits = [(match.start(), match.end(), match.lastgroup)
            for match in _ALL_LABELS.finditer(text)]
    for index, (start, end, key) in enumerate(hits):
        stop = hits[index + 1][0] if index + 1 < len(hits) else len(text)
        field = _GROUP_FIELD[key]
        value_lines: list[str] = []
        for line in text[end:stop].splitlines():
            line = line.strip()
            if not line:
                continue
            if line.endswith(":"):
                break  # чужая подпись: значение кончилось
            if field in _NUMBERED_FIELDS and _NUMBERING.match(line):
                continue
            value_lines.append(line)
        found.setdefault(field, []).append(" ".join(value_lines).strip())
    return found


def _first(found: dict[str, list[str]], key: str) -> str:
    """Первое непустое значение подписи. «Данные отсутствуют» — не значение."""
    for value in found.get(key) or []:
        if value and not _ABSENT.match(value):
            return value
    return ""


def _float(text: str) -> float | None:
    clean = re.sub(r"[^\d,.\-]", "", (text or "").replace("\xa0", "")).replace(",", ".")
    clean = re.sub(r"\.(?=.*\.)", "", clean)
    try:
        return float(clean)
    except ValueError:
        return None


def _numbers(text: str) -> list[str]:
    return list(dict.fromkeys(_CAD.findall(text or "")))


def _kind(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if line.strip().casefold() == "вид объекта недвижимости" and index:
            kind = _KINDS.get(lines[index - 1].strip().casefold())
            if kind:
                return kind
    return ""


def _rights(found: dict[str, list[str]], section_present: bool) -> list[dict[str, Any]]:
    """Права из раздела 2. Пустая клетка держателя — свойство вида выписки."""
    out: list[dict[str, Any]] = []
    for raw in found.get("right_text") or []:
        if not raw or _ABSENT.match(raw):
            continue
        date = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", raw)
        number = re.search(r"\b(\d[\d\-/]{6,})\b", raw)
        kind = raw.split(number.group(1))[0].strip() if number else raw.strip()
        out.append({
            "type": kind.strip(" ,;"),
            "number": number.group(1) if number else "",
            "date": date.group(1) if date else "",
            "share": "",
            "holders": [],
            # Имя не раскрыто ВИДОМ выписки, а не отсутствием права.
            "holder_withheld": True,
        })
    if not out and section_present:
        return []
    return out


def read(data: bytes, *, ocr: bool = True) -> dict[str, Any]:
    """Печатная форма → запись. Текстовый слой, а скана нет — распознавание."""
    import pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    source = "layer"
    if len(text.strip()) < MIN_TEXT_LAYER_CHARS:
        # Скан без текстового слоя — не пустой документ. Распознавания нет —
        # это отказ с причиной, а не запись без полей.
        if not ocr:
            raise NoTextLayer(
                "в PDF нет текстового слоя, а распознавание не по бюджету "
                f"архива (не больше {OCR_PAGES} страниц на документ)")
        try:
            text = pdf_ocr.text(data, pages=OCR_PAGES)
        except pdf_ocr.Unavailable as exc:
            raise NoTextLayer(str(exc)) from exc
        source = "ocr"
    return read_text(text, text_source=source)


def read_text(text: str, *, text_source: str = "layer") -> dict[str, Any]:
    """Текст печатной формы → запись. Чужой документ — отказ, а не пустая запись.

    Отдельно от `read` затем, чтобы проверки шли на ТЕКСТЕ живого документа, а
    не на нарисованном нами PDF: своя подделка проверяла бы наши же подписи.
    """
    if "Выписка из Единого государственного реестра недвижимости" not in text:
        raise ValueError("не печатная форма выписки ЕГРН")

    lines = text.splitlines()
    kind = _kind(lines)
    if not kind:
        raise ValueError("форма не называет вид объекта недвижимости")
    found = _values(lines)
    number = _first(found, "cadastral_number")
    if not _CAD.fullmatch(number):
        raise ValueError("в форме не прочитан кадастровый номер объекта")

    notes = _first(found, "special_notes")
    # Раздел прав объявлен отсутствующим В САМОЙ форме — это ответ реестра.
    section_absent = bool(
        re.search(r"2\s*[-–—]\s*Сведения о зарегистрированных правах", notes)
        or re.search(r"2\s*[-–—]\s*Сведения о зарегистрированных правах", text))
    extract = re.search(r"№\s*(КУВИ-[\d/\-]+)", text)
    formed = re.search(r"(\d{2}\.\d{2}\.\d{4})\s*г\.\s*№\s*КУВИ", text)

    record: dict[str, Any] = {
        "kind": kind,
        "cadastral_number": number,
        "quarter": _first(found, "quarter"),
        "address": _first(found, "address"),
        "cadastral_value_rub": _float(_first(found, "value_text")),
        "status": _first(found, "status"),
        "special_notes": notes,
        "formed_at": formed.group(1) if formed else "",
        "extract_number": extract.group(1) if extract else "",
        "area_sqm": _float(_first(found, "area_text")),
        # Происхождение записи и то, чем она прочитана: печатная форма отвечает
        # не на все вопросы машинной, и читатель обязан это знать.
        "source": "print_form",
        "text_source": text_source,
        "rights_section": "absent" if section_absent else "present",
        "restrictions": [],
    }
    record["rights"] = _rights(found, not section_absent)
    if kind == "land":
        record.update({
            "area_kind": "",
            "category": _first(found, "category"),
            "permitted_use": _first(found, "permitted_use"),
            "objects": _numbers(_first(found, "objects_text")),
        })
    else:
        floors = _first(found, "floors_text")
        above = re.match(r"\s*(\d+)", floors)
        under = re.search(r"подземных\s+(\d+)", floors)
        record.update({
            "name": _first(found, "name"),
            "purpose": _first(found, "purpose"),
            "floors": above.group(1) if above else "",
            "underground_floors": under.group(1) if under else "",
            "year_built": _first(found, "year_built"),
            "lands": _numbers(_first(found, "lands_text")),
            "rooms": _numbers(_first(found, "rooms_text")),
        })
    return record
