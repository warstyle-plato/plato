"""The normal contract card presents the shared v4 projection on phone and desktop."""
import copy
import pytest
from playwright.sync_api import expect
import developaid_contract_gpr_export as export
import developaid_contract_workforce as workforce
from tests.test_monitor_cumulative_controls import browser_page, CONTRACT


def source_state():
    source={'sha256':'b'*64,'contract':{'number':'A-123','date':'2026-01-01'}}
    lines=[{'code':str(i),'name':name,'start':start,'finish':finish}
           for i,name,start,finish in [(1,'Подтверждённый остаток','2026-01-01','2026-01-10'),
               (2,'Физфакт неизвестен','2026-01-01','2026-01-10'),
               (3,'Будущая работа','2026-12-01','2026-12-31')]]
    positions=[]
    for i,line in enumerate(lines):
        q={'fact_quantity':5,'contract_quantity':10,'unit':'м2','fraction':.5} if i==0 else None
        positions.append({**line,'code':'rds:0:'+str(i),'number':'1.1.'+str(i+1),'position_key':[0,i],
            'section':'Устройство кровли Корпус 1','quantity':q,
            'physical':{**q,'planned_fraction':1,'lag_days':14} if q else None,
            'source_dates':['2026-01-20'] if q else [],'reporting_events':[]})
    schedule={'lines':lines,'source_identity':source}
    row={'id':CONTRACT,'contract':'A-123','contract_date':'2026-01-01','contractor':'ООО «Исполнитель»'}
    reports=[{'date':'2026-01-24','text':'Исполнитель (кровля) ИТР 5, рабочие 82'}]
    crew=workforce.project(schedule,reports,row,{'rows':[row,{**row,'id':'c'*64,'contract':'B-456'}]},'2026-01-24',source=source)
    return {'source':source,'schedule':schedule,'cut':'2026-01-24','workforce':crew,
            'presentation':export.presentation(schedule,{},'2026-01-24',positions)}


@pytest.mark.parametrize('width',[390,1440])
def test_card_shared_projection_distinguishes_calendar_risk_and_shows_unallocated_company_facts(width):
    state=source_state();before=copy.deepcopy(state)
    dto={'ok':True,'pending':False,'ticket':'a'*32,'contract_id':CONTRACT,'documents':[],
         'gpr':state,'gpr_export':{'available':True,'revision':'d'*64,'filename':'Fixture.xlsx'}}
    with browser_page(width) as (page,responses,errors):
        page.route('**/monitor/contracts/documents',lambda route:route.fulfill(json=dto))
        page.locator('#contractsTab').click();page.locator('tr[data-contract-id="'+CONTRACT+'"] .contract-open').click()
        expect(page.locator('.contract-gpr-position')).to_have_count(3)
        expect(page.locator('[data-company-latest="2026-01-24"]')).to_contain_text('82')
        assert page.locator('[data-company-date]').count()==1
        unknown=page.locator('.contract-gpr-position[data-rds-position="0:1"]')
        assert unknown.locator('[data-report-state="overdue_unclosed"]').get_attribute('fill').startswith('url(#contract-gpr-risk-position-')
        assert unknown.locator('[data-deadline-state]').inner_text().startswith('Срок истёк; физфакт не подтверждён')
        known=page.locator('.contract-gpr-position[data-rds-position="0:0"]')
        assert known.locator('[data-report-state="overdue"]').count()>0
        assert known.locator('[data-physical-source-date]').get_attribute('data-physical-source-date')=='2026-01-20'
        assert known.locator('[data-forecast-finish]').get_attribute('data-forecast-basis')=='planned_start_average'
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        scroll=page.locator('.contract-gpr-scroll')
        if width==390:
            assert scroll.evaluate('(e)=>e.scrollWidth>e.clientWidth')
            assert known.locator('.contract-gpr-name').evaluate('(e)=>getComputedStyle(e).position')=='static'
            scroll.evaluate('(e)=>e.scrollLeft=280')
            assert scroll.evaluate('(e)=>e.scrollLeft')>0
        ids=page.locator('pattern[id^="contract-gpr-risk-"]').evaluate_all('(els)=>els.map(e=>e.id)')
        assert len(ids)==len(set(ids))
        assert not errors,errors
    assert state==before
