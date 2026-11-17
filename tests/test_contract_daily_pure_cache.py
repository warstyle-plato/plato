"""Daily text memoization preserves native mutable returns and live decisions."""
import concurrent.futures
import contextvars
import inspect

import pytest

import developaid_contract_match_cache as cache
import developaid_contract_match_verify as verify
import developaid_monitor_contract_links as links


@pytest.mark.parametrize('name,domain,value',[
    ('_party_parts','party_parts','ООО «Синтетический Подрядчик»'),
    ('_work_words','work_words','Облицовка фасадов, монтаж облицовки и кровли'),
])
def test_native_body_is_reused_once_and_every_return_is_fresh(name,domain,value,monkeypatch):
    function=getattr(links,name);native=inspect.unwrap(function)
    expected=native(value);calls=[]
    dependency='_party_identity'if domain=='party_parts'else'_text'
    original=getattr(links,dependency)
    def counted(text):calls.append(1);return original(text)
    monkeypatch.setattr(links,dependency,counted)
    assert inspect.signature(function)==inspect.signature(native)
    assert function.__annotations__==native.__annotations__
    assert function.__name__==native.__name__ and function.__doc__==native.__doc__
    with cache.scope()as state:
        for _ in range(3):
            result=function(value)
            assert result==expected
            mutable=result[0]if domain=='party_parts'else result
            if domain=='party_parts':mutable.append('synthetic-poison')
            else:mutable.add('synthetic-poison')
        assert len(calls)==1
        cached=state.entries[(domain,(value,))]
        assert (type(cached)is tuple and type(cached[0])is tuple if domain=='party_parts'
                else type(cached)is frozenset)
    assert function(value)==expected and len(calls)==2


@pytest.mark.parametrize('name',['_party_parts','_work_words'])
@pytest.mark.parametrize('value',[None,'',False,0,1,[],{'raw':'source'}])
def test_input_types_and_native_values_are_preserved(name,value):
    function=getattr(links,name);native=inspect.unwrap(function)
    expected=native(value)
    with cache.scope()as state:
        for _ in range(2):assert function(value)==expected
        if type(value)is not str and value is not None:
            assert not state.entries


@pytest.mark.parametrize('name',['_party_parts','_work_words'])
def test_mutating_nonstring_source_keeps_native_string_reads_and_exceptions(name):
    function=getattr(links,name);native=inspect.unwrap(function)
    class Source:
        def __init__(self):self.reads=0
        def __str__(self):
            self.reads+=1
            if self.reads==3:raise ValueError('synthetic read failure')
            return 'ООО Первый'if self.reads==1 else'АО Второй'
    expected=Source();actual=Source()
    with cache.scope()as state:
        for _ in range(2):assert function(actual)==native(expected)
        with pytest.raises(ValueError,match='synthetic read failure'):function(actual)
        with pytest.raises(ValueError,match='synthetic read failure'):native(expected)
        assert actual.reads==expected.reads==3 and not state.entries


def test_new_domains_are_explicit_separate_and_live_row_body_changes_still_apply():
    assert verify.PURPOSE=='contract-pure-matching-hit-verify-v2'
    assert verify.KINDS==('party','reference','scope','party_parts','work_words')
    assert cache._KINDS==frozenset(verify.KINDS)
    row={'id':'same','contractor':'ООО Подрядчик','subject':'Облицовка фасадов',
         'scope':[],'physical_items':[]}
    with cache.scope()as state:
        assert links._party_rows('ООО Подрядчик (фасадов)',[row])==([row],'work_context')
        row['subject']='Монтаж кровли'
        assert links._party_rows('ООО Подрядчик (фасадов)',[row])==([],'unresolved_context')
        row['physical_items'].append({'name':'Облицовка фасадов'})
        assert links._party_rows('ООО Подрядчик (фасадов)',[row])==([row],'work_context')
        assert {'party','party_parts','work_words'}<={kind for kind,key in state.entries}
        assert links._party_parts('АО Другой')==(['другой'],'ао')
        assert links._party_parts('ООО Подрядчик')==(['подрядчик'],'ооо')


@pytest.mark.parametrize('name,domain',[('_party_parts','party_parts'),('_work_words','work_words')])
@pytest.mark.parametrize('limit',['entries','bytes'])
def test_admission_fallback_still_returns_fresh_native_values(name,domain,limit,monkeypatch):
    monkeypatch.setattr(cache,'MAX_ENTRIES'if limit=='entries'else'MAX_BYTES',0)
    function=getattr(links,name);expected=inspect.unwrap(function)('ООО Подрядчик облицовка')
    with cache.scope()as state:
        for _ in range(3):
            result=function('ООО Подрядчик облицовка');assert result==expected
            if domain=='party_parts':result[0].clear()
            else:result.clear()
        assert not state.entries and state.bytes==0


@pytest.mark.parametrize('name,domain',[('_party_parts','party_parts'),('_work_words','work_words')])
def test_native_poisoned_mutable_projection_hit_cannot_be_certified(name,domain):
    function=getattr(links,name);text='ООО Подрядчик облицовка'
    with verify.collect()as observer:
        with cache.scope()as state:
            function(text)
            state.entries[(domain,(text,))]=('synthetic-poison',)
            try:function(text)
            except Exception:pass
        assert observer.attempted[domain]==1 and observer.verified[domain]==0
        with pytest.raises(verify.VerificationProblem):observer.proof()
    assert cache._current()is None and verify._VERIFY.get()is None


@pytest.mark.parametrize('name',['_party_parts','_work_words'])
def test_foreign_copied_context_cannot_observe_new_projection_even_if_caught(name):
    function=getattr(links,name)
    with verify.collect()as observer:
        with cache.scope():
            function('ООО Подрядчик')
            inherited=contextvars.copy_context()
            def foreign():
                try:function('ООО Подрядчик')
                except verify.VerificationProblem:return 'rejected'
                return 'incorrectly-admitted'
            with concurrent.futures.ThreadPoolExecutor(max_workers=1)as pool:
                assert pool.submit(inherited.run,foreign).result(timeout=10)=='rejected'
        with pytest.raises(verify.VerificationProblem):observer.proof()


def test_both_new_domains_are_recomputed_with_nested_cache_disabled_and_reset():
    text='ООО Подрядчик облицовка'
    with verify.collect()as observer:
        with cache.scope()as state:
            for _ in range(2):
                assert links._party_parts(text)==(['подрядчик','облицовка'],'ооо')
                assert links._work_words(text)=={'подрядчик','облицовк'}
            assert type(state.entries[('party_parts',(text,))][0])is tuple
            assert type(state.entries[('work_words',(text,))])is frozenset
        proof=observer.proof()
        assert proof['hits']['party_parts']=={'attempted':1,'verified':1}
        assert proof['hits']['work_words']=={'attempted':1,'verified':1}
    assert cache._current()is None and verify._VERIFY.get()is None
