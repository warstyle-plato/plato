"""Fixed cached B/P/L observations, never a whole-book export or acceptance.

The application chooses one saved FM and one RSS at/before the cut. Monetary
roles follow existing 1045 readers. Only section/chapter summaries, bounded
primary anchors and typed gaps leave the source. No formula is evaluated.
"""
from __future__ import annotations

import contextlib
import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import math
import re
import zipfile

import developaid_admin_expenses_source as ahr
import developaid_cached_source_audit as audit

PURPOSE = 'budget_funding_cached_cells_v1'
SourceProblem = ahr.SourceProblem
MAX_SOURCE = ahr.MAX_SOURCE
MAX_ROWS = 20000
MAX_COLUMNS = 1000
MAX_CELLS = 2_000_000
MAX_BUDGET_LEAVES = 2000
MAX_SECTIONS = 32
MAX_ISSUES = 64
MAX_OUTPUT = 128 * 1024
MAX_FAILURE_DIAGNOSTIC = 2 * 1024
CHAPTERS = ('1', '2', '3')
ESTIMATE = 'Расчет стоимости строительства'
PAYMENTS = 'Реестр платежей'
_CODE = re.compile(r'[0-9]+(?:\.[0-9]+)*\Z')
_SCALES = {'руб.': 1, 'тыс. руб.': 1000, 'млн руб.': 1000000}
_ROLE_LABELS = {
    'bank_limit': {'смета', 'смета лимит банка', 'сметная стоимость',
        'сметная стоимость с ндс', 'утвержденная сметная стоимость',
        'утвержденная сметная стоимость с ндс', 'лимит банка', 'банковский лимит'},
    'payment_code': {'код', 'код рсс', 'код статьи', 'код статьи рсс', 'код по рсс',
        'код позиции сметы', 'код сметы'},
    'payment_date': {'дата оплаты', 'дата платежа', 'дата платежного поручения',
        'дата п п'},
    'payment_amount': {'сумма', 'сумма оплаты', 'сумма платежа', 'сумма с ндс',
        'сумма оплаты с ндс', 'сумма платежа с ндс'},
}
_ROLE_WORD = re.compile(r'(?<![а-яa-z])(?:код[а-я]*|дат[а-я]*|смет[а-я]*|лимит[а-я]*|'
                        r'опла[а-я]*|сумм[а-я]*|платеж[а-я]*)(?![а-яa-z])')
_UNIT_SUFFIX = re.compile(r'(?:[,;:]?\s*\(?\s*(?:(?:тыс|млн)\.?\s*)?'
                          r'(?:руб\.?|рублей|р\.|₽)\s*\)?[.,;:]*)$')


class _WorksheetSizeProblem(SourceProblem):
    """A rejected sheet's metadata, not a successful source observation."""
    def __init__(self, name, rows, columns):
        super().__init__('worksheet_size_limit')
        self.stage = {'cf_1_new': 'fm_cf', ESTIMATE: 'rss_estimate', PAYMENTS: 'rss_payments'}.get(name)
        self.declared_rows = rows
        self.declared_columns = columns
        self.captured_source = None


def failure_diagnostic(exc):
    """Closed, bounded allowlist. Never serialise arbitrary exception/context."""
    if type(exc) is not _WorksheetSizeProblem:
        return None
    try:
        if exc.stage not in {'fm_cf', 'rss_estimate', 'rss_payments'}:
            return None
        source = exc.captured_source
        if (type(source) is not dict or not isinstance(source.get('sha256'), str)
                or not re.fullmatch('[0-9a-f]{64}', source['sha256'])
                or type(source.get('bytes')) is not int or not 0 <= source['bytes'] <= MAX_SOURCE):
            return None
        raw_rows, raw_columns = exc.declared_rows, exc.declared_columns
        rows = raw_rows if type(raw_rows) is int and 1 <= raw_rows <= 1048576 else None
        columns = raw_columns if type(raw_columns) is int and 1 <= raw_columns <= 16384 else None
        rectangle = rows * columns if rows is not None and columns is not None else None
        result = {
            'schema': 1, 'scope': 'rejected_workbook_dimensions_at_read_time', 'stage': exc.stage,
            'source_identity': {'kind': 'fm' if exc.stage == 'fm_cf' else 'rss',
                                'sha256': source['sha256'], 'bytes': source['bytes']},
            'declared_max_row': rows, 'declared_max_column': columns,
            'declared_rectangle_cells': rectangle,
            'dimension_basis': 'worksheet_metadata_not_verified_content_extents',
            'dimension_state': 'observed' if rectangle is not None else 'partial_or_outside_excel_range',
            'failed_bounds': {
                'rows': raw_rows > MAX_ROWS if type(raw_rows) is int and raw_rows >= 1 else None,
                'columns': raw_columns > MAX_COLUMNS if type(raw_columns) is int and raw_columns >= 1 else None,
                'rectangle_cells': rectangle > MAX_CELLS if rectangle is not None else None},
            'limits': {'rows': MAX_ROWS, 'columns': MAX_COLUMNS, 'rectangle_cells': MAX_CELLS},
            'identity_captured_before_failure_not_pair_confirmation': True,
            'complete_projection': False, 'financial_acceptance': False,
        }
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) <= MAX_FAILURE_DIAGNOSTIC:
            return result
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass
    return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, default=str, separators=(',', ':')).encode()).hexdigest()


def _code(value):
    if isinstance(value, bool):
        return None
    value = str(value or '').strip().rstrip('.')
    return value if len(value) <= 96 and _CODE.fullmatch(value) else None


def _day(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str) and len(value) <= 32:
        for form in ('%Y-%m-%d', '%d.%m.%Y'):
            try:
                return dt.datetime.strptime(value.strip(), form).date()
            except ValueError:
                pass
    return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        text = str(value).strip().replace(' ', '').replace('\xa0', '').replace('\u202f', '').replace(',', '.')
        result = Decimal(text)
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _observation(values, units, *, reason='source_cells_incomplete'):
    values = list(values)
    numbers = [_number(value) for value in values]
    range_problem = any(value is not None and value != 0 and abs(value.adjusted()) > 400
                        for value in numbers)
    with localcontext() as precision:
        precision.prec = 512  # Finite Excel numbers plus the bounded row count.
        raw = (sum(numbers, Decimal(0)) if not range_problem
               and all(value is not None for value in numbers) else None)
        scale = _SCALES.get(units.get('recognized_unit')) if units.get('state') == 'observed' else None
        rubles = raw * scale if raw is not None and scale is not None else None
    def safe(value):
        if value is None:
            return None
        try:
            result = float(value)
        except (ValueError, OverflowError):
            return None
        return result if math.isfinite(result) and (result != 0 or value == 0) else None
    raw_float, rubles_float = safe(raw), safe(rubles)
    return {'state': 'known' if rubles_float is not None else 'unknown',
        'raw_cached_sum': raw_float, 'rubles': rubles_float,
        'raw_cached_sum_decimal': str(raw) if raw is not None else None,
        'rubles_decimal': str(rubles) if rubles is not None else None,
        'reason': None if rubles_float is not None else 'numeric_range_limit' if range_problem else reason if raw is None else
            'unit_not_established' if scale is None else 'numeric_range_limit'}


@contextlib.contextmanager
def _book(raw):
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 4096 or len({m.filename for m in members}) != len(members) \
                    or sum(m.file_size for m in members) > ahr.MAX_EXPANDED:
                raise SourceProblem('workbook_size_limit')
        with contextlib.closing(load_workbook(io.BytesIO(raw), read_only=True,
                data_only=True, keep_links=False)) as book:
            yield book
    except SourceProblem:
        raise
    except Exception:
        raise SourceProblem('workbook_unreadable') from None


class _BoundedWorksheetView:
    """Read-only bounds proved from the complete XML, never a source edit."""
    def __init__(self, sheet, rows, columns):
        self._sheet = sheet
        self.title = sheet.title
        self.max_row = rows
        self.max_column = columns

    def iter_rows(self, **kwargs):
        requested = kwargs.get('max_row')
        if requested is not None and (type(requested) is not int or requested < 1):
            raise ValueError('invalid_bounded_row')
        kwargs['max_row'] = min(requested, self.max_row) if requested is not None else self.max_row
        if kwargs.get('max_col') is None:
            kwargs['max_col'] = self.max_column
        column = kwargs['max_col']
        if type(column) is not int or not 1 <= column <= MAX_COLUMNS or kwargs['max_row'] * column > MAX_CELLS:
            raise ValueError('invalid_bounded_column')
        for key in ('min_row', 'min_col'):
            if key in kwargs and (type(kwargs[key]) is not int or kwargs[key] < 1):
                raise ValueError('invalid_bounded_minimum')
        if kwargs.get('min_row', 1) > kwargs['max_row'] or kwargs.get('min_col', 1) > column:
            return iter(())
        return self._sheet.iter_rows(**kwargs)

    def cell(self, row, column):
        # The complete proof established that coordinates beyond payload extent
        # are blank. Preserve the native blank-cell protocol within old bounds.
        if (type(row) is not int or type(column) is not int
                or not 1 <= row <= MAX_ROWS or not 1 <= column <= MAX_COLUMNS
                or row * column > MAX_CELLS):
            raise ValueError('cell_outside_read_bounds')
        return self._sheet.cell(row, column)


class _ExtentStream:
    def __init__(self, stream):
        self.stream = stream
        self.bytes = 0

    def read(self, size=65536):
        size = min(size, 65536) if size >= 0 else 65536
        chunk = self.stream.read(size)
        self.bytes += len(chunk)
        if self.bytes > ahr.MAX_EXPANDED:
            raise ValueError('extent_read_limit')
        return chunk


def _extent_coordinate(value):
    if not isinstance(value, str):
        raise ValueError('coordinate_missing')
    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', value)
    if match is None:
        raise ValueError('coordinate_invalid')
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord('A') + 1
    row = int(match[2])
    if row > 1048576 or column > 16384:
        raise ValueError('coordinate_outside_excel')
    return row, column


def _verified_payload_extent(sheet):
    """A failed/ambiguous proof returns None, never an empty successful sheet.

    Values/formula text are not inspected or retained. All payload coordinates,
    including uncached/shared formulas, are checked before a bounded view exists.
    """
    try:
        from lxml import etree
        namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        worksheet, data, row_tag, cell_tag = (namespace + name for name in ('worksheet', 'sheetData', 'row', 'c'))
        stack = []
        data_seen = False
        active_row = None
        previous_row = previous_column = 0
        active_cell = None
        max_row = max_column = nodes = cells = 0

        def include(row, column):
            nonlocal max_row, max_column
            max_row, max_column = max(max_row, row), max(max_column, column)
            if max_row > MAX_ROWS or max_column > MAX_COLUMNS or max_row * max_column > MAX_CELLS:
                raise ValueError('payload_size_limit')

        with sheet._get_source() as raw:
            stream = _ExtentStream(raw)
            parsed = etree.iterparse(stream, events=('start', 'end'), resolve_entities=False,
                load_dtd=False, no_network=True, recover=False, huge_tree=False)
            for event, element in parsed:
                tag = element.tag
                if not isinstance(tag, str):
                    raise ValueError('entity_or_unknown_node')
                local = tag.rsplit('}', 1)[-1]
                if event == 'start':
                    parent = stack[-1] if stack else None
                    stack.append(tag)
                    nodes += 1
                    if len(stack) > 64 or nodes > MAX_CELLS * 8:
                        raise ValueError('xml_resource_limit')
                    if len(stack) == 1:
                        if tag != worksheet or element.getroottree().docinfo.doctype:
                            raise ValueError('worksheet_namespace_or_doctype')
                    if local in ('sheetData', 'row', 'c', 'v', 'f', 'is') and tag != namespace + local:
                        raise ValueError('payload_namespace_unknown')
                    if tag == data:
                        if parent != worksheet or data_seen:
                            raise ValueError('sheet_data_ambiguous')
                        data_seen = True
                    elif tag == row_tag:
                        reference = element.get('r', '')
                        if parent != data or not re.fullmatch(r'[1-9][0-9]{0,6}', reference):
                            raise ValueError('row_reference_unknown')
                        active_row = int(reference)
                        if not previous_row < active_row <= 1048576:
                            raise ValueError('row_reference_order')
                        previous_row, previous_column = active_row, 0
                    elif tag == cell_tag:
                        if parent != row_tag or active_row is None or active_cell is not None:
                            raise ValueError('cell_structure_unknown')
                        row, column = _extent_coordinate(element.get('r'))
                        if row != active_row or column <= previous_column:
                            raise ValueError('cell_reference_order')
                        previous_column = column
                        cells += 1
                        if cells > MAX_CELLS:
                            raise ValueError('xml_cell_resource_limit')
                        active_cell = {'row': row, 'column': column,
                            'payload': element.get('t', 'n') != 'n' or bool(set(element.attrib) - {'r', 's', 't'})}
                    elif active_cell is not None:
                        # Even empty v/f/is and unknown cell children are not
                        # proven formatting-only. Formula areas are also bounded.
                        active_cell['payload'] = True
                        if tag == namespace + 'f' and 'ref' in element.attrib:
                            area = element.get('ref').split(':')
                            if not 1 <= len(area) <= 2:
                                raise ValueError('formula_area_unknown')
                            first = _extent_coordinate(area[0])
                            last = _extent_coordinate(area[-1])
                            if first[0] > last[0] or first[1] > last[1]:
                                raise ValueError('formula_area_order')
                            include(*last)
                    elif local in ('v', 'f', 'is'):
                        raise ValueError('payload_outside_cell')
                else:
                    if not stack or stack.pop() != tag:
                        raise ValueError('xml_structure_unknown')
                    if element.tail and element.tail.strip():
                        raise ValueError('mixed_worksheet_content')
                    if tag in (cell_tag, row_tag, data) and element.text and element.text.strip():
                        raise ValueError('mixed_cell_or_row_content')
                    if tag == cell_tag:
                        if active_cell['payload'] or len(element):
                            include(active_cell['row'], active_cell['column'])
                        active_cell = None
                    elif tag == row_tag:
                        active_row = None
                    element.clear()
                    while element.getprevious() is not None:
                        del element.getparent()[0]
            # Complete parse and read through ZIP EOF/CRC, not an XML prefix.
            if stream.read(1) or stack or not data_seen or not max_row or not max_column:
                raise ValueError('extent_not_proven')
        return max_row, max_column
    except Exception:
        return None


def _sheet(book, name):
    if name not in book.sheetnames:
        raise SourceProblem('required_sheet_missing')
    sheet = book[name]
    if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS \
            or sheet.max_row * sheet.max_column > MAX_CELLS:
        extent = _verified_payload_extent(sheet)
        if extent is None:
            raise _WorksheetSizeProblem(name, sheet.max_row, sheet.max_column)
        return _BoundedWorksheetView(sheet, *extent)
    return sheet


def _header(sheet, rows):
    evidence = ahr._HeaderEvidence(sheet.max_column)
    for index, cells in enumerate(sheet.iter_rows(max_row=min(rows, sheet.max_row)), 1):
        evidence.add(index, cells)
    result = evidence.result()
    result['context']['sheet'] = sheet.title
    return result


def _role(sheet, column, role):
    """Fixed semantic labels, with contradictory headers failing closed.

    A token such as 'оплата' is not enough: 'Дата оплаты' must never make an
    amount column valid, and 'Оплачено по смете' cannot establish a limit.
    Only coordinates/role names leave the header, never arbitrary text.
    """
    cells, conflicts = [], []
    for row in sheet.iter_rows(max_row=min(9, sheet.max_row), min_col=column, max_col=column):
        cell = row[0]
        if not isinstance(cell.value, str) or len(cell.value) > 32768:
            continue
        text = cell.value.lower().replace('ё', 'е').replace('\xa0', ' ').replace('\u202f', ' ').strip()
        text = _UNIT_SUFFIX.sub('', text)
        text = re.sub(r'[\s,;:()[\].—–/\\-]+', ' ', text).strip()
        if text in _ROLE_LABELS[role]:
            cells.append(cell.coordinate)
        elif _ROLE_WORD.search(text):
            conflicts.append(cell.coordinate)
    return {'state': 'ambiguous' if cells and conflicts else 'unknown' if conflicts or not cells else 'observed',
            'role': role, 'cells': cells, 'conflicting_cells': conflicts}


def _cell(cell, coordinate):
    # read_only openpyxl EmptyCell has neither coordinate nor row. The fixed
    # reader already knows its position; a missing cell must stay missing.
    return {'cell': coordinate, **ahr._raw(cell)}


def _finance(raw):
    from openpyxl.utils import get_column_letter
    with _book(raw) as book:
        sheet = _sheet(book, 'cf_1_new')
        header, columns = None, None
        for index, cells in enumerate(sheet.iter_rows(max_row=min(80, sheet.max_row)), 1):
            labels = [str(c.value or '').strip().lower().replace('ё', 'е') for c in cells]
            if all(name in labels for name in ('итого', 'факт', 'план')):
                if any(labels.count(name) != 1 for name in ('итого', 'факт', 'план')):
                    raise SourceProblem('finance_columns_ambiguous')
                header = index
                columns = dict(zip(('total', 'fact', 'plan'), [labels.index(k) for k in ('итого', 'факт', 'план')]))
                break
        if columns is None:
            raise SourceProblem('finance_columns_missing')
        units = _header(sheet, header)
        items, codes = [], set()
        for index, cells in enumerate(sheet.iter_rows(min_row=header+1,
                max_col=max(2, *columns.values())+1), header+1):
            code = _code(cells[2].value)
            if not code or not (code == '2' or code.startswith('2.') or code == '3.1.4.1.3'):
                continue
            if code in codes:
                raise SourceProblem('finance_codes_ambiguous')
            codes.add(code)
            items.append({'code': code, 'code_cell': cells[2].coordinate,
                'cells': {key: _cell(cells[col], f'{get_column_letter(col+1)}{index}')
                          for key, col in columns.items()}})
        parents = {'.'.join(parts[:i]) for code in codes
                   for parts in [code.split('.')] for i in range(1, len(parts))}
        leaves = [item for item in items if item['code'] not in parents]
        counted = [item for item in leaves if item['code'] == '3.1.4.1.3' or
                   item['code'].startswith('2.') and item['code'] != '2.4.5'
                   and not item['code'].startswith('2.4.5.')]
        if not any(item['code'].startswith('2.') for item in counted):
            raise SourceProblem('finance_budget_rows_missing')
        if len(counted) > MAX_BUDGET_LEAVES:
            raise SourceProblem('projection_size_limit')
        def section(code):
            return '.'.join(code.split('.')[:2]) if code.startswith('2.') else code
        sections = sorted({section(item['code']) for item in counted})
        if len(sections) > MAX_SECTIONS:
            raise SourceProblem('projection_size_limit')
        by_code = {item['code']: item for item in items}
        rows = []
        for code in sections:
            chosen = [item for item in counted if section(item['code']) == code]
            rows.append({'code': code, 'leaf_count': len(chosen),
                'primary_anchor': by_code.get(code),
                'leaf_cells_sha256': _digest(chosen),
                'observations': {key: _observation((item['cells'][key]['cached_value'] for item in chosen), units)
                                 for key in ('total', 'fact', 'plan')}})
        return {'state': 'read', 'sheet': 'cf_1_new', 'unit_evidence': units,
            'header_cells': {k: sheet.cell(header, v+1).coordinate for k, v in columns.items()},
            'budget_scope': 'leaf_2_except_tax_2.4.5_plus_bank_commission_3.1.4.1.3',
            'budget_composition_completeness_verified': False,
            'source_costs_root_anchor': by_code.get('2'),
            'source_excluded_tax_anchor': by_code.get('2.4.5'),
            'leaf_count': len(counted), 'leaf_cells_sha256': _digest(counted), 'sections': rows,
            'observations': {key: _observation((i['cells'][key]['cached_value'] for i in counted), units)
                             for key in ('total', 'fact', 'plan')}}


def _rss_copy(project, cut):
    import developaid_monitor as monitor
    aliases_reader = reader = None
    try:
        base = monitor._SNAPSHOT_DIR.absolute()
        aliases_reader = audit.Reader(base, 'aliases')
        aliases = aliases_reader.read('.aliases.json')
        value = audit._json(aliases[0]) if aliases else {'aliases': {}}
        if not isinstance(value, dict) or not isinstance(value.get('aliases'), dict):
            raise SourceProblem('project_identity_invalid')
        original = audit._namespace(monitor._slug(project))
        selected = audit._namespace(value['aliases'].get(original, original))
        if selected in value['aliases'] and value['aliases'][selected] != selected:
            raise SourceProblem('project_identity_invalid')
        reader = audit.Reader(base / selected, 'finance')
        eligible = [name for name in audit._estimate_members(reader) if name[:-5] <= cut]
        if not eligible:
            return None, None, {'state': 'source_missing_at_cut', 'namespace_sha256': hashlib.sha256(selected.encode()).hexdigest()}
        name = eligible[-1]
        source = reader.read('estimate/'+name, max_bytes=MAX_SOURCE)
        metadata = reader.read('estimate/'+name[:-5]+'.json', max_bytes=65536)
        if not source or not metadata:
            raise SourceProblem('rss_source_metadata_missing')
        meta = audit._json(metadata[0])
        if not isinstance(meta, dict) or meta.get('taken_at') != name[:-5] \
                or type(meta.get('bytes')) is not int or meta['bytes'] != source[1]['bytes']:
            raise SourceProblem('rss_source_metadata_mismatch')
        if 'source_sha256' in meta and meta['source_sha256'] != source[1]['sha256']:
            raise SourceProblem('rss_source_pair_mismatch')
        checked_source = reader.read('estimate/'+name, max_bytes=MAX_SOURCE)
        checked_meta = reader.read('estimate/'+name[:-5]+'.json', max_bytes=65536)
        if checked_source is None or checked_meta is None \
                or checked_source[1] != source[1] or checked_meta[1] != metadata[1]:
            raise SourceProblem('source_changed')
        if [n for n in audit._estimate_members(reader) if n[:-5] <= cut] != eligible:
            raise SourceProblem('source_changed')
        reader.check_identity()
        if aliases_reader.read('.aliases.json') != aliases:
            raise SourceProblem('source_changed')
        return source[0], meta, {'state': 'read', 'sha256': source[1]['sha256'], 'bytes': source[1]['bytes'],
            'metadata_sha256': metadata[1]['sha256'], 'version_date': name[:-5],
            'metadata_bound_to_bytes': 'source_sha256' in meta,
            'namespace_sha256': hashlib.sha256(selected.encode()).hexdigest(),
            'aliases_sha256': aliases[1]['sha256'] if aliases else None}
    except (audit.AuditError, OSError, ValueError) as exc:
        if isinstance(exc, SourceProblem):
            raise
        raise SourceProblem('rss_source_unavailable') from None
    finally:
        if reader is not None:
            reader.close()
        if aliases_reader is not None:
            aliases_reader.close()


def _bank(raw, cut):
    with _book(raw) as book:
        estimate = _sheet(book, ESTIMATE)
        units = _header(estimate, 9)
        limit_role = _role(estimate, 5, 'bank_limit')
        roots, chapters = {}, {}
        for index, cells in enumerate(estimate.iter_rows(max_col=7), 1):
            code = _code(cells[0].value)
            if not code:
                continue
            if code in roots:
                raise SourceProblem('rss_codes_ambiguous')
            # The explicit canonical code, not row order/adjacency, determines
            # a chapter. A payment code absent from this source stays unknown.
            roots[code] = code.split('.')[0]
            if code in CHAPTERS:
                chapters[code] = {'chapter': code, 'code_cell': cells[0].coordinate,
                    'limit_cell': _cell(cells[4], f'E{index}'),
                    'source_reported_paid_cell': _cell(cells[6], f'G{index}')}
        payments = _sheet(book, PAYMENTS)
        payment_units = _header(payments, 9)
        payment_roles = {'code': _role(payments, 7, 'payment_code'),
            'date': _role(payments, 9, 'payment_date'),
            'amount': _role(payments, 10, 'payment_amount')}
        selected = {ch: [] for ch in CHAPTERS}
        issues, anchors, counts = [], {ch: [] for ch in CHAPTERS}, {'nonempty': 0, 'future': 0, 'outside': 0, 'selected': 0, 'incomplete': 0}
        proof_rows = []
        scope_unknown = False
        for index, cells in enumerate(payments.iter_rows(min_row=10, max_col=12), 10):
            if not any(c.value not in (None, '') for c in cells):
                continue
            counts['nonempty'] += 1
            day = _day(cells[8].value)
            if day is not None and day > cut:
                counts['future'] += 1
                continue
            code = _code(cells[6].value)
            chapter = roots.get(code)
            if chapter is not None and chapter not in CHAPTERS:
                counts['outside'] += 1
                continue
            amount = _cell(cells[9], f'J{index}')
            errors = (['date'] if day is None else []) + (['estimate_code'] if chapter is None else []) \
                + (['amount'] if _number(amount['cached_value']) is None else [])
            scope_unknown = scope_unknown or chapter is None
            counts['selected'] += 1
            row = {'code': code, 'chapter': chapter, 'date': day.isoformat() if day else None,
                'date_cell': f'I{index}', 'code_cell': f'G{index}', 'amount_cell': amount}
            proof_rows.append(row)
            if errors:
                counts['incomplete'] += 1
                if len(issues) < MAX_ISSUES:
                    issues.append({'row': index, 'fields': errors,
                        'cells': {'code': f'G{index}', 'date': f'I{index}', 'amount': f'J{index}'}})
            if chapter in selected:
                selected[chapter].append(amount['cached_value'] if not errors else None)
                if len(anchors[chapter]) < 2:
                    anchors[chapter].append(row)
                else:
                    anchors[chapter][-1] = row
        rows = []
        for chapter in CHAPTERS:
            primary = chapters.get(chapter)
            limit = _observation([primary['limit_cell']['cached_value']] if primary else [None], units,
                reason='chapter_limit_missing_or_invalid')
            paid = _observation(selected[chapter], payment_units)
            if limit_role['state'] != 'observed':
                limit = _observation([None], units, reason='limit_column_role_unknown')
            # Unknown payment code might belong to any selected chapter.
            if scope_unknown:
                paid = _observation([None], payment_units, reason='payment_scope_unknown')
            if any(role['state'] != 'observed' for role in payment_roles.values()):
                paid = _observation([None], payment_units, reason='payment_column_role_unknown')
            rows.append({'chapter': chapter, 'primary': primary, 'observed_limit': limit,
                'observed_payments_at_or_before_cut': paid, 'payment_anchors': anchors[chapter]})
        total_paid = _observation((row['amount_cell']['cached_value'] for row in proof_rows), payment_units)
        if counts['incomplete']:
            total_paid = _observation([None], payment_units, reason='payment_rows_incomplete')
        if any(role['state'] != 'observed' for role in payment_roles.values()):
            total_paid = _observation([None], payment_units, reason='payment_column_role_unknown')
        return {'state': 'read', 'bank_chapters': list(CHAPTERS), 'estimate_sheet': ESTIMATE,
            'payments_sheet': PAYMENTS, 'unit_evidence': units, 'payment_unit_evidence': payment_units,
            'limit_role_evidence': limit_role, 'payment_role_evidence': payment_roles,
            'chapters': rows, 'row_counts': counts, 'incomplete_rows': issues,
            'incomplete_rows_truncated': counts['incomplete'] > len(issues),
            'selected_payment_cells_sha256': _digest(proof_rows),
            'observed_payments_at_or_before_cut': total_paid,
            'payments_complete_through_cut': None,
            'payment_identity_verified': False,
            'coverage_reason': 'Upload date, filename and last payment do not establish completeness through the cut.'}


def capture(project, cut, *, runtime):
    try:
        day = dt.date.fromisoformat(cut)
        if day.isoformat() != cut or day > dt.date.today() or not isinstance(project, str) \
                or not project.strip() or len(project) > 200 or any(c in project for c in ('/', '\\', '\0')):
            raise ValueError()
    except (TypeError, ValueError):
        raise SourceProblem('request_invalid') from None
    fm, meta, fm_source = ahr._copy(project)
    rss, rss_meta, rss_source = _rss_copy(project, cut)
    version = _day(meta.get('taken_at'))
    result = {'schema': 1, 'purpose': PURPOSE, 'cut': cut,
        'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'runtime': {key: str(runtime.get(key) or '')[:64] for key in ('version', 'commit')},
        'finance_source': {**fm_source, 'version_date': version.isoformat() if version else None},
        'rss_source': rss_source, 'values_are_cached_source_observations': True,
        'financial_acceptance': False, 'source_files_written': False,
        'full_BPL_at_cut_confirmed': False, 'formulas_evaluated': False,
        'raw_formula_text_returned': False,
        'observation_scope': 'raw_saved_sources_not_a_historical_financial_verdict'}
    # An undated FM can provide bounded cached source observations, but never
    # money asserted to belong to the selected historical cut. This distinction
    # is explicit in the projection rather than guessed from an upload date.
    eligibility = ('source_date_unknown' if version is None else
                   'source_after_cut' if version > day else 'eligible_version')
    try:
        result['finance'] = {**_finance(fm), 'source_temporal_state': eligibility,
            'amounts_at_cut': None, 'historical_financial_acceptance': False}
        result['bank'] = _bank(rss, day) if rss is not None else {'state': 'source_missing_at_cut'}
    except _WorksheetSizeProblem as exc:
        # The existing post-read coherent-pair checks below have not run.
        source = fm_source if exc.stage == 'fm_cf' else rss_source
        exc.captured_source = ({'sha256': source.get('sha256'), 'bytes': source.get('bytes')}
                               if type(source) is dict else None)
        raise
    _, again_meta, again_fm_source = ahr._copy(project)
    _, again_rss_meta, again_rss_source = _rss_copy(project, cut)
    if meta != again_meta or fm_source != again_fm_source or rss_meta != again_rss_meta or rss_source != again_rss_source:
        raise SourceProblem('source_changed')
    if rss is not None and fm_source['namespace_sha256'] != rss_source['namespace_sha256']:
        raise SourceProblem('project_identity_changed')
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_OUTPUT:
        raise SourceProblem('projection_size_limit')
    return result
