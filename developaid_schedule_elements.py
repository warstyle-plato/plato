"""Owner-approved estimates, explicit element assignments and shared projection.

Names never assign works or building types. Each mapping is bound to the full
source by the readiness profile; missing internal shares never mean equal shares.
"""
from __future__ import annotations

import html
import math
import developaid_schedule_internal_weights as internal
import developaid_schedule_groups as display_groups

PROFILE_ID = 'residential-monolith-unfinished-v1'
TITLE = 'Монолитный жилой корпус без отделки квартир'
ACCEPTED_ON = '2026-11-12'
SOURCE_URL = 'https://smetnoedelo.ru/upload/iblock/780/RAZYASNENIE-SIS-O-raschete-stroitelnoy-gotovnosti.pdf'
SOURCE = 'Оценочные доли, принятые владельцем 12.11.2026. Метод: разъяснение СИС от 06.05.2019 № РС-ПГ-139/19.'
ELEMENTS = (
    ('underground', 'Нулевой цикл и подземная часть', 12),
    ('frame', 'Надземный монолит', 25),
    ('masonry', 'Кладка стен и перегородок', 5),
    ('facade', 'Фасады и окна', 17),
    ('roof', 'Кровля', 3),
    ('common_finish', 'Отделка МОП', 7),
    ('engineering', 'Внутренние инженерные системы с ПНР', 18),
    ('lifts', 'Лифты с испытаниями', 4),
    ('networks', 'Наружные сети', 5),
    ('landscape', 'Благоустройство', 4),
)


def catalog(overrides=None):
    overrides = overrides or {}
    return [dict(id=key, name=name, default=weight, value=overrides.get(key, weight),
                 origin='manual' if key in overrides else 'estimate') for key, name, weight in ELEMENTS]


def validate(config, full):
    if (not isinstance(config, dict) or not {'id', 'overrides', 'assignments', 'objects'} <= set(config)
            or set(config)-{'id', 'overrides', 'assignments', 'objects', 'corpus_shares'} or config['id'] != PROFILE_ID):
        raise ValueError('Выберите поддерживаемый оценочный профиль.')
    overrides, assignments, objects = (config[k] for k in ('overrides', 'assignments', 'objects'))
    ids = {key for key, _, _ in ELEMENTS}
    if not isinstance(overrides, dict) or set(overrides)-ids:
        raise ValueError('Неизвестный элемент в долях.')
    for value in overrides.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > 1e9:
            raise ValueError('Доля должна быть конечным неотрицательным числом; пустое поле не равно нулю.')
    if not isinstance(objects, dict) or set(objects)-{row.get('object') or 'Общие работы' for row in full.values()} or any(not isinstance(v, str) or v not in {'residential', 'separate'} for v in objects.values()):
        raise ValueError('Явно укажите тип каждого корпуса; паркингу нужен отдельный профиль.')
    if not isinstance(assignments, dict) or set(assignments)-set(full):
        raise ValueError('Сопоставление относится к неизвестной работе полного ГПР.')
    shares = config.get('corpus_shares', {})
    residential = {obj for obj, kind in objects.items() if kind == 'residential'}
    if (not isinstance(shares, dict) or shares and (set(shares) != residential
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in shares.values())
            or not math.isclose(math.fsum(shares.values()), 100, abs_tol=1e-6))):
        raise ValueError('Экспертные доли должны охватывать все жилые корпуса и давать 100%; пустые доли не означают равные.')
    for value in assignments.values():
        if (not isinstance(value, dict) or not {'element_id', 'share'} <= set(value)
                or set(value)-{'element_id', 'share', 'weight'} or not isinstance(value['element_id'], str) or value['element_id'] not in ids):
            raise ValueError('Выберите элемент для работы.')
        share = value['share']
        if share is not None and (isinstance(share, bool) or not isinstance(share, (int, float)) or not math.isfinite(share) or not 0 <= share <= 100):
            raise ValueError('Внутренняя доля должна быть числом от 0 до 100 или оставаться неизвестной.')
        if value.get('weight') is not None:
            internal.validate(value['weight'])
            if share is not None:
                raise ValueError('Экспертная доля и расчётный вес не используются одновременно.')


def weights(config, rows):
    """A full element can span stages, but never buildings or equal guesses."""
    groups = {}
    for key, row in rows.items():
        obj = row.get('object') or 'Общие работы'
        assignment = config['assignments'].get(key)
        if config['objects'].get(obj) == 'residential' and assignment:
            groups.setdefault((obj, assignment['element_id']), []).append((key, assignment))
    values = {r['id']: r['value'] for r in catalog(config['overrides'])}
    result, reasons = {}, {}
    overlaps = internal.overlapping(config['assignments'])
    for (obj, element), assignments in groups.items():
        if any(key in overlaps for key, _ in assignments):
            for key, _ in assignments:
                reasons[key] = 'Плановая позиция источника повторно распределена между работами или корпусами.'
            continue
        if any(assignment.get('weight') is not None for _, assignment in assignments):
            split, reason = internal.shares(assignments)
            if reason:
                for key, _ in assignments:
                    reasons[key] = reason
                continue
            members = list(split.items())
        else:
            members = [(key, assignment['share']) for key, assignment in assignments]
            if len(members) == 1 and members[0][1] is None:
                members = [(members[0][0], 100)]
        if any(share is None for _, share in members) or not math.isclose(math.fsum(share or 0 for _, share in members), 100, abs_tol=1e-6):
            for key, _ in members:
                reasons[key] = 'Не подтверждены внутренние доли элемента «'+dict((k, n) for k, n, _ in ELEMENTS)[element]+'» (нужно 100%).'
        else:
            for key, share in members:
                result[key] = values[element]*share/100
    return result, reasons


def projection(entries, config, *, cut, confirmed):
    config = config or dict(id=PROFILE_ID, overrides={}, assignments={}, objects={})
    rows = {row['id']: row for row in entries}
    weight_map, weight_reasons = weights(config, rows)
    shares = catalog(config['overrides'])
    nominal = math.fsum(row['value'] for row in shares)
    objects = sorted({row.get('object') or 'Общие работы' for row in entries})
    stage_of = lambda row: display_groups.section(row, config['assignments'].get(row['id']))
    stages = sorted({stage_of(row) for row in entries}, key=display_groups.order)
    included = [row for row in entries if config['objects'].get(row.get('object') or 'Общие работы') != 'separate']
    included_objects = {row.get('object') or 'Общие работы' for row in included}
    corpus_shares, corpus_reason, corpus_basis = {}, '', ''
    manual_corpora = config.get('corpus_shares') or {}
    if manual_corpora and set(manual_corpora) == included_objects:
        corpus_shares = {obj: value/100 for obj, value in manual_corpora.items()}
        corpus_basis = 'Экспертные доли корпусов: '+', '.join(obj+' — '+f'{value:g}%' for obj,value in manual_corpora.items())
    elif len(included_objects) > 1:
        # Nominal element percentages describe one building, not its size in
        # the project. Retain the full comparable plan before normalizing the
        # element shares; counting buildings would silently assign equal size.
        members = [(row['id'], config['assignments'].get(row['id'], {})) for row in included]
        plan_shares, problem = internal.shares(members)
        if internal.overlapping(dict(members)):
            problem = 'Плановая позиция источника повторно распределена между работами или корпусами.'
        if not problem:
            required = {element['id'] for element in shares if element['value'] > 0}
            for obj in sorted(included_objects):
                present = {config['assignments'][row['id']]['element_id'] for row in included
                           if (row.get('object') or 'Общие работы') == obj}
                if required-present:
                    problem = obj+': полный план не содержит всех учитываемых разделов; общий масштаб корпуса неизвестен.'
                    break
        if problem:
            corpus_reason = ('Не определён общий вес корпусов: нужен полный сопоставимый план каждой работы. '
                             + problem.replace('элемента', 'объявленного состава'))
        else:
            corpus_shares = {obj: math.fsum(plan_shares[row['id']]/100 for row in included
                            if (row.get('object') or 'Общие работы') == obj) for obj in included_objects}
            corpus_basis = internal.LABELS[members[0][1]['weight']['basis']]

    def group(name, members, whole=False, project=False):
        project_scaled = project and len(included_objects) > 1
        current_weights = ({key: value*corpus_shares[rows[key].get('object') or 'Общие работы']
                            for key, value in weight_map.items()} if project_scaled and not corpus_reason
                           else {} if project_scaled else weight_map)
        counts = dict(completed=0, in_progress=0, not_started=0, unknown=0)
        problems, dates, sources, weighted = [], set(), set(), []
        known_weight, known, numeric, mapped, eligible_readings = 0, 0, 0, 0, 0
        for row in members:
            key, fact = row['id'], row.get('primary') or {}
            obj = row.get('object') or 'Общие работы'
            if config['objects'].get(obj) == 'separate':
                problems.append(obj+': отдельный состав (в том числе паркинг); нужен отдельный профиль.')
                continue
            value, date = fact.get('value'), fact.get('date')
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
            numeric += valid
            # ISO dates here come from primary_fact; invalid dates are unknown.
            import datetime as dt
            try:
                day = dt.date.fromisoformat(date).isoformat()
            except (ValueError, TypeError):
                day = None
            eligible = valid and day is not None and day <= cut and not fact.get('requires_reconciliation')
            eligible_readings += eligible
            counts['unknown' if not eligible else 'completed' if value >= 1 else 'not_started' if value == 0 else 'in_progress'] += 1
            if config['objects'].get(obj) != 'residential':
                problems.append(obj+': не подтверждён тип здания.')
            elif key not in config['assignments']:
                problems.append((row.get('name') or key)+': работа не сопоставлена с элементом.')
            elif key in weight_reasons:
                problems.append(weight_reasons[key])
            if key in current_weights:
                mapped += 1
            if not eligible:
                problems.append((row.get('name') or key)+': нет пригодного датированного показания'+(' (требуется сверка).' if fact.get('requires_reconciliation') else '.'))
            elif key in current_weights:
                known += 1
                weight = current_weights[key]
                known_weight += weight
                weighted.append(weight*min(1, value))
                if weight == 0 and value < 1:
                    problems.append((row.get('name') or key)+': работа не завершена и имеет нулевой вес; это не подтверждает полную готовность.')
                if weight > 0:
                    dates.add(day)
                    sources.add(fact.get('label') or 'Источник работы')
        residential = {row.get('object') or 'Общие работы' for row in members if config['objects'].get(row.get('object') or 'Общие работы') != 'separate'}
        denominator = (nominal*math.fsum(corpus_shares.values()) if project_scaled else nominal*len(residential)) if whole else math.fsum(current_weights.get(row['id'], 0) for row in members)
        unknown_weight = any(row['id'] not in current_weights and config['objects'].get(row.get('object') or 'Общие работы') != 'separate' for row in members)
        if whole:
            for obj in sorted(residential):
                present = {config['assignments'][row['id']]['element_id'] for row in members if (row.get('object') or 'Общие работы') == obj and row['id'] in config['assignments']}
                for element in shares:
                    if element['value'] > 0 and element['id'] not in present:
                        problems.append(obj+': нет сопоставления элемента «'+element['name']+'».')
        if not confirmed:
            problems.insert(0, 'Полный состав и сопоставление с действующим ГПР ещё не подтверждены.')
        if project_scaled and corpus_reason:
            problems.insert(0, corpus_reason)
        if known_weight <= 0:
            problems.append('Нет положительного веса с пригодным показанием; процент пока не определён.')
        progress = math.fsum(weighted)/known_weight if confirmed and known_weight > 0 else None
        return dict(name=name, progress=progress, counts=counts, total=len(members), known_readings=known,
                    numeric_readings=numeric, eligible_readings=eligible_readings, known_weights=mapped, requires_reconciliation=sum(bool((row.get('primary') or {}).get('requires_reconciliation')) for row in members),
                    source_dates=sorted(dates), sources=sorted(sources), reason=' '.join(dict.fromkeys(problems)),
                    coverage=100*known_weight/denominator if denominator > 0 and (whole or not unknown_weight) and not (project_scaled and corpus_reason) else None,
                    known_weight=known_weight, partial=bool(problems) or bool(project and manual_corpora), oldest_date=min(dates) if dates else None,
                    work_ids=[row['id'] for row in members])
    indexed = {}
    by_object = {}
    for row in entries:
        obj, stage = row.get('object') or 'Общие работы', stage_of(row)
        indexed.setdefault((obj, stage), []).append(row)
        by_object.setdefault(obj, []).append(row)
    # A malformed source must not turn a bounded work list into millions of cells.
    shown_objects, shown_stages = objects[:32], stages[:100]
    matrix = [dict(stage=stage, cells=[group(obj, indexed.get((obj, stage), [])) for obj in shown_objects]) for stage in shown_stages]
    return dict(project=group('Проект', entries, True, project=True), corpora=[group(obj, by_object[obj], True) for obj in objects],
                matrix=matrix, matrix_objects=shown_objects, matrix_truncated=len(objects)>32 or len(stages)>100,
                share_total=nominal, manual=bool(config['overrides']),
                project_weight_basis=corpus_basis,
                project_weight_estimated=bool(manual_corpora),
                internal_weight_methods=internal.methods(config['assignments']))


def render_matrix(state):
    esc = lambda value: html.escape(str(value), quote=True)
    def forecast(row):
        value = row.get('forecast') or {}
        if not value.get('total'):
            return ''
        from developaid_schedule_visual import date_text
        text = 'Выполнено' if value.get('all_complete') else date_text(value['finish']) if value.get('finish') else 'Нет срока'
        title = value.get('note', '')+' Учтено '+str(value['covered'])+' из '+str(value['total'])+' работ.'
        return '<span class="readiness-cell-forecast" title="'+esc(title)+'">'+esc(text)+'</span><small class="readiness-forecast-coverage">'+str(value['covered'])+'/'+str(value['total'])+' работ</small>'
    def cell(row):
        if not row['total']:
            return '<td class="readiness-cell-empty">—</td>'
        pct = '—' if row['progress'] is None else f"{row['progress']*100:.1f}%".replace('.', ',')
        label = row['name']+': '+('пока не определено' if row['progress'] is None else pct+(' · по известным данным' if row.get('partial') else ''))
        bar = '' if row['progress'] is None else '<span class="readiness-meter" aria-hidden="true"><i style="width:'+str(max(0,min(100,row['progress']*100)))+'%"></i></span>'
        return '<td data-object="'+esc(row['name'])+'" aria-label="'+esc(label)+'"><strong>'+esc(pct)+'</strong>'+bar+forecast(row)+'</td>'
    def evidence(stage, row):
        if not row['total']:
            return ''
        coverage = 'неизвестно' if row['coverage'] is None else f"{row['coverage']:.1f}%".replace('.', ',')
        date = row['oldest_date'] or 'не указана'
        return '<article><h4>'+esc(stage)+' · '+esc(row['name'])+'</h4><p>Учтено '+str(row['known_readings'])+' из '+str(row['total'])+' работ; покрытие веса: '+esc(coverage)+'. Самое старое учтённое показание: '+esc(date)+'.</p>'+('<p>'+esc(row['reason'])+'</p>' if row['reason'] else '')+'</article>'
    limit = '<p>Матрица показывает первые 100 этапов и 32 корпуса из-за размера источника. Полный список работ остаётся в Ганте; общая готовность учитывает весь подтверждённый состав.</p>' if state.get('matrix_truncated') else ''
    corpora = {row['name']:row for row in state['corpora']}
    totals = '<tr class="readiness-total"><th scope="row">Итого по корпусу</th>'+''.join(cell(corpora[obj]) for obj in state['matrix_objects'])+'</tr>'
    project = state['project']
    if project.get('progress') is not None:
        totals = '<tr class="readiness-project-total"><th scope="row">Всего по жилым корпусам</th><td colspan="'+str(len(state['matrix_objects']))+'"><strong>'+esc(f"{project['progress']*100:.1f}%".replace('.', ','))+'</strong>'+forecast(project)+'</td></tr>'+totals
    rows = ''.join('<tr class="readiness-stage-row"><th scope="row">'+esc(row['stage'])+'</th>'+''.join(cell(c) for c in row['cells'])+'</tr>' for row in state['matrix'])
    details = ''.join(evidence(row['stage'], c) for row in state['matrix'] for c in row['cells'])
    return '<section id="gprMatrix"><h3>Готовность и сроки по корпусам</h3><p>Процент — по оценочным весам разделов; дата под ним — условное окончание при плановом темпе. Учтён известный состав, это не прогноз РНВ.</p>'+limit+'<div class="readiness-matrix" style="--readiness-columns:'+str(len(state['matrix_objects']))+'"><table><thead><tr><th scope="col">Этап</th>'+''.join('<th scope="col">'+esc(obj)+'</th>' for obj in state['matrix_objects'])+'</tr></thead><tbody>'+totals+rows+'</tbody></table></div><details class="readiness-matrix-evidence"><summary>Состав, даты и ограничения расчёта</summary>'+details+'</details></section>'
