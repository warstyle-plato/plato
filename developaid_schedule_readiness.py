"""Source-bound readiness: one declared full scope, explicit weights, no archive union."""
from __future__ import annotations

import hashlib
import html
import json
import math
import copy

import developaid_monitor as monitor
import developaid_schedule_versions as versions
import developaid_schedule_gpr_physical as physical
import developaid_cumulative_progress as quantities
import developaid_schedule_completed_facts as completed
import developaid_schedule_elements as elements

MAX_MEMBERS = 3000
BASIS = {'smr_cost': 'Полная стоимость СМР', 'estimated_elements': 'Оценочные доли строительных элементов'}
CONFIG_FIELDS = {'label', 'scope_kind', 'scope_note', 'basis', 'source_reference', 'building_type',
                 'full_source_sha256', 'effective_from', 'full_scope_confirmed', 'included_ids', 'excluded_ids',
                 'crosswalk', 'outside_completed_ids', 'owner_note', 'weights', 'element_profile'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _events(project):
    path = monitor._project_dir(project)/'readiness_profiles.json'
    if not path.exists():
        return []
    if path.stat().st_size > 16*1024*1024:
        raise ValueError('История профилей превышает допустимый размер.')
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('История профилей готовности не читается.')
    events = data.get('events')
    if data.get('schema') != 1 or not isinstance(events, list) or len(events) > 100:
        raise ValueError('История профилей готовности не читается.')
    for number, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise ValueError('Запись профиля готовности повреждена.')
        if (not isinstance(event.get('profile'), dict)
                or not {'basis', 'scope_kind', 'full_source_sha256', 'remaining_source_sha256',
                        'full_fingerprint', 'effective_from', 'included_ids', 'excluded_ids',
                        'crosswalk', 'outside_completed_ids', 'weights'} <= set(event['profile'])):
            raise ValueError('Запись профиля готовности повреждена.')
        if event.get('revision') != number or _digest(event['profile']) != event.get('profile_sha256'):
            raise ValueError('Отпечаток профиля готовности не совпадает с сохранённым.')
        if event['profile']['effective_from'] < event['recorded_at'][:10]:
            raise ValueError('Подтверждение состава не может предшествовать его записи.')
    return events


def _catalog(project, sha, *, full=False, effective_from=None):
    state = monitor._baseline_state(project)
    legacy = monitor._legacy_baseline_file(project)
    paths = []
    legacy_sha = state['versions'][0]['previous_source_sha256'] if state['versions'] else state['source_sha256']
    if legacy is not None and sha == legacy_sha:
        paths.append(legacy)
    for event in state['versions']:
        if event['source_sha256'] == sha and (not full or event.get('baseline_scope', 'full_schedule') == 'full_schedule'):
            if full and effective_from and event['effective_from'] > effective_from:
                raise ValueError('Полный источник ещё не действует на дату профиля.')
            paths.append(monitor._project_dir(project)/'baseline'/'schedule_sources'/(sha+'.xlsx'))
    if not paths:
        raise ValueError('Выберите сохранённый полный ГПР этого проекта; остаточный план не является полным составом.')
    data = versions._read(paths[0])
    if versions.digest(data) != sha:
        raise ValueError('Отпечаток сохранённого полного состава изменился.')
    rows = monitor._read_baseline_gpr_bytes(data)['works']
    if not rows or len(rows) > MAX_MEMBERS:
        raise ValueError('Полный состав пуст или превышает допустимый размер.')
    result = {}
    for row in rows:
        key = str(row.get('id') or row.get('wbs') or '')
        if not key or key in result:
            raise ValueError('Идентификатор полного состава повторяется; неоднозначные строки требуют проверки.')
        result[key] = row
    return result


def _fingerprint(rows):
    return _digest(sorted(physical.definition(row) for row in rows.values()))


def _ids(value, name):
    if not isinstance(value, list) or len(value) > MAX_MEMBERS or any(not isinstance(x, str) or not x for x in value):
        raise ValueError('Укажите идентификаторы: '+name+'.')
    if len(set(value)) != len(value):
        raise ValueError('Идентификатор повторяется: '+name+'.')
    return set(value)


def preview(project, configuration, *, expected_source_sha256, expected_source_revision, expected_revision):
    """Definitions come from saved sources, never caller names, paths or books."""
    if type(expected_source_revision) is not int or type(expected_revision) is not int or min(expected_source_revision, expected_revision) < 0:
        raise ValueError('Укажите целые неотрицательные ревизии.')
    allowed = CONFIG_FIELDS
    if not isinstance(configuration, dict) or set(configuration)-allowed:
        raise ValueError('Профиль принимает только идентификаторы, основания и веса, без строк исходника или путей.')
    cfg = dict(configuration)
    for name in ('label', 'scope_note', 'source_reference'):
        if not isinstance(cfg.get(name), str) or not cfg[name].strip() or len(cfg[name]) > 1000:
            raise ValueError('Укажите название, границы состава и источник весов.')
    if not isinstance(cfg.get('basis'), str) or not isinstance(cfg.get('scope_kind'), str) or cfg['basis'] not in BASIS or cfg['scope_kind'] not in {'construction', 'gpr_all'}:
        raise ValueError('Выберите сметные веса или оценочные доли и явно назовите состав.')
    if cfg['basis'] == 'estimated_elements' and (cfg['scope_kind'] != 'construction' or not isinstance(cfg.get('building_type'), str) or not cfg['building_type'].strip()):
        raise ValueError('Для оценочных долей нужны тип здания и отдельный строительный состав.')
    day = versions._day(cfg.get('effective_from'))
    if day < versions._now().date():
        raise ValueError('Подтверждение состава не может менять прошлые срезы.')
    current = monitor._working_baseline_state(project)
    if (current['source_sha256'] != expected_source_sha256 or current['revision'] != expected_source_revision
            or len(current['versions']) != expected_source_revision or len(_events(project)) != expected_revision):
        raise versions.ScheduleVersionConflict('Источник или профиль готовности изменён. Перечитайте состояние.')
    if not isinstance(cfg.get('full_source_sha256'), str) or not versions._SHA.fullmatch(cfg['full_source_sha256']):
        raise ValueError('Укажите отпечаток одного полного ГПР.')
    full = _catalog(project, cfg['full_source_sha256'], full=True, effective_from=cfg['effective_from'])
    remaining = _catalog(project, current['source_sha256'])
    element_profile = cfg.get('element_profile')
    if element_profile is not None:
        if cfg['basis'] != 'estimated_elements':
            raise ValueError('Оценочный профиль элементов не смешивается со сметными весами.')
        elements.validate(element_profile, full)
        # Origin and building type belong to the code catalog, never caller prose.
        cfg.update(label=elements.TITLE, building_type=elements.TITLE, source_reference=elements.SOURCE)
    included = _ids(cfg.get('included_ids', list(full) if cfg['scope_kind'] == 'gpr_all' else None), 'состав показателя')
    excluded = _ids(cfg.get('excluded_ids', []), 'исключения')
    if not included or included & excluded or included | excluded != set(full):
        raise ValueError('Состав показателя и явные исключения должны без пересечений покрывать выбранный полный источник.')
    if cfg['scope_kind'] == 'gpr_all' and excluded:
        raise ValueError('Показатель gpr_all должен включать весь полный ГПР без исключений.')
    if element_profile is not None and set(element_profile['assignments']) & excluded:
        raise ValueError('Исключённая работа не должна одновременно иметь долю элемента.')
    # Exact unique definitions are used immediately. Only exceptions need an override.
    by_definition = {}
    for key, row in full.items():
        by_definition.setdefault(physical.definition(row), []).append(key)
    links = {key: by_definition[physical.definition(row)][0] for key, row in remaining.items()
             if len(by_definition.get(physical.definition(row), [])) == 1}
    overrides = cfg.get('crosswalk') or []
    if not isinstance(overrides, list) or len(overrides) > MAX_MEMBERS:
        raise ValueError('Слишком много исключений сопоставления.')
    seen = set()
    for link in overrides:
        if not isinstance(link, dict) or set(link) != {'remaining_id', 'full_id'}:
            raise ValueError('Исключение сопоставления задаётся двумя идентификаторами.')
        rid, fid = link['remaining_id'], link['full_id']
        if not isinstance(rid, str) or not isinstance(fid, str) or rid not in remaining or fid not in full or rid in seen:
            raise ValueError('Неизвестное или повторное сопоставление работы.')
        if str(remaining[rid].get('object') or '').strip().casefold() != str(full[fid].get('object') or '').strip().casefold():
            raise ValueError('Нельзя переносить выполнение между разными корпусами.')
        links[rid] = fid
        seen.add(rid)
    if (set(links) != set(remaining) or len(set(links.values())) != len(links)) and not (element_profile is not None and cfg.get('full_scope_confirmed') is not True):
        raise ValueError('Не все работы остаточного ГПР однозначно сопоставлены с полным составом. Уточните только исключения.')
    outside = set(full)-set(links.values())
    declared = _ids(cfg.get('outside_completed_ids', []), 'подтверждённые работы вне остаточного перечня')
    outside_confirmed = declared == outside and (not outside or isinstance(cfg.get('owner_note'), str) and bool(cfg['owner_note'].strip()))
    if element_profile is not None:
        generated, _ = elements.weights(element_profile, {k: row for k, row in full.items() if k in included})
        cfg['weights'] = [{'full_id': key, 'value': value} for key, value in generated.items()]
    weights = cfg.get('weights') or []
    if not isinstance(weights, list) or len(weights) > MAX_MEMBERS:
        raise ValueError('Слишком много весов.')
    weight_ids, positions = set(), set()
    for weight in weights:
        if not isinstance(weight, dict) or set(weight)-{'full_id', 'value', 'planned_cost_split', 'basis', 'valuation_key', 'position_keys'}:
            raise ValueError('Вес содержит неизвестные поля.')
        key, value = weight.get('full_id'), weight.get('value')
        if not isinstance(key, str) or key not in included or key in weight_ids or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Вес должен быть конечным неотрицательным числом одной работы выбранного состава.')
        weight_ids.add(key)
        if cfg['basis'] == 'smr_cost':
            if weight.get('planned_cost_split') is not True or weight.get('basis') not in {'with_vat', 'without_vat', 'unspecified'}:
                raise ValueError('Для сметного веса нужны полная стоимость СМР и основание НДС.')
            valuation = weight.get('valuation_key')
            if not isinstance(valuation, list) or len(valuation) > 5 or any(not isinstance(v, (str, int)) or isinstance(v, bool) for v in valuation):
                raise ValueError('Укажите однозначное основание оценки стоимости.')
            keys = _ids(weight.get('position_keys'), 'позиции стоимости СМР')
            if not keys or positions & keys:
                raise ValueError('Позиции стоимости повторяются в нескольких работах; двойной вес не допускается.')
            positions.update(keys)
        elif set(weight)-{'full_id', 'value'}:
            raise ValueError('Оценочные доли и сметные основания не смешиваются.')
    cfg.update(included_ids=sorted(included), excluded_ids=sorted(excluded),
               crosswalk=[{'remaining_id': rid, 'full_id': fid,
                           'basis': 'explicit_override' if rid in seen else 'exact_definition'} for rid, fid in sorted(links.items())],
               outside_completed_ids=sorted(declared), weights=sorted(weights, key=lambda x: x['full_id']),
               remaining_source_sha256=current['source_sha256'], full_fingerprint=_fingerprint(full),
               remaining_fingerprint=_fingerprint(remaining))
    # Validate a complete supplied weight set now; partial profiles may save
    # their scope but cannot yield a number until every weight is available.
    if weight_ids == included and element_profile is None:
        _weight_check(cfg)
    sha = _digest(cfg)
    return {'profile': cfg, 'profile_sha256': sha, 'expected_revision': expected_revision,
            'review': {'full_works': len(full), 'remaining_works': len(remaining), 'included_works': len(included),
                       'excluded_works': len(excluded), 'outside_completed_works': len(declared), 'outside_candidate_ids': sorted(outside), 'outside_confirmed': outside_confirmed,
                       'automatic_links': len(links)-len(seen), 'explicit_links': len(seen),
                       'known_weights': len(weights), 'full_scope_confirmed': cfg.get('full_scope_confirmed') is True,
                       'objects': sorted({row.get('object') or 'Общие работы' for key, row in full.items() if key in included})},
            'applied': False}


def _weight_check(profile, weights=None, *, require_total=True):
    weights = profile['weights'] if weights is None else weights
    if (len({w.get('full_id') for w in weights}) != len(weights)
            or any(isinstance(w.get('value'), bool) or not isinstance(w.get('value'), (int, float))
                   or not math.isfinite(w['value']) or w['value'] < 0 for w in weights)):
        raise ValueError('Веса повторяются или содержат недопустимое значение.')
    if not weights or math.fsum(w['value'] for w in weights) <= 0:
        raise ValueError('Нет положительных весов полного состава.')
    if profile['basis'] != 'estimated_elements':
        metric = quantities.aggregate_quantities([{'member_key': w['full_id'], 'progress': 0,
            'unit': 'доля работы', 'planned_work_amount': w['value'], 'planned_cost_split': w['planned_cost_split'],
            'planned_work_amount_basis': w['basis'], 'valuation_key': w.get('valuation_key') or []} for w in weights])
        if metric['ratio'] is None:
            raise ValueError(metric['reason'])


def save(project, configuration, *, expected_source_sha256, expected_source_revision,
         expected_revision, expected_profile_sha256, author=''):
    folder = monitor._project_dir(project)
    with versions.lock(folder/'baseline'):
        # A fresh, uncached source read under the same cross-worker lock.
        fresh = versions.state(folder/'baseline', monitor._legacy_baseline_file(project), versions._now().date().isoformat())
        if fresh['source_sha256'] != expected_source_sha256 or fresh['revision'] != expected_source_revision or len(fresh['versions']) != expected_source_revision:
            raise versions.ScheduleVersionConflict('Утверждённый источник изменился.')
        result = preview(project, configuration, expected_source_sha256=expected_source_sha256,
            expected_source_revision=expected_source_revision, expected_revision=expected_revision)
        if result['profile_sha256'] != expected_profile_sha256:
            raise versions.ScheduleVersionConflict('Профиль изменился после проверки.')
        draft = result['profile'].get('element_profile') is not None and result['profile'].get('full_scope_confirmed') is not True
        if not draft and not result['review']['outside_confirmed']:
            raise ValueError('Решение100% должно явно покрывать работы вне остаточного перечня и иметь основание.')
        if len(_events(project)) >= 100:
            raise ValueError('Достигнут предел профилей готовности.')
        if not draft and result['profile'].get('full_scope_confirmed') is not True:
            raise ValueError('Подтвердите полный состав выбранного показателя, а не только наличие файла.')
        events = _events(project)
        if events and result['profile']['effective_from'] < events[-1]['profile']['effective_from']:
            raise ValueError('Нельзя обойти уже сохранённый будущий профиль.')
        event = {'revision': len(events)+1, 'recorded_at': versions._now().isoformat(), 'author': str(author)[:200],
                 'profile_sha256': result['profile_sha256'], 'profile': result['profile']}
        if event['profile']['effective_from'] < event['recorded_at'][:10]:
            raise ValueError('Дата изменилась во время проверки. Проверьте профиль заново.')
        encoded = json.dumps({'schema': 1, 'events': [*events, event]}, ensure_ascii=False).encode()
        if len(encoded) > 16*1024*1024:
            raise ValueError('Достигнут предел истории профилей.')
        versions._atomic(folder/'readiness_profiles.json', encoded)
    return {'revision': event['revision'], 'profile_sha256': event['profile_sha256'], 'applied': True}


def model(work_fact, *, cut, baseline_scope, source_sha256, profile=None, full_rows=None, blockers=()):
    """Pure projection; profile absence never expands a remaining list to a project."""
    works = work_fact.get('works') or {}
    entries = [dict(value, id=key, primary=value.get('primary') or {}) for key, value in works.items()]
    reason = 'Нет подтверждённого полного состава и весов. Показан текущий остаточный перечень.' if baseline_scope == 'remaining_work' else 'Нет подтверждённого профиля полного состава и весов.'
    active = bool(profile and profile.get('full_scope_confirmed') is True and profile.get('remaining_source_sha256') == source_sha256
                  and profile['effective_from'] <= cut and full_rows)
    if active:
        links = profile['crosswalk']
        matched = {link['full_id'] for link in links}
        outside = set(full_rows)-matched
        if (len(matched) != len(links) or {link['remaining_id'] for link in links} != set(works)
                or len({link['remaining_id'] for link in links}) != len(links)
                or matched-set(full_rows) or set(profile['outside_completed_ids']) != outside
                or set(profile['included_ids']) & set(profile['excluded_ids'])
                or set(profile['included_ids']) | set(profile['excluded_ids']) != set(full_rows)):
            active = False
            reason = 'Полный состав или сопоставление работ не подтверждены однозначно.'
    if active:
        full = full_rows
        reverse = {link['full_id']: link['remaining_id'] for link in profile['crosswalk']}
        entries = []
        for fid in profile['included_ids']:
            row = full[fid]
            if fid in reverse:
                fact = (works.get(reverse[fid]) or {}).get('primary') or {}
            else:
                fact = {'value': 1.0, 'basis': 'owner_outside_remaining', 'label': 'Решение владельца',
                        'source': 'Подтверждённые работы вне остаточного перечня', 'date': profile['effective_from'], 'actual_finish': None}
                identity = physical.definition(row)
                if any(tuple(b.get('definition') or ()) == identity and any(
                    completed._supersedes(tuple(reading), (profile['effective_from'], profile.get('recorded_at') or '')) for reading in b.get('observations') or []) for b in blockers):
                    fact = dict(fact, value=None, requires_reconciliation=True, reason='Есть более позднее противоречащее показание; требуется сверка.')
            entries.append(dict(row, id=fid, primary=fact))
    elif profile:
        reason = 'Профиль относится к другому источнику или ещё не действует на выбранную дату.'
    weight_map = {w['full_id']: w['value'] for w in (profile or {}).get('weights') or []} if active else {}

    def group(name, rows, *, project_group=False):
        counts = {'completed': 0, 'in_progress': 0, 'not_started': 0, 'unknown': 0}
        dates, sources, numeric, eligible_count, reconcile = set(), set(), 0, 0, 0
        weighted, row_values = [], []
        own_weights = [w for w in (profile or {}).get('weights') or [] if w['full_id'] in {row['id'] for row in rows}] if active else []
        weight_reason = ''
        complete_weights = active and {w['full_id'] for w in own_weights} == {row['id'] for row in rows} and len(own_weights) == len(rows)
        if complete_weights:
            try:
                _weight_check(profile, own_weights, require_total=project_group)
            except ValueError as exc:
                complete_weights, weight_reason = False, str(exc)
        for row in rows:
            fact = row.get('primary') or {}
            value = fact.get('value')
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1
            numeric += valid
            blocked = fact.get('requires_reconciliation') is True
            reconcile += blocked
            day = monitor._day(fact.get('date'))
            eligible = valid and day is not None and day.isoformat() <= cut and not blocked
            eligible_count += eligible
            counts['unknown' if not eligible else 'completed' if value == 1 else 'not_started' if value == 0 else 'in_progress'] += 1
            if eligible:
                dates.add(day.isoformat())
                if fact.get('label'):
                    sources.add(fact['label'])
                row_values.append(value)
                if row['id'] in weight_map:
                    weighted.append(value*weight_map[row['id']])
        total_weight = math.fsum(w['value'] for w in own_weights)
        value = math.fsum(weighted)/total_weight if complete_weights and total_weight > 0 and counts['unknown'] == 0 else None
        group_reason = ''
        if not active:
            group_reason = reason
        elif not complete_weights:
            group_reason = weight_reason or 'Не для всех работ этого состава подтверждены веса.'
        elif counts['unknown']:
            group_reason = ('Показания требуют сверки.' if reconcile else 'Не все работы имеют пригодное датированное показание на выбранную дату.')
        if value is not None and value >= 1-1e-9 and any(p < 1-1e-9 for p in row_values):
            value = None
            group_reason = 'Есть незавершённая работа с нулевым весом;100%веса не подтверждают завершение всех работ.'
        return {'name': name, 'progress': value, 'counts': counts, 'total': len(rows), 'known_readings': eligible_count,
                'numeric_readings': numeric, 'known_weights': len(own_weights), 'requires_reconciliation': reconcile,
                'source_dates': sorted(dates), 'sources': sorted(sources), 'reason': group_reason}
    corpora = {}
    for row in entries:
        corpora.setdefault(row.get('object') or 'Общие работы', []).append(row)
    project = group('Проект', entries, project_group=True)
    result = {'project': project, 'corpora': [group(name, rows) for name, rows in sorted(corpora.items())],
            'full_scope_confirmed': active, 'scope_label': ('Строительная готовность СМР' if profile['scope_kind'] == 'construction' else 'Готовность работ по ГПР') if active else 'Текущий остаточный перечень' if baseline_scope == 'remaining_work' else 'Текущий ГПР',
            'basis_label': BASIS[profile['basis']] if active else None, 'estimated': active and profile['basis'] == 'estimated_elements',
            'profile_label': profile.get('label') if active else None, 'source_reference': profile.get('source_reference') if active else None,
            'excluded_works': len(profile['excluded_ids']) if active else 0,
            'reason': project['reason'],
            'historical_completed_works': ((work_fact.get('completed_facts') or {}).get('counts') or {}).get('confirmed_works', 0),
            'source_sha256': source_sha256, 'cut': cut}
    element_config = (profile or {}).get('element_profile')
    projection = elements.projection(entries, element_config, cut=cut, confirmed=active)
    result.update({key: value for key, value in projection.items() if key not in {'project', 'corpora'}})
    if element_config is not None:
        result.update(project=projection['project'], corpora=projection['corpora'], reason=projection['project']['reason'],
                      source_reference=elements.SOURCE, estimated=True, profile_label=elements.TITLE,
                      basis_label=BASIS['estimated_elements'])
    return result


def build(project, cut, schedule):
    try:
        events = _events(project)
        history_error = None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        events, history_error = [], 'Профиль готовности не прочитан. Текущие показания работ сохранены.'
    event = next((event for event in reversed(events) if event['profile']['effective_from'] <= cut), None)
    profile, full = (dict(event['profile'], recorded_at=event['recorded_at']) if event else None), None
    error = None
    if profile:
        try:
            full = _catalog(project, profile['full_source_sha256'], full=True, effective_from=profile['effective_from'])
            if _fingerprint(full) != profile['full_fingerprint']:
                raise ValueError('Полный состав изменился после подтверждения.')
        except (OSError, ValueError) as exc:
            error, profile = str(exc), None
    selected = schedule.get('approved_plan') or {}
    result = model(schedule.get('work_fact') or {}, cut=cut, baseline_scope=schedule.get('baseline_scope', 'full_schedule'),
                   source_sha256=selected.get('source_sha256'), profile=profile, full_rows=full,
                   blockers=(schedule.get('completed_facts') or {}).get('completion_blockers') or [])
    if error or history_error:
        result['reason'] = error or history_error
    result['profile_revision'] = (event or {}).get('revision', 0)
    latest = events[-1] if events else {}
    result.update(latest_profile_revision=latest.get('revision', 0),
                  latest_profile_sha256=latest.get('profile_sha256', ''),
                  latest_profile_effective_from=(latest.get('profile') or {}).get('effective_from', ''),
                  pending_profile='future' if latest and latest['profile']['effective_from'] > cut else None)
    if latest and not event:
        result['reason'] = 'Сохранённый профиль ещё не действует на выбранную дату. Текущие показания показаны отдельно.'
    return result


def editor(project, *, full_source_sha256=''):
    """Load saved choices from disk; callers supply no work labels or paths."""
    events = _events(project)
    current = monitor._working_baseline_state(project)
    base = monitor._baseline_state(project)
    legacy_sha = base['versions'][0]['previous_source_sha256'] if base['versions'] else base['source_sha256']
    choices = []
    if legacy_sha and monitor._legacy_baseline_file(project) is not None:
        choices.append({'sha256': legacy_sha, 'label': 'Первый сохранённый ГПР — полноту нужно подтвердить'})
    today = versions._now().date().isoformat()
    for event in base['versions']:
        if event.get('baseline_scope', 'full_schedule') == 'full_schedule' and event['effective_from'] <= today and event['source_sha256'] not in {c['sha256'] for c in choices}:
            choices.append({'sha256': event['source_sha256'], 'label': 'Полный ГПР от '+event['effective_from']})
    latest = events[-1] if events else None
    sha = full_source_sha256 or ((latest or {}).get('profile') or {}).get('full_source_sha256') or (choices[-1]['sha256'] if choices else '')
    if not sha:
        return {'available': False, 'reason': 'Среди сохранённых источников нет подтверждённого полного ГПР. Остаточный перечень не заменяет полный состав.'}
    if not isinstance(sha, str) or not versions._SHA.fullmatch(sha):
        raise ValueError('Выберите отпечаток сохранённого полного ГПР.')
    full = _catalog(project, sha, full=True, effective_from=today)
    remaining = _catalog(project, current['source_sha256'])
    previous = next((e for e in reversed(events) if e['profile']['full_source_sha256'] == sha and e['profile'].get('element_profile')), None)
    if previous:
        cfg = copy.deepcopy({k: v for k, v in previous['profile'].items() if k in CONFIG_FIELDS})
        cfg['crosswalk'] = [{k: link[k] for k in ('remaining_id', 'full_id')} for link in cfg['crosswalk'] if link.get('basis') == 'explicit_override']
        if previous['profile']['remaining_source_sha256'] != current['source_sha256']:
            cfg.update(full_scope_confirmed=False, outside_completed_ids=[], owner_note='', crosswalk=[])
    else:
        cfg = dict(label=elements.TITLE, scope_kind='construction', scope_note='Явно подтверждённый строительный состав жилых корпусов; паркинг отдельно.',
                   basis='estimated_elements', source_reference=elements.SOURCE, building_type=elements.TITLE,
                   full_source_sha256=sha, full_scope_confirmed=False, included_ids=list(full), excluded_ids=[],
                   outside_completed_ids=[], owner_note='', crosswalk=[], weights=[],
                   element_profile=dict(id=elements.PROFILE_ID, overrides={}, assignments={}, objects={}))
    cfg['effective_from'] = max(today, cfg.get('effective_from') or today)
    by_definition = {}
    for key, row in full.items():
        by_definition.setdefault(physical.definition(row), []).append(key)
    automatic = {key: by_definition[physical.definition(row)][0] for key, row in remaining.items() if len(by_definition.get(physical.definition(row), [])) == 1}
    links = dict(automatic)
    links.update({link['remaining_id']: link['full_id'] for link in cfg['crosswalk']})
    outside = set(full)-set(links.values())
    shares = elements.catalog(cfg['element_profile']['overrides'])
    for share in shares:
        changes, previous_override = [], None
        for e in events:
            if e['profile']['full_source_sha256'] != sha:
                continue
            overrides = (e['profile'].get('element_profile') or {}).get('overrides', {})
            override = overrides.get(share['id'])
            if override is not None and override != previous_override:
                changes.append(e)
            previous_override = override
        if share['origin'] == 'manual' and changes:
            change = changes[-1]
            share.update(author=change['author'], recorded_at=change['recorded_at'])
    return dict(available=True, configuration=cfg, options=dict(expected_source_sha256=current['source_sha256'], expected_source_revision=current['revision'], expected_revision=len(events)),
                sources=choices, elements=shares, profile_id=elements.PROFILE_ID, title=elements.TITLE, source=elements.SOURCE, source_url=elements.SOURCE_URL, accepted_on=elements.ACCEPTED_ON,
                works=[dict(id=key, name=row.get('name') or key, object=row.get('object') or 'Общие работы', section=row.get('section') or 'Без этапа') for key, row in full.items()],
                unmatched=[dict(id=key, name=row.get('name') or key, object=row.get('object') or 'Общие работы') for key, row in remaining.items() if key not in automatic],
                outside=[dict(id=key, name=full[key].get('name') or key, object=full[key].get('object') or 'Общие работы') for key in sorted(outside)],
                history=[dict(revision=e['revision'], recorded_at=e['recorded_at'], author=e['author'],
                              overrides=(e['profile'].get('element_profile') or {}).get('overrides', {})) for e in events if e['profile']['full_source_sha256'] == sha])


def render(state):
    """Shared HTML; missing inputs stay compact so the Gantt remains primary."""
    if not state:
        return ''
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    from developaid_schedule_visual import date_text
    def facts(row):
        c = row['counts']
        return 'Завершено: '+str(c['completed'])+' · в работе: '+str(c['in_progress'])+' · не начато: '+str(c['not_started'])+' · неизвестно: '+str(c['unknown'])
    def evidence(row):
        eligible = row.get('eligible_readings', row['known_readings'])
        weighted = ' · включено во взвешенный расчёт: '+str(row['known_readings']) if 'eligible_readings' in row else ''
        return 'Пригодные показания: '+str(eligible)+' из '+str(row['total'])+weighted+' · веса полного состава: '+str(row['known_weights'])+' из '+str(row['total'])+'. Даты учтённых источников: '+(', '.join(date_text(day) for day in row['source_dates']) or 'нет учтённых показаний')+'. '+', '.join(row['sources'])
    def card(row):
        value = 'Не определена' if row['progress'] is None else f"{row['progress']*100:.1f}%".replace('.', ',')
        partial = '<p>По известным данным; состав учтён не полностью.</p>' if row.get('partial') and row['progress'] is not None else ''
        return '<article class="readiness-item"><h4>'+esc(row['name'])+'</h4><strong>'+esc(value)+'</strong>'+partial+'<details><summary>Состав и данные</summary><p>'+esc(facts(row))+'</p><p>'+esc(evidence(row))+'</p><p>'+esc(row['reason'])+'</p></details></article>'
    project = state['project']
    known = project['progress'] is not None or any(row['progress'] is not None for row in state['corpora'])
    heading = state['scope_label']+(' · оценочный профиль' if state['estimated'] else '')
    out = ['<style>.readiness-matrix{max-width:100%;overflow-x:auto}.readiness-matrix table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:12px}.readiness-matrix th,.readiness-matrix td{padding:7px;border:1px solid #dce3ed;overflow-wrap:anywhere;vertical-align:top}.readiness-summary{padding:12px 16px;border-bottom:1px solid #dce3ed;overflow-wrap:anywhere}.readiness-summary h3{font-size:15px;margin:0 0 7px}.readiness-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));gap:10px;margin-top:10px}.readiness-item{border:1px solid #dce3ed;border-radius:7px;padding:10px}.readiness-item h4{margin:0 0 7px}.readiness-item strong{font-size:20px}.readiness-project-value{display:block;font-size:30px;line-height:1.1;margin:8px 0}.readiness-item details{margin-top:7px}@media(max-width:640px){.readiness-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.readiness-item{padding:9px}.readiness-item h4{font-size:13px}.readiness-item summary{font-size:11px}}.readiness-item p,.readiness-summary p{font-size:12px;line-height:1.5;margin:5px 0}.readiness-summary summary{cursor:pointer;font-size:12px}</style>',
           '<section class="readiness-summary"><h3>'+esc(heading)+'</h3>']
    if project['progress'] is not None:
        out.append('<strong class="readiness-project-value">'+esc(f"{project['progress']*100:.1f}%".replace('.', ','))+'</strong>')
        if project.get('partial'):
            out.append('<p>По известным данным; это не готовность всего состава. '+esc(project['reason'])+'</p>')
    else:
        out.append('<p class="readiness-gap">Общая готовность пока не определена. '+esc(state['reason'])+'</p>')
    out.append('<p>'+esc(facts(project))+'</p><p>'+esc(evidence(project))+'</p>')
    if state.get('estimated'):
        out.append('<p>Оценка по удельным весам видов работ'+(' с ручными долями' if state.get('manual') else '')+', не по объёмам этого проекта.</p>')
    if known:
        out.append('<p>'+esc(state.get('profile_label'))+' · '+esc(state.get('basis_label'))+'</p><div class="readiness-grid">'+''.join(card(row) for row in state['corpora'])+'</div>')
    else:
        out.append('<details class="readiness-corpus-counts"><summary>Текущий состав по корпусам</summary>'+''.join('<p><b>'+esc(row['name'])+'</b>: '+esc(facts(row))+'. '+esc(evidence(row))+'</p>' for row in state['corpora'])+'</details>')
    if state['full_scope_confirmed']:
        out.append('<p>Вне состава показателя: '+str(state['excluded_works'])+' работ. '+esc(state.get('source_reference'))+'</p>')
    else:
        out.append('<details class="readiness-history-note"><summary>Завершённые работы из других источников</summary><p>Исторических подтверждений: '+str(state['historical_completed_works'])+'. Они не прибавлены к полному составу автоматически.</p></details>')
    if 'matrix' in state:
        out.append('<style>@media(max-width:640px){.readiness-matrix table,.readiness-matrix tbody,.readiness-matrix tr,.readiness-matrix tbody th,.readiness-matrix td{display:block;width:auto}.readiness-matrix thead{display:none}.readiness-matrix tbody tr{border:1px solid #dce3ed;border-radius:7px;margin:10px 0;overflow:hidden}.readiness-matrix tbody th{text-align:left;background:#f3f6fa}.readiness-matrix td{border-width:1px 0 0;overflow-wrap:break-word}.readiness-matrix td::before{content:attr(data-object);display:block;font-weight:700;margin-bottom:5px}.readiness-matrix .readiness-cell-empty{display:none}}</style>')
        out.append(elements.render_matrix(state))
    return ''.join(out)+'</section>'
