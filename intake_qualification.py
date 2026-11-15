"""Closed, signed document qualifications; never a money input or authority grant."""
from __future__ import annotations
import copy
import hashlib
import hmac
import json
import re

KEY = '_intake_qualification'
PACKET = '_tep_source_packet'
DOMAIN = b'plato/document-qualification/v1\0'
MAX_BYTES = 14000
MAX_ITEMS = 24
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_FIELDS = {'schema','key_scope','owner','intake_id','revision','queue_sha256','source',
           'binding','overrides_sha256','status','obligations','signature','recipient'}
_ITEM_FIELDS = {'index','question','quote','route','status'}


class QualificationError(ValueError):
    """A closed, safe explanation for an overlarge source qualification."""
    pass


def _raw(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise QualificationError('Квалификация документа слишком велика. Уточните обязательства в карточке.')
    return data


def _text(value, limit):
    text = ' '.join(str(value or '').split())
    if not text or len(text) > limit or any(ord(ch)<32 for ch in text):
        raise QualificationError('Описание обязательства требует повторной проверки карточки.')
    return text


def obligations(queue):
    """Durable unresolved valuations, including later unpriced cards after stop."""
    answers = {a.get('index'):a for a in queue.get('answers') or [] if type(a.get('index')) is int}
    out = []
    for index, card in enumerate(queue.get('cards') or []):
        answer = answers.get(index)
        options = card.get('options') or []
        missing = bool(card.get('adds') and any(o.get('target') and o.get('value') is None for o in options))
        unresolved = bool(answer and (answer.get('deferred') or answer.get('pending_proposal')))
        if not unresolved and not (missing and (not answer or answer.get('action') != 'answer')):
            continue
        choice = (answer or {}).get('choice')
        option = options[choice] if type(choice) is int and 0 <= choice < len(options) else None
        route = _text(option.get('label'), 200) if option else ''
        out.append({'index':index, 'question':_text(card.get('question') or 'Обязательство из документа', 500),
            'quote':_text(card.get('quote') or card.get('question') or 'Обязательство из документа', 500),
            'route':route, 'status':'valuation_missing' if route else 'route_unconfirmed'})
    if len(out) > MAX_ITEMS:
        raise QualificationError('Слишком много неуточнённых обязательств. Уточните их в карточке.')
    _raw(out)
    return out


def item_reason(item):
    source = item['quote'] if item['quote'] != item['question'] else item['question']
    route = ('Способ учёта: '+item['route']+'.') if item['route'] else 'Способ учёта ещё не подтверждён.'
    return ('Стоимость обязательства «'+source+'» не определена и в денежный расчёт не включена. '+route)


def issue(queue, *, owner, recipient, queue_sha256, source, binding, overrides_sha256, key_scope, key):
    items = obligations(queue)
    body = {'schema':1, 'key_scope':key_scope, 'owner':owner, 'intake_id':queue['id'],
        'revision':queue.get('revision',0), 'queue_sha256':queue_sha256, 'source':source, 'recipient':recipient,
        'binding':binding, 'overrides_sha256':overrides_sha256,
        'status':'conditional' if items else 'verified_empty', 'obligations':items}
    record = {**body, 'signature':hmac.new(key, DOMAIN+_raw(body), hashlib.sha256).hexdigest()}
    if validate(record, key) is None:
        raise QualificationError('Квалификация документа не подтверждена.')
    return record


def validate(record, key):
    try:
        if not isinstance(record,dict) or set(record) != _FIELDS or type(record['schema']) is not int or record['schema'] != 1:
            return None
        if record['key_scope'] not in {'telegram','stage'} or not re.fullmatch(r'[0-9a-f]{32}',record['intake_id']):return None
        if type(record['revision']) is not int or record['revision'] < 0:return None
        if record['recipient'] is not None and (not isinstance(record['recipient'],str) or not _HEX.fullmatch(record['recipient'])):return None
        for field in ['owner','queue_sha256','binding','overrides_sha256','signature']:
            if not isinstance(record[field],str) or not _HEX.fullmatch(record[field]):return None
        source = record['source']
        if not isinstance(source,dict) or set(source) != {'kind','sha256'} or source['kind'] not in {'file','queue'} or not _HEX.fullmatch(source['sha256']):return None
        items = record['obligations']
        if not isinstance(items,list) or len(items)>MAX_ITEMS or record['status'] != ('conditional' if items else 'verified_empty'):return None
        seen=set()
        for item in items:
            if not isinstance(item,dict) or set(item)!=_ITEM_FIELDS:return None
            if type(item['index']) is not int or item['index']<0 or item['index'] in seen:return None
            seen.add(item['index'])
            if item['status'] not in {'valuation_missing','route_unconfirmed'}:return None
            for field,limit in [('question',500),('quote',500)]:
                if not isinstance(item[field],str) or _text(item[field],limit)!=item[field]:return None
            if not isinstance(item['route'],str) or len(item['route'])>200:return None
            if bool(item['route']) != (item['status']=='valuation_missing'):return None
        body={k:v for k,v in record.items()if k!='signature'}
        expected=hmac.new(key,DOMAIN+_raw(body),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(record['signature'],expected):return None
        _raw(record)
        return copy.deepcopy(record)
    except (ValueError,TypeError,KeyError,OverflowError):
        return None


def document_context(inputs):
    packet=inputs.get(PACKET) or {}
    if isinstance(packet,dict) and packet.get('kind')=='teaser_card':return True
    origins=inputs.get('_field_origin') or {}
    return isinstance(origins,dict) and any(isinstance(o,dict) and o.get('source')=='document'for o in origins.values())


def state(inputs, key_for):
    record=inputs.get(KEY)
    if record is None and KEY not in inputs and not document_context(inputs):return None
    valid=None
    if (isinstance(record,dict) and isinstance(record.get('key_scope'),str)
            and record['key_scope'] in {'telegram','stage'}):
        try:valid=validate(record,key_for(record['key_scope']))
        except (ValueError,RuntimeError,OSError):pass
    packet=inputs.get(PACKET)
    if valid and isinstance(packet,dict) and packet.get('intake_id') != valid['intake_id']:valid=None
    if valid:
        reason=('Предварительный расчёт. '+' '.join(item_reason(x)for x in valid['obligations'])) if valid['obligations'] else ''
        return {'status':valid['status'],'verified':True,'obligations':valid['obligations'],'reason':reason}
    return {'status':'review_required','verified':False,'obligations':[],
        'reason':'Предварительный расчёт: условия учёта обязательств из документа не подтверждены. '
                 'Вернитесь к карточке документа; отсутствие оценки не означает нулевую стоимость.'}


def apply(inputs, result, key_for):
    qualification=state(inputs,key_for)
    if qualification is None or not isinstance(result,dict):return result
    summary=result.setdefault('summary',{})
    summary['intake_qualification']=qualification
    if qualification['reason']:
        reason=str(summary.get('preliminary_reason') or '').strip()
        summary['preliminary']=True
        if qualification['reason'] not in reason:
            summary['preliminary_reason']=' '.join(x for x in [reason,qualification['reason']]if x)
    return result


def qualified_workbook(content, qualification):
    """Add a first disclosure sheet without rewriting any original sheet/cache."""
    import io
    import zipfile
    from xml.etree import ElementTree as ET
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    pkg='http://schemas.openxmlformats.org/package/2006/relationships'
    ct='http://schemas.openxmlformats.org/package/2006/content-types'
    tag=lambda name:'{'+ns+'}'+name
    if not qualification.get('reason'):
        return content
    target_base='xl/worksheets/intake_qualification'
    marker='PlatoIntakeQualification'
    with zipfile.ZipFile(io.BytesIO(content))as original:
        import posixpath
        workbook=ET.fromstring(original.read('xl/workbook.xml'))
        relationships=ET.fromstring(original.read('xl/_rels/workbook.xml.rels'))
        types=ET.fromstring(original.read('[Content_Types].xml'))
        styles=ET.fromstring(original.read('xl/styles.xml'))
        sheets=workbook.find(tag('sheets'))
        old_order=list(sheets)
        existing=None
        target=target_base+'.xml'
        by_id={node.get('Id'):node for node in relationships}
        for candidate in old_order:
            relationship=by_id.get(candidate.get('{'+rel+'}id'))
            if relationship is None or relationship.get('TargetMode')=='External':continue
            named=relationship.get('Target','')
            name=posixpath.normpath(named.lstrip('/')if named.startswith('/')else posixpath.join('xl',named))
            if name.startswith(target_base)and name in original.namelist():
                prior_sheet=ET.fromstring(original.read(name))
                properties=prior_sheet.find(tag('sheetPr'))
                if properties is not None and properties.get('codeName')==marker:
                    existing=candidate;target=name;break
        if existing is None:
            index=1
            while target in original.namelist():
                target=target_base+'_'+str(index)+'.xml';index+=1
            names={sheet.get('name')for sheet in sheets}
            title='Условия расчёта';index=2
            while title in names:
                title='Условия расчёта ('+str(index)+')';index+=1
            ids={r.get('Id')for r in relationships}
            rid='rIdIntakeQualification'
            while rid in ids:rid+='x'
            sheet_id=max(int(sheet.get('sheetId'))for sheet in sheets)+1
            existing=ET.Element(tag('sheet'),{'name':title,'sheetId':str(sheet_id),'{'+rel+'}id':rid})
            ET.SubElement(relationships,'{'+pkg+'}Relationship',{'Id':rid,'Type':rel+'/worksheet','Target':'/'+target})
            ET.SubElement(types,'{'+ct+'}Override',{'PartName':'/'+target,'ContentType':'application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'})
        else:
            sheets.remove(existing)
        sheets.insert(0,existing)
        new_order=list(sheets)
        # Local names (including print areas/titles) bind by sheet INDEX,
        # while formula references and relationship IDs bind by stable names.
        for node in workbook.iter(tag('definedName')):
            if 'localSheetId'in node.attrib:
                prior_index=int(node.get('localSheetId'))
                node.set('localSheetId',str(new_order.index(old_order[prior_index])))
        for view in workbook.iter(tag('workbookView')):
            view.set('activeTab','0');view.set('firstSheet','0')
        fonts=styles.find(tag('fonts'));font_id=len(fonts)
        font=ET.SubElement(fonts,tag('font'))
        ET.SubElement(font,tag('b'));ET.SubElement(font,tag('sz'),{'val':'14'})
        ET.SubElement(font,tag('color'),{'rgb':'FF8A4B08'});ET.SubElement(font,tag('name'),{'val':'Calibri'})
        fonts.set('count',str(len(fonts)))
        xfs=styles.find(tag('cellXfs'));body_style=len(xfs)
        for font_number in (0,font_id):
            xf=ET.SubElement(xfs,tag('xf'),{'numFmtId':'0','fontId':str(font_number),'fillId':'0','borderId':'0','xfId':'0','applyAlignment':'1'})
            ET.SubElement(xf,tag('alignment'),{'wrapText':'1','vertical':'top'})
        xfs.set('count',str(len(xfs)))
        sheet=ET.Element(tag('worksheet'))
        properties=ET.SubElement(sheet,tag('sheetPr'),{'codeName':marker});ET.SubElement(properties,tag('pageSetUpPr'),{'fitToPage':'1'})
        views=ET.SubElement(sheet,tag('sheetViews'));view=ET.SubElement(views,tag('sheetView'),{'workbookViewId':'0'})
        ET.SubElement(view,tag('pane'),{'ySplit':'2','topLeftCell':'A3','activePane':'bottomLeft','state':'frozen'})
        ET.SubElement(sheet,tag('sheetFormatPr'),{'defaultRowHeight':'15'})
        cols=ET.SubElement(sheet,tag('cols'));ET.SubElement(cols,tag('col'),{'min':'1','max':'1','width':'112','customWidth':'1'})
        data=ET.SubElement(sheet,tag('sheetData'))
        lines=['Предварительный расчёт по известным затратам']
        if qualification['obligations']:
            lines+=['Оценки перечисленных обязательств не подтверждены. Эти расходы не добавлены в денежный расчёт.']
            lines += [item_reason(item)for item in qualification['obligations']]
        else:lines += [qualification['reason']]
        for number,text in enumerate(lines,1):
            row=ET.SubElement(data,tag('row'),{'r':str(number),'ht':str(36 if number==1 else max(45,min(400,(len(text)//90+1)*16))),'customHeight':'1'})
            cell=ET.SubElement(row,tag('c'),{'r':'A'+str(number),'s':str(body_style+(1 if number==1 else 0)),'t':'inlineStr'})
            ET.SubElement(ET.SubElement(cell,tag('is')),tag('t')).text=text
        ET.SubElement(sheet,tag('pageMargins'),{'left':'0.4','right':'0.4','top':'0.5','bottom':'0.5','header':'0.2','footer':'0.2'})
        ET.SubElement(sheet,tag('pageSetup'),{'paperSize':'9','orientation':'portrait','fitToWidth':'1','fitToHeight':'0'})
        replacements={'xl/workbook.xml':workbook,'xl/_rels/workbook.xml.rels':relationships,'[Content_Types].xml':types,'xl/styles.xml':styles,target:sheet}
        encoded={name:ET.tostring(node,encoding='utf-8',xml_declaration=True)for name,node in replacements.items()}
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED)as result:
            for info in original.infolist():
                result.writestr(info,encoded.pop(info.filename,original.read(info.filename)))
            for name,raw in encoded.items():result.writestr(name,raw)
        return output.getvalue()
