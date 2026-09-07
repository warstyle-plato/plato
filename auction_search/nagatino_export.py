"""Свод «участок → объекты на нём» книгой Excel.

Таблица живёт на служебной странице, но работают с ней в Excel: «таблицу то мне
сюда в эксель надо» (владелец, 07.09.2026). Книга собирается из того же
`territory()`, что рисует страницу, — второй сборки нет: разойдясь, они дали бы
два достоверных на вид ответа об одной территории.

Три вещи книга обязана сказать так же, как экран.

**Земля и строения не складываются.** У участка площадь земли, у здания —
площадь здания; они стоят в РАЗНЫХ колонках, а не в одной.

**Объект на нескольких участках повторяется у каждого.** В извещении 47 строк
на 39 объектов, и строка «стоит на N участках» это называет: сложив колонку
площадей по строкам, получишь метры, которых не существует. Поэтому итог по
объектам считается по объектам, а не по строкам листа.

**Оперативное управление — не собственность.** У девяти строений собственник
город Москва, а держит их ГБУ «Жилищник»: это своя колонка, а не замена
собственнику.

Запуск проверок: python3 -m pytest tests/test_the_nagatino_export.py -q
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="171717")
LAND_FILL = PatternFill("solid", fgColor="EFEFEA")

# Земля идёт ПЕРЕД площадями: «не понимаю, где статус земли... столбец с
# информацией по участку должен быть где-то перед столбцом D» (владелец,
# 07.09.2026). Заполнены земельные графы только на строке УЧАСТКА.
#
# Сперва я повторял их и на строках строений — чтобы строка была
# самодостаточной. Вышло хуже: рядом оказывались два собственника, земли и
# строения, и различить их было нечем («почему в столбце Д, где речь об
# участках, указаны и данные про строения? это путаница» — тот же день).
# Колонка принадлежит одному виду строк; связь со своим участком держит
# колонка «Участок», по ней и сводят.
SHEET_LANDS = (
    ("row_kind", "Строка", 11),
    ("cadastral_number", "Кадастровый номер", 24),
    ("land", "Участок", 22),
    ("land_area_sqm", "Площадь земли, м²", 16),
    ("object_area_sqm", "Площадь строения, м²", 18),
    ("cadastral_value_rub", "Кадастровая стоимость, ₽", 21),
    ("owner", "Правообладатель — по этой строке", 54),
    ("inn", "ИНН", 13),
    ("burden", "Аренда и обременения", 60),
    ("disposal", "Вывод DevelopAid — чьё это", 56),
    ("permitted_use", "Разрешённое использование / назначение", 42),
    ("fate", "Судьба по извещению", 19),
    ("note", "Примечание", 32),
    ("address", "Адрес по ЕГРН", 50),
)

# Лист «Кто чем владеет» — две таблицы, и они отвечают на РАЗНЫЕ вопросы.
# Верхняя: что записано в документах. Нижняя: чьё это, если считать по участку
# («если строения на участке автокомбината, значит строения автокомбината, если
# там жилищник значит Москва», владелец 07.09.2026). Сложить их в одну нельзя:
# первая — ответ ЕГРН, вторая — наш вывод, и под одной шапкой они читались бы
# как одно утверждение. Группа при этом не колонка, а полоса: строки стоят
# внутри своей группы, и у каждой группы свой промежуточный итог.
SHEET_OWNERS = (
    ("name", "Правообладатель", 52),
    ("inn", "ИНН", 14),
    ("lands", "Участков", 10),
    ("land_area_sqm", "Земли, м²", 14),
    ("objects", "Строений", 10),
    ("objects_area_sqm", "Их площадь, м²", 16),
    # Справочная колонка: земля ПОД строениями. Своей она владельцу не
    # становится, и складывать её нельзя — участок под строениями двух
    # владельцев посчитан у каждого. Итог группы поэтому объединение, а не
    # сумма строк, и об этом сказано под таблицей.
    ("under_land_area_sqm", "Земля под их строениями, м² · справочно", 24),
    ("value_rub", "Кадастровая стоимость, ₽", 22),
)
# Та же справочная колонка есть и во взгляде «по участку» (владелец,
# 07.09.2026: «вторая таблица так же столбец такой должна иметь»): у Брынцалова
# своей земли нет ни в одном взгляде, а под его строениями 97 563 м².
SHEET_HOLDINGS = SHEET_OWNERS + (("by", "На чём основано", 34),)
# Порядок групп — тот же, что в реестре и на экране: второй список разошёлся бы
# с первым молча.
_MONEY = '#,##0" ₽"'
_AREA = '#,##0.0'
_OWNER_FORMATS = {"land_area_sqm": _AREA, "objects_area_sqm": _AREA,
                  "under_land_area_sqm": _AREA, "value_rub": _MONEY}


def _owner_text(owner: dict[str, Any]) -> str:
    """Кто держит объект ЭТОЙ строки: собственность, дата и иные права разом.

    Раньше это были три колонки. Их стало слишком много, а разнесённые они не
    отвечали на один вопрос — «с кем разговаривать»: собственник в одной графе,
    оперативное управление в другой, дата в третьей.
    """
    # Вывод сюда НЕ попадает: у него своя графа. Слитые в одну клетку, ответ
    # реестра и наше прочтение читались бы как одна запись — на экране их
    # разводит мелкий шрифт, а в книге клетка есть клетка.
    if not owner.get("name"):
        return str(owner.get("note") or "")
    line = str(owner["name"])
    if owner.get("since"):
        line += f", право с {owner['since']}"
    for item in owner.get("others") or []:
        line += f"\n{item.get('right_type')}: {item.get('name')}"
    return line


def _burden_text(items: list[dict[str, Any]], *, with_kind: bool) -> str:
    """Обременение строкой: кто, до какого срока и по какому документу.

    Показывать одну аренду нельзя: ипотека и «прочие ограничения» — тоже
    обременения, и молча выброшенное читается как его отсутствие.
    """
    out = []
    for item in items or []:
        parts = [item.get("name") or "—"]
        if item.get("until"):
            parts.append(f"до {item['until']}")
        elif any(char.isdigit() for char in item.get("term") or ""):
            parts.append(item["term"])
        else:
            # У 77:05:0004001:1093 сама запись ЕГРН обрывается на слове «до».
            # Печатать это как срок значит выдать обрыв документа за ответ.
            parts.append("срок в записи ЕГРН не указан")
        if item.get("document_number"):
            parts.append(f"договор {item['document_number']}")
        line = ", ".join(parts)
        out.append(f"{item.get('kind')}: {line}" if with_kind else line)
    return "; ".join(out)


def _land_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Объект на нескольких участках стоит в книге у каждого. Метры при этом его
    # собственные, и посчитать их дважды нельзя: у повтора площадь не
    # печатается вовсе, а строка говорит, где она учтена. Иначе сумма колонки
    # (56 323,3 м²) разошлась бы с итогом объектов (52 381,0) — и обе выглядели
    # бы верными.
    counted: dict[str, str] = {}
    for land in view["lands"]:
        disposal = land.get("disposal") or {}
        rows.append({
            "row_kind": "участок",
            "cadastral_number": land["cadastral_number"] + (" (часть)" if land.get("part") else ""),
            "land": land["cadastral_number"],
            "land_area_sqm": land.get("area_sqm"),
            "object_area_sqm": None,
            "cadastral_value_rub": land.get("cadastral_value_rub"),
            "owner": _owner_text(land["owner"]),
            "inn": land["owner"].get("inn") or "",
            # Аренда и прочие обременения — один вопрос «чем связан объект», а
            # вид стоит в самой строке: «Аренда: …», «Ипотека: …».
            "burden": _burden_text((land.get("leases") or []) + (land.get("encumbrances") or []),
                                   with_kind=True),
            # Вывод подписан как вывод и стоит вместе со своим основанием.
            "disposal": (f"{disposal['who']} — {disposal['ground']}"
                         if disposal.get("who") else ""),
            "permitted_use": land.get("permitted_use") or "",
            "fate": "",
            "note": ("объектов на участке нет" if not land["objects"] else
                     f"строений {len(land['objects'])}, вместе {land['objects_area_sqm']:,.1f} м²"
                     .replace(",", " ")),
            "address": land.get("address") or "",
        })
        for item in land["objects"]:
            notes = []
            first = counted.get(item["cadastral_number"])
            if len(item.get("lands") or []) > 1:
                notes.append(f"стоит на {len(item['lands'])} участках")
            # Площадь берётся из выписки; её нет — из извещения, и это сказано.
            area = item.get("area_sqm")
            if area is None and item.get("notice_area_sqm") is not None:
                area = item["notice_area_sqm"]
                notes.append("площадь по извещению — выписки ЕГРН на объект нет")
            elif not item.get("extract"):
                notes.append("выписки ЕГРН нет")
            if (item.get("notice_area_sqm") is not None and item.get("area_sqm") is not None
                    and abs(item["notice_area_sqm"] - item["area_sqm"]) > 0.05):
                notes.append(f"в извещении {item['notice_area_sqm']:,.1f} м²".replace(",", " "))
            if first:
                notes.append(f"повтор: метры учтены у {first}")
                area = None
            else:
                counted[item["cadastral_number"]] = land["cadastral_number"]
            rows.append({
                "row_kind": "строение",
                "cadastral_number": item["cadastral_number"] + (" (часть)" if item.get("part") else ""),
                # Земельные графы у строения пусты: они про участок, и стоят на
                # его строке. Здесь остаётся только связь — чей это участок.
                "land": ", ".join(item.get("lands") or []) or "—",
                "land_area_sqm": None,
                "object_area_sqm": area,
                "cadastral_value_rub": item.get("cadastral_value_rub"),
                "owner": _owner_text(item["owner"]),
                "inn": item["owner"].get("inn") or "",
                "burden": _burden_text((item.get("leases") or []) + (item.get("encumbrances") or []),
                                       with_kind=True),
                # У строения без своего права графа вывода не пустует: «по
                # зданиям, о которых мы говорили, что это автокомбинат, так же
                # писать, что судя по тому, что на участке автокомбината, это
                # их собственность» (владелец, 07.09.2026).
                "disposal": str((item.get("owner") or {}).get("guess") or ""),
                "permitted_use": " · ".join(x for x in (item.get("name"), item.get("purpose"),
                                                        f"постр. {item['year_built']}"
                                                        if item.get("year_built") else "") if x),
                "fate": item.get("fate") or "",
                "note": "; ".join(notes),
                "address": item.get("address") or "",
            })
    return rows


def _fill(sheet, columns, rows: list[dict[str, Any]], formats: dict[str, str]) -> None:
    sheet.append([column[1] for column in columns])
    keys = [column[0] for column in columns]
    for row in rows:
        sheet.append([row.get(key) if row.get(key) is not None else "" for key in keys])
    sheet.freeze_panes = "A2"
    sheet.sheet_view.showGridLines = False
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 40
    # Колонки, где текст многострочный: без переноса вторая строка «Оперативное
    # управление: …» не видна вовсе, а она про то, с кем разговаривать.
    wrapped = {"owner", "burden", "disposal", "permitted_use", "note", "address"}
    for index, (key, _title, width) in enumerate(columns, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = width
        if key in formats:
            for cell in sheet[letter][1:]:
                cell.number_format = formats[key]
        if key in wrapped:
            for cell in sheet[letter][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    for index, row in enumerate(rows, start=2):
        if row.get("row_kind") == "участок":
            for cell in sheet[index]:
                cell.fill = LAND_FILL
                cell.font = Font(bold=True)


GROUP_FILL = PatternFill("solid", fgColor="E7E7E1")
TOTAL_FILL = PatternFill("solid", fgColor="F3F3EF")


def _owners_table(sheet, columns, rows: list[dict[str, Any]], order: list[dict[str, Any]],
                  title: str, note: str, start: int,
                  unions: dict[str, Any] | None = None) -> int:
    """Одна таблица листа владельцев: полосы групп и итог у каждой.

    Возвращает номер строки ПОСЛЕ таблицы. Итог группы считается по её же
    строкам — не по своему кругу: разойдясь, он назвал бы другую сумму под тем
    же именем.
    """
    keys = [column[0] for column in columns]
    sheet.cell(row=start, column=1, value=title).font = Font(bold=True, size=13)
    sheet.cell(row=start + 1, column=1, value=note).font = Font(color="6B6B6B", size=10)
    sheet.cell(row=start + 1, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    sheet.merge_cells(start_row=start + 1, start_column=1,
                      end_row=start + 1, end_column=len(columns))
    sheet.row_dimensions[start + 1].height = 30
    head = start + 2
    for index, (_key, caption, _width) in enumerate(columns, start=1):
        cell = sheet.cell(row=head, column=index, value=caption)
        cell.fill = HEADER_FILL
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[head].height = 30
    line = head + 1
    counted: list[dict[str, Any]] = []
    for group in order:
        inside = [row for row in rows if row.get("group") == group.get("key")]
        if not inside:
            continue
        band = sheet.cell(row=line, column=1, value=str(group.get("title") or ""))
        band.font = Font(bold=True)
        for index in range(1, len(columns) + 1):
            sheet.cell(row=line, column=index).fill = GROUP_FILL
        line += 1
        for row in inside:
            for index, key in enumerate(keys, start=1):
                value = row.get(key)
                cell = sheet.cell(row=line, column=index,
                                  value="" if value is None else value)
                if key in _OWNER_FORMATS:
                    cell.number_format = _OWNER_FORMATS[key]
                if key == "name":
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
            line += 1
        total = {"name": f"Итого · {group.get('title')}"}
        for key in ("lands", "land_area_sqm", "objects", "objects_area_sqm", "value_rub"):
            total[key] = round(sum(float(row.get(key) or 0) for row in inside), 1)
        # Справочная земля не суммируется: у двух владельцев группы под
        # строениями бывает один участок, и сумма назвала бы метры, которых
        # нет. Итог группы — объединение, посчитанное там же, где сама
        # величина.
        if unions is not None:
            total["under_land_area_sqm"] = ((unions.get("by_group") or {})
                                            .get(str(group.get("key")))
                                            or {}).get("area_sqm", "")
        for index, key in enumerate(keys, start=1):
            cell = sheet.cell(row=line, column=index, value=total.get(key, ""))
            cell.font = Font(bold=True)
            cell.fill = TOTAL_FILL
            if key in _OWNER_FORMATS:
                cell.number_format = _OWNER_FORMATS[key]
        line += 1
        counted += inside
    # Строки, чья группа не названа вовсе, теряться не должны: молча
    # пропущенная строка читается как её отсутствие в территории.
    rest = [row for row in rows if row not in counted]
    if rest:
        # Имя полосы берут у самих строк: «группа не назначена» и «хозяин не
        # определён» — разные утверждения, и второе принадлежит нижней таблице.
        titles = {str(row.get("group_title") or "") for row in rest}
        caption = titles.pop() if len(titles) == 1 and all(titles) else "Группа не назначена"
        band = sheet.cell(row=line, column=1, value=caption)
        band.font = Font(bold=True)
        for index in range(1, len(columns) + 1):
            sheet.cell(row=line, column=index).fill = GROUP_FILL
        line += 1
        for row in rest:
            for index, key in enumerate(keys, start=1):
                value = row.get(key)
                cell = sheet.cell(row=line, column=index,
                                  value="" if value is None else value)
                if key in _OWNER_FORMATS:
                    cell.number_format = _OWNER_FORMATS[key]
            line += 1
        total = {"name": f"Итого · {caption}"}
        for key in ("lands", "land_area_sqm", "objects", "objects_area_sqm", "value_rub"):
            total[key] = round(sum(float(row.get(key) or 0) for row in rest), 1)
        for index, key in enumerate(keys, start=1):
            cell = sheet.cell(row=line, column=index, value=total.get(key, ""))
            cell.font = Font(bold=True)
            cell.fill = TOTAL_FILL
            if key in _OWNER_FORMATS:
                cell.number_format = _OWNER_FORMATS[key]
        line += 1
    grand = {"name": "ВСЕГО"}
    for key in ("lands", "land_area_sqm", "objects", "objects_area_sqm", "value_rub"):
        grand[key] = round(sum(float(row.get(key) or 0) for row in rows), 1)
    if unions is not None:
        grand["under_land_area_sqm"] = (unions.get("total") or {}).get("area_sqm", "")
    for index, key in enumerate(keys, start=1):
        cell = sheet.cell(row=line, column=index, value=grand.get(key, ""))
        cell.font = Font(bold=True)
        if key in _OWNER_FORMATS:
            cell.number_format = _OWNER_FORMATS[key]
    return line + 1


def build(view: dict[str, Any], owners: list[dict[str, Any]],
          holdings: list[dict[str, Any]] | None = None,
          groups: list[dict[str, Any]] | None = None,
          under: dict[str, Any] | None = None,
          under_holdings: dict[str, Any] | None = None) -> bytes:
    """Книга свода. Считает не она — она показывает посчитанное."""
    book = Workbook()
    rows = _land_rows(view)
    sheet = book.active
    sheet.title = "ЗУ и объекты"
    _fill(sheet, SHEET_LANDS, rows,
          {"land_area_sqm": _AREA, "object_area_sqm": _AREA, "cadastral_value_rub": _MONEY})
    totals = view["totals"]
    # Итог обязан сходиться с колонкой, а не считаться по своему кругу: у
    # повтора площадь не напечатана, поэтому сумма колонки и есть сумма
    # объектов. Второй итог — по выпискам ЕГРН — назван отдельно: у одного
    # объекта выписки нет вовсе, и его метры взяты из извещения.
    printed = round(sum(row["object_area_sqm"] for row in rows
                        if isinstance(row.get("object_area_sqm"), (int, float))), 1)
    note = "объект на нескольких участках учтён один раз"
    if abs(printed - totals["objects_area_sqm"]) > 0.05:
        # Разделитель разрядов меняем У ЧИСЛА, а не во всей фразе: иначе
        # запятая пропадает и в самом предложении.
        egrn = f"{totals['objects_area_sqm']:,.1f}".replace(",", " ")
        note += (f"; по выпискам ЕГРН {egrn} м² — на один объект выписки нет, "
                 "его метры из извещения")
    sheet.append([])
    tail = {"row_kind": "итого",
            "cadastral_number": f"{totals['lands']} участков и {totals['objects']} объектов",
            "land_area_sqm": totals["land_area_sqm"], "object_area_sqm": printed,
            "cadastral_value_rub": round(totals["land_value_rub"] + totals["objects_value_rub"], 1),
            "note": note}
    # Строка итога собирается ПО КЛЮЧАМ: список по позициям ломается молча,
    # стоит колонке появиться в середине — а она только что появилась.
    sheet.append([tail.get(key, "") for key, _title, _width in SHEET_LANDS])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    sheet.cell(row=sheet.max_row, column=3).number_format = _AREA
    sheet.cell(row=sheet.max_row, column=4).number_format = _AREA
    sheet.cell(row=sheet.max_row, column=5).number_format = _MONEY

    second = book.create_sheet("Кто чем владеет")
    second.sheet_view.showGridLines = False
    for index, (_key, _caption, width) in enumerate(SHEET_HOLDINGS, start=1):
        second.column_dimensions[get_column_letter(index)].width = width
    order = list(groups or [])
    line = _owners_table(
        second, SHEET_OWNERS,
        [{**row, "value_rub": round((row.get("land_value_rub") or 0)
                                    + (row.get("objects_value_rub") or 0), 1)}
         for row in owners],
        order,
        "Что записано в документах",
        "Собственник по выпискам ЕГРН. Земля стоит там, где право на участок "
        "зарегистрировано; у четырнадцати участков из двадцати его нет вовсе — "
        "это ответ реестра, а не наш пробел. Оперативное управление ГБУ "
        "«Жилищник» собственностью не является: эти строения записаны за городом. "
        "Последняя колонка справочная — земля ПОД строениями, своей она владельцу "
        "не становится. Складывать её нельзя: на одном участке стоят строения "
        "разных владельцев, и он посчитан у каждого; итог группы поэтому "
        "объединение участков, а не сумма строк.",
        1, under)
    if holdings:
        _owners_table(
            second, SHEET_HOLDINGS, holdings, order,
            "Чьё это, если считать по участку — вывод DevelopAid",
            "Строения приписаны хозяину земли, на которой стоят: «если строения "
            "на участке автокомбината, значит строения автокомбината, если там "
            "жилищник значит Москва» (решение владельца, 07.09.2026). Это НАШ "
            "вывод, а не запись реестра. Хозяина участка называет ЕГРН; нет "
            "записи — единственный собственник строений на нём, а если лица "
            "разные, но группа одна — группа. Объект на нескольких участках "
            "посчитан один раз.",
            line + 1, under_holdings)

    third = book.create_sheet("Источники")
    source = view.get("source") or {}
    notice = source.get("notice") or {}
    extracts = source.get("egrn_extracts") or {}
    third.column_dimensions["A"].width = 34
    third.column_dimensions["B"].width = 104
    for name, value in (
        ("Территория", "КРТ нежилой застройки 14,62 га, Варшавское ш., влд. 37, "
                       "Нагатинская ул., влд. 3А/6 (ЮАО, Нагатино-Садовники)"),
        ("Состав территории", f"Извещение о торгах {notice.get('number', '')} "
                              f"от {notice.get('date', '')} — приложение № 2"),
        ("Площади, права, аренда", f"Выписки ЕГРН, {extracts.get('count', '')} шт., "
                                   f"сформированы {extracts.get('formed_at', '')}"),
        ("Чего здесь нет", "Правообладателя участка там, где собственность не "
                           "зарегистрирована: это ответ ЕГРН, а не наш пробел"),
        ("Как читать лист", "Строка участка выделена заливкой; под ней идут его "
                            "строения. Земельные графы (C–G) заполнены только на строке "
                            "участка — они про землю. У строения своя земля названа "
                            "номером в колонке «Участок»: по ней лист и сводится"),
        ("Где чей ответ", "Колонка «Статус земли» — запись ЕГРН. Колонка «Кто "
                          "распоряжается» — вывод DevelopAid, и рядом стоит, на чём он "
                          "сделан: у 11 участков это номер городского договора аренды "
                          "(«М-05-…», «…-05 ДГИ»), у трёх — только общее правило: в "
                          "Москве неразграниченная госсобственность в распоряжении "
                          "города. Записи о собственности Москвы в ЕГРН по ним нет"),
        ("Оперативное управление", "Не собственность: у девяти строений собственник — "
                                   "город Москва, держатель — ГБУ «Жилищник»"),
        ("Земля и строения", "Разные величины и разные колонки: у участка площадь земли, "
                             "у здания площадь здания; плотность считается только по земле"),
        ("Расхождение документов", "77:05:0004001:2077 есть в выписках и нет в извещении; "
                                   "77:05:0004001:1951 наоборот"),
    ):
        third.append([name, value])
        third.cell(row=third.max_row, column=1).font = Font(bold=True)
        third.cell(row=third.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    third.sheet_view.showGridLines = False

    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()
