"""Source-only corpus GPR snapshots. No automatic WBS, baseline or KS mapping.

The two-row header identifies each corpus independently. Row numbers are source
coordinates, not task identifiers; repeated design rows are never aggregated.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from typing import Any

import developaid_monitor_ledgers as ledgers

_READ_CACHE_ENTRIES = 8
_READ_CACHE_BYTES = 16 * 1024 * 1024


def _text(value: Any) -> str:
    return str(value if value is not None else '').strip()


def _date(value: Any) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(_text(value), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _raw(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def read(data: bytes) -> dict | None:
    """Share bounded source parsing within one coherent read, never decisions.

    Exact bytes own the cache key. Encoded results give each reader its own
    mutable copy; the approved-read context is discarded at the request end.
    """
    import developaid_monitor as monitor

    context = monitor._APPROVED_SCHEDULE_READ.get()
    if context is None:
        return _read_uncached(data)
    cache = context.setdefault(('corpus-source-parses',), {})
    key = hashlib.sha256(data).digest()
    if key in cache:
        return json.loads(cache[key])
    result = _read_uncached(data)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    if (len(cache) < _READ_CACHE_ENTRIES
            and sum(map(len, cache.values())) + len(encoded) <= _READ_CACHE_BYTES):
        cache[key] = encoded
    return result


def _read_uncached(data: bytes) -> dict | None:
    """Recognize only the selected ГПР sheet and bounded two-row corpus schema."""
    sheets = ledgers._read_workbook('gpr.xlsx', data, sheet_names={'гпр'})
    rows = next((rows for name, rows in sheets if name.strip().casefold() == 'гпр'), None)
    if rows is None:
        return None
    header, blocks, name_col = None, [], None
    for ri, row in enumerate(rows[:19]):
        names = [_text(v).casefold() for v in row]
        if names[:4] != ['№', 'наименование работ', 'стадия', 'статус'] or ri+1 >= len(rows):
            continue
        subs = rows[ri+1]
        for col, name in enumerate(names):
            if not re.fullmatch(r'корпус\s+[\w-]+|паркинг', name):
                continue
            if col+2 >= len(subs):
                continue
            fact, start, finish = [_text(v) for v in subs[col:col+3]]
            match = re.fullmatch(r'Факт\s+(\d{1,2}\.\d{1,2}\.\d{4})', fact, re.I)
            if not match or start.casefold() != 'старт' or finish.casefold() != 'финиш':
                continue
            blocks.append({'name': _text(row[col]), 'col': col,
                           'fact_day': _date(match[1]), 'fact_day_raw': match[1]})
        if len(blocks) >= 2:
            header, name_col = ri+1, names.index('наименование работ')
            break
        blocks = []
    if header is None:
        return None
    if len(blocks) > 16:
        raise ValueError('В корпусном ГПР слишком много объектов: допустимо не более 16.')
    packages, issues, excluded_rows = [], [], []
    for block in blocks:
        if not block['fact_day']:
            issues.append({'cell': ledgers._cell(block['col']+1, header+1),
                           'code': 'invalid_fact_day',
                           'message': 'Дата показания в шапке некорректна; дата среза не подставлена.'})
    group = ''
    headings = []
    for ri, row in enumerate(rows[header+1:], header+2):
        def cell(col):
            return row[col] if col < len(row) else None
        name = _text(cell(name_col))
        number_raw = _text(cell(0))
        if number_raw and not re.fullmatch(r'[1-9]\d*(?:\.0)?', number_raw):
            # A group is identified by its own non-numeric label in column A.
            # Residual text in the name column must not keep the previous group.
            group = number_raw
            headings.append({'name': group, 'source_row': ri, 'cell': ledgers._cell(1, ri)})
            excluded_rows.append(ri)
            continue
        if not name:
            continue
        if not re.fullmatch(r'[1-9]\d*(?:\.0)?', number_raw):
            excluded_rows.append(ri)
            continue
        scopes = []
        for block in blocks:
            col = block['col']
            refs = {key: ledgers._cell(col+offset+1, ri)
                    for offset, key in enumerate(('progress', 'start', 'finish'))}
            values = {key: cell(col+offset) for offset, key in enumerate(('progress', 'start', 'finish'))}
            parsed = {'start': _date(values['start']), 'finish': _date(values['finish'])}
            progress = None
            raw_progress = values['progress']
            if raw_progress is not None and _text(raw_progress):
                try:
                    number = float(str(raw_progress).replace(',', '.').replace('%', '').strip())
                    if '%' in str(raw_progress):
                        number /= 100
                    if math.isfinite(number) and 0 <= number <= 1:
                        progress = number
                except (ValueError, TypeError):
                    pass
                if progress is None:
                    issues.append({'cell': refs['progress'], 'code': 'invalid_progress',
                                   'message': 'Процент не распознан: ожидается доля от 0 до 1 или число со знаком %.'})
            for key in ('start', 'finish'):
                if _text(values[key]) and not parsed[key]:
                    issues.append({'cell': refs[key], 'code': 'invalid_date',
                                   'message': 'Дата «'+_text(values[key])[:64]+'» не распознана; срок не подставлен.'})
            if parsed['start'] and parsed['finish'] and parsed['finish'] < parsed['start']:
                issues.append({'cell': refs['finish'], 'code': 'reversed_dates',
                               'message': 'Окончание раньше начала.'})
            scopes.append({'corpus': block['name'], 'fact_day': block['fact_day'],
                           'fact_day_raw': block['fact_day_raw'], 'progress': progress,
                           'start': parsed['start'], 'finish': parsed['finish'],
                           'applicability': 'unconfirmed', 'mapping_status': 'unconfirmed',
                           'source_cells': refs, 'raw': {k: _raw(v) for k, v in values.items()}})
        packages.append({'source_row': ri, 'source_id': 'ГПР!'+ledgers._cell(name_col+1, ri),
                         'number_raw': number_raw, 'name': name, 'group': group,
                         'group_source': dict(headings[-1]) if headings else None,
                         'stage': _text(cell(2)), 'status': _text(cell(3)), 'scopes': scopes})
        if len(packages) > 1000:
            raise ValueError('В корпусном ГПР слишком много пакетов: допустимо не более 1000.')
    if not packages:
        return None
    result = {'format': 'corpus-gpr-v1', 'sheet': 'ГПР', 'sha256': hashlib.sha256(data).hexdigest(),
            'packages': packages, 'issues': issues[:100], 'issue_count': len(issues),
            'issues_not_shown': max(0, len(issues)-100),
            'excluded_non_task_rows': excluded_rows,
            'baseline_approved': False, 'quantity_mapping_confirmed': False,
            'reason': 'Показания исходного ГПР по корпусам. Связи с WBS и объёмами КС не подтверждены; '
                      'проценты не меняют утверждённый график и не дают темп или прогноз РНВ.'}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 8*1024*1024:
        raise ValueError('Результат разбора корпусного ГПР слишком большой.')
    return result



def as_schedule(source: dict) -> dict:
    """Adapt explicit package/object pairs only on the approved-baseline path.

    No RSS code, dependency, duration or WBS is fabricated. A zero without any
    plan date is not proof that a package applies to that object. Known readings
    with incomplete/invalid dates stay in the source and the physical catalog;
    calendar consumers independently require both dates.
    """
    works = []
    for package in source.get('packages') or []:
        for scope in package.get('scopes') or []:
            raw = scope.get('raw') or {}
            has_date = any(_text(raw.get(key)) for key in ('start', 'finish'))
            if not has_date and not (isinstance(scope.get('progress'), (int, float))
                                     and scope['progress'] > 0):
                continue
            refs = scope['source_cells']
            start = dt.date.fromisoformat(scope['start']) if scope.get('start') else None
            finish = dt.date.fromisoformat(scope['finish']) if scope.get('finish') else None
            problem = ''
            if start and finish and finish < start:
                problem = ('окончание '+finish.strftime('%d.%m.%Y')+' раньше начала '+start.strftime('%d.%m.%Y')+
                           ' (лист «'+source['sheet']+'», ячейки '+refs['start']+' и '+refs['finish']+')')
                start = finish = None
            elif not (start and finish):
                # The calendar needs both dates; the work names its own cell.
                problem = '; '.join(
                    label+(' «'+_text(raw.get(key))[:64]+'» не распознано' if _text(raw.get(key)) else ' не указано')+
                    ' (лист «'+source['sheet']+'», ячейка '+refs[key]+')'
                    for key, label, value in (('start', 'начало', start), ('finish', 'окончание', finish))
                    if value is None)
            group = package.get('group') or ''
            construction = bool(re.match(
                r'конструктив|фасад|отделка|внутренние инженерные|вис[. ]|наружные сети', group.casefold()))
            tid = 'corpus:' + source['sheet'] + '!' + refs['progress']
            works.append({'id': tid, 'wbs': '', 'name': package['name'],
                'object': scope['corpus'], 'section': group, 'kind': 'Работа', 'is_work': True,
                'progress': scope.get('progress'), 'progress_date': scope.get('fact_day'),
                'start': start, 'finish': finish,
                'status': package.get('status') or '', 'overdue': False,
                'duration': (finish-start).days+1 if start and finish else None,
                'predecessors': '', 'estimate_code': '', 'estimate_name': '',
                'basis': source['sheet']+'!'+refs['start']+'; '+source['sheet']+'!'+refs['finish'],
                'source_format': source['format'], 'source_sha256': source['sha256'],
                'source_id': package['source_id'], 'source_cells': dict(refs),
                'source_group': package.get('group_source'), 'construction_work': construction,
                'date_problem': problem})
    if not works:
        raise ValueError('В корпусном ГПР нет явно заполненных пар работы и объекта.')
    return {'rows': works, 'works': works, 'overdue': [], 'without_code': works,
            'source_format': source['format'], 'source_sha256': source['sha256'],
            'corpus_source': source}


def for_view(project: str, cut: str = '', *, baseline_sha256: str = '') -> dict | None:
    """Retain visible corpus evidence and identify the explicitly used baseline."""
    import developaid_monitor as monitor
    selected = monitor._working_baseline_state(project, cut)
    def approved_source():
        path = selected['path']
        if path is not None:
            try:
                taken_at = dt.date.fromisoformat(selected['taken_at']).isoformat()
            except (OSError, ValueError, KeyError, TypeError):
                taken_at = ''
            if taken_at and (not cut or taken_at <= cut or selected.get('baseline_scope') == 'remaining_work'):
                parsed = read(path.read_bytes())
                if parsed is not None:
                    if parsed['sha256'] != selected['source_sha256']:
                        raise ValueError('Отпечаток действующего ГПР не совпадает с утверждённым.')
                    return dict(parsed, taken_at=taken_at)
        return None
    # An archived source upload must not displace the explicitly selected plan.
    source = approved_source() if selected.get('path') is not None else None
    if selected.get('baseline_scope') == 'remaining_work':
        # Operational history shows today's plan and historical facts, never
        # an alternative archived plan when that plan is not a corpus file.
        return (dict(source, baseline_approved=True, working_source_state='approved',
                     reason='Этот файл используется как действующий утверждённый план. '
                            'Завершённые работы показаны отдельно по подтверждённым фактам.')
                if source is not None else None)
    if source is None:
        source = latest(project, cut)
    if source is None:
        source = approved_source()
    if source is None:
        return None
    same = bool(baseline_sha256 and source.get('sha256') == baseline_sha256)
    reason = ('Этот файл используется как утверждённый план. Показания ГПР и объёмы КС сохраняют свои основания; '
              'их связь проверяется отдельно.' if same else
              'Корпусный ГПР загружен, но рабочий план использует другую версию. '
              'Чтобы считать по этому файлу, примените его как утверждённый план; показания ниже уже доступны.'
              if baseline_sha256 else source.get('reason') or '')
    return dict(source, baseline_approved=same, reason=reason,
                working_source_state='approved' if same else 'different_baseline' if baseline_sha256 else 'source_only')


def store(project: str, data: bytes, taken_at: str, parsed: dict) -> dict:
    import developaid_monitor as monitor
    day = dt.date.fromisoformat(taken_at).isoformat()
    fact_days = {scope['fact_day'] for package in parsed['packages'] for scope in package['scopes']
                 if scope.get('fact_day')}
    if any(fact_day > day for fact_day in fact_days):
        raise ValueError('Дата версии раньше даты факта в шапке ГПР. Выберите дату не раньше последнего показания.')
    root = monitor._project_dir(project) / 'gpr_corpus'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = dict(parsed, taken_at=day)
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
    with ledgers._lock(root):
        path = monitor._inside(root, day+'.json')
        if path.exists():
            previous = json.loads(path.read_text())
            if previous.get('sha256') != result['sha256']:
                raise FileExistsError('Корпусный ГПР на эту дату уже сохранён; выберите другую дату версии.')
            return previous
        ledgers._atomic(path, payload)
    return result


def latest(project: str, cut: str = '') -> dict | None:
    import developaid_monitor as monitor
    path = monitor._latest(project, 'gpr_corpus', '.json', cut)
    if path is None:
        return None
    return json.loads(path.read_text())


def render(source: dict | None) -> str:
    """Read-only evidence table, shared with HTML/PDF. No overall percentage."""
    import html
    if not source:
        return ''
    esc = lambda value: html.escape(str(value if value is not None else '—'), quote=True)
    out = ['<section class="corpus-gpr-source"><h3>ГПР по корпусам · исходные показания</h3>',
           '<p>'+esc(source.get('reason'))+'</p>',
           '<p>Версия загружена: '+esc(source.get('taken_at'))+' · лист '+esc(source.get('sheet'))+'</p>']
    for issue in source.get('issues') or []:
        out.append('<p class="note">'+esc(issue['cell'])+': '+esc(issue['message'])+'</p>')
    if source.get('issues_not_shown'):
        out.append('<p class="note">Других замечаний: '+esc(source['issues_not_shown'])+'.</p>')
    out.append('<details><summary>Работы и даты из исходного файла</summary><div style="overflow-x:auto"><table style="min-width:760px"><thead><tr><th>Работа</th><th>Корпус</th><th>Факт на дату</th><th>Начало → окончание</th><th>Источник</th></tr></thead><tbody>')
    shown = 0
    total_scopes = sum(len(p.get('scopes') or []) for p in source.get('packages') or [])
    for package in source.get('packages') or []:
        for scope in package.get('scopes') or []:
            if shown >= 400:
                continue
            shown += 1
            value = scope.get('progress')
            progress = 'нет числа' if value is None else f'{value*100:g}%'
            refs = scope['source_cells']
            out.append('<tr><td>'+esc(package['name'][:500])+'</td><td>'+esc(scope['corpus'])+
                       '</td><td>'+esc(progress)+' · '+esc(scope.get('fact_day') or scope.get('fact_day_raw'))+
                       '</td><td>'+esc((_text(scope['raw'].get('start')) or '—')[:128])+' → '+esc((_text(scope['raw'].get('finish')) or '—')[:128])+
                       '</td><td>ГПР!'+esc(refs['progress'])+'; '+esc(refs['start'])+'; '+esc(refs['finish'])+'</td></tr>')
    out.append('</tbody></table></div></details>')
    if total_scopes > shown:
        out.append('<p class="note">Показаны первые 400 строк по корпусам из '+esc(total_scopes)+'. Все исходные показания сохранены в версии.</p>')
    out.append('<p class="note">Ноль без дат не означает, что работа применима к корпусу. Общие работы и готовность по разным основаниям не суммируются.</p></section>')
    return ''.join(out)


def render_overview(source: dict | None, cut: str = '') -> str:
    """Readable source-only fallback when no approved corpus mapping exists."""
    if not source:
        return ''
    import html
    from developaid_schedule_visual import day, date_text, lanes, legend, styles
    packages = source.get('packages') or []
    if not packages:
        return ''
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    out = [styles(), '<section class="schedule-overview corpus-gpr-overview"><h3>Исходные показания ГПР по корпусам</h3>',
           '<p class="schedule-note">'+esc(source.get('reason') or 'Связи ГПР с КС проверяются отдельно.')+'</p>',
           '<p class="schedule-note">Пакетов в исходном файле: '+str(len(packages))+'. '
           'Выберите работу, чтобы открыть показания по корпусам. Эти показания не заменяют полный план и факт проекта.</p>']
    for package in packages:
        rows = [{'id': str(package.get('source_id') or '')+':'+str(scope.get('corpus') or ''),
                 'name': scope.get('corpus') or 'Объект не указан',
                 'subtitle': ('Показание на '+date_text(scope.get('fact_day'))
                              if day(scope.get('fact_day')) else 'Дата показания не распознана'),
                 'plan_start': scope.get('start'), 'plan_finish': scope.get('finish'),
                 'source_progress': scope.get('progress')}
                for scope in package.get('scopes') or []]
        out.append('<details class="corpus-gpr-package" data-source-id="'+esc(package.get('source_id'))+'">'
                   '<summary>'+esc(package.get('name') or 'Пакет без названия')+'</summary>'+lanes(rows)+legend(rows)+'</details>')
    out.append('<details class="schedule-source-packages"><summary>Все пакеты исходного файла ('+str(len(packages))+')</summary>')
    out.append(render(source))
    out.append('</details></section>')
    return ''.join(out)
