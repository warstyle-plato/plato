"""Add a builder entry sheet to a supplied RDS workbook; never import it into production.

Usage: python scripts/contract_builder_template.py SOURCE --sheet 'RDS sheet' --output OUTPUT
The source layout must explicitly name quantity, unit and total in A:J. Formula
caches of unchanged source cells are retained for read-only/mobile viewers.
"""
from __future__ import annotations
import argparse
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


def prepare(source, sheet_name, output):
    source,output = Path(source),Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Выберите отдельный выходной файл; исходник сохраняется.')
    book = load_workbook(source);values = load_workbook(source,data_only=True)
    sheet = values[sheet_name]
    if not (str(sheet['A6'].value or '').startswith('№') and str(sheet['C6'].value or '').startswith('Ед.') and
            str(sheet['D6'].value or '').startswith('Кол-во') and 'Всего стоимость' in str(sheet['J6'].value or '')):
        raise ValueError('Не подтверждён явный формат РДС A:J; сопоставление по положению запрещено.')
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
                         'estimate':0,'index':i,'source_row':i,'amount':cost})
    if not rows:
        raise ValueError('Нет позиций РДС с подтверждёнными количествами и стоимостью.')
    write_builder_template(book,{'rows':rows,'headings':headings,'estimate_sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
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
    book.save(output)
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
    return {'positions':len(rows),'source_total':sum(r['amount'] for r in rows),'output':str(output)}


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('--sheet',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(prepare(args.source,args.sheet,args.output))
