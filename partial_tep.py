"""Opt-in partial TEP drafts: missing source facts never become model zeroes."""
from __future__ import annotations
import math

KIND = 'developaid.project.partial-tep'
STATE_KEY = '_partial_tep'
FIELDS = ('gns', 'total_area', 'useful', 'saleable', 'transfer', 'units')
INPUTS = ('purchase_price_mln', 'land_rights_cost_mln', 'project_start',
          'construction_months', 'main_above_th_per_sqm')
LABELS = {'gns': 'ГНС', 'total_area': 'общая площадь', 'useful': 'полезная площадь',
          'saleable': 'продаваемая площадь', 'transfer': 'передаваемая площадь', 'units': 'количество'}
INPUT_LABELS = {'purchase_price_mln': 'Цена входа', 'land_rights_cost_mln': 'Земельные права / ВРИ',
                'project_start': 'Начало проекта', 'construction_months': 'Срок строительства',
                'main_above_th_per_sqm': 'СМР надземной части', 'main_under_th_per_sqm': 'СМР подземной части',
                'apartment_price_th': 'Цена квартир', 'commercial_price_th': 'Цена коммерции',
                'parking_price_th': 'Цена машино-места', 'storage_price_th': 'Цена кладовых'}
PRODUCTS = {'apartments': 'Квартиры', 'ground_commercial': 'Коммерция',
            'underground_parking': 'Подземный паркинг', 'storage': 'Кладовые'}
UNSUPPORTED_SWITCHES = tuple(f'{prefix}{suffix}_enabled'
                             for prefix in ('retail', 'offices', 'above_parking')
                             for suffix in ('', '2', '3', '4', '5')) + ('sports_enabled',)


class PartialTepError(ValueError):
    pass


def active(inputs):
    return isinstance(inputs, dict) and STATE_KEY in inputs


def numeric(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def required_inputs(rows):
    keys = list(INPUTS)
    for product, price in [('apartments', 'apartment_price_th'), ('ground_commercial', 'commercial_price_th'),
                           ('underground_parking', 'parking_price_th'), ('storage', 'storage_price_th')]:
        if product in rows:
            keys.append(price)
    if any(key in rows for key in ('underground_parking', 'storage')):
        keys.append('main_under_th_per_sqm')
    return keys


def missing(inputs, tep):
    if not active(inputs):
        return []
    state = inputs[STATE_KEY]
    if not isinstance(state, dict) or state.get('kind') != KIND or state.get('version') != 1:
        raise PartialTepError('Неверный формат черновика ТЭП. Загрузите исходный файл заново.')
    rows = state.get('rows')
    if not isinstance(rows, list) or not rows or any(not isinstance(k, str) or k not in PRODUCTS for k in rows):
        raise PartialTepError('Не заданы поддерживаемые продукты черновика ТЭП.')
    if not isinstance(tep, dict):
        raise PartialTepError('Не задана таблица ТЭП.')
    if (inputs.get('project_kind', 'mixed') != 'mixed'
            or any(inputs.get(key) for key in UNSUPPORTED_SWITCHES)
            or any(key not in PRODUCTS and isinstance(row, dict)
                   and any(numeric(row.get(f)) and row[f] > 0 for f in FIELDS)
                   for key, row in tep.items())):
        raise PartialTepError('Частичный ТЭП v1 поддерживает только квартиры, встроенную коммерцию, подземный паркинг и кладовые.')
    rows = list(dict.fromkeys(rows + [key for key in PRODUCTS if isinstance(tep.get(key), dict) and any(numeric(tep[key].get(f)) and tep[key][f] > 0 for f in FIELDS)]))
    result = []
    # No client-supplied "ready" or missing-fields list can waive this contract.
    for key in dict.fromkeys(rows):
        row = tep.get(key) if isinstance(tep.get(key), dict) else {}
        present = any(numeric(row.get(f)) and row[f] > 0 for f in FIELDS)
        for field in FIELDS:
            if not numeric(row.get(field)) or (field == 'gns' and present and not row.get(field)):
                result.append({'path': f'tep.{key}.{field}', 'label': f'{PRODUCTS[key]}: {LABELS[field]}'})
        if key == 'underground_parking':
            guest = row.get('guest_units')
            if (not numeric(guest) or (numeric(row.get('units')) and guest > row['units'])):
                result.append({'path': f'tep.{key}.guest_units', 'label': 'Подземный паркинг: гостевые места (от 0 до общего количества)'})
    for key in required_inputs(rows):
        value = inputs.get(key)
        known = (isinstance(value, str) and len(value) == 10 and _date(value)) if key == 'project_start' else numeric(value)
        if key == 'construction_months' and known:
            known = value > 0 and value == int(value)
        if not known:
            result.append({'path': f'inputs.{key}', 'label': INPUT_LABELS.get(key, key)})
    return result


def _date(value):
    import datetime
    try:
        datetime.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def require_complete(inputs, tep):
    gaps = missing(inputs, tep)
    if gaps:
        raise PartialTepError('Черновик ТЭП: расчёт и финансовые документы недоступны. Не указано: '
                              + '; '.join(item['label'] for item in gaps) + '.')


def schema():
    return {'kind': KIND, 'fields': list(FIELDS), 'base_inputs': list(INPUTS),
            'unsupported_switches': list(UNSUPPORTED_SWITCHES),
            'labels': LABELS, 'input_labels': INPUT_LABELS, 'products': PRODUCTS,
            'prices': {'apartments': 'apartment_price_th', 'ground_commercial': 'commercial_price_th',
                       'underground_parking': 'parking_price_th', 'storage': 'storage_price_th'}}
