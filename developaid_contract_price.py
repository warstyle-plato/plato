"""Explicit full contractual price, independent of an estimate's remaining scope.

Only a clause declaring the contract's price supplies this value. Act totals,
partial estimates and increases by an unspecified amount are not a full price.
The latest dated amendment of this condition wins; unrelated amendments keep it.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from developaid_contract_terms import _day, _edition
from developaid_monitor_ledgers import amount_basis

_PRICE = (r'(?:Цена\s+(?:настоящего\s+)?Договора|'
          r'Стоимость\s+(?:всех\s+)?Работ\s+по\s+(?:настоящему\s+)?Договору)')
_DECLARATION = re.compile(_PRICE + r'[^.;]{0,220}?\b(?:составляет|составит|устанавливается\s+в\s+размере)\s+', re.I)
_MONEY = re.compile(r'([\-−]?\d[\d \u00a0]*(?:[,.]\d{1,2})?)(?!\d)\s*'
                    r'(?:\([^)]{0,450}\)\s*)?руб(?:лей|ль|ля|\.)?\s*'
                    r'(?:,?\s*(\d{1,2})\s*коп(?:еек|ейка|ейки|\.)?)?', re.I)
_CHANGE = re.compile(r'(?:увеличить|уменьшить|изменить)\s+Цену\s+Договора\b|'
                     r'Цена\s+Договора\s+(?:увеличивается|уменьшается|изменяется)\b', re.I)
_PART = re.compile(r'\b(?:по|на|за|для)\s+(?:(?:перв\w*|втор\w*|треть\w*|четверт\w*|пят\w*|'
                   r'\d+(?:[-–]\w+)?|[ivx]+)\s+)?(?:этап\w*|раздел\w*|корпус\w*|очеред\w*)\b|'
                   r'в\s+части|на\s+завершение|дополнительн\w*\s+работ', re.I)
_TAX_START = re.compile(r'(?:в\s*том\s*числе|в\s*т\.?\s*ч\.?|включая|с\s+уч[её]том|с|без)\s*НДС(?![а-я])', re.I)
_OTHER_OBLIGATION = re.compile(r'\b(?:сумм[аы]|размер|аванс\w*|плат[её]ж\w*|оплат\w*|неустойк\w*|'
                               r'штраф\w*|пени|гаранти\w*|стоимость)\b|'
                               r'\bи\s+определен\w*|\bна\s+основании|\b\d+\.\d+\.', re.I)


def _tax_context(text, start):
    """Only the VAT qualification immediately attached to this price.

    A following VAT-only sentence can qualify the price. A new obligation or
    monetary object cannot lend its tax basis to the preceding contract price.
    Decimal points and руб./коп./в т. ч. keep their spelling and positions.
    """
    fragment = text[start:start+2000]
    leading = re.match(r'\s*(?:[,.:()–—-]\s*)*', fragment).end()
    if not _TAX_START.match(fragment, leading):
        return ''
    masked = list(fragment)
    for match in re.finditer(r'(?<=\d)\.(?=\d)|\b(?:руб|коп)\.|\bв\s*т\.\s*ч\.', fragment, re.I):
        for index in range(match.start(), match.end()):
            if masked[index] == '.':
                masked[index] = '~'
    boundary = re.search(r'[.!?;»]', ''.join(masked[leading:]))
    end = leading + boundary.start() if boundary else len(fragment)
    other = _OTHER_OBLIGATION.search(fragment, leading)
    if other:
        end = min(end, other.start())
    return fragment[:end]


def _value(match):
    if not match:
        return None, 'Полная цена договора после слова «составляет» не прочитана.'
    number = match[1].replace(' ', '').replace('\xa0', '').replace(',', '.').replace('−', '-')
    try:
        value = Decimal(number)
    except InvalidOperation:
        return None, 'Полная цена договора не прочитана как число.'
    if value < 0 or value > Decimal('1000000000000000'):
        return None, 'Полная цена договора отрицательная или выходит за допустимый диапазон.'
    if match[2] is not None:
        kopecks = Decimal(match[2]) / 100
        if '.' in number and value % 1 != kopecks:
            return None, 'Копейки в цифровой записи цены расходятся с копейками после слова «рублей».'
        value = value // 1 + kopecks
    return float(value), ''


def read(texts):
    from developaid_contract_documents import _date, _space
    candidates, warnings = [], []
    for page, raw in enumerate(texts, 1):
        text = _space(raw)
        declarations = list(_DECLARATION.finditer(text))
        for declaration in declarations:
            found = _MONEY.match(text, declaration.end())
            value, reason = _value(found)
            before = text[max(0, declaration.start()-120):declaration.start()]
            clauses = [m for m in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)+)\.?\s+', before)
                       if not _date(m[1]) and not re.fullmatch(r'\d{1,2}\.\d{1,2}\.\d{4}',m[1])]
            clause = clauses[-1][1] if clauses else ''
            end = found.end() if found else declaration.end()
            tax = _tax_context(text, end)
            quote = text[declaration.start():min(len(text), end+len(tax))]
            provisional = re.search(r'(?:предварительн\w*|ориентировочн\w*)\s*$', before, re.I)
            if provisional:
                quote = before[provisional.start():]+quote
            if _PART.search(declaration[0]):
                value, reason = None, 'Условие цены относится к отдельной части работ; новая полная цена договора не подтверждена.'
            basis = amount_basis(tax)
            if basis == 'conflicting':
                value, reason = None, 'В условии полной цены одновременно указаны «без НДС» и «с НДС».'
            if re.search(r'предварительн\w*|ориентировочн\w*', quote, re.I):
                value, reason = None, 'В документе цена названа предварительной; окончательная полная цена не подтверждена.'
            if reason:
                warnings.append(f'Стр. {page}: {reason}')
            rate = re.search(r'НДС\s*\(?\s*(\d{1,2}(?:[,.]\d+)?)\s*%', tax, re.I)
            candidates.append({'value': value, 'amount_basis': basis, 'vat_rate': float(rate[1].replace(',', '.')) if rate else None,
                               'vat_text': tax.strip(), 'page': page, 'clause': clause, 'quote': quote,
                               'reason': reason})
        for change in _CHANGE.finditer(text):
            # A price condition explicitly stating its new full value can
            # contain «изменяется и составляет». A separate delta is not it.
            if any(d.start() <= change.start() and change.end() <= d.end() for d in declarations):
                continue
            candidates.append({'value': None, 'amount_basis': 'unspecified', 'vat_rate': None, 'vat_text': '',
                'page': page, 'clause': '', 'quote': text[max(0,change.start()-50):change.end()+250],
                'reason': 'Цена договора изменена, но новая полная цена не указана или не прочитана.'})
            warnings.append(f'Стр. {page}: цена договора изменена; полная новая цена требует уточнения.')
    return {'candidates': candidates, 'changes_price': bool(candidates), 'warnings': warnings}


def resolve(records, cut):
    result = {'amount': None, 'amount_basis': 'unspecified', 'source': None, 'history': [], 'warnings': [], 'state': 'unknown'}
    groups = {}
    for record in records:
        if record.get('removed_at') or record.get('act') or (record.get('scan') and not record['scan'].get('confirmed_at')):
            continue
        if not (record.get('price') or {}).get('changes_price'):
            continue
        day = _edition(record)[1]
        if not _day(day):
            result['warnings'].append('В документе есть изменение цены, но дата договора или ДС не прочитана.')
        elif day <= cut:
            groups.setdefault(_edition(record), []).append(record)
    for _, current in sorted(groups.items()):
        entries = []
        for record in current:
            result['warnings'].extend(record['price'].get('warnings') or [])
            for value in record['price']['candidates']:
                label = (record.get('title') or 'Договор или ДС') + f" · стр. {value['page']}" \
                    + (f" · п. {value['clause']}" if value['clause'] else '')
                source = {'kind': 'contract_document', 'label': label, 'sha256': record['sha256'],
                          'page': value['page'], 'clause': value['clause'], 'quote': value['quote'],
                          'edition_date': _edition(record)[1], 'agreement': record.get('agreement'),
                          'vat_rate': value['vat_rate'], 'vat_text': value['vat_text']}
                entries.append({'amount': value['value'], 'amount_basis': value['amount_basis'], 'source': source})
        result['history'].extend(entries)
        values = {(r['amount'], r['amount_basis']) for r in entries}
        if len(values) == 1 and entries[0]['amount'] is not None:
            result.update(amount=entries[0]['amount'], amount_basis=entries[0]['amount_basis'],
                          source=entries[0]['source'], state='known')
        else:
            result.update(amount=None, amount_basis='conflicting', source=None, state='conflicting')
            result['warnings'].append('Действующая полная цена договора не определена: новая редакция '
                                      'содержит разные или непрочитанные суммы. Прежняя цена не подставлена.')
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    return result


def rebase_summary(observation, condition):
    """One monetary percentage: summary's qualified fact / explicit current full price.

    The printed summary observation is retained as evidence. Its snapshot date
    does not become an execution date, and amounts of individual acts are not added.
    """
    result = {**observation, 'reported_observation': dict(observation), 'price_source': condition['source'],
              'planned_amount_basis': condition['amount_basis']}
    known = condition['state'] == 'known' and condition['amount'] is not None and condition['amount'] > 0
    first, second = condition['amount_basis'], observation.get('completed_amount_basis') or 'unspecified'
    result['completed_amount_basis'] = second
    comparable = first == second and first in {'with_vat', 'without_vat'}
    if observation.get('state') != 'known' or not known or not comparable:
        return dict(result, ratio=None, planned=condition['amount'], state='unknown',
                    monetary_comparable=False, requires_reconciliation=True,
                    basis_signature=None, basis_label='суммы договора по КС-2 сводной',
                    why='Полная цена из договора и итог КС-2 сводной не подтверждены на сопоставимой базе НДС.')
    completed = observation['completed']
    signature = hashlib.sha256(json.dumps(['explicit_contract_price', condition['amount'], first, second],
                                          ensure_ascii=False).encode()).hexdigest()
    return dict(result, ratio=completed/condition['amount'], planned=condition['amount'],
                monetary_comparable=True,
                basis_signature=signature, basis_label='суммы договора по КС-2 сводной',
                requires_reconciliation=completed < 0 or completed > condition['amount'],
                why='Итог КС-2 взят из сводной, полная цена — из действующего договора или ДС. '
                    'Это денежное закрытие, не физическая готовность и не даты выполнения.')
