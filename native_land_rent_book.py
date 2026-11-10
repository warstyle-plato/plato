"""Native books consume the shared editable land-lease worksheet.

No rate, accrual or cash-allocation implementation lives here. The same
``v4_land_rent.build_sheet`` formulas serve housing, office/retail and hotel.
"""
from __future__ import annotations

import io
import calendar
from copy import copy
from datetime import date
from typing import Any

from openpyxl.cell.cell import Cell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet._reader import WorksheetReader

SHEET = "Аренда ЗУ"
PHASE_LIMITATION = ("Нативная книга отражает одну очередь; общая аренда по очередям здесь не рассчитана. "
                    "Нужна книга с подтверждённой моделью очередей.")


def requested(spec: dict[str, Any]) -> bool:
    inputs = spec.get("land_rent_inputs") or {}
    result = spec.get("land_rent") or {}
    return (inputs.get("land_right") == "lease"
            or inputs.get("land_rent_mode", "unspecified") != "unspecified"
            or result.get("status") not in (None, "not_applicable"))


def end_formula(spec: dict[str, Any], rve: str) -> str:
    """Keep the canonical residual horizon tied to an editable RVE date."""
    result = spec.get("land_rent") or {}
    try:
        commissioning = date.fromisoformat(str(result["rve"]))
        end = date.fromisoformat(str(result["project_end"]))
    except (KeyError, ValueError):
        raise ValueError("Аренда ЗУ: в исходном расчёте не определён горизонт проекта") from None
    months = (end.year - commissioning.year) * 12 + end.month - commissioning.month
    if months < 0:
        raise ValueError("Аренда ЗУ: горизонт раньше ввода")
    target_month = commissioning.month - 1 + months
    target_year, target_month = commissioning.year + target_month // 12, target_month % 12 + 1
    moved = date(target_year, target_month, min(commissioning.day, calendar.monthrange(target_year, target_month)[1]))
    days = (end - moved).days
    return f"EDATE({rve},{months})" + (f"{days:+d}" if days else "")


def add(book, spec: dict[str, Any], *, start: str, rve: str, end: str,
        month_formulas: list[str], input_fill=None):
    """Return formula refs (million RUB), or None for unchanged owned land.

    The source/input pair is mandatory for an editable sheet: a computed cash
    array alone is not a substitute for an exportable financial model.
    """
    if not requested(spec):
        return None
    inputs, result = spec.get("land_rent_inputs"), spec.get("land_rent")
    if not isinstance(inputs, dict) or not isinstance(result, dict):
        raise ValueError("Аренда ЗУ: для редактируемой книги нужны условия договора и результат расчёта")
    if len(result.get("phase_shares") or []) > 1 and result.get("status") != "not_applicable":
        # Existing phased+PF routing chooses generic v4 before reaching a
        # native book. A direct native route must not freeze the consolidated
        # cutoff or repeat a common-parcel cost in a one-queue financial model.
        raise ValueError(PHASE_LIMITATION)
    if SHEET in book.sheetnames:
        raise ValueError("Аренда ЗУ: лист уже добавлен")
    from v4_land_rent import build_sheet

    sheet = book.create_sheet(SHEET)
    styles = {}
    for key in ("amount", "date", "input", "input_date", "input_text"):
        cell = Cell(sheet, row=1, column=1)
        cell.font = Font(name="Carlito", size=11, color="0000FF" if key.startswith("input") else "203C32")
        if key.startswith("input"):
            cell.fill = copy(input_fill) if input_fill is not None else PatternFill("solid", fgColor="FFF2CC")
        cell.number_format = "dd.mm.yyyy" if key.endswith("date") else "#,##0.000" if key != "input_text" else "General"
        styles[key] = cell.style_id
    xml = build_sheet(inputs, result, styles, project_start_formula=start,
                      rve_formula=rve, project_end_formula=end,
                      months=len(month_formulas),
                      # Calendar cash buckets start on day 1. Exact contract,
                      # project-start and RVE dates above keep their own days.
                      month_formulas=[f"({formula})-DAY({formula})+1" for formula in month_formulas])
    # Parse the shared OOXML with openpyxl's own reader. Styles belong to this
    # workbook; validations and editable source cells survive the round trip.
    WorksheetReader(sheet, io.BytesIO(xml), [], False, False).bind_all()
    sheet.sheet_view.showGridLines = False
    sheet.sheet_properties.tabColor = "C26A0A"
    return lambda index: f"'{SHEET}'!{get_column_letter(4 + index)}6"


def vat_exempt(month_ref: str) -> str:
    """Public/unknown tax treatment never creates an assumed VAT credit."""
    return f'IF(\'{SHEET}\'!$I$18="Облагается НДС",0,SUM({month_ref}))'


def qualifier() -> str:
    # Completeness and historical-import policy belong to the shared sheet,
    # including the difference between accrual completeness and cash knowns.
    return f"'{SHEET}'!$L$13"


def qualify(sheet) -> None:
    """Qualify financial conclusions where the user reads their totals."""
    previous = str(sheet["A2"].value or "")
    prefix = previous[1:] if previous.startswith("=") else '"' + previous.replace('"', '""') + '"'
    sheet["A2"] = f'={prefix}&IF({qualifier()}="",""," · "&{qualifier()})'
    alignment = copy(sheet["A2"].alignment)
    alignment.wrap_text = True
    sheet["A2"].alignment = alignment
    sheet.row_dimensions[2].height = max(sheet.row_dimensions[2].height or 0, 45)
