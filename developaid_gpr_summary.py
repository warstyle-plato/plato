"""Pure presentation of the canonical, source-bound readiness projection."""
from __future__ import annotations

import math
import html

from developaid_schedule_visual import date_text, day


def display_forecast(state, forecast, members, references):
    """Presentation of the very members already used by the project forecast.

    Dates are copied from the canonical per-work group calculation. This does
    not change the population, weights, facts, forecast or official milestone.
    """
    from developaid_schedule_plan_scenario import group
    points, names = [], {}
    for row in members:
        key = str(row.get('id') or '')
        reference = references.get(key)
        if not key or len(key) > 512 or not isinstance(reference, str) or not reference or len(reference) > 512:
            continue
        single = group([row])
        complete = single['all_complete']
        measured = bool(row.get('forecast_known') and not row.get('observed_complete_by'))
        scenario = row.get('plan_pace_scenario') or {}
        points.append(dict(work_id=key, reference_work_id=reference, finish=single['finish'],
                           plan_finish=single['plan_finish'], complete=complete,
                           basis='complete' if complete else 'measured' if measured and single['finish']
                           else 'conditional' if single['finish'] else 'unknown',
                           source_date=scenario.get('source_date')))
        names[key] = row
    truncated = len(points) > 2000
    points = points[:2000]
    result = dict(schema=1, basis='readiness_project_forecast', cut=state.get('cut'),
                  source_sha256=forecast['source_sha256'], full_source_sha256=forecast['full_source_sha256'],
                  id_scope=forecast['id_scope'], finish=forecast['finish'], total=forecast['total'],
                  covered=forecast['covered'], reference_total=forecast['reference_total'],
                  truncated=truncated, rows=points, paragraphs=[])
    evidence = forecast.get('explanation') or {}
    project = state.get('project') or {}
    summary = gpr_summary(state, state.get('cut'))
    if not summary or truncated:
        return result
    counts = evidence.get('counts') or {}
    estimate = (('Условная оценка' if counts.get('conditional') else 'Оценка')+' окончания учтённых работ — '+date_text(forecast['finish'])+'. '
                if forecast.get('finish') else 'Окончание учтённых работ пока не определено. ')
    paragraph = (estimate + summary['readiness_text']+' Срок опирается на '+str(forecast['covered'])
                 +' из '+str(forecast['total'])+' работ: '+str(counts.get('conditional', 0))
                 +' с условной датой, '+str(counts.get('measured', 0))+' с измеренным темпом, '
                 +str(counts.get('complete', 0))+' завершены по источникам. '
                 'Дата разрешения на ввод и критический путь этим расчётом не подтверждены.')
    chosen = [r for r in evidence.get('rows', []) if r.get('latest')][:2]
    for item in sorted(evidence.get('rows', []), key=lambda r: -(r.get('delta_days') or 0)):
        if len(chosen) == 3:
            break
        if item not in chosen:
            chosen.append(item)
    details = []
    for item in chosen:
        row = names.get(item.get('work_id'))
        if not row:
            continue
        # Bounded display labels; original names/IDs remain in the complete matrix.
        label = ' · '.join(str(row.get(k) or '') for k in ('object', 'name') if row.get(k))
        if len(label) > 240:
            label = label[:239]+'…'
        text = label+': '+date_text(item['finish'])
        if item.get('plan_finish'):
            text += ' вместо '+date_text(item['plan_finish'])
        if item.get('delta_days') is not None:
            text += ' ('+('+' if item['delta_days'] > 0 else '')+str(item['delta_days'])+' дн.)'
        fact = row.get('display_progress') or {}
        value = fact.get('value')
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            text += '; показание '+f'{value*100:.1f}%'.replace('.', ',')
            if day(fact.get('date')):
                text += ' от '+date_text(fact['date'])
        details.append(text)
    if details:
        second = 'Поздние даты и наибольшие сдвиги в этом составе: '+'; '.join(details)+'. '
    else:
        second = 'Конкретные работы, объясняющие позднюю дату, в этом срезе не подтверждены. '
    second += ('В первую очередь проверьте свежие показания этих работ и их последовательность. '
               'Пока новых датированных данных нет, условный сценарий использует последнее показание '
               'и плановый темп, а не подтверждённую скорость выполнения.')
    result['paragraphs'] = [paragraph, second]
    return result


def render_analysis(display):
    """One automatic explanation for Monitor, report and their print consumers."""
    if not isinstance(display, dict) or display.get('truncated') or len(display.get('paragraphs', [])) != 2:
        return ''
    return ('<section class="gpr-automatic-analysis"><h3>Платон: пояснение расчётного среза</h3>'
            '<small>Автоматически по данным ГПР; без обращения к языковой модели.</small>'
            +''.join('<p class="gpr-analysis-paragraph">'+html.escape(text)+'</p>'
                     for text in display['paragraphs'])+'</section>')


def gpr_summary(state, cut):
    """Read supplied project scalars only; never infer weights, dates or scope."""
    if not isinstance(state, dict) or state.get('cut') != str(cut) or not isinstance(state.get('project'), dict):
        return None
    if state.get('basis') == 'gpr_work_forecast' and isinstance(state.get('summary'), dict):
        return dict(state['summary'])
    project = state['project']
    number = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    progress = project.get('progress')
    progress = progress if number(progress) and 0 <= progress <= 1 else None
    coverage = project.get('coverage')
    coverage = coverage if number(coverage) and 0 <= coverage <= 100 else None
    dates = [value for value in project.get('source_dates', []) if day(value) and value <= str(cut)]
    fact_as_of = min(dates, default=None)
    forecast = project.get('forecast') or {}
    bound = (forecast.get('source_sha256') == state.get('source_sha256')
             and forecast.get('id_scope') in {'current_source', 'full_source'}
             and (forecast.get('id_scope') != 'full_source' or bool(forecast.get('full_source_sha256'))))
    forecast = forecast if bound else {}
    finish, plan = forecast.get('finish'), forecast.get('plan_finish')
    finish = finish if day(finish) else None
    plan = plan if day(plan) else None
    estimated, partial = bool(state.get('estimated')), bool(project.get('partial'))
    label = 'Оценочная готовность по ГПР' if estimated else 'Готовность по ГПР'
    value = f'{progress*100:.1f}%'.replace('.', ',') if progress is not None else 'Не определена'
    total, known = project.get('total'), project.get('known_readings')
    count_text = lambda value: str(value) if type(value) is int and value >= 0 else 'неизвестно'
    scope_text = 'Учтённый состав: '+count_text(total)+' работ.'
    scope_text += (' Показания с весом: ' if estimated and progress is not None else ' Пригодные показания: ')+count_text(known)+' из '+count_text(total)+' работ.'
    if coverage is not None:
        scope_text += ' Покрытие веса: '+f'{coverage:.1f}%'.replace('.', ',')+'.'
    if partial:
        scope_text += ' Оценка по известной части состава.'
    as_of_text = 'Показания от '+date_text(fact_as_of)+'.' if fact_as_of else 'Дата учтённых показаний неизвестна.'
    as_of_text += ' Срез '+date_text(cut)+'.'
    plan_text = ('План окончания учтённых работ: '+date_text(plan)+'. Даты известны для '
                 +str(forecast.get('plan_covered'))+' из '+str(forecast.get('total'))+' работ.') if plan else ''
    forecast_text = ('Оценка окончания: '+date_text(finish)+'. При плановом темпе. Сроки известны для '
                     +str(forecast.get('covered'))+' из '+str(forecast.get('total'))+' работ. Это не прогноз РНВ.') if finish else 'Оценка окончания учтённых работ пока не определена.'
    return dict(schema=1, source_sha256=state.get('source_sha256'), cut=str(cut),
                full_source_sha256=forecast.get('full_source_sha256'), id_scope=forecast.get('id_scope'),
                profile_revision=state.get('profile_revision'), profile_sha256=state.get('profile_sha256'),
                profile_effective_from=state.get('profile_effective_from'),
                progress=progress, coverage=coverage, total=total, known_readings=known,
                estimated=estimated, partial=partial, fact_as_of=fact_as_of,
                label=label, value=value, scope_text=scope_text, as_of_text=as_of_text,
                finish=finish, plan_finish=plan, forecast_text=forecast_text, plan_text=plan_text,
                display=forecast.get('display'),
                reason=project.get('reason') or state.get('reason') or '',
                readiness_text=label+': '+value+'. '+scope_text+' '+as_of_text)
