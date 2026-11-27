"""Add a builder entry sheet to a supplied RDS workbook; never import it into production.

Usage: python scripts/contract_builder_template.py SOURCE --sheet 'RDS sheet' --output OUTPUT
The source layout must explicitly name quantity, unit and total in A:J. Formula
caches of unchanged source cells are retained for read-only/mobile viewers.
"""
from __future__ import annotations
import argparse
import datetime as dt
import copy
import hashlib
import io
import math
import re
import sys
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET
from openpyxl import load_workbook
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from developaid_contract_physical_sheets import write_builder_template
from developaid_contract_hierarchy import style_row
from developaid_contract_builder_plan import cache_builder_formulas, BuilderEvaluator

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def retain_formula_caches(source, output):
    """Restore caches after prepare() verified every original formula unchanged.

    Shared-formula follower XML has no formula text; openpyxl expands it.
    Equality is therefore checked through the workbook model before this step.
    """
    buffer = io.BytesIO()
    with ZipFile(source) as before, ZipFile(output) as after, ZipFile(buffer,'w',ZIP_DEFLATED) as result:
        for member in after.infolist():
            raw = after.read(member.filename)
            if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',member.filename) and member.filename in before.namelist():
                old = ET.fromstring(before.read(member.filename));new = ET.fromstring(raw)
                cells = {c.get('r'):c for c in old.iter(MAIN+'c')}
                for cell in new.iter(MAIN+'c'):
                    original = cells.get(cell.get('r'))
                    if original is None:
                        continue
                    formula,old_formula = cell.find(MAIN+'f'),original.find(MAIN+'f')
                    cached = original.find(MAIN+'v')
                    if cached is None or original.get('t') in ('s','inlineStr'):
                        continue
                    if (formula is None) != (old_formula is None):
                        continue
                    current = cell.find(MAIN+'v')
                    if current is not None:
                        cell.remove(current)
                    cell.append(copy.deepcopy(cached))
                    if original.get('t'):
                        cell.set('t',original.get('t'))
                raw = ET.tostring(new,encoding='utf-8',xml_declaration=True)
            result.writestr(member,raw)
    Path(output).write_bytes(buffer.getvalue())



def linked_physical_plans(book, values, rds_name, *, comparison_name='Накопленный план-факт', gpr_name='ГПР актуальный'):
    """Follow explicit formula references, never similar names or number prefixes."""
    if comparison_name not in book or gpr_name not in book:return {},None
    reference=book[comparison_name];schedule=book[gpr_name]
    if reference['B1'].value!='Всего по договору (РДС)' or reference['C1'].value!='План на дату ГПР':
        raise ValueError('Не подтверждены подписи физического плана.')
    if schedule['E8'].value!='Начало' or schedule['F8'].value!='Окончание' or schedule['L8'].value!='План на дату, %':
        raise ValueError('Не подтверждены колонки исходного ГПР.')
    base=re.escape("'"+rds_name.replace("'","''")+"'!")
    gpr=re.escape("'"+gpr_name.replace("'","''")+"'!")
    result={}
    # The RDS itself selects its active plan/fact row. There are old duplicate
    # comparison blocks below it; scanning all look-alike references is unsafe.
    rds_sheet=book[rds_name]
    comparison_ref=re.escape("'"+comparison_name.replace("'","''")+"'!")
    corpus=''
    norm=lambda text:re.sub(r'\s+',' ',str(text or '')).strip().casefold()
    corpus_id=lambda text:(re.search(r'корпус\s*(\d+)',norm(text)).group(1) if re.search(r'корпус\s*(\d+)',norm(text)) else None)
    for raw in values[rds_name].iter_rows(min_row=8):
        identity=raw[0].row
        if str(raw[1].value or '').startswith('ВСЕГО по РДС'):break
        if raw[0].value is None and str(raw[1].value or '').startswith('Корпус'):corpus=str(raw[1].value)
        if raw[0].value is None or not isinstance(raw[3].value,(int,float)) or not isinstance(raw[9].value,(int,float)):continue
        selected=re.fullmatch(r'='+comparison_ref+r'\$?D\$?(\d+)',str(rds_sheet.cell(identity,12).value or ''))
        fallback=None
        if not selected:
            # Some RDS rows have no formula link. Require a full, unique
            # number + corpus + exact work title identity; never number alone.
            title=norm(str(raw[1].value or '').split(':',1)[0]).rstrip('.')
            candidates=[cells[0].row for cells in schedule.iter_rows(min_row=9,max_col=6)
                if str(cells[1].value or '').strip()==str(raw[0].value).strip()
                and corpus_id(cells[0].value)==corpus_id(corpus) and corpus_id(corpus) is not None
                and norm(cells[3].value).rstrip('.')==title
                and isinstance(cells[4].value, dt.datetime)
                and isinstance(cells[5].value, dt.datetime)]
            if len(candidates)!=1:continue
            fallback=candidates[0]
        number=int(selected[1]) if selected else None
        if selected:
            rds=re.fullmatch(r'='+base+r'\$?([DJ])\$?(\d+)',str(reference.cell(number,2).value or ''))
            if not rds or int(rds[2])!=identity:
                raise ValueError('Явная ссылка РДС на физический план не возвращает ту же позицию.')
            targets=re.findall(gpr+r'\$L\$(\d+)',str(reference.cell(number,3).value or ''))
            if len(targets)!=1:raise ValueError('Нет единственной явной ссылки плана операции на ГПР.')
            row=int(targets[0])
        else:
            row=fallback
        result[identity]={'start':values[gpr_name].cell(row,5).value.isoformat()[:10],
              'finish':values[gpr_name].cell(row,6).value.isoformat()[:10],
              'source_formula':schedule.cell(row,12).value,'source_row':row,
              'method':str(schedule['A4'].value),
              'source':{'selected_comparison':rds_name+'!L'+str(identity) if selected else None,
                        'mapping_rule':'explicit_formula_chain' if selected else 'unique_full_number_corpus_exact_work_title',
                        'rds_quantity':rds_name+'!D'+str(identity),
                        'comparison_basis':rds_name+'!'+rds[1]+str(identity) if selected else None,
                        'natural_plan_basis':'RDS quantity × explicit GPR physical-profile fraction; no money-to-quantity conversion',
                        'physical_plan':comparison_name+'!C'+str(number) if selected else None,
                        'gpr_fraction':gpr_name+'!L'+str(row),
                        'gpr_start':gpr_name+'!E'+str(row),'gpr_finish':gpr_name+'!F'+str(row)},
              'initial_fraction':values[gpr_name].cell(row,12).value}
    return result,values[gpr_name]['B2'].value

def prepare(source, sheet_name, output):
    source,output = Path(source),Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Выберите отдельный выходной файл; исходник сохраняется.')
    book = load_workbook(source);values = load_workbook(source,data_only=True)
    sheet = values[sheet_name]
    if not (str(sheet['A6'].value or '').startswith('№') and str(sheet['C6'].value or '').startswith('Ед.') and
            str(sheet['D6'].value or '').startswith('Кол-во') and 'Всего стоимость' in str(sheet['J6'].value or '')):
        raise ValueError('Не подтверждён явный формат РДС A:J; сопоставление по положению запрещено.')
    plans,cut=linked_physical_plans(book,values,sheet_name)
    rows,headings = [],[]
    for row in sheet.iter_rows(min_row=8):
        i=row[0].row;number,name,unit,quantity= [sheet.cell(i,c).value for c in (1,2,3,4)]
        cost=sheet.cell(i,10).value
        if str(name or '').startswith('ВСЕГО по РДС'):
            break
        if not number and str(name or '').startswith('Корпус'):
            headings.append({'name':name,'before_position':len(rows)})
        if number is not None and not isinstance(cost,(int,float)) and name:
            headings.append({'number':str(number),'name':name,'before_position':len(rows)})
        if number is not None and isinstance(quantity,(int,float)) and isinstance(cost,(int,float)):
            rows.append({'number':str(number),'name':name,'unit':unit,'contract_quantity':quantity,
                         'estimate':0,'index':i,'source_row':i,'amount':cost,'builder_plan':plans.get(i)})
    if not rows:
        raise ValueError('Нет позиций РДС с подтверждёнными количествами и стоимостью.')
    write_builder_template(book,{'rows':rows,'headings':headings,'estimate_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'cut':cut})
    target=book[sheet_name]
    for row in sheet.iter_rows(min_row=8):
        i=row[0].row;number,name=sheet.cell(i,1).value,sheet.cell(i,2).value
        if not name:
            continue
        corpus=not number and str(name).startswith('Корпус')
        total=not number and (str(name).startswith('По разделу') or str(name).startswith('ВСЕГО'))
        if corpus or total or number is not None:
            style_row(target,i,number,corpus=corpus,total=total)
    for page in book:
        page.freeze_panes=None
    evaluator=BuilderEvaluator(book)
    builder=book['Физфакт строителей']
    for cells in builder.iter_rows(min_row=4):
        if cells[3].value!='Монтаж':continue
        original=plans.get(int(str(cells[19].value).split(':')[-1]))
        if original:
            assert math.isclose(evaluator.cell(builder.title,'K'+str(cells[0].row)),original['initial_fraction'],abs_tol=1e-9)
    book.save(output)
    output.write_bytes(cache_builder_formulas(output.read_bytes(),book))
    saved=load_workbook(output,data_only=False)
    for page in values:
        old=book[page.title]
        def comparable(value):
            return vars(value) if hasattr(value,'text') and hasattr(value,'ref') else value
        for cells in old:
            for cell in cells:
                a,b=comparable(cell.value),comparable(saved[page.title][cell.coordinate].value)
                assert a == b or type(a) in (int,float) and type(b) in (int,float) and math.isclose(a,b,rel_tol=1e-15,abs_tol=1e-15), cell.coordinate
    retain_formula_caches(source,output)
    cached=load_workbook(output,data_only=True)
    for page in values:
        assert [[c.value for c in row] for row in page] == [[c.value for c in row] for row in cached[page.title]]
    return {'positions':len(rows),'automatically_planned':sum(bool(row.get('builder_plan')) for row in rows),'source_total':sum(r['amount'] for r in rows),'output':str(output)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('--sheet',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(prepare(args.source,args.sheet,args.output))
