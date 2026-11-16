"""One fixed-purpose review reads retained KS bytes, not just a filtered report."""
from __future__ import annotations

import copy
import datetime as dt
import io

import openpyxl
import pytest

import developaid_contract_source_review as review
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import archive, ks
from test_monitor_cumulative_api import api, post, poll, KEY  # noqa: F401

TODAY=dt.date.today().isoformat()


def source_book(number='A-12'):
    wb=openpyxl.load_workbook(io.BytesIO(ks(number=number)))
    ws=wb.active
    ws['H7'],ws['K7']='КС2-1','КС2-2'
    # A source date outside the recognised period label is still inspectable.
    ws['H5']=dt.date(2026,1,31)
    out=io.BytesIO();wb.save(out);return out.getvalue()


def saved():
    snapshot=ledgers.store_archive('Fixture',archive([('KS.xlsx',source_book())]),
        (dt.date.today()-dt.timedelta(days=2)).isoformat(),'KS.zip')
    register=contracts.build('Fixture',TODAY,include_history=False)
    return snapshot,register['rows'][0]


def test_native_projection_is_private_source_bound_and_does_not_modify_the_sources(api):
    client,_=api
    _,row=saved()
    before={p:p.read_bytes() for p in ledgers._root('Fixture').iterdir() if p.is_file()}
    response=post(client,'contracts/source-review',project='Fixture',cut=TODAY,contract_id=row['id'])
    assert response.status_code in (200,202) and response.headers['cache-control']=='private, no-store'
    result=response if response.status_code==200 else poll(client,response.json()['ticket'])
    assert result.json()['ok'] is True
    data=result.json()['source_review']
    assert data['state']=='read' and data['source_count']==1
    source,=data['sources']
    assert source['archive_sha256']==source['snapshot_id'][11:]
    assert len(source['file_sha256'])==64 and source['source']['filename']=='KS.xlsx'
    cells={c['cell']:c for c in source['header_cells']}
    assert cells['B3']['value']=='A-12'
    assert cells['H7']['value']=='КС2-1' and cells['H5']['value'].startswith('2026-01-31')
    periods=[p for item in source['items'] for p in item['periods']]
    assert any(p['label']=='КС2-1' and p['quantity'] is not None for p in periods)
    assert all(p['date_end'] is None for p in periods)
    assert all(path.read_bytes()==value for path,value in before.items())
    assert 'content_base64' not in str(data) and 'raw_zip' not in data


def test_previous_retained_archives_are_read_as_separate_source_versions(api):
    _,row=saved()
    later=source_book()
    # A later saved version does not erase the earlier proof.
    ledgers.store_archive('Fixture',archive([('KS.xlsx',later)]),
                         (dt.date.today()-dt.timedelta(days=1)).isoformat(),'KS-later.zip')
    data=review.review('Fixture',row['id'],TODAY)
    assert len(data['sources'])==2
    assert len({s['snapshot_id'] for s in data['sources']})==2


def test_a_missing_original_is_unknown_not_proof_of_missing_dates(api):
    _,row=saved()
    next(ledgers._root('Fixture').glob('*.zip')).unlink()
    data=review.review('Fixture',row['id'],TODAY)
    assert data['state']=='incomplete' and data['source_count']==0
    assert data['unavailable_originals'] and 'даты не объявлены отсутствующими' in data['unavailable_originals'][0]['reason']


def test_source_sha_drift_is_a_failure_not_cached_old_success(api):
    _,row=saved()
    next(ledgers._root('Fixture').glob('*.zip')).write_bytes(b'changed')
    with pytest.raises(review.SourceReviewProblem,match='SHA'):
        review.review('Fixture',row['id'],TODAY)


def test_source_changing_during_the_read_is_rejected(api,monkeypatch):
    _,row=saved()
    raw=ledgers._read_workbook
    def changed(*args,**kwargs):
        values=raw(*args,**kwargs)
        next(ledgers._root('Fixture').glob('*.zip')).write_bytes(b'changed')
        return values
    monkeypatch.setattr(ledgers,'_read_workbook',changed)
    with pytest.raises(review.SourceReviewProblem,match='SHA'):
        review.review('Fixture',row['id'],TODAY)


def test_a_reissued_contract_of_another_date_is_not_joined_as_this_cards_fact(api,monkeypatch):
    _,row=saved()
    parse=ledgers.parse_archive
    def changed(raw):
        value=copy.deepcopy(parse(raw));value['ledgers'][0]['contract_date']='2026-01-02';return value
    monkeypatch.setattr(ledgers,'parse_archive',changed)
    data=review.review('Fixture',row['id'],TODAY)
    assert data['state']=='incomplete' and not data['sources']
    assert data['identity_exclusions'] and 'не присоединены' in data['identity_exclusions'][0]['reason']


@pytest.mark.parametrize('extra',[{'path':'/etc/passwd'},{'sheet':'Other'},{'range':'A1:ZZ99999'},
                                 {'url':'https://example.invalid/'}])
def test_the_endpoint_never_accepts_caller_source_selectors(api,extra):
    client,_=api;_,row=saved()
    response=client.post('/monitor/contracts/source-review',json={
        'key':KEY,'project':'Fixture','cut':TODAY,'contract_id':row['id'],**extra})
    assert response.status_code==422 and response.headers['cache-control']=='private, no-store'


def test_denied_access_never_opens_an_archive(api,monkeypatch):
    client,_=api;calls=[]
    monkeypatch.setattr(review,'_original',lambda *args:calls.append(args))
    response=post(client,'contracts/source-review',project='Fixture',cut=TODAY,contract_id='a'*64,key='wrong')
    assert response.status_code==403 and calls==[]


def test_summary_header_projection_excludes_neighbouring_contract_sections():
    own={'document_form':'closing_summary','source':{'filename':'Summary.xlsx','sheet':'KS','row':20}}
    siblings=[{'source':{**own['source'],'row':10}},own,{'source':{**own['source'],'row':30}}]
    rows=[['Номер акта']]+[[''] for _ in range(8)]+[['OTHER CONTRACT']]+[[''] for _ in range(9)]+[
          ['OWN CONTRACT']]+[[''] for _ in range(9)]+[['NEXT CONTRACT']]
    got=review._headers(own,rows,siblings)
    values=[c['value'] for c in got['cells']]
    assert 'OWN CONTRACT' in values and 'Номер акта' in values
    assert 'OTHER CONTRACT' not in values and 'NEXT CONTRACT' not in values


def test_the_last_contract_ends_at_its_printed_total_not_the_projects_grand_total():
    own={'document_form':'closing_summary','source':{'filename':'Summary.xlsx','sheet':'KS','row':10},
         'reported_total':{'source':{'row':12}}}
    rows=[['column labels']]+[[''] for _ in range(8)]+[['OWN CONTRACT'],['own act'],['own total'],['PROJECT TOTAL']]
    got=review._headers(own,rows,[own])
    values=[c['value'] for c in got['cells']]
    assert 'OWN CONTRACT' in values and 'own total' in values and 'PROJECT TOTAL' not in values


def test_unknown_last_section_end_is_not_guessed_from_the_rest_of_the_sheet():
    own={'document_form':'closing_summary','source':{'filename':'Summary.xlsx','sheet':'KS','row':10}}
    rows=[['column labels']]+[[''] for _ in range(8)]+[['OWN CONTRACT'],['UNKNOWN CONTINUATION']]
    got=review._headers(own,rows,[own])
    assert got['truncated']
    assert 'UNKNOWN CONTINUATION' not in [c['value'] for c in got['cells']]


@pytest.mark.parametrize('limit',['MAX_ARCHIVES','MAX_ITEMS','MAX_PERIODS','MAX_HEADER_CELLS','MAX_RESULT_BYTES'])
def test_budgets_fail_explicitly_instead_of_returning_truncated_success(api,monkeypatch,limit):
    _,row=saved()
    monkeypatch.setattr(review,limit,0)
    with pytest.raises(review.SourceReviewProblem):review.review('Fixture',row['id'],TODAY)


def test_ambiguous_existing_identity_is_rejected_before_any_original_read(api,monkeypatch):
    _,row=saved()
    reg=contracts.build('Fixture',TODAY,include_history=False)
    reg['rows'].append({**copy.deepcopy(row),'id':'f'*64})
    monkeypatch.setattr(contracts,'build',lambda *_args,**_kw:reg)
    calls=[];monkeypatch.setattr(review,'_original',lambda *_args:calls.append(True))
    with pytest.raises(review.SourceReviewProblem,match='нескольким карточкам'):
        review.review('Fixture',row['id'],TODAY)
    assert not calls


@pytest.mark.parametrize('field,value', [('contract', 'A-13'),
    ('contractor', 'ООО «Другой подрядчик»'), ('customer', 'ООО «Другой заказчик»'),
    ('contract_date', None), ('contract_date', '2026-01-02')])
def test_projection_requires_the_original_number_both_parties_and_known_date(api,monkeypatch,field,value):
    _,row=saved()
    parse=ledgers.parse_archive
    def changed(raw):
        result=copy.deepcopy(parse(raw));result['ledgers'][0][field]=value;return result
    monkeypatch.setattr(ledgers,'parse_archive',changed)
    data=review.review('Fixture',row['id'],TODAY)
    assert data['state']=='incomplete' and data['source_count']==0


def test_an_unknown_card_date_is_rejected_before_reading_originals(api,monkeypatch):
    _,row=saved()
    reg=contracts.build('Fixture',TODAY,include_history=False)
    reg['rows'][0]['contract_date']=None
    monkeypatch.setattr(contracts,'build',lambda *_args,**_kw:reg)
    calls=[];monkeypatch.setattr(review,'_original',lambda *_args:calls.append(True))
    with pytest.raises(review.SourceReviewProblem,match='не подтверждены'):
        review.review('Fixture',row['id'],TODAY)
    assert not calls


def test_global_summary_preamble_cannot_leak_a_neighbour_total():
    own={'document_form':'closing_summary','source':{'filename':'Summary.xlsx','sheet':'KS','row':20},
         'reported_total':{'source':{'row':22}}}
    next_card={'source':{**own['source'],'row':30}}
    rows=[[] for _ in range(30)]
    rows[0]=['Номер акта','Дата акта']
    rows[4]=['GLOBAL-TOTAL-CANARY',123456789]
    rows[6]=['Дата','2026-01-01',987654321]
    rows[19],rows[21]=['OWN CONTRACT'],['OWN TOTAL']
    got=review._headers(own,rows,[own,next_card])
    values=[cell['value'] for cell in got['cells']]
    assert 'Номер акта' in values and 'OWN TOTAL' in values
    assert not {'GLOBAL-TOTAL-CANARY',123456789,987654321,'2026-01-01'} & set(values)
