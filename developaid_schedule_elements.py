"""Owner-approved estimates, explicit element assignments and shared projection.

Names never assign works or building types. Each mapping is bound to the full
source by the readiness profile; missing internal shares never mean equal shares.
"""
from __future__ import annotations

import html
import math
import developaid_schedule_internal_weights as internal

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
    if not isinstance(config, dict) or set(config) != {'id', 'overrides', 'assignments', 'objects'} or config['id'] != PROFILE_ID:
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
    stages = sorted({row.get('section') or 'Без этапа' for row in entries})
    included = [row for row in entries if config['objects'].get(row.get('object') or 'Общие работы') != 'separate']
    included_objects = {row.get('object') or 'Общие работы' for row in included}
    corpus_shares, corpus_reason, corpus_basis = {}, '', ''
    if len(included_objects) > 1:
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
                    known_weight=known_weight, partial=bool(problems), oldest_date=min(dates) if dates else None)
    indexed = {}
    by_object = {}
    for row in entries:
        obj, stage = row.get('object') or 'Общие работы', row.get('section') or 'Без этапа'
        indexed.setdefault((obj, stage), []).append(row)
        by_object.setdefault(obj, []).append(row)
    # A malformed source must not turn a bounded work list into millions of cells.
    shown_objects, shown_stages = objects[:32], stages[:100]
    matrix = [dict(stage=stage, cells=[group(obj, indexed.get((obj, stage), [])) for obj in shown_objects]) for stage in shown_stages]
    return dict(project=group('Проект', entries, True, project=True), corpora=[group(obj, by_object[obj], True) for obj in objects],
                matrix=matrix, matrix_objects=shown_objects, matrix_truncated=len(objects)>32 or len(stages)>100,
                share_total=nominal, manual=bool(config['overrides']),
                project_weight_basis=corpus_basis,
                internal_weight_methods=internal.methods(config['assignments']))


def render_matrix(state):
    esc = lambda value: html.escape(str(value), quote=True)
    def cell(row):
        if not row['total']:
            return '<td class="readiness-cell-empty">—</td>'
        pct = 'Пока не определено' if row['progress'] is None else f"{row['progress']*100:.1f}%".replace('.', ',')+(' · по известным данным' if row['partial'] else '')
        coverage = 'неизвестно' if row['coverage'] is None else f"{row['coverage']:.1f}%".replace('.', ',')
        date = row['oldest_date'] or 'не указана'
        return '<td data-object="'+esc(row['name'])+'"><strong>'+esc(pct)+'</strong><div>Учтено '+str(row['known_readings'])+' из '+str(row['total'])+' работ; покрытие веса: '+esc(coverage)+'.</div><div>Самое старое учтённое показание: '+esc(date)+'.</div>'+('<details><summary>Что не учтено</summary>'+esc(row['reason'])+'</details>' if row['reason'] else '')+'</td>'
    limit = '<p>Матрица показывает первые 100 этапов и 32 корпуса из-за размера источника. Полный список работ остаётся в Ганте; общая готовность учитывает весь подтверждённый состав.</p>' if state.get('matrix_truncated') else ''
    return '<section id="gprMatrix"><h3>Готовность по этапам и корпусам</h3><p>Оценка по удельным весам видов работ'+(' с ручными долями' if state.get('manual') else '')+', не по объёмам этого проекта.</p>'+limit+'<div class="readiness-matrix"><table><thead><tr><th>Этап</th>'+''.join('<th>'+esc(obj)+'</th>' for obj in state['matrix_objects'])+'</tr></thead><tbody>'+''.join('<tr><th>'+esc(row['stage'])+'</th>'+''.join(cell(c) for c in row['cells'])+'</tr>' for row in state['matrix'])+'</tbody></table></div></section>'
