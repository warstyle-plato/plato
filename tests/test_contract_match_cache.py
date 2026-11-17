"""Pure matching reuse cannot freeze source/owner/cut decisions or change DTOs."""
import concurrent.futures
import contextvars
import copy
import datetime as dt
import inspect
import json
import threading

from fastapi.encoders import jsonable_encoder
import openpyxl
import pytest

import developaid_contract_match_cache as cache
import developaid_monitor as monitor
import developaid_monitor_contract_links as links
import developaid_monitor_contract_risk as risk
import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_archive_union import grown
from test_contracts_from_cumulative_headers import archive, ks


def test_cache_is_call_local_nested_and_cleans_up_after_failure():
    calls = []
    def compute():
        calls.append(1)
        return 'normalized'
    for _ in range(2):
        assert cache.remember('party', ('source',), compute) == 'normalized'
    assert len(calls) == 2 and cache._current() is None
    with pytest.raises(ValueError, match='synthetic'):
        with cache.scope() as first:
            for _ in range(3):
                assert cache.remember('party', ('source',), compute) == 'normalized'
            with cache.scope() as nested:
                assert nested is first
            with pytest.raises(RuntimeError, match='nested'):
                with cache.scope() as nested:
                    assert nested is first
                    raise RuntimeError('nested')
            assert cache._current() is first
            assert len(calls) == 3
            def failed():
                raise RuntimeError('compute')
            for _ in range(2):
                with pytest.raises(RuntimeError, match='compute'):
                    cache.remember('party', ('failed',), failed)
            assert cache.remember('party', ('failed',), lambda:'recovered') == 'recovered'
            raise ValueError('synthetic')
    assert cache._current() is None
    with cache.scope() as second:
        assert second is not first and not second.entries
        cache.remember('party', ('source',), compute)
    assert len(calls) == 4


def test_entry_and_byte_admission_fall_back_without_changing_results(monkeypatch):
    monkeypatch.setattr(cache, 'MAX_ENTRIES', 2)
    calls = []
    with cache.scope() as state:
        for text in ('one', 'two', 'three', 'three'):
            assert cache.remember('party', (text,), lambda: calls.append(text) or text) == text
        assert len(state.entries) == 2 and len(calls) == 4
        assert state.bytes <= cache.MAX_BYTES
    monkeypatch.setattr(cache, 'MAX_BYTES', 100)
    with cache.scope() as state:
        for _ in range(2):
            assert cache.remember('party', ('large'*1000,), lambda: 'result'*1000) == 'result'*1000
        assert not state.entries and state.bytes == 0


def test_non_string_inputs_and_mutable_values_are_never_retained():
    with cache.scope() as state:
        for value in (False, 0, 1, [], {'raw':'source'}):
            assert cache.remember('party', (value,), lambda: 'result') == 'result'
        for _ in range(2):
            result = cache.remember('party', ('source',), lambda: ['fresh'])
            result.append('changed')
            assert result == ['fresh','changed']
        assert not state.entries


def test_all_projection_kinds_share_the_real_budget_and_entry_limit(monkeypatch):
    assert cache.MAX_BYTES == 2*1024*1024 and cache.MAX_ENTRIES == 4096
    kinds = ('party','reference','scope')
    with cache.scope() as state:
        for i in range(600):
            value = str(i)+'x'*5000
            assert cache.remember(kinds[i%3],(str(i),),lambda:value) == value
        assert {kind for kind,key in state.entries} == set(kinds)
        assert 0 < state.bytes <= cache.MAX_BYTES
        assert len(state.entries) < 600
        before = len(state.entries),state.bytes
        for kind in kinds:
            value = 'new-large-value'*500
            assert cache.remember(kind,('overflow',),lambda:value) == value
        assert (len(state.entries),state.bytes) == before
    # Isolate the real entry cap from the independently tested byte cap.
    monkeypatch.setattr(cache,'MAX_BYTES',32*1024*1024)
    with cache.scope() as state:
        for i in range(cache.MAX_ENTRIES+3):
            assert cache.remember(kinds[i%3],(str(i),),lambda:'value') == 'value'
        assert len(state.entries) == cache.MAX_ENTRIES


def test_reference_keys_follow_all_live_body_fields_but_dates_still_qualify(monkeypatch):
    number = contracts._contract_number
    calls = []
    def counted(value, *, reference=False):
        calls.append(value)
        return number(value, reference=reference)
    monkeypatch.setattr(contracts, '_contract_number', counted)
    row = {'id':'same-id','customer':'ООО «Заказчик»','contractor':'Исполнитель ООО',
           'contract':'Договор № A-12', 'contract_date':'2026-01-01', 'kind':'rss'}
    with cache.scope():
        first = contracts._reference_key(row)
        assert first == ('ооо заказчик','ооо исполнитель','a-12')
        assert contracts._reference_key(copy.deepcopy(row)) == first and len(calls) == 1
        identity = (*first, '2026-01-01')
        assert contracts._reference_differences(identity,row) == []
        row['contract_date'] = '2025-01-01'
        assert contracts._reference_differences(identity,row) == ['дата договора']
        row['customer_conflict'] = True
        assert 'в шапке РСС названы разные заказчики' in contracts._reference_differences(identity,row)
        for field,value,index in [('customer','АО Другой',0),('contractor','АО Другой',1),('contract','A-12/1',2)]:
            changed = dict(row, **{field:value})
            assert contracts._reference_key(changed)[index] != first[index]
        assert len(calls) == 4
        assert contracts._reference_key(dict(row, contractor=None))[1] == ''
        assert contracts._reference_key(dict(row, contractor=False))[1] == ''


def test_scope_cache_uses_complete_body_and_returns_fresh_sets():
    row = {'id':'same-id','subject':'Корпус 1','scope':[], 'physical_items':[]}
    with cache.scope():
        assert links._contract_scope_info(row) == ({'1'},False)
        links._contract_scope_info(row)[0].add('poison')
        assert links._contract_scope_info(row) == ({'1'},False)
        row['scope'].append('Корпус 2')
        assert links._contract_scope_info(row) == ({'1','2'},False)
        row['physical_items'].append({'scope':'Корпус 3','name':'Корпус 4'})
        assert links._contract_scope_info(row) == ({'1','2','3','4'},False)
        row['physical_items'][0]['name'] = 'Корпус 5/6'
        assert links._contract_scope_info(row) == ({'1','2','3','5'},True)
        row['subject'] = 'Корпус 7'
        assert links._contract_scope_info(row) == ({'7','2','3','5'},True)
        assert links._contract_scope_info(dict(row,subject=['Корпус 8'])) == ({'8','2','3','5'},True)


def test_unsupported_reference_inputs_keep_original_read_order():
    reads=[]
    class Source(dict):
        def get(self,field):
            reads.append(field)
            return super().get(field)
    class Changing:
        def __str__(self):
            row['contractor']='Changed'
            return 'Owner'
    with cache.scope() as state:
        custom=Source(customer='Owner',contractor='Builder',contract='A')
        assert contracts._reference_key(custom) == ('owner','builder','a')
        assert reads == ['customer','contractor','contract']
        row={'customer':Changing(),'contractor':'Before','contract':'A'}
        assert contracts._reference_key(row) == ('owner','changed','a')
        assert ('reference',('Owner','Builder','A')) not in state.entries


def test_scope_legacy_signature_grammar_stays_separate():
    text = 'Корпуса 3, 2–13 этажа Корпуса 1'
    current = links._scope_info(text)
    legacy = links._scope_info(text,_legacy_identity=True)
    assert current != legacy
    with cache.scope():
        assert links._scope_info(text) == current
        assert links._scope_info(text,_legacy_identity=True) == legacy


def test_concurrent_calls_and_copied_context_threads_have_separate_caches():
    barrier = threading.Barrier(2)
    def worker(text):
        with cache.scope() as state:
            barrier.wait(timeout=10)
            assert cache.remember('party', ('same',), lambda:text) == text
            return state
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first,second = list(pool.map(worker,('first','second')))
        assert first is not second
        with cache.scope() as parent:
            cache.remember('party', ('same',), lambda:'parent')
            inherited = contextvars.copy_context()
            def copied():
                with cache.scope() as child:
                    assert child is not parent
                    return cache.remember('party', ('same',), lambda:'child')
            assert pool.submit(inherited.run,copied).result(timeout=10) == 'child'
            assert cache.remember('party', ('same',), lambda:'wrong') == 'parent'
    assert cache._current() is None


def test_decorators_keep_metadata_and_source_consumers():
    def original(value: str) -> str:
        """Synthetic normalization."""
        return value.casefold()
    for wrapped in (cache.scalar('party')(original), cache.scoped(original)):
        assert inspect.signature(wrapped) == inspect.signature(original)
        assert inspect.unwrap(wrapped) is original
        assert inspect.getsource(wrapped) == inspect.getsource(original)
        assert wrapped.__annotations__ == original.__annotations__
        assert wrapped.__name__ == original.__name__ and wrapped.__doc__ == original.__doc__


@pytest.mark.parametrize('admit', [True, False])
def test_full_native_history_payments_and_daily_dto_equal_without_cache(tmp_path,monkeypatch,admit):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    project,cut = 'Synthetic complete matching','2026-11-06'
    ledgers.store_archive(project,archive([('A.xlsx',ks()),('B.xlsx',ks(number='B-24'))]),'2026-10-01','first.zip')
    ledgers.store_archive(project,archive([('A.xlsx',grown())]),'2026-11-01','second.zip')
    folder = monitor._project_dir(project)/'estimate';folder.mkdir()
    book = openpyxl.Workbook();sheet=book.active;sheet.title='Реестр договоров'
    sheet.cell(1,1,'Заказчик');sheet.cell(1,2,'ООО «Заказчик»')
    for col,name in ((4,'Дата договора'),(8,'Сумма договора'),(12,'Выполнено по реестру')):sheet.cell(6,col,name)
    for index,number in enumerate(('A-12','B-24'),9):
        for col,value in ((2,'ООО «Подрядчик»'),(3,number),(4,dt.date(2026,1,1)),(8,1000),(12,900)):sheet.cell(index,col,value)
    pay=book.create_sheet('Реестр платежей')
    for index,(number,date,amount) in enumerate((('A-12',dt.date(2026,1,1),100),('A-12',dt.date(2026,1,1),-25),('A-12',None,0),('B-24',dt.date(2026,1,1),0)),10):
        for col,value in ((2,'Подрядчик ООО'),(3,number),(4,date),(6,'Аванс'),(9,dt.date(2026,10,5)),(10,amount)):pay.cell(index,col,value)
    book.save(folder/'2026-11-01.xlsx');book.close()
    reports=[{'date':'2026-11-02','parsed':{'contractors':[], 'works':[
        {'contractor':'Подрядчик ООО','line':'Корпус 1 по договору № A-12 бетонирование'},
        {'contractor':'ООО «Подрядчик»','line':'Корпус 1/2 работа требует уточнения'}]}}]
    def full():
        return links.enrich(project,contracts.build(project,cut),cut,_reports=reports,_parties=[])
    sources={p:p.read_bytes() for p in monitor._project_dir(project).rglob('*') if p.suffix in {'.zip','.xlsx','.json'}}
    remember=cache.remember
    with monkeypatch.context() as inactive:
        inactive.setattr(cache,'remember',lambda kind,key,compute:compute())
        expected=full()
    if not admit:
        monkeypatch.setattr(cache,'MAX_ENTRIES',0)
    actual=full()
    assert cache.remember is remember and cache._current() is None
    assert actual == expected
    assert json.dumps(jsonable_encoder(actual),ensure_ascii=False) == json.dumps(jsonable_encoder(expected),ensure_ascii=False)
    by_number={row['contract']:row for row in actual['rows']}
    assert by_number['A-12']['advance']['paid'] is None
    assert by_number['A-12']['advance']['confirmed_paid'] == 75
    assert by_number['A-12']['advance']['unmatched_candidates'] == 1
    assert by_number['B-24']['advance']['paid'] == 0
    assert len(by_number['A-12']['progress']['series']) == 2
    assert actual['unmatched_works']
    assert all(p.read_bytes() == data for p,data in sources.items())


def test_payment_allocation_is_recomputed_with_changed_counts_and_signed_values():
    row={'customer':'Owner','contractor':'Builder','contract':'A','contract_date':'2026-01-01','completed':10}
    paid=[{'contractor':'Builder','contract':'A','contract_date':dt.date(2026,1,1),
           'amount':25,'date':dt.date(2026,2,1),'advance_label':False,'source':{}}]
    with cache.scope():
        identity=risk.payment_identity(row,reference_key=contracts._reference_key)
        def result(count):
            return risk.advance(row,paid,reference_key=contracts._reference_key,completed_basis='with_vat',identity_counts={identity:count})
        assert result(1)['paid'] == 25
        assert result(2)['paid'] is None
        paid[0]['amount']=-5
        assert result(1)['paid'] == -5
        paid[0]['amount']=None
        assert result(1)['paid'] is None
