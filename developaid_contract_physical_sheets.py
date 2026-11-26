"""Private lineage and builder entry sheets in the real contract export."""
import json
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
            cell.alignment = Alignment(wrap_text=True,vertical='top')
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
        def joined(key):
            return '; '.join(str(x[key]) if x.get(key) is not None else 'не записан' for x in sources) or 'нет источника'
        references = '; '.join(str(x.get('source',{}).get('sheet',''))+'!'+str(x.get('source',{}).get('row',''))+
            ' · '+str(x.get('source',{}).get('completed_quantity_cell') or '') for x in sources)
        binding = audit.get('gpr_binding') or {}
        links = '; '.join(str(x['code'])+' × '+str(x['share']) for x in binding.get('lines') or [])
        sheet.append([section,row.get('number'),row.get('name'),row.get('contract_quantity'),row.get('unit'),references,
            joined('reported_work_quantity'),joined('reported_material_quantity'),joined('snapshot_date'),
            row.get('fact_quantity'),audit.get('accepted_material_quantity'),audit.get('conversion') or 'не принято',
            links or binding.get('reason') or 'не привязано',audit.get('state') or 'audit_not_retained',
            audit.get('reason') or (row.get('comments') or {}).get('fact_quantity') or 'Аудит источника не сохранён; обновите карточку.'])
        style_row(sheet,sheet.max_row,row.get('number'),name_column=3)
        sheet.cell(sheet.max_row,6).comment = Comment(json.dumps(audit,ensure_ascii=False),'DevelopAid')
    _finish(sheet)


def write_builder_template(book, comparison):
    sheet = _sheet(book,'Физфакт строителей',
        'Заполняйте жёлтые поля: накопленный объём на дату наблюдения, отдельно для монтажа и поставки. '
        'Пусто = нет сведений; 0 = явно подтверждённый ноль. Не складывайте накопленные итоги разных дат. '
        'Это лист сбора данных: ввод не изменяет КС, принятый факт или Гант автоматически. Для принятия нужны проверка источника и привязки.',
        ['Корпус / участок','№ РДС','Операция','Вид','Ед.','Всего РДС','Дата наблюдения','Накопленный физфакт',
         'Исполнитель','Основание / документ / фото','Примечание','Редакция РДС','Идентификатор позиции'],
        [26,12,55,15,10,16,18,22,26,50,45,25,22])
    headings = {}
    for heading in comparison.get('headings') or []:
        headings.setdefault(heading['before_position'],[]).append(heading)
    section = ''
    for index,row in enumerate(comparison.get('rows') or []):
        for heading in headings.get(index,[]):
            if not heading.get('number'):
                section = heading['name']
            sheet.append([heading.get('number') or '',heading['name']])
            sheet.merge_cells(start_row=sheet.max_row,start_column=2,end_row=sheet.max_row,end_column=11)
            style_row(sheet,sheet.max_row,heading.get('number'),corpus=not heading.get('number'),through=13)
        for kind in ('Монтаж','Поставка'):
            sheet.append([section,row.get('number'),row.get('name'),kind,row.get('unit'),row.get('contract_quantity'),
                None,None,None,None,None,comparison.get('estimate_sha256'),str(row.get('estimate'))+':'+str(row.get('index'))])
            style_row(sheet,sheet.max_row,row.get('number'),name_column=3)
            for col in range(7,12):
                sheet.cell(sheet.max_row,col).fill = PatternFill('solid',fgColor='FFF2CC')
            sheet.cell(sheet.max_row,7).number_format = 'DD.MM.YYYY'
    if sheet.max_row >= 4:
        qty = DataValidation(type='decimal',operator='greaterThanOrEqual',formula1='0',allow_blank=True)
        date = DataValidation(type='date',operator='between',formula1='DATE(2000,1,1)',formula2='TODAY()',allow_blank=True)
        for validation,area,message in [(qty,f'H4:H{sheet.max_row}','Укажите неотрицательный накопленный объём.'),
                                        (date,f'G4:G{sheet.max_row}','Укажите дату наблюдения, не позднее сегодняшней.')]:
            validation.showErrorMessage = True; validation.errorTitle = 'Проверьте значение'; validation.error = message
            sheet.add_data_validation(validation);validation.add(area)
    _finish(sheet)
