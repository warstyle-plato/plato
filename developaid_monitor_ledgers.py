"""Bounded, read-only cumulative work ledgers and immutable private snapshots.

This reader imports evidence; it does not change GPR facts, deadlines, payments
or contract rights. Workbook formulas and macros are never executed. Annual
ledger amounts are explicitly distinct from whole-contract amounts.
"""
from __future__ import annotations

import calendar
import contextlib
from collections import OrderedDict
import datetime as dt
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import threading
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

import developaid_monitor as monitor

MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
PARSER_SCHEMA = 4
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 100
MAX_SHEETS = 60
MAX_ROWS = 20_000
MAX_COLUMNS = 160
MAX_CELLS = 1_000_000
MAX_RATIO = 1_000
MAX_ITEMS = 20_000
MAX_PERIOD_VALUES = 100_000
MAX_PARSED_BYTES = 24 * 1024 * 1024
MAX_ISSUES = 100
MAX_TEXT_CELL_CHARS = 20_000
MAX_MATERIALIZED_TEXT_BYTES = 16 * 1024 * 1024
SUPPORTED = {'.xlsx', '.xlsm', '.xls'}
# Kept distinct from an actually empty cell; this is never evaluated.
_UNCACHED_FORMULA = '=__uncached_formula__'
_PARSE_CACHE = OrderedDict()
_PARSE_CACHE_LOCK = threading.Lock()
_PARSE_CACHE_ENTRIES = 2
_PARSE_CACHE_BYTES = 4 * 1024 * 1024


class _SheetRows(list):
    """Transient workbook structure; source formulas are evidence, never run."""

    def __init__(self, *, header_merges=()):
        super().__init__()
        self.header_merges = header_merges
        self.formulas = {}


class LedgerProblem(ValueError):
    """An actionable, safe upload error (never an underlying library message)."""

    def __init__(self, message: str, *, files: list[dict] | None = None):
        super().__init__(message)
        self.files = files or []


class LedgerConflict(LedgerProblem):
    pass


def _text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _norm(value: Any) -> str:
    return _text(value).lower().replace('ё', 'е')


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip().replace('\xa0', '').replace(' ', '').replace(',', '.')
        if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text):
            result = float(text)
            return result if math.isfinite(result) else None
    return None


def _day(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 10_000 < value < 80_000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(value))).isoformat()
    text = _text(value)
    for pattern, order in [(r'(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)', (0, 1, 2)),
                           (r'(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})(?!\d)', (2, 1, 0))]:
        match = re.search(pattern, text)
        if match:
            parts = list(map(int, match.groups()))
            if parts[order[0]] < 100:
                parts[order[0]] += 2000
            try:
                date = dt.date(*(parts[i] for i in order))
                return date.isoformat() if 2000 <= date.year <= 2100 else None
            except ValueError:
                return None
    return None


def _iso(value: Any) -> str:
    text = _text(value)
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            raise ValueError
        return dt.date.fromisoformat(text).isoformat()
    except ValueError:
        raise LedgerProblem('Укажите действительную дату архива в формате ГГГГ-ММ-ДД.') from None


def _cell(column: int, row: int) -> str:
    out = ''
    while column:
        column, mod = divmod(column-1, 26)
        out = chr(65+mod) + out
    return f'{out}{row}'


def _source(filename: str, sheet: str, row: int, **cells) -> dict:
    return {'filename': filename, 'sheet': sheet, 'row': row, **cells}


def _safe_name(name: str) -> str:
    name = unicodedata.normalize('NFC', name)
    path = PurePosixPath(name)
    segments = name.rstrip('/').split('/')
    if (not name or len(name) > 240 or '\\' in name or '\x00' in name
            or path.is_absolute() or any(part in {'', '.', '..'} for part in segments)
            or re.match(r'^[A-Za-z]:', name) or any(ord(c) < 32 for c in name)):
        raise LedgerProblem('В архиве есть недопустимое имя файла. Пересоздайте ZIP с книгами Excel.')
    return name


def _zip_members(data: bytes, *, workbook: bool = False) -> list[tuple[str, bytes]]:
    if not data or len(data) > (MAX_FILE_BYTES if workbook else MAX_ARCHIVE_BYTES):
        raise LedgerProblem('Архив или книга превышает допустимый размер 20 МБ.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > (1000 if workbook else MAX_FILES):
                raise LedgerProblem('В архиве слишком много файлов.')
            total = 0
            names = set()
            out = []
            for info in infos:
                name = _safe_name(info.filename)
                normalized = name.casefold().rstrip('/')
                if normalized in names:
                    raise LedgerProblem('В архиве повторяются имена файлов. Удалите дубликаты из ZIP.')
                names.add(normalized)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.flag_bits & 1:
                    raise LedgerProblem('Ссылки и зашифрованные файлы в архиве не поддерживаются.')
                if info.is_dir():
                    continue
                total += info.file_size
                if (info.file_size > MAX_FILE_BYTES or total > MAX_UNPACKED_BYTES
                        or info.file_size > max(1, info.compress_size) * MAX_RATIO):
                    raise LedgerProblem('Распакованный архив превышает безопасный предел размера.')
                # Reading is bounded by the verified member size; no member is extracted.
                with z.open(info) as handle:
                    payload = handle.read(MAX_FILE_BYTES+1)
                if len(payload) != info.file_size or len(payload) > MAX_FILE_BYTES:
                    raise LedgerProblem('Размер файла в архиве не соответствует его содержимому.')
                out.append((name, payload))
            return out
    except LedgerProblem:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError, EOFError):
        raise LedgerProblem('ZIP не читается или повреждён. Пересоздайте архив с книгами Excel.') from None


def _xlsx_bounds(data: bytes, *, header_merges: dict | None = None) -> int:
    row_bound = 1
    count = 0
    for name, raw in _zip_members(data, workbook=True):
        if not name.endswith('.xml'):
            continue
        declarations = raw.replace(b'\x00', b'').upper()
        if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
            raise LedgerProblem('Книга содержит неподдерживаемые XML-объявления.')
        if not re.fullmatch(r'xl/worksheets/sheet[^/]*\.xml', name):
            continue
        merges = []
        try:
            for _, element in ET.iterparse(io.BytesIO(raw), events=('end',)):
                if element.tag.rsplit('}', 1)[-1] == 'mergeCell' and header_merges is not None:
                    from openpyxl.utils.cell import range_boundaries
                    try:
                        left, top, right, bottom = range_boundaries(element.attrib.get('ref', ''))
                        if (all(isinstance(value, int) for value in (left, top, right, bottom))
                                and 1 <= top <= bottom <= 45 and 1 <= left <= right <= MAX_COLUMNS):
                            merges.append((top-1, left-1, bottom-1, right-1))
                            if len(merges) > 45 * MAX_COLUMNS:
                                raise LedgerProblem('В книге слишком много объединений в шапке таблицы.')
                    except (ValueError, TypeError):
                        raise LedgerProblem('В книге не распознана объединённая шапка таблицы.') from None
                    element.clear()
                if element.tag.rsplit('}', 1)[-1] == 'c':
                    # Empty formatting at column 1000 is not business data.
                    nonempty = any(child.tag.rsplit('}', 1)[-1] in {'v', 'f', 'is'}
                                   for child in element)
                    if nonempty:
                        ref = element.attrib.get('r', '')
                        match = re.fullmatch(r'([A-Z]+)([1-9]\d*)', ref)
                        if not match:
                            raise LedgerProblem('В книге не распознаны координаты ячеек.')
                        col = 0
                        for c in match.group(1):
                            col = col*26 + ord(c)-64
                        row = int(match.group(2))
                        count += 1
                        if row > MAX_ROWS or col > MAX_COLUMNS or count > MAX_CELLS:
                            raise LedgerProblem('В книге слишком большая таблица для загрузки накопительных.')
                        row_bound = max(row_bound, row)
                    element.clear()
        except ET.ParseError:
            raise LedgerProblem('XML книги повреждён. Откройте и пересохраните книгу в Excel.') from None
        if header_merges is not None:
            header_merges[name] = merges
    return row_bound


def _bounded_row(row, budget: dict) -> list[Any]:
    # Shared-string references can expand a tiny ZIP into enormous repeated
    # business strings. Check materialized values before retaining/normalizing
    # rows; the same budget is shared by every workbook in the archive.
    for value in row:
        if isinstance(value, str):
            if len(value) > MAX_TEXT_CELL_CHARS:
                raise LedgerProblem('В книге есть слишком длинная текстовая ячейка.')
            budget['text_bytes'] += len(value.encode('utf-8'))
            if budget['text_bytes'] > MAX_MATERIALIZED_TEXT_BYTES:
                raise LedgerProblem('В архиве слишком большой объём текстовых ячеек.')
    return list(row)


def _read_workbook(filename: str, data: bytes, budget: dict | None = None) -> list[tuple[str, list[list[Any]]]]:
    budget = budget if budget is not None else {'text_bytes': 0}
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == '.xls':
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=data, on_demand=True)
            try:
                if wb.nsheets > MAX_SHEETS:
                    raise LedgerProblem('В книге слишком много листов.')
                out = []
                cells = 0
                for index in range(wb.nsheets):
                    sheet = wb.sheet_by_index(index)
                    if sheet.nrows > MAX_ROWS or sheet.ncols > MAX_COLUMNS:
                        raise LedgerProblem('В книге слишком большая таблица для загрузки накопительных.')
                    cells += sheet.nrows * sheet.ncols
                    if cells > MAX_CELLS:
                        raise LedgerProblem('В книге слишком большая таблица для загрузки накопительных.')
                    out.append((sheet.name, [_bounded_row([sheet.cell_value(r, c) for c in range(sheet.ncols)], budget)
                                             for r in range(sheet.nrows)]))
                    wb.unload_sheet(index)
                return out
            finally:
                wb.release_resources()
        except LedgerProblem:
            raise
        except ImportError:
            raise LedgerProblem('На сервере не установлен модуль чтения XLS.') from None
        except Exception:
            raise LedgerProblem('Книга XLS не читается. Пересохраните её в Excel.') from None
    header_merges = {}
    bound = _xlsx_bounds(data, header_merges=header_merges)
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True, keep_links=False)
        formula_wb = None
        try:
            if len(wb.worksheets) > MAX_SHEETS:
                raise LedgerProblem('В книге слишком много листов.')
            formula_wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
            out = []
            for sheet, formula_sheet in zip(wb.worksheets, formula_wb.worksheets):
                bounds = {'max_row': min(sheet.max_row or bound, bound),
                          'max_col': min(sheet.max_column or MAX_COLUMNS, MAX_COLUMNS)}
                rows = _SheetRows(header_merges=header_merges.get(sheet._worksheet_path.lstrip('/'), ()))
                for row_number, (cached, source) in enumerate(zip(
                        sheet.iter_rows(**bounds), formula_sheet.iter_rows(**bounds)), start=1):
                    # Reading formula text only identifies unavailable cached values;
                    # formulas/macros and external references are never executed.
                    _bounded_row([cell.value for cell in source if cell.data_type == 'f'], budget)
                    values = [_UNCACHED_FORMULA if cell.value is None and raw.data_type == 'f' else cell.value
                              for cell, raw in zip(cached, source)]
                    rows.formulas.update({(row_number, column): raw.value
                                          for column, raw in enumerate(source) if raw.data_type == 'f'})
                    rows.append(_bounded_row(values, budget))
                out.append((sheet.title, rows))
            return out
        finally:
            wb.close()
            if formula_wb is not None:
                formula_wb.close()
    except LedgerProblem:
        raise
    except Exception:
        raise LedgerProblem('Книга Excel не читается. Откройте и пересохраните её в Excel.') from None


def _value_right(row: list[Any], col: int) -> Any:
    return next((value for value in row[col+1:] if value is not None and _text(value)), None)


def _party(value: Any) -> str:
    text = _text(value)
    # A comma can be part of the legal name. Strip only the beginning of
    # address/registration details, not arbitrary company punctuation.
    return re.split(r';|,\s*(?=\d{6}\b|ИНН\b|КПП\b|Адрес\b)|\b(?:ИНН|КПП|Адрес|Юридический адрес)\b',
                    text, maxsplit=1, flags=re.I)[0].strip(' ,;')


def _party_key(value: str) -> str:
    # Same legal name with case/quotes/ё differences is still one candidate.
    # Preserve business punctuation: different legal names must not collapse.
    return re.sub(r'\s+', ' ', re.sub(r'[«»“”"]', '', value.casefold().replace('ё', 'е'))).strip()


def _contract(value: Any) -> str:
    text = _text(value)
    text = re.sub(r'^договор\s*(?:подряда\s*)?(?:№|N)?\s*', '', text, flags=re.I)
    return re.split(r'\s+от\s+', text, maxsplit=1, flags=re.I)[0].strip(' №')


def _metadata(rows: list[list[Any]], filename: str = "", sheet: str = "") -> dict:
    out = {'contractor': '', 'customer': '', 'contract': '', 'contract_date': None,
           'contract_amount': None, 'amount_scope': 'year_or_sheet',
           'object_scope': '', 'system_scope': '', 'site_scope': '',
           'scope_evidence': {'object_scope': [], 'system_scope': [], 'site_scope': []},
           'identity_source': {}, 'identity_warnings': [],
           'party_evidence': {'customer': [], 'contractor': []}}
    refs, dates = [], []
    for i, row in enumerate(rows[:40]):
        for j, value in enumerate(row):
            label = _norm(value)
            right = next(((k, v) for k, v in enumerate(row[j+1:], j+1)
                          if v is not None and _text(v)), None)
            if label in {'подрядчик', 'субподрядчик', 'генподрядчик', 'заказчик'} and right:
                field = 'contractor' if label in {'подрядчик', 'субподрядчик'} else 'customer'
                out['party_evidence'][field].append({'value': _party(right[1]),
                    'raw': _text(right[1]), 'source': _source(filename, sheet, i+1,
                    cell=_cell(right[0]+1, i+1), label_cell=_cell(j+1, i+1), label=_text(value))})
            elif label in {'объект', 'наименование объекта', 'система', 'наименование системы', 'стройка'} and right:
                field = ('system_scope' if label in {'система', 'наименование системы'} else
                         'site_scope' if label == 'стройка' else 'object_scope')
                out['scope_evidence'][field].append({'raw': _text(right[1]),
                    'source': _source(filename, sheet, i+1, cell=_cell(right[0]+1, i+1),
                                      label_cell=_cell(j+1, i+1), label=_text(value))})
            elif re.fullmatch(r'договор(?:\s+подряда)?', label) and right:
                if re.match(r'^(?:дс\b|доп(?:олнительное|\.)?\s*соглаш)', _norm(right[1])):
                    out['identity_warnings'].append('В поле договора указано допсоглашение; основной договор не установлен по догадке.')
                    continue
                refs.append((_contract(right[1]), _source(filename, sheet, i+1,
                    cell=_cell(right[0]+1, i+1), label_cell=_cell(j+1, i+1), label='Договор')))
                # Only a date explicitly attached to the contract reference is identity.
                # An act/work period/file date must never supply a missing contract date.
                if re.search(r'\bот\s+', _text(right[1]), re.I):
                    dates.append((_day(right[1]), refs[-1][1], str(right[1])))
                for ri in (i, i+1):
                    if ri >= len(rows):
                        continue
                    date_row = rows[ri]
                    for ci, date_label in enumerate(date_row):
                        if _norm(date_label) not in {'дата', 'дата договора', 'дата заключения договора', 'от'}:
                            continue
                        found = next(((k, v) for k, v in enumerate(date_row[ci+1:], ci+1)
                                      if v is not None and _text(v)), None)
                        if found:
                            dates.append((_day(found[1]), _source(filename, sheet, ri+1,
                                cell=_cell(found[0]+1, ri+1), label_cell=_cell(ci+1, ri+1),
                                label='Дата договора из шапки накопительной'), str(found[1])))
            elif 'сметная (договорная) стоимость' in label:
                amount = next((_number(v) for v in row[j+1:] if _number(v) is not None), None)
                if amount is not None:
                    out['contract_amount'] = amount
    for field, evidence in out['scope_evidence'].items():
        values = {_norm(item['raw']): item['raw'] for item in evidence if _norm(item['raw'])}
        if len(values) == 1:
            out[field] = next(iter(values.values()))
    for field, evidence in out['party_evidence'].items():
        candidates = {}
        for item in evidence:
            key = _party_key(item['value'])
            if key:
                candidates.setdefault(key, item)
        if len(candidates) == 1:
            first = next(iter(candidates.values()))
            out[field] = first['value']
            out['identity_source'][field] = first['source']
        elif len(candidates) > 1:
            role = 'заказчика' if field == 'customer' else 'подрядчика'
            out['identity_warnings'].append(
                f'В шапке указаны разные наименования {role}; сторона договора не выбрана. Проверьте исходные ячейки.')
    numbers = {number for number, _ in refs if number}
    if len(numbers) == 1:
        out['contract'] = next(iter(numbers))
        out['identity_source']['contract'] = refs[0][1]
    elif refs:
        out['identity_warnings'].append('В шапке несколько разных номеров договора; договор не выбран.')
    valid = {date for date, _, _ in dates if date}
    if len(valid) == 1 and all(date for date, _, _ in dates):
        out['contract_date'] = next(iter(valid))
        out['identity_source']['contract_date'] = dates[0][1]
    elif dates:
        out['identity_warnings'].append('В шапке нет единственной действительной даты договора; проверьте поле даты, не дату акта или периода.')
    if dates:
        out['contract_date_evidence'] = [{'date': date, 'raw': text, 'source': source}
                                         for date, source, text in dates]
    return out


_MONTH_NAMES = (
    r'январ[ья]', r'феврал[ья]', r'март[а]?', r'апрел[ья]',
    r'ма[йя]', r'июн[ья]', r'июл[ья]', r'август[а]?',
    r'сентябр[ья]', r'октябр[ья]', r'ноябр[ья]', r'декабр[ья]',
)


def _period_dates(label: str, *, year: int | None = None) -> tuple[str | None, str | None]:
    """Read explicit dates or one named calendar month, never an act number.

    The ledger's labelled annual year can qualify a month-only heading. The
    archive date and current year cannot. A month is the whole calendar period,
    so a cut inside it does not claim its final quantity as completed.
    """
    text = _norm(label)
    named = [month for month, pattern in enumerate(_MONTH_NAMES, 1)
             for _ in re.finditer(r'(?<![а-я])(?:'+pattern+r')(?![а-я])', text)]
    years = set(re.findall(r'(?<!\d)20\d\d(?!\d)', text))
    matches = re.findall(r'(?<!\d)(?:\d{1,2}[./]\d{1,2}[./](?:\d{4}|\d{2})|20\d\d-\d{2}-\d{2})(?!\d)', text)
    if matches:
        dates = [_day(value) for value in matches]
        if len(dates) > 2 or not all(dates) or dates[0] > dates[-1]:
            return None, None
        if years - {date[:4] for date in dates} or any(month not in {int(date[5:7]) for date in dates} for month in named):
            return None, None
        return dates[0], dates[-1]
    if len(years) > 1:
        return None, None
    source_year = int(next(iter(years))) if years else year
    if isinstance(source_year, bool) or not isinstance(source_year, int) or not 2000 <= source_year <= 2099:
        return None, None
    # A written day is not a whole-month heading. Do not silently widen it.
    if any(re.search(r'(?<!\d)\d{1,2}\s*(?:'+pattern+r')(?![а-я])', text) for pattern in _MONTH_NAMES):
        return None, None
    numeric = re.findall(r'(?<![\d./])(\d{1,2})[./](20\d\d)(?!\d)', text)
    months = named + [int(month) for month, _ in numeric]
    if len(months) != 1 or not 1 <= months[0] <= 12:
        return None, None
    month = months[0]
    first = dt.date(source_year, month, 1)
    last = dt.date(source_year, month, calendar.monthrange(source_year, month)[1])
    return first.isoformat(), last.isoformat()


def _restore_period_dates(snapshot: dict) -> dict:
    """Interpret preserved period labels in old imports without writing them.

    Values, source bindings and snapshot identity stay intact. This shared read
    path also serves physical progress, so it cannot disagree with contracts.
    """
    ledgers = []
    for ledger in snapshot.get('ledgers') or []:
        items = []
        for item in ledger.get('items') or []:
            periods = []
            for period in item.get('periods') or []:
                if not period.get('date_start') and not period.get('date_end'):
                    first, last = _period_dates(period.get('label') or '', year=ledger.get('period_year'))
                    if first and last:
                        period = {**period, 'date_start': first, 'date_end': last}
                periods.append(period)
            items.append({**item, 'periods': periods})
        known = any(p.get('date_end') for item in items for p in item['periods'])
        warnings = list(ledger.get('warnings') or [])
        if known:
            warnings = [warning for warning in warnings if warning !=
                        'Точные даты выполнения в книге не распознаны. Дата архива не является датой выполнения работ.']
        ledgers.append({**ledger, 'items': items, 'period_dates_known': known, 'warnings': warnings})
    return {**snapshot, 'ledgers': ledgers}


def amount_basis(header: str) -> str:
    """Explicit tax basis shared by cumulative and contract-register readers.

    This labels source wording only. It never selects a VAT rate or converts
    an amount. A label without an explicit qualifier stays unspecified.
    """
    text = _norm(header)
    without = bool(re.search(r'без\s*ндс', text))
    included = bool(re.search(r'(?:с\s*ндс|с\s+учетом\s+ндс|включая\s*ндс|в\s*том\s*числе\s*ндс|в\s*т\.?\s*ч\.?\s*ндс)', text))
    if without and included:
        return 'conflicting'
    if without:
        return 'without_vat'
    if included:
        return 'with_vat'
    return 'unspecified'


def _amount_basis(header: str) -> str:
    # Backward-compatible private entry point; one predicate owns semantics.
    return amount_basis(header)


def _full_contract_price(label: str) -> bool:
    text = _norm(label)
    return bool(re.search(r'(?:новая|итоговая|общая|полная)\s+(?:сумма|цена|стоимость)\s+(?:по\s+)?договора', text)
                or re.search(r'(?:сумма|цена|стоимость)\s+договора\s+с\s+уч[её]том\b', text))


def _money_kind(qhead: list[Any], column: int) -> str:
    label = _norm(qhead[column]) if 0 <= column < len(qhead) else ''
    if 'стоимост' not in label and 'сумм' not in label:
        return ''
    if 'матер' in label and 'смр' not in label:
        return 'material'
    if 'смр' in label and 'матер' not in label:
        return 'work'
    return ''


def _money_pair_columns(qhead: list[Any], first: int) -> dict[str, int]:
    kinds = {_money_kind(qhead, first): first, _money_kind(qhead, first+1): first+1}
    return kinds if set(kinds) == {'work', 'material'} else {}


def _money_pair_total(first: int, at) -> float | None:
    raw = [at(first), at(first+1)]
    values = [_number(value) for value in raw]
    if any(_text(value) and number is None for value, number in zip(raw, values)):
        return None
    return sum(value or 0.0 for value in values) if any(value is not None for value in values) else None


def _money_parts(qhead: list[Any], first: int, at) -> tuple[float | None, float | None]:
    """(works, materials) money of a labelled pair; unlabelled pairs are unknown.

    The book's total already counts an empty half as nothing when the other half
    is a number, so the halves do the same and always add up to that total. Two
    empty halves stay unknown."""
    kinds = _money_pair_columns(qhead, first)
    if not kinds or _money_pair_total(first, at) is None:
        return None, None
    work, material = _number(at(kinds['work'])), _number(at(kinds['material']))
    if work is None and material is None:
        return None, None
    return work or 0.0, material or 0.0


def group_basis(parent: dict, children: list[dict]) -> str:
    """Prove a source rollup without discarding independent execution."""
    leaves = [child for child in children if child.get('is_group') is not True]
    if not leaves or not any((_number(child.get('planned_amount')) or 0) > 0 for child in leaves):
        return ''

    def completed(item, field):
        reported = _number(item.get('reported_' + field))
        return reported if reported is not None else _number(item.get(field))

    amount = _number(parent.get('planned_amount'))
    done = completed(parent, 'completed_amount')
    quantity = completed(parent, 'completed_quantity')
    independent = ('completed_quantity', 'material_quantity', 'completed_work_amount', 'completed_material_amount')
    empty_fact = (done in {None, 0} and quantity in {None, 0}
                  and all(completed(parent, field) in {None, 0} for field in independent))
    if amount is None and _number(parent.get('plan_quantity')) is None and empty_fact:
        return 'empty_structured_heading'
    if amount == 0 and empty_fact:
        return 'zero_cost_structured_heading'
    costs = [_number(child.get('planned_amount')) for child in leaves]
    facts = [completed(child, 'completed_amount') for child in leaves]
    # Net-zero totals do not erase a delivery or opposite monetary corrections.
    # A nonzero part of a subtotal must be reconciled on its own source basis.
    for field in ('plan_quantity', *independent):
        value = completed(parent, field)
        if value in {None, 0}:
            continue
        parts = [completed(child, field) for child in leaves]
        if (any(part is None for part in parts)
                or abs(sum(parts)-value) > max(1e-6, abs(value)*1e-7)):
            return ''
        if field in {'plan_quantity', 'completed_quantity', 'material_quantity'} and any(
                _norm(child.get('unit')) != _norm(parent.get('unit')) for child in leaves):
            return ''
    if (amount is not None and amount > 0 and done is not None
            and all(value is not None for value in costs + facts)
            and abs(sum(costs)-amount) <= max(.01, abs(amount)*1e-7)
            and abs(sum(facts)-done) <= max(.01, abs(done)*1e-7)):
        return 'reconciled_subtotal'
    return ''


def _total_label(name: str) -> bool:
    return bool(re.match(r'^(?:итого\b|всего\b|по\s+(?:разделу|смете)\b|'
                         r'(?:в\s+том\s+числе\s+|в\s*т\.?\s*ч\.?\s*)?ндс\b)', _norm(name)))


def _formula_columns(value: str, row: int, operator: str) -> set[int]:
    """Read only same-row references from a declared sum/product, not evaluate it."""
    text = re.sub(r'\s|\$', '', str(value or '')).upper().removeprefix('=')
    rounded = re.fullmatch(r'ROUND\((.+),[0-6]\)', text)
    if rounded:
        text = rounded.group(1)
    if operator == '+' and text.startswith('SUM(') and text.endswith(')'):
        text = text[4:-1]
        span = re.fullmatch(r'([A-Z]+)([1-9]\d*):([A-Z]+)([1-9]\d*)', text)
        if span and int(span[2]) == row == int(span[4]):
            coordinates = {_cell(col+1, row): col for col in range(MAX_COLUMNS)}
            first, last = coordinates.get(span[1]+span[2]), coordinates.get(span[3]+span[4])
            return set(range(first, last+1)) if first is not None and last is not None and first <= last else set()
        text = text.replace(',', '+')
    terms = text.split(operator)
    if len(terms) < 2 or any(not re.fullmatch(r'[A-Z]+[1-9]\d*', term) for term in terms):
        return set()
    coordinates = {_cell(col+1, row): col for col in range(MAX_COLUMNS)}
    if any(term not in coordinates for term in terms):
        return set()
    return {coordinates[term] for term in terms}


def _merged_cost_column(rows, hi: int, qi: int, plan_col: int, first_period: int,
                        anchor: int | None) -> int | None:
    """Resolve a merged money field using its values and declared formula links.

    A merged caption does not label its leftmost cell as the position total.
    A multi-value field needs proof of the full total; alignment is insufficient.
    """
    spans = [(left, right) for top, left, bottom, right in getattr(rows, 'header_merges', ())
             if hi <= top <= qi and left == anchor and right < first_period and left < right]
    if not spans:
        return anchor
    if len(set(spans)) != 1:
        return None
    left, right = spans[0]
    field = set(range(left, right+1))
    price_columns = set()
    for ri in range(hi, qi+1):
        for ci in range(plan_col+1, left):
            label = _norm(rows[ri][ci]) if ci < len(rows[ri]) else ''
            if re.search(r'(?:цен[аы]|стоимост\w*)\s+за\s+(?:ед|единиц)', label):
                price_columns.add(ci)
                for top, start, bottom, end in getattr(rows, 'header_merges', ()):
                    if top == ri and start == ci and end < left:
                        price_columns.update(range(start, end+1))
    formulas = getattr(rows, 'formulas', {})
    populated, proven = set(), set()
    unknown = False
    for row_number, values in enumerate(rows, start=1):
        if row_number <= qi+1 or plan_col >= len(values) or _number(values[plan_col]) is None:
            continue
        at = lambda col: _number(values[col]) if col < len(values) else None
        populated.update(col for col in field if at(col) not in {None, 0})
        unknown |= any(col < len(values) and _text(values[col]) and at(col) is None for col in field)
        for col in field:
            total = at(col)
            if total in {None, 0}:
                continue
            formula = formulas.get((row_number, col), '')
            summed = _formula_columns(formula, row_number, '+')
            if (len(summed) >= 2 and summed == field-{col} and all(at(part) is not None for part in summed)
                    and abs(total-sum(at(part) for part in summed)) <= max(.02, abs(total)*1e-7)):
                proven.add(col)
            product = _formula_columns(formula, row_number, '*')
            rates = product-{plan_col}
            if len(product) != 2 or plan_col not in product or len(rates) != 1:
                continue
            rate = next(iter(rates))
            parts = _formula_columns(formulas.get((row_number, rate), ''), row_number, '+')
            if (rate in price_columns and len(parts) >= 2 and parts == price_columns-{rate}
                    and all(at(part) is not None for part in parts) and at(rate) is not None
                    and abs(at(rate)-sum(at(part) for part in parts)) <= max(.01, abs(at(rate))*1e-7)
                    and abs(total-at(plan_col)*at(rate)) <= max(.02, abs(total)*1e-7)):
                proven.add(col)
    if len(proven) == 1:
        return next(iter(proven))
    # One populated value in the entire declared field is unambiguous. Blank
    # or zero companions provide no competing subtotal; an uncached formula does.
    return next(iter(populated)) if not proven and len(populated) == 1 and not unknown else None


def _ledger(filename: str, sheet: str, rows: list[list[Any]]) -> dict | None:
    # Recognize a labelled table, not the file's name or a particular contractor.
    top = rows[:45]
    main_headers = [(i, r) for i, r in enumerate(top)
                    if any('наименование работ' in _norm(v) for v in r)
                    and any('ед.' in _norm(v) or 'единица измерения' in _norm(v) for v in r)
                    and any('кол-во' in _norm(v) or 'количество' in _norm(v) for v in r)]
    if not main_headers:
        return None
    hi, head = main_headers[-1]
    name_col = next(j for j, v in enumerate(head) if 'наименование работ' in _norm(v))
    unit_col = next(j for j, v in enumerate(head) if 'ед.' in _norm(v) or 'единица измерения' in _norm(v))
    plan_col = next(j for j, v in enumerate(head) if 'кол-во' in _norm(v) or 'количество' in _norm(v))
    candidates = [(i, r) for i, r in enumerate(top[hi+1:hi+5], start=hi+1)
                  if sum('количеств' in _norm(v) or _norm(v) == 'кол-во' for v in r) >= 2]
    if not candidates:
        raise LedgerProblem('В накопительной не распознаны колонки количества выполненных работ.')
    qi, qhead = candidates[-1]
    years = [(j, _text(v)) for r in top[hi:qi+1] for j, v in enumerate(r)
             if re.fullmatch(r'20\d\d\s*год', _text(v))]
    if len(years) != 1:
        raise LedgerProblem('В накопительной не распознан единственный годовой итог количества.')
    year_col, year_label = years[0]
    qlabel = _norm(qhead[year_col]) if year_col < len(qhead) else ''
    if not ('количеств' in qlabel or qlabel == 'кол-во'):
        raise LedgerProblem('Годовой итог накопительной не содержит количества.')
    split = 'матер' in qlabel and year_col+1 < len(qhead) and 'смр' in _norm(qhead[year_col+1])
    actual_col = year_col+1 if split else year_col
    first_period = min(j for j, v in enumerate(qhead) if j > plan_col and ('количеств' in _norm(v) or _norm(v) == 'кол-во'))
    # A planned total may be labelled in any row of the multi-row header.
    # Price per unit and material/work subtotals are not a position total.
    cost_labels, generic_cost_labels = set(), set()
    for header_row in rows[hi:qi+1]:
        for col in range(plan_col+1, min(first_period, len(header_row))):
            label = _norm(header_row[col])
            if (not re.search(r'стоимост|сумм', label)
                    or re.search(r'за\s*(?:ед|единиц)|цен[аы]\s+(?:за\s+)?ед', label)
                    or re.search(r'матер|мтр|оборуд|смр|пнр', label)):
                continue
            generic_cost_labels.add(col)
            if re.search(r'договорн|сметн|итого|всего|общая|полная', label):
                cost_labels.add(col)
    # When the total group has multiple labelled subcolumns, its rightmost
    # explicit total wins. Without a total label, only a single cost column is
    # unambiguous. Never take the adjacent unit price just because it is last.
    cost_col = max(cost_labels) if cost_labels else (
        next(iter(generic_cost_labels)) if len(generic_cost_labels) == 1 else None)
    cost_col = _merged_cost_column(rows, hi, qi, plan_col, first_period, cost_col)
    # The planned cost heading can span rows/columns: an upper total label and
    # a lower «Стоимость итого, с НДС». Unit prices and actual periods are
    # separate groups; neither may supply the planned total's tax qualifier.
    cost_group_start = min(cost_labels | generic_cost_labels) if (cost_labels or generic_cost_labels) else first_period
    for header_row in rows[hi:qi+1]:
        for col in range(plan_col+1, min(first_period, len(header_row))):
            label = _norm(header_row[col])
            if (('стоимост' in label and ('итого' in label or 'договорн' in label or 'сметн' in label))
                    and not re.search(r'за\s*(?:ед|единиц)', label)):
                cost_group_start = min(cost_group_start, col)
    planned_bases = {_amount_basis(_text(header_row[col]))
                     for header_row in rows[hi:qi+1]
                     for col in range(cost_group_start, min(first_period, len(header_row)))} - {'unspecified'}
    planned_amount_basis = ('conflicting' if 'conflicting' in planned_bases or len(planned_bases) > 1
                            else next(iter(planned_bases)) if planned_bases else 'unspecified')
    amount_col = year_col+3 if split else year_col+1
    annual_money_cols = (year_col+2, year_col+3) if split else (year_col+1,)
    annual_bases = {_amount_basis(_text(qhead[c])) for c in annual_money_cols if c < len(qhead)} - {'unspecified'}
    completed_amount_basis = ('conflicting' if len(annual_bases) > 1 else
                              next(iter(annual_bases)) if annual_bases else 'unspecified')
    period_cols = [j for j, v in enumerate(qhead) if plan_col < j < year_col
                   and ('количеств' in _norm(v) or _norm(v) == 'кол-во')
                   and not ('смр' in _norm(v) and split)]
    meta = _metadata(rows, filename, sheet)
    warnings = list(meta.get('identity_warnings') or [])
    if not meta['contractor'] or not meta['contract']:
        warnings.append('В шапке не распознаны контрагент или номер договора.')
    if not meta['contract_date']:
        warnings.append('В шапке не распознана действительная дата договора.')
    warnings.append('Сумма и количества этой книги относятся к её году или составу работ; это не подтверждение полной суммы договора.')
    if split:
        warnings.append('Материалы и монтаж учтены отдельно. Поставку не считать выполнением монтажа.')
    # Works and materials money are told apart by their own column labels, never
    # by position. An unlabelled pair stays a total with an explicit warning.
    money_split = split and bool(_money_pair_columns(qhead, year_col+2))
    if split and not money_split:
        warnings.append('Колонки сумм материалов и СМР не распознаны по подписям; '
                        'выполнение работ и поставка материалов по деньгам не разделены.')
    def labelled_parts(first, last):
        found = {'work': set(), 'material': set()}
        for col in range(first, last):
            for header_row in reversed(rows[hi:qi+1]):
                label = _norm(header_row[col]) if col < len(header_row) else ''
                work = bool(re.search(r'смр|пнр|^(?:(?:стоимость|цена)\s+)?работ(?:а|ы)?\b', label))
                material = bool(re.search(r'матер|мтр|оборуд', label))
                if work != material:
                    found['work' if work else 'material'].add(col)
                    break
        if all(len(columns) == 1 for columns in found.values()):
            return {key: next(iter(columns)) for key, columns in found.items()}
        return {}

    planned_parts = labelled_parts(cost_group_start, first_period)
    rate_parts = labelled_parts(plan_col+1, cost_group_start)
    rate_bases = {_amount_basis(_text(header_row[col])) for header_row in rows[hi:qi+1]
                  for col in rate_parts.values() if col < len(header_row)} - {'unspecified'}
    rate_basis = ('conflicting' if 'conflicting' in rate_bases or len(rate_bases) > 1 else
                  next(iter(rate_bases)) if rate_bases else 'unspecified')
    weight_basis = planned_amount_basis
    if not planned_parts and rate_parts:
        if (rate_basis == 'conflicting' or (planned_amount_basis != 'unspecified'
                and rate_basis != 'unspecified' and planned_amount_basis != rate_basis)):
            weight_basis = 'conflicting'
        elif weight_basis == 'unspecified':
            weight_basis = rate_basis
    items = []
    scope = ''
    section_stack, locations, context_headings = [], [], []
    errors = []
    for ri, row in enumerate(rows, start=1):
        for ci, value in enumerate(row, start=1):
            if isinstance(value, str) and value.startswith(('#REF!', '#DIV/0!', '#VALUE!', '#N/A', '#NAME?', '#NUM!')):
                errors.append(_cell(ci, ri))
        if ri <= qi+1:
            continue
        def at(c):
            return row[c] if c is not None and c < len(row) else None
        name, unit = _text(at(name_col)), _text(at(unit_col))
        position = _text(at(max(0, name_col-1)))
        node = {'position': position, 'name': name,
                'source': {'row': ri, 'cell': _cell(name_col+1, ri)}}
        heading = bool(re.search(r'[a-zа-я]', name, re.I)) and unit.upper() in {'', 'X', 'Х'}
        total = _total_label(name)
        code = tuple(position.rstrip('.').split('.')) if re.fullmatch(r'\d+(?:\.\d+)*\.?', position) else ()
        if heading and not total:
            if re.search(r'корпус|секци|паркинг|автостоян', name, re.I):
                locations, section_stack, context_headings = [node], [], []
            elif re.search(r'этаж|подземн|уровень|отметк', name, re.I):
                locations = locations[:1] + [node] if locations else [node]
            elif not code:
                context_headings = (context_headings + [node])[-4:]
        if code and re.search(r'[a-zа-я]', name, re.I) and not total:
            while section_stack and not (len(section_stack[-1][0]) < len(code)
                    and code[:len(section_stack[-1][0])] == section_stack[-1][0]):
                section_stack.pop()
        parents, seen_rows = [], set()
        for parent in [*locations, *(entry[1] for entry in section_stack)]:
            if parent['source']['row'] != ri and parent['source']['row'] not in seen_rows:
                parents.append(parent)
                seen_rows.add(parent['source']['row'])
        parents.sort(key=lambda parent: parent['source']['row'])
        if code and re.search(r'[a-zа-я]', name, re.I) and not total:
            section_stack.append((code, node))
        scope = ' · '.join(parent['name'] for parent in locations)
        if not scope and parents:
            scope = parents[-1]['name']
        unit_known = bool(unit and unit.upper() not in {'X', 'Х'}
                          and not re.fullmatch(r'[\d., ]+', unit))
        numeric_work = (bool(re.search(r'[a-zа-я]', name, re.I)) and any(
            _number(at(col)) is not None for col in (plan_col, actual_col, cost_col, amount_col)))
        if (not name or (not unit_known and not numeric_work)
                or total):
            continue
        plan, actual = _number(at(plan_col)), _number(at(actual_col))
        item_warnings = []
        if not unit_known:
            item_warnings.append('Единица измерения не подтверждена; строка сохранена для проверки состава ведомости.')
        if plan is None:
            # A formula with no cached result is missing evidence, not zero.
            if not _text(at(plan_col)):
                warnings.append(f'Строка {ri}: нет сохранённого планового количества.')
            item_warnings.append('Полное количество позиции не подтверждено; строка сохранена, процент не рассчитан.')
        if actual is None:
            item_warnings.append('Нет сохранённого выполненного количества: требуется пересчёт и сохранение книги в Excel.')
        if actual is not None and (actual < -1e-6 or (plan is not None and plan >= 0 and actual > plan + max(1e-6, abs(plan)*1e-7))):
            item_warnings.append('Выполненное количество выходит за границы планового. Проверьте объём или состав работ.')
        if split and actual is not None:
            source_remaining = _number(at(year_col+4))
            if (plan is not None and source_remaining is not None
                    and abs(source_remaining-(plan-actual)) > max(1e-6, abs(plan)*1e-7)):
                item_warnings.append('Остаток в книге отличается от остатка по монтажу. '
                                     'Поставку материалов нельзя вычитать как выполненный монтаж.')
        periods = []
        for col in period_cols:
            label = next((_text(rows[r][col]) for r in range(qi-1, hi-1, -1)
                          if col < len(rows[r]) and _text(rows[r][col])
                          and 'выполнено работ' not in _norm(rows[r][col])), '')
            start, end = _period_dates(label, year=int(year_label[:4]))
            pqty = _number(at(col+1 if split else col))
            pmat = _number(at(col)) if split else None
            pwork = pmaterial = None
            if split:
                pamount = _money_pair_total(col+2, at)
                pwork, pmaterial = _money_parts(qhead, col+2, at)
                bad = [c for c in (col+2, col+3) if _text(at(c)) and _number(at(c)) is None]
                if bad:
                    item_warnings.append('Не подтверждены суммы выполнения в ячейках '
                                         + ', '.join(_cell(c+1, ri) for c in bad)
                                         + ': непустое значение не прочитано как число; сумма периода неизвестна.')
                    if any(at(c) == _UNCACHED_FORMULA for c in bad):
                        item_warnings.append('У формулы нет сохранённого результата. Пересчитайте и сохраните книгу в Excel; формула не вычислялась.')
                if not _money_pair_columns(qhead, col+2):
                    item_warnings.append('Подписи сумм периода не разделяют материалы и СМР; '
                                         'отдельные денежные показатели не определены.')
            else:
                pamount = _number(at(col+1))
            money_cols = (col+2, col+3) if split else (col+1,)
            bases = {_amount_basis(_text(qhead[c])) for c in money_cols if c < len(qhead)} - {'unspecified'}
            pamount_basis = 'conflicting' if len(bases) > 1 else next(iter(bases)) if bases else 'unspecified'
            periods.append({'label': label, 'quantity': pqty, 'material_quantity': pmat,
                            'amount': pamount, 'work_amount': pwork, 'material_amount': pmaterial,
                            'amount_split': split and pwork is not None and pmaterial is not None,
                            'amount_basis': pamount_basis, 'date_start': start, 'date_end': end,
                            'source': _source(filename, sheet, ri,
                                              quantity_cell=_cell(col+(2 if split else 1), ri),
                                              amount_cell=(_cell(col+3, ri)+' + '+_cell(col+4, ri)
                                                           if split else _cell(col+2, ri)))})
        completed_work = completed_material = None
        if split:
            completed_amount = _money_pair_total(year_col+2, at)
            completed_work, completed_material = _money_parts(qhead, year_col+2, at)
            bad = [c for c in (year_col+2, year_col+3) if _text(at(c)) and _number(at(c)) is None]
            if bad:
                item_warnings.append('Не подтверждены годовые суммы в ячейках '
                                     + ', '.join(_cell(c+1, ri) for c in bad)
                                     + ': непустое значение не прочитано как число; годовой итог неизвестен.')
                if any(at(c) == _UNCACHED_FORMULA for c in bad):
                    item_warnings.append('У формулы нет сохранённого результата. Пересчитайте и сохраните книгу в Excel; формула не вычислялась.')
        else:
            completed_amount = _number(at(amount_col))
        planned_total = _number(at(cost_col))
        plan_work = plan_material = None
        plan_work_cell = plan_material_cell = None
        planned_cost_method = ''
        parts = planned_parts or rate_parts
        if parts and (planned_parts or plan is not None):
            raw_parts = {kind: at(col) for kind, col in parts.items()}
            numeric = {kind: _number(value) for kind, value in raw_parts.items()}
            if (any(value is not None for value in numeric.values())
                    and not any(_text(raw_parts[kind]) and value is None for kind, value in numeric.items())):
                multiplier = 1 if planned_parts else plan
                work = (numeric['work'] or 0) * multiplier
                material = (numeric['material'] or 0) * multiplier
                if planned_total is not None and abs(work+material-planned_total) <= max(.01, abs(planned_total)*1e-7):
                    plan_work, plan_material = work, material
                    prefix = '' if planned_parts else _cell(plan_col+1, ri) + ' × '
                    plan_work_cell = prefix + _cell(parts['work']+1, ri)
                    plan_material_cell = prefix + _cell(parts['material']+1, ri)
                    planned_cost_method = 'labelled_subtotals' if planned_parts else 'quantity_times_labelled_unit_price'
                else:
                    item_warnings.append('Подписанные плановые стоимости СМР и материалов не сходятся с полной стоимостью позиции; веса выполнения не использованы.')
        items.append({'position': position, 'name': name,
                      'scope': scope, 'unit': unit if unit_known else '', 'plan_quantity': plan,
                      'section_path': parents, 'context_headings': list(context_headings),
                      'parent_row': parents[-1]['source']['row'] if parents else None,
                      'is_group': False,
                      'completed_quantity': actual, 'material_quantity': _number(at(year_col)) if split else None,
                      'quantity_kind': 'installation' if split else 'work_quantity',
                      'planned_amount': _number(at(cost_col)), 'completed_amount': completed_amount,
                      'planned_work_amount': plan_work, 'planned_material_amount': plan_material,
                      'planned_cost_split': plan_work is not None and plan_material is not None,
                      'planned_work_amount_basis': weight_basis,
                      'planned_cost_method': planned_cost_method,
                      'planned_amount_basis': planned_amount_basis,
                      'completed_amount_basis': completed_amount_basis,
                      'completed_work_amount': completed_work, 'completed_material_amount': completed_material,
                      'amount_split': split and completed_work is not None and completed_material is not None,
                      'periods': periods, 'warnings': item_warnings,
                      'source': _source(filename, sheet, ri,
                                        unit_cell=_cell(unit_col+1, ri),
                                        plan_quantity_cell=_cell(plan_col+1, ri),
                                        completed_quantity_cell=_cell(actual_col+1, ri),
                                        material_quantity_cell=_cell(year_col+1, ri) if split else None,
                                        planned_amount_cell=_cell(cost_col+1, ri) if cost_col is not None else None,
                                        planned_work_amount_cell=plan_work_cell,
                                        planned_material_amount_cell=plan_material_cell,
                                        completed_amount_cell=(_cell(year_col+3, ri)+' + '+_cell(year_col+4, ri)
                                                               if split else _cell(amount_col+1, ri)))})
        if len(items) > MAX_ITEMS or len(items)*len(period_cols) > MAX_PERIOD_VALUES:
            raise LedgerProblem('В накопительной слишком много строк или периодов для одного импорта.')
    if errors:
        warnings.append('В книге есть ошибки формул Excel: ' + ', '.join(errors[:20]) + (', …' if len(errors)>20 else '') + '.')
    if not items:
        raise LedgerProblem('В накопительной не найдено строк с объёмами работ.')
    by_row = {item['source']['row']: item for item in items}
    descendants = {}
    for item in items:
        for parent in item['section_path']:
            if parent['source']['row'] in by_row:
                descendants.setdefault(parent['source']['row'], set()).add(item['source']['row'])
    for row_number in sorted(descendants, key=lambda row: len(descendants[row])):
        parent = by_row[row_number]
        children = [by_row[row] for row in descendants[row_number] if not by_row[row]['is_group']]
        parent['group_basis'] = group_basis(parent, children)
        parent['is_group'] = bool(parent['group_basis'])
    if not any(p['date_end'] for item in items for p in item['periods']):
        warnings.append('Точные даты выполнения в книге не распознаны. Дата архива не является датой выполнения работ.')
    declared_form = 'ks6a' if any(re.search(r'кс[-\s]*6[-\s]*а', _norm(v))
                                 for row in top for v in row if isinstance(v, str)) else 'cumulative'
    incomplete = sum(not item.get('unit') or any(_number(item.get(field)) is None for field in
                        ('plan_quantity', 'completed_quantity', 'planned_amount', 'completed_amount'))
                     for item in items if not item['is_group'])
    return {**meta, 'document_form': declared_form, 'period_year': int(year_label[:4]), 'items': items,
            'source_complete': incomplete == 0, 'incomplete_rows_count': incomplete,
            'unread_rows_count': 0,
            'source': _source(filename, sheet, hi+1), 'warnings': warnings,
            'period_dates_known': any(p['date_end'] for item in items for p in item['periods'])}


def _summary(filename: str, sheet: str, rows: list[list[Any]]) -> list[dict] | None:
    headers = [(i, r) for i, r in enumerate(rows)
               if any('сумма договора' in _norm(v) for v in r)
               and any('дата кс' in _norm(v) for v in r)
               and any('сумма по кс' in _norm(v) for v in r)]
    if not headers:
        return None
    customer = next((_party(r[0]) for r in rows[:5] if r and re.match(r'^(?:ООО|АО|ПАО|ИП)\b', _text(r[0]), re.I)), '')
    contractor = ''
    current = None
    contracts = []
    header_map = {}
    header_indices = {i: r for i, r in headers}
    for ri, row in enumerate(rows):
        if ri in header_indices:
            labels = [_norm(v) for v in row]
            def col(needle):
                return next(j for j, label in enumerate(labels) if needle in label)
            header_map = {'contract': col('№ договора'), 'amount': col('сумма договора'),
                          'number': col('№ кс'), 'date': col('дата кс'), 'act_amount': col('сумма по кс')}
            def basis_header(column):
                # Tax qualifiers can be a preceding/following header cell in
                # the same column. Never borrow a neighbour's VAT qualifier.
                return ' '.join(_text(rows[r][column]) for r in range(max(0, ri-2), min(len(rows), ri+2))
                                if column < len(rows[r]) and isinstance(rows[r][column], str))
            header_map['amount_header'] = basis_header(header_map['amount'])
            header_map['act_amount_header'] = basis_header(header_map['act_amount'])
            continue
        def at(field):
            c = header_map.get(field)
            return row[c] if c is not None and c < len(row) else None
        first = _text(row[0]) if row else ''
        if (re.match(r'^(?:ООО|АО|ПАО|ИП)\b', first, re.I)
                and not re.match(r'^(?:договор|дс|доп\.?\s*соглаш)\b', _text(at('contract')), re.I)):
            contractor = _party(first)
            current = None
            continue
        if not header_map:
            # Contractor headings conventionally precede each repeated header.
            if re.match(r'^(?:ООО|АО|ПАО|ИП)\b', first, re.I) and ri > 2:
                contractor = _party(first)
            continue
        contract_text = _text(at('contract'))
        if re.match(r'^договор\b', contract_text, re.I):
            current = {'contractor': contractor, 'customer': customer,
                       'contract': _contract(contract_text), 'contract_date': _day(contract_text),
                       'amount': _number(at('amount')), 'amount_date': _day(contract_text),
                       'amount_scope': 'full_contract',
                       'amount_basis': _amount_basis(header_map['amount_header']),
                       'deadline': None, 'acts': [], 'amount_versions': [], 'warnings': [],
                       'source': _source(filename, sheet, ri+1, cell=_cell(header_map['amount']+1, ri+1), amount_header=header_map['amount_header'])}
            contracts.append(current)
            if current['amount'] is not None:
                current['amount_versions'].append({'amount': current['amount'], 'date': current['amount_date'],
                                                   'scope': 'full_contract', 'amount_basis': current['amount_basis'],
                                                   'label': contract_text, 'source': _source(filename, sheet, ri+1)})
        elif current is not None and re.match(r'^(?:дс|доп\.?\s*соглаш)', contract_text, re.I):
            amount = _number(at('amount'))
            if amount is not None:
                declared_full = _full_contract_price(first+' '+contract_text+' '+header_map['amount_header'])
                scope = 'full_contract' if declared_full else 'ambiguous_amendment'
                current['amount'] = amount if declared_full else None
                current['amount_date'] = _day(contract_text)
                current['amount_scope'] = scope
                current['amount_basis'] = _amount_basis(header_map['amount_header'])
                current['amount_versions'].append({'amount': current['amount'], 'stated_amount': amount,
                                                   'scope': scope, 'amount_basis': current['amount_basis'],
                                                   'date': current['amount_date'],
                                                   'label': contract_text, 'source': _source(filename, sheet, ri+1)})
                if not declared_full:
                    current['warnings'].append(f'Строка {ri+1}: сумма допсоглашения не подписана как полная новая сумма договора. '
                                               'Действующая сумма договора требует подтверждения.')
        if current is None:
            continue
        number, amount = _text(at('number')), _number(at('act_amount'))
        if number and amount is not None and not re.match(r'^(?:итого|всего)', _norm(first)):
            date = _day(at('date'))
            if not date:
                current['warnings'].append(f'Строка {ri+1}: у акта нет действительной даты.')
            current['acts'].append({'number': number, 'date': date, 'amount': amount,
                                    'amount_basis': _amount_basis(header_map['act_amount_header']),
                                    'source': _source(filename, sheet, ri+1, amount_header=header_map['act_amount_header'])})
    for item in contracts:
        if not item['contractor']:
            item['warnings'].append('Не распознан контрагент договорного блока.')
        if not item['amount_date']:
            item['warnings'].append('У действующей суммы договора не распознана дата версии.')
        seen = set()
        for act in item['acts']:
            key = (act['number'], act['date'])
            if key in seen:
                item['warnings'].append('Повторяются номер и дата акта; требуется сверка перед суммированием.')
                break
            seen.add(key)
    return contracts


def parse_archive(data: bytes, filename: str = '') -> dict:
    if filename and PurePosixPath(filename).suffix.lower() != '.zip':
        raise LedgerProblem('Выберите ZIP-архив с накопительными книгами Excel.')
    members = _zip_members(data)
    budget = {'text_bytes': 0}
    result = {'files': [], 'ledgers': [], 'summary_contracts': [], 'warnings': [],
              'identity_schema': 4, 'parser_schema': PARSER_SCHEMA}
    if not members:
        raise LedgerProblem('Архив пуст. Добавьте накопительные книги Excel.')
    for name, payload in members:
        if name.startswith('__MACOSX/') or PurePosixPath(name).name == '.DS_Store':
            result['files'].append({'filename': name, 'status': 'ignored', 'warnings': ['Служебный файл архива.']})
            continue
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in SUPPORTED:
            files = [*result['files'], {'filename': name, 'status': 'failed',
                                       'warnings': ['Поддерживаются только XLS, XLSX и XLSM.']}]
            read = {f['filename'] for f in files}
            files += [{'filename': n, 'status': 'not_read', 'warnings': ['Импорт остановлен до сохранения.']}
                      for n, _ in members if n not in read]
            raise LedgerProblem('В архиве есть неподдерживаемый файл. Оставьте только XLS, XLSX и XLSM.', files=files)
        try:
            sheets = _read_workbook(name, payload, budget)
            count = 0
            sheet_warnings = []
            recognized = []
            companions = []
            for title, rows in sheets:
                ledger = _ledger(name, title, rows)
                if ledger is not None:
                    ledger['file_sha256'] = hashlib.sha256(payload).hexdigest()
                    result['ledgers'].append(ledger)
                    if (sum(len(l['items']) for l in result['ledgers']) > MAX_ITEMS
                            or sum(len(i['periods']) for l in result['ledgers'] for i in l['items']) > MAX_PERIOD_VALUES):
                        raise LedgerProblem('В архиве слишком много строк или периодов для одного импорта.')
                    count += 1
                    recognized.append({'sheet': title, 'kind': 'cumulative'})
                    continue
                contracts = _summary(name, title, rows)
                if contracts is not None:
                    result['summary_contracts'].extend(contracts)
                    count += 1
                    recognized.append({'sheet': title, 'kind': 'summary'})
                elif any(_text(v) for row in rows for v in row):
                    sheet_warnings.append(f'Лист «{title}» не является накопительной или сводной по закрытию и не включён в расчёт.')
                    companions.append({'sheet': title, 'reason': 'Не распознана таблица накопительной или сводной.'})
            if not count:
                raise LedgerProblem('В книге не распознаны накопительные или сводная по закрытию.')
            result['files'].append({'filename': name, 'status': 'parsed', 'sheets': count,
                                    'recognized_sheets': recognized, 'companions': companions,
                                    'warnings': sheet_warnings, 'sha256': hashlib.sha256(payload).hexdigest()})
            result['warnings'].extend(sheet_warnings)
        except LedgerProblem as exc:
            # File names are part of the authenticated import report, not logs.
            files = [*result['files'], {'filename': name, 'status': 'failed', 'warnings': [str(exc)]}]
            read = {f['filename'] for f in files}
            files += [{'filename': n, 'status': 'not_read', 'warnings': ['Импорт остановлен до сохранения.']}
                      for n, _ in members if n not in read]
            raise LedgerProblem(f'Файл «{name}»: {exc}', files=files) from None
    if not result['ledgers'] and not result['summary_contracts']:
        raise LedgerProblem('В архиве не найдено накопительных или договоров.', files=result['files'])
    result['files_count'] = sum(f['status'] == 'parsed' for f in result['files'])
    result['read_files'] = [f['filename'] for f in result['files'] if f['status'] == 'parsed']
    result['companion_files'] = [f['filename'] for f in result['files'] if f['status'] == 'ignored']
    result['unread_files'] = []
    result['ledgers_count'] = len(result['ledgers'])
    result['quantity_rows_count'] = sum(len(l['items']) for l in result['ledgers'])
    result['warnings_count'] = (len(result['warnings']) + sum(len(l['warnings']) + sum(len(i['warnings']) for i in l['items'])
                                                                  for l in result['ledgers'])
                                + sum(len(c['warnings']) for c in result['summary_contracts']))
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_PARSED_BYTES:
        raise LedgerProblem('Разобранные данные слишком велики. Уменьшите объём одного архива.', files=result['files'])
    return result


def _root(project: str, *, create: bool = False) -> Path:
    if not _text(project) or len(project) > 200:
        raise LedgerProblem('Выберите проект.')
    path = monitor._project_dir(project) / 'cumulative'
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextlib.contextmanager
def _lock(root: Path):
    try:
        import fcntl
    except ImportError:
        raise LedgerProblem('Хранилище накопительных недоступно в этой среде.') from None
    fd = os.open(root / '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _atomic(path: Path, data: bytes):
    fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _snapshot_path(root: Path, stem: str) -> Path:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', stem):
        raise LedgerProblem('Неверный идентификатор архива.')
    path = root / f'{stem}.json'
    if path.resolve().parent != root.resolve():
        raise LedgerProblem('Неверный идентификатор архива.')
    return path


def _brief(snapshot: dict) -> dict:
    return {key: snapshot.get(key) for key in ('snapshot_id', 'taken_at', 'loaded_at', 'filename',
                                              'files_count', 'ledgers_count', 'quantity_rows_count', 'warnings_count')}


def _import_result(snapshot: dict, *, duplicate: bool) -> dict:
    """Return an actionable protocol without transferring the whole manifest.

    Row problems precede general methodology notes, so the bounded preview does
    not hide an overrun behind repeated annual-scope notices. Counts include
    every distinct issue, including the portion omitted from the preview.
    """
    issues, seen = [], set()
    total = 0

    def add(message, source):
        nonlocal total
        source = source or {}
        row = source.get('row')
        explicit_row = re.match(r'^Строка (\d+):', str(message))
        if explicit_row:
            row = int(explicit_row.group(1))
        item = {'filename': source.get('filename', ''), 'sheet': source.get('sheet', ''),
                'row': row, 'message': str(message)}
        key = (item['filename'], item['sheet'], item['row'], item['message'])
        if key in seen:
            return
        seen.add(key)
        total += 1
        if len(issues) < MAX_ISSUES:
            issues.append(item)

    for ledger in snapshot.get('ledgers', []):
        for item in ledger.get('items', []):
            for message in item.get('warnings', []):
                add(message, item.get('source'))
    file_messages = set()
    for file in snapshot.get('files', []):
        for message in file.get('warnings', []):
            add(message, {'filename': file.get('filename', '')})
            file_messages.add(str(message))
    for ledger in snapshot.get('ledgers', []):
        for message in ledger.get('warnings', []):
            add(message, ledger.get('source'))
    for contract in snapshot.get('summary_contracts', []):
        for message in contract.get('warnings', []):
            add(message, contract.get('source'))
    for message in snapshot.get('warnings', []):
        if str(message) not in file_messages:
            add(message, {})
    return {**_brief(snapshot), 'files': snapshot['files'], 'warnings': snapshot['warnings'],
            'duplicate': duplicate, 'issues': issues, 'issues_count': total,
            'issues_overflow_count': max(0, total-len(issues))}


def store_archive(project: str, data: bytes, taken_at: Any, filename: str = '') -> dict:
    day = _iso(taken_at)
    digest = hashlib.sha256(data).hexdigest()
    stem = f'{day}-{digest}'
    # Validate every input before creating a project or persisting any bytes.
    parsed = parse_archive(data, filename)
    root = _root(project, create=True)
    with _lock(root):
        existing = list(root.glob(f'{day}-*.json'))
        if existing:
            path = _snapshot_path(root, stem)
            if len(existing) == 1 and existing[0] == path:
                stored = json.loads(path.read_text(encoding='utf-8'))
                return _import_result(stored, duplicate=True)
            raise LedgerConflict('Архив на эту дату уже загружен. Выберите дату нового среза; предыдущий архив сохранён.')
        stored = {**parsed, 'snapshot_id': stem, 'taken_at': day,
                  'loaded_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'filename': PurePosixPath(filename).name[:240] if filename else 'Накопительные.zip',
                  'sha256': digest}
        raw_path = root / f'{stem}.zip'
        try:
            _atomic(raw_path, data)
            # JSON is the commit marker; list/read never expose an incomplete write.
            _atomic(_snapshot_path(root, stem), json.dumps(stored, ensure_ascii=False, allow_nan=False).encode())
        except Exception:
            raw_path.unlink(missing_ok=True)
            raise
        return _import_result(stored, duplicate=False)


def list_snapshots(project: str) -> list[dict]:
    root = _root(project)
    if not root.exists():
        return []
    out = []
    for path in sorted(root.glob('*.json'), reverse=True):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', path.stem):
            continue
        checked = _snapshot_path(root, path.stem)
        try:
            snapshot = json.loads(checked.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise LedgerProblem('Сохранённый архив не читается. Обратитесь к администратору.') from None
        out.append(_brief(snapshot))
    return out


def basis_metadata_current(snapshot: dict) -> bool:
    return snapshot.get('parser_schema') == PARSER_SCHEMA and all(
        item.get(field) in {'with_vat', 'without_vat', 'unspecified', 'conflicting'}
        for ledger in snapshot.get('ledgers') or [] for item in ledger.get('items') or []
        for field in ('planned_amount_basis', 'completed_amount_basis'))


def _current_archive(data: bytes, digest: str, filename: str) -> dict:
    """Bounded process cache of parsed evidence, never original bytes or state.

    The caller verifies the ZIP hash on every read, including cache hits. JSON
    gives each consumer its own copy and bounds retained private data to 8 MiB.
    """
    key = (PARSER_SCHEMA, digest, filename)
    with _PARSE_CACHE_LOCK:
        cached = _PARSE_CACHE.get(key)
        if cached is not None:
            _PARSE_CACHE.move_to_end(key)
    if cached is not None:
        return json.loads(cached)
    parsed = parse_archive(data, filename)
    encoded = json.dumps(parsed, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(encoded) <= _PARSE_CACHE_BYTES:
        with _PARSE_CACHE_LOCK:
            _PARSE_CACHE[key] = encoded
            _PARSE_CACHE.move_to_end(key)
            while len(_PARSE_CACHE) > _PARSE_CACHE_ENTRIES:
                _PARSE_CACHE.popitem(last=False)
    return parsed


def _preserve_source_indices(previous: dict, parsed: dict) -> dict:
    """Keep persisted li:ii bindings on the same immutable source cells.

    A newer parser may retain previously omitted work rows. Appending these
    rows preserves existing ids without hiding the newly recovered evidence.
    An old id with no unique source counterpart must fail rather than point to
    a different work. Coordinates are safe here because the ZIP hash is fixed.
    """
    def source_key(value):
        source = value.get('source') or {}
        key = tuple(source.get(field) for field in ('filename', 'sheet', 'row'))
        return key if all(key) else None

    def ordered(old, new, *, ledger=False):
        index = {}
        for value in new:
            key = source_key(value)
            if key is None or key in index:
                raise LedgerProblem('После обновления разбора источник позиции не определяется однозначно; прежние привязки не перенесены.')
            index[key] = value
        aligned, used = [], set()
        for value in old:
            key = source_key(value)
            if key is None or key not in index or key in used:
                raise LedgerProblem('После обновления разбора прежняя позиция не найдена в исходном архиве; привязки требуют проверки.')
            current = index[key]
            if ledger:
                current['items'] = ordered(value.get('items') or [], current.get('items') or [])
            aligned.append(current)
            used.add(key)
        return aligned + [value for value in new if source_key(value) not in used]

    return dict(parsed, ledgers=ordered(previous.get('ledgers') or [], parsed.get('ledgers') or [], ledger=True))


def read_snapshot(project: str, snapshot_id: str) -> dict:
    """Read one immutable import through the current source parser.

    Old manifests never need another upload. Reparse only the retained original
    ZIP, verify its hash, and keep all snapshot bindings and stored bytes intact.
    """
    root = _root(project)
    path = _snapshot_path(root, snapshot_id)
    try:
        snapshot = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise LedgerProblem('Сохранённый архив не читается. Обратитесь к администратору.') from None
    if not basis_metadata_current(snapshot):
        raw = root / (snapshot_id + '.zip')
        if raw.resolve().parent != root.resolve():
            raise LedgerProblem('Неверное расположение исходного архива.')
        if raw.is_file():
            try:
                with raw.open('rb') as handle:
                    data = handle.read(MAX_ARCHIVE_BYTES + 1)
            except OSError:
                raise LedgerProblem('Сохранённый исходный архив не читается.') from None
            if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != snapshot_id[11:]:
                raise LedgerProblem('Исходный архив не совпадает с сохранённым отпечатком.')
            parsed = _current_archive(data, snapshot_id[11:], snapshot.get('filename') or 'Накопительные.zip')
            parsed = _preserve_source_indices(snapshot, parsed)
            return {**snapshot, **parsed, 'source_parse_state': 'refreshed'}
        return {**_restore_period_dates(snapshot), 'source_parse_state': 'original_unavailable'}
    return {**_restore_period_dates(snapshot), 'source_parse_state': 'current'}


def latest_snapshot(project: str, cut: str = '') -> dict | None:
    cutoff = _iso(cut) if cut else dt.date.today().isoformat()
    snapshots = [s for s in list_snapshots(project) if s['taken_at'] <= cutoff]
    return read_snapshot(project, snapshots[0]['snapshot_id']) if snapshots else None


def effective_snapshot(project: str, cut: str = '', *, snapshot: dict | None = None) -> dict | None:
    """One read-only header decision projection for contracts and quantities."""
    snapshot = latest_snapshot(project, cut) if snapshot is None else snapshot
    if snapshot is None:
        return None
    import developaid_monitor_header_confirmations as confirmations
    try:
        return confirmations.apply(project, snapshot, _iso(cut) if cut else dt.date.today().isoformat())
    except confirmations.ConfirmationProblem as exc:
        raise LedgerProblem(str(exc)) from None
