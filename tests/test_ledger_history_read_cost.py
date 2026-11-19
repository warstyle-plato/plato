"""Repeated legacy archive reads preserve all evidence within the same byte budget."""
import copy
import gzip
import json
import random
import zlib

import pytest

import developaid_monitor_ledgers as ledgers


@pytest.fixture(autouse=True)
def isolated_cache():
    with ledgers._PARSE_CACHE_LOCK:ledgers._PARSE_CACHE.clear()
    yield
    with ledgers._PARSE_CACHE_LOCK:ledgers._PARSE_CACHE.clear()


def test_five_large_recent_archives_parse_once_each_and_keep_identical_independent_values(monkeypatch):
    # Each cell is within the real parser's per-cell bound. The whole parsed
    # archive is >4 MiB and was therefore never retained by the previous cache.
    payload={'parser_fingerprint':ledgers._PARSER_FINGERPRINT,
             'ledgers':[{'items':[{'name':'Источник '+('я'*9000),'position':i,'quantity':None}
                                  for i in range(300)]}]}
    assert ledgers._PARSE_CACHE_BYTES<len(json.dumps(payload,ensure_ascii=False).encode())<ledgers.MAX_PARSED_BYTES
    calls=[]
    def parse(data,filename):
        calls.append(filename)
        return copy.deepcopy(payload)
    monkeypatch.setattr(ledgers,'parse_archive',parse)
    for repeat in range(2):
        for index in range(5):
            result=ledgers._current_archive(b'original',str(index)*64,f'Archive{index}.zip')
            assert result==payload
            result['ledgers'][0]['items'][0]['name']='Caller mutation'
    assert len(calls)==5 and len(ledgers._PARSE_CACHE)==5
    assert sum(len(x) for x in ledgers._PARSE_CACHE.values())<=ledgers._PARSE_CACHE_TOTAL_BYTES
    for key, packed in ledgers._PARSE_CACHE.items():assert ledgers._decode_archive(packed,key)==payload


def test_filename_source_digest_and_parser_revision_remain_separate_cache_identities(monkeypatch):
    calls=[]
    def parse(data,filename):
        calls.append(1);return {'name':filename,'raw':data.decode(),
                               'parser_fingerprint':ledgers._PARSER_FINGERPRINT}
    monkeypatch.setattr(ledgers,'parse_archive',parse)
    first=ledgers._current_archive(b'first','a'*64,'first.zip')
    assert ledgers._current_archive(b'first','a'*64,'first.zip')==first
    ledgers._current_archive(b'second','b'*64,'first.zip')
    ledgers._current_archive(b'first','a'*64,'renamed.zip')
    monkeypatch.setattr(ledgers,'PARSER_SCHEMA',ledgers.PARSER_SCHEMA+1)
    ledgers._current_archive(b'first','a'*64,'first.zip')
    assert len(calls)==4
    monkeypatch.setattr(ledgers,'_PARSER_FINGERPRINT','changed-reader')
    refreshed=ledgers._current_archive(b'first','a'*64,'first.zip')
    assert refreshed['parser_fingerprint']=='changed-reader'
    assert ledgers._current_archive(b'first','a'*64,'first.zip')==refreshed
    assert len(calls)==5


def test_lru_retains_recent_entries_without_exceeding_the_total_compressed_byte_budget(monkeypatch):
    rng=random.Random(741)
    text=''.join(rng.choices('abcdefghijklmnopqrstuvwxyz0123456789',k=6000))
    payload={'text':text,'parser_fingerprint':ledgers._PARSER_FINGERPRINT}
    envelope={'identity':ledgers._archive_cache_key('0'*64,'source.zip'),'parsed':payload}
    length=len(gzip.compress(json.dumps(envelope,ensure_ascii=False).encode(),compresslevel=3,mtime=0))
    monkeypatch.setattr(ledgers,'_PARSE_CACHE_BYTES',length+100)
    monkeypatch.setattr(ledgers,'_PARSE_CACHE_TOTAL_BYTES',2*length+1)
    monkeypatch.setattr(ledgers,'parse_archive',lambda *a:dict(payload))
    for index in range(2):ledgers._current_archive(b'raw',str(index)*64,'source.zip')
    ledgers._current_archive(b'raw','0'*64,'source.zip')  # Touch the oldest.
    ledgers._current_archive(b'raw','2'*64,'source.zip')
    assert {key[1] for key in ledgers._PARSE_CACHE}=={'0'*64,'2'*64}
    assert sum(len(x) for x in ledgers._PARSE_CACHE.values())<=ledgers._PARSE_CACHE_TOTAL_BYTES


def test_incompressible_or_oversized_result_is_returned_intact_but_not_retained(monkeypatch):
    monkeypatch.setattr(ledgers,'_PARSE_CACHE_BYTES',10)
    payload={'data':[1,2,3],'parser_fingerprint':ledgers._PARSER_FINGERPRINT}
    monkeypatch.setattr(ledgers,'parse_archive',lambda *a:copy.deepcopy(payload))
    assert ledgers._current_archive(b'raw','a'*64,'source.zip')==payload
    assert not ledgers._PARSE_CACHE
    monkeypatch.setattr(ledgers,'_PARSE_CACHE_BYTES',1000)
    monkeypatch.setattr(ledgers,'MAX_PARSED_BYTES',10)
    assert ledgers._current_archive(b'raw','a'*64,'source.zip')==payload
    assert not ledgers._PARSE_CACHE


@pytest.mark.parametrize('damage',['header','deflate'])
def test_damaged_disposable_cache_reparses_the_original(monkeypatch,damage):
    calls=[]
    def parse(*a):
        calls.append(1)
        return {'data':['preserved',None,0],'parser_fingerprint':ledgers._PARSER_FINGERPRINT}
    monkeypatch.setattr(ledgers,'parse_archive',parse)
    first=ledgers._current_archive(b'raw','a'*64,'source.zip')
    key=ledgers._archive_cache_key('a'*64,'source.zip')
    broken=b'damaged'
    if damage=='deflate':
        packed=bytearray(ledgers._PARSE_CACHE[key])
        packed[10]=(packed[10]&~6)|6  # Reserved DEFLATE block type.
        broken=bytes(packed)
        with pytest.raises(zlib.error):gzip.decompress(broken)
    ledgers._PARSE_CACHE[key]=broken
    assert ledgers._current_archive(b'raw','a'*64,'source.zip')==first
    assert len(calls)==2
