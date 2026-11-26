"""Trace physical evidence without altering financial selection or valuation."""
from __future__ import annotations
import math
from developaid_contract_fact import match
from developaid_monitor_statement_union import _unit


def numeric(value):
    return type(value) in (float, int) and math.isfinite(value)


def position_audit(position, identity, current, fact, observed, binding, cut):
    sources, rejected = [], []
    for item in fact.get('physical_source_rows') or []:
        evidence = {'number':item.get('position') or '', 'name':item.get('name') or '', 'unit':item.get('unit') or ''}
        linked = match(evidence, current.get('estimates') or [])
        if isinstance(linked, str):
            if evidence['number'] != position.get('number'):
                continue
            rejected.append(linked)
        elif linked[:2] != identity:
            continue
        source = item.get('source') or {}
        raw = item.get('reported_completed_quantity')
        if raw is None:
            raw = item.get('completed_quantity')
        sources.append({'number':evidence['number'], 'name':evidence['name'], 'source':source,
            'unit':evidence['unit'], 'plan_quantity':item.get('plan_quantity'),
            'reported_work_quantity':raw,
            'reported_material_quantity':item.get('reported_material_quantity', item.get('material_quantity')),
            'snapshot_date':item.get('snapshot_date') or source.get('source_date'),
            'period_count':len(item.get('periods') or [])+len(item.get('undated_periods') or []),
            'quantity_bases':sorted({p.get('quantity_basis') or 'explicit_quantity' for p in (item.get('periods') or [])+(item.get('undated_periods') or [])}),
            'match':linked if isinstance(linked,str) else linked[2],
            'match_status':'rejected' if isinstance(linked,str) else 'linked',
            'conversion':'1:1' if _unit(evidence['unit']) == _unit(position.get('unit')) else 'unit_conflict'})
    known = bool(observed and observed.get('work_observed') and numeric(observed.get('work_quantity')))
    quantity = observed.get('work_quantity') if known else None
    derived_zero = quantity == 0 and any('нулевой суммой' in basis.lower() for x in sources for basis in x['quantity_bases'])
    if known and derived_zero:
        state = 'accounted_zero_physical_unknown'
        reason = ('По КС учтено 0 работ: ноль выведен из нулевой стоимости компонента, а ячейка объёма пуста. '
                  'Это не подтверждённый физический ноль на площадке. Поставка известна отдельно; физический объём требует подтверждения.')
        known = False
        quantity = None
    elif known:
        state = 'confirmed_zero' if quantity == 0 else 'confirmed_quantity'
        reason = 'Объём подтверждён принятыми физическими записями КС; единица совпадает с РДС.'
    elif rejected:
        reason = '; '.join(dict.fromkeys(rejected))
        state = 'unit_conflict' if 'измеряется' in reason else 'known_value_unlinked'
    elif sources and any(numeric(x['reported_work_quantity']) for x in sources):
        state = 'known_source_value_unaccepted'
        reason = ('В исходном накопительном итоге есть число, но нет принятой датированной записи объёма работ. '
                  'Нулевой итог при пустых периодах не подтверждает нулевое выполнение. '
                  'Исходное число и координаты сохранены в аудите; факт на срез неизвестен.')
    elif sources:
        state, reason = 'source_quantity_missing', 'Строка КС найдена, но физический объём работ не подтверждён. Поставка не означает монтаж.'
    elif fact.get('source') == 'ks2' and known is False:
        state, reason = 'source_missing', 'Позиция не найдена в принятых КС-2; отсутствие не доказывает ноль.'
    elif observed:
        state, reason = 'processing_or_component_gap', ' '.join(observed.get('reasons') or []) or 'Запись есть, но компонент работ не определён.'
    else:
        state, reason = 'source_missing', 'Исходная строка КС для этой позиции не найдена.'
    return {'state':state, 'reason':reason, 'sources':sources, 'rds_position':list(identity),
        'rds_number':position.get('number'), 'rds_unit':position.get('unit'), 'rds_quantity':position.get('quantity'),
        'estimate_sha256':current.get('estimate_sha256'), 'cut':cut,
        'accepted_work_quantity':quantity, 'accounted_work_quantity':(observed or {}).get('work_quantity'), 'accepted_material_quantity':(observed or {}).get('material_quantity'),
        'accepted_sources':(observed or {}).get('sources') or [],
        'gpr_binding':binding, 'conversion':'1:1' if known else None,
        'schedule_reason':(binding or {}).get('reason') or ''}
