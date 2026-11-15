"""Pure presentation of the canonical, source-bound readiness projection."""
from __future__ import annotations

import math

from developaid_schedule_visual import date_text, day


def gpr_summary(state, cut):
    """Read supplied project scalars only; never infer weights, dates or scope."""
    if not isinstance(state, dict) or state.get('cut') != str(cut) or not isinstance(state.get('project'), dict):
        return None
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
    scope_text = f'Учтённый состав: {total} работ.'
    scope_text += (' Показания с весом: ' if estimated and progress is not None else ' Пригодные показания: ')+f'{known} из {total} работ.'
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
                reason=project.get('reason') or state.get('reason') or '',
                readiness_text=label+': '+value+'. '+scope_text+' '+as_of_text)
