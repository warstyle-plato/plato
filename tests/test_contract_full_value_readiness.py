"""Owner's full-value aggregate keeps delivery and installation independently evidenced."""
import io
import json

import pytest
from openpyxl import load_workbook

import developaid_contract_control as control
import developaid_contract_comparison as comparison
import developaid_contract_comparison_export as export
import developaid_monitor_page as page
from tests import page_blocks
from tests.test_monitor_cumulative_api import api  # noqa: F401
from tests.test_contract_material_plan import work, calculate
from tests.test_contract_known_schedule_dates_without_fact import source_card  # noqa: F401


def actual(code='1', *, installed=0, delivered=0, volume=None, material_volume=None,
           last=None, material_last=None):
    return {'code':code,'fact':installed+delivered if delivered is not None else None,
            'work_fact':installed,'material_fact':delivered,
            'volumes':[] if volume is None else [{'unit':'м2','quantity':volume}],
            'material_volumes':[] if material_volume is None else [{'unit':'м2','quantity':material_volume}],
            'last':last,'material_last':material_last,'complete':False}


def project(got, rows):
    current={'in_force':True,'lines':rows,'schedule_sha256':'a'*64}
    return comparison.build({'control':got,'plan':{'editions':[current]},'fact':{},
        'documents':[{'sha256':'a'*64,'title':'Учебный ГПР','schedule':{'lines':rows}}]}, '2026-03-10')


def test_overdelivery_is_capped_independently_and_does_not_install_either_work():
    rows=[work('1',100,900),work('2',900,100)]
    got=calculate(rows,[actual(delivered=2000,material_last='2026-03-09')])
    assert got['total']['readiness'] == pytest.approx(0.45)
    assert got['total']['lag_days'] == 5
    assert got['total']['fact'] == 2000  # Money is evidence, not the capped readiness contribution.
    assert got['components']['work']['counted'] == 0
    assert got['components']['material']['counted'] == 900
    assert all(row['state']=='behind' and row['readiness']==0 for row in got['lines'])
    assert got['materials'][0]['readiness'] == pytest.approx(2000/900)


def test_supply_only_contract_has_readiness_and_a_dated_delivery_without_installed_work():
    got=calculate([work('1',0,1000,supply_only=True)],
                  [actual(delivered=1000,material_last='2026-03-09')])
    assert got['lines']==[] and got['components']['work']['amount']==0
    assert got['total']['readiness']==1 and got['total']['state']=='done'
    assert got['forecast']['done'] and got['forecast']['finish']=='2026-03-09'
    assert got['materials'][0]['finished']=='2026-03-09'


def test_quantity_controls_delivery_when_confirmed_and_money_fallback_is_named():
    rows=[work('1',100,900,material_volume={'unit':'м2','quantity':100})]
    got=calculate(rows,[actual(delivered=450,material_volume=10)])
    assert got['materials'][0]['readiness']==0.1
    assert got['total']['readiness']==0.09
    assert got['total']['fact']==450
    no_quantity=calculate([work('1',100,900)], [actual(delivered=450)])
    material=next(r for r in project(no_quantity,[work('1',100,900)])['lines'] if r.get('component')=='material')
    assert material['readiness']==0.5 and material['fact']==450
    assert 'по стоимости' in material['money_fallback'] and 'Монтаж не подтверждён' in material['money_fallback']


@pytest.mark.parametrize('gap',['amount','fact','composition'])
def test_unknown_component_prevents_overall_readiness_but_retains_the_known_work(gap):
    row=work('1',100,900)
    source=actual(installed=50,delivered=450)
    if gap=='amount': row['material_amount']=None
    if gap=='fact': source['material_fact']=None
    if gap=='composition': row['material_amount']=800
    got=calculate([row],[source])
    assert got['total'] is None and got['note'] and got['data_gaps']
    assert got['components']['work']['readiness']==0.5
    assert got['lines'][0]['readiness']==0.5
    assert source['fact']==500  # No rewriting the financial evidence to fit the aggregate.


def test_latest_delivery_and_work_dates_remain_independent_and_forecast_uses_both():
    got=calculate([work('1',100,900)],
                  [actual(installed=100,delivered=900,last='2026-03-05',material_last='2026-03-09')])
    assert got['lines'][0]['finished']=='2026-03-05'
    assert got['materials'][0]['finished']=='2026-03-09'
    assert got['forecast']['finish']=='2026-03-09'
    assert got['forecast']['done']
    undated=calculate([work('1',100,900)],
                      [actual(installed=100,delivered=900,last='2026-03-05')])
    assert undated['total']['readiness']==1
    assert undated['forecast']['finish'] is None and 'Дата завершения' in undated['forecast']['note']
    assert undated['materials'][0]['finished'] is None


def test_component_rows_count_source_coverage_once_and_export_each_contribution():
    rows=[work('1',100,900),work('2',0,1000,supply_only=True)]
    got=calculate(rows,[actual(installed=50,delivered=450),actual('2',delivered=500)])
    view=project(got,rows)
    assert view['coverage']['calculated']==view['coverage']['source_works']==2
    assert view['coverage']['unknown']==0
    assert [r['code'] for r in view['lines']]==['1','1::material','2']
    assert view['lines'][0]['fact']==50 and view['lines'][1]['fact']==450
    # The compact Excel is RDS-led and does not repeat component display rows.
    from tests.contract_rds_fixtures import native_card
    cached=native_card()
    meta=cached['comparison_export']; rds=cached['rds_comparison']
    book=load_workbook(io.BytesIO(export.workbook(meta,rds,rds['rows'])),data_only=True)
    assert len(book.worksheets)==1 and book.active.max_column==16
    assert book.active.max_row==8
    assert not any('— поставка материалов' in str(cell.value) for row in book.active for cell in row)


def test_native_page_names_full_value_and_keeps_visible_component_numbers_without_mutation():
    got=calculate([work('1',100,900)],[actual(installed=50,delivered=900)])
    summary=dict(got['total'],components=got['components'])
    out,_=page_blocks.run('const row='+json.dumps({'schedule_control':summary})+';const before=JSON.stringify(row);',
        'console.log(JSON.stringify({html:contractScheduleParts(row),same:before===JSON.stringify(row)}))',page=page.MONITOR_PAGE)
    rendered=json.loads(out)
    assert rendered['same'] and 'общая готовность в расчёте' in rendered['html']
    assert '95 %' in rendered['html'] and 'Работы: 50 %' in rendered['html']
    assert 'Поставка материалов: 100 %' in rendered['html'] and 'Поставка не подтверждает монтаж' in rendered['html']


def test_fresh_unknown_card_never_falls_back_to_stale_known_register_metrics():
    got=calculate([work('1',100,900)],[actual(installed=50,delivered=None)])
    row={'amount':1000,'completed':None,'physical_items':[],
         'schedule_control':{'readiness':0.95,'plan_done':0.95,'finish':'2026-03-09'}}
    def render(source):
        out,_=page_blocks.run('const row='+json.dumps(row)+';const card='+json.dumps({'control':got})+';',
            'console.log(JSON.stringify(contractCardSummary(row,card)))',page=source)
        return json.loads(out)
    def check(html):
        assert '95 %' not in html and '09.03.2026' not in html
        assert 'Работы: 50 %' in html and 'Поставка материалов: Готовность неизвестна' in html
        assert 'Не рассчитано' in html
    check(render(page.MONITOR_PAGE))
    broken=page.MONITOR_PAGE.replace(
        'const total=d?.control?(d.control.total||{}):(r.schedule_control||{}),fc=d?.control?(d.control.forecast||{}):(r.schedule_control||{})',
        'const total=d?.control?.total||r.schedule_control||{},fc=d?.control?.forecast||r.schedule_control||{}')
    assert broken!=page.MONITOR_PAGE
    with pytest.raises(AssertionError):
        check(render(broken))


def test_counterexample_old_work_only_aggregate_fails_the_full_value_assertion(monkeypatch):
    rows=[work('1',100,900),work('2',900,100)]
    native=control._materials
    monkeypatch.setattr(control,'_materials',lambda *args: [])
    broken=calculate(rows,[actual(installed=100,delivered=900,last='2026-03-10')])
    with pytest.raises(AssertionError):
        assert broken['total']['readiness']==0.5
    monkeypatch.setattr(control,'_materials',native)


def test_repeated_names_in_different_source_rows_never_share_material_facts():
    rows=[work('1.1',100,900),work('2.1',100,900)]
    for row in rows: row['name']='Одинаковый монтаж'
    got=calculate(rows,[actual('1.1',delivered=900,material_last='2026-03-09')])
    view=project(got,rows)
    assert got['total']['readiness']==0.45
    materials={r['source_code']:r for r in view['lines'] if r.get('component')=='material'}
    assert materials['1.1']['fact']==900 and materials['2.1']['fact']==0
    assert materials['1.1']['parent_code']=='1.1' and materials['2.1']['parent_code']=='2.1'
    assert view['coverage']['calculated']==view['coverage']['source_works']==2


@pytest.mark.parametrize('width',[390,1440])
def test_native_page_keeps_work_and_delivery_rows_and_unknowns_visible(source_card,width):  # noqa: F811
    from playwright.sync_api import expect
    from tests.test_contract_card_shows_its_documents import _serve
    from tests.test_monitor_cumulative_controls import CONTRACT,browser_page
    rows=[work('1',100,900)]
    got=calculate(rows,[actual(installed=50,delivered=900,material_last='2026-03-09')])
    source_card.update(control=got,comparison=project(got,rows))
    with browser_page(width) as (browser,_,errors):
        _serve(browser,source_card,[])
        browser.locator('#contractsTab').click()
        browser.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        summary=browser.locator('#contractCardSummary')
        expect(summary).to_contain_text('Общая готовность в расчёте: 95 %')
        expect(summary.locator('[data-contract-component="work"]')).to_contain_text('Работы: 50 %')
        expect(summary.locator('[data-contract-component="material"]')).to_contain_text('Поставка материалов: 100 %')
        table=browser.locator('#contractComparisonRows')
        expect(table.locator('[data-comparison-code="1"]')).to_contain_text('50 ₽')
        expect(table.locator('[data-comparison-code="1::material"]')).to_contain_text('900 ₽')
        expect(table.locator('[data-comparison-code="1::material"]')).to_contain_text('Монтаж не подтверждён')
        assert browser.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors


@pytest.mark.parametrize('operation',['view','documents'])
@pytest.mark.parametrize('prior_revision',[None,'contract-full-value-v1','contract-full-value-ks-source-fallback-v1',
                                          'contract-full-value-ks-source-fallback-v2',
                                          'contract-full-value-ks-source-fallback-v3','contract-rds-plan-fact-v1','contract-rds-plan-fact-v2'])
def test_old_method_ticket_is_immutable_but_cannot_readmit_or_replace_fresh_calculation(api,monkeypatch,operation,prior_revision):
    import developaid_management_report_jobs as jobs
    from tests.test_monitor_cumulative_api import post,poll,core,KEY
    client,root=api
    purpose='monitor-cumulative-v1:contracts'
    owner=jobs.owner_binding(KEY,'',purpose)
    payload={'operation':operation,'click':'a'*32,'project':'Учебный','cut':'2026-03-10'}
    if operation=='documents':
        payload.update(contract_id='f'*64,view='raw',correction_id='',correction_guard='',logical_contract_id='')
    import developaid_monitor_ledgers as ledgers
    context=ledgers.snapshot_job_context('Учебный')
    payload['source_context']=context
    if prior_revision is not None:
        # Main уже считает полную стоимость, но ещё не выбирает КС-2 при отсутствии КС-6а.
        payload['contract_calculation_revision']=prior_revision
    old={'ok':True,'weights':'Готовность работ без материалов','legacy':True}
    store=jobs.Store(root/'monitor'/'.cumulative_jobs')
    store.start(owner,purpose,payload,lambda:old,'a'*32,context=context)
    response=poll(client,'a'*32)
    assert response.status_code==200 and response.json()['legacy']
    original=store._meta('a'*32)
    calls=[]
    def current(*args):
        calls.append(args)
        return {'ok':True,'new_method':control.CALCULATION_REVISION}
    monkeypatch.setattr(core,'_monitor_cumulative_execute',current)
    path='contracts/build' if operation=='view' else 'contracts/documents'
    params={'project':'Учебный','cut':'2026-03-10'}
    if operation=='documents':params['contract_id']='f'*64
    assert post(client,path,**params,ticket='a'*32).status_code==409
    assert store._meta('a'*32)==original and not calls
    assert post(client,path,**params,ticket='b'*32).status_code==202
    fresh=poll(client,'b'*32)
    assert fresh.status_code==200 and fresh.json()['new_method']==control.CALCULATION_REVISION
    assert len(calls)==1 and poll(client,'a'*32).json()==response.json()
