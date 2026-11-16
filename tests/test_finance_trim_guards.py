"""Trim-specific strict-money, journal durability and nonfinance-card regressions."""
import datetime as dt
import io
import os
import stat

import openpyxl
import pytest

import developaid_actuals as actuals
import developaid_finance_allocations as bank
import developaid_finance_management as management
import developaid_monitor as monitor
import developaid_monitor_dashboard as dashboard
from test_finance_money_bridge import source as source_book
from test_the_approved_budget_says_what_it_is_made_of import _finmodel

DAY = '2026-11-09'
PROJECT = 'Synthetic durable finance trim'


@pytest.fixture
def saved_source(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path / 'monitor')
    now = lambda: dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(bank, '_now', now)
    monkeypatch.setattr(management, '_now', now)
    path = monitor._project_dir(PROJECT) / 'baseline' / 'finance.xlsx'
    path.parent.mkdir(parents=True)
    path.write_bytes(source_book(future_bank='3.1'))
    return path


def request(family):
    if family == 'bank':
        state = bank.view(PROJECT, DAY)
        return bank.apply, {'project': PROJECT, 'source_sha256': state['source_sha256'],
            'revision': state['revision'], 'assignments': [{'row_id': state['rows'][0]['row_id'], 'bank_code': '2.6'}],
            'note': 'Synthetic owner classification, unchanged source amounts.', 'cut': DAY}
    state = management.view(PROJECT, DAY)
    return management.apply, {'project': PROJECT, 'source_sha256': state['source_sha256'],
        'revision': state['revision'], 'item_ids': [row['item_id'] for row in state['rows']],
        'management_article': '2.6', 'note': 'Synthetic owner management article.', 'cut': DAY}


@pytest.mark.parametrize('family,journal', [('bank', 'finance_allocations'), ('management', 'finance_management')])
def test_new_journal_syncs_parent_then_event_file_then_final_directory(saved_source, monkeypatch, family, journal):
    apply, payload = request(family)
    before = saved_source.read_bytes()
    events = []
    fsync, replace = os.fsync, os.replace
    def sync(descriptor):
        kind = 'directory' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file'
        events.append((kind, os.readlink('/proc/self/fd/' + str(descriptor))))
        return fsync(descriptor)
    def rename(source, target):
        events.append(('rename', str(target)))
        return replace(source, target)
    monkeypatch.setattr(os, 'fsync', sync)
    monkeypatch.setattr(os, 'replace', rename)
    assert apply(**payload)['revision'] == 1
    rename_index = next(i for i, event in enumerate(events) if event[0] == 'rename')
    assert any(kind == 'file' for kind, _ in events[:rename_index])
    assert any(kind == 'directory' and path == str(saved_source.parent.parent)
               for kind, path in events[:rename_index])
    assert any(kind == 'directory' and path.endswith('/' + journal)
               for kind, path in events[rename_index + 1:])
    assert saved_source.read_bytes() == before


@pytest.mark.parametrize('family,journal', [('bank', 'finance_allocations'), ('management', 'finance_management')])
def test_directory_sync_failure_after_append_is_unknown_and_stale_CAS_cannot_repeat(saved_source, monkeypatch, family, journal):
    apply, payload = request(family)
    original = bank._sync_directory
    def fail(folder):
        if folder.name == journal:
            raise bank.AllocationProblem('Synthetic uncertain directory durability', 503)
        return original(folder)
    monkeypatch.setattr(bank, '_sync_directory', fail)
    with pytest.raises(bank.AllocationProblem) as caught:
        apply(**payload)
    assert caught.value.status == 503
    folder = saved_source.parent.parent / journal
    files = list(folder.glob('[0-9]*.json'))
    assert len(files) == 1
    raw = files[0].read_bytes()
    with pytest.raises(bank.AllocationProblem) as repeated:
        apply(**payload)
    assert repeated.value.status == 409
    assert len(list(folder.glob('[0-9]*.json'))) == 1 and files[0].read_bytes() == raw


@pytest.mark.parametrize('family', ['bank', 'management'])
def test_parent_directory_sync_failure_stops_before_an_event(saved_source, monkeypatch, family):
    apply, payload = request(family)
    real = os.fsync
    def fail(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError('SYNTHETIC-PRIVATE-FILESYSTEM-CANARY')
        return real(descriptor)
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(bank.AllocationProblem) as caught:
        apply(**payload)
    assert caught.value.status == 503 and 'CANARY' not in str(caught.value)
    assert not list(saved_source.parent.parent.glob('finance_*/*[0-9].json'))


@pytest.mark.parametrize('amount,expected', [('1\u202f234,50', 1234500), ('1\u00a0234,50', 1234500),
    ('0', 0), ('-3,5', -3500), (None, None), ('NaN', None), ('1e308', None), (True, None)])
def test_local_FM_money_adapter_preserves_exact_knownness_and_protected_legacy_parser(amount, expected):
    raw = io.BytesIO(_finmodel({'2.2.1': ('Synthetic leaf', amount, 0, amount)}))
    raw.name = 'synthetic-strict-money.xlsx'
    got = dashboard._read_finance_baseline(raw)
    assert got['known']
    comp = got['budget_composition']
    assert comp['known_fields']['total'] is (expected is not None)
    canonical = dashboard._own_money(comp, {ch: 0 for ch in ('1', '2', '3')},
        {ch: {'total': 0, 'borrowed': 0} for ch in ('1', '2', '3')}, ['1', '2', '3'], dt.date.fromisoformat(DAY),
        chapter_flow=got['chapter_flow'])['reconciliation']
    assert canonical['budget'] == expected
    assert canonical['confirmed_additional'] is None
    assert not canonical['financial_acceptance_performed']
    assert actuals._money('1\u202f234,50') == 0.0


def test_missing_model_credit_readings_are_not_known_zero():
    book = openpyxl.load_workbook(io.BytesIO(_finmodel({'2.2.1': ('Synthetic leaf', 10, 2, 8)})))
    sheet = book['cf_1_new']
    sheet['C30'], sheet['D30'] = '3.1.1.1.2', dashboard._FM_CREDIT_LABEL
    sheet['I30'], sheet['J30'], sheet['K30'], sheet['N30'] = None, 'NaN', True, None
    data = io.BytesIO(); book.save(data); book.close(); data.name = 'synthetic-credit-unknown.xlsx'
    got = dashboard._read_finance_baseline(data)
    assert got['credit_plan']['total'] is None and got['credit_plan']['drawn'] is None
    assert got['credit_plan']['plan'] is None
    assert all(value is None for value in got['credit_plan']['monthly'].values())
    assert got['budget_composition']['known_fields']['total'] and got['budget_composition']['total'] == 10000


@pytest.mark.parametrize('width', [390, 1440])
def test_finance_KPI_adaptation_keeps_current_and_future_nonfinance_nodes_and_handlers(width):
    from test_monitor_cumulative_controls import browser_page
    with browser_page(width) as (page, _, errors):
        result = page.evaluate('''()=>{
          $('kpis').innerHTML=kpi('Готовность учтённых работ','42%','')+kpi('Новая каноническая оценка','30.05.2028','')
            +kpi('Резерв · РСС','1','')+kpi('Дефицит · РСС','2','');
          const retained=$('kpis').firstElementChild;let clicks=0;
          retained.addEventListener('click',()=>{clicks++});
          renderFundingReconciliationKpis({reconciliation:{display_rows:[{label:'Утверждённый бюджет',value:null,note:'unknown'}]}});
          retained.click();
          return {labels:[...$('kpis').children].map(e=>e.querySelector('.l')?.textContent),
            same:retained.parentNode===$('kpis'),clicks};
        }''')
        assert result == {'labels': ['Утверждённый бюджет', 'Готовность учтённых работ', 'Новая каноническая оценка'],
                          'same': True, 'clicks': 1}
        assert not errors
