"""Один ввод: лист «Вводные», куда печатают, и «Параметры модели», который считает.

Книга v4 собирается патчем XML шаблона — 73 104 формулы методики владельца, и
пересобрать их кодом значит завести вторую реализацию экономики. Поэтому лист
шаблона остаётся на месте со всеми своими ссылками, только переименовывается, а
рядом появляется лист ввода: каждая ячейка, в которую человек печатал, уезжает
туда, а на прежнем месте остаётся читалка `='Вводные'!X`.

Почему именно так, а не «добавим второй лист»: два места ввода — это два
достоверных на вид ответа про одно число (владелец, 04.09.2026: «получается у
нас будет по сути два ввода чтоль?»). Значит ввод обязан остаться один, а лист,
в который вписать нельзя, не имеет права называться «Вводные».

Что считается вводом, решает не наш список, а САМ ШАБЛОН: синий шрифт на жёлтой
заливке — конвенция финмоделирования, и она в книге уже проставлена (226 ячеек).
Свой список разошёлся бы с ней молча, а забытая в нём ячейка осталась бы жёлтой
на расчётном листе — то есть приглашала бы печатать там, где печатать больше
нельзя.

Цена переименования измерена: 85 665 вхождений внутри `<x:f>`, 15 в тексте,
одно имя листа. Адреса при этом НЕ двигаются — меняется только имя перед `!`,
поэтому ни одна ссылка не ломается.
"""

from __future__ import annotations

import re
from typing import Any

ENTRY_SHEET = "Вводные"
PARAMS_SHEET = "Параметры модели"

_CELL = re.compile(r'<x:c r="([A-Z]+\d+)"([^>]*?)(?:/>|>(.*?)</x:c>)', re.S)
_ROW = re.compile(r'<x:row r="(\d+)"([^>]*?)(?:/>|>(.*?)</x:row>)', re.S)


def _fill_ids(styles: str, rgb: str) -> set[int]:
    block = re.search(r"<x:fills[^>]*>(.*?)</x:fills>", styles, re.S)
    if not block:
        return set()
    fills = re.findall(r"<x:fill>.*?</x:fill>", block.group(1), re.S)
    return {i for i, fill in enumerate(fills) if rgb.upper() in fill.upper()}


def _font_ids(styles: str, rgb: str) -> set[int]:
    block = re.search(r"<x:fonts[^>]*>(.*?)</x:fonts>", styles, re.S)
    if not block:
        return set()
    fonts = re.findall(r"<x:font>.*?</x:font>", block.group(1), re.S)
    return {i for i, font in enumerate(fonts) if rgb.upper() in font.upper()}


def _xf_ids(styles: str, fills: set[int], fonts: set[int]) -> list[int]:
    block = re.search(r"<x:cellXfs[^>]*>(.*?)</x:cellXfs>", styles, re.S)
    if not block:
        return []
    out: list[int] = []
    for index, item in enumerate(re.findall(r"<x:xf [^>]*/?>", block.group(1))):
        fill = re.search(r'fillId="(\d+)"', item)
        font = re.search(r'fontId="(\d+)"', item)
        if fill and font and int(fill.group(1)) in fills and int(font.group(1)) in fonts:
            out.append(index)
    return out


def style_map(styles: str) -> dict[str, Any]:
    """Стили шаблона: где печатают и где считается.

    Синий шрифт на жёлтой заливке — «вписано руками», зелёный на голубой —
    «формула». Это конвенция самого шаблона, а не наша выдумка, и ставшая
    формулой ячейка обязана перекраситься: жёлтая ячейка с формулой приглашает
    затереть формулу.
    """
    entry = _xf_ids(styles, _fill_ids(styles, "FFF2CC"), _font_ids(styles, "0000FF"))
    formula = _xf_ids(styles, _fill_ids(styles, "EAF2F8"), _font_ids(styles, "008000"))
    return {"entry": set(entry), "formula": formula[0] if formula else None,
            "entry_default": entry[0] if entry else None}


def shared_strings(xml: str) -> list[str]:
    out: list[str] = []
    for item in re.findall(r"<x:si>(.*?)</x:si>", xml, re.S):
        out.append("".join(re.findall(r"<x:t[^>]*>(.*?)</x:t>", item, re.S)))
    return out


def cell_text(attrs: str, body: str, strings: list[str]) -> str:
    """Текст ячейки: общая строка, встроенная строка или строковый результат."""
    if 't="s"' in attrs:
        found = re.search(r"<x:v>(\d+)</x:v>", body or "")
        if found:
            index = int(found.group(1))
            return strings[index] if 0 <= index < len(strings) else ""
        return ""
    if 't="inlineStr"' in attrs:
        return "".join(re.findall(r"<x:t[^>]*>(.*?)</x:t>", body or "", re.S))
    found = re.search(r"<x:v>(.*?)</x:v>", body or "", re.S)
    return found.group(1) if found and 't="str"' in attrs else ""


def column_of(coord: str) -> str:
    return re.match(r"[A-Z]+", coord).group(0)


def row_of(coord: str) -> int:
    return int(re.search(r"\d+", coord).group(0))


def rename_in_formula(text: str, old: str = ENTRY_SHEET, new: str = PARAMS_SHEET) -> str:
    """Имя листа в ОДНОЙ формуле. Правило одно на всю книгу и на проверки.

    Движок собирает формулы под прежним именем, а переименование идёт по
    книге разом. Проверке, которая сверяет собранную формулу с той, что писал
    движок, нужно то же преобразование — второе разошлось бы с первым молча.
    """
    quoted = f"'{old}'!"
    plain = re.compile(r"(?<![A-Za-zА-Яа-я0-9_'])%s!" % re.escape(old))
    return plain.sub(f"'{new}'!", text.replace(quoted, f"'{new}'!"))


def rename_sheet_refs(xml: str, old: str = ENTRY_SHEET, new: str = PARAMS_SHEET) -> str:
    """Имя листа перед `!` — и только оно.

    Адрес (`$B$15`) не двигается, поэтому ни одна из 85 665 ссылок не ломается.
    Правится и текст: подпись «Вводные / очереди» на листе ПРОВЕРКИ называет
    лист, и после переименования она указывала бы на несуществующий.
    """
    def swap(text: str) -> str:
        return rename_in_formula(text, old, new)
    xml = re.sub(r"<x:f>([^<]*)</x:f>", lambda m: "<x:f>" + swap(m.group(1)) + "</x:f>", xml)
    xml = re.sub(r"<x:t([^>]*)>([^<]*)</x:t>",
                 lambda m: f"<x:t{m.group(1)}>" + m.group(2).replace(old, new) + "</x:t>", xml)
    xml = re.sub(r'(<x:c [^>]*t="str"[^>]*>)<x:v>([^<]*)</x:v>',
                 lambda m: m.group(1) + "<x:v>" + m.group(2).replace(old, new) + "</x:v>", xml)
    return xml



GUIDE_SHEET = "ИНСТРУКЦИЯ"


def guide(entry: str, params: str, styles: str, report: dict[str, Any],
          missing: list[str] | None = None) -> str:
    """Лист «как заполнять» — собранный из самой книги, а не написанный рядом.

    «Объясни инструкцией, что где вводить, а Эксель можно и где» (владелец,
    04.09.2026). Написать это текстом значило бы завести вторую правду о
    книге: разделы переименуют, ячейка переедет, а инструкция останется
    прежней и будет читаться как верная — ровно то, чем оказалась оговорка
    «кадастровых номеров у площадки нет».

    Поэтому здесь нет ни одного числа и ни одного названия раздела, взятого
    из головы: разделы читаются с листа ввода, цвета — из стилей шаблона,
    счёт переехавшего — из отчёта о переносе, а «чего не хватает» — из того
    же `missing`, который книга и так показывает.
    """
    smap = style_map(styles)
    entry_rows = scan(entry)
    header_ids = _header_styles(styles)
    # Заголовков у раздела два и они соседние: имя раздела и шапка колонок
    # («Показатель | Значение | Ед. изм.»). Разделом считается первый —
    # шапка колонок в оглавлении читалась бы как ещё пять разделов с одним и
    # тем же именем.
    marked: list[tuple[int, str]] = []
    for number in sorted(entry_rows):
        if number <= 3:  # первые строки листа ввода — его собственная шапка
            continue
        cell = entry_rows[number].get("A")
        if not cell:
            continue
        title = cell_text(cell["attrs"], cell["body"], [])
        if not title:
            continue
        if cell["style"] in header_ids or (title == title.upper() and len(title) > 6):
            marked.append((number, title))
    sections: list[tuple[int, str]] = []
    for index, (number, title) in enumerate(marked):
        if index and number == marked[index - 1][0] + 1:
            continue  # шапка колонок своего раздела
        sections.append((number, title))

    lines: list[tuple[str, str]] = [
        ("Куда печатать", f"Только на лист «{ENTRY_SHEET}». Это единственное место "
                          "ввода в книге."),
        ("Где считается", f"Лист «{PARAMS_SHEET}» и все листы за ним. Там стоят "
                          "формулы шаблона; вписанное туда число стирает формулу, "
                          "и книга дальше считает по нему."),
        ("Как отличить", "Цвет — утверждение о ячейке, а не украшение. "
                         "Синий шрифт на жёлтой заливке — печатают руками. "
                         "Зелёный на голубой — считается формулой. "
                         "Белый жирный на тёмно-синем — заголовок."),
        ("Что стоит на прежних местах",
         f"На «{PARAMS_SHEET}» вместо каждой вводной осталась ссылка на лист "
         f"«{ENTRY_SHEET}»: адреса не двигались, и ни одна формула книги не "
         "сломалась. Править ссылку незачем — правьте то, на что она смотрит."),
        ("Когда пересчитывается",
         "Excel считает книгу при открытии, дальше — сразу после правки. "
         "F9 пересчитывает вручную."),
        ("Куда смотреть после",
         "«ОТЧЕТ» — итог, «Дашборд» — картинки, «ПРОВЕРКИ» — сходимость. "
         "MODEL STATUS в B3 «ПРОВЕРОК» — общий вердикт, «Статус» построчно: "
         "FAIL значит, что книга сама с собой не согласна, и число из «ОТЧЕТ» "
         "брать нельзя, пока он не пройден."),
    ]

    out: list[str] = []
    at = 1
    head = smap.get("entry_default")

    def row(cells: str) -> None:
        nonlocal at
        out.append(f'<x:row r="{at}">' + cells + "</x:row>")
        at += 1

    row(_text_cell(f"A{at}", "DEVELOPAID · КАК ЗАПОЛНЯТЬ КНИГУ", None))
    row(_text_cell(f"A{at}", "Собрано из самой книги: разделы прочитаны с листа "
                             "ввода, цвета — из стилей шаблона. Второй правды о "
                             "книге здесь нет.", None))
    at += 1

    row(_text_cell(f"A{at}", "ПРАВИЛА", None))
    for name, text in lines:
        row(_text_cell(f"A{at}", name, None) + _text_cell(f"B{at}", text, None))
    at += 1

    row(_text_cell(f"A{at}", "РАЗДЕЛЫ ЛИСТА ВВОДА", None))
    row(_text_cell(f"A{at}", "Раздел", None) + _text_cell(f"B{at}", "Строки", None))
    for index, (number, title) in enumerate(sections):
        end = (sections[index + 1][0] - 1) if index + 1 < len(sections) else max(entry_rows)
        row(_text_cell(f"A{at}", title, None)
            + _text_cell(f"B{at}", f"{number}–{end}", None))
    at += 1

    row(_text_cell(f"A{at}", "СКОЛЬКО ЯЧЕЕК", None))
    row(_text_cell(f"A{at}", "Переехало на лист ввода", None)
        + _text_cell(f"B{at}", str(report.get("moved", 0)), None))
    row(_text_cell(f"A{at}", "Перекрашено (была жёлтой, стала формулой)", None)
        + _text_cell(f"B{at}", str(report.get("restyled", 0)), None))
    at += 1

    row(_text_cell(f"A{at}", "ЧЕГО КНИГА НЕ СЧИТАЕТ", None))
    left = list(missing or [])
    if left:
        row(_text_cell(f"A{at}", "Движок сообщил при сборке:", None))
        for item in left[:40]:
            row(_text_cell(f"A{at}", str(item)[:300], None))
    else:
        row(_text_cell(f"A{at}", "Всё, что движок умеет писать в книгу, в неё "
                                 "попало: список несобранного пуст.", None))
    row(_text_cell(f"A{at}", "Отдельно: нормативов города, справочника районов и "
                             "расчёта ГлавАПУ в книге нет — их считает сервис, а "
                             "в книгу приезжает результат.", None))

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<x:cols><x:col min="1" max="1" width="46" customWidth="1"/>'
            '<x:col min="2" max="2" width="96" customWidth="1"/></x:cols>'
            "<x:sheetData>" + "".join(out) + "</x:sheetData></x:worksheet>")


def _header_styles(styles: str) -> set[int]:
    """Заголовок раздела: белый жирный на тёмно-синем."""
    fills = _fill_ids(styles, "1F4E78") | _fill_ids(styles, "17365D")
    fonts = _font_ids(styles, "FFFFFF")
    return set(_xf_ids(styles, fills, fonts))


def scan(sheet: str) -> dict[int, dict[str, dict[str, Any]]]:
    """Лист как строки → колонка → {стиль, атрибуты, тело}. Порядок сохраняется."""
    out: dict[int, dict[str, dict[str, Any]]] = {}
    for row in _ROW.finditer(sheet):
        number = int(row.group(1))
        body = row.group(3) or ""
        cells: dict[str, dict[str, Any]] = {}
        for cell in _CELL.finditer(body):
            coord, attrs, inner = cell.group(1), cell.group(2), cell.group(3) or ""
            style = re.search(r's="(\d+)"', attrs)
            cells[column_of(coord)] = {
                "coord": coord, "attrs": attrs, "body": inner,
                "style": int(style.group(1)) if style else None,
                "formula": "<x:f>" in inner,
            }
        out[number] = cells
    return out


QUEUE_HEADER_ROW = 87
QUEUE_ROWS = (88, 89, 90, 91)
TITLE_ROWS = (1, 2, 3)


def _text_cell(coord: str, value: str, style: int | None) -> str:
    attr = f' s="{style}"' if style is not None else ""
    return (f'<x:c r="{coord}"{attr} t="inlineStr"><x:is><x:t>'
            + value.replace("&", "&amp;").replace("<", "&lt;") + "</x:t></x:is></x:c>")


def _moved_cell(coord: str, source: dict[str, Any]) -> str:
    """Ячейка переезжает КАК ЕСТЬ — со своим стилем и значением.

    Собирать её заново значило бы завести второй ответ на «как это выглядит»:
    жёлтая заливка и синий шрифт в шаблоне не украшение, а утверждение «здесь
    печатают», и терять его нельзя.
    """
    return f'<x:c r="{coord}"{source["attrs"]}>{source["body"]}</x:c>'


def plan(sheet: str, styles: str) -> dict[str, Any]:
    """Что переезжает на лист ввода — и куда именно.

    Строка копируется ЦЕЛИКОМ, а не разбирается по колонкам: у шаблона четыре
    разные геометрии блоков (подпись слева, подпись справа, сценарные колонки,
    таблица очередей), и угаданная геометрия однажды подпишет число чужим
    именем. Копия несёт подписи, единицы и ключи сама.

    Блок очередей переворачивается: 39 колонок, и поля ТЭП стоят в W–AC за
    краем экрана — ровно то, из-за чего «хер поймёшь, куда ТЭПы вбивать»
    (владелец, 03.09.2026). Строкой на показатель и колонкой на очередь он
    читается.
    """
    smap = style_map(styles)
    headers = _header_styles(styles)
    entry_styles = smap["entry"]
    rows = scan(sheet)

    restyle: list[str] = []
    keep: list[int] = []
    for number in sorted(rows):
        if number in TITLE_ROWS or number == QUEUE_HEADER_ROW or number in QUEUE_ROWS:
            continue
        cells = rows[number]
        has_entry = False
        for cell in cells.values():
            if cell["style"] in entry_styles:
                if cell["formula"]:
                    restyle.append(cell["coord"])
                else:
                    has_entry = True
        if has_entry:
            keep.append(number)

    # Заголовок раздела едет вместе со своими строками: без него список
    # вводных читается как одна простыня.
    #
    # Заголовков у раздела ДВА и они соседние — имя («СДЕЛКА, НАЛОГИ И
    # ФИНАНСИРОВАНИЕ») и шапка колонок («Показатель | Значение | Ед. изм.»).
    # Пока каждый решал за себя, шапка становилась границей для имени над ней:
    # первая вводная лежит ПОСЛЕ шапки, значит «до следующего заголовка» у
    # имени вводных не было, и на лист ввода уезжала только шапка. Выходило
    # сто строк подписей и пять «Показатель» без единого названия раздела —
    # ровно то, из-за чего «хер поймёшь, куда вбивать». Подряд идущие
    # заголовки — один заголовок, и решают они вместе.
    # Шапка горизонтальной таблицы очередей сюда не идёт: сама таблица
    # переворачивается и уезжает своим блоком ниже, а её «ID | Вкл. |
    # Наименование» без неё — заголовок без таблицы.
    header_rows = [number for number in sorted(rows)
                   if number not in TITLE_ROWS and number != QUEUE_HEADER_ROW
                   and (rows[number].get("A") or rows[number].get("J"))
                   and (rows[number].get("A") or rows[number].get("J"))["style"] in headers]
    groups: list[list[int]] = []
    for number in header_rows:
        if groups and number == groups[-1][-1] + 1:
            groups[-1].append(number)
        else:
            groups.append([number])
    wanted = set(keep)
    for index, group in enumerate(groups):
        following = [number for number in keep if number > group[-1]]
        limit = groups[index + 1][0] if index + 1 < len(groups) else 10 ** 9
        if following and min(following) < limit:
            wanted.update(group)

    queue_header = rows.get(QUEUE_HEADER_ROW, {})
    queue_columns: list[str] = []
    for column, cell in queue_header.items():
        live = [rows.get(number, {}).get(column) for number in QUEUE_ROWS]
        if any(one and one["style"] in entry_styles and not one["formula"] for one in live):
            queue_columns.append(column)
        for one in live:
            if one and one["style"] in entry_styles and one["formula"]:
                restyle.append(one["coord"])
    queue_columns.sort(key=lambda c: (len(c), c))
    return {"rows": rows, "keep": sorted(wanted), "scalar_rows": keep,
            "queue_columns": queue_columns, "queue_header": queue_header,
            "restyle": restyle, "styles": smap, "headers": headers}


def build(sheet: str, styles: str) -> tuple[str, str, dict[str, Any]]:
    """Лист ввода и расчётный лист: значения туда, читалки сюда.

    Возвращает (расчётный XML, XML листа ввода, отчёт). Соответствие адресов
    строится в том же проходе, что и перенос, — второй список «что куда уехало»
    разошёлся бы с первым молча.
    """
    made = plan(sheet, styles)
    rows, smap = made["rows"], made["styles"]
    entry_styles, formula_style = smap["entry"], smap["formula"]
    moved: dict[str, str] = {}
    out: list[str] = []
    at = 1

    out.append(f'<x:row r="{at}">'
               + _text_cell(f"A{at}", "DEVELOPAID · ВВОДНЫЕ ПРОЕКТА", None) + "</x:row>")
    at += 1
    out.append(f'<x:row r="{at}">'
               + _text_cell(f"A{at}", "Печатают только здесь. Лист «Параметры модели» "
                                      "читает эти ячейки и считает по ним — вписывать там нечего.",
                            None) + "</x:row>")
    at += 2

    for number in made["keep"]:
        cells = rows[number]
        parts: list[str] = []
        for column, cell in sorted(cells.items(), key=lambda pair: (len(pair[0]), pair[0])):
            target = f"{column}{at}"
            if cell["style"] in entry_styles and not cell["formula"]:
                parts.append(_moved_cell(target, cell))
                moved[cell["coord"]] = target
            elif not cell["formula"]:
                parts.append(f'<x:c r="{target}"{cell["attrs"]}>{cell["body"]}</x:c>')
        if parts:
            out.append(f'<x:row r="{at}">' + "".join(parts) + "</x:row>")
            at += 1

    at += 1
    out.append(f'<x:row r="{at}">'
               + _text_cell(f"A{at}", "ТЭП И СРОКИ ПО ОЧЕРЕДЯМ", None) + "</x:row>")
    at += 1
    out.append(f'<x:row r="{at}">'
               + _text_cell(f"A{at}", "Показатель", None)
               + "".join(_text_cell(f"{chr(ord('B') + index)}{at}",
                                    cell_text(rows[QUEUE_ROWS[index]].get("C", {}).get("attrs", ""),
                                              rows[QUEUE_ROWS[index]].get("C", {}).get("body", ""),
                                              []) or f"Очередь {index + 1}", None)
                          for index in range(len(QUEUE_ROWS)))
               + "</x:row>")
    at += 1
    for column in made["queue_columns"]:
        head = made["queue_header"].get(column) or {}
        title = cell_text(head.get("attrs", ""), head.get("body", ""), []) or column
        parts = [_text_cell(f"A{at}", title, None)]
        for index, number in enumerate(QUEUE_ROWS):
            cell = rows.get(number, {}).get(column)
            target = f"{chr(ord('B') + index)}{at}"
            if cell and cell["style"] in entry_styles and not cell["formula"]:
                parts.append(_moved_cell(target, cell))
                moved[cell["coord"]] = target
        out.append(f'<x:row r="{at}">' + "".join(parts) + "</x:row>")
        at += 1

    entry_xml = ('<?xml version="1.0" encoding="utf-8"?>'
                 '<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                 f'<x:sheetData>{"".join(out)}</x:sheetData></x:worksheet>')

    params = sheet
    for source, target in moved.items():
        style = f' s="{formula_style}"' if formula_style is not None else ""
        replacement = (f'<x:c r="{source}"{style}>'
                       f"<x:f>'{ENTRY_SHEET}'!{target}</x:f></x:c>")
        params = _CELL.sub(lambda m, c=source, r=replacement: r if m.group(1) == c else m.group(0),
                           params, count=0)
    for coord in made["restyle"]:
        params = re.sub(r'(<x:c r="%s")[^>]*?s="\d+"' % re.escape(coord),
                        lambda m: m.group(1) + f' s="{formula_style}"', params, count=1)
    return params, entry_xml, {"moved": len(moved), "restyled": len(made["restyle"]),
                               "rows": len(made["keep"]), "map": moved}
