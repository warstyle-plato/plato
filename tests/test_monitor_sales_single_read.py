"""One native sales read supplies both the dashboard and its prose summary."""
import concurrent.futures
import copy
import datetime as dt
import io
import json
import threading

import openpyxl
import pytest
from fastapi.encoders import jsonable_encoder

import developaid_actuals as actuals
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_monitor_keeps_every_snapshot import _rss_book
from test_the_monitor_takes_the_finmodel_as_its_finance_book import _finmodel

DAY=dt.date(2026,11,16)
VIEW={'schedule':{'approved_end':'2027-10-01','forecast_end':None}}


def sales_book(*, valid=True, september=3):
    book=openpyxl.Workbook();sheet=book.active
    sheet.title='План продаж'if valid else'Продажи П-Ф'
    for index,(month,mark,units,area,price)in enumerate([
        (dt.date(2026,9,1),'ФАКТ',september,300,20),
        (dt.date(2026,10,1),'ФАКТ',1,50,30),
        (dt.date(2026,12,1),'ПЛАН',99,500,40)],actuals._SALES_FIRST_ROW):
        for field,value in zip(('period','mark','units','area','price'),(month,mark,units,area,price)):
            sheet.cell(index,actuals._SALES_COLUMNS[field]+1,value)
    stream=io.BytesIO();book.save(stream);book.close();return stream.getvalue()


def make_project(project, *, book='success',manual=True,finance=True,units=4):
    monitor.store_estimate(project,_rss_book(),DAY.isoformat())
    if finance:
        path=monitor._project_dir(project)/'baseline'/'finance.xlsx'
        path.parent.mkdir();path.write_bytes(_finmodel())
    if book!='absent':monitor.store_sales_file(project,sales_book(valid=book=='success'),'2026-11-15')
    if manual:monitor.store_sales(project,[{'month':'2026-10','units':units,'area':240,'revenue':160}],'2026-11-15')
    return monitor._latest(project,'estimate','.xlsx',DAY.isoformat())


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    import developaid_monitor_page  # noqa: F401 — native Monitor overlays
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')


def wire(value):return json.dumps(jsonable_encoder(value),ensure_ascii=False,separators=(',',':'))


@pytest.mark.parametrize('book,manual,known,units',[
    ('success',False,True,4),('success',True,True,7),
    ('wrong_sheet',True,True,4),('wrong_sheet',False,False,None),
    ('absent',True,True,4),('absent',False,False,None),
])
def test_one_native_read_keeps_complete_values_sources_and_summary(monkeypatch,book,manual,known,units):
    project='Synthetic single sales read';rss=make_project(project,book=book,manual=manual)
    native=actuals.read_sales;reads=[];failures=[]
    def read(path):
        reads.append(path)
        try:return native(path)
        except KeyError as error:failures.append(type(error));raise
    monkeypatch.setattr(actuals,'read_sales',read)
    real_summary=dashboard._summary;seen=[]
    def summary(view,funding,sales):
        before=copy.deepcopy(sales);result=real_summary(view,funding,sales)
        assert sales==before
        seen.append(sales);return result
    monkeypatch.setattr(dashboard,'_summary',summary)
    sources={p:(p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_mode)
             for p in monitor._project_dir(project).rglob('*')if p.suffix in ('.xlsx','.json')}
    actual=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    assert len(reads)==(0 if book=='absent'else 1)
    assert failures==([KeyError]if book=='wrong_sheet'else [])
    assert actual['sales']is seen[0]
    assert list(actual)==['physical','construction','schedule','sales','funding','summary','sources']
    assert actual['sales']['known']is known
    if known:
        assert actual['sales']['total_units']==units
        assert actual['sales']['total_area']==(540 if book=='success'and manual else 350 if book=='success'else 240)
        assert actual['sales']['total_revenue']==(6160 if book=='success'and manual else 7500 if book=='success'else 160)
        assert any('Продажи.'in value and f'{units} лотов'in value for value in actual['summary'])
        assert ('лист продаж не разобран'in actual['sales']['source'])==(book=='wrong_sheet')
        assert ('строки на 'in actual['sales']['source'])==manual
    else:
        assert actual['sales']=={'known':False,'reason':'не загружены ни книга, ни строки продаж'}
    original=wire(actual)
    if known:actual['sales']['recent'].clear()
    repeated=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    assert wire(repeated)==original
    assert len(reads)==(0 if book=='absent'else 2)  # A new request reads its current source again.
    assert all((p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_mode)==state for p,state in sources.items())


def test_future_versions_and_new_request_keep_their_own_cut():
    project='Synthetic dated sales';rss=make_project(project)
    monitor.store_sales_file(project,sales_book(september=9),'2026-11-17')
    monitor.store_sales(project,[{'month':'2026-10','units':10,'area':100,'revenue':500}],'2026-11-17')
    historical=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    current=dashboard._dashboard(project,rss,dt.date(2026,11,17),copy.deepcopy(VIEW))
    assert historical['sales']['total_units']==7
    assert '2026-11-17'not in historical['sales']['source']
    assert current['sales']['total_units']==19
    assert current['sales']['source']=='2026-11-17.xlsx + строки на 2026-11-17'
    assert wire(dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW)))==wire(historical)


def test_failed_decoder_is_not_cached_across_requests_or_source_replacement():
    project='Synthetic corrected sales';rss=make_project(project,book='wrong_sheet')
    first=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    assert 'лист продаж не разобран'in first['sales']['source']
    path=monitor._project_dir(project)/'sales'/'2026-11-15.xlsx'
    before=path.read_bytes();path.write_bytes(sales_book());assert path.read_bytes()!=before
    second=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    assert 'лист продаж не разобран'not in second['sales']['source']
    assert second['sales']['total_units']==7


def test_missing_finance_stays_unknown_while_manual_sales_remain_known():
    project='Synthetic unknown finance';rss=make_project(project,book='wrong_sheet',finance=False)
    actual=dashboard._dashboard(project,rss,DAY,copy.deepcopy(VIEW))
    assert actual['funding']['known']is False
    assert actual['sales']['known']is True and actual['sales']['total_units']==4
    assert 'лист продаж не разобран'in actual['sales']['source']
    assert actual['construction']['approved']is None and actual['construction']['remaining_need']is None


def test_concurrent_projects_keep_separate_local_payloads(monkeypatch):
    projects=['Synthetic sales first','Synthetic sales second']
    rss={project:make_project(project,book='wrong_sheet',units=count)
         for project,count in zip(projects,(4,9))}
    native=actuals.read_sales;barrier=threading.Barrier(2);reads=[]
    def read(path):
        reads.append(path);barrier.wait(timeout=10);return native(path)
    monkeypatch.setattr(actuals,'read_sales',read)
    def build(project):return dashboard._dashboard(project,rss[project],DAY,copy.deepcopy(VIEW))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:
        first,second=list(pool.map(build,projects))
    assert len(reads)==2 and len(set(reads))==2
    assert first['sales']['total_units']==4 and second['sales']['total_units']==9
    assert first['sales']is not second['sales']
