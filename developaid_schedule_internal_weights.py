"""Internal weight provenance and full planned measures, never task counts."""
from __future__ import annotations

import math
import re

LABELS = {'smr_cost': 'Полная плановая стоимость СМР',
          'planned_quantity': 'Проектный объём однородных работ'}
EXPERT_LABEL = 'Экспертная оценка внутренних долей'
FIELDS = {'basis', 'value', 'unit', 'source_reference', 'valuation_key',
          'cost_basis', 'position_keys', 'full_scope'}


def methods(assignments):
    labels = {LABELS[assignment['weight']['basis']] for assignment in assignments.values() if assignment.get('weight')}
    if any(assignment.get('share') is not None for assignment in assignments.values()):
        labels.add(EXPERT_LABEL)
    return sorted(labels)


def validate(weight):
    if not isinstance(weight, dict) or set(weight) != FIELDS:
        raise ValueError('Для внутреннего веса нужны полный план, единицы, база сравнения и источник.')
    if not isinstance(weight['basis'], str) or weight['basis'] not in LABELS:
        raise ValueError('Вес определяется полной стоимостью СМР или проектным объёмом однородных работ.')
    value = weight['value']
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1e18):
        raise ValueError('Полный план должен быть конечным неотрицательным числом; пустое поле не равно нулю.')
    for field, limit in [('unit', 32), ('source_reference', 1000), ('valuation_key', 300)]:
        if not isinstance(weight[field], str) or len(weight[field]) > limit:
            raise ValueError('Укажите допустимые единицы, источник и общую базу сравнения.')
    if type(weight['full_scope']) is not bool:
        raise ValueError('Подтверждение полного плана должно быть явным.')
    if not isinstance(weight['cost_basis'], str) or weight['cost_basis'] not in {'', 'with_vat', 'without_vat'}:
        raise ValueError('Укажите, включает ли плановая стоимость НДС.')
    if weight['basis'] == 'smr_cost' and weight['unit'] != 'RUB':
        raise ValueError('Полная стоимость СМР задаётся в рублях.')
    if weight['basis'] == 'planned_quantity' and re.search(r'(?<!\w)(?:rub|руб(?:л[ья]|лей)?|usd|eur)(?!\w)|[₽$€]', weight['unit'], re.I):
        raise ValueError('Денежная сумма не является проектным натуральным объёмом; выберите стоимость СМР.')
    keys = weight['position_keys']
    if (not isinstance(keys, list) or len(keys) > 3000
            or any(not isinstance(k, str) or not k.strip() or len(k) > 300 for k in keys)
            or len({k.strip() for k in keys}) != len(keys)):
        raise ValueError('Укажите уникальные идентификаторы конечных позиций источника без повторов.')


def overlapping(assignments):
    """Position identifiers include source/version/object; totals are not leaves."""
    owners = {}
    for key, assignment in assignments.items():
        for position in (assignment.get('weight') or {}).get('position_keys', []):
            owners.setdefault(position.strip(), []).append(key)
    return {key for keys in owners.values() if len(keys) > 1 for key in keys}


def shares(members):
    """Return explicit calculated shares, or one reason blocking the whole group."""
    nodes = [assignment.get('weight') for _, assignment in members]
    if any(not node for node in nodes):
        return {}, 'Не для всех работ элемента задан полный план; равные веса не подставляются.'
    if any(assignment.get('share') is not None for _, assignment in members):
        return {}, 'В одном элементе экспертные доли не смешиваются с расчётом по полному плану.'
    for node in nodes:
        validate(node)
    kinds = {node['basis'] for node in nodes}
    if len(kinds) != 1:
        return {}, 'В одном элементе нельзя складывать стоимость и натуральные объёмы.'
    if any(node['value'] is None for node in nodes):
        return {}, 'Не хватает полной плановой стоимости или проектного объёма одной из работ.'
    if any(not node['full_scope'] for node in nodes):
        return {}, 'Не подтверждён полный план работ; оплата, аванс и остаток на завершение не задают вес.'
    if any(not node['source_reference'].strip() or not node['position_keys'] for node in nodes):
        return {}, 'Не указаны источник и отдельные конечные позиции полного плана работ.'
    if any(not node['valuation_key'].strip() for node in nodes) or len({node['valuation_key'].strip() for node in nodes}) != 1:
        return {}, 'Не подтверждена единая база сравнения: версия и уровень цен сметы либо один вид однородных работ.'
    if nodes[0]['basis'] == 'smr_cost':
        if any(not node['cost_basis'] for node in nodes) or len({node['cost_basis'] for node in nodes}) != 1:
            return {}, 'Стоимость работ имеет неизвестную или разную базу НДС.'
    else:
        units = {node['unit'].strip().casefold().replace('³', '3').replace('²', '2') for node in nodes}
        if '' in units or len(units) != 1:
            return {}, 'Проектные объёмы должны относиться к однородным работам в одинаковых единицах.'
    total = math.fsum(node['value'] for node in nodes)
    if not math.isfinite(total) or total <= 0:
        return {}, 'Нет положительного полного планового показателя для распределения веса элемента.'
    return {key: node['value']/total*100 for (key, _), node in zip(members, nodes)}, ''
