"""The owner can qualify old stored FM bytes without rewriting the workbook."""
import datetime as dt
import hashlib
import io

import openpyxl
import pytest

import developaid_finance_units as units
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
import developaid_admin_expenses as admin
import developaid_budget_funding_source as proof
from test_the_approved_budget_says_what_it_is_made_of import _finmodel

PROJECT = 'Учебная финмодель без подписи единиц'


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    book = openpyxl.load_workbook(io.BytesIO(_finmodel()))
    sheet = book['cf_1_new']
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and 'руб.' in cell.value:
                cell.value = None
    out = io.BytesIO(); book.save(out)
    raw = out.getvalue()
    monitor.replace_finance_baseline(PROJECT, raw, '2026-10-01')
    return raw, monitor._project_dir(PROJECT)/'baseline'/'finance.xlsx'


def test_thousands_restore_budget_and_admin_from_the_same_declared_source(stored):
    raw, path = stored
    before = dashboard._finance_baseline(PROJECT)
    assert not before['known']
    assert admin.for_project(PROJECT, '2026-10-31')['total'] is None
    source = units.configure(PROJECT)
    units.configure(PROJECT, 'тыс. руб.', expected_source_sha256=source['source_sha256'])
    result = dashboard._finance_baseline(PROJECT)
    assert result['known']
    expected = dashboard._read_finance_baseline(io.BytesIO(_finmodel()))
    assert result['approved'] == expected['approved']
    assert result['budget_composition']['unit_scale'] == 1000
    evidence = result['budget_composition']['unit_evidence']
    assert evidence['basis'] == 'owner_declaration'
    assert evidence['header_evidence']['state'] == 'missing'
    assert admin.for_project(PROJECT, '2026-10-31')['source']['unit_factor_to_rubles'] == 1000
    captured = proof._finance(raw, monitor.finance_baseline_meta(PROJECT))
    assert captured['observations']['total']['rubles'] == result['approved']
    assert path.read_bytes() == raw


def test_declaration_is_bound_to_exact_bytes_and_does_not_survive_replacement(stored):
    raw, _ = stored
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='изменилась'):
        units.configure(PROJECT, 'тыс. руб.', expected_source_sha256='f'*64)
    units.configure(PROJECT, 'тыс. руб.', expected_source_sha256=digest)
    monitor.replace_finance_baseline(PROJECT, raw, '2026-10-02')
    assert units.configure(PROJECT)['money_unit'] is None
    assert not dashboard._finance_baseline(PROJECT)['known']


def test_another_file_and_conflicting_header_cannot_inherit_the_declaration(stored):
    raw, _ = stored
    digest = hashlib.sha256(raw).hexdigest()
    meta = {'money_unit':{'basis':'owner_declaration','unit':'тыс. руб.','source_sha256':digest}}
    missing = {'state':'missing','recognized_unit':None}
    assert units.resolve(missing, meta, 'f'*64) == missing
    ambiguous = {'state':'ambiguous','recognized_unit':None}
    assert units.resolve(ambiguous, meta, digest) == ambiguous
    result = units.resolve({'state':'observed','recognized_unit':'руб.'}, meta, digest)
    assert result['state'] == 'ambiguous' and result['recognized_unit'] is None


def test_rss_facts_survive_an_unknown_financial_budget(tmp_path, monkeypatch):
    from test_funding_strict_source_readers import source_case
    rss, _ = source_case(tmp_path, monkeypatch, [(dt.date(2026,10,31),20_000,'2.6')])
    monkeypatch.setattr(dashboard, '_finance_for_cut', lambda *_: {'known':False,'reason':'Единицы ФМ не указаны.'})
    result = dashboard._funding_risk('demo', rss, dt.date(2026,10,31), {})
    assert not result['known'] and result['reason'] == 'Единицы ФМ не указаны.'
    bank = result['bank_observations']
    assert bank['bank_limit'] > 0 and bank['paid_actual'] == 20_000
    assert bank['paid_borrowed'] == 20_000
    assert bank['available_bank_limit'] == bank['bank_limit']-20_000
    import developaid_management_report as report
    report_data = dict(end='2026-10-31',kind='month',funding={'state':'ok','limit':result})
    cards = {r['label']:r for r in report.tiles(report_data)}
    assert cards['Утверждённый бюджет']['value'] == 'нет данных'
    assert cards['Лимит банка']['value'] == report._rub(bank['bank_limit'])
    assert cards['Осталось по смете после всех оплат']['value'] == report._rub(bank['available_bank_limit'])


def test_unit_endpoint_requires_admin_and_matching_saved_source(stored, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY','synthetic-finance-unit-key')
    client = TestClient(main.core.app)
    raw, _ = stored
    payload = dict(project=PROJECT,unit='тыс. руб.',expected_source_sha256=hashlib.sha256(raw).hexdigest())
    assert client.post('/monitor/finance-unit',json=payload).status_code == 403
    assert units.configure(PROJECT)['money_unit'] is None
    payload['key'] = 'synthetic-finance-unit-key'
    assert client.post('/monitor/finance-unit',json=dict(payload,expected_source_sha256='f'*64)).status_code == 400
    response = client.post('/monitor/finance-unit',json=payload)
    assert response.status_code == 200 and response.json()['money_unit']['unit'] == 'тыс. руб.'
    assert dashboard._finance_baseline(PROJECT)['budget_composition']['unit_scale'] == 1000


@pytest.mark.parametrize('width',[390,1440])
def test_monitor_keeps_bank_facts_visible_when_budget_units_are_unknown(width):
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    bank = dict(scope='rss_chapters_1_2_3',bank_limit=9_000_000.,paid_actual=2_000_000.,
                paid_borrowed=1_000_000.,available_bank_limit=7_000_000.,note='По РСС, главы 1–3.')
    with browser_page(width) as (page, _, errors):
        page.evaluate('bank=>{currentView={dashboard:{funding:{known:false,reason:"Единицы ФМ не указаны",bank_observations:bank}}};renderDash(currentView);selectMonitorTab("money")}',bank)
        host = page.locator('.rss-bank-observations')
        expect(host).to_be_visible()
        expect(host).to_contain_text('9 млн ₽')
        expect(host).to_contain_text('7 млн ₽')
        expect(host).to_contain_text('главы 1–3')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('value',[[],{},None,True])
def test_corrupt_unit_metadata_cannot_crash_or_establish_an_unbound_scale(value):
    header = {'state':'missing','recognized_unit':None}
    declaration = {'money_unit':{'basis':'owner_declaration','source_sha256':'a'*64,'unit':value}}
    assert units.resolve(header,declaration,'a'*64) == header
    declaration['money_unit'].update(unit='тыс. руб.',source_sha256=None)
    assert units.resolve(header,declaration,None) == header


def test_form_sends_the_unit_only_for_the_file_shown_before_confirmation():
    from test_monitor_cumulative_controls import browser_page
    from playwright.sync_api import expect
    calls = []
    with browser_page(1440) as (page,_,errors):
        def respond(route):
            body = route.request.post_data_json
            calls.append(body)
            if not body.get('unit'):
                return route.fulfill(json={'source_sha256':'a'*64,'file_name':'Показанная ФМ.xlsx','taken_at':'2026-10-01'})
            return route.fulfill(status=400,json={'detail':'Финансовая модель изменилась; обновите данные.'})
        page.route('**/monitor/finance-unit',respond)
        page.evaluate("selectMonitorTab('data');$('setupCard').classList.add('open')")
        page.locator('#financeUnitLoad').click()
        expect(page.locator('#financeUnitSource')).to_contain_text('Показанная ФМ.xlsx')
        page.select_option('#financeUnit','тыс. руб.')
        page.locator('#financeUnitSave').click()
        expect(page.locator('#financeUnitMsg')).to_contain_text('изменилась')
        assert len(calls)==2 and calls[1]['expected_source_sha256']=='a'*64
        assert calls[1]['unit']=='тыс. руб.'
        assert not errors
