"""Two-sheet, source-current GPR and accepted RDS performance workbook."""
from __future__ import annotations

import datetime as dt
import io
import math
import re
from urllib.parse import quote

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import developaid_contract_gpr as gpr
import developaid_contract_comparison_export as rds_export
from developaid_contract_rds import LAYOUT

SCHEMA = 'contract-gpr-performance-xlsx-v2'
COLORS = {'plan': '9DC3E6', 'fact': '70AD47', 'lag': 'E06666', 'unknown': 'D9D9D9'}
LEGEND = ('Синий — исходный план; зелёный — подтверждённая физическая доля на дату среза; '
          'красный — невыполненная часть плана к срезу и срок после окончания незавершённой работы; '
          'серый — нет единого сопоставимого физического показателя строки. Цвет факта — проекция накопительного '
          'объёма на исходные полосы, а не ежедневная история работ. Деньги не заменяют физический объём.')


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
    return meta


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


def timeline(schedule, cut, overlays=None):
    relative = schedule.get('calendar_basis') == 'relative'
    anchored = (schedule.get('anchor') or {}).get('handover_date') if relative else None
    if relative:
        maximum = max((column['finish_day'] for column in schedule.get('columns') or []), default=0)
        first = gpr.day(anchored)
        if first and any(value['fact_fraction'] < 1 for value in (overlays or {}).values()) and gpr.day(cut):
            maximum = max(maximum, (gpr.day(cut)-first).days+1)
        step = max(1, math.ceil(maximum/366))
        return [{'start': (first+dt.timedelta(days=i)).isoformat() if first else None,
                 'finish': (first+dt.timedelta(days=min(i+step, maximum)-1)).isoformat() if first else None,
                 'start_day': i+1, 'finish_day': min(i+step, maximum),
                 'label': (first+dt.timedelta(days=i)).strftime('%d.%m') if first else str(i+1)}
                for i in range(0, maximum, step)]
    dates = [gpr.day(line.get(key)) for line in schedule.get('lines') or [] for key in ('start', 'finish')]
    dates = [date for date in dates if date]
    if not dates:
        return []
    first, last = min(dates), max(dates)
    if any(value['fact_fraction'] < 1 for value in (overlays or {}).values()) and gpr.day(cut):
        last = max(last, gpr.day(cut))
    step = max(1, math.ceil(((last-first).days+1)/366))
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
    indices = [i for i, tick in enumerate(ticks) if occupied(line, tick)]
    result = {i: 'plan' if overlay else 'unknown' for i in indices}
    if overlay and indices:
        ready = overlay['fact_fraction']*len(indices)
        due = (overlay.get('planned_fraction') or 0)*len(indices)
        for position, index in enumerate(indices):
            if position+.5 <= ready:
                result[index] = 'fact'
            elif position+.5 <= due:
                result[index] = 'lag'
        if overlay['fact_fraction'] < 1 and line.get('finish'):
            for index, tick in enumerate(ticks):
                if tick.get('start') and line['finish'] < tick['start'] <= cut:
                    result[index] = 'lag'
    return result


def ordered_positions(positions):
    """Keep known nonzero work visible; never reorder the original RDS table."""
    return sorted(positions, key=lambda line: (0 if (line.get('quantity') or {}).get('fact_quantity', 0) > 0
                                              else 1 if line.get('quantity') else 2))


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


def presentation(schedule, overlays, cut, positions=(), *, statement=None, _ticks=None):
    """Geometry shared by the native popup and the export's source commentary."""
    positions = ordered_positions(positions)
    position_overlays = {line['code']: line['physical'] for line in positions if line.get('physical')}
    ticks = _ticks if _ticks is not None else timeline(schedule, cut, {**overlays, **position_overlays})
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
            if end > begin:
                parts.append((begin, end))
        overlay = overlays.get(line['code'])
        total = sum(end-begin for begin, end in parts)
        bars = [{'start': begin, 'end': end, 'state': 'plan' if overlay else 'unknown'} for begin, end in parts]
        consumed = 0
        if overlay and total:
            ready = total*overlay['fact_fraction']
            due = total*(overlay.get('planned_fraction') or 0)
            for begin, end in parts:
                green = min(end-begin, max(ready-consumed, 0))
                if green:
                    bars.append({'start': begin, 'end': begin+green, 'state': 'fact'})
                red_begin, red_end = max(ready-consumed, 0), min(end-begin, due-consumed)
                if red_end > red_begin:
                    bars.append({'start': begin+red_begin, 'end': begin+red_end, 'state': 'lag'})
                consumed += end-begin
            if first and line.get('finish') and line['finish'] < cut and overlay['fact_fraction'] < 1:
                bars.append({'start': (gpr.day(line['finish'])-first).days+1,
                             'end': (gpr.day(cut)-first).days+1, 'state': 'lag', 'overdue': True})
        rows.append({'code': line['code'], 'name': line['name'], 'start': line.get('start'),
                     'finish': line.get('finish'), 'relative_segments': line.get('relative_segments'),
                     'duration_printed': line.get('duration_printed'), 'relative_unit': line.get('relative_unit'),
                     'page': line.get('page'), 'bars': bars, 'physical': overlay,
                     **{key: line[key] for key in ('number', 'section', 'position_key', 'gpr_code', 'quantity', 'note') if key in line}})
    projected = (presentation({**schedule, 'lines': positions}, position_overlays, cut, _ticks=ticks)['rows']
                 if positions else [])
    return {'ticks': ticks, 'length': length, 'rows': rows, 'positions': projected, 'statement': statement,
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


def _fact_source_label(comparison):
    label = {'ks6a': 'КС-6а', 'ks2': 'КС-2'}.get(comparison.get('source'), 'не определён')
    summary = comparison.get('statement_summary') or {}
    dates = [gpr.day(value) for value in summary.get('source_dates') or []]
    if not any(dates):
        dates = [gpr.day(act.get('date')) for act in (comparison.get('act_evidence') or {}).get('acts') or []]
    dates = [value for value in dates if value]
    return label+(' · '+max(dates).strftime('%d.%m.%Y') if dates else '')


def workbook(meta, cached):
    state = cached['gpr']
    comparison = cached.get('rds_comparison') or {}
    rows = comparison.get('rows') or [] if comparison.get('available') else []
    base = rds_export.workbook({**meta, 'layout': LAYOUT}, {**comparison, 'layout': LAYOUT, 'rows': rows}, rows)
    book = load_workbook(io.BytesIO(base))
    book.active.title = 'Выполнение'
    if not comparison.get('available'):
        book.active['A4'] = comparison.get('detail') or 'РДС или пригодные данные выполнения не определены.'
    sheet = book.create_sheet('ГПР', 0)
    schedule, overlays = state['schedule'], state.get('overlays') or {}
    positions = ordered_positions(gpr.position_projections(cached, comparison, schedule))
    display = presentation(schedule, overlays, meta['cut'], positions)
    ticks = display['ticks']
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
        'Синий — план; зелёный — выполненный объём; красный — отставание; серый — нет сопоставимого физического показателя.']
    statement = statement_projection(comparison)
    if statement:
        text_rows[3:3] = ['\n'.join(statement_text(statement))]
    if positions:
        known = sum(line.get('quantity') is not None for line in positions)
        text_rows.append('Объём известен по '+str(known)+' из '+str(len(positions))+
                         ' позиций РДС. Сначала показаны операции с ненулевым выполнением; исходный ГПР — ниже.')
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
    header = len(text_rows)+2
    for column, text in enumerate(('№', 'Работа / ресурс', 'Начало', 'Окончание', 'Физический факт', 'Источник / основание'), 1):
        put(header, column, text)
    for index, tick in enumerate(ticks, 7):
        put(header, index, tick['label'])
        sheet.column_dimensions[get_column_letter(index)].width = 3.5
    for column in range(1, end_column+1):
        cell = sheet.cell(header, column)
        cell.fill = PatternFill('solid', fgColor='1F4E78')
        cell.font = Font(color='FFFFFF', bold=True, size=9)
    def write_positions(row):
        put(row, 2, 'Физический факт по позициям РДС — отдельно от общего процента конструкции')
        sheet.row_dimensions[row].height = 34
        row += 1
        for line in positions:
            quantity = line.get('quantity')
            text = (format(quantity['fact_quantity'], '.15g')+' / '+format(quantity['contract_quantity'], '.15g')+
                    ' '+quantity['unit']+' · '+format(quantity['fraction']*100, '.1f')+'%') if quantity else 'Нет сопоставленного объёма'
            for column, value in enumerate((line['number'], line['name']+'\nФакт: '+text, line.get('start'), line.get('finish'),
                text, (line.get('section')+' · ' if line.get('section') else '')+_fact_source_label(comparison)), 1):
                put(row, column, value)
            sheet.cell(row, 5).comment = Comment(rds_export._text(line['note']), 'DevelopAid')
            for index, state_name in cell_states(line, ticks, line.get('physical'), meta['cut']).items():
                put(row, index+7, '').fill = PatternFill('solid', fgColor=COLORS[state_name])
            sheet.row_dimensions[row].height = 64
            row += 1
        return row
    row = write_positions(header+1) if positions else header+1
    if positions:
        put(row, 2, "Исходный ГПР — строки и интервалы документа")
        row += 1
    source_first_row = row
    for row, line in enumerate(schedule['lines'], source_first_row):
        overlay = overlays.get(line['code'])
        for column, value in enumerate((line['code'], line['name'], line.get('start'), line.get('finish'),
                 (str(overlay['fact_quantity'])+' / '+str(overlay['contract_quantity'])+' '+str(overlay['unit']))
                 if overlay else 'Общий % не рассчитан; операции выше' if positions else 'не подтверждён',
                 'ГПР, стр. '+str(line.get('page') or '—')), 1):
            put(row, column, value)
        for index, state_name in cell_states(line, ticks, overlay, meta['cut']).items():
            put(row, index+7, '').fill = PatternFill('solid', fgColor=COLORS[state_name])
        sheet.cell(row, 2).comment = Comment(rds_export._text(str(segments(line))+
            ('\nДлительность, напечатанная в ГПР: '+str(line['duration_printed'])+' '+str(line.get('relative_unit'))
             if line.get('duration_printed') is not None else '')+
            ('\n'+overlay['note'] if overlay else '\nПригодного отдельного физического показателя нет.')), 'DevelopAid')
    row = source_first_row+len(schedule['lines'])+2
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
    row += 2
    details = [LEGEND, schedule.get('assumption') or 'Календарные даты из исходного ГПР.',
        (state.get('staffing') or {}).get('note') or 'Сопоставление численности требует одинакового состава работ.',
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
