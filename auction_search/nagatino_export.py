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

# Земля идёт ПЕРЕД площадями и повторяется на каждой строке, включая строки
# строений: «не понимаю, где статус земли» (владелец, 07.09.2026). В плоском
# листе строка участка и строка строения выглядят одинаково, и чей под зданием
# участок приходилось искать глазами вверх по листу. Повтор здесь не дубль:
# он делает строку самодостаточной — по ней можно фильтровать и сводить.
SHEET_LANDS = (
    ("row_kind", "Строка", 12),
    ("cadastral_number", "Кадастровый номер", 24),
    ("land", "Участок", 24),
    ("land_status", "Статус земли (запись ЕГРН)", 40),
    ("land_disposal", "Кто распоряжается — вывод DevelopAid", 34),
    ("land_disposal_ground", "На чём этот вывод", 56),
    ("land_lease", "Аренда земли", 52),
    ("land_area_sqm", "Площадь земли, м²", 17),
    ("object_area_sqm", "Площадь строения, м²", 19),
    ("cadastral_value_rub", "Кадастровая стоимость, ₽", 22),
    ("owner", "Правообладатель (собственность)", 46),
    ("inn", "ИНН", 14),
    ("since", "Право с", 12),
    ("other_rights", "Иное право (оперативное управление и т. п.)", 44),
    ("lease", "Аренда объекта", 46),
    ("encumbrance", "Иные обременения (ипотека, ограничения)", 52),
    ("permitted_use", "Разрешённое использование / назначение", 44),
    ("fate", "Судьба по извещению", 20),
    ("note", "Примечание", 34),
    ("address", "Адрес по ЕГРН", 52),
)

SHEET_OWNERS = (
    ("name", "Правообладатель", 52),
    ("inn", "ИНН", 14),
    ("group_title", "Группа", 24),
    ("lands", "Участков", 10),
    ("land_area_sqm", "Земли, м²", 14),
    ("objects", "Строений", 10),
    ("objects_area_sqm", "Их площадь, м²", 16),
    ("value_rub", "Кадастровая стоимость, ₽", 22),
)

_MONEY = '#,##0" ₽"'
_AREA = '#,##0.0'


def _owner_text(owner: dict[str, Any]) -> str:
    return str(owner.get("name") or owner.get("note") or "")


def _others_text(owner: dict[str, Any]) -> str:
    return "; ".join(f"{item.get('right_type')}: {item.get('name')}"
                     for item in owner.get("others") or [])


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


def _land_status(land: dict[str, Any]) -> str:
    """Чья земля — словами документа, а не нашим выводом.

    «Собственность не зарегистрирована» — это ответ ЕГРН. Что такой землёй
    распоряжается город, видно по номерам договоров аренды («М-05-…»,
    «…-05 ДГИ»), но записи о собственности Москвы в реестре нет, и писать её
    в этой графе нельзя.
    """
    owner = land["owner"]
    if owner.get("name"):
        return f"собственность: {owner['name']}"
    return "собственность в ЕГРН не зарегистрирована"


def _land_rows(view: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Объект на нескольких участках стоит в книге у каждого. Метры при этом его
    # собственные, и посчитать их дважды нельзя: у повтора площадь не
    # печатается вовсе, а строка говорит, где она учтена. Иначе сумма колонки
    # (56 323,3 м²) разошлась бы с итогом объектов (52 381,0) — и обе выглядели
    # бы верными.
    counted: dict[str, str] = {}
    for land in view["lands"]:
        status = _land_status(land)
        disposal = land.get("disposal") or {}
        land_lease = _burden_text(land.get("leases"), with_kind=False)
        rows.append({
            "row_kind": "участок",
            "cadastral_number": land["cadastral_number"] + (" (часть)" if land.get("part") else ""),
            "land": land["cadastral_number"],
            "land_status": status,
            # Вывод стоит СВОЕЙ графой: в клетке статуса — ответ ЕГРН, здесь —
            # наше суждение с основанием. Слитые, они читались бы как реестр.
            "land_disposal": disposal.get("who") or "",
            "land_disposal_ground": disposal.get("ground") or "",
            "land_lease": land_lease,
            "land_area_sqm": land.get("area_sqm"),
            "object_area_sqm": None,
            "cadastral_value_rub": land.get("cadastral_value_rub"),
            "owner": _owner_text(land["owner"]),
            "inn": land["owner"].get("inn") or "",
            "other_rights": _others_text(land["owner"]),
            "since": land["owner"].get("since") or "",
            "lease": _burden_text(land.get("leases"), with_kind=False),
            "encumbrance": _burden_text(land.get("encumbrances"), with_kind=True),
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
            # Строение на нескольких участках: свести их статусы в одну клетку
            # значило бы сказать о земле то, чего документ не говорит.
            many = len(item.get("lands") or []) > 1
            rows.append({
                "row_kind": "строение",
                "cadastral_number": item["cadastral_number"] + (" (часть)" if item.get("part") else ""),
                "land": ", ".join(item.get("lands") or []) or "—",
                "land_status": ("у каждого участка свой статус — см. их строки" if many
                                else status),
                "land_disposal": "" if many else (disposal.get("who") or ""),
                "land_disposal_ground": "" if many else (disposal.get("ground") or ""),
                "land_lease": "" if many else land_lease,
                "land_area_sqm": None,
                "object_area_sqm": area,
                "cadastral_value_rub": item.get("cadastral_value_rub"),
                "owner": _owner_text(item["owner"]),
                "inn": item["owner"].get("inn") or "",
                "other_rights": _others_text(item["owner"]),
                "since": item["owner"].get("since") or "",
                "lease": _burden_text(item.get("leases"), with_kind=False),
                "encumbrance": _burden_text(item.get("encumbrances"), with_kind=True),
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
    for index, (key, _title, width) in enumerate(columns, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = width
        if key in formats:
            for cell in sheet[letter][1:]:
                cell.number_format = formats[key]
    for index, row in enumerate(rows, start=2):
        if row.get("row_kind") == "участок":
            for cell in sheet[index]:
                cell.fill = LAND_FILL
                cell.font = Font(bold=True)


def build(view: dict[str, Any], owners: list[dict[str, Any]]) -> bytes:
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
    _fill(second, SHEET_OWNERS,
          [{**row, "value_rub": round((row.get("land_value_rub") or 0)
                                      + (row.get("objects_value_rub") or 0), 1)}
           for row in owners],
          {"land_area_sqm": _AREA, "objects_area_sqm": _AREA, "value_rub": _MONEY})

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
