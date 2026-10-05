"""Лист книги «Нежильё — стратегия»: результат движка для ТЦ и офисов вне ДДУ.

Формулы шаблона считают отдельно стоящий объект продажей по ДДУ с эскроу.
Прямую продажу без эскроу и доходный метод (аренда, NOI, выход, свой кредит
объекта) считает движок (`developaid_nonres_strategy`), и в книгу приходит
его результат — значениями, с явной пометкой «СЧИТАЕТ ДВИЖОК». Лист не
притворяется расчётом: ни одна формула книги его не читает, и об этом сказано
на нём самом и в списке проблем сборки.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape as _xml_escape

SHEET = "Нежильё — стратегия"
SHEET_PATH = "xl/worksheets/sheetNonresStrategy.xml"
REL_ID = "RidNonresStrategy0001"
SHEET_ID = 903

_NS = 'xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Помесячные ряды движка: поле месячной строки финансирования → подпись.
MONTHLY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("nonres_revenue", "Поступления объекта (ДКП / аренда / выход / оценка), ₽"),
    ("nonres_costs", "Расходы объекта (продажи, OPEX, налог на имущество, выход), ₽"),
    ("nonres_vat_paid", "НДС объекта к уплате (− возмещение), ₽"),
    ("nonres_loan_draw", "Кредит объекта — выборка, ₽"),
    ("nonres_loan_interest", "Кредит объекта — проценты начисленные, ₽"),
    ("nonres_loan_fee", "Кредит объекта — комиссия, ₽"),
    ("nonres_loan_repayment", "Кредит объекта — погашение, ₽"),
    ("nonres_loan_balance", "Кредит объекта — остаток, ₽"),
    ("nonres_cash_to_equity", "Деньги объекта собственнику (без CAPEX), ₽"),
)

NOTE = ("СЧИТАЕТ ДВИЖОК · в книгу приходит результат. Формулы листов «ОБЪЕКТЫ», "
        "CF и «ОТЧЕТ» считают эти объекты продажей по ДДУ с эскроу; стратегию "
        "реализации (прямая продажа без эскроу, доходный метод, свой кредит "
        "объекта) они не моделируют, поэтому итоги «ОТЧЕТА» и сверка «ПРОВЕРКИ» "
        "с движком по этим объектам расходятся. Авторитетный расчёт — отчёт "
        "DevelopAid; числа ниже — его.")


def _col(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _text(coord: str, value: Any) -> str:
    return (f'<x:c r="{coord}" t="inlineStr"><x:is><x:t xml:space="preserve">'
            f'{_xml_escape(str(value))}</x:t></x:is></x:c>')


def _number(coord: str, value: Any) -> str:
    return f'<x:c r="{coord}"><x:v>{repr(float(value or 0.0))}</x:v></x:c>'


def _row(number: int, cells: list[str]) -> str:
    return f'<x:row r="{number}">' + "".join(cells) + "</x:row>"


def _shown(row: dict[str, Any]) -> tuple[str, Any]:
    unit, value = row.get("unit"), row.get("value")
    if unit in ("rub", "pct"):
        return "number", float(value or 0.0)
    if unit == "date":
        return "text", ".".join(reversed(str(value or "—")[:7].split("-")))
    return "text", value if value not in (None, "") else "—"


def build_sheet(report: list[dict[str, Any]], monthly: list[dict[str, Any]]) -> str:
    """XML листа: пометка, таблица каждого объекта, помесячные ряды."""
    rows: list[str] = []
    n = 1
    rows.append(_row(n, [_text(f"A{n}", SHEET)]))
    n += 1
    rows.append(_row(n, [_text(f"A{n}", NOTE)]))
    n += 2
    for item in report:
        rows.append(_row(n, [_text(f"A{n}", item.get("title") or item.get("key")),
                             _text(f"B{n}", "₽ / доля / дата")]))
        n += 1
        for line in item.get("rows") or []:
            kind, value = _shown(line)
            cell = _number(f"B{n}", value) if kind == "number" else _text(f"B{n}", value)
            rows.append(_row(n, [_text(f"A{n}", line.get("label") or ""), cell]))
            n += 1
        for warning in item.get("warnings") or []:
            rows.append(_row(n, [_text(f"A{n}", warning)]))
            n += 1
        n += 1
    rows.append(_row(n, [_text(f"A{n}", "Помесячно — все объекты вне ДДУ вместе")]))
    n += 1
    rows.append(_row(n, [_text(f"A{n}", "Месяц")]
                     + [_text(f"{_col(i + 1)}{n}", label)
                        for i, (_, label) in enumerate(MONTHLY_COLUMNS)]))
    n += 1
    for line in monthly:
        rows.append(_row(n, [_text(f"A{n}", str(line.get("month") or "")[:7])]
                         + [_number(f"{_col(i + 1)}{n}", line.get(key))
                            for i, (key, _) in enumerate(MONTHLY_COLUMNS)]))
        n += 1
    return ('<?xml version="1.0" encoding="utf-8"?>'
            f'<x:worksheet {_NS}><x:sheetPr><x:tabColor rgb="FFB45309" /></x:sheetPr>'
            '<x:sheetViews><x:sheetView workbookViewId="0" /></x:sheetViews>'
            '<x:sheetFormatPr defaultRowHeight="15" />'
            '<x:cols><x:col min="1" max="1" width="56" customWidth="1" />'
            f'<x:col min="2" max="{len(MONTHLY_COLUMNS) + 1}" width="22" customWidth="1" /></x:cols>'
            f'<x:sheetData>{"".join(rows)}</x:sheetData></x:worksheet>')


def workbook_with_sheet(workbook: str) -> str:
    if f'name="{SHEET}"' in workbook:
        return workbook
    sheet = f'<x:sheet name="{SHEET}" sheetId="{SHEET_ID}" r:id="{REL_ID}" {_R_NS} />'
    return workbook.replace("</x:sheets>", sheet + "</x:sheets>", 1)


def rels_with_sheet(rels: str) -> str:
    link = (f'<Relationship Type="{_REL_NS}/worksheet" Target="/{SHEET_PATH}" '
            f'Id="{REL_ID}" />')
    return rels.replace("</Relationships>", link + "</Relationships>", 1)


def types_with_sheet(types: str) -> str:
    override = (f'<Override PartName="/{SHEET_PATH}" ContentType='
                '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml" />')
    return types.replace("</Types>", override + "</Types>", 1)
