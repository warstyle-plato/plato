"""Explicit work-completion terms of a contract and its dated agreements.

A later agreement changes only the conditions it states. Dates of payment,
guarantees and the validity of the contract are not work-completion deadlines.
Every selected date retains its clause, page, quotation and document identity.
"""
from __future__ import annotations

import datetime as dt
import re

_END = (r'(?:срок\s+)?(?:окончани[ея]|завершени[ея])\s+(?:всех\s+)?работ'
        r'(?:\s+по\s+(?:настоящему\s+)?договору)?')
_SEP = r'\s*(?:[–—:\-]\s*)?(?:(?:установлен\w*\s+)?(?:до|не\s+позднее)\s+)?'


def read(texts: list[str]) -> dict:
    """Read explicit clauses, not dates inferred from a neighbouring table."""
    # The PDF reader owns the supported spelling and validity of dates.
    from developaid_contract_documents import _WHEN, _date, _space

    candidates, warnings = [], []
    exact = re.compile(_END + _SEP + '(' + _WHEN + ')', re.I)
    for page, raw in enumerate(texts, 1):
        text = _space(raw)
        parsed_starts = set()
        for match in exact.finditer(text):
            parsed_starts.add(match.start())
            value = _date(match[1])
            before = text[max(0, match.start()-100):match.start()]
            clauses = list(re.finditer(r'(?<!\d)(\d+(?:\.\d+)+)\.?\s+', before))
            clause = clauses[-1][1] if clauses else ''
            quote = text[match.start():min(len(text), match.end()+300)]
            if not value:
                warnings.append(f'Стр. {page}: дата окончания работ «{match[1]}» не распознана.')
            candidates.append({'value': value, 'page': page, 'clause': clause, 'quote': quote,
                               'conditional': bool(re.search(r'при\s+условии', quote, re.I))})
        # A later relative condition cannot silently retain an earlier absolute
        # date. Its missing trigger is exposed instead of guessed from upload time.
        reference = re.compile(_END + r'\s*(?:[–—:\-]\s*)?(?:установлен\w*|определ\w*|согласно|'
                               r'в\s+соответствии|по)\b[^.;]{0,90}график\w*\s+производства\s+работ', re.I)
        references = [m for m in reference.finditer(text)
                      if not re.search(r'кажд\w*|корпус\w*|отдельн\w*|этап\w*', m[0], re.I)]
        for match in references:
            candidates.append({'value': None, 'page': page, 'clause': '',
                               'quote': text[match.start():min(len(text), match.end()+100)],
                               'conditional': False, 'schedule_reference': True})
        relative = re.compile(_END + r'\s*[–—:\-]\s*((?:через|в\s+течение|согласно|в\s+соответствии|по\s+графику)\b[^;]{0,250})', re.I)
        for match in relative.finditer(text):
            if match.start() not in parsed_starts and not any(r.start() == match.start() for r in references):
                quote = text[match.start():match.end()]
                candidates.append({'value': None, 'page': page, 'clause': '', 'quote': quote,
                                   'conditional': True})
                warnings.append(f'Стр. {page}: окончание работ задано условием; календарная дата '
                                'не рассчитана без указанного основания.')
    dates = {c['value'] for c in candidates if c['value']}
    if len(dates) > 1:
        warnings.append('В тексте документа указаны разные даты окончания работ; срок не выбран автоматически.')
    known = candidates[0] if len(dates) == 1 and all(c['value'] for c in candidates) else None
    return {'deadline': known, 'candidates': candidates, 'changes_deadline': bool(candidates),
            'warnings': warnings}


def _day(value):
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def _edition(record):
    agreement = record.get('agreement')
    identity = agreement or record.get('contract') or {}
    number = str(identity.get('number') or '')
    return (bool(agreement), identity.get('date') or '', int(number) if number.isdigit() else 0)


def _source(record, value):
    title = record.get('title') or ('Дополнительное соглашение' if record.get('agreement') else 'Договор')
    label = title + f" · стр. {value['page']}" + (f" · п. {value['clause']}" if value['clause'] else '')
    return {'kind': 'contract_document', 'label': label, 'sha256': record['sha256'],
            'page': value['page'], 'clause': value['clause'], 'quote': value['quote'],
            'conditional': value['conditional'], 'edition_date': _edition(record)[1],
            'agreement': record.get('agreement')}


def _referenced_schedule(records, cut):
    """Only an explicit term reference can use the dated annex's end as a deadline."""
    eligible = [r for r in records if not r.get('removed_at') and not r.get('act')
                and not (r.get('scan') and not r['scan'].get('confirmed_at'))
                and _day(_edition(r)[1]) and _edition(r)[1] <= cut
                and (r.get('schedule') or {}).get('lines')]
    if not eligible:
        return None
    latest = max(map(_edition, eligible))
    graphs = [r for r in eligible if _edition(r) == latest]
    # Two annexes of one edition are not resolved by upload order or filename.
    if len(graphs) != 1:
        return None
    graph = graphs[0]
    lines = graph['schedule']['lines']
    if any(not _day(r.get('start')) or not _day(r.get('finish')) or r['start'] > r['finish']
           or r.get('date_precision') == 'chart_marks' for r in lines):
        return None
    return {'value': max(r['finish'] for r in lines), 'sha256': graph['sha256'],
            'pages': graph['schedule'].get('pages') or []}


def resolve(records: list[dict], cut: str) -> dict:
    """Latest explicit term on the cut; unrelated agreements preserve the earlier term."""
    result = {'deadline': None, 'source': None, 'history': [], 'warnings': [], 'state': 'unknown'}
    for record in records:
        if (record.get('terms') or {}).get('changes_deadline') and not _day(_edition(record)[1]) \
                and not record.get('removed_at') and not record.get('act') \
                and not (record.get('scan') and not record['scan'].get('confirmed_at')):
            result['warnings'].append('В документе есть условие окончания работ, но дата договора или ДС '
                                      'не прочитана: его место в редакциях не определено.')
    eligible = [r for r in records if not r.get('removed_at') and not r.get('act')
                and not (r.get('scan') and not r['scan'].get('confirmed_at'))
                and _day(_edition(r)[1]) and _edition(r)[1] <= cut
                and (r.get('terms') or {}).get('changes_deadline')]
    eligible.sort(key=_edition)
    groups = {}
    for record in eligible:
        groups.setdefault(_edition(record), []).append(record)
    for _, current in sorted(groups.items()):
        entries = []
        for record in current:
            terms = record['terms']
            result['warnings'].extend(terms.get('warnings') or [])
            for value in terms.get('candidates') or []:
                source = _source(record, value)
                deadline = value['value']
                if value.get('schedule_reference'):
                    graph = _referenced_schedule(records, cut)
                    if graph:
                        deadline = graph['value']
                        source.update(basis='contract_schedule_reference', schedule_sha256=graph['sha256'],
                                      schedule_pages=graph['pages'])
                    else:
                        result['warnings'].append('Условие окончания работ ссылается на ГПР, но действующее '
                                                  'приложение с однозначными датами не прочитано.')
                entries.append({'deadline': deadline, 'source': source})
        result['history'].extend(entries)
        dates = {e['deadline'] for e in entries}
        if len(dates) == 1 and None not in dates:
            result.update(deadline=entries[0]['deadline'], source=entries[0]['source'], state='known')
        else:
            result.update(deadline=None, source=None, state='unknown' if dates == {None} else 'conflicting')
            result['warnings'].append('В действующей редакции документы дают разные или непрочитанные сроки '
                                      'окончания работ; прежний срок не использован вместо нового.')
    graph = _referenced_schedule(records, cut)
    if result['deadline'] and graph and graph['value'] != result['deadline']:
        result['schedule_comparison'] = {'deadline': result['deadline'], 'schedule_finish': graph['value'],
                                         'schedule_sha256': graph['sha256'], 'schedule_pages': graph['pages']}
        result['warnings'].append('Дата окончания в условии договора отличается от окончания загруженного ГПР. '
                                  'Оба источника сохранены; срок договора не заменён датой графика.')
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    return result
