"""One source-qualified monetary observation across annual KS statements.

Annual facts of different years can be added; a work's plan is counted once.
This describes the uploaded source coverage, never execution dates or physical
readiness. A conflict blocks the union without discarding per-source figures.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math

_BASES = {'with_vat', 'without_vat', 'unspecified'}


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _source(source):
    return tuple(str((source or {}).get(field) or '') for field in ('filename', 'sheet'))


def _unit(value):
    from developaid_monitor_contracts import _norm
    text = _norm(value).replace('²', '2').replace('³', '3')
    return {'м^2': 'м2', 'м^3': 'м3', 'м.кв.': 'м2', 'кв.м': 'м2',
            'м.куб.': 'м3', 'куб.м': 'м3', 'пог.м': 'м', 'п.м': 'м'}.get(text, text)


def _work(item):
    from developaid_monitor_contracts import _norm
    path = item.get('section_path') or item.get('context_headings') or []
    if isinstance(path, str):
        path = [path]
    return (tuple(_norm(item.get(field)) for field in ('position', 'name', 'scope'))
            + (_unit(item.get('unit')), tuple(_norm(value) for value in path)))


def _annual(item, reference, observation_year):
    year = item.get('period_year')
    if not isinstance(year, int) or isinstance(year, bool) or not 2000 <= year <= 2099:
        return None, 'year_unknown'
    if year != reference.get('period_year'):
        return None, 'year_conflict'
    if year > observation_year:
        return None, 'future_year'
    if item.get('future_periods_excluded') is not False:
        return None, 'future_or_unverified_periods'
    reported = _number(item.get('reported_completed_amount'))
    amount = reported if reported is not None else _number(item.get('completed_amount'))
    if amount is None:
        return None, 'completed_amount_unknown'
    quantity = _number(item.get('reported_completed_quantity'))
    if quantity is None:
        quantity = _number(item.get('completed_quantity'))
    materials = _number(item.get('reported_material_quantity'))
    if materials is None:
        materials = _number(item.get('material_quantity'))
    return (year, amount, quantity, materials), None


def statement_union(row: dict) -> dict:
    """Union known work-year facts, with a single unchanged plan per exact work."""
    result = {'ratio': None, 'planned': None, 'completed': None, 'remaining': None,
              'basis': 'statement_union', 'basis_label': 'стоимости работ по ведомостям',
              'basis_signature': None, 'scope_fingerprint': None,
              'source_years': [], 'source_count': 0, 'position_count': 0,
              'annual_position_count': 0, 'duplicate_count': 0, 'coverage': [],
              'coverage_basis': 'uploaded_annual_statements', 'state': 'unknown',
              'why': 'Нет квалифицированных годовых итогов для общего процента.',
              'problems': []}

    def fail(code, message, *, source=None, position=None):
        result['state'] = 'incomparable'
        result['why'] = message
        result['problems'].append({'code': code, 'source': source, 'position': position})
        return result

    references = row.get('reported_performance_sources') or []
    items = row.get('physical_items') or []
    if not references or not items:
        return result
    observation = _day(row.get('source_date'))
    if observation is None:
        dates = [_day(item.get('snapshot_date')) for item in items]
        if dates and all(dates) and len(set(dates)) == 1:
            observation = dates[0]
    if observation is None:
        return fail('observation_date_unknown', 'Дата наблюдения годового итога не подтверждена.')
    qualifications = {}
    for reference in references:
        source = _source(reference.get('source'))
        if not all(source):
            return fail('source_identity_unknown', 'Для одной ведомости не подтверждены файл и лист источника.')
        if reference.get('future_periods_excluded') is not False:
            return fail('future_or_unverified_periods', 'Общий итог содержит будущие или непроверенные периоды.', source=source)
        if reference.get('source_complete') is False or (_number(reference.get('unread_rows_count')) or 0) > 0:
            return fail('partial_source', 'Одна из ведомостей прочитана не полностью; общий процент не выбран.', source=source)
        bases = reference.get('planned_amount_basis'), reference.get('completed_amount_basis')
        if reference.get('monetary_comparable') is not True or any(basis not in _BASES for basis in bases):
            return fail('tax_basis_unverified', 'Основания стоимостей одной ведомости не подтверждены или несовместимы.', source=source)
        if bases[0] != 'unspecified' and bases[1] != 'unspecified' and bases[0] != bases[1]:
            return fail('tax_basis_mismatch', 'План и выполнение одной ведомости имеют разные явные основания НДС.', source=source)
        year = reference.get('period_year')
        if not isinstance(year, int) or isinstance(year, bool) or not 2000 <= year <= 2099:
            return fail('year_unknown', 'Год одной накопительной ведомости не подтверждён.', source=source)
        if year > observation.year:
            return fail('future_year', 'Год ведомости позже даты наблюдения; этот итог не использован.', source=source)
        key = source, year
        qualification = (bases, reference.get('works_materials_split') is True)
        if key in qualifications and qualifications[key] != qualification:
            return fail('source_qualification_conflict', 'Один источник имеет разные основания сравнения.', source=source)
        qualifications[key] = qualification
    result['source_count'] = len(qualifications)
    tax_bases = {qualification[0] for qualification in qualifications.values()}
    if len(tax_bases) != 1:
        return fail('tax_basis_changed', 'Ведомости используют разные основания стоимостей; их итоги не сложены.')
    observed_sources, works, evidence = set(), {}, {}
    for item in items:
        source = _source(item.get('source'))
        year = item.get('period_year')
        key = source, year
        if key not in qualifications:
            return fail('position_source_unverified', 'Позиция не относится к квалифицированной годовой ведомости.',
                        source=source, position=item.get('position'))
        if item.get('is_group') is True:
            parent = (item.get('source') or {}).get('row')
            if not isinstance(parent, int) or not any(
                    child.get('parent_row') == parent and child is not item
                    and _source(child.get('source')) == source and child.get('period_year') == year
                    for child in items):
                return fail('unproven_group', 'Строка помечена итоговой группой без подтверждённых дочерних позиций.',
                            source=source, position=item.get('position'))
            continue
        observed_sources.add(key)
        work = _work(item)
        quantity_plan = _number(item.get('plan_quantity'))
        amount_plan = _number(item.get('planned_amount'))
        if not work[1] or not work[3] or quantity_plan is None or quantity_plan <= 0:
            return fail('quantity_plan_unknown', 'Для позиции не подтверждён положительный полный объём.',
                        source=source, position=item.get('position'))
        if amount_plan is None or amount_plan < 0:
            return fail('planned_amount_unknown', 'Для позиции не подтверждена неотрицательная плановая стоимость.',
                        source=source, position=item.get('position'))
        definition = quantity_plan, amount_plan
        if work in works and works[work] != definition:
            return fail('plan_changed', 'План или цена одной работы различаются между ведомостями; общий процент не выбран.',
                        source=source, position=item.get('position'))
        works[work] = definition
        reference = next(reference for reference in references
                         if _source(reference.get('source')) == source and reference.get('period_year') == year)
        annual, error = _annual(item, reference, observation.year)
        if error:
            return fail(error, 'Для позиции не подтверждён сопоставимый годовой итог выполнения.',
                        source=source, position=item.get('position'))
        # An annual execution record is not multiplied by copies of its book.
        annual_key = work, year
        if annual_key in evidence:
            if evidence[annual_key] != annual:
                return fail('annual_evidence_conflict', 'Одна работа за один год имеет разные итоги; они не сложены.',
                            source=source, position=item.get('position'))
            result['duplicate_count'] += 1
        else:
            evidence[annual_key] = annual
    if set(qualifications) != observed_sources:
        return fail('source_positions_missing', 'Для одной ведомости не получены её позиции; общий процент не выбран.')
    if not works or not evidence:
        return fail('leaf_positions_missing', 'В годовых ведомостях не подтверждены отдельные позиции работ.')
    planned = sum(value[1] for value in works.values())
    if planned <= 0:
        return fail('nonpositive_price', 'Суммарная плановая стоимость равна нулю; денежный процент не определён.')
    completed = sum(value[1] for value in evidence.values())
    scope = _digest(sorted((work, definition) for work, definition in works.items()))
    bases = next(iter(tax_bases))
    coverage = sorted((_digest(work), year) for work, year in evidence)
    totals = {work: sum(annual[1] for (key, _), annual in evidence.items() if key == work)
              for work in works}
    result.update(ratio=completed/planned, planned=planned, completed=completed,
        remaining=planned-completed, basis_signature=_digest(['statement_union', planned, scope, bases]),
        scope_fingerprint=scope, source_years=sorted({year for _, year in evidence}),
        position_count=len(works), annual_position_count=len(evidence), coverage=coverage,
        state='known', why='Известные годовые итоги по загруженным ведомостям; план каждой работы учтён один раз.',
        requires_reconciliation=any(value < 0 or value > works[work][1] for work, value in totals.items()))
    return result
