"""Read-only, project-scoped inventory of saved GPR plans and fact parses.

No file contents or filesystem paths leave this diagnostic. A fact parse is
never promoted to a plan. Source hashes remain identities, not upload requests.
"""
from __future__ import annotations

import json
import hashlib


def inspect(project: str, cut: str = '') -> dict:
    import developaid_monitor as monitor
    import developaid_gpr_corpus as corpus
    import developaid_schedule_versions as versions

    selected = monitor._working_baseline_state(project, cut)
    root = monitor._project_dir(project)
    candidates = []
    errors = []
    raw_hashes = set()

    def source_summary(parsed):
        if not parsed:
            return {}
        schedule = corpus.as_schedule(parsed)
        works = schedule['works']
        return {'works': len(works), 'known_percentages': sum(w['progress'] is not None for w in works),
                'undated_works': sum(not w['start'] or not w['finish'] for w in works),
                'invalid_dates': sum(i.get('code') == 'invalid_date' for i in parsed.get('issues', [])),
                'issue_count': parsed.get('issue_count', 0)}

    paths = []
    legacy = monitor._legacy_baseline_file(project)
    if legacy:
        paths.append(('initial_plan', '', legacy, {}))
    for event in selected['versions']:
        paths.append(('approved_plan', event['effective_from'],
            root/'baseline'/'schedule_sources'/(event['source_sha256']+'.xlsx'), event))
    for path in sorted((root/'schedule_fact').glob('*.xlsx')):
        if monitor._day(path.stem):
            paths.append(('uploaded_fact', path.stem, path, {}))
    paths.sort(key=lambda entry: (entry[2] == selected['path'], entry[1]), reverse=True)
    omitted = 0
    remaining_bytes = 32*1024*1024
    for index, (kind, day, path, event) in enumerate(paths):
        try:
            size = path.stat().st_size
            if index >= 8 or size > remaining_bytes:
                omitted += 1
                continue
            remaining_bytes -= size
            data = versions._read(path)
            sha = versions.digest(data)
            if event and sha != event['source_sha256']:
                raise ValueError('Отпечаток сохранённой версии не совпадает с журналом.')
            raw_hashes.add(sha)
            candidates.append({'kind': kind, 'taken_at': day, 'source_sha256': sha,
                'revision': event.get('revision', 0), 'selected': sha == selected['source_sha256'],
                'raw_source_saved': True, 'summary': source_summary(corpus.read(data))})
        except (OSError, ValueError):
            if path == selected['path']:
                raise
            errors.append({'kind': kind, 'taken_at': day, 'reason': 'Сохранённый источник не прочитан или не прошёл проверку отпечатка.'})
    remaining_bytes = 16*1024*1024
    for index, path in enumerate(sorted((root/'gpr_corpus').glob('*.json'), reverse=True)):
        if not monitor._day(path.stem):
            continue
        try:
            size = path.stat().st_size
            if index >= 32 or size > remaining_bytes:
                omitted += 1
                continue
            remaining_bytes -= size
            raw_parse = path.read_bytes()
            parsed = json.loads(raw_parse)
            sha = parsed['sha256']
            if not versions._SHA.fullmatch(sha):
                raise ValueError
            candidates.append({'kind': 'corpus_fact_parse', 'taken_at': path.stem,
                'source_sha256': sha, 'selected': False, 'raw_source_saved': sha in raw_hashes,
                'parse_sha256': hashlib.sha256(raw_parse).hexdigest(),
                'summary': source_summary(parsed)})
        except (OSError, ValueError, KeyError, TypeError):
            errors.append({'kind': 'corpus_fact_parse', 'taken_at': path.stem,
                'reason': 'Сохранённое показание не прочитано.'})
    return {'selected_plan': {key: selected.get(key) for key in
                ('source_sha256', 'revision', 'effective_from', 'approved_at', 'baseline_scope')},
            'candidates': candidates, 'errors': errors, 'incomplete': bool(omitted), 'omitted_sources': omitted,
            'explanation': 'Плановые даты читаются из выбранного утверждённого файла. '
                'Загрузка процентов сохраняет отдельные показания и не заменяет план. '
                'Архивные версии не применяются автоматически. Если правильный файл уже сохранён, '
                'администратор может проверить его на сервере и утвердить штатным способом без повторной загрузки.'}


def render(state: dict) -> str:
    import html
    esc = lambda v: html.escape(str(v if v is not None else '—'), quote=True)
    labels = {'initial_plan': 'Первый план', 'approved_plan': 'Утверждённая версия',
              'uploaded_fact': 'Файл показаний', 'corpus_fact_parse': 'Сохранённые показания по корпусам'}
    plan = state['selected_plan']
    out = ['<section class="gpr-source-state"><h3>Какой источник используется</h3><p>'+esc(state['explanation'])+'</p>',
           '<p>Выбранный план: версия '+esc(plan['revision'])+' · '+esc(plan['source_sha256'])+'</p>',
           '<details><summary>Архив планов и отдельно загруженные показания</summary>']
    for c in state['candidates']:
        s = c['summary']
        out.append('<p>'+esc(labels[c['kind']])+' · '+esc(c['taken_at'])+' · '+esc(c['source_sha256'])+
                   (' · выбранный план' if c['selected'] else ' · справочно')+
                   (' · исходный файл сохранён' if c['raw_source_saved'] else ' · сохранён разбор; исходного файла в перечне нет')+
                   (' · работ: '+esc(s['works'])+', с процентом: '+esc(s['known_percentages'])+
                    ', с неполными датами: '+esc(s['undated_works']) if s else '')+'</p>')
    if state.get('incomplete'):
        out.append('<p class="contract-warning">История прочитана частично: источников вне лимита '+esc(state['omitted_sources'])+'. Отсутствие файла в этом перечне не доказывает его отсутствие в архиве.</p>')
    out.extend('<p class="contract-warning">'+esc(e['reason'])+'</p>' for e in state['errors'])
    return ''.join(out)+'</details></section>'
