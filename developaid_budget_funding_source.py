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
_EXTENT_REASONS = frozenset({
    'extent_read_limit', 'coordinate_missing', 'coordinate_invalid', 'coordinate_outside_excel',
    'payload_size_limit', 'entity_or_unknown_node', 'xml_resource_limit',
    'worksheet_namespace_or_doctype', 'payload_namespace_unknown', 'sheet_data_ambiguous',
    'row_reference_unknown', 'row_reference_order', 'cell_structure_unknown',
    'cell_reference_order', 'xml_cell_resource_limit', 'formula_area_unknown', 'formula_area_order',
    'payload_outside_cell', 'xml_structure_unknown', 'mixed_worksheet_content',
    'mixed_cell_or_row_content', 'extent_not_proven', 'metadata_formula_structure',
    'parser_unavailable', 'xml_parse_failure', 'zip_integrity_failure',
    'source_stream_failure', 'internal_proof_failure'})
_EXTENT_CONTEXTS = frozenset({'root', 'sheet_data', 'row', 'cell', 'worksheet_metadata', 'unknown'})
_MAIN_QNAME = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_X14_QNAME = '{http://schemas.microsoft.com/office/spreadsheetml/2009/9/main}'
_XM_QNAME = '{http://schemas.microsoft.com/office/excel/2006/main}'
_FORMATTING_FORMULA_PATH = (
    _MAIN_QNAME+'worksheet', _MAIN_QNAME+'extLst', _MAIN_QNAME+'ext',
    _X14_QNAME+'conditionalFormattings', _X14_QNAME+'conditionalFormatting',
    _X14_QNAME+'cfRule', _X14_QNAME+'dataBar', _X14_QNAME+'cfvo', _XM_QNAME+'f')
_FORMATTING_FORMULA_CHECKS = ('path', 'data_seen', 'row_inactive', 'cell_inactive',
    'attributes_empty', 'first_child', 'cfvo_formula', 'rule_data_bar', 'rule_guid',
    'extension_attributes', 'extension_uri')
_DATA_VALIDATION_EXTENSION_PATH = (_MAIN_QNAME+'worksheet', _MAIN_QNAME+'extLst', _MAIN_QNAME+'ext')
_DATA_VALIDATION_PATH = _DATA_VALIDATION_EXTENSION_PATH + (_X14_QNAME+'dataValidations',)
_DATA_VALIDATION_RECORD_PATH = _DATA_VALIDATION_PATH + (_X14_QNAME+'dataValidation',)
_DATA_VALIDATION_FORMULA_PATHS = frozenset(
    _DATA_VALIDATION_RECORD_PATH + (_X14_QNAME+name, _XM_QNAME+'f')
    for name in ('formula1', 'formula2'))
_DATA_VALIDATION_SQREF_PATH = _DATA_VALIDATION_RECORD_PATH + (_XM_QNAME+'sqref',)
_DATA_VALIDATION_EXTENSION_URI = '{CCE6A557-97BC-4B89-ADB6-D9C93CAAB3DF}'
_DATA_VALIDATION_ENUMS = {
    'type': frozenset(('none', 'whole', 'decimal', 'list', 'date', 'time', 'textLength', 'custom')),
    'errorStyle': frozenset(('stop', 'warning', 'information')),
    'operator': frozenset(('between', 'notBetween', 'equal', 'notEqual', 'lessThan',
                          'lessThanOrEqual', 'greaterThan', 'greaterThanOrEqual')),
    'imeMode': frozenset(('noControl', 'off', 'on', 'disabled', 'hiragana', 'fullKatakana',
                         'halfKatakana', 'fullAlpha', 'halfAlpha', 'fullHangul', 'halfHangul'))}
_NAMESPACE_PATH_TOKENS = {
    _MAIN_QNAME+'worksheet': 'worksheet', _MAIN_QNAME+'sheetData': 'sheetData',
    _MAIN_QNAME+'row': 'row', _MAIN_QNAME+'c': 'c', _MAIN_QNAME+'v': 'v',
    _MAIN_QNAME+'f': 'f', _MAIN_QNAME+'is': 'is', _MAIN_QNAME+'extLst': 'extLst',
    _MAIN_QNAME+'ext': 'ext', _X14_QNAME+'conditionalFormattings': 'x14:cfs',
    _X14_QNAME+'conditionalFormatting': 'x14:cf', _X14_QNAME+'cfRule': 'x14:rule',
    _X14_QNAME+'dataBar': 'x14:bar', _X14_QNAME+'cfvo': 'x14:cfvo', _XM_QNAME+'f': 'xm:f'}
_NAMESPACE_PATH_LIMIT = 12
_QNAME_PATH_FINGERPRINT_SCHEMA = 'expanded-qname-path-v1'
_QNAME_PATH_FINGERPRINT_MAX_BYTES = 64 * 1024


class _ExtentProofProblem(ValueError):
    def __init__(self, reason):
        self.reason = reason if isinstance(reason, str) and reason in _EXTENT_REASONS else 'internal_proof_failure'
        super().__init__(self.reason)


def _namespace_rejection(tag):
    """Private failure metadata only; never a namespace acceptance rule."""
    if type(tag) is not str:
        return None
    local = tag.rsplit('}', 1)[-1]
    if local not in ('sheetData', 'row', 'c', 'v', 'f', 'is'):
        return None
    if tag.startswith('{'):
        end = len(tag) - len(local) - 1
        if end < 1 or tag[end] != '}':
            return None
        # Do not encode/copy an unbounded URI merely to truncate it.
        if end - 1 > 256:
            return {'local_name': local, 'namespace_uri': None, 'truncated': True}
        uri = tag[1:end]
    elif tag == local:
        uri = ''
    else:
        return None
    try:
        truncated = len(uri.encode('utf-8')) > 256
    except UnicodeError:
        return None
    return {'local_name': local, 'namespace_uri': None if truncated else uri,
            'truncated': truncated}


def _checked_namespace_structure(value):
    """Only fixed tokens/states; an incomplete path never attests compatibility."""
    if (type(value) is not dict or set(value) != {'path', 'depth', 'truncated', 'other', 'first_unmet', 'checks'}
            or type(value['path']) is not list or type(value['depth']) is not int
            or not 1 <= value['depth'] <= 64 or type(value['truncated']) is not bool
            or type(value['other']) is not bool or type(value['first_unmet']) is not str
            or type(value['checks']) is not list):
        return False
    tokens = frozenset(_NAMESPACE_PATH_TOKENS.values()) | {'other'}
    if (len(value['path']) != min(value['depth'], _NAMESPACE_PATH_LIMIT)
            or any(type(token) is not str or token not in tokens for token in value['path'])
            or value['truncated'] != (value['depth'] > _NAMESPACE_PATH_LIMIT)
            or 'other' in value['path'] and not value['other']
            or not value['truncated'] and value['other'] != ('other' in value['path'])):
        return False
    states = value['checks']
    if (len(states) != len(_FORMATTING_FORMULA_CHECKS)
            or any(type(state) is not str or state not in {'match', 'no_match', 'not_evaluated'} for state in states)):
        return False
    expected_path = [_NAMESPACE_PATH_TOKENS[tag] for tag in _FORMATTING_FORMULA_PATH]
    if (states[0] == 'match') != (not value['truncated'] and value['path'] == expected_path):
        return False
    if value['first_unmet'] == 'none':
        return all(type(state) is str and state == 'match' for state in states)
    if value['first_unmet'] not in _FORMATTING_FORMULA_CHECKS:
        return False
    first = _FORMATTING_FORMULA_CHECKS.index(value['first_unmet'])
    return states == ['match'] * first + ['no_match'] + ['not_evaluated'] * (len(states) - first - 1)


def _namespace_path_fingerprint(stack):
    """Hash a complete bounded QName stack; never return a partial digest."""
    if (type(stack) not in (list, tuple) or not 1 <= len(stack) <= 64
            or any(type(tag) is not str or not tag for tag in stack)
            or sum(len(tag) for tag in stack) > _QNAME_PATH_FINGERPRINT_MAX_BYTES):
        return None
    try:
        # The character precheck bounds even worst-case JSON escaping before
        # encoding; the byte check is on the full canonical representation.
        content = json.dumps({'schema': _QNAME_PATH_FINGERPRINT_SCHEMA, 'path': list(stack)},
            ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, OverflowError):
        return None
    if len(content) > _QNAME_PATH_FINGERPRINT_MAX_BYTES:
        return None
    return {'schema': _QNAME_PATH_FINGERPRINT_SCHEMA, 'sha256': hashlib.sha256(content).hexdigest()}


def _checked_namespace_path_fingerprint(value):
    return (type(value) is dict and set(value) == {'schema', 'sha256'}
            and type(value['schema']) is str and value['schema'] == _QNAME_PATH_FINGERPRINT_SCHEMA
            and type(value['sha256']) is str and len(value['sha256']) == 64
            and re.fullmatch('[0-9a-f]{64}', value['sha256']) is not None)


def _checked_extent_failure(value):
    """Metadata only. Unknown exception text/objects never cross this boundary."""
    fields = {'schema', 'outcome', 'basis', 'complete_proof', 'reason', 'context',
              'candidate_payload_max_row', 'candidate_payload_max_column',
              'candidate_payload_rectangle', 'cell_elements_seen', 'xml_nodes_seen',
              'xml_bytes_observed', 'sheet_data_seen'}
    if type(value) is not dict or set(value) not in (
            fields, fields | {'namespace_rejection'}, fields | {'namespace_rejection', 'namespace_structure'},
            fields | {'namespace_rejection', 'namespace_structure', 'namespace_path_fingerprint'}):
        return None
    if (type(value['schema']) is not int or value['schema'] != 1
            or value['outcome'] != 'rejected' or value['basis'] != 'partial_XML_scan_not_an_accepted_extent'
            or value['complete_proof'] is not False
            or not isinstance(value['reason'], str) or value['reason'] not in _EXTENT_REASONS
            or not isinstance(value['context'], str) or value['context'] not in _EXTENT_CONTEXTS
            or type(value['sheet_data_seen']) is not bool):
        return None
    if 'namespace_rejection' in value:
        metadata = value['namespace_rejection']
        if (value['reason'] != 'payload_namespace_unknown' or type(metadata) is not dict
                or set(metadata) != {'local_name', 'namespace_uri', 'truncated'}
                or type(metadata['local_name']) is not str
                or metadata['local_name'] not in ('sheetData', 'row', 'c', 'v', 'f', 'is')
                or type(metadata['truncated']) is not bool):
            return None
        uri = metadata['namespace_uri']
        if metadata['truncated']:
            if uri is not None:
                return None
        else:
            if type(uri) is not str or len(uri) > 256:
                return None
            try:
                if len(uri.encode('utf-8')) > 256:
                    return None
            except UnicodeError:
                return None
    if 'namespace_structure' in value:
        if (not _checked_namespace_structure(value['namespace_structure'])
                or value['namespace_structure']['first_unmet'] == 'none'):
            return None
    if 'namespace_structure' in value:
        metadata, structure = value['namespace_rejection'], value['namespace_structure']
        qname = ('{' + metadata['namespace_uri'] + '}' + metadata['local_name']
                 if metadata['namespace_uri'] else metadata['local_name'])
        token = _NAMESPACE_PATH_TOKENS.get(qname, 'other')
        if ((token == 'other' and not structure['other'])
                or not structure['truncated'] and structure['path'][-1] != token):
            return None
    if ('namespace_path_fingerprint' in value
            and not _checked_namespace_path_fingerprint(value['namespace_path_fingerprint'])):
        return None
    limits = {'candidate_payload_max_row': 1048576, 'candidate_payload_max_column': 16384,
              'candidate_payload_rectangle': 1048576 * 16384, 'cell_elements_seen': MAX_CELLS + 1,
              'xml_nodes_seen': MAX_CELLS * 8 + 1, 'xml_bytes_observed': ahr.MAX_EXPANDED + 65536}
    for key, limit in limits.items():
        item = value[key]
        if item is not None and (type(item) is not int or not 0 <= item <= limit):
            return None
    rows, columns = value['candidate_payload_max_row'], value['candidate_payload_max_column']
    if ((rows is None) != (columns is None) or rows is not None and (rows < 1 or columns < 1)):
        return None
    if value['candidate_payload_rectangle'] != (rows * columns if rows is not None and columns is not None else None):
        return None
    return dict(value)


class _WorksheetSizeProblem(SourceProblem):
    """A rejected sheet's metadata, not a successful source observation."""
    def __init__(self, name, rows, columns, extent_failure=None):
        super().__init__('worksheet_size_limit')
        self.stage = {'cf_1_new': 'fm_cf', ESTIMATE: 'rss_estimate', PAYMENTS: 'rss_payments'}.get(name)
        self.declared_rows = rows
        self.declared_columns = columns
        self.captured_source = None
        self.extent_failure = extent_failure


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
        extent = _checked_extent_failure(exc.extent_failure)
        if extent is not None:
            enriched = {**result, 'extent_proof': extent}
            if len(json.dumps(enriched, ensure_ascii=False, allow_nan=False).encode()) <= MAX_FAILURE_DIAGNOSTIC:
                return enriched
            if 'namespace_path_fingerprint' in extent:
                enriched['extent_proof'] = {k: v for k, v in extent.items() if k != 'namespace_path_fingerprint'}
                if len(json.dumps(enriched, ensure_ascii=False, allow_nan=False).encode()) <= MAX_FAILURE_DIAGNOSTIC:
                    return enriched
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
            raise _ExtentProofProblem('extent_read_limit')
        return chunk


def _extent_coordinate(value):
    if not isinstance(value, str):
        raise _ExtentProofProblem('coordinate_missing')
    match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', value)
    if match is None:
        raise _ExtentProofProblem('coordinate_invalid')
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord('A') + 1
    row = int(match[2])
    if row > 1048576 or column > 16384:
        raise _ExtentProofProblem('coordinate_outside_excel')
    return row, column


def _formatting_formula_checks(stack, element, data_seen, active_row, active_cell):
    """The original exception predicates, in their original short-circuit order."""
    parents = None
    def ancestor(index):
        nonlocal parents
        if parents is None:
            parents = list(element.iterancestors())
        return parents[index]
    checks = (
        lambda: tuple(stack) == _FORMATTING_FORMULA_PATH,
        lambda: bool(data_seen),
        lambda: active_row is None,
        lambda: active_cell is None,
        lambda: not element.attrib,
        lambda: element.getprevious() is None,
        lambda: dict(ancestor(0).attrib) == {'type': 'formula'},
        lambda: ancestor(2).get('type') == 'dataBar',
        lambda: re.fullmatch(r'\{[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\}',
                            ancestor(2).get('id', '')) is not None,
        lambda: set(ancestor(5).attrib) == {'uri'},
        lambda: ancestor(5).get('uri', '').upper() == '{78C0D931-6437-407D-A8EE-F0AAD7539E65}')
    states = ['not_evaluated'] * len(checks)
    for index, check in enumerate(checks):
        states[index] = 'match' if check() else 'no_match'
        if states[index] == 'no_match':
            break
    return states


def _formatting_formula(stack, element, data_seen, active_row, active_cell):
    """Only the existing standard Excel2010 data-bar threshold exception."""
    return all(state == 'match' for state in _formatting_formula_checks(
        stack, element, data_seen, active_row, active_cell))


def _data_validation_metadata(stack, element, data_seen, active_row, active_cell, root_element, *, end=False):
    """Only the closed standard Excel2010 data-validation metadata subtree.

    Formula and reference text stay opaque. Exact ownership, grammar and public
    attribute types are separate from the unchanged data-bar exception.
    """
    path = tuple(stack)
    formula_wrappers = {p[:-1] for p in _DATA_VALIDATION_FORMULA_PATHS}
    paths = {_DATA_VALIDATION_EXTENSION_PATH, _DATA_VALIDATION_PATH,
             _DATA_VALIDATION_RECORD_PATH, _DATA_VALIDATION_SQREF_PATH,
             *formula_wrappers, *_DATA_VALIDATION_FORMULA_PATHS}
    if (path not in paths or not data_seen or active_row is not None or active_cell is not None):
        return False
    chain = [*reversed(list(element.iterancestors())), element]
    if (len(chain) != len(path) or chain[0] is not root_element
            or tuple(node.tag for node in chain) != path):
        return False
    extension = chain[2]
    if (set(extension.attrib) != {'uri'}
            or extension.get('uri', '').upper() != _DATA_VALIDATION_EXTENSION_URI
            or chain[1].attrib):
        return False

    def attributes(node, *, container=False):
        booleans = {'disablePrompts'} if container else {
            'allowBlank', 'showDropDown', 'showInputMessage', 'showErrorMessage'}
        integers = {'xWindow', 'yWindow', 'count'} if container else set()
        strings = set() if container else {'errorTitle', 'error', 'promptTitle', 'prompt'}
        enums = {} if container else _DATA_VALIDATION_ENUMS
        for name, value in node.attrib.items():
            if name in booleans:
                if value not in {'0', '1', 'false', 'true'}:
                    return False
            elif name in integers:
                if re.fullmatch(r'[0-9]{1,10}', value) is None or int(value) > 2**32 - 1:
                    return False
            elif name in enums:
                if value not in enums[name]:
                    return False
            elif name not in strings:
                return False
        return True

    if len(chain) >= 4 and not attributes(chain[3], container=True):
        return False
    if len(chain) >= 5 and not attributes(chain[4]):
        return False
    if len(chain) >= 6 and chain[5].attrib:
        return False
    if len(chain) >= 7 and chain[6].attrib:
        return False
    previous = element.getprevious()
    previous_tag = previous.tag if previous is not None else None
    if path == _DATA_VALIDATION_PATH and previous is not None:
        return False
    if path == _DATA_VALIDATION_RECORD_PATH and previous_tag not in (None, _X14_QNAME+'dataValidation'):
        return False
    if path in formula_wrappers:
        allowed_previous = (None,) if path[-1] == _X14_QNAME+'formula1' else (None, _X14_QNAME+'formula1')
        if previous_tag not in allowed_previous:
            return False
    if path in _DATA_VALIDATION_FORMULA_PATHS and previous is not None:
        return False
    if path == _DATA_VALIDATION_SQREF_PATH and previous_tag not in (
            None, _X14_QNAME+'formula1', _X14_QNAME+'formula2'):
        return False
    leaf = path in _DATA_VALIDATION_FORMULA_PATHS or path == _DATA_VALIDATION_SQREF_PATH
    if not leaf and element.text and element.text.strip():
        return False
    if end:
        # Streaming cleanup retains only the final already-validated child.
        expected = (_X14_QNAME+'dataValidations' if path == _DATA_VALIDATION_EXTENSION_PATH else
                    _X14_QNAME+'dataValidation' if path == _DATA_VALIDATION_PATH else
                    _XM_QNAME+'sqref' if path == _DATA_VALIDATION_RECORD_PATH else
                    _XM_QNAME+'f' if path in formula_wrappers else None)
        if leaf:
            return len(element) == 0
        if len(element) != 1 or element[0].tag != expected:
            return False
    return True


def _namespace_structure(stack, element, data_seen, active_row, active_cell):
    tokens = [_NAMESPACE_PATH_TOKENS.get(tag, 'other') for tag in stack]
    states = _formatting_formula_checks(stack, element, data_seen, active_row, active_cell)
    return {'path': tokens[:_NAMESPACE_PATH_LIMIT], 'depth': len(stack),
            'truncated': len(stack) > _NAMESPACE_PATH_LIMIT, 'other': 'other' in tokens,
            'first_unmet': (_FORMATTING_FORMULA_CHECKS[states.index('no_match')]
                            if 'no_match' in states else 'none'), 'checks': states}


def _verified_payload_extent(sheet, *, _failure=None):
    """A failed/ambiguous proof returns None, never an empty successful sheet.

    Values/formula text are not inspected or retained. All payload coordinates,
    including uncached/shared formulas, are checked before a bounded view exists.
    """
    max_row = max_column = nodes = cells = 0
    data_seen = False
    context = 'unknown'
    namespace_rejection = None
    namespace_structure = None
    namespace_path_fingerprint = None
    if type(_failure) is dict:
        _failure.pop('namespace_rejection', None)
        _failure.pop('namespace_structure', None)
        _failure.pop('namespace_path_fingerprint', None)
    stream = None
    xml_error = ()
    try:
        from lxml import etree
        xml_error = (etree.XMLSyntaxError,)
        namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        worksheet, data, row_tag, cell_tag = (namespace + name for name in ('worksheet', 'sheetData', 'row', 'c'))
        stack = []
        root_element = data_element = row_element = None
        active_row = None
        previous_row = previous_column = 0
        active_cell = None
        formatting_formula = None
        formatting_threshold = None
        data_validation_extension = None
        data_validation_leaf = None
        data_validation_count = 0

        def include(row, column):
            nonlocal max_row, max_column
            max_row, max_column = max(max_row, row), max(max_column, column)
            if max_row > MAX_ROWS or max_column > MAX_COLUMNS or max_row * max_column > MAX_CELLS:
                raise _ExtentProofProblem('payload_size_limit')

        with sheet._get_source() as raw:
            stream = _ExtentStream(raw)
            parsed = etree.iterparse(stream, events=('start', 'end'), resolve_entities=False,
                load_dtd=False, no_network=True, recover=False, huge_tree=False)
            for event, element in parsed:
                tag = element.tag
                if not isinstance(tag, str):
                    raise _ExtentProofProblem('entity_or_unknown_node')
                local = tag.rsplit('}', 1)[-1]
                if event == 'start':
                    stack.append(tag)
                    context = ('cell' if active_cell is not None or local == 'c' and data in stack else
                               'row' if active_row is not None else 'sheet_data' if data in stack else
                               'root' if len(stack) == 1 else 'worksheet_metadata')
                    nodes += 1
                    if len(stack) > 64 or nodes > MAX_CELLS * 8:
                        raise _ExtentProofProblem('xml_resource_limit')
                    if formatting_formula is not None:
                        raise _ExtentProofProblem('metadata_formula_structure')
                    if formatting_threshold is not None:
                        raise _ExtentProofProblem('metadata_formula_structure')
                    if data_validation_leaf is not None:
                        raise _ExtentProofProblem('metadata_formula_structure')
                    if len(stack) == 1:
                        if tag != worksheet or element.getroottree().docinfo.doctype:
                            raise _ExtentProofProblem('worksheet_namespace_or_doctype')
                        root_element = element
                    data_validation = False
                    starts_data_validation = (
                        tuple(stack) == _DATA_VALIDATION_EXTENSION_PATH
                        and element.get('uri', '').upper() == _DATA_VALIDATION_EXTENSION_URI
                        or tuple(stack) == _DATA_VALIDATION_PATH)
                    if data_validation_extension is not None or starts_data_validation:
                        if not _data_validation_metadata(
                                stack, element, data_seen, active_row, active_cell, root_element):
                            raise _ExtentProofProblem('metadata_formula_structure')
                        data_validation = True
                        if data_validation_extension is None:
                            data_validation_extension = element if len(stack) == 3 else element.getparent()
                            data_validation_count = 0
                        if tuple(stack) == _DATA_VALIDATION_RECORD_PATH:
                            data_validation_count += 1
                        if tag in (_XM_QNAME+'f', _XM_QNAME+'sqref'):
                            data_validation_leaf = element
                    is_formatting_formula = (local == 'f' and tag != namespace+'f'
                        and _formatting_formula(stack, element, data_seen, active_row, active_cell))
                    if is_formatting_formula:
                        formatting_formula = element
                        formatting_threshold = element.getparent()
                    is_data_validation_formula = data_validation and tag == _XM_QNAME+'f'
                    if (local in ('sheetData', 'row', 'c', 'v', 'f', 'is') and tag != namespace + local
                            and not is_formatting_formula and not is_data_validation_formula):
                        namespace_rejection = _namespace_rejection(tag)
                        namespace_structure = _namespace_structure(stack, element, data_seen, active_row, active_cell)
                        namespace_path_fingerprint = _namespace_path_fingerprint(stack)
                        raise _ExtentProofProblem('payload_namespace_unknown')
                    if tag == data:
                        if (tuple(stack) != (worksheet, data) or element.getparent() is not root_element or data_seen):
                            raise _ExtentProofProblem('sheet_data_ambiguous')
                        data_seen = True
                        data_element = element
                    elif tag == row_tag:
                        reference = element.get('r', '')
                        if (tuple(stack) != (worksheet, data, row_tag) or element.getparent() is not data_element
                                or not re.fullmatch(r'[1-9][0-9]{0,6}', reference)):
                            raise _ExtentProofProblem('row_reference_unknown')
                        active_row = int(reference)
                        row_element = element
                        if not previous_row < active_row <= 1048576:
                            raise _ExtentProofProblem('row_reference_order')
                        previous_row, previous_column = active_row, 0
                    elif tag == cell_tag:
                        if (tuple(stack) != (worksheet, data, row_tag, cell_tag) or element.getparent() is not row_element
                                or active_row is None or active_cell is not None):
                            raise _ExtentProofProblem('cell_structure_unknown')
                        row, column = _extent_coordinate(element.get('r'))
                        if row != active_row or column <= previous_column:
                            raise _ExtentProofProblem('cell_reference_order')
                        previous_column = column
                        cells += 1
                        if cells > MAX_CELLS:
                            raise _ExtentProofProblem('xml_cell_resource_limit')
                        active_cell = {'row': row, 'column': column,
                            'payload': element.get('t', 'n') != 'n' or bool(set(element.attrib) - {'r', 's', 't'})}
                    elif active_cell is not None:
                        # Even empty v/f/is and unknown cell children are not
                        # proven formatting-only. Formula areas are also bounded.
                        active_cell['payload'] = True
                        if tag == namespace + 'f' and 'ref' in element.attrib:
                            area = element.get('ref').split(':')
                            if not 1 <= len(area) <= 2:
                                raise _ExtentProofProblem('formula_area_unknown')
                            first = _extent_coordinate(area[0])
                            last = _extent_coordinate(area[-1])
                            if first[0] > last[0] or first[1] > last[1]:
                                raise _ExtentProofProblem('formula_area_order')
                            include(*last)
                    elif local in ('v', 'f', 'is') and not is_formatting_formula and not is_data_validation_formula:
                        raise _ExtentProofProblem('payload_outside_cell')
                else:
                    if (data_validation_extension is not None and not _data_validation_metadata(
                            stack, element, data_seen, active_row, active_cell, root_element, end=True)):
                        raise _ExtentProofProblem('metadata_formula_structure')
                    if (data_validation_extension is not None and tuple(stack) == _DATA_VALIDATION_PATH
                            and element.get('count') is not None and int(element.get('count')) != data_validation_count):
                        raise _ExtentProofProblem('metadata_formula_structure')
                    if not stack or stack.pop() != tag:
                        raise _ExtentProofProblem('xml_structure_unknown')
                    if element.tail and element.tail.strip():
                        raise _ExtentProofProblem('mixed_worksheet_content')
                    if tag in (cell_tag, row_tag, data) and element.text and element.text.strip():
                        raise _ExtentProofProblem('mixed_cell_or_row_content')
                    if tag == cell_tag:
                        if active_cell['payload'] or len(element):
                            include(active_cell['row'], active_cell['column'])
                        active_cell = None
                    elif tag == row_tag:
                        active_row = None
                        row_element = None
                    if element is formatting_formula:
                        formatting_formula = None
                    if element is formatting_threshold:
                        formatting_threshold = None
                    if element is data_validation_leaf:
                        data_validation_leaf = None
                    if element is data_validation_extension:
                        data_validation_extension = None
                    element.clear()
                    while element.getprevious() is not None:
                        del element.getparent()[0]
                    context = ('cell' if active_cell is not None else 'row' if active_row is not None else
                               'sheet_data' if data in stack else 'root' if len(stack) <= 1 else 'worksheet_metadata')
            # Complete parse and read through ZIP EOF/CRC, not an XML prefix.
            if stream.read(1) or stack or not data_seen or not max_row or not max_column:
                raise _ExtentProofProblem('extent_not_proven')
        return max_row, max_column
    except _ExtentProofProblem as exc:
        reason = exc.reason
    except ImportError:
        reason = 'parser_unavailable'
    except zipfile.BadZipFile:
        reason = 'zip_integrity_failure'
    except OSError:
        reason = 'source_stream_failure'
    except xml_error:
        reason = 'xml_parse_failure'
    except Exception:
        reason = 'internal_proof_failure'
    if type(_failure) is dict:
        observed_rows = max_row or None
        observed_columns = max_column or None
        record = _checked_extent_failure({
            'schema': 1, 'outcome': 'rejected', 'basis': 'partial_XML_scan_not_an_accepted_extent',
            'complete_proof': False, 'reason': reason, 'context': context,
            'candidate_payload_max_row': observed_rows, 'candidate_payload_max_column': observed_columns,
            'candidate_payload_rectangle': max_row * max_column if observed_rows is not None else None,
            'cell_elements_seen': cells, 'xml_nodes_seen': nodes,
            'xml_bytes_observed': stream.bytes if stream is not None else None,
            'sheet_data_seen': data_seen,
            **({'namespace_rejection': namespace_rejection, 'namespace_structure': namespace_structure}
               if namespace_rejection is not None else {}),
            **({'namespace_path_fingerprint': namespace_path_fingerprint}
               if namespace_rejection is not None and namespace_path_fingerprint is not None else {})})
        if record is not None:
            _failure.update(record)
    return None


def _sheet(book, name):
    if name not in book.sheetnames:
        raise SourceProblem('required_sheet_missing')
    sheet = book[name]
    if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS \
            or sheet.max_row * sheet.max_column > MAX_CELLS:
        failure = {}
        extent = _verified_payload_extent(sheet, _failure=failure)
        if extent is None:
            raise _WorksheetSizeProblem(name, sheet.max_row, sheet.max_column, failure)
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
