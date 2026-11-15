"""Source-bound owner classification never overrides money or known XLSX codes."""
import datetime as dt
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import developaid_finance_allocations as allocations
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_finance_money_bridge import source

DAY = '2026-11-09'
PROJECT = 'Synthetic allocation'


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    monkeypatch.setattr(allocations, '_now', lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc))
    raw = source()
    path = monitor._project_dir(PROJECT) / 'baseline' / 'finance.xlsx'
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    state = allocations.view(PROJECT, DAY)
    assert len(state['rows']) == 1
    return path, raw, state


def assign(state, code='2.6', **extra):
    return allocations.apply(PROJECT, state['source_sha256'], state['revision'],
        [{'row_id': state['rows'][0]['row_id'], 'bank_code': code, **extra}],
        'Owner instructed the selected unclassified payment to this bank article.', DAY)


def canonical(model):
    return dashboard._own_money(model['budget_composition'], {'1': 0, '2': 200_000, '3': 50_000},
        {c: {'total': 0, 'borrowed': 0} for c in ('1', '2', '3')}, ['1', '2', '3'], dt.date.fromisoformat(DAY),
        chapter_flow=model['chapter_flow'])


def test_save_reload_provenance_and_global_gap_are_preserved(stored):
    path, raw, state = stored
    base = dashboard._read_finance_baseline(path)
    before = canonical(base)
    saved = assign(state)
    assert saved['revision'] == 1
    model = allocations.qualify(PROJECT, base, DAY)
    own = canonical(model)
    assert own['admin']['by_chapter']['2']['total'] == 282_500
    assert own['admin']['by_chapter']['3']['total'] == 77_500
    assert own['admin']['unallocated'] == {'total': 0, 'paid': 0, 'to_pay': 0}
    assert own['admin']['allocation_known']
    assert len(own['admin']['owner_decisions']) == 1
    r = own['reconciliation']
    for field in ('budget', 'paid_at_cut', 'available_bank_limit', 'calculated_additional'):
        assert r[field] == before['reconciliation'][field]
    assert r['budget'] == 360_000 and r['calculated_additional'] == 110_000
    assert r['admin_expenses']['owner_decision_count'] == 1
    assert 'по решению владельца' in r['admin_expenses']['note']
    proofs = model['budget_composition']['admin_items'][0]['money_allocation']['proofs']
    rows = [row for proof in proofs for row in proof['sources']]
    assert next(row for row in rows if row['row'] == 2 and row['sheet'] == 'History')['bank_code'] == '2.6'
    assert next(row for row in rows if row['row'] == 3 and row['sheet'] == 'History')['bank_code'] == '3.1'
    manual = next(row for row in rows if row['owner_decision'])
    assert manual['raw_bank_code'] == '' and manual['bank_code_origin'] == 'owner_instruction'
    assert manual['owner_decision']['actor'] == 'administrator'
    assert path.read_bytes() == raw
    assert allocations.view(PROJECT, DAY)['rows'][0]['decision']['bank_code'] == '2.6'


def test_historical_cut_revocation_and_version_change_fail_closed(stored):
    path, raw, state = stored
    assign(state)
    base = dashboard._read_finance_baseline(path)
    assert canonical(allocations.qualify(PROJECT, base, '2026-11-08'))['admin']['unallocated']['total'] == 7500
    new = allocations.view(PROJECT, DAY)
    revoked = assign(new, '')
    assert revoked['revision'] == 2
    assert canonical(allocations.qualify(PROJECT, base, DAY))['admin']['unallocated']['total'] == 7500
    assign(revoked)
    path.write_bytes(raw + b' changed version')
    current = dashboard._read_finance_baseline(path)
    assert allocations.active(PROJECT, current['budget_composition']['source_sha256'], DAY)['assignments'] == {}
    assert canonical(allocations.qualify(PROJECT, current, DAY))['admin']['unallocated']['total'] == 7500
    with pytest.raises(allocations.AllocationProblem) as e:
        assign(state)
    assert e.value.status == 409


def test_only_concrete_blank_fact_source_cells_can_be_selected(stored):
    path, raw, state = stored
    model = dashboard._read_finance_baseline(path)
    known = model['budget_composition']['admin_items'][0]['money_allocation']['proofs'][0]['sources'][0]
    wrong_id = allocations.source_cell_id(state['source_sha256'], known['sheet'], known['row'], known['bank_column'], known['amount_column'])
    with pytest.raises(allocations.AllocationProblem) as e:
        allocations.apply(PROJECT, state['source_sha256'], 0, [{'row_id': wrong_id, 'bank_code': '3.1'}], 'Owner decision', DAY)
    assert e.value.status == 409
    for extra in ({'amount': 999}, {'model_amount': 999}):
        with pytest.raises(allocations.AllocationProblem):
            assign(state, **extra)
    assert not list((monitor._project_dir(PROJECT) / 'finance_allocations').glob('*.json'))
    assert path.read_bytes() == raw


def test_revision_race_and_source_race_preserve_the_first_valid_event(stored, monkeypatch):
    path, raw, state = stored
    def attempt(code):
        try:
            return assign(state, code)['revision']
        except allocations.AllocationProblem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['2.6', '3.1']))
    assert sorted(results) == [1, 409]
    current = allocations.view(PROJECT, DAY)
    read = allocations._read_model
    def replace_during_validation(data, assignments=None):
        value = read(data, assignments)
        path.write_bytes(raw + b' newer')
        return value
    monkeypatch.setattr(allocations, '_read_model', replace_during_validation)
    with pytest.raises(allocations.AllocationProblem) as e:
        assign(current)
    assert e.value.status == 409
    assert len(list((monitor._project_dir(PROJECT) / 'finance_allocations').glob('*.json'))) == 1


def test_malformed_audit_never_reveals_an_older_decision(stored):
    path, raw, state = stored
    assign(state)
    folder = monitor._project_dir(PROJECT) / 'finance_allocations'
    (folder / '000000000002.json').write_text('{not valid json')
    model = allocations.qualify(PROJECT, dashboard._read_finance_baseline(path), DAY)
    assert model['allocation_problem']
    assert canonical(model)['admin']['unallocated']['total'] == 7500
    assert canonical(model)['reconciliation']['budget'] == 360_000
    assert path.read_bytes() == raw


@pytest.mark.parametrize('code', ['4.1', '2', '-2.6', '2.6<script>'])
def test_invalid_target_or_duplicate_selection_cannot_create_an_event(stored, code):
    _, _, state = stored
    with pytest.raises(allocations.AllocationProblem):
        assign(state, code)
    row = {'row_id': state['rows'][0]['row_id'], 'bank_code': '2.6'}
    with pytest.raises(allocations.AllocationProblem):
        allocations.apply(PROJECT, state['source_sha256'], 0, [row, row], 'Owner decision', DAY)


def test_qualified_cache_is_revision_bound_and_never_shares_mutable_values(stored, monkeypatch):
    path, _, state = stored
    assign(state)
    base = dashboard._read_finance_baseline(path)
    allocations._QUALIFIED_CACHE.clear()
    read = allocations._read_model
    calls = []
    def count(*a, **kw):
        calls.append(1)
        return read(*a, **kw)
    monkeypatch.setattr(allocations, '_read_model', count)
    first = allocations.qualify(PROJECT, base, DAY)
    first['budget_composition']['total'] = -1
    second = allocations.qualify(PROJECT, base, DAY)
    assert len(calls) == 1 and second['budget_composition']['total'] == 360_000
    current = allocations.view(PROJECT, DAY)
    assign(current, '3.1')
    changed = allocations.qualify(PROJECT, base, DAY)
    assert canonical(changed)['admin']['by_chapter']['3']['total'] == 85_000
    assert second['source'] == base['source']


def test_normal_baseline_replacement_uses_the_same_source_lock(stored):
    import threading
    path, raw, _ = stored
    started = threading.Event()
    def replace():
        started.set()
        return monitor.replace_finance_baseline(PROJECT, raw, DAY, 'new.xlsx')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with allocations.source_lock(PROJECT):
            future = pool.submit(replace)
            assert started.wait(2)
            assert not future.done()
            assert path.read_bytes() == raw
        assert future.result(timeout=5)['replaced']


@pytest.mark.parametrize('width', [390, 1440])
def test_owner_provenance_and_unchanged_total_reach_monitor_html_and_pdf(stored, width):
    import developaid_management_report as report
    from browser import chromium_or_skip
    from market_search import report_pdf
    from playwright.sync_api import sync_playwright
    from test_monitor_cumulative_controls import browser_page
    import pymupdf

    path, _, state = stored
    assign(state)
    own = canonical(allocations.qualify(PROJECT, dashboard._read_finance_baseline(path), DAY))
    r = own['reconciliation']
    note = 'Банковское отнесение 1 строки — по решению владельца.'
    with browser_page(width) as (page, responses, errors):
        page.evaluate('''r=>{currentView={dashboard:{funding:{known:true,reconciliation:r}}};
            renderDash(currentView);selectMonitorTab('money');}''', r)
        detail = page.locator('.funding-admin-breakdown')
        detail.locator('summary').click()
        assert note in detail.inner_text()
        assert 'Банковская статья не уточнена' not in detail.inner_text()
        assert 'Статьи главы 2' in detail.inner_text() and 'Статьи главы 3' in detail.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
    limit = {'own_money':own,'reconciliation':r}
    html = report._funding_html({'kind':'week','funding':{'state':'ok','limit':limit,'rss':None,
        'draws':dict.fromkeys(('period','month','total')),'interest':dict.fromkeys(('period','month','total'))}})
    assert note in html and '282 500 ₽' in html and '77 500 ₽' in html
    assert note in report._own_money_lines(limit)
    if width == 1440:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
            try:
                page = browser.new_page()
                page.set_content(report_pdf.document(html,style=report.REPORT_STYLE,title='Synthetic owner decision'))
                document = pymupdf.open(stream=page.pdf(format='A4'),filetype='pdf')
                text = ' '.join(' '.join(p.get_text().split()) for p in document)
                assert note in text and '282 500 ₽' in text and '77 500 ₽' in text
            finally:
                browser.close()


def test_legacy_schedule_payment_baseline_writer_uses_the_same_lock_and_sha_fence(stored):
    import threading
    from test_monitor_keeps_every_snapshot import _baseline_book
    path, raw, state = stored
    assign(state)
    changed = raw + b' changed financial source'
    started = threading.Event()
    def upload():
        started.set()
        return monitor.store_schedule(PROJECT, _baseline_book(), changed, DAY)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with allocations.source_lock(PROJECT):
            future = pool.submit(upload)
            assert started.wait(2)
            assert not future.done()
            assert path.read_bytes() == raw
        assert future.result(timeout=5)['baseline']
    assert path.read_bytes() == changed
    new = dashboard._read_finance_baseline(path)
    qualified = allocations.qualify(PROJECT, new, DAY)
    assert canonical(qualified)['admin']['unallocated']['total'] == 7500
    assert not canonical(qualified)['admin']['owner_decisions']
