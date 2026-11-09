"""Narrow, reconciled monetary provenance for economic FM admin leaves.

Supported formulas are SUMIFS over one named Excel table (code and month
criteria), optionally multiplied by (1 - a numeric cell), and SUMPRODUCT over
an explicit rectangular budget range with code/month equality criteria. This
is not an Excel evaluator. Unsupported expressions never acquire a bank split.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

_CELL = r'\$?[A-Z]{1,3}\$?[1-9][0-9]*'
_REF = r'([^\[\],()]+)\[([^\[\]]+)\]'
_SUMIFS = re.compile(r'^=SUMIFS\(' + _REF + ',' + _REF + ',(' + _CELL + '),'
                       + _REF + ',(' + _CELL + r')\)/([0-9.]+)(?:\*\(1-(' + _CELL + r')\))?$')
_SHEET = r"(?:'([^']+)'|([^!(),*]+))!"
_PRODUCT = re.compile(r'^=SUMPRODUCT\(' + _SHEET + r'(\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+)\*\('
                      + _SHEET + r'(\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+)=(' + _CELL + r')\)\*\('
                      + _SHEET + r'(\$?[A-Z]+\$?\d+:\$?[A-Z]+\$?\d+)=(' + _CELL + r')\)\)/([0-9.]+)$')


def _number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _code(value: Any) -> str:
    text = str(value or '').strip().rstrip('.')
    return text if re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', text) else ''


def _day(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date() if value.time() == dt.time() else None
    return value if isinstance(value, dt.date) else None


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=.01)


def _tables(raw: bytes) -> dict:
    """Bind table names to their owning sheet via OOXML relationships."""
    ns = {'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rels = {e.attrib['Id']: posixpath.normpath('xl/' + e.attrib['Target'].lstrip('/'))
                if not e.attrib['Target'].startswith('/') else e.attrib['Target'].lstrip('/')
                for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        for sheet in ET.fromstring(z.read('xl/workbook.xml')).findall('{*}sheets/{*}sheet'):
            target = rels[sheet.attrib['{' + ns['r'] + '}id']]
            directory, name = posixpath.split(target)
            path = directory + '/_rels/' + name + '.rels'
            if path not in z.namelist():
                continue
            for rel in ET.fromstring(z.read(path)):
                if not rel.attrib.get('Type', '').endswith('/table'):
                    continue
                dest = rel.attrib['Target']
                dest = dest.lstrip('/') if dest.startswith('/') else posixpath.normpath(directory + '/' + dest)
                node = ET.fromstring(z.read(dest))
                cols = [c.attrib['name'] for c in node.findall('{*}tableColumns/{*}tableColumn')]
                result[node.attrib['displayName']] = {'sheet': sheet.attrib['name'],
                    'bounds': range_boundaries(node.attrib['ref']), 'columns': cols,
                    'totals': int(node.attrib.get('totalsRowCount', 0)),
                    'headers': int(node.attrib.get('headerRowCount', 1))}
    return result


class _Reader:
    def __init__(self, raw: bytes, values: Any, sheet: str, bank_assignments=None):
        self.values, self.sheet, self.grids = values, sheet, {}
        self.bank_assignments = bank_assignments or {}
        import hashlib
        self.source_sha256 = hashlib.sha256(raw).hexdigest()
        self.tables = _tables(raw)
        formulas = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        try:
            self.formulas = list(formulas[sheet].iter_rows(values_only=True))
        finally:
            formulas.close()

    def grid(self, sheet):
        if sheet not in self.grids:
            self.grids[sheet] = list(self.values[sheet].iter_rows(values_only=True))
        return self.grids[sheet]

    def cell(self, sheet, row, column):
        grid = self.grid(sheet)
        return grid[row - 1][column - 1] if 0 < row <= len(grid) and 0 < column <= len(grid[row - 1]) else None

    def ref(self, ref):
        return self.cell(self.sheet, *coordinate_to_tuple(ref.replace('$', '')))

    def split(self, formula, code, month):
        text = getattr(formula, 'text', formula)
        if not isinstance(text, str):
            raise ValueError('формула денежного источника не поддержана')
        m = _SUMIFS.fullmatch(text)
        if m:
            table, amount, table2, codes, code_ref, table3, dates, month_ref, divisor, coefficient = m.groups()
            if table != table2 or table != table3 or table not in self.tables:
                raise ValueError('SUMIFS ссылается не на одну известную таблицу')
            if _code(self.ref(code_ref)) != code or _day(self.ref(month_ref)) != month:
                raise ValueError('критерии SUMIFS не совпадают со строкой и месяцем модели')
            meta = self.tables[table]
            left, top, right, bottom = meta['bounds']
            try:
                ac, cc, dc, bc = [left + meta['columns'].index(x) for x in (amount, codes, dates, 'Код банк')]
            except ValueError as exc:
                raise ValueError('в таблице источника нет явной колонки «Код банк» или критерия') from exc
            factor = 1.
            refs = []
            if coefficient:
                number = _number(self.ref(coefficient))
                if number is None or not 0 <= number <= 1:
                    raise ValueError('коэффициент распределения не является числом от 0 до 1')
                factor = 1 - number
                refs.append({'sheet': self.sheet, 'cell': coefficient.replace('$', ''), 'value': number})
            selected = [(r, ac) for r in range(top + meta['headers'], bottom + 1 - meta['totals'])
                        if self.cell(meta['sheet'], r, cc) == self.ref(code_ref)
                        and _day(self.cell(meta['sheet'], r, dc)) == month]
            return self._amounts(meta['sheet'], selected, bc, divisor, factor, refs)
        m = _PRODUCT.fullmatch(text)
        if m:
            p = m.groups()
            sheet, matrix = p[0] or p[1], p[2]
            sheet2, codes, code_ref = p[3] or p[4], p[5], p[6]
            sheet3, dates, month_ref, divisor = p[7] or p[8], p[9], p[10], p[11]
            if sheet != sheet2 or sheet != sheet3 or sheet not in self.values.sheetnames:
                raise ValueError('SUMPRODUCT ссылается не на один известный лист')
            if _code(self.ref(code_ref)) != code or _day(self.ref(month_ref)) != month:
                raise ValueError('критерии SUMPRODUCT не совпадают со строкой и месяцем модели')
            l, t, r, b = range_boundaries(matrix)
            cl, ct, cr, cb = range_boundaries(codes)
            dl, ht, dr, hb = range_boundaries(dates)
            if cl != cr or (ct, cb) != (t, b) or ht != hb or (dl, dr) != (l, r):
                raise ValueError('размеры денежных и критериальных диапазонов не согласованы')
            header = self.grid(sheet)[ht - 1]
            banks = [i + 1 for i, value in enumerate(header) if str(value or '').strip().lower() == 'код банк']
            if len(banks) != 1:
                raise ValueError('денежный источник не имеет единственной явной колонки «Код банк»')
            columns = [c for c in range(l, r + 1) if _day(self.cell(sheet, ht, c)) == month]
            if len(columns) > 1:
                raise ValueError('в денежном источнике месяц повторён')
            selected = [(row, col) for row in range(t, b + 1)
                        if self.cell(sheet, row, cl) == self.ref(code_ref) for col in columns]
            return self._amounts(sheet, selected, banks[0], divisor, 1., [])
        raise ValueError('формула денежного источника не поддержана')

    def _amounts(self, sheet, cells, bank_col, divisor, factor, refs):
        try:
            denominator = _number(float(divisor))
        except ValueError:
            denominator = None
        if denominator is None or denominator <= 0:
            raise ValueError('масштаб денежной формулы не подтверждён')
        rows, amounts = [], defaultdict(float)
        for row, col in cells:
            raw = self.cell(sheet, row, col)
            # Excel SUMIFS/SUMPRODUCT treats genuinely empty numeric cells as
            # zero; an error/string is not accepted as a cached numeric zero.
            amount = 0. if raw is None else _number(raw)
            if amount is None:
                raise ValueError('денежный диапазон содержит ошибку или нечисловое значение')
            amount *= factor * 1000 / denominator
            original = self.cell(sheet, row, bank_col)
            missing = original is None or isinstance(original, str) and not original.strip()
            bank = _code(original)
            from developaid_finance_allocations import source_cell_id
            identifier = source_cell_id(self.source_sha256, sheet, row, bank_col, col)
            decision = self.bank_assignments.get(identifier)
            if decision:
                if (not missing or decision.get('row_id') != identifier
                        or decision.get('source_sha256') != self.source_sha256
                        or decision.get('basis') != 'owner_instruction'
                        or decision.get('actor') != 'administrator'
                        or not re.fullmatch(r'[123](?:\.[0-9]+)+', decision.get('bank_code', ''))):
                    raise ValueError('решение владельца не соответствует пустой ячейке этого источника')
                bank = decision['bank_code']
            amounts[bank] += amount
            if amount:
                rows.append({'sheet': sheet, 'row': row, 'amount_column': col,
                             'bank_column': bank_col, 'bank_code': bank, 'amount': amount,
                             'raw_bank_missing': missing, 'raw_bank_code': _code(original),
                             'bank_code_origin': 'owner_instruction' if decision else 'workbook',
                             'owner_decision': dict(decision) if decision else None,
                             'coefficient': factor, 'coefficient_sources': refs})
        return dict(amounts), rows


def admin_allocations(raw: bytes, values: Any, sheet: str, header: int, items: list[dict],
                      bank_chapters: tuple[str, ...] = ('1', '2', '3'), bank_assignments=None) -> dict:
    """Return reconciled monthly parts, preserving every unsupported residual."""
    if header < 2:
        return {}
    try:
        reader = _Reader(raw, values, sheet, bank_assignments)
    except (KeyError, ValueError, zipfile.BadZipFile, ET.ParseError, TypeError):
        return {}
    source = reader.grid(sheet)
    months = [(c, _day(value), str(source[header - 2][c - 1] or '').strip().lower())
              for c, value in enumerate(source[header - 1], 1)
              if _day(value) is not None and c <= len(source[header - 2])
              and str(source[header - 2][c - 1] or '').strip().lower() in ('факт', 'план')]
    output = {}
    for item in items:
        row = item['source']['row']
        parts, proofs, reasons = [], [], []
        field_known = {}
        aggregate_mismatch = False
        for field, label in [('fact', 'факт'), ('plan', 'план')]:
            matched = 0.
            supported = True
            selected = [(c, day) for c, day, kind in months if kind == label]
            if not selected:
                supported = False
                reasons.append(f'{label}: нет помесячных колонок источника')
            for column, day in selected:
                expected = _number(reader.cell(sheet, row, column))
                if expected is None:
                    supported = False
                    reasons.append(f'{label}: отсутствует сохранённая сумма месяца')
                    continue
                expected *= 1000
                try:
                    formula = reader.formulas[row - 1][column - 1]
                    split, evidence = reader.split(formula, item['code'], day)
                    if not _same(sum(split.values()), expected):
                        raise ValueError('денежные строки месяца не равны сохранённой сумме финмодели')
                except (ValueError, IndexError, KeyError) as exc:
                    supported = False
                    reasons.append(f'{label}: {exc}')
                    # The saved model month is known even when its bank split
                    # is not. Retain its calendar and economic amount.
                    matched += expected
                    if expected:
                        parts.append({'field': field, 'month': day.isoformat(),
                                      'bank_code': '', 'bank_chapter': '', 'amount': expected})
                    continue
                matched += expected
                parts.extend({'field': field, 'month': day.isoformat(), 'bank_code': bank,
                              'bank_chapter': bank.split('.')[0] if bank and bank.split('.')[0] in bank_chapters else '',
                              'amount': amount}
                             for bank, amount in split.items() if amount)
                proofs.append({'field': field, 'month': day.isoformat(), 'sheet': sheet,
                               'row': row, 'column': column, 'amount': expected,
                               'formula': getattr(formula, 'text', formula), 'sources': evidence})
            expected_field = _number(item.get(field)) if item.get('known_fields', {}).get(field, True) else None
            residual = expected_field - matched if expected_field is not None else None
            if residual is None or not _same(residual, 0.):
                supported = False
                reasons.append(f'{label}: сумма месяцев не покрывает всю строку финмодели')
            if residual is not None and not _same(residual, 0.):
                aggregate_mismatch = True
            if not supported:
                reasons.append(f'{label}: подтверждённые части сохранены, остаток без денежной главы')
            field_known[field] = supported
        by_chapter = {}
        for part in parts:
            bucket = by_chapter.setdefault(part['bank_chapter'], {'total': 0., 'fact': 0., 'plan': 0., 'monthly': {}})
            bucket[part['field']] += part['amount']
            bucket['total'] += part['amount']
            if part['field'] == 'plan' and part['month']:
                bucket['monthly'][part['month']] = bucket['monthly'].get(part['month'], 0.) + part['amount']
        # Missing aggregate cells are not legacy zeroes. Monthly provenance
        # may still be useful, but never add I - zero(J) - K as a second cost.
        fields = item.get('known_fields') or {}
        if fields.get('total', True):
            economic_difference = item['total'] - sum(split['total'] for split in by_chapter.values())
            if not _same(economic_difference, 0.):
                aggregate_mismatch = True
                reasons.append('ИТОГО строки не равно сумме подтверждённых частей и остатка')
        if aggregate_mismatch:
            # A discrepancy is not a signed bank allocation. Keep the known
            # economic leaf and retain proofs only as diagnostic evidence.
            by_chapter = {'': {'total': item['total'], 'fact': item['fact'], 'plan': item['plan'],
                              'monthly': {m: a for m, a in item['monthly'].items() if a is not None}}}
            reasons.append('противоречие итогов: денежное распределение строки не подтверждено')
            field_known = dict.fromkeys(('fact', 'plan'), False)
        if any(p['amount'] and not p['bank_chapter'] for p in parts):
            reasons.append('часть денежных строк не имеет подтверждённого кода банка')
        output[item['code']] = {'by_chapter': by_chapter, 'parts': parts, 'proofs': proofs,
                                'reasons': list(dict.fromkeys(reasons)),
                                'allocation_known': not reasons,
                                'known_fields': field_known,
                                'basis': 'reconciled_monthly_formula_sources'}
    return output
