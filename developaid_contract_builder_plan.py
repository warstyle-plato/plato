"""Automatic, source-bound physical plan formulas for builder entry sheets."""
from __future__ import annotations
import datetime as dt
import io
import math
import posixpath
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET
from openpyxl.formula import Tokenizer
from xlsx_eval import Evaluator, _as_date, _as_number



class BuilderEvaluator(Evaluator):
    """Additional date predicates only for this sheet; financial evaluator unchanged."""
    def _call(self,name):
        if name not in ('ISNUMBER','DATE','EOMONTH'):
            return super()._call(name)
        self._expect('(');args=[]
        if self._peek()!=('op',')'):
            while True:
                args.append(self._expression())
                if self._peek()!=('op',','):break
                self._take()
        self._expect(')')
        if name=='ISNUMBER':return type(args[0]) in (int,float)
        if name=='DATE':
            year,month,number=map(lambda x:int(_as_number(x)),args)
            year+=(month-1)//12;month=(month-1)%12+1
            return dt.date(year,month,1)+dt.timedelta(days=number-1)
        current=_as_date(args[0]);month=current.month+int(_as_number(args[1]))
        year=current.year+month//12;month=month%12+1
        return dt.date(year,month,1)-dt.timedelta(days=1)

def date(value):
    if isinstance(value, dt.datetime):return value.date()
    if isinstance(value, dt.date):return value
    try:return dt.date.fromisoformat(value)
    except (TypeError,ValueError):return None


def plan_spec(row, comparison, schedule):
    if row.get('builder_plan'):
        return row['builder_plan']
    binding=(row.get('physical_audit') or {}).get('gpr_binding') or {}
    if binding.get('status') not in ('confirmed','proposed'):
        return None
    by_code={}
    for line in (schedule or {}).get('lines') or []:
        by_code.setdefault(line.get('code'),[]).append(line)
    targets=binding.get('lines') or []
    if not targets or not math.isclose(sum(t.get('share',0) for t in targets),1,abs_tol=1e-9):return None
    groups=[];begin=date(comparison.get('remaining_start'))
    for target in targets:
        candidates=by_code.get(target.get('code')) or []
        if len(candidates)!=1:return None
        line=candidates[0]
        parts=line.get('segments') or [{'start':line.get('start'),'finish':line.get('finish')}]
        if any(not date(p.get('start')) or not date(p.get('finish')) for p in parts):return None
        intervals=[(date(p['start']),date(p['finish'])) for p in parts]
        if begin and begin>max(end for start,end in intervals):
            intervals=[(begin,begin)]
        elif begin:
            intervals=[(max(start,begin),end) for start,end in intervals if end>=begin]
        if not intervals or any(end<start for start,end in intervals):return None
        groups.append({'share':target['share'],'intervals':[(a.isoformat(),b.isoformat()) for a,b in intervals]})
    return {'groups':groups,'start':min(a for g in groups for a,b in g['intervals']),
            'finish':max(b for g in groups for a,b in g['intervals']),
            'method':'Равномерный физический план по активным интервалам принятого ГПР; реальные разрывы исключены.',
            'source':{'binding':binding,'schedule_source':'accepted_contract_gpr'}}


def fraction_formula(spec, excel_row):
    at=f'IF(I{excel_row}="",$I$1,I{excel_row})'
    if spec.get('source_formula'):
        source_row=spec['source_row']
        references={'$B$2':at, f'$E{source_row}':f'$G{excel_row}',f'$F{source_row}':f'$H{excel_row}',
                    f'$K{source_row}':f'((YEAR($H{excel_row})-YEAR($G{excel_row}))*12+MONTH($H{excel_row})-MONTH($G{excel_row})+1)'}
        parts=[]
        for token in Tokenizer(spec['source_formula']).items:
            if token.type=='OPERAND' and token.subtype=='RANGE':
                if token.value not in references:raise ValueError('Не распознана ссылка физического плана: '+token.value)
                parts.append(references[token.value])
            else:parts.append(token.value)
        return '='+''.join(parts)
    def excel_day(value):
        at=date(value);return f'DATE({at.year},{at.month},{at.day})'
    terms=[]
    for group in spec['groups']:
        total=sum((date(end)-date(start)).days+1 for start,end in group['intervals'])
        elapsed='+'.join(f'MAX(0,MIN({at},{excel_day(end)})-{excel_day(start)}+1)' for start,end in group['intervals'])
        terms.append(f'{group["share"]}*MIN(1,({elapsed})/{total})')
    return '='+ '+'.join(terms)


def cache_builder_formulas(payload, book):
    """Compute only trusted builder formulas; keep caches visible on mobile."""
    names=[name for name in ('Физфакт строителей','Выполнение','РДС — план и факт','Численность') if name in book]
    evaluator=BuilderEvaluator(book)
    values={name:{c.coordinate:evaluator.cell(name,c.coordinate) for row in book[name] for c in row if c.data_type=='f'} for name in names}
    main='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    rel='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
    buffer=io.BytesIO()
    with ZipFile(io.BytesIO(payload)) as before,ZipFile(buffer,'w',ZIP_DEFLATED) as after:
        roots=ET.fromstring(before.read('xl/workbook.xml'))
        targets={x.get('Id'):x.get('Target') for x in ET.fromstring(before.read('xl/_rels/workbook.xml.rels'))}
        paths={}
        for sheet in roots.iter(main+'sheet'):
            name=sheet.get('name')
            if name not in values:continue
            target=targets[sheet.get(rel+'id')]
            path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
            paths[path]=values[name]
        for member in before.infolist():
            raw=before.read(member.filename)
            if member.filename in paths:
                cached_values=paths[member.filename]
                root=ET.fromstring(raw)
                for cell in root.iter(main+'c'):
                    if cell.get('r') not in cached_values:continue
                    value=cached_values[cell.get('r')]
                    old=cell.find(main+'v')
                    if old is not None:cell.remove(old)
                    cached=ET.SubElement(cell,main+'v')
                    if type(value) in (int,float):
                        cell.attrib.pop('t',None);cached.text=repr(value)
                    elif value in ('',None):
                        cell.set('t','str');cached.text=''
                    else:raise ValueError('Не подтверждён числовой результат формулы.')
                raw=ET.tostring(root,encoding='utf-8',xml_declaration=True)
            after.writestr(member,raw)
    return buffer.getvalue()
