"""Actual model, Telegram card/edit URL, full PDF, teaser and cached workbook."""
import copy
import io
from urllib.parse import parse_qs
import zipfile

from openpyxl import load_workbook
from pypdf import PdfReader
import pytest

from test_document_qualification import core, document, qual, CHAT


def model(item):
    return core._run_authoritative_model(item['inputs'],item['tep'],[],{})


def text_pdf(content):return '\n'.join(page.extract_text()or''for page in PdfReader(io.BytesIO(content)).pages)


def test_actual_telegram_result_and_edit_handoff_keep_specific_excluded_cost(document,monkeypatch):
    item=document();bundle=model(item);result=bundle['consolidated'];sent=[];attachments=[]
    monkeypatch.setattr(core,'_telegram_api',lambda method,payload=None,**kw:sent.append((method,payload))or{})
    monkeypatch.setattr(core,'_telegram_send_attachments',lambda *a,**k:attachments.append((a,k)))
    summary={'project_name':'Synthetic qualified model','purchase_price_mln':73.5,
        'revenue_mln':result['summary']['revenue']/1e6,'net_profit_mln':result['summary']['net_profit']/1e6,
        'llcr':result['summary']['llcr'],'layout':result['report'].get('layout')or{},
        # Deliberately omit all client qualification text and metadata. The
        # already-signed source session must retain its record by itself.
        'report_payload':{'inputs':{k:v for k,v in item['inputs'].items()if k not in {qual.KEY,qual.PACKET}},
                          'tep':item['tep'],'rates':[],'phasing':{},'result':result}}
    assert core.telegram_result(core.TelegramResultRequest(session=item['token'],summary=summary))=={'ok':True}
    messages=[payload for method,payload in sent if method=='sendMessage']
    text=''.join(p['text']for p in messages)
    assert '275 м²'in text and 'не включена'in text
    assert 'HMAC'not in text and 'SHA'not in text and item['record']['signature']not in text
    url=messages[-1]['reply_markup']['inline_keyboard'][0][0]['web_app']['url']
    token=parse_qs(url.split('#',1)[1])['telegram_session'][0]
    opened=core.telegram_session_data(core.TelegramSessionRequest(session=token))
    assert opened['overrides_review_required']is False and opened['calc_overrides'][qual.KEY]==item['record']
    assert attachments and attachments[0][0][1]['inputs'][qual.KEY]==item['record']


def test_native_full_pdf_and_two_page_teaser_both_name_the_unpriced_obligation(document):
    item=document();bundle=model(item);result=bundle['consolidated']
    # The direct rendering adapter also reads the validated input record,
    # so client omission of preliminary prose cannot remove the disclosure.
    result=copy.deepcopy(result);result['summary']['preliminary_reason']=''
    payload={'inputs':item['inputs'],'tep':item['tep'],'rates':[],'phasing':{},'result':result,
        'project_name':'Synthetic qualified source'}
    full=core._build_developaid_pdf(payload)
    text=text_pdf(full)
    assert '275 м²'in text and 'не включена'in text
    assert item['record']['signature']not in text and 'HMAC'not in text
    teaser=core.build_teaser_pdf(bundle,item['inputs'],item['tep'],{},site={})
    assert len(PdfReader(io.BytesIO(teaser)).pages)==2
    teaser_text=text_pdf(teaser)
    assert '275 м²'in teaser_text and 'не включена'in teaser_text


def test_actual_workbook_disclosure_preserves_original_sheets_formulas_and_cached_values(document,monkeypatch):
    class FixedDateTime(core.datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,11,15,12,0,tzinfo=tz)
    monkeypatch.setattr(core,'datetime',FixedDateTime)
    item=document();bundle=model(item)
    ordinary={k:v for k,v in item['inputs'].items()if k not in {qual.KEY,qual.PACKET,'_field_origin'}}
    hints=core._v4_finance_hints(bundle)
    raw=core.build_project_workbook(ordinary,item['tep'],[],{},project_name='Synthetic source',finance_hints=hints)
    qualified=core.build_project_workbook(item['inputs'],item['tep'],[],{},project_name='Synthetic source',finance_hints=hints)
    # Every original worksheet remains byte-exact, including formula caches.
    with zipfile.ZipFile(io.BytesIO(raw[0]))as before,zipfile.ZipFile(io.BytesIO(qualified[0]))as after:
        original_sheets=[name for name in before.namelist()if name.startswith('xl/worksheets/')]
        assert original_sheets
        for name in original_sheets:assert after.read(name)==before.read(name),name
    book=load_workbook(io.BytesIO(qualified[0]),data_only=False)
    assert book.sheetnames[0]=='Условия расчёта'and book.active.title=='Условия расчёта'
    notice=' '.join(str(cell.value or '')for row in book.active for cell in row)
    assert '275 м²'in notice and 'не включена'in notice
    assert 'HMAC'not in notice and 'SHA'not in notice and item['record']['signature']not in notice
    assert qualified[2]['preliminary']is True
    assert qualified[2]['intake_qualification']['status']=='conditional'
    assert '275 м²'in qualified[2]['preliminary_reason']


def test_overlay_keeps_local_names_print_ranges_relationships_and_selection_after_save(document):
    from openpyxl import Workbook
    from openpyxl.workbook.defined_name import DefinedName
    from xml.etree import ElementTree as ET
    item=document();state=core._intake_qualification_state(item['inputs'])
    book=Workbook();book.active.title="Finance O'Brien"
    book.create_sheet('Условия расчёта');book.create_sheet('Cash flows')
    for index,sheet in enumerate(book):
        sheet['A1']=index+1;sheet['B2']='=SUM(A1:A1)'
        sheet.print_area='A1:C7';sheet.print_title_rows='1:2'
        sheet.defined_names.add(DefinedName('LocalMetric',localSheetId=index,
            attr_text="'"+sheet.title.replace("'","''")+"'!$B$2"))
    book.active=2;book.views[0].firstSheet=1
    baseline=io.BytesIO();book.save(baseline)
    # Exercise reserved rID and part-name collisions; neither may overwrite
    # an existing member or create duplicate relationship/sheet IDs.
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel='http://schemas.openxmlformats.org/package/2006/relationships'
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(baseline.getvalue()))as source,zipfile.ZipFile(output,'w')as archive:
        for info in source.infolist():
            raw=source.read(info.filename)
            if info.filename=='xl/_rels/workbook.xml.rels':
                relationships=ET.fromstring(raw)
                ET.SubElement(relationships,'{'+rel+'}Relationship',{
                    'Id':'rIdIntakeQualification','Type':'http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme','Target':'theme/theme1.xml'})
                raw=ET.tostring(relationships)
            archive.writestr(info,raw)
        archive.writestr('xl/worksheets/intake_qualification.xml','<worksheet xmlns="'+ns+'"><sheetData/></worksheet>')
    original=output.getvalue()
    amended=qual.qualified_workbook(original,state)
    parsed=load_workbook(io.BytesIO(amended),data_only=False)
    assert parsed.sheetnames[0]=='Условия расчёта (2)'
    assert parsed.active.title=='Условия расчёта (2)'and parsed.views[0].firstSheet==0
    for sheet in book:
        assert str(parsed[sheet.title].print_area)==str(sheet.print_area)
        assert parsed[sheet.title].print_title_rows==sheet.print_title_rows
        assert parsed[sheet.title]['B2'].value=='=SUM(A1:A1)'
    with zipfile.ZipFile(io.BytesIO(amended))as archive:
        tree=ET.fromstring(archive.read('xl/workbook.xml'))
        sheets=tree.find('{'+ns+'}sheets');ids=[node.get('sheetId')for node in sheets]
        assert len(ids)==len(set(ids))
        names=[node for node in tree.iter('{'+ns+'}definedName')if node.get('name')=='LocalMetric']
        assert sorted(int(node.get('localSheetId'))for node in names)==[1,2,3]
        relationships=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        rids=[node.get('Id')for node in relationships]
        assert len(rids)==len(set(rids))
        rid_map={node.get('Id'):node.get('Target')for node in relationships}
        for sheet in sheets:
            rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target=rid_map[rid]
            path=target.lstrip('/')if target.startswith('/')else'xl/'+target
            assert path in archive.namelist()
        assert archive.read('xl/worksheets/intake_qualification.xml')==b'<worksheet xmlns="'+ns.encode()+b'"><sheetData/></worksheet>'
    again=qual.qualified_workbook(amended,state)
    restored=load_workbook(io.BytesIO(again));assert restored.sheetnames==parsed.sheetnames
    saved=io.BytesIO();restored.save(saved)
    reopened=load_workbook(io.BytesIO(saved.getvalue()))
    assert reopened.active.title=='Условия расчёта (2)'and reopened.views[0].firstSheet==0
    for sheet in book:
        assert str(reopened[sheet.title].print_area)==str(sheet.print_area)
        assert reopened[sheet.title].print_title_rows==sheet.print_title_rows


def test_explicitly_priced_public_workbook_has_no_conditional_sheet_or_stamp(document):
    item=document(True);bundle=model(item)
    built=core.build_project_workbook(item['inputs'],item['tep'],[],{},
        project_name='Synthetic priced source',finance_hints=core._v4_finance_hints(bundle))
    book=load_workbook(io.BytesIO(built[0]),data_only=False)
    assert not any(name.startswith('Условия расчёта')for name in book.sheetnames)
    assert 'intake_qualification'not in built[2]
    assert qual.qualified_workbook(built[0],core._intake_qualification_state(item['inputs']))==built[0]


def test_telegram_composes_live_rent_and_document_reasons_without_reviving_a_client_date(document,monkeypatch):
    item=document();inputs={**item['inputs'],'land_right':'lease','vri_region':'msk','land_rent_mode':'manual',
        'land_rent_cadastral_mln':100,'land_rent_regime_start':None,'land_rights_cost_mln':0,
        'project_start':'2031-01-01','ird_months':12,'construction_months':12,
        'land_rent_rates':[{'year':1,'rate_pct':1.5}],'land_rent_tail_rule':'repeat_last',
        'land_rent_vat_treatment':'public_exempt','land_rent_termination_date':'2033-01-01',
        'land_rent_cadastral_target_mln':120}
    bundle=core._run_authoritative_model(inputs,item['tep'],[],{});result=bundle['consolidated'];sent=[]
    monkeypatch.setattr(core,'_telegram_send_intake_text',lambda chat,text,**kw:sent.append(text))
    monkeypatch.setattr(core,'_telegram_send_attachments',lambda *a,**kw:None)
    reason=result['summary']['preliminary_reason']
    assert 'аренд'in reason.casefold()and'275 м²'in reason
    core.telegram_result(core.TelegramResultRequest(session=item['token'],summary={
        'preliminary_reason':'Дата аренды подтверждена 01.11.2026',
        'report_payload':{'inputs':inputs,'tep':item['tep'],'result':result}}))
    assert 'аренд'in sent[0].casefold()and'275 м²'in sent[0]
    assert '01.11'not in sent[0]


def test_long_workbook_qualification_fits_a4_without_rewriting_the_model():
    """Disclosure print layout keeps full long obligations and original caches."""
    import textwrap
    from openpyxl import Workbook
    book=Workbook();book.active.title='Модель';book.active['A1']='=1+2'
    source=io.BytesIO();book.save(source)
    obligation={'question':'Обязательство по исходному документу',
                'quote':('Подробное описание исходных данных и неоценённого обязательства. '*7).strip(),
                'route':'Подтвердить стоимость после получения сметы','status':'valuation_missing'}
    state={'reason':'Предварительный расчёт','obligations':[obligation]}
    content=qual.qualified_workbook(source.getvalue(),state)
    result=load_workbook(io.BytesIO(content))
    sheet=result.worksheets[0]
    assert sheet.column_dimensions['A'].width==85
    assert sheet.print_area=="'Условия расчёта'!$A$1:$A$3"
    assert str(sheet.page_setup.paperSize)==str(sheet.PAPERSIZE_A4)
    assert sheet.page_setup.orientation=='portrait'
    assert sheet.page_setup.fitToWidth==1 and sheet.page_setup.fitToHeight==0
    text=qual.item_reason(obligation)
    assert sheet['A3'].value==text and sheet['A3'].alignment.wrap_text
    assert sheet['A3'].alignment.vertical=='top'
    assert sheet.row_dimensions[3].height >= len(textwrap.wrap(text,width=74))*16
    # Adding/formatting the disclosure must not rewrite formulas or cached data.
    with zipfile.ZipFile(io.BytesIO(source.getvalue()))as old,zipfile.ZipFile(io.BytesIO(content))as new:
        assert new.read('xl/worksheets/sheet1.xml')==old.read('xl/worksheets/sheet1.xml')
    again=qual.qualified_workbook(content,state)
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(again))as archive:
        tree=ET.fromstring(archive.read('xl/workbook.xml'))
        areas=[n for n in tree.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}definedName')
               if n.get('name')=='_xlnm.Print_Area'and n.get('localSheetId')=='0']
        assert len(areas)==1
