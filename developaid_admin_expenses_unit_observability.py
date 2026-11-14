"""Diagnostic hints from already-read AHR cells; no raw money-unit inference."""
from __future__ import annotations

import hashlib
import json
import re

MAX_LEAF_SAMPLES = 4
MAX_CELL_SAMPLES = 12
MAX_FORMAT_GROUPS = 12
MAX_FORMAT_CHARS = 256
MAX_DIAGNOSTIC_BYTES = 16 * 1024
UNIT_HEADERS = {"едизм", "единицаизмерения", "единицыизмерения"}
PHYSICAL = {"м²": "м²", "м2": "м²", "кв. м": "м²", "кв.м": "м²",
            "м³": "м³", "м3": "м³", "м": "м", "га": "га",
            "шт": "шт.", "шт.": "шт.", "чел": "чел.", "чел.": "чел."}
FORMAT_LITERALS = re.compile(r'"[^"]*"|\[[^\]]*\]|\\.')


def _hash(value):
    digest = hashlib.sha256()
    for start in range(0, len(value), 4096):
        digest.update(value[start:start + 4096].encode())
    return digest.hexdigest()


def _hint(value, currency):
    text = " ".join(value.split()).lower()
    match = currency.fullmatch(text)
    if match:
        scale = (match['scale'] or '').lower()
        token = 'тыс. руб.' if scale.startswith('тыс') else 'млн руб.' if scale else 'руб.'
        return {'kind': 'currency', 'token': token}
    if text in PHYSICAL:
        return {'kind': 'physical', 'token': PHYSICAL[text]}
    if text == '%':
        return {'kind': 'percent', 'token': '%'}
    return None


def _format(cell, currency):
    try:
        value = cell.number_format
    except Exception:
        return {'state': 'unknown', 'code': 'number_format_unavailable', 'format_sha256': None}
    if not isinstance(value, str):
        return {'state': 'unknown', 'code': 'number_format_unavailable', 'format_sha256': None}
    result = {'format_sha256': _hash(value), 'state': 'display_hint_only', 'hints': [],
              'display_scaling_syntax': False, 'display_scale_ambiguous': False}
    if len(value) > MAX_FORMAT_CHARS:
        return {**result, 'state': 'bounded_incomplete', 'code': 'format_character_limit'}
    unknown, conditional = 0, False
    for match in FORMAT_LITERALS.finditer(value):
        token = match[0]
        literal = None
        if token.startswith('"'):
            literal = token[1:-1]
        elif token.startswith('\\'):
            literal = token[1:]
        elif re.fullmatch(r'\[\$(₽|руб\.|р\.)(?:-(?:[0-9a-fA-F]{1,8}|ru-RU))?\]', token):
            literal = token[2:-1].split('-', 1)[0]
        elif token[1:-1].lower() in {'red', 'black', 'blue', 'green', 'yellow', 'white', 'cyan', 'magenta'}:
            continue
        elif re.fullmatch(r'\[[<>=]{1,2}-?[0-9]+(?:[.,][0-9]+)?\]', token):
            conditional = True
            continue
        else:
            unknown += 1
        if literal is not None and literal.strip():
            hint = _hint(literal, currency)
            if hint and hint not in result['hints']:
                result['hints'].append(hint)
            elif not hint:
                unknown += 1
    syntax = FORMAT_LITERALS.sub('', value)
    if '₽' in syntax:
        hint = {'kind': 'currency', 'token': 'руб.'}
        if hint not in result['hints']:
            result['hints'].append(hint)
        syntax = syntax.replace('₽', '')
    if '%' in syntax:
        result['hints'].append({'kind': 'percent', 'token': '%'})
    if syntax != 'General' and re.search(r'[^0-9#?.,;+\-()@_* /%Ee\s]', syntax):
        unknown += 1
    result['display_scaling_syntax'] = bool(re.search(r'[0#?][0#?.,]*,\s*(?:;|$)', syntax))
    result['display_scale_ambiguous'] = bool(result['display_scaling_syntax'] or ';' in syntax
        or conditional or any(h['kind'] != 'currency' for h in result['hints']) or unknown)
    if unknown:
        result.update(state='unknown', code='unknown_format_literal', unknown_literal_count=unknown)
    return result


def _base(leaf_count):
    return {'schema': 1, 'scope': 'already_read_ahr_cells_diagnostic_only',
            'state': 'diagnostic_only', 'raw_unit_state': 'unknown',
            'raw_storage_unit': None, 'money_factor': None, 'financial_acceptance': False,
            'available_leaf_count': leaf_count, 'sampled_leaf_count': 0,
            'format_groups': [], 'cell_samples': [], 'row_unit_samples': [], 'gaps': []}


def _limited(result, code):
    return {**_base(result['available_leaf_count']), 'state': 'bounded_incomplete',
            'gaps': [code], 'omitted_leaf_count': result['available_leaf_count']}


def observe(leaves, row_cells, header_cells, columns, currency):
    """Only existing E:H unit headers/rows and the12 already-read I/J/K cells."""
    result = _base(len(leaves))
    if columns != {'total': 8, 'fact': 9, 'plan': 10}:
        return _limited(result, 'money_columns_outside_diagnostic_scope')
    if len(leaves) > MAX_LEAF_SAMPLES or len(leaves) * 3 > MAX_CELL_SAMPLES:
        return _limited(result, 'leaf_or_cell_sample_limit')
    candidates = []
    for column in range(4, 8):
        value = header_cells[column].value
        label = re.sub(r'[\s._-]', '', value.lower()) if isinstance(value, str) and len(value) <= 64 else ''
        if label in UNIT_HEADERS:
            candidates.append(column)
    result['unit_header'] = {'state': 'observed_unique' if len(candidates) == 1 else
                            'ambiguous' if candidates else 'missing',
                            'cells': [header_cells[c].coordinate for c in candidates]}
    if len(candidates) != 1:
        result['gaps'].append('unit_header_ambiguous' if candidates else 'unit_header_missing')
    groups = {}
    for leaf in leaves:
        cells = row_cells[leaf['row']]
        for key, column in columns.items():
            hint = _format(cells[column], currency)
            group = hint['format_sha256']
            if group is not None:
                groups.setdefault(group, {**hint, 'cell_count': 0})['cell_count'] += 1
            else:
                result['gaps'].append('number_format_unavailable')
            result['cell_samples'].append({'cell': leaf['cells'][key]['cell'], 'format_sha256': group})
        if len(candidates) == 1:
            column = candidates[0]
            sample = {'code': leaf['code'], 'row': leaf['row'], 'cell': f'{"EFGH"[column-4]}{leaf["row"]}',
                      'state': 'unknown', 'formula': None}
            try:
                value = cells[column].value
                if isinstance(value, str):
                    sample['value_sha256'] = _hash(value)
                    hint = _hint(value, currency) if len(value) <= 64 else None
                    if hint:
                        sample.update(state='row_label_hint_only', **hint)
                elif value is None:
                    sample['state'] = 'missing'
            except Exception:
                sample['error_code'] = 'unit_cell_unavailable'
            result['row_unit_samples'].append(sample)
    if len(groups) > MAX_FORMAT_GROUPS:
        return _limited(result, 'format_group_limit')
    result['format_groups'] = list(groups.values())
    if len(groups) > 1:
        result['gaps'].append('mixed_format_groups')
    for hint in groups.values():
        if hint.get('code'):
            result['gaps'].append(hint['code'])
        if hint['state'] == 'bounded_incomplete':
            result['state'] = 'bounded_incomplete'
        if any(h['kind'] != 'currency' for h in hint['hints']):
            result['gaps'].append('nonmonetary_format_hint')
    if any(s.get('kind') in {'physical', 'percent'} for s in result['row_unit_samples']):
        result['gaps'].append('nonmonetary_row_unit')
    units = {s.get('token') for s in result['row_unit_samples'] if s.get('kind') == 'currency'}
    if len(units) > 1:
        result['gaps'].append('mixed_row_unit_tokens')
    result['gaps'] = list(dict.fromkeys(result['gaps']))
    result['sampled_leaf_count'] = len(leaves)
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_DIAGNOSTIC_BYTES:
        return _limited(result, 'unit_observability_size_limit')
    return result
