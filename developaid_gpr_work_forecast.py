"""One source-bound work-date assessment, independent of RNV and money pace.

An active readiness profile owns its membership even when its weights are
incomplete. Only an absent/not-yet-effective profile permits the explicitly
typed construction roster fallback. Invalid owner membership never expands.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import re
from collections import defaultdict

SCHEMA = 1
BASIS = 'gpr_work_forecast'
_SHA = re.compile(r'[a-f0-9]{64}')


def _day(value):
    try:
        return dt.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _key(ids):
    return json.dumps(sorted(ids, key=lambda s: s.encode('utf-16-be')), ensure_ascii=False, separators=(',', ':'))


def _configured_profile(state):
    revision = state.get('profile_revision')
    return (state.get('profile_state') in {'active', 'invalid'}
            or type(revision) is int and revision > 0
            or (state.get('forecast_identity') or {}).get('id_scope') == 'full_source')


def applies_to(schedule):
    """Explicit corpus provenance or a configured profile owns this producer.

    A profile is an independent WORK contract, never evidence of a corpus
    format. Other legacy WBS retains its source-qualified date readers. Missing
    evidence in an opted-in catalog/profile must not select a legacy fallback.
    """
    state = schedule.get('readiness') or {}
    return (_configured_profile(state) or schedule.get('source_format') == 'corpus-gpr-v1'
            or any(row.get('source_format') == 'corpus-gpr-v1' for row in
                   [*(schedule.get('rows') or []), *(schedule.get('undated_works') or [])]))


def unavailable(schedule, cut, reason, code='unavailable'):
    source = (schedule.get('approved_plan') or {}).get('source_sha256')
    return dict(schema=SCHEMA, basis=BASIS, cut=str(cut), source_sha256=source,
                state='unavailable', reason=reason, reason_code=code,
                profile_state=(schedule.get('readiness') or {}).get('profile_state'),
                scope_kind='unavailable', ordered_members=[], covered_members=[], missing_members=[],
                outside_members=[], aggregates={}, project={}, corpora=[], matrix=[])


def _stats(points, intended, missing=0):
    covered = [p for p in points if p.get('complete') or p.get('finish')]
    dates = [p['finish'] for p in covered if _day(p.get('finish'))]
    plans = [p.get('plan_finish') for p in covered]
    starts = [p.get('plan_start') for p in covered]
    plan = max(plans) if plans and all(_day(p) for p in plans) else None
    finish = max(dates, default=None)
    return dict(finish=finish, comparison_plan_finish=plan,
                comparison_plan_start=min(starts) if starts and all(_day(p) for p in starts) else None,
                delta_days=(_day(finish)-_day(plan)).days if finish and plan else None,
                covered=len(covered), total=intended, missing=max(missing, intended-len(covered)),
                complete=bool(intended and len(covered) == intended and all(p.get('complete') for p in covered)),
                measured=sum(p.get('basis') == 'measured' for p in covered),
                conditional=sum(p.get('basis') == 'conditional' for p in covered),
                completed=sum(bool(p.get('complete')) for p in covered),
                comparison_members=[p['reference_work_id'] for p in covered])


def _profile_state(state):
    status = state.get('profile_state')
    if status in {'active', 'absent', 'future', 'invalid'}:
        return status
    # Compatibility with previously compiled snapshots, using typed identity
    # evidence only. No human reason is parsed and no failed profile is revived.
    if (state.get('forecast_identity') or {}).get('id_scope') == 'full_source':
        return 'active'
    if state.get('pending_profile') == 'future' and not state.get('profile_revision'):
        return 'future'
    if state.get('profile_revision') == state.get('latest_profile_revision') == 0:
        return 'absent'
    return 'invalid'


def _carry_consistent(schedule, state, carry):
    """Cross-check already-owned lineage evidence without opening a source."""
    if not isinstance(carry, dict):
        return False
    if not carry:
        if _profile_state(state) == 'active':
            reference = state.get('profile_reference_source_sha256')
            # A normal full/remaining crosswalk may have two source hashes.
            # Date-only projection rewrites the compiled full-source hash;
            # only that difference from the owner event requires a carry.
            compiled_reference = (state.get('forecast_identity') or {}).get('full_source_sha256')
            if reference is not None and reference != compiled_reference:
                return False
            parent_facts = (state.get('fact_source_carry') is not None
                            or schedule.get('fact_source_carry') is not None
                            or any(row.get('gpr_fact_source_carry') is not None for row in
                                   [*(schedule.get('rows') or []), *(schedule.get('undated_works') or [])]))
            if reference is None and parent_facts:
                return False
        return True
    source = schedule['approved_plan']
    if (carry.get('kind') != 'approved_date_only_projection'
            or carry.get('to_source_sha256') != source.get('source_sha256')
            or not isinstance(carry.get('from_source_sha256'), str) or not _SHA.fullmatch(carry['from_source_sha256'])
            or carry['from_source_sha256'] == carry['to_source_sha256']
            or carry.get('profile_decisions_unchanged') is not True or carry.get('persisted') is not False):
        return False
    if (type(state.get('profile_revision')) is not int or state['profile_revision'] <= 0
            or not isinstance(state.get('profile_sha256'), str) or not _SHA.fullmatch(state['profile_sha256'])
            or not _day(state.get('profile_effective_from')) or state['profile_effective_from'] > state['cut']
            or any(carry.get(key) != state.get(key) for key in
                   ['profile_revision', 'profile_sha256', 'profile_effective_from'])
            or type(source.get('revision')) is not int or source['revision'] <= 0
            or type(carry.get('source_revision')) is not int or carry['source_revision'] != source['revision']
            or type(carry.get('profile_revision')) is not int
            or carry.get('source_effective_from') != source.get('effective_from')
            or carry.get('source_approved_at') != source.get('approved_at')):
        return False
    common = ['from_source_sha256', 'to_source_sha256', 'source_revision', 'source_effective_from',
              'source_approved_at', 'parent_effective_from', 'parent_approved_at', 'changed_date_cells', 'persisted']
    fact = state.get('fact_source_carry')
    source_fact = schedule.get('fact_source_carry')
    if fact is not None or source_fact is not None:
        if (not isinstance(fact, dict) or not isinstance(source_fact, dict)
                or fact.get('kind') != 'unchanged_parent_gpr_facts' or fact != source_fact
                or any(fact.get(key) != carry.get(key) for key in common)):
            return False
    reference = state.get('profile_reference_source_sha256')
    if reference is None:
        # A retained old-producer snapshot needs independent fact lineage.
        # In its absence an update is required; another cut is never consulted.
        if not fact:
            return False
    elif reference != carry['from_source_sha256']:
        return False
    for row in [*(schedule.get('rows') or []), *(schedule.get('undated_works') or [])]:
        row_carry = row.get('gpr_fact_source_carry')
        if row_carry is not None and (not fact or not isinstance(row_carry, dict)
                or row_carry.get('kind') != fact['kind']
                or any(row_carry.get(key) != carry.get(key) for key in common)):
            return False
    return True


def build(schedule, cut):
    """Compile dates from the same current roster and existing native points."""
    cut = str(cut)
    source = (schedule.get('approved_plan') or {}).get('source_sha256')
    if not _day(cut) or schedule.get('cut') != cut or not isinstance(source, str) or not _SHA.fullmatch(source):
        return unavailable(schedule, cut, 'Источник или дата среза для общей оценки работ не подтверждены.', 'source_or_cut')
    rows = [*(schedule.get('rows') or []), *(schedule.get('undated_works') or [])]
    ids = [r.get('id') for r in rows]
    if (not rows or len(rows) > 3000 or any(not isinstance(k, str) or not k or len(k) > 512 for k in ids)
            or len(set(ids)) != len(ids)):
        return unavailable(schedule, cut, 'Исходный состав работ неполон или содержит неоднозначные идентификаторы.', 'roster')
    state = schedule.get('readiness') or {}
    if not isinstance(state, dict) or state.get('cut') != cut or state.get('source_sha256') != source:
        return unavailable(schedule, cut, 'Профиль, исходный ГПР и дата среза не совпадают. Общая дата требует сверки.', 'profile_binding')
    profile_state = _profile_state(state)
    if profile_state == 'invalid':
        return unavailable(schedule, cut, state.get('reason') or 'Состав профиля не подтверждён для текущего источника.', 'invalid_profile')
    if profile_state in {'absent', 'future'} and _configured_profile(state):
        return unavailable(schedule, cut, 'Состояние профиля противоречит подтверждённому составу работ.', 'profile_state_identity')
    from developaid_report_gantt import _readiness_calendar
    from developaid_schedule_plan_scenario import decorate_readiness
    if profile_state == 'active':
        if state.get('profile_effective_from') and state['profile_effective_from'] > cut:
            return unavailable(schedule, cut, 'Профиль ещё не действует на выбранную дату.', 'future_profile_mismatch')
        projection = _readiness_calendar(schedule, cut)
        if projection['readiness_forecast_invalid'] or not projection.get('display'):
            return unavailable(schedule, cut, 'Не подтверждена точная связь выбранного состава с текущим ГПР.', 'profile_membership')
        value = copy.deepcopy(state)
        scope_kind = 'readiness_profile'
    else:
        # Dates do not need readiness weights. All explicitly construction
        # rows, including missing observations/dates, retain their denominator.
        members = [r for r in rows if r.get('construction_work') is True]
        if not members:
            return unavailable(schedule, cut, 'В утверждённом источнике нет явно определённого строительного состава.', 'no_construction_scope')
        def group(name, works):
            readings = [r.get('display_progress') or {} for r in works]
            readings = [f for f in readings if type(f.get('value')) in {int, float}
                        and math.isfinite(f['value']) and 0 <= f['value'] <= 1
                        and _day(f.get('date')) and f['date'] <= cut and not f.get('requires_reconciliation')]
            return dict(name=name, work_ids=[r['id'] for r in works], total=len(works),
                        progress=None, known_readings=len(readings), source_dates=sorted({f['date'] for f in readings}), partial=True,
                        reason='Для этого среза нет действующего профиля весов. Готовность не рассчитана.')
        groups = defaultdict(list)
        for row in members:
            groups[row.get('object') or 'Общие работы'].append(row)
        value = dict(cut=cut, source_sha256=source, estimated=False, full_scope_confirmed=False,
                     scope_label='Известные строительные работы текущего ГПР',
                     project=group('Проект', members), corpora=[group(name, works) for name, works in groups.items()],
                     matrix=[], forecast_scope={},
                     forecast_identity=dict(id_scope='current_source', source_sha256=source,
                         full_source_sha256=None, remaining_ids={r['id']:r['id'] for r in members}))
        decorate_readiness(value, rows)
        projection = _readiness_calendar(dict(schedule, readiness=value), cut)
        if projection['readiness_forecast_invalid']:
            return unavailable(schedule, cut, 'Строительный состав не связан однозначно с исходными строками.', 'construction_membership')
        scope_kind = 'construction_partial'
    forecast = value['project']['forecast']
    points = copy.deepcopy(projection['points'])
    by_id = {r['id']:r for r in rows}
    from developaid_schedule_plan_scenario import linear_eligible
    if any(point.get('basis') == 'conditional' and not linear_eligible(by_id[key])
           for key, point in points.items()):
        return unavailable(schedule, cut, 'Процент из ГПР не позволяет рассчитать новую дату части этих работ. План и показания сохранены.', 'method_eligibility')
    if scope_kind == 'construction_partial' and any(
            point.get('finish') and (not _day(point.get('source_date')) or point['source_date'] > cut
                                    or by_id[key].get('requires_reconciliation'))
            for key, point in points.items()):
        return unavailable(schedule, cut, 'Часть оценок окончания не подтверждена датированным выполнением. План и показания сохранены.', 'observation_binding')
    mapping = value['forecast_identity']['remaining_ids']
    references = value['project']['work_ids']
    exclusions = {r['work_id']:r['kind'] for r in forecast.get('excluded') or []}
    ordered, missing = [], []
    for ref in references:
        current = mapping.get(ref)
        point = points.get(str(current)) if current is not None else None
        status = 'excluded' if ref in exclusions else 'covered' if point and (point['complete'] or point['finish']) else 'missing'
        reason = exclusions.get(ref) or next((r['kind'] for r in forecast.get('gaps') or [] if r.get('work_id') == ref), None)
        if status == 'missing':
            reason = reason or ((by_id.get(str(current)) or {}).get('plan_pace_scenario') or {}).get('reason') or 'Нет пригодной датированной оценки окончания.'
            missing.append(dict(reference_work_id=ref, work_id=current, reason=reason))
        ordered.append(dict(reference_work_id=ref, work_id=current, status=status, reason=reason))
    for key, point in points.items():
        point['plan_start'] = by_id[key].get('plan_start')
        point['object'] = by_id[key].get('object')
        point['delta_days'] = ((_day(point['finish'])-_day(point['plan_finish'])).days
                               if _day(point.get('finish')) and _day(point.get('plan_finish')) else None)
    intended = [r for r in ordered if r['status'] != 'excluded']
    intended_current = {str(r['work_id']) for r in intended if r['work_id'] is not None}
    excluded_current = {str(mapping[ref]):reason for ref, reason in exclusions.items() if mapping.get(ref) is not None}
    stats = _stats(list(points.values()), len(intended), len(missing))
    if forecast.get('finish') != stats['finish'] or forecast.get('covered') != stats['covered']:
        return unavailable(schedule, cut, 'Общая дата или покрытие не совпали с точками того же состава.', 'summary_mismatch')
    carry = state.get('profile_source_carry', {})
    if not _carry_consistent(schedule, state, carry):
        return unavailable(schedule, cut, 'Связь профиля с исправленной версией ГПР требует проверки.', 'profile_carry_binding')
    value.update(schema=SCHEMA, basis=BASIS, scope_kind=scope_kind, profile_state=profile_state,
                 state='complete' if stats['complete'] else 'unavailable' if not stats['covered'] else 'partial' if missing or scope_kind == 'construction_partial' else 'known',
                 source_order=ids, reference_source_sha256=carry.get('from_source_sha256') or value['forecast_identity'].get('full_source_sha256') or source,
                 ordered_members=ordered, covered_members=stats['comparison_members'], missing_members=missing,
                 outside_members=[dict(work_id=r['id'], reason=excluded_current.get(r['id']) or 'outside_assessment_scope')
                                  for r in rows if r['id'] not in intended_current],
                 reason=(state.get('reason') or '') if scope_kind == 'readiness_profile' else
                        'Частичная дата известных строительных работ. Это не срок всего проекта и не прогноз РНВ.')
    if missing:
        details = '; '.join(str((by_id.get(str(r['work_id'])) or {}).get('name') or 'Работа')+': '+str(r['reason'])
                            for r in missing[:3])
        value['reason'] = 'Дата не определена для '+str(len(missing))+' работ. '+details
    if not stats['covered']:
        value['reason_code'] = 'no_usable_work_dates'
    value['project']['forecast'].update(stats)
    aggregates = {}
    def aggregate(group):
        wanted = [key for key in group.get('work_ids') or [] if key not in exclusions]
        selected = [points[str(mapping[key])] for key in wanted if mapping.get(key) is not None and str(mapping[key]) in points]
        result = _stats(selected, len(wanted))
        result.update(plan_finish=result['comparison_plan_finish'], basis='conditional' if result['conditional'] else 'measured',
                      source_total=len(wanted), group=True,
                      work_ids=[str(mapping[key]) for key in wanted if mapping.get(key) is not None])
        key = _key(result['work_ids'])
        if key != '[]':
            aggregates.setdefault(key, result)
        return result
    aggregate(value['project'])
    for group in value['corpora']:
        group['forecast'].update(aggregate(group))
    for stage in value.get('matrix') or []:
        for group in stage.get('cells') or []:
            group['forecast'].update(aggregate(group))
    # Native hierarchy and presentation stages consume compiled aggregates;
    # their labels never decide project membership or create a new maximum.
    def cache_rows(members):
        current_ids = {r['id'] for r in members}
        keys = [ref for ref in references if ref not in exclusions and mapping.get(ref) in current_ids]
        if keys:
            aggregate(dict(work_ids=keys))
    presentation = defaultdict(list)
    by_group = (schedule.get('display_groups') or {}).get('by_id') or {}
    for row in rows:
        presentation[(row.get('object'), by_group.get(row['id']) or row.get('section'))].append(row)
        presentation[(row.get('object'), row.get('section'))].append(row)
    for members in presentation.values():
        cache_rows(list({r['id']:r for r in members}.values()))
    value['aggregates'] = aggregates
    from developaid_schedule_plan_scenario import group as date_group
    outside_points = {}
    for row in rows:
        if row['id'] in intended_current:
            continue
        measured = row.get('forecast_known') and not row.get('observed_complete_by')
        single = date_group([row])
        if not single['all_complete'] and not measured and not linear_eligible(row):
            continue
        if not single['finish'] and not single['all_complete']:
            continue
        finish, plan = single['finish'], row.get('plan_finish')
        outside_points[row['id']] = dict(work_id=row['id'], reference_work_id=None, outside=True,
            finish=finish, plan_finish=plan, complete=single['all_complete'],
            basis='complete' if single['all_complete'] else 'measured' if measured else 'conditional',
            source_date=(row.get('plan_pace_scenario') or {}).get('source_date'),
            delta_days=(_day(finish)-_day(plan)).days if _day(finish) and _day(plan) else None)
    value['outside_points'] = outside_points
    # Preserve the already-qualified points; extra plan metadata is not a
    # second forecast. Canonical dates and explanation membership stay native.
    value['project']['forecast']['display']['rows'] = list(points.values())
    value['summary'] = describe(value, cut)
    value['project']['forecast']['display']['paragraphs'][0] = value['summary']['forecast_text']+' '+value['summary']['scope_text']+' '+value['summary']['as_of_text']
    return value


def for_schedule(schedule, cut):
    """A supplied stale DTO is rejected, never repaired from another scope."""
    expected = build(schedule, cut)
    if 'work_forecast' not in schedule:
        return expected
    try:
        actual = json.dumps(schedule['work_forecast'], ensure_ascii=False, sort_keys=True, allow_nan=False)
        wanted = json.dumps(expected, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        actual, wanted = '', '!'
    if actual != wanted:
        return unavailable(schedule, cut, 'Сохранённая оценка относится к другому источнику, срезу или составу. Обновите срез.', 'dto_binding')
    return copy.deepcopy(schedule['work_forecast'])


def describe(value, cut):
    """Public text reads compiled dates; readiness weights remain independent."""
    from developaid_gpr_summary import gpr_summary
    from developaid_schedule_visual import date_text
    result = gpr_summary(dict(value, basis=None), cut) or {}
    result.pop('display', None)
    f = (value.get('project') or {}).get('forecast') or {}
    finish, plan, delta = f.get('finish'), f.get('comparison_plan_finish'), f.get('delta_days')
    label = ('Условная дата известных строительных работ' if value.get('scope_kind') == 'construction_partial'
             else 'Условная оценка окончания учтённых работ' if f.get('conditional') else 'Оценка окончания учтённых работ')
    scope = ('В составе оценки '+str(f.get('total'))+' работ; дата или завершение известны для '+str(f.get('covered'))+'. '
             + ('Для '+str(f.get('missing'))+' работ дата не определена. ' if f.get('missing') else '')
             +'Состав не подтверждает окончание всего проекта или получение РНВ.') if f else value.get('reason') or 'Состав для оценки даты не определён.'
    text = label+': '+date_text(finish)+'.' if finish else ('Работы отмечены выполненными; дата их окончания не подтверждена.' if f.get('complete') else 'Расчётная дата окончания работ не определена.')
    if f.get('conditional'):
        text += ' Условный сценарий при плановом темпе, а не измеренная скорость.'
    if value.get('state') == 'unavailable':
        text += ' '+str(value.get('reason') or '')
    result.update(finish=finish, plan_finish=plan, delta_days=delta,
                  forecast_label=label, forecast_text=text, scope_text=scope,
                  as_of_text='Срез '+date_text(cut)+'.',
                  plan_text='План того же учтённого состава: '+date_text(plan)+'.' if plan else 'Сопоставимый план по работам с оценкой не определён.',
                  delta_text=(f'{delta:+g} дн. к плану того же состава.' if delta is not None else 'Отклонение не рассчитано: нет сопоставимой пары дат.'),
                  reason=value.get('reason') or '', cut=str(cut), source_sha256=value.get('source_sha256'))
    return result


def report_model(block, cut):
    """Adapt the validated DTO to the existing compact report renderer."""
    projection = block.get('calendar') or {}
    roster = projection.get('rows') or []
    by_id = {str(item['task']['id']):item['task'] for item in roster
             if isinstance(item, dict) and isinstance(item.get('task'), dict) and item['task'].get('id') is not None}
    order = projection.get('source_order') or []
    schedule = dict(cut=str(cut), approved_plan=block.get('approved_plan'),
                    readiness=block.get('readiness'),
                    fact_source_carry=projection.get('fact_source_carry'),
                    rows=[by_id[key] for key in order if key in by_id], undated_works=[],
                    management=[dict(task, level='task') for task in by_id.values()],
                    display_groups=block.get('work_forecast_groups') or {},
                    work_forecast=block.get('work_forecast'))
    if len(order) != len(set(order)) or set(order) != set(by_id) or len(by_id) != len(roster):
        value = unavailable(schedule, cut, 'Исходный перечень календаря не подтверждён.', 'report_roster')
    else:
        value = for_schedule(schedule, cut)
    valid = value['state'] != 'unavailable'
    summary = value.get('summary') or describe(value, cut)
    groups, memberships = [], {}
    for corpus in value.get('corpora') or []:
        forecast = corpus['forecast']
        keys = set(forecast.get('work_ids') or [])
        objects = {by_id[key].get('object') for key in keys if key in by_id and by_id[key].get('object')}
        group = dict(name=corpus['name'], progress=corpus.get('progress'), objects=objects,
                     partial_progress=bool(corpus.get('partial')), selected=forecast['covered'], total=forecast['total'],
                     plan_start=forecast.get('comparison_plan_start'), plan_finish=forecast.get('comparison_plan_finish'),
                     finish=forecast.get('finish'), complete=forecast.get('complete'),
                     partial=bool(forecast.get('missing')), unknown=not forecast.get('finish') and not forecast.get('complete'))
        groups.append(group)
        for obj in objects:
            memberships.setdefault(obj, []).append(group)
    intended_current = {str(m['work_id']) for m in value.get('ordered_members') or []
                        if m.get('status') != 'excluded' and m.get('work_id') is not None}
    outside = {}
    for key, task in by_id.items():
        if key in intended_current:
            continue
        obj = task.get('object') or 'Объект не указан'
        matches = memberships.get(obj) or []
        group = matches[0] if len(matches) == 1 else outside.get(obj)
        if group is None:
            group = dict(name=obj, progress=None, objects={obj}, partial_progress=False,
                         selected=0, total=0, plan_start=None, plan_finish=None, finish=None,
                         complete=False, partial=False, unknown=True)
            groups.append(group);outside[obj] = group
        group['outside'] = group.get('outside', 0)+1
    matrix = []
    for stage in value.get('matrix') or []:
        matrix.append(dict(stage=stage.get('stage') or 'Этап не указан', values=[
            next((cell.get('progress') for cell in stage.get('cells') or [] if cell.get('name') == c['name']), None)
            for c in value.get('corpora') or []]))
    owner = projection.get('owner_rnv') or {}
    return dict(qualified=valid, assessment_qualified=valid, readiness_qualified=valid, work_forecast=True,
                finish=summary.get('finish') if valid else None,
                covered=(value.get('project') or {}).get('forecast', {}).get('covered') if valid else None,
                total=(value.get('project') or {}).get('forecast', {}).get('total') if valid else None,
                summary=summary, groups=groups, matrix=matrix, matrix_columns=len(value.get('corpora') or []),
                owner_plan=owner.get('date') if owner.get('source') == 'owner_decision' else None, cut=str(cut))
