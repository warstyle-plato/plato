"""Native registry quotes qualified statement value shares without inventing a union."""
import copy
import developaid_contract_register_display as display
import pytest
from playwright.sync_api import expect
from tests.test_monitor_cumulative_controls import browser_page


def statement(**changes):
    return dict(amount_scope='statement',planned=100,completed=50,completion_ratio=.5,
        monetary_comparable=True,financial_complete=True,natural_complete=True,source_complete=True,
        future_periods_excluded=False,period_dates_known=False,period_year=2026,source_date='2026-11-18',
        source={'file_sha256':'a'*64,'filename':'КС6а.xlsx','sheet':'Лист 1'},**changes)


def row(index,refs=None,**changes):
    return dict(id=f'{index:064x}',contractor='ООО «Исполнитель»',contract=f'Д-{index}',
        source_kind='cumulative',source_date='2026-11-18',amount=100,completed=None,completion_ratio=None,
        statement_progress={'state':'unknown','why':'Состав истории не подтверждён.'},
        physical_items=[],warnings=[],reported_performance_sources=refs or [],**changes)


@pytest.mark.parametrize('width',[390,1440])
def test_native_register_qualified_shares_and_fail_closed_sources(width):
    first=statement();same=copy.deepcopy(first);same['source_date']='2026-11-06'
    other=statement();other.update(period_year=2025,completed=90,completion_ratio=.9)
    other['source']={**other['source'],'sheet':'2025','filename':'<img src=x onerror="window.injected=1">.xlsx'}
    conflict=statement();conflict.update(completed=60,completion_ratio=.6)
    variants=[]
    for index,change in enumerate([{'monetary_comparable':False},{'financial_complete':False},
        {'future_periods_excluded':True},{'completion_ratio':'0.5'},{'completed':True},{'completion_ratio':.4},
        {'period_year':2027},{'source_date':'2026-12-01'}, {'source':{'filename':'Unpinned.xlsx','sheet':'1'}}],5):
        value=statement();value.update(change);variants.append(row(index,[value]))
    known=row(15,[first]);known.update(completed=30,completion_ratio=.3)
    zero=statement();zero.update(completed=0,completion_ratio=0)
    unresolved=row(17,[first]);unresolved['logical_ownership']={'state':'unresolved'}
    rows=[row(1,[first]),row(2,[first,same]),row(3,[first,other]),row(4,[first,conflict]),
          *variants,row(14),known,row(16,[zero]),unresolved,row(18,[{**first,'financial_complete':True,'natural_complete':False,'source_complete':False}])]
    next(value for value in rows if value['id']==f'{14:064x}')['schedule_control']={'readiness':.99,'coverage':{'known':1,'unknown':9}}
    display.attach({'rows': rows}, '2026-11-26')
    before=copy.deepcopy(rows)
    with browser_page(width,init="localStorage.setItem('monitor_cut','2026-11-26')") as (page,responses,errors):
        register={'project':'Учебный проект','cut':'2026-11-26','source_date':'2026-11-18','rows':rows}
        def result(route):route.fulfill(json={'ok':True,'pending':False,'register':register})
        page.route('**/monitor/contracts/build',result);page.route('**/monitor/contracts/result',result)
        page.locator('#contractsTab').click()
        expect(page.locator('tr.contract-row[data-contract-id]')).to_have_count(len(rows))
        money=lambda index:page.locator('tr[data-contract-id="'+f'{index:064x}'+'"] .contract-money')
        assert money(1).locator('.contract-register-completion').count()==1
        assert '50%' in money(1).inner_text().replace(' ','')
        for index in [1,2,3,4,16,18]:
            money(index).locator('.contract-completion-sources > summary').click()
        assert 'Архив: 18.11.2026' in money(1).inner_text() and '100 ₽' in money(1).inner_text()
        assert 'дата выполнения не подтверждена' in money(1).inner_text()
        assert money(2).locator('.contract-statement-share').count()==1
        assert money(2).locator('[data-statement-source-date]').get_attribute('data-statement-source-date')=='2026-11-18'
        assert money(3).locator('.contract-statement-share').count()==2
        assert '2025' in money(3).inner_text() and '90%' in money(3).inner_text().replace(' ','')
        assert 'не складываются' in money(3).inner_text()
        assert money(3).locator('img').count()==0 and page.evaluate('window.injected||null') is None
        assert 'расходятся' in money(4).inner_text() and '%' not in money(4).inner_text()
        for index in [*range(5,15),17]:
            assert money(index).locator('.contract-statement-share').count()==0
            assert 'не подтверждён' in money(index).inner_text() and '%' not in money(index).inner_text()
        assert money(15).locator('.contract-done').count()==1 and money(15).locator('.contract-statement-share').count()==0
        assert '30%' in money(15).inner_text().replace(' ','')
        assert '50%' in money(18).inner_text().replace(' ','') and 'По ведомости' in money(18).inner_text()
        assert '0%' in money(16).inner_text().replace(' ','') and 'Закрыто 0 ₽' in money(16).inner_text()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors
    assert rows==before
