"""Source-current GPR, accepted RDS performance and applicable workforce workbook."""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import re
from urllib.parse import quote

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import developaid_contract_gpr as gpr
import developaid_contract_comparison_export as rds_export
import developaid_contract_workforce as workforce
import developaid_contract_gpr_reporting as reporting
from developaid_contract_rds import LAYOUT

SCHEMA = 'contract-gpr-performance-xlsx-v6'
PRESENTATION_SCHEMA = 'contract-gpr-known-state-v5'
COLORS = reporting.COLORS
LEGEND = reporting.LEGEND


def filename(project, contract, cut):
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', str(project)+'_'+str(contract)).strip(' ._')[:160]
    return (stem or 'contract')+'_ГПР_выполнение_'+cut+'.xlsx'


def disposition(meta):
    return 'attachment; filename="contract-gpr-performance-'+meta['cut']+'.xlsx"; filename*=UTF-8\'\''+quote(meta['filename'], safe='')


def bind_snapshot(project, cut, contract_id, result, label):
    state = result.get('gpr') or {}
    if not state.get('source') or not (state.get('schedule') or {}).get('lines'):
        return {'available': False, 'detail': 'Действующий ГПР не определён. Проверьте документы договора.'}
    context = {'schema': SCHEMA, 'project': project, 'cut': cut, 'contract_id': contract_id, 'label': label, 'filename': filename(project, label.get('contract') or 'contract', cut),
               'gpr_binding': {key: state[key] for key in ('project', 'contract_id', 'documents_raw_id',
                   'document_source_ids', 'guard', 'source') if key in state}}
    if result.get('source_correction'):
        context['source_correction'] = result['source_correction']
    return {**context, 'available': True, 'revision': gpr.digest({**context, 'gpr': state,
                                                               'rds': result.get('rds_comparison')})}


def select_snapshot(cached, project, cut, contract_id, revision):
    meta = cached.get('gpr_export') or {}
    if cached.get('pending') or cached.get('ok') is not True or not meta.get('available'):
        raise rds_export.ExportProblem(meta.get('detail') or 'Дождитесь загрузки карточки договора.')
    if (meta.get('project'), meta.get('cut'), meta.get('contract_id')) != (project, cut, contract_id):
        raise rds_export.ExportProblem('ГПР относится к другой карточке или срезу. Откройте договор заново.')
    expected = bind_snapshot(project, cut, contract_id, cached, meta.get('label') or {})
    if expected != meta or meta.get('revision') != revision:
        raise rds_export.ExportProblem('Версия ГПР изменилась. Откройте карточку заново перед выгрузкой.')
    rds_export.require_current_sources(meta)
    require_current_workforce(cached, project)
    return meta


def require_current_workforce(cached, project):
    if not workforce.require_current((cached.get('gpr') or {}).get('workforce') or {}, project):
        raise rds_export.ExportProblem('Данные численности изменились. Откройте карточку заново перед выгрузкой.')


def segments(line):
    """Keep disjoint source bars; a legacy envelope is explicitly identified."""
    found = line.get('segments') or []
    if found:
        return found
    if line.get('relative_segments'):
        return line['relative_segments']
    if line.get('start') and line.get('finish'):
        return [{'start': line['start'], 'finish': line['finish']}]
    return []


def timeline(schedule, cut, overlays=None, *, include_day='', headroom_days=0):
    view_days = [gpr.day(value) for value in (cut,include_day) if gpr.day(value)]
    if gpr.day(include_day) and headroom_days:
        view_days.extend((gpr.day(include_day)-dt.timedelta(days=1),
                          gpr.day(include_day)+dt.timedelta(days=headroom_days)))
    relative = schedule.get('calendar_basis') == 'relative'
    anchored = (schedule.get('anchor') or {}).get('handover_date') if relative else None
    if relative:
        maximum = max((column['finish_day'] for column in schedule.get('columns') or []), default=0)
        first = gpr.day(anchored)
        origin = first
        if origin:
            dates = [origin, origin+dt.timedelta(days=max(maximum-1, 0))]
            dates.extend(view_days)
            first, last = min(dates), max(dates)
            maximum = (last-first).days+1
        relative_first = (first-origin).days if first and origin else 0
        step = 1 if maximum <= 1096 else max(1, math.ceil(maximum/366))
        return [{'start': (first+dt.timedelta(days=i)).isoformat() if first else None,
                 'finish': (first+dt.timedelta(days=min(i+step, maximum)-1)).isoformat() if first else None,
                 'start_day': relative_first+i+1, 'finish_day': relative_first+min(i+step, maximum),
                 'label': (first+dt.timedelta(days=i)).strftime('%d.%m') if first else str(i+1)}
                for i in range(0, maximum, step)]
    dates = [gpr.day(line.get(key)) for line in schedule.get('lines') or [] for key in ('start', 'finish')]
    dates = [date for date in dates if date]
    if not dates:
        return []
    dates.extend(view_days)
    first, last = min(dates), max(dates)
    step = 1 if (last-first).days < 1096 else max(1, math.ceil(((last-first).days+1)/366))
    return [{'start': (first+dt.timedelta(days=i)).isoformat(),
             'finish': min(first+dt.timedelta(days=i+step-1), last).isoformat(),
             'label': (first+dt.timedelta(days=i)).strftime('%d.%m')}
            for i in range(0, (last-first).days+1, step)]


def occupied(line, tick):
    for part in segments(line):
        if tick.get('start') and part.get('start'):
            if part['start'] <= tick['finish'] and part['finish'] >= tick['start']:
                return True
        elif tick.get('start_day') and part.get('start_day'):
            if part['start_day'] <= tick['finish_day'] and part['finish_day'] >= tick['start_day']:
                return True
    return False


def cell_states(line, ticks, overlay, cut=''):
    """Calendar cells are source plan only; cumulative quantity has no dates."""
    indices = [i for i, tick in enumerate(ticks) if occupied(line, tick)]
    return {i: 'plan' if ticks[i].get('start') and ticks[i]['start'] > cut else 'unknown' for i in indices}


def physical_progress(line, overlay, cut, source_dates=()):
    """A quantity scale at one data cut, never an observed production interval."""
    value = line.get('quantity')
    value = value if isinstance(value, dict) else overlay or {}
    numeric = lambda v: type(v) in (int, float) and math.isfinite(v)
    quantity, total = value.get('fact_quantity'), value.get('contract_quantity')
    fraction = value.get('fraction', value.get('fact_fraction'))
    if (numeric(quantity) and numeric(total) and total > 0 and quantity > total
            and 'fraction' not in value and fraction == 1):
        # The legacy single-position DTO clipped its meter at100%. Keep the
        # actual quantity/ratio visible; only the separate meter is bounded.
        fraction = quantity/total
    if (not numeric(quantity) or quantity < 0 or not numeric(total) or total <= 0
            or not numeric(fraction) or fraction < 0 or not value.get('unit')
            or not math.isclose(fraction, quantity/total, abs_tol=1e-9)):
        return None
    planned = (overlay or {}).get('planned_fraction')
    planned = planned if numeric(planned) and 0 <= planned <= 1 else None
    lag = (overlay or {}).get('lag_days')
    return {'fact_quantity': quantity, 'contract_quantity': total, 'unit': value['unit'],
            'fraction': fraction, 'planned_fraction': planned,
            'delta_pp': (fraction-planned)*100 if planned is not None else None,
            'lag_days': lag if numeric(lag) else None, 'cut': cut,
            'source_dates': list(line.get('source_dates', source_dates)),
            'basis': 'cumulative_quantity_at_cut', 'production_history_available': False}


def progress_text(progress):
    if not progress:
        return 'Физический объём не подтверждён.'
    text = 'Физический объём на срез: '+format(progress['fraction']*100, '.1f')+'%'
    if progress['planned_fraction'] is not None:
        text += '; расчётный план на тот же срез: '+format(progress['planned_fraction']*100, '.1f')+'%'
        text += '; отклонение: '+format(progress['delta_pp'], '+.1f')+' п.п.'
        text += ' (равномерно по интервалам ГПР)'
    if progress['lag_days'] is not None:
        text += '; расчётное отставание: '+format(progress['lag_days'], '.15g')+' дн.'
    return text+'. Даты производства работ не подтверждены.'


def progress_cell_text(progress):
    """Compact visible metrics; full assumptions remain in the cell comment."""
    if not progress:
        return 'План / факт не сопоставлены.'
    fact = format(progress['fraction']*100,'.1f')+'%'
    if progress['planned_fraction'] is None:
        return 'Факт '+fact+'; расчётный план не подтверждён.'
    text = 'Расч. план '+format(progress['planned_fraction']*100,'.1f')+'% · факт '+fact
    delta = progress['delta_pp']
    text += '\n'+('Недобор ' if delta < 0 else 'Выше плана ' if delta > 0 else 'Отклонение ')+format(abs(delta),'.1f')+' п.п.'
    if progress['lag_days']:
        text += ' · расч. '+format(progress['lag_days'],'.15g')+' дн.'
    return text


def deadline_status(line, progress, cut):
    finish, date = gpr.day(line.get('finish')), gpr.day(cut)
    if not finish or not date:
        return None
    if progress and progress['fraction'] >= 1:
        return {'state':'quantity_complete_date_unknown',
                'text':'Объём достиг 100%; фактическая дата завершения не подтверждена.',
                'actual_finish': None}
    if finish >= date:
        return ({'state':'not_due','text':'Срок по ГПР на дату среза ещё не прошёл.'}
                if progress and progress['planned_fraction'] is not None else None)
    days = (date-finish).days
    if not progress:
        return {'state':'overdue_unknown', 'days_after_planned_finish':days,
                'text':'Срок прошёл; выполнение не подтверждено. После планового срока: '+str(days)+' дн.'}
    observed_dates = [gpr.day(value) for value in progress.get('source_dates') or []]
    observed_dates = [value for value in observed_dates if value and value <= date]
    if not observed_dates or max(observed_dates) <= finish:
        return {'state':'deadline_passed_unconfirmed','days_after_planned_finish':days,
                'text':'Срок прошёл; завершение не подтверждено свежим отчётом. Последний источник: '+
                       (max(observed_dates).isoformat() if observed_dates else 'дата не подтверждена')+'.'}
    if progress['planned_fraction'] is None:
        return {'state':'deadline_comparison_unconfirmed','days_after_planned_finish':days,
                'text':'Плановый срок прошёл; сопоставление известного объёма с этим сроком не подтверждено.'}
    remaining = max(progress['contract_quantity']-progress['fact_quantity'],0)
    fraction = max(1-progress['fraction'],0)
    return {'state':'overdue_incomplete','days_after_planned_finish':days,
            'remaining_quantity':remaining,'remaining_fraction':fraction,'unit':progress['unit'],
            'observed_at':max(observed_dates).isoformat(),
            'text':'На '+max(observed_dates).isoformat()+' работа не завершена: остаток '+
                   format(remaining,'.15g')+' '+progress['unit']+' ('+format(fraction*100,'.1f')+
                   '%). На дату среза срок ГПР прошёл '+str(days)+' дн. назад; '
                   'нового подтверждения выполнения после этой даты источника нет.'}


def ordered_positions(positions, cut=''):
    """Keep known nonzero work visible; never reorder the original RDS table."""
    def rank(line):
        progress = physical_progress(line,line.get('physical'),cut)
        status = deadline_status(line,progress,cut) or {}
        positive = bool(progress and progress['fact_quantity'] > 0)
        if status.get('state') == 'overdue_incomplete':
            return 0 if positive else 1
        if positive:
            return 2
        if status.get('state') == 'overdue_unknown':
            return 3
        return 4 if progress else 5
    sections = list(dict.fromkeys(line.get('section') or '' for line in positions))
    return sorted(positions,key=lambda line:(sections.index(line.get('section') or ''),rank(line)))


def statement_projection(comparison):
    if comparison.get('source') != 'ks6a':
        return None
    summary = comparison.get('statement_summary') or {}
    source = (summary.get('cash') or {}).get('source') or {}
    if not source:
        return None
    keys = ('total', 'work', 'material', 'known_total', 'known_work', 'known_material')
    def values(part):
        return {key: part.get(key) if type(part.get(key)) in (int, float) and math.isfinite(part[key]) else None
                for key in keys}
    return {'source_dates': summary.get('source_dates') or [], 'kind': comparison.get('source'),
            **values(source), 'cut': comparison.get('cut'),
            **{key: values((summary.get('cash') or {}).get(key) or {}) for key in ('current', 'after_cut', 'undated')}}


def statement_text(statement):
    """Describe source totals separately from the amount attributable to the cut."""
    def money(value):
        return (format(value/1e6, '.1f').replace('.', ',')+' млн ₽' if abs(value) >= 1e6
                else format(value, ',.2f').replace(',', ' ').replace('.', ',')+' ₽')
    def amount(part, key):
        if part.get(key) is not None:
            return money(part[key])
        known = part.get('known_'+key)
        return 'известная часть '+money(known)+'; полный итог не подтверждён' if known is not None else 'не подтверждено'
    lines = ['Всего в исходной КС-6а: '+amount(statement, 'total'),
             'Работы: '+amount(statement, 'work')+' · материалы: '+amount(statement, 'material')+'.']
    if any(statement[key].get('total') != 0 for key in ('after_cut', 'undated')):
        lines.append('В учёте на срез: '+amount(statement['current'], 'total')+
            '; позже среза: '+amount(statement['after_cut'], 'total')+
            '; без подтверждённой даты: '+amount(statement['undated'], 'total')+'.')
    return lines


def presentation(schedule, overlays, cut, positions=(), *, statement=None, source_dates=(), _ticks=None, _include_day='', _headroom_days=0):
    """Geometry shared by the native popup and the export's source commentary."""
    positions = ordered_positions(positions,cut)
    source_dates = source_dates or (statement or {}).get('source_dates') or []
    position_overlays = {line['code']: line['physical'] for line in positions if line.get('physical')}
    ticks = _ticks if _ticks is not None else timeline(schedule, cut, include_day=_include_day,headroom_days=_headroom_days)
    first = gpr.day(ticks[0].get('start')) if ticks else None
    last = gpr.day(ticks[-1].get('finish')) if ticks else None
    length = ((last-first).days+1) if first and last else max((tick.get('finish_day', 0) for tick in ticks), default=0)
    rows = []
    for line in schedule.get('lines') or []:
        parts = []
        for part in segments(line):
            if first and part.get('start'):
                begin, end = (gpr.day(part['start'])-first).days, (gpr.day(part['finish'])-first).days+1
            else:
                begin, end = part.get('start_offset', (part.get('start_day') or 1)-1), part.get('end_offset', part.get('finish_day') or 0)
            if schedule.get('calendar_basis') == 'relative' and 'start_offset' in part:
                begin, end = part['start_offset'], part['end_offset']
                anchor = gpr.day((schedule.get('anchor') or {}).get('handover_date'))
                if first and anchor:
                    begin, end = begin+(anchor-first).days, end+(anchor-first).days
            if end > begin:
                parts.append((begin, end))
        overlay = overlays.get(line['code'])
        progress = physical_progress(line,overlay,cut,source_dates)
        bars = []
        boundary = (gpr.day(cut)-first).days+1 if first and gpr.day(cut) else None
        for begin, end in parts:
            split = min(end, max(begin, boundary)) if boundary is not None else begin
            if split > begin:
                bars.append({'start': begin, 'end': split, 'state': 'unknown'})
            if end > split:
                bars.append({'start': split, 'end': end, 'state': 'plan'})
        rows.append({'code': line['code'], 'name': line['name'], 'start': line.get('start'),
                     'finish': line.get('finish'), 'relative_segments': line.get('relative_segments'),
                     'duration_printed': line.get('duration_printed'), 'relative_unit': line.get('relative_unit'),
                     'page': line.get('page'), 'bars': bars, 'physical': overlay,
                     'progress': progress, 'deadline_status': deadline_status(line,progress,cut),
                     'reporting': reporting.project(line,progress,parts,first.isoformat() if first else None,cut),
                     **{key: line[key] for key in ('number', 'section', 'position_key', 'gpr_code', 'quantity', 'note', 'physical_audit') if key in line}})
    projected = (presentation({**schedule, 'lines': positions}, position_overlays, cut, source_dates=source_dates, _ticks=ticks)['rows']
                 if positions else [])
    return {'schema': PRESENTATION_SCHEMA, 'ticks': ticks, 'length': length, 'start': first.isoformat() if first else None,
            'cut': cut, 'cut_offset': (gpr.day(cut)-first).days if first and gpr.day(cut) else None,
            'rows': rows, 'positions': projected, 'statement': statement,
            'legend': LEGEND, 'colors': COLORS}


def _edition_label(source):
    edition = source.get('edition') or {}
    if not isinstance(edition, dict):
        return 'редакция по исходному документу'
    label = 'ДС' if edition.get('kind') == 'agreement' else 'договор'
    if edition.get('number'):
        label += ' № '+str(edition['number'])
    if gpr.day(edition.get('date')):
        label += ' от '+gpr.day(edition['date']).strftime('%d.%m.%Y')
    return label


def fact_source_dates(comparison):
    summary = comparison.get('statement_summary') or {}
    dates = [gpr.day(value) for value in summary.get('source_dates') or []]
    if not any(dates):
        dates = [gpr.day(act.get('date')) for act in (comparison.get('act_evidence') or {}).get('acts') or []]
    return sorted({value.isoformat() for value in dates if value})


def company_workforce_rows(projection):
    """Supplemental source observations, never a contract allocation or total."""
    if projection.get('available'):
        return []
    found, single, by_date = [], False, {}
    for item in projection.get('rows') or []:
        if (not gpr.day(item.get('date')) or
                projection.get('cut') and item['date'] > projection['cut']):
            continue
        by_date.setdefault(item['date'],[]).extend(c for c in item.get('candidates') or [] if c.get('personnel_key'))
    for date, values in sorted(by_date.items()):
        # Only identical source records are duplicates. Different source keys
        # or conflicting values stay separate even when their counts match.
        candidates = list({workforce.digest(candidate):candidate for candidate in values}.values())
        if not candidates:
            continue
        row = {'date':date,'workers':None,'itr':None,'candidates':candidates,
               'reason':'Несколько строк подрядчика на дату; численность не суммируется.'}
        if len(candidates) == 1:
            candidate = candidates[0]
            reasons = []
            for key,label in (('workers','Рабочие'),('itr','ИТР')):
                value = candidate.get(key)
                if (candidate.get(key+'_present') is True and type(value) in (int,float)
                        and math.isfinite(value) and value >= 0 and not (candidate.get('ambiguities') or {}).get(key)):
                    row[key] = value
                    single = True
                else:
                    reasons.append(label+': категория не подтверждена.')
            row['reason'] = 'Одна запись подрядчика на дату. По договорам повторно не суммировать. План не сопоставлен.'+(' '+' '.join(reasons) if reasons else '')
        found.append(row)
    return found if single else []


def write_company_workforce(book,projection):
    rows = company_workforce_rows(projection)
    if not rows:
        return None
    sheet = book.create_sheet('Численность подрядчика')
    title = 'Численность подрядчика · '+str(projection.get('contractor') or '')
    scope = 'Записи о подрядчике из отчётов, без распределения по договорам. По нескольким договорам повторно не суммировать. План и отклонение не подтверждены; отсутствие не означает ноль.'
    for index,text in enumerate((title,scope),1):
        cell = sheet.cell(index,1,rds_export._text(text));cell.data_type='s'
        sheet.merge_cells(start_row=index,start_column=1,end_row=index,end_column=8)
        sheet.row_dimensions[index].height=42
    headers=('Дата','План рабочих','Рабочие подрядчика','Отклонение','План ИТР','ИТР подрядчика','Отклонение','Основание / пределы')
    for column,text in enumerate(headers,1):
        cell=sheet.cell(4,column,text);cell.fill=PatternFill('solid',fgColor='1F4E78')
        cell.font=Font(name='Calibri',size=10,bold=True,color='FFFFFF')
    for index,item in enumerate(rows,5):
        values=(gpr.day(item['date']),None,item['workers'],None,None,item['itr'],None,item['reason'])
        for column,value in enumerate(values,1):
            cell=sheet.cell(index,column,rds_export._text(value) if isinstance(value,str) else value)
            if isinstance(value,str):cell.data_type='s'
        sheet.cell(index,1).number_format='dd.mm.yyyy'
        sheet.cell(index,8).comment=Comment(json.dumps({'scope':'contractor_unallocated','contract_fact':False,
            'plan':None,'delta':None,'date':item['date'],'candidates':item['candidates']},ensure_ascii=False),'DevelopAid')
        sheet.row_dimensions[index].height=62
    for cells in sheet:
        for cell in cells:
            cell.alignment=Alignment(wrap_text=True,vertical='top')
            if cell.row != 4:cell.font=Font(name='Calibri',size=10)
    for column,width in zip('ABCDEFGH',(14,15,18,15,13,17,15,66)):
        sheet.column_dimensions[column].width=width
    sheet.auto_filter.ref='A4:H'+str(sheet.max_row)
    sheet.freeze_panes=None
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    return sheet


def _fact_source_label(comparison):
    label = {'ks6a': 'КС-6а', 'ks2': 'КС-2'}.get(comparison.get('source'), 'не определён')
    dates = [gpr.day(value) for value in fact_source_dates(comparison)]
    dates = [value for value in dates if value]
    return label+(' · '+max(dates).strftime('%d.%m.%Y') if dates else '')


def workbook(meta, cached):
    state = cached['gpr']
    comparison = cached.get('rds_comparison') or {}
    rows = comparison.get('rows') or [] if comparison.get('available') else []
    base = rds_export.workbook({**meta, 'layout': LAYOUT}, {**comparison, 'layout': LAYOUT, 'rows': rows}, rows)
    book = load_workbook(io.BytesIO(base))
    book.active.title = 'Выполнение'
    from developaid_contract_physical_sheets import write_audit, write_builder_template
    write_audit(book, comparison)
    write_builder_template(book, comparison)
    if not comparison.get('available'):
        book.active['A4'] = comparison.get('detail') or 'РДС или пригодные данные выполнения не определены.'
    sheet = book.create_sheet('ГПР', 0)
    schedule, overlays = state['schedule'], state.get('overlays') or {}
    positions = ordered_positions(gpr.position_projections(cached, comparison, schedule),meta['cut'])
    display = presentation(schedule, overlays, meta['cut'], positions,
                           source_dates=fact_source_dates(comparison),
                           _include_day=dt.date.today().isoformat(),_headroom_days=14)
    ticks = display['ticks']
    views = {line['code']:line for line in display['rows']+display['positions']}
    if len(ticks) > 1096 or len(schedule['lines'])+len(positions) > 10000:
        raise rds_export.ExportProblem('ГПР слишком большой для одной выгрузки. Проверьте диапазон исходного графика.')
    label = meta.get('label') or {}
    source = state['source']
    def put(row, column, value):
        cell = sheet.cell(row, column, rds_export._text(value) if isinstance(value, str) else value)
        if isinstance(cell.value, str):
            cell.data_type = 's'
        cell.font = Font(name='Calibri', size=10)
        cell.alignment = Alignment(vertical='top', wrap_text=True)
        return cell
    text_rows = ['ГПР · '+(label.get('contract') or 'Договор')+' · '+(label.get('contractor') or ''),
        'Проект: '+meta['project']+' · Редакция ГПР: '+_edition_label(source),
        'Срез: '+gpr.day(meta['cut']).strftime('%d.%m.%Y')+' · Источник выполнения: '+_fact_source_label(comparison),
        'Серый — будущий план; сиреневый — нет подтверждения. Зелёный — план выполнен; жёлтый — отставание; красный — подтверждённая незавершённость после срока.']
    statement = statement_projection(comparison)
    if statement:
        text_rows[3:3] = ['\n'.join(statement_text(statement))]
    if positions:
        known = sum(line.get('quantity') is not None for line in positions)
        text_rows.append('Объём известен по '+str(known)+' из '+str(len(positions))+
                         ' позиций РДС. Сначала показаны операции с ненулевым выполнением; исходный ГПР — ниже.')
    if schedule.get('assumption'):
        text_rows.append('Основа календарных дат ГПР: '+schedule['assumption'])
    text_rows.append('Последний известный объём сохраняется до следующего подтверждения и среза; сравнение с планом — на каждый день. Это не даты производства работ.')
    text_rows.append('Сегодня — оранжевая линия; дата среза — чёрная. При совпадении показана одна линия.')
    end_column = max(7, len(ticks)+6)
    for row, text in enumerate(text_rows, 1):
        put(row, 1, text)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        sheet.row_dimensions[row].height = (max(42, 6+14*sum(max(1, math.ceil(len(line)/110))
            for line in statement_text(statement))) if statement and row == 4 else 30)
    sheet['A1'].comment = Comment(rds_export._text('Источник SHA256: '+source['sha256']+
        '\nРедакция: '+str(source['edition'])+'\nОснование начала: '+str(schedule.get('anchor') or {})+
        '\nПодписание: '+str(state.get('signature_evidence') or {})), 'DevelopAid')
    if statement:
        sheet['A4'].comment = Comment(rds_export._text(str(statement)+
            '\nЭто сумма исходного снимка КС-6а, не оплата и не историческая оценка РДС.'), 'DevelopAid')
    today_row = len(text_rows)+1
    today = sheet.cell(today_row, 1)
    cut_day = gpr.day(meta['cut'])
    cut_formula = 'DATE('+str(cut_day.year)+','+str(cut_day.month)+','+str(cut_day.day)+')'
    today.value = '=IF(TODAY()='+cut_formula+',"Сегодня и срез: "&TEXT(TODAY(),"dd.mm.yyyy"),"Сегодня: "&TEXT(TODAY(),"dd.mm.yyyy")&" · срез: '+cut_day.strftime('%d.%m.%Y')+'")'
    if ticks and ticks[0].get('start') and ticks[-1].get('finish'):
        def clock_date(value):
            date = gpr.day(value)
            return 'DATE('+str(date.year)+','+str(date.month)+','+str(date.day)+')'
        today.value += '&IF(OR(TODAY()<'+clock_date(ticks[0]['start'])+',TODAY()>'+clock_date(ticks[-1]['finish'])+')," — вне диапазона календаря; обновите выгрузку","")'
    today.alignment = Alignment(wrap_text=True, vertical='top')
    sheet.merge_cells(start_row=today_row, start_column=1, end_row=today_row, end_column=6)
    sheet.row_dimensions[today_row].height = 30
    header = today_row+2
    for column, text in enumerate(('№', 'Работа / ресурс', 'Начало по плану', 'Окончание по плану',
                                  'Физический объём · 0–100%', 'План / отклонение на срез · источник'), 1):
        put(header, column, text)
    for index, tick in enumerate(ticks, 7):
        put(header, index, tick['label'])
        sheet.column_dimensions[get_column_letter(index)].width = 3.5
    for column in range(1, end_column+1):
        cell = sheet.cell(header, column)
        cell.fill = PatternFill('solid', fgColor='1F4E78')
        cell.font = Font(color='FFFFFF', bold=True, size=9)
    def identity(line,track):
        return {'track':track,'position_key':line.get('position_key'),'code':line['code'],
                'source_gpr_code':line.get('gpr_code') or line['code'],'section':line.get('section'),
                'gpr_sha256':source['sha256']}
    def status_note(row,status):
        if not status:
            return
        cell = sheet.cell(row,6)
        text = status['text']
        if status['state'] == 'overdue_incomplete':
            text = 'Срок прошёл '+str(status['days_after_planned_finish'])+' дн. назад; не завершено на '+status['observed_at']+' · остаток '+format(status['remaining_quantity'],'.15g')+' '+status['unit']+' ('+format(status['remaining_fraction']*100,'.1f')+'%)'
        elif status['state'] == 'overdue_unknown':
            text = 'Срок прошёл '+str(status['days_after_planned_finish'])+' дн. назад; факт не подтверждён.'
        elif status['state'] == 'deadline_comparison_unconfirmed':
            text = 'Срок прошёл; связь объёма с этим сроком не подтверждена.'
        elif status['state'] == 'not_due':
            text = 'Срок ещё не прошёл.'
        cell.value = str(cell.value or '')+'\n'+text
        if status['state'] == 'overdue_incomplete':
            sheet.cell(row,2).font = Font(name='Calibri',size=10,bold=True,color=COLORS['overdue'])
        elif status['state'] in {'overdue_unknown','deadline_comparison_unconfirmed','deadline_passed_unconfirmed'}:
            sheet.cell(row,2).font = Font(name='Calibri',size=10,color='9C6500')
    def write_reporting(row,line):
        view = views[line['code']]
        model = view.get('reporting')
        if not model:
            return
        sheet.cell(row,2).comment.text += '\n'+json.dumps({'reporting':model},ensure_ascii=False)
        for index,bar in reporting.cell_states(model,ticks).items():
            cell = put(row,index+7,'')
            cell.fill = PatternFill('solid',fgColor=COLORS[bar['state']])
            checkpoint = next((item for item in model['checkpoints'] if item['date']==bar['report_date']),model['current'])
            title = {'fact':'Известный объём покрывает план','warning':'Известный объём отстаёт от плана',
                     'overdue':'Не завершено после срока ГПР',
                     'closure_unconfirmed':'После срока нет свежего подтверждения завершения'}[bar['state']]
            cell.comment = Comment(title+' · состояние '+bar['state_start']+' — '+bar['state_finish']+
                ' · план '+format(bar['planned_fraction_start']*100,'.1f')+' → '+format(bar['planned_fraction_finish']*100,'.1f')+
                '% · факт '+format(bar['fact_fraction']*100,'.1f')+'% по данным от '+bar['report_date']+'; не даты производства'+'\n'+json.dumps({
                **identity(line,'report_state'),**bar,'checkpoint':checkpoint,'not_actual_dates':True},ensure_ascii=False),'DevelopAid')
            if bar['range_kind'] in {'checkpoint','source_snapshot'}:
                cell.value = '●'
                cell.alignment = Alignment(horizontal='center',vertical='center')
    def write_positions(row):
        put(row, 2, 'Физический факт по позициям РДС — отдельно от общего процента конструкции')
        sheet.row_dimensions[row].height = 34
        row += 1
        from developaid_contract_hierarchy import style_row
        section = None
        for line in positions:
            if line.get('section') != section:
                section = line.get('section')
                put(row,2,section or 'Корпус не определён')
                sheet.merge_cells(start_row=row,start_column=2,end_row=row,end_column=6)
                style_row(sheet,row,corpus=True,through=6)
                row += 1
            quantity = line.get('quantity')
            progress = physical_progress(line, line.get('physical'), meta['cut'], fact_source_dates(comparison))
            text = (format(quantity['fact_quantity'], '.15g')+' / '+format(quantity['contract_quantity'], '.15g')+
                    ' '+quantity['unit']+' · '+format(quantity['fraction']*100, '.1f')+'%') if quantity else (line.get('physical_audit') or {}).get('reason') or 'Нет сопоставленного объёма'
            for column, value in enumerate((line['number'], line['name']+'\nИсходный план · Факт: '+text, line.get('start'), line.get('finish'),
                progress['fraction'] if progress else text,
                progress_cell_text(progress)+'\nПодтверждение: '+str(views[line['code']]['reporting'].get('last_confirmed_at') or 'нет')+
                ' · возраст '+str(views[line['code']]['reporting'].get('age_days') if views[line['code']]['reporting'].get('age_days') is not None else '—')+' дн.'), 1):
                put(row, column, value)
            if progress:
                sheet.cell(row, 5).number_format = '0.0%'
                sheet.conditional_formatting.add('E'+str(row), DataBarRule(start_type='num', start_value=0,
                    end_type='num', end_value=1, color=COLORS['fact'], showValue=True))
            sheet.cell(row, 5).comment = Comment(rds_export._text(line['note']+'\n'+progress_text(progress)+
                '\nНакопленный объём не задаёт календарный интервал. Шкала E: 0–100%.'), 'DevelopAid')
            sheet.cell(row,2).comment = Comment(json.dumps(identity(line,'source_plan'),ensure_ascii=False),'DevelopAid')
            status_note(row,views[line['code']].get('deadline_status'))
            for column in range(7, end_column+1):
                sheet.cell(row, column).border = Border(bottom=Side(style='thin', color='DCE6F1'))
            for index, state_name in cell_states(line, ticks, line.get('physical'), meta['cut']).items():
                put(row, index+7, '').fill = PatternFill('solid', fgColor=COLORS[state_name])
            style_row(sheet,row,line.get('number'),through=6)
            sheet.row_dimensions[row].height = min(300,max(78,14*(math.ceil(len(line['name'])/50)+math.ceil(len(text)/50)+3)))
            write_reporting(row,line)
            row += 1
        return row
    row = write_positions(header+1) if positions else header+1
    if positions:
        put(row, 2, "Исходный ГПР — строки и интервалы документа")
        row += 1
    source_first_row = row
    row = source_first_row
    for line in schedule['lines']:
        overlay = overlays.get(line['code'])
        progress = physical_progress(line, overlay, meta['cut'], fact_source_dates(comparison))
        for column, value in enumerate((line['code'], line['name'], line.get('start'), line.get('finish'),
                 progress['fraction'] if progress else 'Общий % не рассчитан; операции выше' if positions else 'не подтверждён',
                 progress_cell_text(progress)+'\nГПР, стр. '+str(line.get('page') or '—')), 1):
            put(row, column, value)
        if progress:
            sheet.cell(row, 5).number_format = '0.0%'
            sheet.conditional_formatting.add('E'+str(row), DataBarRule(start_type='num', start_value=0,
                end_type='num', end_value=1, color=COLORS['fact'], showValue=True))
        for column in range(7, end_column+1):
            sheet.cell(row, column).border = Border(bottom=Side(style='thin', color='DCE6F1'))
        for index, state_name in cell_states(line, ticks, overlay, meta['cut']).items():
            put(row, index+7, '').fill = PatternFill('solid', fgColor=COLORS[state_name])
        sheet.cell(row, 2).comment = Comment(rds_export._text(str(segments(line))+
            ('\nДлительность, напечатанная в ГПР: '+str(line['duration_printed'])+' '+str(line.get('relative_unit'))
             if line.get('duration_printed') is not None else '')+
            ('\n'+progress_text(progress) if progress else '\nПригодного отдельного физического показателя нет.')), 'DevelopAid')
        sheet.cell(row,2).comment.text += '\n'+json.dumps(identity(line,'source_plan'),ensure_ascii=False)
        status_note(row,views[line['code']].get('deadline_status'))
        write_reporting(row,line)
        row += 1
    row += 2
    for resource in schedule.get('resources') or []:
        put(row, 2, resource['name'])
        put(row, 6, 'Категория: '+resource['category']+'; повторённые строки не суммируются.')
        columns = {column['period']: column for column in schedule.get('columns') or []}
        for value in resource.get('values') or []:
            period = columns.get(value['period']) or {}
            for index, tick in enumerate(ticks, 7):
                matches = (period.get('start_day') and tick.get('start_day') and
                           period['start_day'] <= tick['start_day'] <= period['finish_day'])
                matches = matches or (value.get('start') and tick.get('start') and
                                      tick['start'] <= value['start'] <= tick['finish'])
                if matches:
                    number = value.get('value')
                    put(row, index, str(number['min'])+'–'+str(number['max']) if isinstance(number, dict) else number)
        row += 1
    # TODAY is intentionally dynamic in Excel. Calendar colors remain source
    # plan; date markers are borders, never percentages stretched over dates.
    last_calendar_row = row
    for index, tick in enumerate(ticks, 7):
        if not tick.get('start') or not tick.get('finish'):
            continue
        column = get_column_letter(index)
        area = column+str(header)+':'+column+str(last_calendar_row)
        first_day, last_day = gpr.day(tick['start']), gpr.day(tick['finish'])
        def date_formula(value):
            return 'DATE('+str(value.year)+','+str(value.month)+','+str(value.day)+')'
        sheet.conditional_formatting.add(area, FormulaRule(formula=['AND(TODAY()>='+date_formula(first_day)+
            ',TODAY()<='+date_formula(last_day)+')'], border=Border(left=Side(style='medium', color='D97706'))))
        if tick['start'] <= meta['cut'] <= tick['finish']:
            for marker_row in range(header, last_calendar_row+1):
                cell = sheet.cell(marker_row, index)
                cell.border = Border(left=Side(style='medium', color='111111'), bottom=cell.border.bottom)
    row += 2
    details = [LEGEND, schedule.get('assumption') or 'Календарные даты из исходного ГПР.',
        (state.get('workforce') or {}).get('reason') or (state.get('workforce') or {}).get('note')
            or (state.get('staffing') or {}).get('note') or 'Сопоставление численности требует одинакового состава работ.',
        'Видимые отметки ЭДО и подтверждение оператора не являются криптографической проверкой подписи.']
    for condition in state.get('conditions') or []:
        details.append(condition['quote']+' '+condition['note']+
                       (' Расчётный ориентир: '+condition['reference_finish'] if condition.get('reference_finish') else
                        ' Все условия начала работ не подтверждены.'))
    for detail in details:
        put(row+1, 1, detail)
        sheet.merge_cells(start_row=row+1, start_column=1, end_row=row+1, end_column=6)
        sheet.row_dimensions[row+1].height = 44
        row += 1
    if workforce.write_sheet(book, state.get('workforce') or {}) is None:
        write_company_workforce(book,state.get('workforce') or {})
    for page in book:
        page.freeze_panes = None
        page.sheet_view.topLeftCell = 'A1'
    book.active = 0
    sheet.column_dimensions['A'].width = 9
    sheet.column_dimensions['B'].width = 55
    for column in ('C', 'D', 'E'):
        sheet.column_dimensions[column].width = 18
    sheet.column_dimensions['F'].width = 30
    sheet.sheet_view.zoomScale = 80
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    output = io.BytesIO()
    book.save(output)
    raw = output.getvalue()
    if len(raw) > rds_export.MAX_XLSX_BYTES:
        raise rds_export.ExportProblem('Excel ГПР превысил допустимый размер.')
    return raw
