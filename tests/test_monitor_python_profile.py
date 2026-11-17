"""Only bounded public code labels and finite numeric timings leave cProfile."""
import concurrent.futures
import json
from pathlib import Path
import sys
import threading
import types

import pytest

import developaid_contract_match_cache as matching
import developaid_contract_stage_profile as stages
import developaid_monitor as monitor
import developaid_monitor_python_profile as profile


def test_real_profiler_preserves_values_never_captures_arguments_and_resets_on_error():
    private='SYNTHETIC_PRIVATE_SOURCE_PATH_CELL_MONEY'
    def calculate(value):
        monitor._day('2034-01-01')
        return {'unknown':None,'zero':0,'refund':-25,'raw':value}
    original=sys.getprofile()
    result,diagnostics=profile.run(calculate,private)
    assert result==calculate(private)
    assert sys.getprofile() is original
    assert private not in json.dumps(diagnostics)
    assert any(row['function']=='_day' for row in diagnostics['rows'])
    assert {'queue','child_threads','job_serialization','job_storage','transfer'}<=set(diagnostics['unmeasured'])
    def fail():raise ValueError(private)
    with pytest.raises(ValueError,match=private):profile.run(fail)
    assert sys.getprofile() is original


def test_nested_and_preexisting_profiler_is_not_replaced_or_disabled(monkeypatch):
    def nested():
        active=sys.getprofile()
        value,diagnostics=profile.run(lambda:monitor._day('2034-01-01'))
        assert sys.getprofile() is active
        assert diagnostics=={'purpose':profile.PURPOSE,'unavailable':'profile_already_active'}
        return value
    result,diagnostics=profile.run(nested)
    assert result.isoformat()=='2034-01-01' and diagnostics['purpose']==profile.PURPOSE
    assert sys.getprofile() is None
    with monkeypatch.context() as local:
        local.setattr(profile.sys,'getprofile',lambda:object())
        local.setattr(profile.cProfile,'Profile',lambda:pytest.fail('Existing profiler replaced'))
        assert profile.run(lambda:7)==(7,{'purpose':profile.PURPOSE,'unavailable':'profile_already_active'})


def entry(code,**updates):
    values=dict(code=code,callcount=1,reccallcount=0,inlinetime=.001,totaltime=.002)
    return types.SimpleNamespace(**{**values,**updates})


def test_export_rejects_private_paths_nonrepo_dynamic_and_malicious_code_labels():
    native=monitor._day.__code__
    private='SYNTHETIC_PRIVATE_SOURCE_PATH'
    entries=[entry(private),entry(native.replace(co_filename='/tmp/'+private+'.py')),
             entry(native.replace(co_filename='<'+private+'>')),
             entry(native.replace(co_filename=str(Path(__file__).resolve()))),
             entry(native.replace(co_filename=str(profile._ROOT/(private+'.py')))),
             entry(native.replace(co_name='<'+private+'>')),entry(native)]
    result=profile._export(entries,.1)
    assert private not in json.dumps(result)
    assert len(result['rows'])==1
    assert result['rows'][0]['file']=='developaid_monitor.py'
    assert '/' not in result['rows'][0]['file'] and '\\' not in result['rows'][0]['file']


def test_worst_case_export_is_finite_bounded_sorted_and_truncated():
    native=monitor._day.__code__
    entries=[entry(native.replace(co_name='f'+'x'*60+str(i),co_firstlineno=i+1),
        callcount=profile.MAX_COUNT,reccallcount=profile.MAX_COUNT,inlinetime=86400,
        totaltime=86400) for i in range(90)]
    result=profile._export(entries,.25)
    assert len(result['rows'])<=40 and result['truncated'] is True
    assert len(json.dumps(result,allow_nan=False).encode())<=12*1024
    assert result['worker_elapsed_ms']==250
    assert all(row['calls']==profile.MAX_COUNT and row['self_ms']==86400000 for row in result['rows'])


@pytest.mark.parametrize('updates',[{'callcount':-1},{'callcount':True},{'callcount':1.0},
    {'reccallcount':profile.MAX_COUNT+1},{'inlinetime':float('nan')},{'totaltime':float('inf')},
    {'inlinetime':-1},{'totaltime':86401},{'totaltime':10**1000}])
def test_invalid_observations_are_explicitly_unavailable_never_zero(updates):
    result=profile._export([entry(monitor._day.__code__,**updates)],.1)
    assert result=={'purpose':profile.PURPOSE,'unavailable':'invalid_profile_metrics'}


def test_invalid_elapsed_keeps_business_result_and_cleans_up_profiler(monkeypatch):
    clock=iter((1.0,float('nan')))
    monkeypatch.setattr(profile.time,'perf_counter',lambda:next(clock))
    value,diagnostics=profile.run(lambda:{'unknown':None,'zero':0})
    assert value=={'unknown':None,'zero':0}
    assert diagnostics=={'purpose':profile.PURPOSE,'unavailable':'invalid_profile_metrics'}
    assert sys.getprofile() is None


def test_parallel_profiles_and_unprofiled_thread_have_no_cross_thread_events():
    barrier=threading.Barrier(3)
    def first():
        barrier.wait(timeout=10)
        for _ in range(100):monitor._day('2034-01-01')
    def second():
        barrier.wait(timeout=10)
        for _ in range(100):matching.strings(('a','b'))
    def plain():
        assert sys.getprofile() is None
        barrier.wait(timeout=10)
        for _ in range(100):stages._finite(1,2)
        assert sys.getprofile() is None
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        one=pool.submit(profile.run,first);two=pool.submit(profile.run,second);other=pool.submit(plain)
        a=one.result(timeout=10)[1];b=two.result(timeout=10)[1];other.result(timeout=10)
    anames={row['function'] for row in a['rows']};bnames={row['function'] for row in b['rows']}
    assert '_day' in anames and 'strings' not in anames
    assert 'strings' in bnames and '_day' not in bnames
    assert '_finite' not in anames|bnames
