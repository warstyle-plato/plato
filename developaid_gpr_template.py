"""Бланк недельного ГПР-факта из утверждённого ГПР Монитора.

Владелец, 30.10.2026, после ГПР по пакетам («этот файл не подходит»): «сделай
шаблон ГПР с разбивкой на корпуса, общие работы и отдельно паркинг, который
был бы полезен с еженедельным выполнением». Бланк собирается из самого
утверждённого ГПР: те же работы с теми же ID — поэтому загруженный обратно
той же кнопкой «ГПР-факт» он ложится на свои работы без всякого сопоставления
(`manager._baseline_status` сводит строки по ID). Раскладка колонок — та,
что читает `actuals.read_schedule`; новых форм загрузки нет.

Работы сгруппированы по объектам: корпуса по номеру, затем паркинг /
стилобат, затем общие объекты (сети, площадка, территория). Процент и статус
предзаполнены текущими — пустая клетка не станет «нет данных», править нужно
только то, что изменилось за неделю. Рядом — план к дате, чтобы видеть, где
отставание.
"""

from __future__ import annotations

import datetime
import io
import re
from typing import Any

import developaid_monitor as monitor
import developaid_monitor_manager as manager

HEADER = ["ID", "WBS", "Раздел", "Объект", "Наименование работ", "Тип строки",
          "% выполнения", "Начало", "Окончание", "Статус", "Длительность, р.д.",
          "Предшественники", "Связанный тендер", "Окончание тендера", "Резерв", "Увязка",
          "Код РСС", "Статья РСС", "Основание привязки", "План к дате, %", "Комментарий"]
HEADER_ROW = 4  # первая строка работ — 5-я, как ждёт `actuals.read_schedule`


def _object_order(name: str) -> tuple:
    low = name.lower()
    number = re.search(r"корпус\D*(\d+)", low)
    if number:
        return (0, int(number.group(1)), name)
    if "корпус" in low:
        return (0, 999, name)
    if "паркинг" in low or "стилобат" in low:
        return (1, 0, name)
    return (2, 0, name)


def build(project: str, upto: str) -> bytes:
    """Книга-бланк на дату ``upto`` (ГГГГ-ММ-ДД) с текущими процентами."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    if not str(project or "").strip():
        raise ValueError("Не указан проект: впишите название проекта в поле «Проект» вверху "
                         "страницы.")
    try:
        works = monitor._read_baseline_gpr(project).get("works") or []
    except FileNotFoundError:
        works = []
    if not works:
        raise ValueError(f"Бланк собирается из утверждённого ГПР, а в проекте «{project}» он "
                         "в Мониторе не загружен.")
    day = datetime.date.fromisoformat(upto)
    statuses = manager._baseline_status(project, upto)

    groups: dict[str, list[dict[str, Any]]] = {}
    for work in works:
        groups.setdefault(str(work.get("object") or "").strip() or "Без объекта", []).append(work)

    book = Workbook()
    sheet = book.active
    sheet.title = "ГПР"
    sheet["A1"] = f"ГПР с процентами — {project}"
    sheet["A1"].font = Font(bold=True, size=13)
    sheet["A2"] = (f"Процент и статус на {day.strftime('%d.%m.%Y')}. Поправьте жёлтые колонки "
                   "«% выполнения» и «Статус» у работ, где что-то изменилось за неделю, и "
                   "загрузите файл кнопкой «Загрузить ГПР с процентами». Строки и ID не "
                   "меняйте: по ID процент ложится на свою работу.")
    for col, title in enumerate(HEADER, 1):
        cell = sheet.cell(row=HEADER_ROW, column=col, value=title)
        cell.font = Font(bold=True)
    edit = PatternFill("solid", fgColor="FFF4C2")
    group_fill = PatternFill("solid", fgColor="E8EEF6")
    line = HEADER_ROW + 1
    for name in sorted(groups, key=_object_order):
        # Строка-заголовок объекта: без ID — `read_schedule` её пропускает.
        title = sheet.cell(row=line, column=5, value=name)
        title.font = Font(bold=True)
        for col in range(1, len(HEADER) + 1):
            sheet.cell(row=line, column=col).fill = group_fill
        line += 1
        rows = sorted(groups[name], key=lambda w: (w.get("start") or datetime.date.max,
                                                    str(w.get("wbs") or "")))
        for work in rows:
            tid = str(work.get("id") or work.get("wbs") or "").strip()
            now = statuses.get(tid) or {}
            progress = now.get("progress")
            if progress is None:
                progress = work.get("progress")
            start, finish = work.get("start"), work.get("finish")
            plan = (monitor._plan_progress(start, finish, day)
                    if isinstance(start, datetime.date) and isinstance(finish, datetime.date)
                    else None)
            values = [tid, work.get("wbs") or tid, work.get("section") or "",
                      work.get("object") or "", work.get("name") or "",
                      work.get("kind") or "Работа", progress, start, finish,
                      now.get("status") or work.get("status") or "", work.get("duration"),
                      work.get("predecessors") or "", "", "", "", "",
                      work.get("estimate_code") or "", work.get("estimate_name") or "",
                      work.get("basis") or "", plan, ""]
            for col, value in enumerate(values, 1):
                cell = sheet.cell(row=line, column=col, value=value)
                if col in (7, 20):
                    cell.number_format = "0%"
                elif col in (8, 9):
                    cell.number_format = "DD.MM.YYYY"
            sheet.cell(row=line, column=7).fill = edit
            sheet.cell(row=line, column=10).fill = edit
            line += 1
    widths = {"A": 8, "B": 10, "C": 16, "D": 16, "E": 48, "F": 9, "G": 12, "H": 11,
              "I": 11, "J": 16, "Q": 12, "R": 24, "S": 14, "T": 12, "U": 30}
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width
    for col in "KLMNOP":  # служебные колонки ГПР: нужны разборщику, не человеку
        sheet.column_dimensions[col].hidden = True
    sheet.freeze_panes = "F5"
    blob = io.BytesIO()
    book.save(blob)
    return blob.getvalue()
