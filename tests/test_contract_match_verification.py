"""Every reused immutable value is checked in the same synchronous call."""
import concurrent.futures
import contextvars
import json

import pytest

import developaid_contract_match_cache as cache
import developaid_contract_match_verify as verify
import developaid_contract_stage_profile as stages
import developaid_monitor_contracts as contracts
import developaid_monitor_contract_links as links


@pytest.mark.parametrize('kind',verify.KINDS)
def test_every_poisoned_kind_is_sticky_even_if_business_catches_the_exception(kind):
    with verify.collect() as state:
        with cache.scope() as ordinary:
            cache.remember(kind,('key',),lambda:'correct')
            ordinary.entries[(kind,('key',))]='poisoned'
            try:cache.remember(kind,('key',),lambda:'correct')
            except Exception:pass  # A native-style broad fallback cannot certify a proof.
        assert state.attempted[kind]==1 and state.verified[kind]==0
        with pytest.raises(verify.VerificationProblem):state.proof()
    assert verify._VERIFY.get() is None and cache._current() is None


@pytest.mark.parametrize('cached,recomputed',[(True,1),(1,True),({'one'},frozenset({'one'})),
    ((frozenset({'one'}),True),(frozenset({'one'}),1)),('value',type('Other',(str,),{})('value'))])
def test_strict_recursive_types_cannot_pass_loose_python_equality(cached,recomputed):
    with verify.collect() as state:
        with cache.scope() as ordinary:
            ordinary.entries[('party',('key',))]=cached
            with pytest.raises(verify.VerificationProblem):cache.remember('party',('key',),lambda:recomputed)
        with pytest.raises(verify.VerificationProblem):state.proof()


def test_prepopulated_cache_is_not_extended_and_nested_pure_compute_is_uncached():
    calls=[]
    def party():calls.append(1);return 'owner'
    def reference():return (cache.remember('party',('owner',),party),'builder','number')
    with cache.scope() as ordinary:
        first=cache.remember('reference',('owner','builder','number'),reference)
        entries=dict(ordinary.entries)
        with verify.collect() as state:
            result=cache.remember('reference',('owner','builder','number'),reference)
            assert result is first and ordinary.entries==entries and len(calls)==2
            assert cache._current() is ordinary
            proof=state.proof()
            assert proof['entered_scopes']==proof['exited_scopes']==0
            assert proof['hits']['reference']=={'attempted':1,'verified':1}
            assert proof['hits']['party']=={'attempted':0,'verified':0}
            assert proof['unexercised_kinds']==['party','scope','party_parts','work_words']
    assert verify._VERIFY.get() is None


def test_nested_observer_and_scopes_share_only_the_observer_and_always_reset():
    with verify.collect() as state:
        with cache.scope() as first:
            with verify.collect() as nested,cache.scope() as same:
                assert nested is state and same is first
                for _ in range(2):cache.remember('party',('same',),lambda:'value')
        assert cache._current() is None
        with cache.scope() as second:
            assert second is not first and second.entries=={}
        proof=state.proof()
        assert proof['entered_scopes']==proof['exited_scopes']==3
    assert verify._VERIFY.get() is None
    with pytest.raises(RuntimeError):
        with verify.collect():raise RuntimeError('synthetic')
    assert verify._VERIFY.get() is None


def test_miss_unsupported_and_full_cache_fallback_keep_original_call_counts(monkeypatch):
    monkeypatch.setattr(cache,'MAX_ENTRIES',1)
    calls=[]
    with verify.collect() as state:
        with cache.scope():
            for _ in range(2):cache.remember('party',('seed',),lambda:calls.append('seed') or 'value')
            for key in (('full',),('full',),(False,),(False,)):
                assert cache.remember('party',key,lambda:calls.append('fallback') or 'value')=='value'
        assert calls==['seed','seed','fallback','fallback','fallback','fallback']
        assert state.proof()['hits']['party']=={'attempted':1,'verified':1}


@pytest.mark.parametrize('condition',['zero_hits','unfinished_hit','unfinished_scope','overflow'])
def test_incomplete_or_overflowed_observation_never_exports_a_success(condition):
    with verify.collect() as state:
        if condition=='unfinished_hit':state.attempted['party']=1
        elif condition=='unfinished_scope':verify.enter_scope()
        elif condition=='overflow':
            with cache.scope() as ordinary:
                ordinary.entries[('party',('key',))]='value';state.attempted['party']=verify.MAX_COUNT
                with pytest.raises(verify.VerificationProblem):cache.remember('party',('key',),lambda:'value')
        with pytest.raises(verify.VerificationProblem):state.proof()
    assert verify._VERIFY.get() is None


def test_recomputation_error_is_redacted_sticky_and_next_normal_call_is_clean():
    private='SYNTHETIC_PRIVATE_PATH_MONEY_SOURCE'
    with verify.collect() as state:
        with cache.scope() as ordinary:
            ordinary.entries[('party',('key',))]='value'
            def fail():raise ValueError(private)
            with pytest.raises(verify.VerificationProblem) as problem:cache.remember('party',('key',),fail)
            assert private not in str(problem.value)
        with pytest.raises(verify.VerificationProblem):state.proof()
    with cache.scope():assert cache.remember('party',('key',),lambda:'value')=='value'
    assert verify._VERIFY.get() is None


def test_foreign_copied_context_is_sticky_failure_even_if_foreign_fallback_swallows_it():
    with verify.collect() as state:
        with cache.scope():
            for _ in range(2):cache.remember('party',('same',),lambda:'value')
        inherited=contextvars.copy_context()
        def foreign():
            try:
                with cache.scope():pass
            except Exception:return 'caught'
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(inherited.run,foreign).result(timeout=10)=='caught'
        with pytest.raises(verify.VerificationProblem):state.proof()
    assert verify._VERIFY.get() is None


def test_proof_retains_only_bounded_fixed_codes_and_counts():
    private='SYNTHETIC_PRIVATE_KEY_VALUE_SOURCE'
    with verify.collect() as state:
        with cache.scope():
            for _ in range(2):cache.remember('party',(private,),lambda:private)
        proof=state.proof()
        assert private not in json.dumps(proof)
        assert len(json.dumps(proof,allow_nan=False).encode())<2048


@pytest.mark.parametrize('invalid',[-1,True,1.0,verify.MAX_COUNT+1])
def test_final_guard_rejects_invalid_counter_state_even_when_totals_match(invalid):
    with verify.collect() as state:
        state.attempted['party']=state.verified['party']=invalid
        with pytest.raises(verify.VerificationProblem):state.proof()


def test_foreign_activity_after_proof_is_caught_again_before_observer_exit():
    with pytest.raises(verify.VerificationProblem):
        with verify.collect() as state:
            with cache.scope():
                for _ in range(2):cache.remember('party',('same',),lambda:'value')
            state.proof()
            inherited=contextvars.copy_context()
            def foreign():
                try:
                    with cache.scope():pass
                except Exception:return
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(inherited.run,foreign).result(timeout=10)
            # No explicit second proof call: closing the worker must reject it.
    assert verify._VERIFY.get() is None


def test_new_unreviewed_cache_domain_is_sticky_failure_not_silently_omitted(monkeypatch):
    monkeypatch.setattr(cache,'_KINDS',cache._KINDS|{'unreviewed'})
    with verify.collect() as state:
        with cache.scope():
            cache.remember('unreviewed',('same',),lambda:'value')
            try:cache.remember('unreviewed',('same',),lambda:'value')
            except Exception:pass
        with pytest.raises(verify.VerificationProblem):state.proof()


def test_foreign_copied_context_direct_fallback_also_cannot_certify_worker_coverage():
    with verify.collect() as state:
        with cache.scope():
            for _ in range(2):cache.remember('party',('same',),lambda:'value')
        inherited=contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(verify.VerificationProblem):
                pool.submit(inherited.run,cache.remember,'party',('foreign',),lambda:'value').result(timeout=10)
        with pytest.raises(verify.VerificationProblem):state.proof()


def test_unsupported_reference_inputs_preserve_original_lazy_read_order():
    reads=[]
    class Source(dict):
        def get(self,key):reads.append(key);return super().get(key)
    class Changing:
        def __str__(self):row['contractor']='Changed';return 'Owner'
    with verify.collect() as state:
        with cache.scope():
            for _ in range(2):cache.remember('party',('seed',),lambda:'seed')
            custom=Source(customer='Owner',contractor='Builder',contract='A')
            assert contracts._reference_key(custom)==('owner','builder','a')
            assert reads==['customer','contractor','contract']
            row={'customer':Changing(),'contractor':'Before','contract':'A'}
            assert contracts._reference_key(row)==('owner','changed','a')
        state.proof()


def test_current_body_changes_and_fresh_scope_sets_are_still_recomputed():
    row={'subject':'Корпус 1','scope':[],'physical_items':[]}
    with verify.collect() as state:
        with cache.scope():
            assert links._contract_scope_info(row)==({'1'},False)
            links._contract_scope_info(row)[0].add('poison')
            assert links._contract_scope_info(row)==({'1'},False)
            row['physical_items'].append({'scope':'Корпус 2','name':'Корпус 3'})
            assert links._contract_scope_info(row)==({'1','2','3'},False)
        assert state.proof()['hits']['scope']['verified']>0


def test_maximum_proof_counts_and_existing_stage_diagnostics_stay_bounded():
    with verify.collect() as state,stages.collect() as diagnostics:
        state.entered=state.exited=verify.MAX_COUNT
        for kind in verify.KINDS:state.attempted[kind]=state.verified[kind]=verify.MAX_COUNT
        for label in stages.STAGES:diagnostics.stages[label]=[stages.MAX_COUNT,stages.MAX_SECONDS,stages.MAX_SECONDS]
        for label in stages.COUNTERS:diagnostics.add(label,stages.MAX_COUNT)
        payload=diagnostics.export();payload['matching_cache_verification']=state.proof()
        assert len(json.dumps(payload,allow_nan=False).encode())<=stages.MAX_BYTES
