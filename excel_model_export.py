from __future__ import annotations

import copy
import html
import io
import re
import threading
import zipfile
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import xlsxwriter
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

_RUNTIME_VERSION = "0.12.38"
_EXPORT_LOCK = threading.RLock()


class ExcelModelRequest(BaseModel):
    inputs: dict[str, Any]
    tep: dict[str, dict[str, Any]]
    rates: list[dict[str, Any]] = Field(default_factory=list)
    phasing: dict[str, Any] = Field(default_factory=dict)
    project_name: str = ""
    cadastral_numbers: list[str] = Field(default_factory=list)
    source_label: str = ""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _mln(value: Any) -> float:
    return _num(value) / 1_000_000.0


def _iso_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except Exception:
        return None


def _safe_name(value: str, fallback: str = "Проект") -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" ._")
    return (text or fallback)[:90]


def _project_title(req: ExcelModelRequest) -> str:
    if str(req.project_name or "").strip():
        return _safe_name(req.project_name)
    if req.cadastral_numbers:
        return _safe_name("_".join(str(item) for item in req.cadastral_numbers[:4]))
    manual = (req.inputs.get("_manual_tep_import") or {}).get("project_name")
    if manual:
        return _safe_name(str(manual))
    return "Девелоперский проект"


def _formats(workbook: xlsxwriter.Workbook) -> dict[str, Any]:
    dark = "#19324A"
    dark2 = "#244A64"
    light = "#EAF0F4"
    border = "#B7C2CC"
    base = {"font_name": "Arial", "font_size": 9}
    return {
        "title": workbook.add_format({**base, "bold": True, "font_size": 18, "font_color": "#FFFFFF", "bg_color": dark, "align": "left", "valign": "vcenter"}),
        "subtitle": workbook.add_format({**base, "font_size": 9, "font_color": "#DCE7EF", "bg_color": dark, "align": "left", "valign": "vcenter"}),
        "section": workbook.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": dark2, "align": "left", "valign": "vcenter", "border": 1, "border_color": dark2}),
        "header": workbook.add_format({**base, "bold": True, "font_color": "#17202A", "bg_color": light, "border": 1, "border_color": border, "align": "center", "valign": "vcenter", "text_wrap": True}),
        "label": workbook.add_format({**base, "font_color": "#111111", "border": 1, "border_color": border, "align": "left", "valign": "vcenter"}),
        "text": workbook.add_format({**base, "font_color": "#111111", "border": 1, "border_color": border, "align": "left", "valign": "vcenter", "text_wrap": True}),
        "input": workbook.add_format({**base, "font_color": "#0000FF", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.00;[Red](#,##0.00);-'}),
        "input_int": workbook.add_format({**base, "font_color": "#0000FF", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0;[Red](#,##0);-'}),
        "input_text": workbook.add_format({**base, "font_color": "#0000FF", "border": 1, "border_color": border, "align": "left", "valign": "vcenter", "text_wrap": True}),
        "input_date": workbook.add_format({**base, "font_color": "#0000FF", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": 'dd.mm.yyyy'}),
        "number": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "integer": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0;[Red](#,##0);-'}),
        "money": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "money_green": workbook.add_format({**base, "font_color": "#008000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "percent": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.0%;[Red](0.0%);-'}),
        "percent_input": workbook.add_format({**base, "font_color": "#0000FF", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.0;[Red](0.0);-'}),
        "multiple": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.00x;[Red](0.00x);-'}),
        "multiple_green": workbook.add_format({**base, "font_color": "#008000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.00x;[Red](0.00x);-'}),
        "date": workbook.add_format({**base, "font_color": "#000000", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": 'dd.mm.yyyy'}),
        "total_label": workbook.add_format({**base, "bold": True, "font_color": "#111111", "top": 1, "top_color": dark, "align": "left", "valign": "vcenter"}),
        "total_money": workbook.add_format({**base, "bold": True, "font_color": "#000000", "top": 1, "top_color": dark, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "total_number": workbook.add_format({**base, "bold": True, "font_color": "#000000", "top": 1, "top_color": dark, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "kpi_label": workbook.add_format({**base, "bold": True, "font_color": "#455A64", "bg_color": "#F4F7F9", "border": 1, "border_color": border, "align": "left", "valign": "vcenter"}),
        "kpi_money": workbook.add_format({**base, "bold": True, "font_size": 12, "font_color": "#008000", "bg_color": "#F4F7F9", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "kpi_number": workbook.add_format({**base, "bold": True, "font_size": 12, "font_color": "#008000", "bg_color": "#F4F7F9", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '#,##0.0;[Red](#,##0.0);-'}),
        "kpi_percent": workbook.add_format({**base, "bold": True, "font_size": 12, "font_color": "#008000", "bg_color": "#F4F7F9", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.0%;[Red](0.0%);-'}),
        "kpi_multiple": workbook.add_format({**base, "bold": True, "font_size": 12, "font_color": "#008000", "bg_color": "#F4F7F9", "border": 1, "border_color": border, "align": "right", "valign": "vcenter", "num_format": '0.00x;[Red](0.00x);-'}),
        "note": workbook.add_format({**base, "font_color": "#6B7280", "italic": True, "text_wrap": True, "valign": "top"}),
        "conclusion": workbook.add_format({**base, "font_size": 10, "font_color": "#111111", "bg_color": "#FFF7D6", "border": 1, "border_color": "#D9C56B", "text_wrap": True, "valign": "top"}),
    }


def _setup_sheet(ws: Any, *, landscape: bool = False) -> None:
    ws.hide_gridlines(2)
    ws.freeze_panes(3, 1)
    ws.set_default_row(16)
    ws.set_landscape() if landscape else ws.set_portrait()
    ws.fit_to_pages(1, 0)
    ws.set_margins(0.3, 0.3, 0.45, 0.45)
    ws.set_header("&LDevelopAid&CФинансовая модель&R&P / &N")
    ws.set_footer("&LЭкспорт текущего серверного расчёта DevelopAid&R&D &T")


def _write_title(ws: Any, title: str, subtitle: str, formats: dict[str, Any], last_col: int = 7) -> None:
    ws.merge_range(0, 0, 0, last_col, title, formats["title"])
    ws.merge_range(1, 0, 1, last_col, subtitle, formats["subtitle"])
    ws.set_row(0, 28)
    ws.set_row(1, 19)


def _write_input_value(ws: Any, row: int, col: int, value: Any, unit: str, field_type: str, formats: dict[str, Any]) -> None:
    if field_type == "date" or (isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[:10] if value else "")):
        parsed = _iso_date(value)
        if parsed:
            ws.write_datetime(row, col, parsed, formats["input_date"])
        else:
            ws.write(row, col, str(value or ""), formats["input_text"])
    elif field_type == "checkbox" or isinstance(value, bool):
        ws.write(row, col, "Да" if bool(value) else "Нет", formats["input_text"])
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        fmt = formats["percent_input"] if "%" in str(unit) else formats["input"]
        if float(value).is_integer() and "%" not in str(unit):
            fmt = formats["input_int"]
        ws.write_number(row, col, float(value), fmt)
    elif isinstance(value, (dict, list)):
        ws.write(row, col, str(value), formats["input_text"])
    else:
        ws.write(row, col, str(value or ""), formats["input_text"])
    try:
        ws.write_comment(row, col, "Источник: текущие вводные расчёта DevelopAid.")
    except Exception:
        pass


def _write_inputs_sheet(workbook: Any, formats: dict[str, Any], core: Any, inputs: dict[str, Any], project_title: str, phase_meta: dict[str, Any] | None = None) -> None:
    ws = workbook.add_worksheet("Вводные")
    _setup_sheet(ws)
    _write_title(ws, f"Вводные · {project_title}", "Синим шрифтом показаны значения, переданные в текущий серверный расчёт", formats, 3)
    ws.set_column("A:A", 34)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 20)
    ws.set_column("D:D", 26)
    row = 3
    used: set[str] = set()
    for group in getattr(core, "FIELD_GROUPS", []) or []:
        group_name, fields = group
        ws.merge_range(row, 0, row, 3, str(group_name), formats["section"])
        row += 1
        ws.write_row(row, 0, ["Параметр", "Значение", "Единица", "Код"], formats["header"])
        row += 1
        for field in fields:
            key, label, unit, field_type = field
            if key not in inputs:
                continue
            used.add(key)
            ws.write(row, 0, label, formats["label"])
            _write_input_value(ws, row, 1, inputs.get(key), unit, field_type, formats)
            ws.write(row, 2, unit, formats["text"])
            ws.write(row, 3, key, formats["text"])
            row += 1
        row += 1

    if phase_meta:
        ws.merge_range(row, 0, row, 3, "Параметры очереди", formats["section"])
        row += 1
        ws.write_row(row, 0, ["Параметр", "Значение", "Единица", "Комментарий"], formats["header"])
        row += 1
        phase_rows = [
            ("Наименование", phase_meta.get("name"), "", ""),
            ("Номер очереди", phase_meta.get("index"), "", ""),
            ("Сдвиг старта", phase_meta.get("start_offset_months"), "мес.", "Относительно старта проекта"),
            ("Коэффициент инфляции затрат", phase_meta.get("cost_inflation_factor"), "x", ""),
            ("Коэффициент инфляции цены", phase_meta.get("sales_price_inflation_factor"), "x", ""),
            ("Кассовая общепроектная нагрузка", _mln(phase_meta.get("cash_shared_cost")), "млн ₽", ""),
            ("Экономически аллоцированная нагрузка", _mln(phase_meta.get("allocated_shared_cost")), "млн ₽", ""),
            ("Аллоцированная чистая прибыль", _mln(phase_meta.get("allocated_net_profit")), "млн ₽", ""),
        ]
        for label, value, unit, note in phase_rows:
            ws.write(row, 0, label, formats["label"])
            if unit == "млн ₽":
                ws.write_number(row, 1, _num(value), formats["money"])
            elif unit == "x":
                ws.write_number(row, 1, _num(value), formats["multiple"])
            elif isinstance(value, (int, float)):
                ws.write_number(row, 1, _num(value), formats["number"])
            else:
                ws.write(row, 1, str(value or ""), formats["text"])
            ws.write(row, 2, unit, formats["text"])
            ws.write(row, 3, note, formats["text"])
            row += 1
        row += 1

    remaining = [key for key in sorted(inputs) if key not in used and not key.startswith("_")]
    if remaining:
        ws.merge_range(row, 0, row, 3, "Дополнительные параметры", formats["section"])
        row += 1
        ws.write_row(row, 0, ["Параметр", "Значение", "Единица", "Код"], formats["header"])
        row += 1
        for key in remaining:
            ws.write(row, 0, key, formats["label"])
            _write_input_value(ws, row, 1, inputs.get(key), "", "", formats)
            ws.write(row, 2, "", formats["text"])
            ws.write(row, 3, key, formats["text"])
            row += 1


def _write_tep_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, str]:
    ws = workbook.add_worksheet("ТЭП")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"ТЭП · {project_title}", "Площади и натуральные показатели текущего расчёта", formats, 7)
    headers = ["Продукт", "Код", "ГНС, м²", "Общая площадь, м²", "Полезная, м²", "Продаваемая, м²", "Передаваемая, м²", "Количество, шт."]
    ws.write_row(3, 0, headers, formats["header"])
    rows = ((result.get("tep") or {}).get("rows") or [])
    start = 4
    for idx, item in enumerate(rows):
        row = start + idx
        ws.write(row, 0, item.get("label") or item.get("key") or "", formats["label"])
        ws.write(row, 1, item.get("key") or "", formats["text"])
        for col, key in enumerate(("gns", "total_area", "useful", "saleable", "transfer", "units"), 2):
            ws.write_number(row, col, _num(item.get(key)), formats["number"])
    total_row = start + len(rows)
    ws.write(total_row, 0, "Итого", formats["total_label"])
    ws.write(total_row, 1, "", formats["total_label"])
    for col in range(2, 8):
        letter = xlsxwriter.utility.xl_col_to_name(col)
        ws.write_formula(total_row, col, f"=SUM({letter}{start+1}:{letter}{total_row})", formats["total_number"])
    ws.set_column("A:A", 25)
    ws.set_column("B:B", 23)
    ws.set_column("C:H", 17)
    return {"gns": f"'ТЭП'!C{total_row+1}", "saleable": f"'ТЭП'!F{total_row+1}"}


def _write_products_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, str]:
    ws = workbook.add_worksheet("Продажи")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"Продажи · {project_title}", "Продукты, объёмы, темпы, цены и выручка", formats, 10)
    headers = ["Продукт", "Код", "Единица", "Объём", "Темп до РВЭ", "Продано до РВЭ", "Стартовая цена, тыс. ₽", "Средняя цена, тыс. ₽", "Выручка, млн ₽", "Старт продаж", "Финиш продаж"]
    ws.write_row(3, 0, headers, formats["header"])
    products = ((result.get("report") or {}).get("products") or [])
    start = 4
    for idx, item in enumerate(products):
        row = start + idx
        ws.write(row, 0, item.get("label") or item.get("key") or "", formats["label"])
        ws.write(row, 1, item.get("key") or "", formats["text"])
        ws.write(row, 2, item.get("unit") or "", formats["text"])
        ws.write_number(row, 3, _num(item.get("quantity")), formats["number"])
        ws.write_number(row, 4, _num(item.get("pace_pre")), formats["number"])
        ws.write_number(row, 5, _num(item.get("share_before_rve")), formats["percent"])
        ws.write_number(row, 6, _num(item.get("start_price_th")), formats["number"])
        ws.write_number(row, 7, _num(item.get("avg_price_th")), formats["number"])
        ws.write_number(row, 8, _mln(item.get("revenue")), formats["money"])
        for col, key in ((9, "sales_start"), (10, "sales_end")):
            parsed = _iso_date(item.get(key))
            if parsed:
                ws.write_datetime(row, col, parsed, formats["date"])
            else:
                ws.write(row, col, "", formats["text"])
    total_row = start + len(products)
    ws.write(total_row, 0, "Итого", formats["total_label"])
    for col in range(1, 8):
        ws.write(total_row, col, "", formats["total_label"])
    ws.write_formula(total_row, 8, f"=SUM(I{start+1}:I{total_row})", formats["total_money"])
    ws.write(total_row, 9, "", formats["total_label"])
    ws.write(total_row, 10, "", formats["total_label"])
    ws.set_column("A:A", 24)
    ws.set_column("B:C", 18)
    ws.set_column("D:I", 16)
    ws.set_column("J:K", 14)
    return {"revenue": f"'Продажи'!I{total_row+1}"}


def _write_capex_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, str]:
    ws = workbook.add_worksheet("CAPEX")
    _setup_sheet(ws)
    _write_title(ws, f"CAPEX и структура расходов · {project_title}", "Все суммы приведены в млн ₽", formats, 6)
    capex = result.get("capex") or {}
    labels = {
        "land_rights": "Земля / смена ВРИ", "ird": "ИРД", "design_p": "Проект П", "design_rd": "Проект РД",
        "author_supervision": "Авторский надзор", "technical_supervision": "Технический заказчик / стройконтроль",
        "project_management": "Управление проектом", "preparation": "Подготовительные работы", "main_above": "Основное строительство — наземная часть",
        "main_under": "Основное строительство — подземная часть", "utilities": "Наружные сети", "landscaping": "Благоустройство",
        "commissioning": "Сдача и ввод", "site_maintenance": "Содержание стройплощадки", "social": "Социальная нагрузка",
        "offices": "Офисы / МФОЦ", "standalone_retail": "Коммерция ОСЗ", "above_parking": "Наземный паркинг",
        "gc_fee": "Генподрядчик", "reserve": "Резерв",
    }
    ws.write_row(3, 0, ["Статья", "Код", "Сумма, млн ₽", "Доля CAPEX"], formats["header"])
    items = [(key, value) for key, value in capex.items() if key != "total" and abs(_num(value)) > 0.001]
    start = 4
    for idx, (key, value) in enumerate(items):
        row = start + idx
        ws.write(row, 0, labels.get(key, key), formats["label"])
        ws.write(row, 1, key, formats["text"])
        ws.write_number(row, 2, _mln(value), formats["money"])
        ws.write_formula(row, 3, f"=IF($C${start+len(items)+1}=0,0,C{row+1}/$C${start+len(items)+1})", formats["percent"])
    total_row = start + len(items)
    ws.write(total_row, 0, "Итого CAPEX", formats["total_label"])
    ws.write(total_row, 1, "", formats["total_label"])
    ws.write_formula(total_row, 2, f"=SUM(C{start+1}:C{total_row})", formats["total_money"])
    ws.write_formula(total_row, 3, "=1", formats["percent"])
    expense = ((result.get("report") or {}).get("expense_structure") or [])
    exp_start = total_row + 4
    ws.merge_range(exp_start, 0, exp_start, 3, "Полная структура расходов", formats["section"])
    ws.write_row(exp_start + 1, 0, ["Статья", "Сумма, млн ₽", "Доля", ""], formats["header"])
    for idx, item in enumerate(expense):
        row = exp_start + 2 + idx
        ws.write(row, 0, item.get("label") or "", formats["label"])
        ws.write_number(row, 1, _mln(item.get("value")), formats["money"])
        ws.write_number(row, 2, _num(item.get("share")), formats["percent"])
        ws.write(row, 3, "", formats["text"])
    exp_total = exp_start + 2 + len(expense)
    ws.write(exp_total, 0, "Итого полные расходы", formats["total_label"])
    ws.write_formula(exp_total, 1, f"=SUM(B{exp_start+3}:B{exp_total})", formats["total_money"])
    ws.write_formula(exp_total, 2, "=1", formats["percent"])
    ws.write(exp_total, 3, "", formats["total_label"])
    ws.set_column("A:A", 38)
    ws.set_column("B:B", 24)
    ws.set_column("C:D", 17)
    if expense:
        chart = workbook.add_chart({"type": "column"})
        chart.add_series({"name": "Расходы, млн ₽", "categories": f"=CAPEX!$A${exp_start+3}:$A${exp_total}", "values": f"=CAPEX!$B${exp_start+3}:$B${exp_total}", "fill": {"color": "#244A64"}, "border": {"none": True}})
        chart.set_title({"name": "Структура полных расходов"})
        chart.set_legend({"none": True})
        chart.set_y_axis({"name": "млн ₽", "major_gridlines": {"visible": True}})
        chart.set_size({"width": 650, "height": 330})
        ws.insert_chart("F4", chart)
    return {"capex": f"'CAPEX'!C{total_row+1}", "total_expenses": f"'CAPEX'!B{exp_total+1}"}


def _write_finance_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, str]:
    ws = workbook.add_worksheet("Финансирование")
    _setup_sheet(ws)
    _write_title(ws, f"Финансирование · {project_title}", "БРИДЖ, проектное финансирование, ставки и долговые метрики", formats, 5)
    finance = result.get("finance") or {}
    report_fin = ((result.get("report") or {}).get("financing") or {})
    money_rows = [
        ("Расчётный лимит БРИДЖ", report_fin.get("calculated_bridge") or finance.get("calculated_bridge_limit")),
        ("Пиковый БРИДЖ", report_fin.get("actual_bridge") or finance.get("peak_bridge")),
        ("Пиковый ПФ", report_fin.get("pf_peak") or finance.get("peak_pf")),
        ("Пиковый непокрытый ПФ", report_fin.get("pf_uncovered_peak") or finance.get("peak_uncovered_pf")),
        ("Лимит ПФ", report_fin.get("pf_limit") or finance.get("pf_limit")),
        ("Пиковый совокупный долг", report_fin.get("peak_total_debt") or finance.get("peak_total_debt")),
        ("Пиковое наполнение эскроу", report_fin.get("peak_escrow") or finance.get("peak_escrow")),
        ("Проценты и комиссии", report_fin.get("interest_and_fees") or finance.get("financing_cost")),
    ]
    rate_rows = [
        ("Текущая ключевая ставка", report_fin.get("current_key_rate") or finance.get("current_key_rate")),
        ("Средняя ключевая в БРИДЖ", report_fin.get("avg_bridge_key_rate") or finance.get("avg_bridge_key_rate")),
        ("Текущая ставка БРИДЖ", report_fin.get("current_bridge_rate") or finance.get("current_bridge_rate")),
        ("Средняя ставка БРИДЖ", report_fin.get("avg_bridge_rate") or finance.get("avg_bridge_rate")),
        ("Средняя ключевая в ПФ", report_fin.get("avg_pf_key_rate") or finance.get("avg_pf_key_rate")),
        ("Средняя базовая ставка ПФ", report_fin.get("avg_pf_base_rate") or finance.get("avg_pf_base_rate")),
        ("Средняя эффективная ставка ПФ", report_fin.get("avg_pf_effective_rate") or finance.get("avg_pf_effective_rate")),
        ("Спецставка ПФ при покрытии 1×", report_fin.get("pf_special_rate") or finance.get("pf_special_rate")),
    ]
    row = 3
    ws.merge_range(row, 0, row, 2, "Долговые показатели", formats["section"])
    row += 1
    ws.write_row(row, 0, ["Показатель", "Значение, млн ₽", "Комментарий"], formats["header"])
    row += 1
    refs: dict[str, str] = {}
    for label, value in money_rows:
        ws.write(row, 0, label, formats["label"])
        ws.write_number(row, 1, _mln(value), formats["money"])
        ws.write(row, 2, "", formats["text"])
        refs[label] = f"'Финансирование'!B{row+1}"
        row += 1
    row += 1
    ws.merge_range(row, 0, row, 2, "Ставки", formats["section"])
    row += 1
    ws.write_row(row, 0, ["Показатель", "Значение", "Комментарий"], formats["header"])
    row += 1
    for label, value in rate_rows:
        ws.write(row, 0, label, formats["label"])
        ws.write_number(row, 1, _num(value), formats["percent"])
        ws.write(row, 2, "", formats["text"])
        row += 1
    row += 1
    ws.merge_range(row, 0, row, 2, "LLCR", formats["section"])
    row += 1
    ws.write_row(row, 0, ["Показатель", "Значение", "Комментарий"], formats["header"])
    row += 1
    numerator_row = row
    ws.write(row, 0, "Числитель LLCR", formats["label"])
    ws.write_number(row, 1, _mln(finance.get("llcr_numerator")), formats["money"])
    ws.write(row, 2, "Денежный поток, доступный для обслуживания долга", formats["text"])
    row += 1
    denominator_row = row
    ws.write(row, 0, "Знаменатель LLCR", formats["label"])
    ws.write_number(row, 1, _mln(finance.get("llcr_denominator")), formats["money"])
    ws.write(row, 2, "Расчётная долговая нагрузка", formats["text"])
    row += 1
    llcr_row = row
    ws.write(row, 0, "LLCR", formats["total_label"])
    ws.write_formula(row, 1, f"=IF(B{denominator_row+1}=0,0,B{numerator_row+1}/B{denominator_row+1})", formats["multiple_green"], _num((result.get("summary") or {}).get("llcr")))
    ws.write(row, 2, "Целевой ориентир DevelopAid: не ниже 1,20x", formats["total_label"])
    ws.set_column("A:A", 38)
    ws.set_column("B:B", 18)
    ws.set_column("C:C", 46)
    return {"interest": refs.get("Проценты и комиссии", ""), "peak_debt": refs.get("Пиковый совокупный долг", ""), "peak_escrow": refs.get("Пиковое наполнение эскроу", ""), "llcr": f"'Финансирование'!B{llcr_row+1}"}


def _write_cf_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, Any]:
    ws = workbook.add_worksheet("Помесячный CF")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"Помесячный денежный поток · {project_title}", "Денежные потоки, долг, эскроу, ставки и налог — млн ₽, если не указано иное", formats, 22)
    columns = [
        ("Месяц", "month", "date"), ("Выручка", "revenue", "money"), ("CAPEX", "capex", "money"), ("Операционные расходы", "operating", "money"),
        ("Выборка БРИДЖ", "bridge_draw", "money"), ("Погашение БРИДЖ", "bridge_repayment", "money"), ("Начисленные проценты БРИДЖ", "bridge_interest", "money"), ("Остаток БРИДЖ", "bridge_balance", "money"),
        ("Выборка ПФ", "pf_draw", "money"), ("Погашение ПФ", "pf_repayment", "money"), ("Начисленные проценты ПФ", "pf_interest", "money"), ("Остаток ПФ", "pf_balance", "money"),
        ("Выплата процентов", "interest_payment", "money"), ("Налог на прибыль", "profit_tax", "money"), ("Эскроу", "escrow", "money"),
        ("Ключевая ставка", "key_rate", "percent"), ("Ставка БРИДЖ", "bridge_rate", "percent"), ("Ставка ПФ", "pf_rate", "percent"), ("Покрытие эскроу / ПФ", "coverage", "multiple"),
        ("Налоговая маржа", "taxable_margin", "money"), ("Налоговый вычет по финансированию", "financing_tax_deduction", "money"), ("Накопленная налоговая прибыль", "taxable_profit_cumulative", "money"),
        ("Чистый проектный CF", "formula", "money"),
    ]
    ws.write_row(3, 0, [col[0] for col in columns], formats["header"])
    rows = (result.get("finance") or {}).get("rows") or []
    start = 4
    for idx, item in enumerate(rows):
        row = start + idx
        for col_idx, (_, key, kind) in enumerate(columns):
            if key == "formula":
                formula = f"=B{row+1}-C{row+1}-D{row+1}-M{row+1}-N{row+1}"
                cached = _mln(item.get("revenue")) - _mln(item.get("capex")) - _mln(item.get("operating")) - _mln(item.get("interest_payment")) - _mln(item.get("profit_tax"))
                ws.write_formula(row, col_idx, formula, formats["money_green"], cached)
            elif kind == "date":
                parsed = _iso_date(item.get(key))
                if parsed:
                    ws.write_datetime(row, col_idx, parsed, formats["date"])
                else:
                    ws.write(row, col_idx, str(item.get(key) or ""), formats["text"])
            elif kind == "money":
                ws.write_number(row, col_idx, _mln(item.get(key)), formats["money"])
            elif kind == "percent":
                ws.write_number(row, col_idx, _num(item.get(key)), formats["percent"])
            elif kind == "multiple":
                ws.write_number(row, col_idx, _num(item.get(key)), formats["multiple"])
    total_row = start + len(rows)
    ws.write(total_row, 0, "Итого / максимум", formats["total_label"])
    for col_idx, (_, key, kind) in enumerate(columns[1:], 1):
        letter = xlsxwriter.utility.xl_col_to_name(col_idx)
        if key in {"bridge_balance", "pf_balance", "escrow", "coverage"}:
            fmt = formats["total_money"] if kind == "money" else formats["multiple"]
            ws.write_formula(total_row, col_idx, f"=MAX({letter}{start+1}:{letter}{total_row})", fmt)
        elif kind == "money":
            ws.write_formula(total_row, col_idx, f"=SUM({letter}{start+1}:{letter}{total_row})", formats["total_money"])
        else:
            ws.write(total_row, col_idx, "", formats["total_label"])
    ws.set_column(0, 0, 12)
    ws.set_column(1, 14, 15)
    ws.set_column(15, 18, 14)
    ws.set_column(19, 22, 17)
    if rows:
        ws.autofilter(3, 0, total_row - 1, len(columns) - 1)
    return {"sheet": ws, "start": start, "end": total_row, "rows": len(rows)}


def _write_tax_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> dict[str, str]:
    ws = workbook.add_worksheet("Налоги")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"Налог на прибыль · {project_title}", "Накопительная налоговая база и признание налога по текущей логике DevelopAid", formats, 8)
    finance = result.get("finance") or {}
    margin_map = finance.get("tax_margin_by_product") or {}
    cost_map = finance.get("tax_cost_by_product") or {}
    labels = {"core": "Основные продукты", "offices": "Офисы / МФОЦ", "standalone_retail": "Коммерция ОСЗ", "above_parking": "Наземный паркинг"}
    ws.write_row(3, 0, ["Продукт", "Налоговая маржа, млн ₽", "Признанная себестоимость, млн ₽"], formats["header"])
    row = 4
    for key in ("core", "offices", "standalone_retail", "above_parking"):
        ws.write(row, 0, labels[key], formats["label"])
        ws.write_number(row, 1, _mln(margin_map.get(key)), formats["money"])
        ws.write_number(row, 2, _mln(cost_map.get(key)), formats["money"])
        row += 1
    ws.write(row, 0, "Итого", formats["total_label"])
    ws.write_formula(row, 1, f"=SUM(B5:B{row})", formats["total_money"])
    ws.write_formula(row, 2, f"=SUM(C5:C{row})", formats["total_money"])
    table_start = row + 3
    ws.merge_range(table_start, 0, table_start, 4, "Помесячный расчёт", formats["section"])
    ws.write_row(table_start + 1, 0, ["Месяц", "Налоговая маржа, млн ₽", "Вычет по финансированию, млн ₽", "Накопленная налоговая прибыль, млн ₽", "Налог, млн ₽"], formats["header"])
    rows = finance.get("rows") or []
    start = table_start + 2
    for idx, item in enumerate(rows):
        r = start + idx
        parsed = _iso_date(item.get("month"))
        if parsed:
            ws.write_datetime(r, 0, parsed, formats["date"])
        else:
            ws.write(r, 0, str(item.get("month") or ""), formats["text"])
        ws.write_number(r, 1, _mln(item.get("taxable_margin")), formats["money"])
        ws.write_number(r, 2, _mln(item.get("financing_tax_deduction")), formats["money"])
        ws.write_number(r, 3, _mln(item.get("taxable_profit_cumulative")), formats["money"])
        ws.write_number(r, 4, _mln(item.get("profit_tax")), formats["money"])
    total = start + len(rows)
    ws.write(total, 0, "Итого налог", formats["total_label"])
    ws.write(total, 1, "", formats["total_label"])
    ws.write(total, 2, "", formats["total_label"])
    ws.write(total, 3, "", formats["total_label"])
    ws.write_formula(total, 4, f"=SUM(E{start+1}:E{total})", formats["total_money"])
    ws.set_column("A:A", 14)
    ws.set_column("B:E", 21)
    return {"tax": f"'Налоги'!E{total+1}"}


def _write_calendar_sheet(workbook: Any, formats: dict[str, Any], result: dict[str, Any], project_title: str) -> None:
    ws = workbook.add_worksheet("Календарь")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"Календарный план · {project_title}", "Ключевые этапы проекта и очередей", formats, 6)
    ws.write_row(3, 0, ["Группа", "Этап", "Начало", "Окончание", "Длительность, дней", "Очередь", "Тип"], formats["header"])
    events = (((result.get("report") or {}).get("calendar") or {}).get("events") or [])
    for idx, item in enumerate(events):
        row = 4 + idx
        ws.write(row, 0, item.get("group") or "", formats["label"])
        ws.write(row, 1, item.get("label") or "", formats["text"])
        for col, key in ((2, "start"), (3, "end")):
            parsed = _iso_date(item.get(key))
            if parsed:
                ws.write_datetime(row, col, parsed, formats["date"])
            else:
                ws.write(row, col, "", formats["text"])
        ws.write_formula(row, 4, f"=IF(OR(C{row+1}=\"\",D{row+1}=\"\"),0,D{row+1}-C{row+1}+1)", formats["integer"])
        ws.write(row, 5, item.get("phase_name") or item.get("phase_index") or "", formats["text"])
        ws.write(row, 6, item.get("type") or "", formats["text"])
    ws.set_column("A:A", 24)
    ws.set_column("B:B", 42)
    ws.set_column("C:D", 14)
    ws.set_column("E:E", 17)
    ws.set_column("F:G", 16)


def _write_phase_comparison(workbook: Any, formats: dict[str, Any], bundle: dict[str, Any], project_title: str) -> None:
    if bundle.get("mode") != "phased":
        return
    ws = workbook.add_worksheet("Очереди")
    _setup_sheet(ws, landscape=True)
    _write_title(ws, f"Сравнение очередей · {project_title}", "Кассовая и экономическая нагрузка, финансирование и доходность", formats, 13)
    headers = ["Очередь", "Продаваемая площадь, м²", "Выручка, млн ₽", "CAPEX, млн ₽", "Кассовая общепроектная нагрузка, млн ₽", "Аллоцированная нагрузка, млн ₽", "Пиковый БРИДЖ, млн ₽", "Пиковый ПФ, млн ₽", "LLCR", "Чистая прибыль, млн ₽", "Аллоцированная прибыль, млн ₽", "Маржа", "Инфляция затрат, x", "Инфляция цены, x"]
    ws.write_row(3, 0, headers, formats["header"])
    comparison = bundle.get("comparison") or []
    start = 4
    for idx, item in enumerate(comparison):
        row = start + idx
        ws.write(row, 0, item.get("name") or f"О{idx+1}", formats["label"])
        ws.write_number(row, 1, _num(item.get("saleable_sqm")), formats["number"])
        for col, key in enumerate(("revenue", "capex", "cash_shared_cost", "allocated_shared_cost", "peak_bridge", "peak_pf"), 2):
            ws.write_number(row, col, _mln(item.get(key)), formats["money"])
        ws.write_number(row, 8, _num(item.get("llcr")), formats["multiple"])
        ws.write_number(row, 9, _mln(item.get("net_profit")), formats["money"])
        ws.write_number(row, 10, _mln(item.get("allocated_net_profit")), formats["money"])
        ws.write_number(row, 11, _num(item.get("margin")), formats["percent"])
        ws.write_number(row, 12, _num(item.get("cost_inflation_factor")), formats["multiple"])
        ws.write_number(row, 13, _num(item.get("sales_price_inflation_factor")), formats["multiple"])
    total = start + len(comparison)
    ws.write(total, 0, "Итого / минимум", formats["total_label"])
    for col in range(1, 8):
        letter = xlsxwriter.utility.xl_col_to_name(col)
        ws.write_formula(total, col, f"=SUM({letter}{start+1}:{letter}{total})", formats["total_money"] if col >= 2 else formats["total_number"])
    ws.write_formula(total, 8, f"=MIN(I{start+1}:I{total})", formats["multiple_green"])
    for col in (9, 10):
        letter = xlsxwriter.utility.xl_col_to_name(col)
        ws.write_formula(total, col, f"=SUM({letter}{start+1}:{letter}{total})", formats["total_money"])
    ws.write_formula(total, 11, f"=IF(C{total+1}=0,0,K{total+1}/C{total+1})", formats["percent"])
    ws.write(total, 12, "", formats["total_label"])
    ws.write(total, 13, "", formats["total_label"])
    ws.set_column("A:A", 14)
    ws.set_column("B:N", 18)
    if comparison:
        chart = workbook.add_chart({"type": "column"})
        chart.add_series({"name": "LLCR", "categories": f"=Очереди!$A${start+1}:$A${total}", "values": f"=Очереди!$I${start+1}:$I${total}", "fill": {"color": "#244A64"}})
        chart.set_title({"name": "LLCR по очередям"})
        chart.set_y_axis({"name": "x", "major_gridlines": {"visible": True}})
        chart.set_legend({"none": True})
        chart.set_size({"width": 600, "height": 320})
        ws.insert_chart("P4", chart)


def _write_summary_sheet(workbook: Any, formats: dict[str, Any], core: Any, result: dict[str, Any], bundle: dict[str, Any], req: ExcelModelRequest, project_title: str, refs: dict[str, str], cf_info: dict[str, Any]) -> None:
    ws = workbook.get_worksheet_by_name("Сводка") or workbook.add_worksheet("Сводка")
    ws.activate()
    _setup_sheet(ws, landscape=True)
    source = str(req.source_label or "Текущий расчёт DevelopAid")
    cadastral = ", ".join(str(x) for x in req.cadastral_numbers)
    subtitle = f"Источник: {source}" + (f" · Кадастровые номера: {cadastral}" if cadastral else "") + f" · Версия: {_RUNTIME_VERSION}"
    _write_title(ws, f"Финансовая модель · {project_title}", subtitle, formats, 11)
    ws.set_column("A:A", 30)
    ws.set_column("B:B", 17)
    ws.set_column("C:C", 3)
    ws.set_column("D:D", 30)
    ws.set_column("E:E", 17)
    ws.set_column("F:L", 13)
    summary = result.get("summary") or {}
    kpis = [
        ("Выручка, млн ₽", refs.get("revenue"), _mln(summary.get("revenue")), "money"),
        ("CAPEX, млн ₽", refs.get("capex"), _mln(summary.get("capex")), "money"),
        ("Полные расходы, млн ₽", refs.get("total_expenses"), _mln(summary.get("total_expenses") or summary.get("full_project_cost")), "money"),
        ("EBITDA, млн ₽", None, _mln(summary.get("ebitda")), "money"),
        ("Чистая прибыль, млн ₽", None, _mln(summary.get("net_profit")), "money"),
        ("Маржа", None, _num(summary.get("margin")), "percent"),
        ("NPV, млн ₽", None, _mln(summary.get("npv")), "money"),
        ("IRR equity", None, _num(summary.get("irr_equity")), "percent"),
        ("LLCR", refs.get("llcr"), _num(summary.get("llcr")), "multiple"),
        ("Пиковый долг, млн ₽", refs.get("peak_debt"), _mln(summary.get("peak_total_debt")), "money"),
        ("Продаваемая площадь, м²", refs.get("saleable"), _num(summary.get("monetizable_saleable_sqm")), "number"),
        ("Полная себестоимость, тыс. ₽/м²", None, _num(summary.get("full_cost_per_saleable_th")), "number"),
    ]
    row = 3
    for index, (label, formula_ref, value, kind) in enumerate(kpis):
        col = 0 if index < 6 else 3
        r = row + (index if index < 6 else index - 6)
        ws.write(r, col, label, formats["kpi_label"])
        fmt = formats[{"money": "kpi_money", "percent": "kpi_percent", "multiple": "kpi_multiple", "number": "kpi_number"}[kind]]
        if formula_ref:
            ws.write_formula(r, col + 1, f"={formula_ref}", fmt, value)
        else:
            ws.write_number(r, col + 1, value, fmt)
    dates = result.get("dates") or {}
    date_row = 10
    ws.merge_range(date_row, 0, date_row, 4, "Ключевые даты", formats["section"])
    ws.write_row(date_row + 1, 0, ["Старт проекта", "РнС", "Старт продаж", "РВЭ", "Режим"], formats["header"])
    for col, key in enumerate(("project_start", "permit", "sales_start", "rve")):
        parsed = _iso_date(dates.get(key))
        if parsed:
            ws.write_datetime(date_row + 2, col, parsed, formats["date"])
        else:
            ws.write(date_row + 2, col, "", formats["text"])
    ws.write(date_row + 2, 4, "Очередность" if bundle.get("mode") == "phased" else "Один этап", formats["text"])
    feasibility = None
    if hasattr(core, "_purchase_feasibility"):
        try:
            feasibility = core._purchase_feasibility(_num(req.inputs.get("purchase_price_mln")), _mln(summary.get("net_profit")), summary.get("llcr"), _num(summary.get("peak_total_debt")))
        except Exception:
            feasibility = None
    if feasibility:
        ws.merge_range(14, 0, 14, 4, "Инвестиционный вывод", formats["section"])
        ws.merge_range(15, 0, 17, 4, f"{feasibility.get('title', '')}\n{feasibility.get('text', '')}", formats["conclusion"])
    ws.merge_range(19, 0, 20, 4, "Экспорт содержит полный снимок текущего серверного расчёта: вводные, ТЭП, продажи, CAPEX, помесячный CF, долг, эскроу, ставки, налог и календарь. Изменение синих вводных в Excel само по себе не запускает серверный перерасчёт.", formats["note"])
    if cf_info.get("rows"):
        start_excel = cf_info["start"] + 1
        end_excel = cf_info["end"]
        chart = workbook.add_chart({"type": "line"})
        chart.add_series({"name": "Остаток ПФ", "categories": f"='Помесячный CF'!$A${start_excel}:$A${end_excel}", "values": f"='Помесячный CF'!$L${start_excel}:$L${end_excel}", "line": {"color": "#19324A", "width": 2.25}})
        chart.add_series({"name": "Эскроу", "categories": f"='Помесячный CF'!$A${start_excel}:$A${end_excel}", "values": f"='Помесячный CF'!$O${start_excel}:$O${end_excel}", "line": {"color": "#6B8E23", "width": 2.0}})
        chart.set_title({"name": "Динамика ПФ и эскроу"})
        chart.set_x_axis({"date_axis": True, "num_format": "mmm-yy"})
        chart.set_y_axis({"name": "млн ₽", "major_gridlines": {"visible": True}})
        chart.set_legend({"position": "bottom"})
        chart.set_size({"width": 720, "height": 360})
        ws.insert_chart("G4", chart)


def _build_workbook_bytes(core: Any, req: ExcelModelRequest, bundle: dict[str, Any], result: dict[str, Any], *, title_suffix: str = "", phase_meta: dict[str, Any] | None = None, include_phase_comparison: bool = False) -> bytes:
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({"title": f"DevelopAid — {_project_title(req)}{title_suffix}", "subject": "Финансовая модель девелоперского проекта", "author": "DevelopAid", "company": "DevelopAid", "comments": f"Экспорт текущего серверного расчёта DevelopAid {_RUNTIME_VERSION}"})
    formats = _formats(workbook)
    project_title = _project_title(req) + title_suffix
    workbook.add_worksheet("Сводка")
    _write_inputs_sheet(workbook, formats, core, req.inputs, project_title, phase_meta)
    tep_refs = _write_tep_sheet(workbook, formats, result, project_title)
    product_refs = _write_products_sheet(workbook, formats, result, project_title)
    capex_refs = _write_capex_sheet(workbook, formats, result, project_title)
    finance_refs = _write_finance_sheet(workbook, formats, result, project_title)
    cf_info = _write_cf_sheet(workbook, formats, result, project_title)
    tax_refs = _write_tax_sheet(workbook, formats, result, project_title)
    _write_calendar_sheet(workbook, formats, result, project_title)
    if include_phase_comparison:
        _write_phase_comparison(workbook, formats, bundle, project_title)
    refs: dict[str, str] = {}
    refs.update(tep_refs)
    refs.update(product_refs)
    refs.update(capex_refs)
    refs.update(finance_refs)
    refs.update(tax_refs)
    _write_summary_sheet(workbook, formats, core, result, bundle, req, project_title, refs, cf_info)
    workbook.close()
    return output.getvalue()


def _calculate_bundle(runtime: Any, req: ExcelModelRequest) -> dict[str, Any]:
    model_req = runtime.core.PhasedCalcRequest(inputs=copy.deepcopy(req.inputs), tep=copy.deepcopy(req.tep), rates=copy.deepcopy(req.rates), phasing=copy.deepcopy(req.phasing))
    return runtime.core.calculate_phased(model_req)


def _consolidated_bytes(runtime: Any, req: ExcelModelRequest) -> tuple[bytes, dict[str, Any]]:
    with _EXPORT_LOCK:
        bundle = _calculate_bundle(runtime, req)
        result = bundle.get("consolidated") or {}
        return _build_workbook_bytes(runtime.core, req, bundle, result, include_phase_comparison=bundle.get("mode") == "phased"), bundle


def _package_bytes(runtime: Any, req: ExcelModelRequest) -> tuple[bytes, dict[str, Any]]:
    with _EXPORT_LOCK:
        bundle = _calculate_bundle(runtime, req)
        if bundle.get("mode") != "phased" or not bundle.get("phases"):
            raise HTTPException(status_code=400, detail="Очередность не включена: пакет отдельных моделей не требуется.")
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("00_Консолидированная модель.xlsx", _build_workbook_bytes(runtime.core, req, bundle, bundle["consolidated"], include_phase_comparison=True))
            for index, phase in enumerate(bundle.get("phases") or [], 1):
                name = _safe_name(str(phase.get("name") or f"Очередь {index}"), f"Очередь {index}")
                phase_bundle = {"mode": "single", "consolidated": phase.get("result") or {}, "phases": [], "comparison": []}
                content = _build_workbook_bytes(runtime.core, req, phase_bundle, phase.get("result") or {}, title_suffix=f" · {name}", phase_meta=phase)
                archive.writestr(f"{index:02d}_{name}.xlsx", content)
        return package.getvalue(), bundle


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _patch_web_ui(runtime: Any) -> None:
    page = str(runtime.core.PAGE)
    if "function exportModelExcel(kind)" in page:
        return
    needle = "initializeApp();"
    if needle not in page:
        return
    script = r'''
function currentExcelModelPayload(){
 const meta=currentPdfReportPayload();
 return {inputs:inputs,tep:tep,rates:rates,phasing:phasing,project_name:String(meta.project_name||''),cadastral_numbers:meta.cadastral_numbers||[],source_label:String(meta.source_label||'')};
}
async function exportModelExcel(kind){
 if(kind==='package'&&!(phasing&&phasing.enabled&&Number(phasing.phase_count||0)>1)){alert('Очередность не включена: отдельный пакет моделей не требуется.');return;}
 const endpoint=kind==='package'?'/model/excel/package':'/model/excel/consolidated';
 const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(currentExcelModelPayload())});
 if(!response.ok){let detail='Не удалось сформировать Excel-модель';try{const data=await response.json();detail=data.detail||detail}catch(e){}alert(detail);return;}
 const blob=await response.blob();const disposition=response.headers.get('Content-Disposition')||'';const utf=disposition.match(/filename\*=UTF-8''([^;]+)/i);const fallback=kind==='package'?'DevelopAid_Модели_по_очередям.zip':'DevelopAid_Финансовая_модель.xlsx';const filename=utf?decodeURIComponent(utf[1]):fallback;const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500);
}
function installExcelExportButtons(){
 if(document.getElementById('exportExcelConsolidated'))return;
 const buttons=Array.from(document.querySelectorAll('button'));const pdfButton=buttons.find(btn=>String(btn.getAttribute('onclick')||'').includes('exportReportPdf')||/PDF/i.test(String(btn.textContent||'')));if(!pdfButton)return;
 const holder=document.createElement('div');holder.className='excel-export-actions';holder.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px';
 const consolidated=document.createElement('button');consolidated.id='exportExcelConsolidated';consolidated.className=pdfButton.className||'btn';consolidated.textContent='Скачать Excel-модель';consolidated.onclick=()=>exportModelExcel('consolidated');
 const pack=document.createElement('button');pack.id='exportExcelPackage';pack.className=pdfButton.className||'btn';pack.textContent='Пакет моделей по очередям (ZIP)';pack.onclick=()=>exportModelExcel('package');
 holder.appendChild(consolidated);holder.appendChild(pack);pdfButton.parentNode.insertBefore(holder,pdfButton.nextSibling);
}
setTimeout(installExcelExportButtons,600);
'''
    runtime.core.PAGE = page.replace(needle, script + "\n" + needle, 1)


def _send_excel_controls(runtime: Any, req: Any) -> None:
    session = str(getattr(req, "session", "") or "")
    summary = getattr(req, "summary", None)
    if not session or not isinstance(summary, dict):
        return
    try:
        session_data = runtime.core._telegram_verify_session(session)
        chat_id = int(session_data.get("chat_id") or 0)
    except Exception:
        return
    report_payload = summary.get("report_payload") or {}
    phasing = report_payload.get("phasing") or {}
    rows = [[{"text": "Скачать консолидированную Excel-модель", "callback_data": "excel_consolidated"}]]
    if phasing.get("enabled") and int(phasing.get("phase_count") or len(phasing.get("phases") or []) or 1) > 1:
        rows.append([{"text": "Пакет моделей по очередям", "callback_data": "excel_package"}])
    runtime._send_message(chat_id, "<b>Excel-модель DevelopAid</b>\n\nКонсолидированная книга содержит вводные, ТЭП, продажи, CAPEX, помесячный CF, долг, эскроу, ставки, налог и календарь. При включённой очередности доступен ZIP с отдельной моделью каждой очереди.", reply_markup={"inline_keyboard": rows})


def _context_request(runtime: Any, chat_id: int) -> ExcelModelRequest | None:
    with runtime._STATE_LOCK:
        session = runtime._PLATON_LAST_SESSION.get(chat_id, "")
        context = copy.deepcopy(runtime._PLATON_CONTEXT_BY_SESSION.get(session) or {})
    if not context:
        return None
    session_data = context.get("session_data") or {}
    return ExcelModelRequest(inputs=context.get("inputs") or {}, tep=context.get("tep") or {}, rates=context.get("rates") or [], phasing=context.get("phasing") or {}, project_name=str(((context.get("inputs") or {}).get("_manual_tep_import") or {}).get("project_name") or ""), cadastral_numbers=session_data.get("cad") or [], source_label="Текущий расчёт DevelopAid")


def _send_excel_file_to_telegram(runtime: Any, chat_id: int, action: str) -> None:
    req = _context_request(runtime, chat_id)
    if req is None:
        runtime._send_message(chat_id, "Контекст модели не найден. Выполните новый расчёт и отправьте результат в Telegram.")
        return
    try:
        runtime.core._telegram_api("sendChatAction", {"chat_id": chat_id, "action": "upload_document"})
    except Exception:
        pass
    try:
        project = _project_title(req)
        if action == "excel_package":
            content, _ = _package_bytes(runtime, req)
            filename = f"DevelopAid_{_safe_name(project)}_модели_по_очередям.zip"
            caption = "<b>Пакет Excel-моделей DevelopAid</b> · консолидированная книга и отдельные книги активных очередей"
            content_type = "application/zip"
        else:
            content, _ = _consolidated_bytes(runtime, req)
            filename = f"DevelopAid_{_safe_name(project)}_финансовая_модель.xlsx"
            caption = "<b>Консолидированная Excel-модель DevelopAid</b> · актуальный расчёт проекта"
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        runtime.core._telegram_send_document_bytes(chat_id, content, filename, caption, content_type)
    except HTTPException as exc:
        runtime._send_message(chat_id, html.escape(str(exc.detail)))
    except Exception as exc:
        runtime._send_message(chat_id, "Не удалось сформировать Excel-модель: " + html.escape(str(exc)))


def _patch_telegram_controls(runtime: Any) -> None:
    route = next((item for item in runtime.app.routes if getattr(item, "path", None) == "/telegram/result" and "POST" in (getattr(item, "methods", None) or set())), None)
    if route is not None:
        original = getattr(route, "endpoint", None)
        if original is not None and not getattr(original, "_developaid_excel_controls", False):
            def wrapped(req: Any) -> Any:
                result = original(req)
                if hasattr(result, "__await__"):
                    async def finish() -> Any:
                        resolved = await result
                        _send_excel_controls(runtime, req)
                        return resolved
                    return finish()
                _send_excel_controls(runtime, req)
                return result
            wrapped._developaid_excel_controls = True
            wrapped.__name__ = getattr(original, "__name__", "telegram_result")
            wrapped.__doc__ = getattr(original, "__doc__", None)
            route.endpoint = wrapped
            if getattr(route, "dependant", None) is not None:
                route.dependant.call = wrapped
    original_update = runtime.core._telegram_handle_update
    if getattr(original_update, "_developaid_excel_callbacks", False):
        return
    def handle_update(update: dict[str, Any]) -> None:
        query = update.get("callback_query") if isinstance(update, dict) else None
        data = str((query or {}).get("data") or "")
        if data not in {"excel_consolidated", "excel_package"}:
            return original_update(update)
        runtime._answer_callback(query or {})
        message = (query or {}).get("message") or {}
        sender = (query or {}).get("from") or {}
        chat_id = int(((message.get("chat") or {}).get("id")) or sender.get("id") or 0)
        if chat_id:
            _send_excel_file_to_telegram(runtime, chat_id, data)
    handle_update._developaid_excel_callbacks = True
    runtime.core._telegram_handle_update = handle_update


def apply(runtime: Any) -> None:
    runtime._RUNTIME_VERSION = _RUNTIME_VERSION
    runtime.app.version = _RUNTIME_VERSION
    _patch_web_ui(runtime)

    @runtime.app.post("/model/excel/consolidated")
    def export_consolidated(req: ExcelModelRequest) -> Response:
        content, _ = _consolidated_bytes(runtime, req)
        filename = f"DevelopAid_{_safe_name(_project_title(req))}_финансовая_модель.xlsx"
        return Response(content=content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": _content_disposition(filename)})

    @runtime.app.post("/model/excel/package")
    def export_package(req: ExcelModelRequest) -> Response:
        content, _ = _package_bytes(runtime, req)
        filename = f"DevelopAid_{_safe_name(_project_title(req))}_модели_по_очередям.zip"
        return Response(content=content, media_type="application/zip", headers={"Content-Disposition": _content_disposition(filename)})

    _patch_telegram_controls(runtime)
