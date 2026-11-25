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
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter

from developaid_contract_rds import LAYOUT, FIELDS
from developaid_contract_fact import _money

SCHEMA = "contract-rds-plan-fact-export-v1"
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
    comparison = result.get("rds_comparison")
    if isinstance(comparison, dict) and not comparison.get('available'):
        return {'available': False, 'detail': comparison.get('detail') or 'Для выгрузки нужна действующая РДС.'}
    if not isinstance(comparison, dict) or not isinstance(comparison.get("rows"), list):
        return {"available": False, "detail": "Таблица план-факта ещё не подготовлена. Откройте карточку заново."}
    if comparison.get("cut") != cut or result.get("contract_id") != contract_id:
        return {"available": False, "detail": "Таблица не соответствует договору или срезу. Откройте карточку заново."}
    rows = comparison["rows"]
    if len(rows) > MAX_ROWS:
        return {"available": False, "detail": "Таблица слишком большая для выгрузки в один файл."}
    documents = [{"sha256": d.get("sha256"), "title": d.get("title")}
                 for d in result.get("documents") or []]
    context = {"project": project, "cut": cut, "contract_id": contract_id,
               "label": label, "source_documents": documents}
    if result.get("source_correction"):
        context["source_correction"] = result["source_correction"]
    revision = _sha({**context, 'rds': comparison,
                     'canonical': {key: result.get(key) for key in ('documents', 'plan', 'fact', 'comparison')}})
    return {"schema": SCHEMA, "layout": LAYOUT, "rows_count": len(rows), "scope": "all_active_rds",
            "available": True, **context, "revision": revision,
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
    if selected_tokens != tokens:
        raise ExportProblem("Выгрузка содержит всю действующую РДС. Откройте карточку заново перед выгрузкой.")
    return meta, cached["rds_comparison"], cached["rds_comparison"]["rows"]


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
    """One original RDS position per row; qualifications remain in cell comments."""
    if filter != 'all' or query.strip() or len(rows) > MAX_ROWS or rows != comparison.get('rows') or \
            meta.get('layout') != LAYOUT or comparison.get('layout') != LAYOUT:
        raise ExportProblem('Excel содержит всю действующую РДС; фильтры таблицы ГПР к нему не применяются.')
    book = Workbook()
    sheet = book.active
    sheet.title = 'РДС — план и факт'
    book.properties.creator = 'DevelopAid'
    labels = ('№', 'Работа из РДС', 'Ед. изм.', 'Начало ГПР', 'Конец ГПР', 'План, объём',
              'Факт, объём', 'Отклонение, объём', 'План, ₽', 'Факт, ₽', 'Отклонение, ₽', 'Отклонение, дни')
    label = meta.get('label') or {}

    def put(row, column, value, comment=''):
        cell = sheet.cell(row, column, _text(value) if isinstance(value, str) else value)
        if isinstance(cell.value, str):
            cell.data_type = 's'
        cell.alignment = Alignment(vertical='top', wrap_text=True)
        cell.font = Font(name='Calibri', size=10)
        if comment:
            cell.comment = Comment(_text(comment), 'DevelopAid')
        return cell

    for row, text in enumerate((
        'РДС: план и факт',
        'Проект: '+meta['project']+' · Договор: '+(label.get('contract') or 'номер не подтверждён')+
            (' · '+label['contractor'] if label.get('contractor') else ''),
        'Дата среза: '+_date(meta['cut']).strftime('%d.%m.%Y')+' · Факт: '+
            {'ks2': 'КС-2', 'ks6a': 'КС-6а'}.get(comparison.get('source'), 'источник не определён')),
        1):
        put(row, 1, text)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
    sheet['A1'].font = Font(name='Calibri', size=15, bold=True)
    sheet.row_dimensions[2].height = 30
    sheet['A3'].comment = Comment(_text('\n'.join(filter_none([
        comparison.get('source_note'), comparison.get('confirmation', {}).get('message'),
        'Пустая ячейка означает неизвестное значение; подтверждённый ноль записан числом 0.',
        'Файл содержит все позиции действующей РДС и не зависит от фильтров таблицы ГПР.',
        *comparison.get('data_gaps', [])]))), 'DevelopAid')
    for first, last, title in ((1, 3, 'Работы РДС'), (4, 5, 'Сроки из ГПР'),
                               (6, 8, 'Объём работ в единице строки'), (9, 11, 'Стоимость работ и поставки'),
                               (12, 12, 'Отклонение')):
        put(5, first, title)
        if first != last:
            sheet.merge_cells(start_row=5, start_column=first, end_row=5, end_column=last)
    for column, text in enumerate(labels, 1):
        put(6, column, text)
    for row in (5, 6):
        for cell in sheet[row]:
            cell.fill = PatternFill('solid', fgColor='1F4E78')
            cell.font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    sheet.row_dimensions[5].height = 26
    sheet.row_dimensions[6].height = 42
    sheet['B6'].comment = Comment(_text('Действующая РДС: '+comparison.get('estimate_title', '')+
                                      '. Позиции и их порядок сохранены из этой редакции.'), 'DevelopAid')
    date_comment = comparison.get('date_assumption') or 'Даты взяты из отдельной принятой строки ГПР.'
    if comparison.get('legal_deadline'):
        date_comment += ' Срок договора: '+_date(comparison['legal_deadline']).strftime('%d.%m.%Y')+'. Это отдельный юридический срок.'
    for column in (4, 5):
        sheet.cell(6, column).comment = Comment(_text(date_comment), 'DevelopAid')
    plan_comment = comparison.get('plan_assumption') or ''
    if comparison.get('remaining_start'):
        plan_comment += ' Учёт оставшихся работ с '+_date(comparison['remaining_start']).strftime('%d.%m.%Y')+'.'
        if comparison.get('remaining_source'):
            plan_comment += ' Источник: '+comparison['remaining_source']+'.'
    sheet['F6'].comment = Comment(_text(plan_comment), 'DevelopAid')
    sheet['G6'].comment = Comment('Физический объём выполненной работы в единице РДС. Количество поставленного материала сюда не прибавляется и из стоимости не выводится.', 'DevelopAid')
    sheet['I6'].comment = Comment(_text(plan_comment), 'DevelopAid')
    evidence = comparison.get('act_evidence') or {}
    fact_comment = 'Полная стоимость работ и поставки по принятому расчёту РДС. Это не оплаты. '+(comparison.get('fact_assumption') or '')
    if evidence.get('total') is not None:
        fact_comment += ' Итоги загруженных актов по самим документам: '+_money(_number(evidence['total']))+'. Это отдельная сверка, а не факт каждой позиции по РДС.'
    sheet['J6'].comment = Comment(_text(fact_comment), 'DevelopAid')
    sheet['L6'].comment = Comment('Опережение минус отставание по принятому расчёту ГПР: плюс — впереди, минус — позади. Это не дни юридической просрочки. Без отдельного показателя позиции ячейка пустая.', 'DevelopAid')
    headings = {}
    for heading in comparison.get('headings') or []:
        headings.setdefault(heading['before_position'], []).append(heading)
    excel_row = 6
    for ordinal, source in enumerate(rows):
        for heading in headings.get(ordinal, []):
            excel_row += 1
            put(excel_row, 1, heading.get('number') or '')
            heading_comment = ''
            if heading.get('quantity') is not None and heading.get('unit'):
                heading_comment = 'Объём по заголовку РДС: '+format(_number(heading['quantity']), 'g').replace('.', ',')+' '+heading['unit']+'. Объёмы отдельных операций в него не складываются.'
            put(excel_row, 2, heading.get('name') or '', heading_comment)
            for cell in sheet[excel_row]:
                cell.fill = PatternFill('solid', fgColor='E8EFF7')
                cell.font = Font(name='Calibri', size=10, bold=True)
            sheet.row_dimensions[excel_row].height = 28
        excel_row += 1
        for column, field in enumerate(FIELDS, 1):
            value = source.get(field)
            if column in (4, 5):
                value = _date(value)
            elif column >= 6:
                value = _number(value)
            comment = (source.get('comments') or {}).get(field) or ''
            if column in (4, 5) and value is not None:
                comment = (comment+' '+date_comment).strip()
            cell = put(excel_row, column, value, comment)
            if column in (4, 5):
                cell.number_format = 'dd.mm.yyyy'
            elif column in (9, 10, 11):
                cell.number_format = '#,##0.00;[Red]-#,##0.00;0.00'
            elif column in (6, 7, 8):
                cell.number_format = '#,##0.###;[Red]-#,##0.###;0'
            elif column == 12:
                cell.number_format = '+0;[Red]-0;0'
        sheet.row_dimensions[excel_row].height = min(78, max(30, 14*(len(str(source.get('name') or ''))//48+1)))
    widths = (9, 61, 12, 14, 14, 15, 15, 16, 19, 19, 19, 15)
    for column, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.freeze_panes = 'D7'
    sheet.auto_filter.ref = f'A6:L{excel_row}'
    sheet.print_title_rows = '5:6'
    sheet.print_options.horizontalCentered = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_area = f'A1:L{excel_row}'
    sheet.oddFooter.center.text = 'Страница &P из &N'
    output = io.BytesIO()
    book.save(output)
    raw = output.getvalue()
    if len(raw) > MAX_XLSX_BYTES:
        raise ExportProblem('Файл слишком большой для выгрузки.')
    return raw


def filter_none(values):
    return [value for value in values if value]
