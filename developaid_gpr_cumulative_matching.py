"""Grounded initial GPR/KS associations, with explicit source-scope cohorts.

Closed construction-operation rules and complete, equal location scopes can
form an automatic leaf binding. Lexical similarity is not an authorization.
Shared source volumes stay one cohort and are never copied to every floor.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re

import developaid_cumulative_progress as progress
import developaid_monitor_contract_links as links
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
import developaid_schedule_physical as quantities

RULE_VERSION = 4
SCOPE_FIELDS = ('locations', 'floors', 'zones', 'systems', 'materials', 'operation_parts')

_GROUND = r'(?:подземн|наземн)(?:ый|ая|ое|ые|ых|ого|ой|ому|ую|ом|ыми)'
_OBJECT_TYPE = r'(?:паркинг(?:а|е|у|ом|и|ов|ах)?|автостоянк(?:а|и|е|у|ой|ах)|стилобат(?:а|е|у|ом|ы|ов|ах)?)'
_OBJECT_NUMBER = r'(?:№\s*)?\d+(?:\.\d+)*(?:[a-zа-я])?'
_OBJECT_NUMBERS = _OBJECT_NUMBER+r'(?:\s*(?:[/,;–—-]|\bи\b|\bпо\b|\bдо\b)\s*'+_OBJECT_NUMBER+r')*'
_OBJECT_LABEL = re.compile(r'(?:(?P<before>'+_GROUND+r')\s+)?(?P<type>'+_OBJECT_TYPE+r')\b'
    r'(?:\s*\(?\s*(?P<after>'+_GROUND+r')\s*\)?)?'
    r'(?:\s*(?:номер\s*)?(?P<numbers>'+_OBJECT_NUMBERS+r')(?![\w.]))?')


def _object_scopes(text, *, whole_object=False):
    """An object type, ground and explicit number are one indivisible scope."""
    values, bad, matches = set(), False, list(_OBJECT_LABEL.finditer(text))
    for match in matches:
        kind = 'stylobate' if match['type'].startswith('стилобат') else 'parking'
        grounds = {'underground' if value.startswith('подземн') else 'aboveground'
                   for value in (match['before'], match['after']) if value}
        bad = bad or len(grounds) > 1
        ground = next(iter(grounds)) if len(grounds) == 1 else 'unspecified'
        number = match['numbers']
        if number and not re.fullmatch(_OBJECT_NUMBER, number):
            bad = True
            number = 'ambiguous'
        elif number:
            number = re.sub(r'[№\s]', '', number)
        # Unparsed qualifying adjectives/numbers do not become generic objects.
        previous = re.search(r'([\w-]+)\s*$', text[:match.start()])
        following = re.match(r'\s*([\w-]+)', text[match.end():])
        if previous and re.search(r'(?:ый|ая|ое|ые|ого|ой|ых|ую)$', previous[1]):
            bad = True
        if following and (re.search(r'(?:ый|ая|ое|ые|ого|ой|ых|ую)$', following[1])
                          or re.match(r'[\d№]', following[1])):
            bad = True
        if re.match(r'\s*(?:№|номер|\d|[/–—-]\s*№?\d)', text[match.end():]):
            bad = True
        values.add('object:'+kind+':'+ground+':'+(number or 'unspecified'))
    if re.search(r'паркинг|автостоян|стилобат', text) and not matches:
        bad = True
    if whole_object and matches:
        remainder = _OBJECT_LABEL.sub(' ', text)
        remainder = re.sub(r'\bкорпус(?:а|е|у|ом|ах)?\s*\d+(?:\s*[,;и-]\s*\d+)*', ' ', remainder)
        remainder = re.sub(r'\bи\b|[\s,;/()+.:-]', '', remainder)
        bad = bad or bool(remainder)
    return frozenset(values), bad


def _text(value):
    return ' '.join(str(value or '').casefold().replace('ё', 'е').split())


def _label(value):
    return (value.get('name') or value.get('text') or '') if isinstance(value, dict) else str(value or '')


def _path(values):
    return [_label(value) for value in values or [] if _label(value)]


def _floors(text):
    text = _text(text)
    text = re.sub(r'(\d+)[- ](?:ый|ой|ий|го|й|ого)\b', r'\1', text)
    values = set()
    chunks = [match[1] for match in re.finditer(
        r'(?<![\d\-–—−])(\d{1,2}(?:\s*(?:[-–—,;]|и)\s*\d{1,2})*)\s*этаж', text)]
    chunks += [match[1] for match in re.finditer(
        r'этаж[аи]?\s*(\d{1,2}(?:\s*(?:[-–—,;]|и)\s*\d{1,2})*)', text)]
    for chunk in chunks:
        for match in re.finditer(r'(\d{1,2})(?:\s*[-–—]\s*(\d{1,2}))?', chunk):
            first, last = int(match[1]), int(match[2] or match[1])
            if 0 < first <= last <= 100:
                values.update(str(number) for number in range(first, last+1))
    if re.search(r'тех(?:ническ\w*)?\s*этаж', text):
        values.add('technical')
    return frozenset(values)


def _locations(text, *, whole_object=False):
    text = re.sub(r'\bкорпус(?:е|у|ом|ах)\b', 'корпус', _text(text))
    corps, ambiguous = links._scope_info(text)
    values = {'corpus:'+number for number in corps}
    objects, bad = _object_scopes(text, whole_object=whole_object)
    values.update(objects)
    return frozenset(values), ambiguous or bad


def _zones(text):
    values = set()
    text = _text(text)
    groups = [match[1] for match in re.finditer(r'захватк[аиоуе]?\s*([\d., и/–—-]+)', text)]
    groups.extend(match[1] for match in re.finditer(r'(?<![\w.])([\d]+(?:[., ]+[\d]+)*)\s*захватк', text))
    for group in groups:
        # Ranges are retained as ambiguous rather than guessed as addresses.
        if re.search(r'[-–—/]', group):
            return frozenset(), True
        values.update(re.findall(r'\d+(?:\.\d+)?', group))
    return frozenset(values), False


def _systems(text):
    text = _text(text)
    matches = re.findall(r'\bитп\s*(?:[-№]\s*)?(\d+(?:\s*(?:[/,;]|и)\s*\d+)*)?', text)
    if not matches and 'индивидуальный тепловой пункт' not in text:
        return frozenset()
    return frozenset('itp:'+number for group in matches for number in re.findall(r'\d+', group)) or frozenset({'itp'})


def _operation_name(text):
    """One closed normalization for typed references, not descriptive text."""
    name = _text(text)
    name = re.sub(r'^\((?=[^)]*\d)[a-zа-я0-9][a-zа-я0-9_.-]{0,23}\)\s*', '', name)
    return re.sub(r'^раздел\s*(?:№\s*)?[\d.]+\s*[.:]?\s*', '', name)


def _operation(text):
    """A deliberately closed operation taxonomy, independent of project names."""
    name = _operation_name(text)
    if re.search(r'демонтаж|разборк|снятие', name):
        return None
    if re.search(r'этаж\s+верт\s+констр|^устройство\s+монолитн\w*\s+железобетонн\w*\s+вертикальн', name):
        return 'monolith_vertical'
    if re.search(r'этаж\s+пп\b|^устройство\s+монолитн\w*\s+железобетонн\w*\s+горизонтальн', name):
        return 'monolith_horizontal'
    if re.search(r'^устройство\s+(?:монолитн\w*\s+)?(?:железобетонн\w*\s+)?(?:ростверк|фундаментн\w*\s+плит|фундамент(?:ов|ы|а|ами|ах)?\b)', name):
        return 'foundations'
    if re.search(r'^срубка\s+оголовков\s+свай|^вырубка\s+бетона\s+из\s+арматурного\s+каркаса\s+свай', name):
        return 'pile_head_cut'
    if re.search(r'^устройство\s+бетонной\s+подготовки', name):
        return 'concrete_preparation'
    if re.search(r'^устройство\s+свайного\s+основания|^вдавливание\s+(?:железобетонн\w*\s+)?свай', name):
        return 'pile_installation'
    if name.startswith('пробные сваи и испытания'):
        return 'trial_piles_and_testing'
    if re.search(r'^испытани[ея]\s+(?:натурн\w*\s+)?сва', name):
        return 'pile_testing'
    if ('итп' in name or 'индивидуальный тепловой пункт' in name) and 'тепломеханическ' in name:
        return 'itp_thermomechanical'
    if ('итп' in name or 'индивидуальный тепловой пункт' in name) and re.search(r'автоматик|автоматизац', name):
        return 'itp_automation'
    if re.search(r'устройство\s+(?:отделки\s+фасадов|нвф)', name):
        if re.search(r'горизонтальн|подшивк', name):
            return 'facade_horizontal'
        if re.search(r'вертикальн', name):
            return 'facade_vertical'
    if re.search(r'^устройство\s+фасадов\s+со\s+штукатурк', name):
        return 'facade_plaster'
    if re.search(r'^(?:устройство\s+)?кладк[аи]\s+(?:стен|каменн)', name):
        return 'masonry'
    if re.search(r'^устройство\s+полов', name):
        return 'floor_finishes'
    if re.search(r'^устройство\s+(?:отделки\s+)?потолков', name):
        return 'ceiling_finishes'
    if re.search(r'^устройство\s+отделки\s+стен', name):
        return 'wall_finishes'
    return None


def _operation_body(text):
    """Remove only typed scope labels; retain every other qualifier."""
    name = _operation_name(text)
    name = re.sub(r'(\d+)[- ](?:ый|ой|ий|го|й|ого)\b', r'\1', name)
    integers = r'\d{1,2}(?:\s*(?:[-–—,;]|и)\s*\d{1,2})*'
    zones = r'\d+(?:\.\d+)?(?:\s*(?:[,;]|и)\s*\d+(?:\.\d+)?)*'
    for pattern in (rf'(?<![\d/–—−-]){integers}\s*этаж(?:а|и|ей)?\b',
                    rf'\bэтаж(?:а|и|ей)?\s*{integers}', r'\bтех(?:ническ(?:ий|ого))?\s*этаж(?:а)?\b',
                    rf'\b(?:для\s+)?корпус(?:а|е|у|ом|ах)?\s*{integers}',
                    rf'\bзахватк[аиоуе]?\s*{zones}'):
        name = re.sub(pattern, ' ', name)
    name = _OBJECT_LABEL.sub(' ', name)
    return _text(name).strip(' ,.;:')


def _closed_parts(text, aliases):
    """Every token of a composition list must be a known complete part."""
    text = text.strip(' ():,;.')
    if not text:
        return frozenset()
    parts = set()
    for token in re.split(r'\s*(?:[,;()]|\bи\b)\s*', text):
        if not token:
            continue
        part = next((part for part, pattern in aliases if re.fullmatch(pattern, token)), None)
        if part is None:
            return frozenset()
        parts.add(part)
    return frozenset(parts)


def _operation_parts(text, family):
    """A whole operation is a closed complete phrase, never an unknown subtype."""
    name = _operation_name(text)
    if family in {'foundations', 'monolith_vertical', 'monolith_horizontal'}:
        body = _operation_body(name)
        construction = r'(?:устройство\s+)?(?:монолитн(?:ых|ые|ой|ая)\s+)?(?:железобетонн(?:ых|ые|ой|ая)\s+)?'
        body = re.sub('^'+construction, '', body)
        if family == 'foundations':
            return _closed_parts(body, [('pile_caps', r'ростверк(?:ов|и|а)?'),
                ('foundation_slabs', r'фундаментн(?:ых|ые|ая|ой)\s+плит(?:ы|а)?'),
                ('footings', r'фундамент(?:ов|ы|а|ами|ах)?')])
        if family == 'monolith_vertical':
            whole = frozenset({'walls', 'columns', 'pylons'})
            if re.fullmatch(r'верт\.?\s+констр\.?', body):
                return whole
            prefix = r'вертикальн(?:ых|ые|ая|ой)\s+'
            generic = re.fullmatch(prefix+r'конструкц(?:ий|ии|ия)(?:\s*(\(.*\)|:.*))?', body)
            if generic:
                return whole if not generic[1] else _closed_parts(generic[1], [
                    ('walls', r'стен(?:ы|а)?'), ('columns', r'колонн(?:ы|а)?'), ('pylons', r'пилон(?:ов|ы|а)?')])
            body = re.sub('^'+prefix, '', body)
            return _closed_parts(body, [('walls', r'стен(?:ы|а)?'),
                ('columns', r'колонн(?:ы|а)?'), ('pylons', r'пилон(?:ов|ы|а)?')])
        whole = frozenset({'plates', 'beams'})
        if body == 'пп':
            return whole
        prefix = r'горизонтальн(?:ых|ые|ая|ой)\s+'
        generic = re.fullmatch(prefix+r'конструкц(?:ий|ии|ия)(?:\s*(\(.*\)|:.*))?', body)
        if generic and not generic[1]:
            return whole
        body = generic[1] if generic else re.sub('^'+prefix, '', body)
        body = body.replace('плит перекрытий и покрытий', 'плит перекрытий, плит покрытий')
        return _closed_parts(body, [('plates', r'плит(?:ы|а)?\s+(?:перекрыти[йя]|покрыти[йя])'),
                                    ('beams', r'бал(?:ок|ки|ка)')])
    if family in {'itp_thermomechanical', 'itp_automation'}:
        # Closed whole-system aliases; arbitrary extra operations are retained.
        name = name.replace('индивидуальный тепловой пункт', 'итп')
        name = re.sub(r'^(?:монтаж|устройство)\s+', '', name)
        name = re.sub(r'\bитп\s*(?:№\s*)?\d+(?:\s*(?:[/,;]|и)\s*\d+)*', 'итп', name)
        name = re.sub(r'[.,:;]', ' ', name)
    # A broad family does not equate МОП with apartments, tile with concrete,
    # painting with plastering, or any other unrecognised named composition.
    return frozenset({'operation:'+_text(name)}) if family else frozenset()


def _structural_task_name(name):
    # Only a whole structural label may inherit its operation from WBS.
    # A procurement, inspection or another unnamed activity cannot become a
    # construction operation merely because its parent is a construction row.
    return bool(re.fullmatch(r'(?:\d+(?:[- ](?:ый|ой|ий|го|й))?\s*этаж|этаж\s*\d+|тех(?:нический)?\s*этаж)', _text(name)))


def _descriptor(name, context, location_context=(), *, hierarchy_ambiguous=False, inherit_operation=True):
    names = [name, *reversed(context)]
    operations = names if inherit_operation else [name]
    operation_source = next((text for text in operations if _operation(text)), '')
    family = _operation(operation_source)
    if re.search(r'демонтаж|разборк|снятие|этаж\s+верт\s+пп\b|^(?:закупк|поставк|доставк|транспортировк|приемк|приёмк|проектирован|контроль|осмотр|обследован)', _text(name)):
        family = None
    location, floors, zones, systems = frozenset(), frozenset(), frozenset(), frozenset()
    partial_name = re.sub(r'тепломеханическ\w*\s+часть', '', _text(name)) if family == 'itp_thermomechanical' else _text(name)
    ambiguous = hierarchy_ambiguous or bool(re.search(
        r'\bкроме\b|за исключением|не включая|частично|\bчасть\b|в части', partial_name))
    locations = [(text, False) for text in [name, *reversed(context)]] + [(text, True) for text in location_context]
    for text, whole_object in locations:
        found, bad = _locations(text, whole_object=whole_object)
        if found and not location:
            location, ambiguous = found, ambiguous or bad
        elif found and location and not location <= found and not found <= location:
            ambiguous = True
        found_floors = _floors(text)
        if found_floors and not floors:
            floors = found_floors
        elif found_floors and floors and not floors <= found_floors:
            ambiguous = True
        found_zones, bad = _zones(text)
        ambiguous = ambiguous or bad
        if found_zones and not zones:
            zones = found_zones
        elif found_zones and zones and not zones <= found_zones:
            ambiguous = True
        found_systems = _systems(text)
        if found_systems and not systems:
            systems = found_systems
        elif found_systems and systems and not systems <= found_systems:
            # An unnumbered ancestor names the same type of plant; a second
            # numbered plant is a conflicting explicit source scope.
            ambiguous = ambiguous or found_systems != frozenset({'itp'})
        if (re.search(r'(?<!\d)[-−]\s*\d+[^.;]{0,40}\bэтаж|этаж\w*\s*[-−]\s*\d|подземн\w*\s+этаж', _text(text))
                or (re.search(r'\bэтаж', _text(text)) and not found_floors)
                or re.search(r'\bитп\s*(?:№\s*)?[a-zа-я]\b', _text(text))
                or re.search(r'\d+(?:-го)?\s*(?:/|по|до|или)\s*\d+(?:-го)?\s*этаж', _text(text))
                or re.search(r'\bитп\s*(?:№\s*)?\d+\s*[-–—]\s*\d+', _text(text))
                or re.search(r'\b(?:участк|секци|зон[аыуе]\b|осях\b|осям\b|оси\b|отметк)', _text(text))):
            ambiguous = True
    # A cross-product of floors and several buildings is not a proved scope.
    if len(location) > 1 and floors:
        ambiguous = True
    materials = frozenset()
    if family in {'facade_vertical', 'facade_horizontal'}:
        for named in map(_text, names):
            found = (frozenset({'aluminium_composite'}) if re.search(r'алюмокомпозит|композитн\w*\s+панел', named)
                     else frozenset({'aluminium'}) if re.search(r'алюминиев\w*\s+панел', named) else frozenset())
            if not materials:
                materials = found
            elif found and materials != found:
                ambiguous = True
    # An ancestor may classify the family, but cannot declare an unknown leaf
    # subtype to be the whole construction package. Only a closed structural
    # floor label delegates its operation description to that ancestor.
    parts_source = operation_source if _structural_task_name(name) else name
    parts = _operation_parts(parts_source, family)
    if family and not parts:
        ambiguous = True
    return {'family': family, 'operation_parts': parts, 'locations': location, 'floors': floors, 'zones': zones,
            'systems': systems, 'materials': materials, 'ambiguous': ambiguous}


def task_descriptor(task):
    context = _path(task.get('parent_path')) + [task.get('section') or '']
    result = _descriptor(task.get('name') or '', context, [task.get('object') or ''],
                         hierarchy_ambiguous=task.get('hierarchy_ambiguous') is True,
                         inherit_operation=_structural_task_name(task.get('name') or ''))
    # A corpus package may name the whole system while the KS names one part.
    # Discovery is useful, but these families never authorize an aggregate or
    # turn a part into the whole package's percentage.
    if task.get('source_format') == 'corpus-gpr-v1':
        name = _text(task.get('name'))
        broad = ({'monolith_vertical', 'monolith_horizontal'} if name == 'монолит надземной части' else
                 {'itp_thermomechanical', 'itp_automation'} if name in {'итп', 'индивидуальный тепловой пункт'} else
                 {'facade_vertical', 'facade_horizontal'} if name == 'монтаж нвф' else set())
        if broad:
            result['candidate_families'] = frozenset(broad)
    return result


def item_descriptor(ledger, item):
    context = [item.get('scope') or '', *_path(item.get('section_path'))]
    locations = [_label(item.get('object_scope') or ledger.get('object_scope')),
                 _label(item.get('system_scope') or ledger.get('system_scope'))]
    return _descriptor(item.get('name') or '', context, locations)


def _scope_key(descriptor):
    return tuple(tuple(sorted(descriptor[field])) for field in SCOPE_FIELDS)


def _equal_scope(source, target):
    return (source['family'] == target['family'] and not source['ambiguous'] and not target['ambiguous'] and bool(source['locations'])
            and _scope_key(source) == _scope_key(target))


def _candidate(source, target):
    broad_candidate = source['family'] in target.get('candidate_families', ())
    if not source['family'] or (source['family'] != target['family'] and not broad_candidate
            and (source['family'], target['family']) != ('pile_testing', 'trial_piles_and_testing')):
        return False
    for field in ('locations', 'floors', 'zones', 'systems'):
        if source[field] and target[field] and not target[field] <= source[field]:
            return False
    return True


def _cohort_scope(source, targets):
    if (source['ambiguous'] or not source['locations'] or not targets
            or any(t['ambiguous'] or t['family'] != source['family'] for t in targets)):
        return False
    # Every declared source dimension must be exactly covered by the target
    # set. An omitted target dimension cannot allocate an explicit source part.
    for field in SCOPE_FIELDS:
        if source[field] != frozenset().union(*(target[field] for target in targets)):
            return False
    # A union alone would accept duplicate leaves or an unknown relationship
    # between several floor/zone dimensions. Require a simple partition of one
    # declared dimension; every other dimension must be identical.
    dimensions = SCOPE_FIELDS
    partitioned = [field for field in dimensions if any(target[field] != source[field] for target in targets)]
    if len(partitioned) != 1:
        return False
    field = partitioned[0]
    seen = set()
    for target in targets:
        if not target[field] or seen.intersection(target[field]):
            return False
        seen.update(target[field])
    return True


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=list).encode()).hexdigest()


def _compile(rows, tid, cut):
    components, members = [], []
    annual = defaultdict(list)
    for row in rows:
        item = row['item']
        component_key = (contracts._norm(item.get('position')), contracts._norm(item.get('name')),
                         contracts._norm(item.get('scope')))
        annual[component_key].append(row)
    invalid = None
    for component_key, annual_rows in annual.items():
        years = [row['ledger'].get('period_year') for row in annual_rows]
        group_invalid = ('unverified_duplicate_marker' if any(row['item'].get('is_duplicate') is True
                         or row['view'].get('duplicate_marker_present') is True for row in annual_rows) else
                         'duplicate_annual_position' if len(set(years)) != len(years)
                         or any(type(year) is not int or year <= 0 for year in years) else None)
        plans = [contracts._number(row['item'].get('plan_quantity')) for row in annual_rows]
        if any(plan is None or plan <= 0 for plan in plans):
            group_invalid = group_invalid or 'plan_unknown'
        elif any(abs(plan-plans[0]) > max(1e-6, abs(plans[0])*1e-7) for plan in plans):
            group_invalid = group_invalid or 'annual_plan_changed'
        units = {quantities._unit(row['item'].get('unit')) for row in annual_rows}
        if len(units) != 1 or not all(units):
            group_invalid = group_invalid or 'annual_unit_changed'
        if any(type(year) is int and year > int(cut[:4]) for year in years):
            group_invalid = group_invalid or 'future_annual_source'
        done = []
        for row in annual_rows:
            view = row['view']
            value = view.get('completed_quantity')
            if value is None:
                value = view.get('reported_completed_quantity')
            number = contracts._number(value)
            if view.get('future_periods_excluded') is not False or number is None or number < 0:
                group_invalid = group_invalid or 'quantity_unknown_or_future'
            else:
                done.append(number)
        latest = max(annual_rows, key=lambda row: row['ledger'].get('period_year') or 0)
        plan = contracts._number(latest['view'].get('plan_quantity'))
        if plan is None or plan <= 0:
            group_invalid = group_invalid or 'plan_unknown'
        component_id = 'auto:'+_digest((tid, progress.contract_identity(rows[0]['ledger']), component_key))[:24]
        components.append({'component_id': component_id, 'task_id': tid,
                           'item_ids': [row['item_id'] for row in annual_rows]})
        members.append({'member_key': component_id,
                        'is_duplicate': any(row['item'].get('is_duplicate') is True or row['view'].get('duplicate_marker_present') is True for row in annual_rows),
                        'progress': None if group_invalid else sum(done)/plan,
                        'unit': latest['view'].get('unit'),
                        **{field: latest['view'].get(field) for field in
                           ('planned_work_amount', 'planned_cost_split', 'planned_work_amount_basis', 'valuation_key')}})
        invalid = invalid or group_invalid
    metric = progress.aggregate_quantities(members)
    return components, members, metric, invalid


def suggest(source, snapshot, cut):
    """Return current-source proposals and safe initial bindings; never write."""
    views = progress.quantity_views(snapshot, cut)
    records = []
    for li, ledger in enumerate((snapshot or {}).get('ledgers') or []):
        for ii, item in enumerate(ledger.get('items') or []):
            key = f'{li}:{ii}'
            records.append({'item_id': key, 'ledger': ledger, 'item': item, 'view': views[key]})
    return _suggest(source, snapshot, cut, records)


def suggest_catalog(catalog, cut):
    """Audit the exact classifier against a protected canonical catalog read."""
    source = {'state': catalog.get('source_state'), 'source_sha256': catalog.get('source_sha256'),
              'tasks': {task['task_id']: task for task in catalog.get('tasks') or []}}
    snapshot = {'snapshot_id': catalog.get('snapshot_id'),
                'taken_at': str(catalog.get('snapshot_id') or '')[:10]}
    records = []
    for row in catalog.get('items') or []:
        ledger = {field: row.get(field) for field in
                  ('customer', 'contractor', 'contract', 'contract_date', 'period_year', 'object_scope', 'system_scope',
                   'site_scope', 'scope_evidence', 'contract_date_evidence', 'source_date_key', 'file_sha256')}
        ledger['source'] = row.get('ledger_source') or {}
        records.append({'item_id': row['item_id'], 'ledger': ledger, 'item': row, 'view': row})
    return _suggest(source, snapshot, cut, records)


def _suggest(source, snapshot, cut, records):
    # Verify against the complete source universe before splitting by scope or
    # annual component. Item IDs still refer to their original catalog rows.
    universe = [record['item'] for record in records]
    retained = {id(item) for item in ledgers.aggregation_members(universe, include_groups=True)}
    records = [record for record in records if id(record['item']) in retained]
    configuration = {'tasks': [], 'components': [],
                     'note': 'Автоматически по точному типу работ и явно указанному полному участку исходников.'}
    result = {'configuration': configuration, 'rule_version': RULE_VERSION,
              'source_sha256': source.get('source_sha256'), 'snapshot_id': (snapshot or {}).get('snapshot_id'),
              'bindings': {}, 'cohorts': [], 'candidates': [], 'coverage': {}}
    can_automate = (source.get('state') == 'approved_gpr'
                    and re.fullmatch(r'[0-9a-f]{64}', str(source.get('source_sha256') or ''))
                    and re.fullmatch(r'\d{4}-\d{2}-\d{2}-[0-9a-f]{64}', str((snapshot or {}).get('snapshot_id') or ''))
                    and progress.snapshot_date(snapshot) and progress.snapshot_date(snapshot) <= cut)
    tasks = source.get('tasks') or {}
    descriptors = {tid: task_descriptor(task) for tid, task in tasks.items()}
    groups = defaultdict(list)
    for record in records:
        ledger, item = record['ledger'], record['item']
        if item.get('is_group') is True:
            continue
        descriptor = item_descriptor(ledger, item)
        identity = progress.contract_identity(ledger)
        key = (identity, descriptor['family'], _scope_key(descriptor), descriptor['ambiguous'])
        groups[key].append(dict(record, descriptor=descriptor))
    proposed_tasks = defaultdict(list)
    reasons = defaultdict(int)
    for key, rows in groups.items():
        identity, family, scope, ambiguous = key
        descriptor = rows[0]['descriptor']
        candidates = [tid for tid, target in descriptors.items() if _candidate(descriptor, target)]
        reason = ('operation_unknown' if not family else 'contract_identity_unknown' if not all(identity)
                  else 'contract_date_after_cut' if contracts._date(rows[0]['ledger'].get('contract_date'))
                      and contracts._date(rows[0]['ledger']['contract_date']) > cut
                  else 'scope_ambiguous' if ambiguous else 'location_unknown' if not descriptor['locations']
                  else 'no_matching_task' if not candidates else 'source_unapproved' if not can_automate else None)
        group_id = 'cohort:'+_digest(key)[:24]
        source_components, source_members, source_metric, source_error = _compile(rows, group_id, cut)
        details = {'item_ids': [row['item_id'] for row in rows], 'operation': family,
                   'source_metric': source_metric, 'source_components': source_components,
                   'scope': {field: sorted(descriptor[field]) for field in SCOPE_FIELDS},
                   'candidate_task_ids': candidates, 'reason': reason,
                   'source_scope': rows[0]['item'].get('scope') or '',
                   'source_name': rows[0]['item'].get('name') or ''}
        if reason is None and len(candidates) == 1 and _equal_scope(descriptor, descriptors[candidates[0]]):
            proposed_tasks[candidates[0]].append((rows, details))
            continue
        cohort = reason is None and len(candidates) > 1 and _cohort_scope(descriptor, [descriptors[tid] for tid in candidates])
        if cohort:
            details.update(cohort_id=group_id, task_ids=candidates,
                           basis='shared_source_scope', leaf_allocation='not_provided')
            result['cohorts'].append(details)
        else:
            details['reason'] = reason or 'incomplete_or_shared_target_scope'
            result['candidates'].append(details)
            reasons[details['reason']] += len(rows)
    # Two source cohorts, or a cohort and a leaf, cannot both claim the same
    # complete front. Different contracts need explicit front boundaries;
    # nested source scopes need an explicit decomposition of those quantities.
    claims = [('cohort', cohort, set(cohort['task_ids'])) for cohort in result['cohorts']]
    claims += [('leaf', details, {tid}) for tid, proposals in proposed_tasks.items() for _, details in proposals]
    blocked = set()
    for i, (kind, details, tids) in enumerate(claims):
        for other_kind, other, other_tids in claims[i+1:]:
            if ((kind == 'cohort' or other_kind == 'cohort') and details['operation'] == other['operation']
                    and tids.intersection(other_tids)):
                blocked.update((id(details), id(other)))
    if blocked:
        retained = []
        for cohort in result['cohorts']:
            if id(cohort) in blocked:
                cohort['reason'] = 'overlapping_source_scopes'
                result['candidates'].append(cohort)
                reasons[cohort['reason']] += len(cohort['item_ids'])
            else:
                retained.append(cohort)
        result['cohorts'] = retained
    # A task cannot silently combine several contracts that claim the same
    # physical scope. The operator needs the distinct fronts, not a name guess.
    for tid, proposals in proposed_tasks.items():
        if any(id(details) in blocked for _, details in proposals):
            for _, details in proposals:
                details['reason'] = 'overlapping_source_scopes'
                result['candidates'].append(details)
                reasons[details['reason']] += len(details['item_ids'])
            continue
        rows = [row for group, _ in proposals for row in group]
        identities = {progress.contract_identity(row['ledger']) for row in rows}
        if len(identities) != 1:
            for _, details in proposals:
                details['reason'] = 'multiple_contract_scopes'
                result['candidates'].append(details)
                reasons[details['reason']] += len(details['item_ids'])
            continue
        components, members, metric, invalid = _compile(rows, tid, cut)
        if invalid or metric['ratio'] is None:
            for _, details in proposals:
                details['reason'] = invalid or 'metric_basis_unknown'
                result['candidates'].append(details)
                reasons[details['reason']] += len(details['item_ids'])
            continue
        configuration['tasks'].append({'task_id': tid, 'mode': 'quantities', 'scope_confirmed': True, 'actual_finish': ''})
        configuration['components'].extend(components)
        result['bindings'][tid] = {'basis': 'closed_operation_and_exact_scope', 'rule_version': RULE_VERSION,
                                  'operation': rows[0]['descriptor']['family'], 'metric': metric,
                                  'members': members, 'item_ids': [row['item_id'] for row in rows]}
    result['coverage'] = {'source_positions': sum(len(rows) for rows in groups.values()),
                          'source_rows': len(records), 'excluded_source_groups': sum(row['item'].get('is_group') is True for row in records),
                          'automatic_tasks': len(configuration['tasks']),
                          'automatic_positions': sum(len(binding['item_ids']) for binding in result['bindings'].values()),
                          'cohorts': len(result['cohorts']), 'cohort_positions': sum(len(c['item_ids']) for c in result['cohorts']),
                          'candidate_positions': sum(len(c['item_ids']) for c in result['candidates']), 'reasons': dict(reasons)}
    return result


def _covered_package_kind(text):
    """Recognize an explicit source heading, never an equipment/finish leaf."""
    name = _operation_name(text)
    if 'индивидуальный тепловой пункт' in name or re.match(r'^итп\b', name):
        return 'itp'
    if re.fullmatch(r'(?:устройство\s+)?монолитн\w*\s+(?:железобетонн\w*\s+)?конструкц\w*\s+надземной\s+части', name):
        return 'monolith_above'
    if re.fullmatch(r'(?:устройство\s+)?монолитн\w*\s+(?:железобетонн\w*\s+)?конструкц\w*\s+подземной\s+части(?:\s*\([^)]*\))?', name):
        return 'monolith_below'
    if re.fullmatch(r'монтаж\s+светопрозрачных\s+конструкций\s+(?:наружное\s+остекление\s+фасадов|внутреннее\s+остекление(?:\s*\([^)]*\))?)', name):
        return 'glazing'
    if re.fullmatch(r'устройство\s+отделки\s+фасадов\s*\((?:вертикальная|горизонтальная)\s+часть\)', name):
        return 'nvf'
    if re.match(r'^устройство\s+кладки\s+стен\s+и\s+перегородок\b', name):
        return 'masonry'
    return None


def _target_package_kind(task):
    if task.get('source_format') != 'corpus-gpr-v1':
        return None
    name = _text(task.get('name'))
    return ({'итп': 'itp', 'индивидуальный тепловой пункт': 'itp',
             'монолит надземной части': 'monolith_above',
             'подземная часть — закрытие': 'monolith_below',
             'подземная часть - закрытие': 'monolith_below',
             'светопрозрачные конструкции': 'glazing', 'монтаж нвф': 'nvf',
             'кладка стен и перегородок': 'masonry'}.get(name))



def _covered_location_possible(source_locations, target_locations):
    if source_locations.intersection(target_locations):
        return True
    for source in source_locations:
        for target in target_locations:
            left, right = source.split(':'), target.split(':')
            if len(left) == len(right) == 4 and left[0] == right[0] == 'object' and left[1] == right[1]:
                if all(a == b or 'unspecified' in (a, b) for a, b in zip(left[2:], right[2:])):
                    return True
    return False


def covered_subtrees(source, snapshot, cut):
    """Complete source subtrees shown beside their possible corpus packages.

    This is explicitly *source-only* evidence. Equal source membership does
    not prove coverage of a whole GPR package, the missing floors, or the
    distribution of one plant between several buildings. These groups never
    produce a task binding, a GPR seed or a certified finish.
    """
    if source.get('state') != 'approved_gpr' or not progress.snapshot_date(snapshot) or progress.snapshot_date(snapshot) > cut:
        return []
    tasks = source.get('tasks') or {}
    groups = {}
    for li, ledger in enumerate((snapshot or {}).get('ledgers') or []):
        records = ledger.get('items') or []
        retained = {id(item) for item in ledgers.aggregation_members(records)}
        for ii, item in enumerate(records):
            if id(item) not in retained:
                continue
            # context_headings is bounded preceding context, not an ancestor
            # chain. Only its most recent heading can be the active chapter.
            contexts = item.get('context_headings') or []
            ancestors = ([contexts[-1]] if contexts else []) + list(item.get('section_path') or [])
            anchor = next((heading for heading in reversed(ancestors)
                           if _covered_package_kind(heading.get('name'))), None)
            if not anchor:
                continue
            kind = _covered_package_kind(anchor['name'])
            named_scope = [heading.get('name') or '' for heading in ancestors]
            named_scope.extend([_label(item.get('object_scope')), item.get('scope') or '', item.get('name') or ''])
            location, bad = _locations(' '.join(named_scope))
            candidates = []
            for tid, task in tasks.items():
                if _target_package_kind(task) != kind:
                    continue
                target_locations, _ = _locations(task.get('object') or '', whole_object=True)
                # Location is a discovery boundary only. Unknown locations
                # retain the project-wide source without claiming any object.
                if location and target_locations and not _covered_location_possible(location, target_locations):
                    continue
                candidates.append(tid)
            origin = item.get('source') or {}
            coordinate = anchor.get('source') or {}
            identity = progress.contract_identity(ledger)
            if not all(identity) or not coordinate.get('row') or not origin.get('filename') or not origin.get('sheet'):
                continue
            key = (li, origin['filename'], origin['sheet'], coordinate['row'], kind)
            if key not in groups:
                gid = 'source-group:'+_digest((identity, origin['filename'], origin['sheet'], ledger.get('period_year'),
                                               coordinate['row'], anchor['name']))[:24]
                scope_text = ''
                groups[key] = {'group_id': gid, 'kind': kind, 'source_name': anchor['name'],
                    'source_scope': scope_text, 'contractor': ledger.get('contractor'), 'contract': ledger.get('contract'),
                    'period_year': ledger.get('period_year'), 'snapshot_date': progress.snapshot_date(snapshot),
                    'source': {**origin, 'row': coordinate['row'], 'cell': coordinate.get('cell')},
                    'source_complete': ledger.get('source_complete') is True or ledger.get('unread_rows_count') == 0,
                    'ledger_source_complete': ledger.get('source_complete') is True,
                    'candidate_task_ids': [], 'target_scope_confirmed': False,
                    'location_known': True, 'location_ambiguous': False, 'unknown_location_positions': 0,
                    '_scope_names': [],
                    'scope_reason': ('Выполнение относится только к указанному разделу и участку КС. '
                                     'Полнота всего пакета ГПР и распределение по отдельным работам не подтверждены.'
                                     if location else 'Выполнение раздела КС известно по проекту; '
                                     'распределение между корпусами в источнике не выделено.'),
                    'item_ids': [], 'components': [], 'unverified_duplicate_item_ids': []}
            group = groups[key]
            group['candidate_task_ids'] = sorted(set(group['candidate_task_ids']).union(candidates))
            group['_scope_names'].extend(text for text in named_scope if _locations(text)[0])
            group['location_known'] = group['location_known'] and bool(location)
            group['location_ambiguous'] = group['location_ambiguous'] or bad
            group['unknown_location_positions'] += int(not location)
            item_id = f'{li}:{ii}'
            group['item_ids'].append(item_id)
            if item.get('is_duplicate') is True:
                group['unverified_duplicate_item_ids'].append(item_id)
            group['components'].append({'component_id': group['group_id']+':'+str(ii),
                'task_id': group['group_id'], 'item_ids': [item_id]})
    retained = []
    for group in groups.values():
        group['source_scope'] = ' · '.join(dict.fromkeys(group.pop('_scope_names')))
        if not group['candidate_task_ids']:
            continue
        if group['unknown_location_positions']:
            group['scope_reason'] = ('Выполнение раздела КС известно по проекту; распределение между корпусами в источнике не выделено.'
                if not group['source_scope'] else 'В разделе КС объединены указанные участки и позиции без уточнения корпуса. '
                'Полнота всего пакета ГПР и распределение по работам не подтверждены.')
        else:
            group['scope_reason'] = 'Выполнение относится только к указанному разделу и участкам КС. Полнота всего пакета ГПР и распределение по отдельным работам не подтверждены.'
        retained.append(group)
    return retained
