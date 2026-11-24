"""XLSX presentation of an already completed, owner-bound contract card.

No source readers, plan/fact calculations, client-provided amounts or formulas.
Row tokens bind a canonical snapshot revision, ordinal and row digest.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill

SCHEMA = "contract-comparison-export-v1"
MAX_ROWS = 10_000
MAX_XLSX_BYTES = 8 * 1024 * 1024
FILTERS = {"all": "Все работы и поставки", "behind": "Отстают от плана", "ahead": "Опережают план",
           "overdue": "Срок прошёл", "done": "Завершены", "unknown": "Нужны данные"}


class ExportProblem(ValueError):
    def __init__(self, detail: str, status: int = 409):
        super().__init__(detail)
        self.status = status


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode()


def _sha(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def bind_snapshot(project: str, cut: str, contract_id: str, result: dict, label: dict) -> dict:
    """Called by the existing documents worker, after JSON encoding its result."""
    comparison = result.get("comparison")
    if not isinstance(comparison, dict) or not isinstance(comparison.get("lines"), list):
        return {"available": False, "detail": "Таблица план-факта ещё не подготовлена. Откройте карточку заново."}
    if comparison.get("cut") != cut or result.get("contract_id") != contract_id:
        return {"available": False, "detail": "Таблица не соответствует договору или срезу. Откройте карточку заново."}
    rows = comparison["lines"]
    if len(rows) > MAX_ROWS:
        return {"available": False, "detail": "Таблица слишком большая для выгрузки в один файл."}
    documents = [{"sha256": d.get("sha256"), "title": d.get("title")}
                 for d in result.get("documents") or []]
    context = {"project": project, "cut": cut, "contract_id": contract_id,
               "label": label, "source_documents": documents}
    if result.get("source_correction"):
        context["source_correction"] = result["source_correction"]
    revision = _sha({**context, "comparison": comparison})
    return {"schema": SCHEMA, "available": True, **context, "revision": revision,
            "row_tokens": [_sha([revision, index, _sha(row)]) for index, row in enumerate(rows)]}


def select_snapshot(cached: dict, project: str, cut: str, contract_id: str,
                    revision: str, selected_tokens: list[str]) -> tuple[dict, dict, list[dict]]:
    """Resolve selections only against the saved server DTO; never rebuild it."""
    if cached.get("pending"):
        raise ExportProblem("Карточка ещё готовится. Дождитесь её загрузки.")
    meta = cached.get("comparison_export") or {}
    if cached.get("ok") is not True or not meta.get("available"):
        raise ExportProblem(meta.get("detail") or "Таблица недоступна. Откройте карточку договора заново.")
    if (meta.get("project"), meta.get("cut"), meta.get("contract_id")) != (project, cut, contract_id):
        raise ExportProblem("Карточка относится к другому договору или срезу. Откройте её заново.")
    expected = bind_snapshot(project, cut, contract_id, cached, meta.get("label") or {})
    if meta != expected or revision != meta.get("revision"):
        raise ExportProblem("Версия таблицы изменилась. Откройте карточку заново перед выгрузкой.")
    tokens = meta["row_tokens"]
    chosen = set(selected_tokens)
    if len(chosen) != len(selected_tokens) or not chosen <= set(tokens):
        raise ExportProblem("Выбранные строки не относятся к этой версии таблицы.")
    rows = cached["comparison"]["lines"]
    return meta, cached["comparison"], [row for token, row in zip(tokens, rows) if token in chosen]


def require_current_sources(meta):
    correction = meta.get('source_correction')
    if not correction:
        return
    import developaid_contract_ownership as ownership
    try:
        with ownership.read_scope(meta['project'], meta['cut']) as context:
            context.adopt({'logical_ownership': {'read_guard': correction['input_guard']}})
    except (ownership.OwnershipProblem, KeyError):
        raise ExportProblem('Источники карточки изменились. Откройте её заново перед выгрузкой.') from None


def _text(value) -> str:
    text = "" if value is None else str(value)
    if len(text) > 32767 or ILLEGAL_CHARACTERS_RE.search(text):
        raise ExportProblem("Один из текстов таблицы нельзя безопасно записать в Excel.")
    return text


def _number(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ExportProblem("В таблице есть неподтверждённое числовое значение. Обновите карточку.")
    return value


def _date(value):
    if value in (None, ""):
        return None
    try:
        if type(value) is not str or dt.date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ExportProblem("В таблице есть непрочитанная дата. Обновите карточку.") from None


def _percent(value) -> str:
    return "" if value is None else f"{_number(value) * 100:.1f}%"


def workbook(meta: dict, comparison: dict, rows: list[dict], *, query: str = "", filter: str = "all") -> bytes:
    """Seven visible columns, native numbers/dates and adjacent visible qualifications."""
    if filter not in FILTERS or len(rows) > MAX_ROWS:
        raise ExportProblem("Не удалось определить строки для выгрузки.")
    book = Workbook()
    sheet = book.active
    sheet.title = "Накопленный план-факт"
    book.properties.creator = "DevelopAid"
    row_number = 0

    def append(values):
        nonlocal row_number
        values = [_text(value) if isinstance(value, str) else value for value in values]
        sheet.append(values)
        row_number += 1
        cells = [sheet.cell(row_number, column) for column in range(1, 8)]
        for cell in cells:
            if isinstance(cell.value, str):
                cell.value = _text(cell.value)
                cell.data_type = "s"  # Source strings, including = + - @, are never formulas.
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if isinstance(cell.value, dt.date):
                cell.number_format = "dd.mm.yyyy"
        return cells

    def note(text):
        append([_text(text)])
        sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=7)

    label = meta.get("label") or {}
    note("Накопленные план и факт по работам и поставкам договора")
    note("Проект: " + meta["project"])
    note("Договор: " + (label.get("contract") or "номер не подтверждён") +
         (" · " + label["contractor"] if label.get("contractor") else ""))
    append(["Дата среза", _date(meta["cut"])])
    note(f"Выгружено строк: {len(rows)} из {len(comparison['lines'])}. Фильтр: {FILTERS[filter]}." +
         (" Поиск: " + query if query else ""))
    edition = comparison.get("edition") or {}
    source = {"ks2": "КС-2 по периодам выполнения", "ks6a": "накопительная КС-6а"}.get(
        comparison.get("source"), "источник факта пока не определён")
    note("Источник факта: " + source + (". Редакция: " + edition["title"] if edition.get("title") else ""))
    if edition.get("date"):
        append(["Дата редакции", _date(edition["date"])])
    if edition.get('start'):
        append(['Начало учёта оставшихся работ', _date(edition['start'])])
        if (edition.get('start_source') or {}).get('title'):
            note('Источник начала учёта: ' + _text(edition['start_source']['title']))
    for key, caption in [("estimate", "Расчёт договорной стоимости"), ("schedule", "ГПР")]:
        if edition.get(key):
            note(caption + ": " + _text(edition[key]))
    coverage = comparison.get("coverage") or {}
    if coverage.get("schedule_sha256"):
        note("Версия исходного ГПР: " + _text(coverage["schedule_sha256"]))
    if (comparison.get("coverage") or {}).get("partial"):
        note("Сопоставление не охватывает весь договор.")
    if comparison.get("preliminary"):
        note("Предварительно: у части актов использована дата составления.")
    confirmation = comparison.get('confirmation') or {}
    if confirmation.get('message'):
        note(confirmation['message'])
    for gap in comparison.get('data_gaps') or []:
        note(gap)
    for value in [comparison.get("reason"), comparison.get("source_note"), comparison.get("plan_assumption"),
                  (comparison.get("schedule_source") or {}).get("assumption"), comparison.get("assumption"),
                  comparison.get("weights")]:
        if value:
            note(value)
    total = comparison.get('total') or {}
    if total.get('readiness') is not None:
        note('Общая готовность работ и поставки в расчёте: ' + _percent(total['readiness']))
    for key, label in [('work','Работы'),('material','Поставка материалов')]:
        component = (comparison.get('components') or {}).get(key)
        if component:
            note(label + ': ' + ('готовность ' + _percent(component['readiness'])
                 if component.get('readiness') is not None else 'готовность неизвестна' if component.get('amount') != 0
                 else 'в расчёте нет этого компонента') + '. Учтённый вклад: ' +
                 (str(_number(component['counted'])) + ' ₽' if component.get('counted') is not None else 'неизвестен'))
    note("Всего по договору — полный объём позиции по действующей редакции договора в единицах строки.")
    note("Пустая числовая ячейка означает неизвестное значение, а не ноль. "
         "Прогноз относится к сопоставленным работам и поставкам и не меняет срок ввода проекта.")
    if meta.get('source_correction'):
        correction = meta['source_correction']
        note('Источники договора уточнены владельцем. Версия выбора: ' + correction['decision_id'])
        note('Источник выполнения: ' + correction['roles']['execution_raw_id'] +
             '. Карточка документов: ' + correction['roles']['documents_raw_id'])
        if correction.get('warning'):
            note(correction['warning'])
    note("Версия таблицы: " + meta["revision"])
    append(["Работа или поставка / единица", "Всего по договору", "План на дату", "Факт", "Отклонение", "Срок строки", "Прогноз окончания"])
    header = row_number
    for cell in sheet[header]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    if not rows:
        note("По выбранному фильтру строк нет." if comparison["lines"] else
             comparison.get("reason") or "Работы и поставки для сравнения не определены. Выполнение неизвестно.")
    sections = any(row.get('section') for row in rows)
    previous_section = None
    for row in rows:
        section = row.get('section') or ''
        if sections and section != previous_section:
            note(section or 'Раздел в ГПР не указан')
            sheet.cell(row_number, 1).font = Font(bold=True, color='1F4E78')
            sheet.cell(row_number, 1).fill = PatternFill('solid', fgColor='E8EFF7')
        previous_section = section
        name = "\n".join(_text(v) for v in [row.get("name"), row.get("context"),
                         " · ".join(_text(v) for v in [row.get("display_code") or row.get("code"), row.get("unit")] if v)] if v)
        scope = row.get('physical_scope')
        if scope:
            origin = 'по КС-6а' if scope.get('source_kind') == 'ks6a' else 'по расчёту договора'
            name += ('\nПолный объём конструкции: ' + str(_number(scope['quantity'])) +
                     ' ' + _text(scope.get('unit')) + ' · ' + origin
                     if scope.get('quantity') is not None else '\nПолный объём конструкции в этой редакции не указан.')
            name += '\nВыполнение — по отдельным операциям.'
        cells = append([name, _number(row.get("contract_total")), _number(row.get("planned")), _number(row.get("fact")), _number(row.get("deviation")),
                        _date(row.get("due")), _date(row.get("finished") or row.get("forecast_finish"))])
        for cell in cells[1:5]:
            cell.number_format = '#,##0.00" ₽"' if row.get("basis") == "money" else "#,##0.###"
        movement = (f"Отставание: {row['lag_days']} дн." if row.get("lag_days", 0) else
                    f"Опережение: {row['ahead_days']} дн." if row.get("ahead_days", 0) else
                    {"done": "Поставка завершена." if row.get("component") == "material" else "Работа завершена.", "on_plan": "По плану."}.get(row.get("state"), ""))
        remarks = ["\n".join(_text(v) for v in [row.get("money_fallback"), row.get("reason"),
                   "Готовность: " + _percent(row["readiness"]) if row.get("readiness") is not None else ""] if v),
                   "Полный объём неизвестен." if row.get("contract_total") is None else "",
                   "План неизвестен." if row.get("planned") is None else "",
                   ("Факт неизвестен. " if row.get("fact") is None else "") +
                   ("Выполнение плана: " + _percent(row["plan_done"]) if row.get("plan_done") is not None else ""),
                   ("Отклонение неизвестно. " if row.get("deviation") is None else "") + movement +
                   (" От плана: " + _percent(row["percent"]) if row.get("percent") is not None else ""),
                   "Срок неизвестен." if not row.get("due") else
                   f"Просрочка: {row['overdue_days']} дн." if row.get("overdue_days", 0) else "",
                   ("По периоду КС, завершено." +
                    (f" Позже срока на {row['late_days']} дн." if (row.get("late_days") or 0) > 0 else ""))
                   if row.get("finished") else "" if row.get("forecast_finish") else "Прогноз не рассчитан."]
        if any(remarks):
            for cell in append(remarks):
                cell.font = Font(size=10, color="526579")
    for column, width in zip("ABCDEFG", [48, 22, 22, 24, 26, 23, 30]):
        sheet.column_dimensions[column].width = width
    sheet.freeze_panes = f"B{header + 1}"
    sheet.print_title_rows = f"{header}:{header}"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.sheet_view.showGridLines = False
    target = io.BytesIO()
    book.save(target)
    raw = target.getvalue()
    if len(raw) > MAX_XLSX_BYTES:
        raise ExportProblem("Файл слишком большой. Сократите число показанных работ.")
    return raw
