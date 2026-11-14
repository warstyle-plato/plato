"""Synthetic AHR cash: date cutoff, signed facts, source precedence and failure isolation."""
import datetime as dt
import io
import json
from pathlib import Path

import openpyxl
import pytest

import developaid_actuals as actuals
import developaid_admin_expenses_cash as cash
import developaid_monitor as monitor
from test_the_approved_budget_says_what_it_is_made_of import _finmodel
from test_payments_join_the_contract_register import _row

REG={'rows':[_row('Admin','A','2.4.1','2.6'),_row('Tax','T','2.4.5.1','2.6'),_row('Build','B','2.2.1','2.1')]}
XW={'articles_by_estimate_code':{'2.6':{'project_management','tax'},'2.1':{'main_under'}}}

def payment(amount,day='2026-11-02',party='Admin',contract='A',code='2.6',row=1):
    return {'amount':amount,'date':dt.date.fromisoformat(day) if day else None,'contractor':party,
            'contract':contract,'estimate_code':code,'source_row':row,'source':'own'}

def calc(rows=(),bdds=None,cut='2026-11-14',budget=100):
    return cash.calculate({'budget':budget},{'rows':list(rows)},REG,XW,bdds or {},cut)

def doc(fact):return {'fact':fact,'source':{'sha256':'a'*64}}

def test_budget_is_non_tax_leaves_and_parent_is_only_composition_diagnostic():
    result=cash.fm_budget(_finmodel())
    assert result['budget']==40000
    assert result['fm_columns_context_only']['fact']==20000  # never paid cash
    assert result['taxes_separate']['total']==120000
    assert result['parent_2_4']['total']==160000
    assert result['all_child_leaf_sum_including_tax']['total']==160000
    assert result['parent_minus_all_children']['total']==0
    assert result['parent_minus_non_tax_leaves']['total']==120000
    assert result['unit_basis']=='existing_native_finmodel_contract'
    assert result['raw_unit_evidence']['state']=='missing'


def test_only_dated_paid_ahr_before_exact_day_is_cash_and_refunds_are_signed():
    result=calc([payment(25),payment(-5,'2026-11-03',row=2),payment(900,'2026-11-15',row=3),
                 payment(800,party='Tax',contract='T',row=4),payment(700,party='Build',contract='B',code='2.1',row=5)])
    assert result['paid_observed_net']==20
    assert result['balance_after_observed_payments']==80
    assert result['coverage']['future_rows_excluded']==1
    assert result['coverage']['excluded_non_ahr_classified_rows']==2
    assert not result['financial_acceptance']


def test_closed_month_bdds_replaces_rss_not_adds_and_current_scalar_is_not_day_cut():
    result=calc([payment(10,'2026-10-05'),payment(7)],{'2026-10-01':doc(30),'2026-11-01':doc(1000)})
    assert result['paid_observed_net']==37
    assert result['balance_after_observed_payments']==63
    assert result['months'][0]['source']=='budget_month_fact'
    assert result['months'][1]['budget_current_month_not_dated']
    assert result['months'][1]['source']=='rss_observed'


def test_explicit_zero_and_negative_budget_fact_are_known():
    result=calc(bdds={'2026-09-01':doc(0),'2026-10-01':doc(-10)})
    assert result['paid_known_part']==-10 and result['balance_after_observed_payments']==110
    assert result['months'][0]['paid']==0
    assert result['remaining_need'] is None


def test_latest_null_wins_even_if_older_file_has_fact():
    def parsed(fact):return {'months':{'2026-10-01':{'extra':{'admin':{'fact':fact,'plan':1}}}}}
    got=cash.selected_months([({'sha256':'new'},parsed(None)),({'sha256':'old'},parsed(99))])
    assert got['2026-10-01']['fact'] is None
    assert got['2026-10-01']['source']['sha256']=='new'


def test_all_available_history_is_used_and_gaps_do_not_erase_known_part():
    result=calc(bdds={'2024-01-01':doc(15),'2026-10-01':doc(20)})
    assert len(result['months'])==35
    assert result['paid_known_part']==35 and result['balance_after_observed_payments']==65
    assert result['remaining_need'] is None and result['state']=='partial'


def test_possible_ahr_and_unknown_date_block_definitive_but_not_known_cash():
    result=calc([payment(10),payment(8,party='Unknown',contract='X',row=2),payment(6,None,row=3)])
    assert result['paid_known_part']==10 and result['balance_after_observed_payments']==90
    assert result['remaining_need'] is None
    assert result['coverage']['unknown_date_possible_ahr_rows']==1
    assert result['coverage']['possible_ahr_unresolved_by_month']=={'2026-11-01':1}


def test_unrelated_unknown_or_duplicate_does_not_become_ahr_unresolved():
    result=calc([payment(10),payment(None,party='Tax',contract='T',row=2),
                 payment(7,party='Tax',contract='T',row=3),payment(7,party='Tax',contract='T',row=4)])
    assert result['coverage']['possible_ahr_unresolved_by_month']=={}
    assert result['coverage']['duplicate_suspected_months']==[]


def test_duplicate_ahr_is_visible_and_never_silently_deduplicated():
    result=calc([payment(10),payment(10,row=2)])
    assert result['paid_known_part']==20
    assert result['coverage']['duplicate_suspected_months']==['2026-11-01']
    assert result['remaining_need'] is None


def test_soft_counterparty_classification_is_labelled_not_confirmed():
    result=calc([payment(10,contract='Other')])
    assert result['paid_known_part']==10
    assert result['paid_classification_basis']['2026-11-01']=={'по контрагенту':10}
    assert result['coverage']['classified_not_strong_months']==['2026-11-01']
    assert result['remaining_need'] is None


def test_observer_does_not_change_canonical_public_mapping():
    rows=[payment(10),payment(-3),payment(7,party='Tax',contract='T',row=2)]
    events=[];args=({'rows':rows,'total':14},REG)
    before=actuals.payments_by_article(*args,crosswalk=XW)
    after=actuals.payments_by_article(*args,crosswalk=XW,classification_observer=events.append)
    assert before==after and len(events)==3
    assert not any('contractor' in e or 'contract' in e for e in events)


@pytest.fixture
def saved(tmp_path,monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'saved')
    monitor.replace_finance_baseline('Synthetic',_finmodel(),'2026-11-01','synthetic.xlsx')
    return monitor._project_dir('Synthetic')


def fail(*a,**kw):raise ValueError('synthetic source unavailable')


def test_rss_failure_keeps_known_fm_budget_and_monthly_fact(saved,monkeypatch):
    monkeypatch.setattr(cash.rss_source,'_rss_copy',fail)
    monkeypatch.setattr(cash,'_budget_listing',lambda *a:([],('stable',)))
    monkeypatch.setattr(cash,'_budget_months',lambda *a:({'2026-10-01':doc(11)},[],[]))
    monkeypatch.setattr(monitor,'_project_dir',fail)
    monkeypatch.setattr(cash.monthly,'_budget_files',fail)
    result=cash.for_project('Synthetic','2026-11-14')
    assert result['budget']==40000 and result['paid_known_part']==11
    assert result['balance_after_observed_payments']==39989
    assert result['coverage']['source_errors']['rss']=='unavailable'


def test_missing_fm_preserves_independent_budget_paid_fact(saved,monkeypatch):
    monkeypatch.setattr(cash.source,'_copy',fail)
    monkeypatch.setattr(cash.rss_source,'_rss_copy',fail)
    monkeypatch.setattr(cash,'_budget_listing',lambda *a:([],('stable',)))
    monkeypatch.setattr(cash,'_budget_months',lambda *a:({'2026-10-01':doc(11)},[],[]))
    result=cash.for_project('Synthetic','2026-11-14')
    assert result['budget'] is None and result['paid_known_part']==11
    assert result['balance_after_observed_payments'] is None


def test_readonly_missing_project_does_not_create_namespace(tmp_path,monkeypatch):
    base=tmp_path/'saved';base.mkdir();monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',base)
    assert cash.for_project('Missing','2026-11-14')['state']=='missing'
    assert list(base.iterdir())==[]


def test_budget_listing_uses_native_upload_order_without_convenience_mkdir(saved):
    folder=saved/'budget';folder.mkdir()
    a=folder/'2026-10-01_2026-10_2026-10.xlsx';b=folder/'2026-10-02_2026-10_2026-10.xlsx'
    a.write_bytes(b'a');b.write_bytes(b'b')
    (folder/'uploads.json').write_text(json.dumps({a.name:'2026-11-02',b.name:'2026-11-01'}))
    paths,stamp=cash._budget_listing(saved,'2026-11-14')
    assert paths==[a,b] and stamp


def test_unreadable_older_budget_does_not_erase_newer_known_months(tmp_path,monkeypatch):
    newer=tmp_path/'2026-11-01_2026-10_2026-10.xlsx';bad=tmp_path/'2026-09-01_2026-09_2026-09.xlsx'
    older=tmp_path/'2026-08-01_2026-09_2026-09.xlsx'
    for p in [newer,bad,older]:p.write_bytes(p.name.encode())
    def parse(raw):
        if b'2026-09-01' in raw:raise ValueError('bad')
        month='2026-10-01' if b'2026-11-01' in raw else '2026-09-01'
        return {'months':{month:{'extra':{'admin':{'fact':12,'plan':9}}}}}
    monkeypatch.setattr(cash.monthly,'read_budget',parse)
    got,_,errors=cash._budget_months([newer,bad,older])
    assert got['2026-10-01']['fact']==12 and '2026-09-01' not in got and len(errors)==1


def test_symlink_budget_is_not_read_and_does_not_hide_fm(saved,tmp_path,monkeypatch):
    outside=tmp_path/'outside';outside.mkdir();(saved/'budget').symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr(cash.rss_source,'_rss_copy',fail)
    result=cash.for_project('Synthetic','2026-11-14')
    assert result['budget']==40000 and result['paid_observed_net'] is None
    assert result['coverage']['source_errors']['budget_files']=='unavailable'


def test_ui_cash_is_primary_source_pills_collapsed_and_unknown_never_zero():
    model=calc(bdds={'2026-10-01':doc(3)},budget=2_000_000)
    html=cash.render(model,'<div class="source-three">three source pills</div>')
    assert html.index('Бюджет АХР по сохранённой ФМ')<html.index('<details class="admin-fm-source">')
    assert '2,00 млн ₽' in html and '1 999 997,00 ₽' in html
    assert cash.tiles({})[0]['value']=='нет данных'
    assert 'font-size:20px' not in cash.render(model,show_tiles=False)


@pytest.mark.parametrize('width',[390,1440])
def test_real_monitor_page_shows_cash_four_before_source_context_and_clears_it(width,tmp_path):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    import developaid_admin_expenses as admin
    from test_admin_expenses_source_scope import workbook
    source=admin.read(workbook(None),cut='2026-11-14')
    model=calc(bdds={'2026-10-01':doc(3_000_000)},budget=300_000_000)
    view={'admin_expenses_cash':model,'admin_expenses':source,
          'admin_expenses_html':cash.render(model,admin.render(source)),'dashboard':{}}
    with browser_page(width) as (page,responses,errors):
        page.evaluate("v=>{currentView=v;renderDash(v);selectMonitorTab('money')}",view)
        card=page.locator('#adminExpensesCard');expect(card).to_be_visible()
        assert card.locator('.admin-expenses-cash > div > div').count()==4
        assert card.locator('details.admin-fm-source').evaluate('(e)=>!e.open')
        expect(card).to_contain_text('300,00 млн ₽')
        expect(card).to_contain_text('297,00 млн ₽')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        for element in card.locator('.admin-expenses-cash > div > div').all():
            assert element.evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        page.screenshot(path=str(tmp_path/f'cash-{width}.png'),full_page=True)
        page.evaluate("()=>{const e=document.getElementById('project');e.value='Other synthetic';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        expect(card).to_be_hidden()
        assert page.evaluate('!currentView || !currentView.admin_expenses_cash')
        assert not errors


def test_pdf_cash_four_on_cover_and_legacy_source_context_is_separate(tmp_path,monkeypatch):
    import pymupdf
    import developaid_management_report as report
    import developaid_admin_expenses as admin
    from browser import chromium_or_skip
    from market_search import report_pdf
    from test_management_report_analytics import _full
    from test_admin_expenses_source_scope import workbook
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    monkeypatch.setenv('DATA_DIR',str(tmp_path/'data'))
    data=_full();model=calc(bdds={'2026-09-01':doc(3_000_000)},budget=300_000_000)
    data['admin_expenses_cash']=model
    data['admin_expenses']=admin.read(workbook(None),cut='2026-11-14')
    html=report.render_html(data)
    cash_section=html.split('<section class="admin-expenses-cash">',1)[1].split('<details',1)[0]
    assert 'font-size:20px' not in cash_section  # cash tiles only in report cover
    text=report.render_text(data)
    for _,label in cash.FIELDS:assert label in text
    assert '<b>Административные расходы · статья 2.6</b>' not in text
    document=report_pdf.document(html,style=report.REPORT_STYLE,title='Synthetic AHR cash')
    raw=report_pdf.render(document,footer='Synthetic',executable_path=str(chromium_or_skip()))
    (tmp_path/'cash-report.pdf').write_bytes(raw)
    pdf=pymupdf.open(stream=raw,filetype='pdf')
    cover=' '.join(pdf[0].get_text().split())
    for _,label in cash.FIELDS:assert label.casefold() in cover.casefold()
    assert '300,00 млн ₽' in cover and '297,00 млн ₽' in cover
    assert any(hit.y0<120 for hit in pdf[1].search_for('Стройка'))


@pytest.mark.parametrize('sheet',['факт','Реестр платежей','статьи_БДДС'])
def test_generic_proposal_keeps_all_columns_despite_reusing_native_sheet_name(sheet):
    book=openpyxl.Workbook();ws=book.active;ws.title=sheet
    for column in range(6,46):
        ws.cell(1,column,'январь');ws.cell(3,column,10);ws.cell(4,column,1)
    ws.cell(3,5,'Материал');ws.cell(4,5,'СМР')
    stream=io.BytesIO();book.save(stream);book.close()
    result=actuals.read_proposal(io.BytesIO(stream.getvalue()),sheet,'2024-01','2.2.2.6')
    assert len(result['months'])==40 and result['payments_total']==440
