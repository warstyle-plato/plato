"""One readable comparison in an isolated, accessible contract dialog."""
import copy

import pytest

import developaid_contract_comparison as comparison
import developaid_contract_fact as fact
import developaid_contract_files as files
from tests.test_contract_fact_prices_ks_by_the_edition import card,REGISTER_ROW  # noqa: F401
from tests.test_contract_card_shows_its_documents import _serve
from tests.test_monitor_cumulative_controls import CONTRACT,browser_page


@pytest.fixture
def compared(card):  # noqa: F811
    return files.listing('Учебный',CONTRACT,'2026-02-04',fact.acts(REGISTER_ROW))


def test_projection_reuses_control_numbers_and_keeps_every_source_work(compared):
    before=copy.deepcopy(compared)
    view=comparison.build(compared,'2026-02-04')
    assert compared==before
    for native in compared['control']['lines']:
        shown=next(r for r in view['lines'] if r['code']==native['code'])
        measure=native.get('volume') or native
        assert (shown['planned'],shown['fact'],shown['deviation'])==(measure['planned'],measure['fact'],measure['deviation'])
        assert shown['plan_done']==native['plan_done'] and shown['forecast_finish']==native['forecast_finish']
    source=next(d for d in compared['documents'] if d['sha256']==view['coverage']['schedule_sha256'])['schedule']['lines']
    parents={r.get('parent') for r in source}
    assert {r['code'] for r in source if r['code'] not in parents}<={r['code'] for r in view['lines']}
    assert view['coverage']['calculated']==len(compared['control']['lines'])


def test_a_known_plan_survives_missing_actuals_without_zeroing_them(card):  # noqa: F811
    listed=files.listing('Учебный',CONTRACT,'2026-02-04')
    assert listed['control']['total'] is None
    rows=listed['comparison']['lines']
    assert any(r['planned'] is not None for r in rows)
    assert all(r['fact'] is None and r['deviation'] is None and r['reason'] for r in rows)


def test_unsuitable_source_works_are_present_with_their_specific_reason(compared):
    listed=copy.deepcopy(compared)
    sha=listed['comparison']['coverage']['schedule_sha256']
    source=next(d for d in listed['documents'] if d['sha256']==sha)
    source['schedule']['lines'].append({'code':'99.1','parent':'99','name':'Работа с непрочитанной датой',
                                       'start':None,'finish':None})
    view=comparison.build(listed,'2026-02-04')
    row=next(r for r in view['lines'] if r['code']=='99.1')
    assert row['state']=='unknown' and row['fact'] is None and row['planned'] is None
    assert 'срок' in row['reason'] and view['coverage']['partial']
    assert view['total']==compared['control']['total']


@pytest.mark.parametrize('width',[390,1440])
def test_modal_has_one_main_table_and_closed_numbered_sources(compared,width):
    from playwright.sync_api import expect
    with browser_page(width) as (page,responses,errors):
        _serve(page,compared,[])
        page.locator('#contractsTab').click()
        opener=page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open')
        opener.click()
        dialog=page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('#contractComparisonRows tr[data-comparison-code]')).to_have_count(len(compared['comparison']['lines']))
        expect(dialog.locator('.contract-comparison')).to_have_count(1)
        expect(dialog.locator('.contract-plan,.contract-fact,.contract-control')).to_have_count(0)
        expect(dialog.locator('details[open]')).to_have_count(0)
        expect(dialog.locator('#contractDocumentList')).not_to_have_attribute('open','')
        if width==390:
            assert dialog.locator('.contract-comparison-scroll').evaluate('e=>getComputedStyle(e).maxHeight')=='none'
            assert dialog.locator('.contract-comparison-scroll').evaluate('e=>getComputedStyle(e).overflowY')=='visible'
        dialog.locator('#contractDocumentList > summary').click()
        help_block=dialog.get_by_text('Как читаются документы',exact=True).locator('..')
        assert not help_block.evaluate('e=>e.open')
        expect(help_block.locator('p')).not_to_be_visible()
        expect(dialog.locator('.contract-document')).to_have_count(len(compared['documents']))
        expect(dialog.locator('.contract-document').first.locator('summary').first).to_contain_text('1.')
        dialog.locator('.contract-document').first.locator('summary').first.click()
        expect(dialog.locator('.contract-document').first.locator('.contract-document-level > summary').first).to_contain_text('1.1')
        expect(dialog.locator('.contract-document-level[open]')).to_have_count(0)
        assert dialog.locator('.contract-compare-main').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=14
        assert dialog.locator('.contract-compare-main').first.evaluate('e=>parseFloat(getComputedStyle(e.parentElement.querySelector(".contract-sub")).fontSize)')>=12
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth') and not errors
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(page.locator('#contractsDetails')).to_be_empty()
        expect(opener).to_be_focused()


@pytest.mark.parametrize('width',[390,1440])
def test_plan_unknown_fact_and_filter_remain_visible_in_the_modal(card,width):  # noqa: F811
    from playwright.sync_api import expect
    listed=files.listing('Учебный',CONTRACT,'2026-02-04')
    with browser_page(width) as (page,_,errors):
        _serve(page,listed,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractComparisonFilter').select_option('unknown')
        rows=page.locator('#contractComparisonRows tr[data-comparison-code]')
        expect(rows).to_have_count(len(listed['comparison']['lines']))
        known=next(r for r in listed['comparison']['lines'] if r['planned'] is not None)
        row=page.locator(f'#contractComparisonRows tr[data-comparison-code="{known["code"]}"]')
        expect(row.locator('[data-label="План на дату"]')).not_to_have_text('Неизвестно')
        expect(row.locator('[data-label="Факт"]')).to_contain_text('Неизвестно')
        row.locator('.contract-comparison-reason > summary').click()
        expect(row.locator('.contract-comparison-reason')).to_contain_text(known['reason'])
        assert not errors


@pytest.mark.parametrize('change',['project','cut','key'])
def test_context_change_closes_and_scrubs_the_dialog(compared,change):
    from playwright.sync_api import expect
    with browser_page(390) as (page,_,errors):
        _serve(page,compared,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.locator('#contractComparisonRows tr[data-comparison-code]')).not_to_have_count(0)
        if change=='key':
            page.evaluate("localStorage.removeItem('plato_projects_key');window.dispatchEvent(new StorageEvent('storage',{key:'plato_projects_key'}))")
        else:
            page.locator('#'+change).evaluate("(e,v)=>{e.value=v;e.dispatchEvent(new Event('input',{bubbles:true}))}",'Другой проект' if change=='project' else '2026-02-03')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.locator('#contractsDetails')).to_be_empty()
        assert not errors


@pytest.mark.parametrize('entry',['button','arrow','row'])
def test_all_entry_points_open_the_same_modal_and_close_restores_focus(compared,entry):
    from playwright.sync_api import expect
    with browser_page(1440) as (page,_,errors):
        _serve(page,compared,[])
        page.locator('#contractsTab').click()
        row=page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        target=row.locator({'button':'.contract-open','arrow':'.contract-more-toggle','row':'td.party'}[entry])
        target.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.locator('#contractComparisonRows tr[data-comparison-code]')).to_have_count(len(compared['comparison']['lines']))
        expect(page.locator('tr.contract-more')).to_have_count(0)
        page.locator('#contractDialogClose').click()
        expect(page.locator('#contractsDetails')).to_be_empty()
        expect(target if entry!='row' else row.locator('.contract-open')).to_be_focused()
        assert not errors


def test_late_response_after_close_does_not_restore_contract_data(compared):
    from playwright.sync_api import expect
    pending=[]
    with browser_page(390) as (page,_,errors):
        page.route('**/monitor/contracts/documents',lambda route:pending.append(route))
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.wait_for_function('document.getElementById("contractDialog").open')
        assert len(pending)==1
        page.locator('#contractDialogClose').click()
        with page.expect_response('**/monitor/contracts/documents'):
            pending[0].fulfill(json={'pending':False,'ok':True,**compared})
        page.evaluate('()=>new Promise(requestAnimationFrame)')
        expect(page.locator('#contractsDetails')).to_be_empty()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        assert not errors


def test_revocation_closes_and_scrubs_the_modal():
    from playwright.sync_api import expect
    with browser_page(390) as (page,_,errors):
        page.route('**/monitor/contracts/documents',lambda route:route.fulfill(status=403,json={'detail':'Нет доступа'}))
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.locator('#contractsDetails')).to_be_empty()
        assert not errors


@pytest.mark.parametrize('width',[390,1440])
def test_reopening_before_native_close_event_keeps_current_modal(compared,width):
    from playwright.sync_api import expect
    with browser_page(width) as (page,_,errors):
        _serve(page,compared,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.get_by_role('dialog')).to_be_visible()
        # close() queues a native event. Reopen in the same task, before that
        # old event arrives, as can happen with immediate keyboard activation.
        page.evaluate('''id=>{
            window.nativeDialogClosures=0;
            document.getElementById('contractDialog').addEventListener('close',()=>window.nativeDialogClosures++);
            closeContractDialog();
            openContractDetails(id);
        }''',CONTRACT)
        page.wait_for_function('window.nativeDialogClosures>=1')
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.locator('#contractComparisonRows tr[data-comparison-code]')).to_have_count(len(compared['comparison']['lines']))
        # An actual external close still scrubs the active card and its forms.
        page.locator('#contractDialog').evaluate('d=>d.close()')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.locator('#contractsDetails')).to_be_empty()
        assert not errors


@pytest.mark.parametrize('width',[390,1440])
def test_prints_current_comparison_or_register_without_private_source_sections(compared,width):
    from playwright.sync_api import expect
    with browser_page(width) as (page,_,errors):
        _serve(page,compared,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.locator('#contractComparisonRows tr[data-comparison-code]')).to_have_count(len(compared['comparison']['lines']))
        page.emulate_media(media='print')
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.locator('.contract-comparison')).to_be_visible()
        expect(page.locator('#contractDocumentList')).not_to_be_visible()
        expect(page.locator('#contractsRows')).not_to_be_visible()
        page.emulate_media(media='screen')
        page.locator('#contractDialogClose').click()
        page.emulate_media(media='print')
        expect(page.locator('#contractsRows')).to_be_visible()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        assert not errors


def test_reopening_cards_does_not_retain_another_cards_term_handler(compared):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import OTHER
    with browser_page(1440) as (page,_,errors):
        page.route('**/monitor/contracts/documents',lambda route:route.fulfill(json={'ok':True,'pending':False,**compared}))
        page.locator('#contractsTab').click()
        page.evaluate('()=>{window.termActions=[];const original=openContractTerm;openContractTerm=id=>{window.termActions.push(id);return original(id)}}')
        for cid in (CONTRACT,OTHER,CONTRACT):
            page.locator(f'tr[data-contract-id="{cid}"] .contract-open').click()
            page.locator('#contractsDetails .contract-term').click()
            expect(page.locator('#contractsTerm')).to_be_visible()
            page.locator('#contractDialogClose').click()
            assert page.locator('#contractsDetails').evaluate('e=>e.onclick')is None
        assert page.evaluate('window.termActions')==[CONTRACT,OTHER,CONTRACT]
        assert not errors


def test_manual_deadline_and_its_label_survive_document_source_refresh(compared):
    from playwright.sync_api import expect
    listed=copy.deepcopy(compared)
    listed['terms']={'deadline':'2027-04-30','history':[{'deadline':'2027-04-30'}],
                     'source':{'label':'ДС № 1 · стр. 2 · п. 2.3.2'}}
    with browser_page(390) as (page,responses,errors):
        row=responses.data['rows'][0]
        row.update(deadline='2027-05-15',deadline_source={'label':'Указан вручную'})
        _serve(page,listed,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        page.locator('#contractComparison[aria-busy="false"]').wait_for()
        term=page.locator('#contractCardSummary [data-label="Срок договора"]')
        expect(term).to_contain_text('15.05.2027')
        expect(term).to_contain_text('Указан вручную')
        expect(term).not_to_contain_text('ДС № 1')
        assert not errors


def _undated_source(sha='a'*64):
    return {'sha256':sha,'title':'Учебный график','contract':{'number':'A-12','date':'2026-01-01'},
            'estimates':[],'schedule':{'lines':[{'code':'1','name':'Работа без дат',
               'parent':None,'start':None,'finish':None}]}}


def _source_only_view(records):
    return files._with_control({'documents':records,'plan':{'editions':[]},
              'fact':{'note':'Нет факта','lines':[]}},None,'2026-02-04')


def test_a_unique_graph_keeps_all_undated_work_without_creating_a_forecast():
    source=_undated_source()
    got=_source_only_view([source])
    assert files._schedule_source([source],'2026-02-04')is None
    assert got['control']['total']is None and got['control']['forecast']is None
    view=got['comparison']
    assert view['schedule_source']is None
    assert view['coverage']['source_known'] and view['coverage']['source_works']==1
    assert view['coverage']['schedule_sha256']==source['sha256'] and view['coverage']['partial']
    row,=view['lines']
    assert row['state']=='unknown' and 'нет корректного срока' in row['reason']
    assert row['planned']is None and row['fact']is None and row['forecast_finish']is None and row['due']is None


@pytest.mark.parametrize('excluded',['ambiguous','scan','future','removed','undated_identity','missing_contract','missing_number','agreement_without_contract_date','act'])
def test_unknown_date_source_identity_obeys_the_same_selection_guards(excluded):
    source=_undated_source()
    records=[source]
    if excluded=='ambiguous':records.append(_undated_source('b'*64))
    elif excluded=='scan':source['scan']={'confirmed_at':None}
    elif excluded=='future':source['contract']['date']='2026-02-05'
    elif excluded=='removed':source['removed_at']='2026-02-01T00:00:00Z'
    elif excluded=='undated_identity':source['contract']['date']=None
    elif excluded=='missing_contract':source.update(contract=None,agreement={'number':'1','date':'2026-01-01'})
    elif excluded=='missing_number':source['contract']['number']=None
    elif excluded=='agreement_without_contract_date':
        source['contract']['date']=None
        source['agreement']={'number':'1','date':'2026-01-01'}
    elif excluded=='act':source['act']={'number':'1','date':'2026-01-01'}
    got=_source_only_view(records)
    assert got['comparison']['lines']==[] and not got['comparison']['coverage']['source_known']
    assert got['comparison']['coverage']['schedule_sha256']is None
    assert got['control']['total']is None and got['control']['forecast']is None


@pytest.mark.parametrize('width',[390,1440])
def test_real_pdf_with_only_undated_work_is_visible_as_unknown(monkeypatch,tmp_path,width):
    from playwright.sync_api import expect
    import developaid_monitor as monitor
    from tests.test_contract_card_shows_its_documents import ROW
    from tests.test_contract_documents_are_read_from_their_tables import schedule_pdf
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    saved=files.store('Учебный',ROW,'График.pdf',schedule_pdf(
        lines=(('1','Работа без прочитанных дат','','',None),),
        title=('Договор подряда № 12-ТСТ от 01.09.2025',)))
    listed=files.listing('Учебный',CONTRACT,'2026-02-04')
    assert listed['comparison']['coverage']['schedule_sha256']==saved['sha256']
    assert listed['control']['forecast']is None and listed['comparison']['schedule_source']is None
    with browser_page(width) as (page,_,errors):
        _serve(page,listed,[])
        page.locator('#contractsTab').click()
        page.locator(f'tr[data-contract-id="{CONTRACT}"] .contract-open').click()
        expect(page.locator('#contractComparisonInfo')).to_contain_text('Сравнено 0 из 1 работ')
        row=page.locator('#contractComparisonRows [data-comparison-code="1"]')
        expect(row.locator('[data-label="План на дату"]')).to_have_text('Неизвестно')
        expect(row.locator('[data-label="Факт"]')).to_contain_text('Неизвестно')
        expect(row.locator('[data-label="Прогноз окончания"]')).to_have_text('Не рассчитан')
        row.locator('.contract-comparison-reason > summary').click()
        expect(row).to_contain_text('нет корректного срока')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
