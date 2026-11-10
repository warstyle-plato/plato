"""Reviewable quantity groups and suggestions; never creates forecast evidence."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import unicodedata

import developaid_cumulative_progress as progress
import developaid_monitor_contracts as contracts
import developaid_gpr_cumulative_matching as matching
import developaid_monitor_ledgers as ledgers
import developaid_schedule_physical as quantities


def _text(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е').split())


def identity(row):
    """The canonical source work, qualified by its unit and full plan."""
    work = _scope_key(row)
    unit, plan = quantities._unit(row.get('unit')), quantities._number(row.get('plan_quantity'))
    if not work or not unit or plan is None or plan <= 0:
        return None
    fields = [work, unit, plan]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def rules(configuration, items):
    eligible = {id(row) for row in ledgers.aggregation_members(list(items.values()))}
    result = []
    for component in configuration['components']:
        rows = [items.get(key) for key in component['item_ids']]
        if (not rows or any(row is None or id(row) not in eligible or not identity(row) for row in rows)
                or progress.annual_component_reason(rows)):
            continue
        result.append({'identity_schema': 2, 'task_id': component['task_id'],
                       'identities': sorted({identity(row) for row in rows}),
                       'scope_keys': sorted({_scope_key(row) for row in rows})})
    return result


def _scope_key(row):
    # Also works on generic source records. Production passes protected
    # position views, whose annual key was computed from the original ledger.
    return row.get('annual_work_key') or progress.annual_work_identity(row, row)


def _contract_packet(row, item_id):
    """A presentation group; it never supplies a quantity or a GPR binding."""
    identity = progress.contract_identity(row)
    if not all(identity):
        identity = ('incomplete', contracts._norm(row.get('customer')),
                    contracts._norm(row.get('contractor')), contracts._contract_number(row.get('contract')),
                    contracts._date(row.get('contract_date')) or contracts._source_date_key(row))
        # An absent party is not proof that two ledgers name one contract.
        identity += (item_id.split(':')[0],)
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]


def _places(text):
    text = _text(text)
    text = re.sub(r'(?<=\d)[-–]?(?:го|ый|ой|й)\b', '', text)
    atom = r'-?\d+(?:[./]\d+)*[а-яa-z]?'
    expression = atom + r'(?:\s*(?:[-–—,;]|\bи\b)\s*' + atom + r')*'
    places, uncertain = {}, False
    for kind, root, marker in (
        ('corpus', 'корпус', r'\b(?:корпус(?:а|ов|е|у|ом|ам|ами|ах)?|корп\.?|к\.?)(?![а-яa-z])'),
        ('section', 'секци', r'\b(?:секци(?:я|и|й|ю|е|ей|ям|ями|ях)|секц\.?)(?![а-яa-z])'),
        ('floor', 'этаж', r'\b(?:этаж(?:и|а|ей|е|у|ом|ам|ами|ах)?|эт\.?)(?![а-яa-z])'),
    ):
        values = set()
        # Unknown forms are evidence of ambiguity, never absence of a place.
        if any(not re.fullmatch(marker, word) for word in re.findall(r'\b'+root+r'[а-я]*\b', text)):
            uncertain = True
        for mention in re.finditer(marker, text):
            prefix = r'\s*[№#]?\s*' + (r'[-–]?\s*' if kind != 'floor' else '')
            after = re.match(prefix + '(' + expression + ')', text[mention.end():])
            before = (re.search('(' + expression + r')\s*$', text[:mention.start()])
                      if kind == 'floor' else None)
            match = after or before
            if not match:
                # The preposition «к» alone is not a building marker.
                if mention.group().rstrip('.') != 'к':
                    uncertain = True
                continue
            value = match.group(1)
            for part in re.split(r'\s*(?:[,;]|\bи\b)\s*', value):
                span = re.fullmatch('(' + atom + r')\s*[-–—]\s*(' + atom + ')', part)
                if not span:
                    values.add(part.strip())
                    continue
                a, b = span.groups()
                if re.fullmatch(r'-?\d+', a) and re.fullmatch(r'-?\d+', b) and 0 <= int(b)-int(a) <= 100:
                    values.update(str(i) for i in range(int(a), int(b)+1))
                else:
                    uncertain = True
        places[kind] = values
    return places, uncertain


def _tokens(text):
    return {t[:6] for t in re.findall(r'[а-яa-z]{3,}', _text(text))
            if t not in {'работа', 'работы', 'устройство', 'строительство', 'корпус', 'секция', 'этаж'}}


def _candidates(group, prepared_tasks):
    label = ' '.join([group['scope'], group['name'], *(group.get('source_context') or [])])
    (places, uncertain), tokens = _places(label), _tokens(group['name'])
    operation_body = matching._operation_body(group['name'])
    found = []
    for task, other, other_uncertain, task_tokens, task_body in prepared_tasks:
        if any(places[k] and other[k] and places[k] != other[k] for k in places):
            continue
        shared = tokens & task_tokens
        if not shared:
            continue
        score = len(shared) / max(1, min(len(tokens), len(task_tokens)))
        exact = _text(group['name']) == _text(task['name'])
        same_corpus = bool(places['corpus'] and places['corpus'] == other['corpus'])
        # Token containment is discovery, never proof of the whole operation.
        # Generic equal names remain useful review hints; unequal phrases need
        # the same complete set of named operations before preselection.
        whole_label = bool(operation_body) and operation_body == task_body
        found.append({'task_id': task['task_id'], 'score': score + int(exact),
                      'strong': same_corpus and not uncertain and not other_uncertain and whole_label,
                      'reason': 'Совпадают корпус и название работ.' if exact and same_corpus
                      else 'Совпадают слова в названии. Проверьте участок и состав работы.'})
    return sorted(found, key=lambda c: (-c['score'], c['task_id']))


def build(items, tasks, configuration, cut, previous_rules=(), *, snapshot=None, views=None):
    views = views if views is not None else items
    prepared_tasks = [(task, *_places(str(task.get('object') or '') + ' ' + task['name']),
                       _tokens(task['name']), matching._operation_body(task['name'])) for task in tasks]
    buckets = defaultdict(list)
    # Run the shared eligibility owner on the full universe, before detaching
    # groups. A duplicate flag alone is not proof and must remain reviewable.
    eligible = {id(row) for row in ledgers.aggregation_members(list(views.values()))}
    excluded = []
    for item_id, row in items.items():
        view = views[item_id]
        if id(view) not in eligible:
            excluded.append(dict(item_id=item_id, is_group=view.get('is_group') is True,
                                 is_duplicate=view.get('is_duplicate') is True, source=view.get('source')))
            continue
        # Annual identity deliberately excludes plan/unit/year. A changed plan
        # or unit is a conflict in one work, never a second independent plan.
        key = _scope_key(view) or ('unqualified', item_id)
        buckets[key].append(item_id)
    rule_targets = defaultdict(set)
    previous_scopes = set()
    task_ids = {t['task_id'] for t in tasks}
    for rule in previous_rules:
        if isinstance(rule, dict) and rule.get('identity_schema') == 2 and rule.get('task_id') in task_ids:
            previous_scopes.update(rule.get('scope_keys') or [])
            for fingerprint in rule.get('identities') or []:
                rule_targets[fingerprint].add(rule['task_id'])
    linked = {i: c['task_id'] for c in configuration['components'] for i in c['item_ids']}
    groups, packets = [], {}
    for item_ids in buckets.values():
        row = views[item_ids[0]]
        gid = hashlib.sha256('|'.join(sorted(item_ids)).encode()).hexdigest()[:16]
        group = {k: row.get(k) or '' for k in ('name', 'scope', 'unit', 'contractor', 'contract', 'contract_date')}
        contract_id = _contract_packet(row, item_ids[0])
        packet = packets.setdefault(contract_id, dict(contract_id=contract_id,
            customer=row.get('customer') or '', contractor=group['contractor'], contract=group['contract'],
            contract_date=group['contract_date'], date_verified=bool(contracts._date(group['contract_date'])),
            identity_complete=bool(all(progress.contract_identity(row))),
            group_ids=[]))
        packet['group_ids'].append(gid)
        group['contract_id'] = contract_id
        group.update(group_id=gid, item_ids=item_ids, years=sorted({items[i]['period_year'] for i in item_ids
                     if type(items[i].get('period_year')) is int}),
                     component_id=(f"{group['scope']} — {group['name']}"[:98] + ' [' + gid + ']'),
                     rows=[dict(item_id=i, **{k: views[i].get(k) for k in
                           ('period_year', 'unit', 'plan_quantity', 'completed_quantity', 'source',
                            'reported_completed_quantity', 'completion_ratio', 'reported_completion_ratio',
                            'quantity_basis', 'quantity_date', 'snapshot_date', 'future_periods_excluded',
                            'section_path', 'object_scope', 'system_scope', 'site_scope')}) for i in item_ids])
        group['source_context'] = list(dict.fromkeys(str(value) for value in
            [row.get('object_scope'), row.get('system_scope'), row.get('site_scope'),
             *[(section.get('name') if isinstance(section, dict) else section)
               for section in row.get('section_path') or []]] if value))
        component = {'component_id': gid, 'task_id': '', 'item_ids': item_ids}
        evaluated = quantities._component(component, items, quantities._day(cut))
        if snapshot is not None:
            # Reuse the accepted GPR observation path for known undated source
            # quantities. No new percentage, completion date or pace formula.
            from developaid_schedule_gpr_physical import _observed_component
            evaluated = _observed_component(component, evaluated, items, views, snapshot, cut, ())
        group.update(plan_quantity=evaluated.get('plan_quantity'), completed_quantity=evaluated.get('completed_quantity'),
                     can_bind=evaluated.get('progress') is not None and not evaluated.get('requires_reconciliation'), issues=[],
                     progress=evaluated.get('progress'), progress_basis=evaluated.get('progress_basis') or 'По датированным периодам',
                     quantity_reason=evaluated.get('reason') or '')
        if not group['can_bind']:
            group['issues'].append(evaluated['reason'])
        if not group['scope']:
            group['issues'].append('Не указан корпус или участок. Уточните его перед привязкой.')
            group['can_bind'] = False
        if not _scope_key(row):
            group['issues'].append('В источнике не подтверждена полная идентичность работы: договор, позиция и участок. Связь лет не установлена; проверьте строки вручную.')
            group['can_bind'] = False
        candidates = _candidates(group, prepared_tasks)
        remembered = set()
        fingerprints = {identity(views[i]) for i in item_ids}
        changed = any(_scope_key(views[i]) in previous_scopes and not rule_targets.get(identity(views[i]))
                      for i in item_ids)
        if changed:
            group['issues'].append('По сравнению с проверенной привязкой изменились договор, единица или план. Проверьте группу заново.')
        if fingerprints and None not in fingerprints and all(rule_targets.get(f) for f in fingerprints):
            remembered = set.intersection(*(rule_targets[f] for f in fingerprints))
        if len(remembered) == 1:
            tid = next(iter(remembered))
            candidates = [dict(task_id=tid, strong=True, score=3,
                               reason='Ранее сохранённая привязка. Подтвердите её для нового архива.')]
        proposed = bool(not changed and candidates and candidates[0]['strong'] and
                        (len(candidates) == 1 or candidates[0]['score'] > candidates[1]['score'] + .25))
        group.update(candidates=candidates[:5], suggested_task_id=candidates[0]['task_id'] if proposed else '',
                     match_reason=candidates[0]['reason'] if candidates else 'Подходящая работа графика не найдена.',
                     status='proposed' if proposed and group['can_bind'] else 'review' if candidates or group['issues'] else 'unmatched')
        group['base_status'] = group['status']
        if any(i in linked for i in item_ids):
            group['status'] = 'bound' if all(i in linked for i in item_ids) else 'review'
            if group['status'] != 'bound':
                group['issues'].append('Часть строк уже привязана. Проверьте состав в ручной настройке.')
        groups.append(group)
    return {'groups': groups, 'contracts': list(packets.values()), 'contract_count': len(packets),
            'row_count': len(items), 'eligible_row_count': sum(len(g['item_ids']) for g in groups),
            'excluded_rows': excluded, 'excluded_group_rows': sum(row['is_group'] for row in excluded),
            'excluded_duplicate_rows': sum(row['is_duplicate'] for row in excluded),
            'group_count': len(groups), 'component_limit': quantities.MAX_ROWS}


def new_unbound(review_model, configuration, fresh):
    """Confirmed quantity works with unbound volumes absent when the scope was confirmed.

    The relation is the page's rule for pending volumes of the full-scope check:
    a group of a contract already bound to the work, a partly bound group of the
    work, or a group whose candidates name the work. It is a reason to check the
    scope again, never a binding.
    """
    confirmed = {t['task_id'] for t in configuration['tasks'] if t['mode'] == 'quantities' and t['scope_confirmed']}
    if not confirmed or not fresh:
        return {}
    groups = review_model.get('groups') or []
    linked = {i: c['task_id'] for c in configuration['components'] for i in c['item_ids']}
    by_contract = defaultdict(set)
    for group in groups:
        by_contract[group['contract_id']].update(linked[i] for i in group['item_ids'] if i in linked)
    found = defaultdict(list)
    for group in groups:
        if not any(i in fresh and i not in linked for i in group['item_ids']):
            continue
        related = (by_contract[group['contract_id']] | {linked[i] for i in group['item_ids'] if i in linked}
                   | {c['task_id'] for c in group.get('candidates') or []})
        for tid in sorted(related & confirmed):
            found[tid].append(group)
    return dict(found)
