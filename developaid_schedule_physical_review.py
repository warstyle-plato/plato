"""Reviewable quantity groups and suggestions; never creates forecast evidence."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import unicodedata

import developaid_schedule_physical as quantities


def _text(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().replace('ё', 'е').split())


def identity(row):
    """Stable across imports, including plan; neither row index nor filename is identity."""
    fields = [_text(row.get(k)) for k in
              ('contractor', 'contract', 'contract_date', 'scope', 'name', 'position', 'quantity_kind')]
    fields += [quantities._unit(row.get('unit')), quantities._number(row.get('plan_quantity'))]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode()).hexdigest()


def rules(configuration, items):
    return [{'task_id': c['task_id'], 'identities': sorted({identity(items[i]) for i in c['item_ids']}),
             'scope_keys': sorted({_scope_key(items[i]) for i in c['item_ids']})}
            for c in configuration['components']]


def _scope_key(row):
    return hashlib.sha256(json.dumps([_text(row.get(k)) for k in
                         ('name', 'scope', 'position', 'quantity_kind')], ensure_ascii=False).encode()).hexdigest()


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
    label = group['scope'] + ' ' + group['name']
    (places, uncertain), tokens = _places(label), _tokens(group['name'])
    found = []
    for task, other, other_uncertain, task_tokens in prepared_tasks:
        if any(places[k] and other[k] and places[k] != other[k] for k in places):
            continue
        shared = tokens & task_tokens
        if not shared:
            continue
        score = len(shared) / max(1, min(len(tokens), len(task_tokens)))
        exact = _text(group['name']) == _text(task['name'])
        same_corpus = bool(places['corpus'] and places['corpus'] == other['corpus'])
        found.append({'task_id': task['task_id'], 'score': score + int(exact),
                      'strong': same_corpus and not uncertain and not other_uncertain and (exact or score >= .75),
                      'reason': 'Совпадают корпус и название работ.' if exact and same_corpus
                      else 'Совпадают слова в названии. Проверьте участок и состав работы.'})
    return sorted(found, key=lambda c: (-c['score'], c['task_id']))


def build(items, tasks, configuration, cut, previous_rules=()):
    prepared_tasks = [(task, *_places(str(task.get('object') or '') + ' ' + task['name']),
                       _tokens(task['name'])) for task in tasks]
    buckets = defaultdict(list)
    # Plan is deliberately excluded here: changed plans must surface as a conflict.
    for item_id, row in items.items():
        key = tuple(_text(row.get(k)) for k in
                    ('contractor', 'contract', 'contract_date', 'scope', 'name', 'position', 'quantity_kind'))
        key += (quantities._unit(row.get('unit')),)
        if not row.get('name') or not row.get('scope'):
            key += (item_id,)
        buckets[key].append(item_id)
    rule_targets = defaultdict(set)
    previous_scopes = set()
    task_ids = {t['task_id'] for t in tasks}
    for rule in previous_rules:
        if isinstance(rule, dict) and rule.get('task_id') in task_ids:
            previous_scopes.update(rule.get('scope_keys') or [])
            for fingerprint in rule.get('identities') or []:
                rule_targets[fingerprint].add(rule['task_id'])
    linked = {i: c['task_id'] for c in configuration['components'] for i in c['item_ids']}
    groups = []
    for item_ids in buckets.values():
        row = items[item_ids[0]]
        gid = hashlib.sha256('|'.join(sorted(item_ids)).encode()).hexdigest()[:16]
        group = {k: row.get(k) or '' for k in ('name', 'scope', 'unit', 'contractor', 'contract', 'contract_date')}
        group.update(group_id=gid, item_ids=item_ids, years=sorted({items[i]['period_year'] for i in item_ids
                     if type(items[i].get('period_year')) is int}),
                     component_id=(f"{group['scope']} — {group['name']}"[:98] + ' [' + gid + ']'),
                     rows=[dict(item_id=i, **{k: items[i].get(k) for k in
                           ('period_year', 'plan_quantity', 'completed_quantity', 'source')}) for i in item_ids])
        evaluated = quantities._component({'component_id': gid, 'task_id': '', 'item_ids': item_ids},
                                         items, quantities._day(cut))
        group.update(plan_quantity=evaluated.get('plan_quantity'), completed_quantity=evaluated.get('completed_quantity'),
                     can_bind=evaluated.get('progress') is not None, issues=[],
                     quantity_reason=evaluated.get('reason') or '')
        if not group['can_bind']:
            group['issues'].append(evaluated['reason'])
        if not group['scope']:
            group['issues'].append('Не указан корпус или участок. Уточните его перед привязкой.')
            group['can_bind'] = False
        candidates = _candidates(group, prepared_tasks)
        remembered = set()
        fingerprints = {identity(items[i]) for i in item_ids}
        changed = any(_scope_key(items[i]) in previous_scopes and not rule_targets.get(identity(items[i]))
                      for i in item_ids)
        if changed:
            group['issues'].append('По сравнению с проверенной привязкой изменились договор, единица или план. Проверьте группу заново.')
        if fingerprints and all(rule_targets.get(f) for f in fingerprints):
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
    return {'groups': groups, 'row_count': len(items), 'group_count': len(groups),
            'component_limit': quantities.MAX_ROWS}
