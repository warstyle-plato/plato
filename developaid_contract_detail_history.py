"""Pure, conservative composition of already dated contract detail views.

The caller supplies one contract's ``(ledger, physical_views)`` pairs after
``contracts._physical``.  No source bytes, store or parser is read or changed.
Only dated periods are composed: annual/cumulative totals are never added.
Consumers must honour ``detail_history_state == 'unknown'`` before aggregating
the returned items.  Their original observations remain in ``history_sources``.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
import re

_SCOPES = ('object_scope', 'system_scope', 'site_scope')
_PLAN = ('plan_quantity', 'planned_amount', 'planned_work_amount',
         'planned_material_amount', 'planned_cost_split', 'planned_work_amount_basis',
         'planned_amount_basis')
_FACTS = ('quantity', 'material_quantity', 'amount', 'work_amount', 'material_amount')
_MESSAGES = {
    'identity': 'Не подтверждены полный состав работы, единица, год или непротиворечивый контекст источника.',
    'provenance': 'Не подтверждены дата наблюдения, архив или отпечаток исходного файла.',
    'plan': 'Плановые объёмы или стоимости отсутствуют либо различаются; общий план не выбран.',
    'incomplete': 'В одном из исходников итог или объём не подтверждён; известные периоды не исправляют неполный исходник.',
    'undated': 'Есть выполнение без подтверждённого периода; оно сохранено справочно и не превращено в датированный факт.',
    'period': 'У периода отсутствуют действительные даты, сумма или объём.',
    'conflict': 'Одновременные наблюдения одного периода противоречат друг другу; версия не выбрана.',
    'overlap': 'Сохранённые периоды пересекаются или имеют разные подписи при одинаковых датах; их суммы не сложены.',
    'duplicate': 'Повтор исходной строки не подтверждён присутствующей канонической строкой.',
    'basis': 'Основания сумм выбранных периодов различаются или противоречивы; суммы не сложены.',
    'scope': 'Область работ в одной версии не указана, а в другой заполнена; независимость работ не подтверждена, суммы не сложены.',
}


def _norm(value):
    text = str(value or '').casefold().replace('ё', 'е')
    return ' '.join(re.sub(r'[«»“”"]', '', text).split())


def normalize_unit(value):
    text = _norm(value).replace('²', '2').replace('³', '3')
    return {'м^2': 'м2', 'м^3': 'м3', 'м.кв.': 'м2', 'кв.м': 'м2',
            'м.куб.': 'м3', 'куб.м': 'м3', 'пог.м': 'м', 'п.м': 'м'}.get(text, text)


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str, separators=(',', ':')).encode()).hexdigest()


def _unique(values):
    result, seen = [], set()
    for value in values:
        key = _digest(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _headings(value):
    if value is None:
        return (), True
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return (), False
    out = []
    for node in value:
        if isinstance(node, dict):
            position, name = _norm(node.get('position')), _norm(node.get('name'))
        elif isinstance(node, str):
            position, name = '', _norm(node)
        else:
            return (), False
        if not name:
            return (), False
        out.append((position, name))
    return tuple(out), True


def _identity(ledger, view):
    """Coordinates and filenames deliberately do not identify a work."""
    scopes, valid = [], True
    for field in _SCOPES:
        header = _norm(ledger.get(field))
        local = _norm(view.get('ledger_'+field) or view.get(field))
        evidence = {_norm(item.get('raw')) for item in
                    (ledger.get('scope_evidence') or {}).get(field, [])
                    if isinstance(item, dict) and _norm(item.get('raw'))}
        if len(evidence) > 1 or (header and local and header != local):
            valid = False
        scopes.append(header or local)
    year = ledger.get('period_year')
    if type(year) is not int or not 2000 <= year <= 2099:
        valid = False
    if view.get('period_year') not in (None, year):
        valid = False
    position, name = (_norm(view.get(field)) for field in ('position', 'name'))
    unit = normalize_unit(view.get('unit'))
    if not position or not name or not unit:
        valid = False
    section, section_valid = _headings(view.get('section_path'))
    context, context_valid = _headings(view.get('context_headings'))
    # Earlier free-text captions may describe other operations. Retain the
    # active caption plus every explicitly identified physical location.
    locations = {}
    for node in context:
        role = re.match(r'^(корпус|секция|этаж|помещение|комната|паркинг|автостоянка)(?=\s|№|\d|$)', node[1])
        if role:
            locations[role[1]] = node
    active = tuple(locations[key] for key in sorted(locations))
    if context and context[-1] not in active:
        active += (context[-1],)
    valid = valid and section_valid and context_valid
    return (tuple(scopes), position, name, unit, year, _norm(view.get('scope')),
            section, active, view.get('is_group') is True), valid


def _place(view):
    source = view.get('source') or {}
    return tuple(source.get(field) for field in ('filename', 'sheet', 'row'))


def work_identity(view):
    """The same semantic identity for projected and single-archive views."""
    ledger = {field: view.get('ledger_'+field) or '' for field in _SCOPES}
    ledger['period_year'] = view.get('period_year')
    return _identity(ledger, view)[0]


def _provenance(ledger, view):
    return {'snapshot_id': ledger.get('archive_snapshot_id') or ledger.get('snapshot_id'),
            'source_date': ledger.get('source_date'), 'file_sha256': ledger.get('file_sha256'),
            'source': copy.deepcopy(view.get('source') or ledger.get('source') or {})}


def _valid_provenance(provenance):
    return bool(_day(provenance['source_date']) and isinstance(provenance['snapshot_id'], str)
                and provenance['snapshot_id']
                and re.fullmatch(r'[0-9a-f]{64}', str(provenance['file_sha256'] or '')))


def _period_key(period):
    return period.get('date_start'), period.get('date_end'), _norm(period.get('label'))


def _period_value(period):
    return tuple(_number(period.get(field)) for field in _FACTS) + (
        period.get('amount_split') is True, period.get('amount_basis') or 'unspecified')


def _view_values(view):
    return (tuple(view.get(field) for field in _PLAN),
            tuple(_number(view.get(field)) for field in (
                'completed_quantity', 'completed_amount', 'material_quantity',
                'reported_completed_quantity', 'reported_completed_amount', 'reported_material_quantity')),
            sorted((_period_key(period), _period_value(period)) for period in view.get('periods') or []),
            sorted((_norm(period.get('label')), _period_value(period))
                   for period in view.get('undated_periods') or []))


def _source(ledger, view, originals):
    record = {'ledger': ledger, 'view': copy.deepcopy(view),
              'original_view': copy.deepcopy(view),
              'provenance': _provenance(ledger, view), 'aliases': [], 'problems': [],
              'identity': _identity(ledger, view)}
    # Tax qualifiers are source metadata, never a replacement for dated facts.
    if len(originals) == 1:
        for field in ('planned_amount_basis', 'completed_amount_basis'):
            record['view'].setdefault(field, originals[0].get(field, 'unspecified'))
    for field in _SCOPES:
        record['view']['ledger_'+field] = ledger.get(field) or view.get('ledger_'+field) or view.get(field) or ''
    record['view']['period_year'] = ledger.get('period_year')
    return record


def _records(ledger, views):
    """A verified in-source duplicate is provenance, not another work/period."""
    originals, places = {}, {}
    for item in ledger.get('items') or []:
        originals.setdefault(_place(item), []).append(item)
    records = [_source(ledger, view, originals.get(_place(view), [])) for view in views]
    for record in records:
        places.setdefault(_place(record['view']), []).append(record)
    result = []
    for record in records:
        view = record['view']
        if view.get('is_duplicate') is not True:
            result.append(record)
            continue
        target = view.get('duplicate_of') or {}
        place = tuple(target.get(field) for field in ('filename', 'sheet', 'row'))
        canonical = [candidate for candidate in places.get(place, []) if candidate is not record
                     and candidate['view'].get('is_duplicate') is not True
                     and target.get('period_year') == ledger.get('period_year')]
        if (len(canonical) == 1 and record['identity'] == canonical[0]['identity']
                and _view_values(view) == _view_values(canonical[0]['view'])):
            canonical[0]['aliases'].append(record)
        else:
            record['problems'].append('duplicate')
            result.append(record)
    return result


def _history(record):
    return dict(copy.deepcopy(record['provenance']), view=copy.deepcopy(record['original_view']))


def _project(records, cut, identity, identity_valid):
    records = sorted(records, key=lambda record: (
        str(record['provenance']['source_date'] or ''), _digest(record['provenance'])))
    newest = records[-1]
    result = copy.deepcopy(newest['view'])
    history_records = [candidate for record in records for candidate in [record, *record['aliases']]]
    result['history_sources'] = _unique([_history(record) for record in history_records])
    result['detail_history_key'] = _digest(identity) if identity_valid else None
    result['detail_history_work_key'] = _digest(identity[:4] + identity[5:]) if identity_valid else None
    result['detail_history_problems'] = []
    problems = result['detail_history_problems']

    if result.get('is_group') is True:
        # Keep source-proven subtotals intact as non-additive source metadata.
        # Aggregation consumers already exclude is_group; no group total is
        # composed with a different archive's leaves here.
        result['detail_history_state'] = 'group'
        result['periods'] = [dict(copy.deepcopy(period),
            selected_source=copy.deepcopy(newest['provenance']),
            history_sources=[dict(copy.deepcopy(newest['provenance']), period=copy.deepcopy(period))])
            for period in result.get('periods') or []
            if _day(period.get('date_end')) and _day(period['date_end']) <= cut]
        return result, []

    def problem(code):
        if code not in problems:
            problems.append(code)

    if not identity_valid:
        problem('identity')
    if any(not _valid_provenance(record['provenance']) for record in records):
        problem('provenance')
    for record in records:
        for code in record['problems']:
            problem(code)
    # Equal values do not prove that two separate rows of one sheet are copies.
    # The verified aliases were removed by _records; remaining repeated work
    # identities at distinct row coordinates must be reconciled explicitly.
    source_rows = {}
    for record in records:
        provenance, place = record['provenance'], _place(record['view'])
        source_key = provenance['snapshot_id'], provenance['file_sha256'], place[1]
        source_rows.setdefault(source_key, set()).add(place[2])
    if any(len(rows) > 1 for rows in source_rows.values()):
        problem('duplicate')
    # A composed view is not the old source row on which duplicate proofs were
    # verified. Those immutable proofs remain available inside history_sources.
    result['is_duplicate'] = False
    for field in ('duplicate_of', 'duplicate_proof', 'duplicate_note',
                  'duplicate_source_fingerprint', 'duplicate_view_fingerprint'):
        result.pop(field, None)

    plans = {tuple(record['view'].get(field) for field in _PLAN) for record in records}
    if (len(plans) != 1 or any(_number(record['view'].get('plan_quantity')) is None
                              or _number(record['view'].get('plan_quantity')) <= 0
                              or _number(record['view'].get('planned_amount')) is None
                              or _number(record['view'].get('planned_amount')) < 0 for record in records)):
        problem('plan')
        for field in ('plan_quantity', 'planned_amount', 'planned_work_amount', 'planned_material_amount'):
            result[field] = None
        result['planned_cost_split'] = False

    candidates, undated = {}, []
    for record in records:
        view = record['view']
        if not view.get('is_group') and any(_number(view.get(field)) is None
                                          for field in ('completed_quantity', 'completed_amount')):
            problem('incomplete')
        for period in view.get('undated_periods') or []:
            undated.append(dict(copy.deepcopy(period), selected_source=copy.deepcopy(record['provenance'])))
            problem('undated')
        valid_periods = 0
        for period in view.get('periods') or []:
            first, last = _day(period.get('date_start')), _day(period.get('date_end'))
            if last and last > cut:
                continue  # Never restore a future period, including from raw ledger.items.
            if not first or not last or first > last:
                problem('period')
                continue
            valid_periods += 1
            if (view.get('completed_amount') is not None
                    and all(period.get(field) is None
                            for field in ('amount', 'quantity', 'material_quantity'))):
                continue  # A reconciled empty cell group is not execution.
            candidates.setdefault(_period_key(period), []).append((record, period))
        known_zero = (_number(view.get('completed_quantity')) == 0
                      and _number(view.get('completed_amount')) == 0)
        if not valid_periods and not known_zero and not view.get('is_group'):
            problem('undated')
    result['undated_periods'] = _unique(undated)
    selected = []
    for key, observations in sorted(candidates.items()):
        days = [record['provenance']['source_date'] for record, _ in observations]
        if all(_day(day) for day in days):
            latest = max(days)
            current = [(record, period) for record, period in observations
                       if record['provenance']['source_date'] == latest]
        else:
            current = observations
            problem('provenance')
        values = {_period_value(period) for _, period in current}
        period = copy.deepcopy(current[0][1])
        period['history_sources'] = _unique([
            dict(copy.deepcopy(record['provenance']), period=copy.deepcopy(observation))
            for record, observation in observations])
        if len(values) != 1:
            problem('conflict')
            for field in _FACTS:
                period[field] = None
            period['selected_source'] = None
        else:
            period['selected_source'] = copy.deepcopy(current[0][0]['provenance'])
        if _number(period.get('amount')) is None or _number(period.get('quantity')) is None:
            problem('period')
        selected.append(period)
    last_end = None
    for period in selected:  # candidates are already sorted by start/end/label.
        if last_end is not None and period['date_start'] <= last_end:
            problem('overlap')
        last_end = max(last_end or period['date_end'], period['date_end'])
    bases = {period.get('amount_basis') for period in selected} - {None, '', 'unspecified'}
    if len(bases) > 1 or not bases <= {'with_vat', 'without_vat'}:
        problem('basis')
    result['periods'] = selected
    result['snapshot_date'] = newest['provenance']['source_date']
    result['archive_snapshot_id'] = newest['provenance']['snapshot_id']
    result['file_sha256'] = newest['provenance']['file_sha256']
    result['quantity_cut'] = cut.isoformat()
    result['quantity_date'] = max((period['date_end'] for period in selected), default=None)
    result['future_periods_excluded'] = any(record['view'].get('future_periods_excluded') is True
                                            for record in records)
    result['detail_history_state'] = 'unknown' if problems else 'known'
    known = result['detail_history_state'] == 'known'
    known_zero = not selected and all(_number(record['view'].get('completed_quantity')) == 0
                                     and _number(record['view'].get('completed_amount')) == 0
                                     for record in records)
    result['quantity_basis'] = ('По сохранённым датированным периодам; для повторяющегося периода '
                                'использовано последнее подтверждённое наблюдение.' if known else
                                'Объединённая история требует сверки; исходные сведения сохранены отдельно.')
    if known and known_zero:
        result['quantity_basis'] = ('Нулевой итог подтверждён исходной проверкой ведомости; '
                                    'непустых датированных периодов нет.')
    for field, period_field in (('completed_quantity', 'quantity'), ('completed_amount', 'amount'),
                                ('material_quantity', 'material_quantity')):
        values = [_number(period.get(period_field)) for period in selected]
        result[field] = (math.fsum(values) if known and values and all(value is not None for value in values)
                         else 0.0 if known and known_zero and field != 'material_quantity' else None)
        result['reported_'+field] = None
    split = known and bool(selected) and all(period.get('amount_split') is True
        and _number(period.get('work_amount')) is not None
        and _number(period.get('material_amount')) is not None for period in selected)
    result['amount_split'] = split
    result['completed_work_amount'] = math.fsum(period['work_amount'] for period in selected) if split else None
    result['completed_material_amount'] = math.fsum(period['material_amount'] for period in selected) if split else None
    plan, completed = _number(result.get('plan_quantity')), result['completed_quantity']
    result['completion_ratio'] = completed/plan if known and plan and completed is not None else None
    result['reported_completion_ratio'] = None
    messages = [f'История работы «{result.get("name") or "без наименования"}»: {_MESSAGES[code]}'
                for code in problems]
    result['warnings'] = list(dict.fromkeys([*(result.get('warnings') or []), *messages]))
    return result, messages


def compose(sources, cut):
    """Compose one contract's detail history without mutating any input.

    ``history_sources`` stores full input views with archive/file provenance.
    Each selected period stores all its observations and ``selected_source``.
    An equal-period later observation replaces its previous cumulative reading;
    differing dates, labels, scopes, units and years never silently replace it.
    """
    day = _day(cut)
    if day is None:
        raise ValueError('Укажите действительную дату среза в формате ГГГГ-ММ-ДД.')
    buckets, warnings = {}, []
    ordinal = 0
    for ledger, views in sources:
        source_day = _day(ledger.get('source_date'))
        if source_day and source_day > day:
            warnings.append('Накопительный источник позже даты среза не включён в историю.')
            continue
        for record in _records(ledger, views):
            identity, valid = record['identity']
            key = identity if valid else ('unresolved', ordinal)
            ordinal += 1
            buckets.setdefault(key, (identity, valid, []))[2].append(record)
    # Filling an absent header field does not prove an independent work.
    # Keep both original observations, but do not add their plans or facts.
    # Two explicitly different non-empty scopes remain distinct. Checking
    # disjoint periods as well prevents duplicating the full work plan.
    scope_candidates = {}
    for identity, valid, records in buckets.values():
        if valid:
            scope_candidates.setdefault(identity[1:], []).append((identity[0], records))
    for candidates in scope_candidates.values():
        for index, (left, left_records) in enumerate(candidates):
            for right, right_records in candidates[index+1:]:
                if left != right and all(not a or not b or a == b for a, b in zip(left, right)):
                    for record in [*left_records, *right_records]:
                        if 'scope' not in record['problems']:
                            record['problems'].append('scope')
    items = []
    for identity, valid, records in buckets.values():
        item, messages = _project(records, day, identity, valid)
        items.append(item)
        warnings.extend(messages)
    return {'items': items, 'warnings': list(dict.fromkeys(warnings))}
