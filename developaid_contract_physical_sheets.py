"""Private lineage and builder entry sheets in the real contract export."""
import json
from copy import copy
import math
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter
from developaid_contract_hierarchy import style_row


def _sheet(book, title, note, headers, widths):
    sheet = book.create_sheet(title)
    sheet.append([title]); sheet.append([note]); sheet.merge_cells(start_row=2,start_column=1,end_row=2,end_column=len(headers))
    sheet.row_dimensions[2].height = 65
    sheet.append(headers)
    for i,width in enumerate(widths,1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    sheet.freeze_panes = None
    return sheet


def _finish(sheet):
    sheet.auto_filter.ref = f'A3:{get_column_letter(sheet.max_column)}{sheet.max_row}'
    for row in sheet:
        for cell in row:
            if isinstance(cell.value,str):
                cell.data_type = 's'
            alignment=copy(cell.alignment);alignment.wrap_text=True;alignment.vertical='top'
            cell.alignment=alignment
            if cell.row <= 3:
                cell.font = Font(name='Calibri',size=11,bold=True)
        if row[0].row >= 4:
            lines = max((sum(max(1,math.ceil(len(part)/max(10,(sheet.column_dimensions[cell.column_letter].width or 20)-2))) for part in str(cell.value or '').splitlines()) for cell in row),default=1)
            sheet.row_dimensions[row[0].row].height = min(240,max(48,lines*14+8))


def write_audit(book, comparison):
    sheet = _sheet(book,'Аудит физобъёмов',
        'Одна строка на позицию РДС. Исходное число не равно принятому факту. Нулевой итог над пустыми периодами '
        'не подтверждает ноль работ. Полное происхождение и связи сохранены в примечании. Денежные значения не пересчитываются.',
        ['Корпус / участок','№ РДС','Операция','РДС: объём','Единица','Строка КС / ячейка','Исходный объём работ',
         'Исходная поставка','Дата источника','Физический факт работ','Принятая поставка','Преобразование','Связь с ГПР','Состояние','Причина'],
        [25,12,55,15,12,30,20,20,16,20,20,18,27,30,80])
    section = ''
    headings = {x['before_position']:x['name'] for x in comparison.get('headings') or [] if not x.get('number')}
    for index,row in enumerate(comparison.get('rows') or []):
        section = headings.get(index,section)
        audit = row.get('physical_audit') or {}
        sources = audit.get('sources') or []
        events = audit.get('accepted_events') or []
        def joined(key):
            return '; '.join(str(x[key]) if x.get(key) is not None else 'не записан' for x in sources) or 'нет источника'
        references = '; '.join(str(x.get('source',{}).get('sheet',''))+'!'+str(x.get('source',{}).get('row',''))+
            ' · '+str(x.get('source',{}).get('completed_quantity_cell') or '') for x in sources)
        work, material, dates = joined('reported_work_quantity'), joined('reported_material_quantity'), joined('snapshot_date')
        if not sources and events:
            # Preserve the typed act increment instead of inventing a raw
            # cumulative cell or saying that a known quantity has no source.
            references = '; '.join(str(x.get('label') or 'КС')+' · стр. '+str(x['source'].get('page') or '—')+
                ' · строка '+str(x['source'].get('row') or '—')+' · SHA '+str(x['source'].get('sha256') or x['source'].get('file_sha256') or 'не указан') for x in events)
            work = '; '.join(str(x['work_quantity']) for x in events)
            material = 'В датированных записях объём поставки не указан'
            dates = '; '.join(dict.fromkeys(x['end'] for x in events))
        binding = audit.get('gpr_binding') or {}
        links = '; '.join(str(x['code'])+' × '+str(x['share']) for x in binding.get('lines') or [])
        sheet.append([section,row.get('number'),row.get('name'),row.get('contract_quantity'),row.get('unit'),references,
            work,material,dates,
            row.get('fact_quantity'),audit.get('accepted_material_quantity'),audit.get('conversion') or 'не принято',
            links or binding.get('reason') or 'не привязано',audit.get('state') or 'audit_not_retained',
            audit.get('reason') or (row.get('comments') or {}).get('fact_quantity') or 'Аудит источника не сохранён; обновите карточку.'])
        style_row(sheet,sheet.max_row,row.get('number'),name_column=3)
        sheet.cell(sheet.max_row,6).comment = Comment(json.dumps(audit,ensure_ascii=False),'DevelopAid')
    _finish(sheet)


def write_builder_template(book, comparison, schedule=None):
    from developaid_contract_builder_plan import plan_spec, fraction_formula, date
    import datetime as dt
    sheet = _sheet(book,'Физфакт строителей',
        'Жёлтые поля — дата наблюдения, накопленный факт, исполнитель и основание. План заполняется автоматически: '
        'на дату строки, а пока она пуста — на срез I1. Голубое I1 меняет дату планового среза. '
        'Монтаж и поставка раздельно; при отсутствии отдельного графика поставки её план не выдумывается. '
        'Факт заполнен 0 по умолчанию: внесите измеренный накопленный объём и дату. Отклонение — факт минус план. Ввод не изменяет КС и принятый Гант автоматически.',
        ['Корпус / участок','№ РДС','Операция','Вид','Ед.','Всего РДС','Начало ГПР','Окончание ГПР',
         'Дата наблюдения','План, объём','План, %','Накопленный физфакт','Факт, %','Факт − план, объём',
         'Факт − план, п.п.','Исполнитель','Основание / документ / фото','Примечание','Редакция РДС',
         'Идентификатор позиции','Основание плана'],
        [26,12,55,15,10,16,16,16,18,18,14,22,14,20,18,26,50,40,25,22,65])
    sheet['H1']='План на срез →'
    sheet['I1']=date(comparison.get('cut')) or dt.date.today()
    sheet['I1'].number_format='DD.MM.YYYY'
    sheet['I1'].fill=PatternFill('solid',fgColor='DDEBF7')
    sheet['I1'].comment=Comment('Дата планового среза. При введённой дате наблюдения план строки пересчитывается на неё.','DevelopAid')
    headings = {}
    for heading in comparison.get('headings') or []:
        headings.setdefault(heading['before_position'],[]).append(heading)
    section = ''; formulas=[]; editable_rows=[]
    for index,row in enumerate(comparison.get('rows') or []):
        for heading in headings.get(index,[]):
            if not heading.get('number'):
                section = heading['name']
            sheet.append([heading.get('number') or '',heading['name']])
            sheet.merge_cells(start_row=sheet.max_row,start_column=2,end_row=sheet.max_row,end_column=18)
            style_row(sheet,sheet.max_row,heading.get('number'),corpus=not heading.get('number'),through=21)
        for kind in ('Монтаж','Поставка'):
            spec=plan_spec(row,comparison,schedule) if kind=='Монтаж' else row.get('material_builder_plan')
            method=spec['method'] if spec else ('Отдельный график поставки не указан.' if kind=='Поставка' else 'Нет принятой связи с ГПР; план неизвестен.')
            sheet.append([section,row.get('number'),row.get('name'),kind,row.get('unit'),row.get('contract_quantity'),
                date(spec['start']) if spec else None,date(spec['finish']) if spec else None,
                None,None,None,0,None,None,None,None,None,None,comparison.get('estimate_sha256'),
                str(row.get('estimate'))+':'+str(row.get('index')),method])
            number=sheet.max_row;editable_rows.append(number)
            style_row(sheet,number,row.get('number'),name_column=3)
            for col in (9,12,16,17,18):
                sheet.cell(number,col).fill = PatternFill('solid',fgColor='FFF2CC')
            for col in (7,8,9):sheet.cell(number,col).number_format='DD.MM.YYYY'
            if spec:
                formulas.extend([(f'K{number}',fraction_formula(spec,number)),
                    (f'J{number}',f'=IF(ISNUMBER(F{number}),F{number}*K{number},"")')])
                sheet.cell(number,21).comment=Comment(json.dumps(spec.get('source') or {},ensure_ascii=False),'DevelopAid')
            formulas.extend([
                (f'N{number}',f'=IF(J{number}="","",IF(L{number}="",0,L{number})-J{number})'),
                (f'O{number}',f'=IF(OR(K{number}="",F{number}<=0),"",(IF(L{number}="",0,L{number})/F{number}-K{number})*100)')])
            formulas.append((f'M{number}',f'=IF(F{number}<=0,"",IF(L{number}="",0,L{number})/F{number})'))
            for col in (11,13):sheet.cell(number,col).number_format='0.0%'
            for col in (10,12,14,15):sheet.cell(number,col).number_format='#,##0.00'
    qty = DataValidation(type='decimal',operator='greaterThanOrEqual',formula1='0',allow_blank=True)
    observed = DataValidation(type='date',operator='between',formula1='DATE(2000,1,1)',formula2='TODAY()',allow_blank=True)
    for validation,message in [(qty,'Укажите неотрицательный накопленный объём.'),
                               (observed,'Укажите дату наблюдения, не позднее сегодняшней.')]:
        validation.showErrorMessage=True;validation.errorTitle='Проверьте значение';validation.error=message
        sheet.add_data_validation(validation)
    for number in editable_rows:
        qty.add(f'L{number}');observed.add(f'I{number}')
    _finish(sheet)
    for coordinate,formula in formulas:sheet[coordinate]=formula
    return sheet
