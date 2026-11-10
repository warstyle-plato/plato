"""One Monitor view retains the active GPR and canonical AHR finance together."""
import datetime as dt
import json

import pytest

import developaid_finance_management as management
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_finance_money_bridge import source
from test_finance_owner_allocations import canonical
from test_monitor_active_plan_note import approve
from test_monitor_cumulative_controls import browser_page
from test_schedule_completed_facts import site, book, PROJECT  # noqa: F401

DAY = '2026-11-10'


@pytest.fixture
def combined_view(site, monkeypatch):
    monkeypatch.setattr(management, '_now', lambda: dt.datetime(2026, 11, 10, 12,
                                                              tzinfo=dt.timezone.utc))
    approve(book('Единственный действующий план', .4, '2027-06-30'), scope='remaining_work')
    path = monitor._project_dir(PROJECT) / 'baseline' / 'finance.xlsx'
    path.write_bytes(source(future_bank='3.1'))
    state = management.view(PROJECT, DAY)
    management.apply(PROJECT, state['source_sha256'], state['revision'],
                     [item['item_id'] for item in state['rows']], '2.6',
                     'Owner: all economic AHR fact and future plan, management article2.6.', DAY)
    own = canonical(management.qualify(PROJECT, dashboard._read_finance_baseline(path), DAY))
    view = json.loads(json.dumps(monitor.build(PROJECT, DAY), default=str, ensure_ascii=False))
    view['dashboard']['funding'] = {'known': True, 'reconciliation': own['reconciliation'],
                                   'own_money': own}
    # Canonical finance must prevail over the old construction fallback.
    view['dashboard']['construction'] = {'approved': 9_000_000}
    return view


@pytest.mark.parametrize('width', [390, 1440])
def test_one_view_shows_current_plan_and_management_ahr_without_changing_bank_sources(combined_view, width):
    from playwright.sync_api import expect
    with browser_page(width) as (page, responses, errors):
        page.route('**/monitor/view', lambda route: route.fulfill(json=combined_view))
        page.route('**/monitor/daily/summary**', lambda route: route.fulfill(json={}))
        page.locator('#project').fill(PROJECT)
        page.locator('#cut').fill(DAY)
        page.locator('#refresh').click()
        expect(page.locator('#activePlan')).to_be_visible()
        expect(page.locator('#activePlan')).to_contain_text('окончательный план')
        sha = combined_view['schedule']['approved_plan']['source_sha256'][:12]
        expect(page.locator('#activePlan')).to_contain_text(sha)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#moneyTab').click()
        expect(page.locator('#activePlan')).to_be_visible()
        detail = page.locator('.funding-admin-breakdown')
        expect(detail.locator('summary')).to_contain_text('управленческая статья 2.6')
        detail.locator('summary').click()
        expect(detail).to_contain_text('Статьи главы 3')
        expect(detail).to_contain_text('Банковская статья не уточнена')
        values = page.locator('#kpis .kpi').evaluate_all(
            "rows=>Object.fromEntries(rows.map(x=>[x.querySelector('.l').textContent,x.querySelector('.n').textContent]))")
        assert values['Утверждённый бюджет'] == '0,4 млн ₽'
        assert 'Дефицит · РСС' not in values
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors


@pytest.mark.parametrize('changed', ['project', 'cut'])
def test_a_late_combined_view_cannot_restore_another_project_or_date(combined_view, changed):
    from playwright.sync_api import expect
    with browser_page(390) as (page, responses, errors):
        page.locator('#project').fill(PROJECT)
        page.locator('#cut').fill(DAY)
        page.evaluate("""()=>{
          const original=post;
          post=(path,body)=>path==='/monitor/view'
            ?new Promise(resolve=>{window.lateCombinedView=resolve})
            :original(path,body);
          window.combinedRefresh=refresh();
        }""")
        page.wait_for_function("typeof window.lateCombinedView==='function'")
        page.locator('#'+changed).fill('Другой проект' if changed == 'project' else '2026-11-11')
        page.evaluate('v=>window.lateCombinedView(v)', combined_view)
        page.evaluate('()=>window.combinedRefresh')
        expect(page.locator('#activePlan')).to_be_hidden()
        expect(page.locator('#financeCard')).to_be_hidden()
        assert page.evaluate('currentView===null')
        assert not errors
