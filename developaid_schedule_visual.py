"""Readable schedule lanes. Presentation only; all dates and facts are supplied."""
from __future__ import annotations

import datetime as dt
import html
import math


def day(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def date_text(value):
    value = day(value)
    return value.strftime('%d.%m.%Y') if value else 'не указан'


def unit_text(value):
    """Typography only; keep the supplied unit and its scale in the model."""
    return str(value or '').replace('м2', 'м²').replace('м3', 'м³')


def styles():
    return '''<style>
.schedule-overview{font-family:Arial,sans-serif;color:#172b45;max-width:100%;overflow-wrap:anywhere}
.schedule-overview *{box-sizing:border-box}.schedule-overview h3{font-size:19px;margin:8px 0 12px}
.schedule-overview .schedule-note{font-size:12px;line-height:1.45;color:#526277;margin:9px 0}
.schedule-rnv-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}
.schedule-rnv-cards>div{background:#f0f4f9;border:1px solid #d6e0eb;border-radius:8px;padding:12px}
.schedule-rnv-cards span{display:block;font-size:12px;color:#526277}.schedule-rnv-cards strong{display:block;font-size:21px;margin-top:6px;line-height:1.25}
.schedule-rnv-cards .schedule-warning{background:#fff6e6}.schedule-overview details{margin:10px 0}.schedule-overview summary{cursor:pointer;font-size:13px;font-weight:600}
.schedule-chart{max-width:100%;margin:10px 0 16px}.schedule-chart-start{break-inside:avoid;page-break-inside:avoid}.schedule-axis{display:grid;grid-template-columns:minmax(140px,27%) minmax(0,1fr) minmax(150px,25%);gap:14px;margin:0 0 8px;break-after:avoid;page-break-after:avoid}
.schedule-axis-track{height:22px;position:relative}.schedule-tick{position:absolute;font-size:11px;white-space:nowrap;transform:translateX(-50%)}
.schedule-tick:first-child{transform:none}.schedule-tick:last-child{transform:translateX(-100%)}
.schedule-tick:only-child{transform:none}
.schedule-lane{display:grid;grid-template-columns:minmax(140px,27%) minmax(0,1fr) minmax(150px,25%);gap:14px;align-items:center;border-top:1px solid #dce3ed;padding:12px 0;break-inside:avoid;page-break-inside:avoid}
.schedule-label{font-size:14px;line-height:1.4;font-weight:600;min-width:0}.schedule-label small{display:block;font-size:12px;font-weight:400;color:#526277;margin-top:5px}
.schedule-lane-bars{height:44px;position:relative;min-width:0}.schedule-gridline{position:absolute;top:0;bottom:0;width:1px;background:#edf1f6}
.schedule-bar{position:absolute;min-height:3px;border-radius:4px;max-width:100%}.schedule-plan{top:5px;background:#aebbc9;border:1px solid #7b8fa4;height:11px}.schedule-forecast{top:24px;background:#205c96;height:11px}.schedule-delay{top:36px;background:#e0a13b;height:3px}.schedule-actual,.schedule-forecast-point{position:absolute;width:9px;height:9px;border-radius:50%;background:#25704c;top:25px;transform:translateX(-50%)}.schedule-forecast-point{background:#205c96}
.schedule-quantity{position:absolute;top:5px;height:11px;background:#25704c;border-radius:4px}.schedule-dates{font-size:12px;line-height:1.55;min-width:0}.schedule-dates span{display:block}.schedule-dates b{font-weight:600}.schedule-delay-note{color:#915d0e;font-weight:600}
.schedule-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin:10px 0}.schedule-legend i{display:inline-block;width:22px;height:9px;border-radius:3px;margin-right:5px;background:#aebbc9}.schedule-legend i.forecast{background:#205c96}.schedule-legend i.actual{background:#25704c}.schedule-legend i.delay{background:#e0a13b}
.schedule-corpus{border:1px solid #dce3ed;border-radius:8px;padding:10px 12px;margin:10px 0}.schedule-corpus>details{padding:0 0 5px}
.schedule-all-tasks{border-collapse:collapse;min-width:760px;font-size:12px}.schedule-all-tasks td,.schedule-all-tasks th{padding:8px;border:1px solid #dce3ed;text-align:left;vertical-align:top}
.schedule-physical-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.schedule-physical-item{border:1px solid #dce3ed;border-radius:8px;padding:10px;min-width:0;break-inside:avoid;page-break-inside:avoid}.schedule-physical-item h4{font-size:14px;margin:0 0 6px}.schedule-physical-item p{font-size:12px;line-height:1.45;margin:5px 0}.schedule-physical-item .schedule-physical-value{font-size:16px;font-weight:700}.schedule-physical-summary{margin:16px 0}
@media(max-width:640px){.schedule-rnv-cards{grid-template-columns:repeat(2,minmax(0,1fr))}.schedule-rnv-cards>div:last-child{grid-column:1/-1}.schedule-rnv-cards strong{font-size:20px}.schedule-axis{display:block}.schedule-axis>div:first-child,.schedule-axis>div:last-child{display:none}.schedule-lane{display:flex;flex-direction:column;align-items:stretch;gap:6px;padding:11px 0}.schedule-label{font-size:15px}.schedule-lane-bars{width:100%;height:40px}.schedule-dates{font-size:12px}.schedule-corpus{padding:10px}.schedule-overview h3{font-size:18px}}
@media print{.schedule-overview{font-size:10pt}.schedule-overview h3{font-size:14pt}.schedule-rnv-cards strong{font-size:15pt}.schedule-rnv-cards>div{padding:8px}.schedule-label{font-size:10pt}.schedule-dates,.schedule-overview .schedule-note,.schedule-legend{font-size:9pt}.schedule-lane{padding:9px 0}.schedule-technical,.schedule-reasons,.schedule-provenance,.schedule-article-details,.schedule-source-packages,.schedule-monitor-link{display:none!important}.schedule-rnv-cards,.schedule-lane{break-inside:avoid;page-break-inside:avoid}}
</style>'''


def lanes(rows, *, caption='', heading=''):
    """Render supplied dates without shrinking text into a scaled SVG."""
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    days = [value for row in rows for key in ('plan_start', 'plan_finish', 'forecast_start',
                                              'forecast_finish', 'actual_finish')
            if (value := day(row.get(key)))]
    if not rows:
        return ''
    first, last = (min(days), max(days)) if days else (dt.date(2000, 1, 1), dt.date(2000, 1, 1))
    span = max((last-first).days, 1)
    pos = lambda value: 2+max(0, min(96, 96*(day(value)-first).days/span))
    months, month = [], first.replace(day=1)
    while month <= last:
        months.append(month)
        month = dt.date(month.year+month.month//12, month.month%12+1, 1)
    step = max(1, (len(months)+6)//7)
    ticks = [(max(month, first), month.strftime('%m.%y')) for i, month in enumerate(months)
             if i % step == 0 or i == len(months)-1]
    out = ['<div class="schedule-chart">']
    # Keep only the heading, axis and first lane together. Later lanes remain
    # free to flow across pages, including in a large management report.
    if heading:
        out.append('<div class="schedule-chart-start"><h3>'+esc(heading)+'</h3>')
    if caption:
        out.append('<p class="schedule-note">'+esc(caption)+'</p>')
    if days:
        out.append('<div class="schedule-axis"><div>Работа / объект</div><div class="schedule-axis-track">')
        for tick, label in ticks:
            out.append(f'<span class="schedule-tick" style="left:{pos(tick):.3f}%">'+esc(label)+'</span>')
        out.append('</div><div>Сроки и причины сдвига</div></div>')
    for index, row in enumerate(rows):
        out.append('<article class="schedule-lane" data-task-id="'+esc(row.get('id'))+'"><div class="schedule-label">'+esc(row.get('name')))
        if row.get('subtitle'):
            out.append('<small>'+esc(row['subtitle'])+'</small>')
        out.append('</div><div class="schedule-lane-bars" aria-hidden="true">')
        for tick, _ in ticks if days else []:
            out.append(f'<i class="schedule-gridline" style="left:{pos(tick):.3f}%"></i>')
        start, finish = day(row.get('plan_start')), day(row.get('plan_finish'))
        forecast_start, forecast = day(row.get('forecast_start')) or start, day(row.get('forecast_finish'))
        if start and finish:
            a, b = pos(start), pos(finish)
            out.append(f'<span class="schedule-bar schedule-plan" style="left:{a:.3f}%;width:{max(.6,b-a):.3f}%"></span>')
            progress = row.get('physical_progress', row.get('source_progress'))
            if isinstance(progress, (int, float)) and not isinstance(progress, bool) and 0 <= progress <= 1:
                out.append(f'<span class="schedule-quantity" style="left:{a:.3f}%;width:{max(0,(b-a)*progress):.3f}%"></span>')
        if forecast_start and forecast and not row.get('actual_finish') and not row.get('forecast_partial'):
            a, b = pos(forecast_start), pos(forecast)
            out.append(f'<span class="schedule-bar schedule-forecast" style="left:{a:.3f}%;width:{max(.6,b-a):.3f}%"></span>')
        if forecast and row.get('forecast_partial'):
            out.append(f'<span class="schedule-forecast-point" style="left:{pos(row["forecast_finish"]):.3f}%"></span>')
        target = day(row.get('actual_finish')) or forecast
        if finish and target and target > finish and not row.get('forecast_partial'):
            a, b = pos(finish), pos(target)
            out.append(f'<span class="schedule-bar schedule-delay" style="left:{a:.3f}%;width:{max(.6,b-a):.3f}%"></span>')
        if day(row.get('actual_finish')):
            out.append(f'<span class="schedule-actual" style="left:{pos(row["actual_finish"]):.3f}%"></span>')
        out.append('</div><div class="schedule-dates"><span><b>План:</b> '+esc(date_text(row.get('plan_start')))+' — '+esc(date_text(row.get('plan_finish')))+'</span>')
        if row.get('actual_finish'):
            out.append('<span><b>Факт окончания:</b> '+esc(date_text(row['actual_finish']))+'</span>')
        elif forecast:
            label = row.get('forecast_label') or 'Прогноз'
            out.append('<span><b>'+esc(label)+':</b> '+esc(date_text(row['forecast_finish']))+'</span>')
        else:
            out.append('<span>Прогноз не подтверждён</span>')
        if isinstance(row.get('physical_progress'), (int, float)):
            out.append('<span>Подтверждённый объём работы: '+esc(f'{row["physical_progress"]*100:.1f}%')+'</span>')
        if isinstance(row.get('source_progress'), (int, float)):
            out.append('<span>Показание исходного ГПР: '+esc(f'{row["source_progress"]*100:.1f}%')+'</span>')
        own, inherited = row.get('own_delay_days'), row.get('inherited_delay_days')
        if own is not None or inherited is not None:
            out.append('<span class="schedule-delay-note">Своя задержка: '+esc('нет данных' if own is None else str(own)+' дн.')+' · от предыдущих этапов: '+esc('нет данных' if inherited is None else str(inherited)+' дн.')+'</span>')
        if row.get('forecast_partial'):
            out.append('<span>Дата только по части работ; это не завершение всего корпуса</span>')
        delta = row.get('delta_days')
        if isinstance(delta, (int, float)) and not isinstance(delta, bool):
            out.append('<span class="schedule-delay-note">Сдвиг работ с рассчитанным прогнозом: '+esc(f'{delta:+g} дн.')+'</span>')
        out.append('</div></article>')
        if heading and index == 0:
            out.append('</div>')
    out.append('</div>')
    return ''.join(out)


def legend(rows=()):
    fact = any(row.get('actual_finish') or row.get('physical_progress') is not None for row in rows)
    source = any(row.get('source_progress') is not None for row in rows)
    return ('<div class="schedule-legend"><span><i></i>План</span><span><i class="forecast"></i>Прогноз</span>'+
            ('<span><i class="actual"></i>Подтверждённый объём / окончание</span>' if fact else '')+
            ('<span><i class="actual"></i>Показание исходного ГПР</span>' if source else '')+
            '<span><i class="delay"></i>Сдвиг</span></div>')


def physical_summary(block, *, include_covered=True):
    """Print the supplied natural quantities and explicit facts, not PM rows.

    Components retain their own units and qualifications. There is no cross-work
    sum, average percentage, date inference or conversion from money here.
    Monitor PAGE owns covered-source cards and requests only bound facts here;
    standalone and report renderers keep the complete source presentation.
    """
    if not block:
        return ''
    esc = lambda value: html.escape(str(value if value is not None else ''), quote=True)
    def number(value):
        return (f'{value:g}'.replace('.', ',') if isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) else 'нет данных')
    out = ['<section class="schedule-physical-summary"><h3>Физическое выполнение по накопительным</h3>',
           '<div class="schedule-physical-grid">']
    displayed = False
    for task in block.get('tasks') or []:
        for component in task.get('components') or []:
            displayed = True
            done, plan = number(component.get('completed_quantity')), number(component.get('plan_quantity'))
            unit = esc(unit_text(component.get('unit')))
            out.append('<article class="schedule-physical-item"><h4>'+esc(task.get('name') or task.get('task_id'))+'</h4><p>'+esc(component.get('component_id'))+'</p><p class="schedule-physical-value">'+esc(done+' / '+plan)+' '+unit+'</p>')
            progress = component.get('progress')
            if isinstance(progress, (int, float)) and not isinstance(progress, bool) and math.isfinite(progress):
                out.append('<p>Доля полного объёма компонента: '+esc(f'{progress*100:g}%'.replace('.', ','))+'</p>')
            if component.get('period_end'):
                out.append('<p>Объём по '+esc(date_text(component['period_end']))+'</p>')
            pace = component.get('rate_per_day')
            if isinstance(pace, (int, float)) and not isinstance(pace, bool) and math.isfinite(pace):
                out.append('<p>Темп: '+esc(f'{pace:.3g}'.replace('.', ','))+' '+unit+'/день</p>')
            if task.get('known') and component.get('known') and component.get('forecast_finish'):
                out.append('<p>Расчётное окончание компонента: '+esc(date_text(component['forecast_finish']))+'</p>')
            if component.get('reason'):
                out.append('<p>'+esc(component['reason'])+'</p>')
            if task.get('reason'):
                out.append('<p>'+esc(task['reason'])+'</p>')
            out.append('</article>')
        if task.get('actual_finish'):
            displayed = True
            out.append('<article class="schedule-physical-item"><h4>'+esc(task.get('name') or task.get('task_id'))+'</h4><p>Подтверждённое окончание, факт: '+esc(date_text(task['actual_finish']))+'</p></article>')
    for group in (block.get('covered_source_groups') or []) if include_covered else []:
        measured, coverage = group.get('model') or {}, group.get('coverage') or {}
        displayed = True
        out.append('<article class="schedule-physical-item ks-covered-source"><h4>'+esc(group.get('source_name'))+'</h4>')
        ratio = measured.get('progress')
        out.append('<p class="schedule-physical-value">'+esc(f'{ratio*100:g}%'.replace('.', ',') if isinstance(ratio, (int, float)) else 'Общий процент не подтверждён')+'</p>')
        out.append('<p>'+esc(' · '.join(str(value) for value in (group.get('contractor'), group.get('contract'), group.get('period_year')) if value))+'</p>')
        if group.get('source_scope'):
            out.append('<p>'+esc(group['source_scope'])+'</p>')
        out.append('<p>'+esc(group.get('scope_reason'))+'</p><p>Известен объём '+esc(coverage.get('known_positions', 0))+' из '+esc(coverage.get('source_positions', 0))+' позиций раздела.</p>')
        if measured.get('progress_date'):
            out.append('<p>По ведомости от '+esc(date_text(measured['progress_date']))+'</p>')
        if measured.get('reason'):
            out.append('<p>'+esc(measured['reason'])+'</p>')
        components = measured.get('components') or []
        for component in components[:8] if ratio is None else []:
            value = component.get('progress')
            out.append('<p>'+esc(component.get('name') or component.get('component_id'))+': '+esc(f'{value*100:g}%'.replace('.', ',') if isinstance(value, (int, float)) else 'нет числа')+' · '+esc(number(component.get('completed_quantity'))+' / '+number(component.get('plan_quantity')))+' '+esc(unit_text(component.get('unit')))+'</p>')
        if ratio is None and len(components) > 8:
            out.append('<p>Других позиций: '+esc(len(components)-8)+'. Полный состав доступен в Мониторе.</p>')
        out.append('</article>')
    out.append('</div>')
    if not displayed and not include_covered and block.get('covered_source_groups'):
        # In Monitor PAGE owns these cards. Avoid both a second card grid
        # and an empty duplicate section; standalone/report output keeps it.
        return ''
    if not displayed:
        status = block.get('evidence_status') or {}
        out.append('<p class="schedule-note">'+esc(status.get('reason') or 'Подтверждённое выполнение по накопительным пока не определено.')+'</p>')
        if status.get('action'):
            out.append('<p class="schedule-note">'+esc(status['action'])+'</p>')
    out.append('<p class="schedule-note">Компоненты с разными единицами и объёмами показаны отдельно. Эти данные не являются средней готовностью всего корпуса.</p></section>')
    return ''.join(out)
