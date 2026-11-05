"""Настоящие графики трёх вкладок и печати читают средние ядра; синтетика."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

sys.path.insert(0,str(Path(__file__).resolve().parent))
from browser import chromium_or_skip, serve
from test_management_report_model import _contract
from market_search import cabinet, contracting


def _summary(*,unknown=False):
    rows=[dict(_contract('2026-01-10','Квартира',100,30e6),units=2),
          dict(_contract('2026-03-12','Квартира',300,60e6),units=5),
          dict(_contract('2026-03-15','Машиноместо',0,8e6),units=2),
          _contract('2026-02-10','Коммерческие площади',50,20e6)]
    if unknown:rows.append(_contract('2026-04-01','Квартира',0,12e6))
    return contracting.summarise({'project':'Синтетический проект','rows':rows,'missing':[]},until='2026-04')


@pytest.fixture
def sales_server():
    app=FastAPI()
    @app.get('/cabinet/sales')
    def page():return HTMLResponse(cabinet.cabinet_page('sales').replace('__DEVELOPAID_VERSION__','test'))
    with serve(app,18865) as base:yield base


@pytest.fixture
def page(sales_server):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            tab=browser.new_page(viewport={'width':1280,'height':1000})
            tab.goto(sales_server+'/cabinet/sales')
            yield tab
        finally:browser.close()


READ="""() => [...document.querySelectorAll('#saleschart svg')]
 .filter(s=>s.getBoundingClientRect().height>0).map(s=>({
 name:s.getAttribute('aria-label'),
 lines:[...s.querySelectorAll('path.chart-average')].map(p=>({
  name:p.getAttribute('aria-label'),axis:p.dataset.axis,dash:p.getAttribute('stroke-dasharray'),path:p.getAttribute('d')})),
 labels:[...s.querySelectorAll('text.chart-average-value')].map(p=>({
  axis:p.dataset.axis,value:Number(p.dataset.value),text:p.textContent,
  cssHeight:p.getBoundingClientRect().height,
  box:{x:p.getBBox().x,y:p.getBBox().y,width:p.getBBox().width,height:p.getBBox().height}})),
 months:[...s.querySelectorAll('text')].map(p=>p.textContent).filter(t=>/^26-/.test(t))
 }))"""


@pytest.mark.parametrize('width',[390,1280])
def test_each_tab_has_weighted_price_and_calendar_pace(page,width):
    from playwright.sync_api import expect
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.set_viewport_size({'width':width,'height':1000})
    d=_summary();page.evaluate('(d)=>{salesData=d;renderSales(d)}',d)
    [amount]=page.evaluate(READ)
    assert amount['name']=='млн ₽ по месяцам'
    assert amount['months']==['26-01','26-02','26-03','26-04']
    assert {x['axis']:x['value'] for x in amount['labels']}=={'left':29.5e6,'right':225000}
    for metric,expected_count in [('area',2),('units',3)]:
        page.locator(f"#sales .switch button[data-for='saleschart'][data-metric='{metric}']").click()
        charts=page.evaluate(READ)
        assert len(charts)==expected_count
        for chart in charts:
            assert [(x['name'],x['axis']) for x in chart['lines']]==[
                ('Средний темп с начала продаж','left'),('Средняя цена с начала продаж','right')]
            assert all(l['dash'] for l in chart['lines'])
            assert all('NaN' not in l['path'] and 'Infinity' not in l['path'] for l in chart['lines'])
        flat=next(c for c in charts if c['name'].startswith('Квартира ·'))
        values={x['axis']:x['value'] for x in flat['labels']}
        assert values['left']==pytest.approx(100 if metric=='area' else 1.75)
        assert values['right']==225000  # Не среднее месячных300000и200000.
        if metric=='units':
            parking=next(c for c in charts if c['name'].startswith('Машиноместо ·'))
            assert {x['axis']:x['value'] for x in parking['labels']}=={'left':1,'right':4e6}
            assert '1,8' in [x['text'] for x in flat['labels']]
        for chart in charts:
            assert len(chart['labels'])==2
            one,two=chart['labels']
            assert abs(one['box']['y']-two['box']['y'])>=12
    expect(page.locator('#saleschart > .sales-average-note').first).to_contain_text('месяцев:')
    assert not errors
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_unknown_metres_do_not_turn_into_a_zero_average(page):
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',_summary(unknown=True))
    [amount]=page.evaluate(READ)
    assert not any(x['axis']=='right' for x in amount['labels'])
    page.locator("#sales .switch button[data-for='saleschart'][data-metric='area']").click()
    flat=next(c for c in page.evaluate(READ) if c['name'].startswith('Квартира ·'))
    assert flat['labels']==[]  # Исторические известные точки могут остаться, текущего числа нет.
    page.locator("#sales .switch button[data-for='saleschart'][data-metric='units']").click()
    flat=next(c for c in page.evaluate(READ) if c['name'].startswith('Квартира ·'))
    assert {x['axis']:x['value'] for x in flat['labels']}=={'left':2}


def test_rendering_reads_server_averages_instead_of_recounting(page):
    d=_summary()
    d['dynamics_pace']['total'][-1]['avg_amount']=123456789
    d['dynamics_pace']['total'][-1]['avg_price_flats']=456789
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',d)
    [chart]=page.evaluate(READ)
    assert {x['axis']:x['value'] for x in chart['labels']}=={'left':123456789,'right':456789}


@pytest.mark.parametrize('selected',['amount','area','units'])
def test_print_contains_averages_for_every_measure(page,selected):
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',_summary())
    page.locator(f"#sales .switch button[data-for='saleschart'][data-metric='{selected}']").click()
    result=page.evaluate("""() => {
      const html=salesPrintHtml(), d=new DOMParser().parseFromString(html,'text/html');
      const charts=[...d.querySelectorAll('#saleschart svg')];
      return {count:charts.length, lines:charts.map(s=>s.querySelectorAll('path.chart-average').length),
        tools:d.querySelectorAll('.switch button').length, html};
    }""")
    assert result['count']==6 and result['lines']==[2]*6
    assert result['tools']==0
    assert 'Средняя цена с начала продаж' in result['html']


def test_single_month_averages_have_visible_markers(page):
    d=contracting.summarise({'project':'Один месяц','rows':[_contract('2026-01-01','Квартира',100,30e6)],'missing':[]})
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',d)
    [chart]=page.evaluate(READ)
    assert {x['axis']:x['value'] for x in chart['labels']}=={'left':30e6,'right':300000}
    assert page.locator('#saleschart > .wrap .chart-average-point').count()==2


def test_full_report_and_other_chart_consumers_still_render(page):
    from test_the_sales_report_survives_a_full_project import full_summary
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.evaluate('(d)=>showSales(d)',full_summary())
    assert page.locator('#sales .salesblock').count()>=6
    assert page.locator('#sb-plan svg').count()>0
    assert page.locator('#saleschart path.chart-average').count()>0
    assert not errors


@pytest.mark.parametrize('tiny',[False,True])
def test_small_nonzero_averages_are_readable_and_not_rounded_to_zero(page,tiny):
    page.set_viewport_size({'width':390,'height':1000})
    row=_contract('2026-01-01','Квартира',.2 if tiny else 25,.4 if tiny else 6e6)
    d=contracting.summarise({'project':'Редкие продажи','rows':[row],'missing':[]},
                          until='2026-04' if tiny else '2027-12')
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',d)
    for metric in ['amount','area','units']:
        page.locator(f"#sales .switch button[data-for='saleschart'][data-metric='{metric}']").click()
        [chart]=page.evaluate(READ)
        for label in chart['labels']:
            assert label['value']>0
            assert label['text'] not in ['0','0,0','0 тыс']
            assert label['cssHeight']>=9
        one,two=chart['labels']
        assert one['box']['y']+one['box']['height']<two['box']['y']


def test_negative_zero_is_not_printed_as_a_negative_average(page):
    d=_summary()
    d['dynamics_pace']['total'][-1]['avg_amount']=-0.0
    d['dynamics_pace']['total'][-1]['avg_price_flats']=-0.0
    page.evaluate('(d)=>{salesData=d;renderSales(d)}',d)
    [chart]=page.evaluate(READ)
    assert len(chart['labels'])==2
    assert all(x['value']==0 and not x['text'].startswith(('-', '−')) for x in chart['labels'])
