"""Stable per-day defaults, explicit manual overrides and bounded factual previews."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import multiprocessing
from pathlib import Path

import pytest
from PIL import Image

import developaid_monitor as monitor
import developaid_site_photos as photos
from developaid_project_notes import _append

PROJECT='Фото — учебный проект'
DAY='2026-11-24'


@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')


def image_bytes(size=(160,120),color=(70,130,190),kind='JPEG',orientation=None):
    mode='RGBA' if len(color)==4 else 'RGB'
    image=Image.new(mode,size,color)
    out=io.BytesIO()
    extra={}
    if orientation:
        exif=Image.Exif();exif[274]=orientation;extra['exif']=exif
    image.save(out,kind,**extra)
    return out.getvalue()


def add(photo_id,day=DAY,*,project=PROJECT,raw=None,at='2030-01-01T00:00:00Z'):
    return photos.store(project,raw or image_bytes(),photo_id,day,'Прораб','Снимок стройки',at=at)


def selected(project=PROJECT,start=None,end=None):
    return {row['id'] for row in photos.photos(project,start,end) if row['chosen']}


def report(start=DAY,end=DAY,project=PROJECT):
    return photos.for_report(project,dt.date.fromisoformat(start),dt.date.fromisoformat(end))


def source_state(project=PROJECT):
    folder=monitor._project_dir(project)/'photos'
    return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [folder/'log.jsonl',*sorted((folder/'files').glob('*.jpg'))]}


def test_defaults_are_at_most_five_per_actual_day_and_identical_across_week_month_and_retry():
    for day in ['2026-11-23',DAY,'2026-11-25']:
        for i in range(9):add(day.replace('-','')+'_'+str(i),day)
    before=source_state()
    weekly=photos.photos(PROJECT,'2026-11-20','2026-11-26')
    monthly=photos.photos(PROJECT,'2026-11-01','2026-11-30')
    assert [r for r in weekly if r['chosen']]==[r for r in monthly if r['chosen']]
    assert len(selected())==15
    for day in [DAY,'2026-11-23','2026-11-25']:
        assert len([r for r in weekly if r['day']==day and r['chosen']])==5
    first=report('2026-11-20','2026-11-26');second=report('2026-11-20','2026-11-26')
    assert first==second and first['selected']==15
    assert source_state()==before
    assert all(r['manual_selection'] is None and not r['day_manual'] for r in weekly)
    assert all(r['day'][:4]=='2026' for r in weekly),'day must never be inferred from at=2030'


def test_first_manual_uncheck_snapshots_one_entry_and_does_not_refill_or_accept_late_upload():
    for i in range(9):add('P'+str(i))
    defaults=selected();target=sorted(defaults)[0]
    log=monitor._project_dir(PROJECT)/'photos'/'log.jsonl'
    count=len(log.read_text().splitlines())
    entry=photos.select(PROJECT,target,False,'Владелец')
    assert len(log.read_text().splitlines())==count+1
    assert set(entry['selection_base_ids'])==defaults and entry['selection_day']==DAY
    assert selected()==defaults-{target}
    add('LATE')
    assert selected()==defaults-{target}
    values={r['id']:r for r in photos.photos(PROJECT)}
    assert values[target]['manual_selection'] is False
    assert values['LATE']['manual_selection'] is None and not values['LATE']['chosen']
    assert all(r['day_manual'] for r in values.values())


def test_manual_include_changes_only_manual_day_and_more_than_five_is_preserved():
    for i in range(8):add('P'+str(i))
    for photo_id in ['P'+str(i) for i in range(8)]:photos.select(PROJECT,photo_id,True,'Владелец')
    assert len(selected())==8
    block=report()
    assert len(block['items'])==8 and block['manual_selected']==8 and block['automatic_selected']==0
    assert 'Ручной набор: 8' in block['notice']
    add('NEXT','2026-11-25')
    assert selected(start=DAY,end=DAY)=={'P'+str(i) for i in range(8)}
    assert selected(start='2026-11-25',end='2026-11-25')=={'NEXT'}


def test_old_explicit_true_and_false_remain_manual_without_automatic_replacement():
    for i in range(8):add('P'+str(i))
    log=monitor._project_dir(PROJECT)/'photos'/'log.jsonl'
    for i in range(7):_append(log,{'kind':'select','id':'P'+str(i),'chosen':True,'by':'Старый выбор'})
    _append(log,{'kind':'select','id':'P7','chosen':False,'by':'Старый выбор'})
    assert len(selected())==7
    add('LATE')
    assert len(selected())==7 and 'LATE' not in selected()
    assert all(row['day_manual'] for row in photos.photos(PROJECT))
    assert len(report()['items'])==7


@pytest.mark.parametrize('record',[{'kind':'select','id':'P0'}, {'kind':'select','id':'P0','chosen':None}])
def test_missing_selection_is_not_an_explicit_false(record):
    add('P0')
    _append(monitor._project_dir(PROJECT)/'photos'/'log.jsonl',record)
    row,=photos.photos(PROJECT)
    assert row['chosen'] and row['manual_selection'] is None and not row['day_manual']
    photos.select(PROJECT,'P0',False,'Владелец')
    row,=photos.photos(PROJECT)
    assert not row['chosen'] and row['manual_selection'] is False


def test_project_choices_do_not_cross_namespaces():
    for project in [PROJECT,'Другой проект']:
        add('SAME',project=project)
    photos.select(PROJECT,'SAME',False,'Владелец')
    assert selected()==set()
    assert selected('Другой проект')=={'SAME'}


def test_original_and_journal_hashes_survive_preview_cache_hits_and_different_duplicate_webhook():
    first=image_bytes(color=(200,10,10));second=image_bytes(color=(10,10,200))
    add('P0',raw=first)
    before=source_state()
    one=photos.preview(PROJECT,'P0');two=photos.preview(PROJECT,'P0')
    assert one['sha256']==two['sha256'] and two['cache_hit']
    duplicate=photos.store(PROJECT,second,'P0',DAY)
    assert duplicate['duplicate']
    assert photos.read(PROJECT,'P0')==first and source_state()==before


def test_exif_orientation_and_long_edge_are_applied_without_rewriting_source():
    raw=image_bytes(size=(2400,1200),orientation=6)
    add('TURNED',raw=raw)
    result=photos.preview(PROJECT,'TURNED')
    assert (result['width'],result['height'])==(640,1280)
    assert len(result['bytes'])<=photos.PREVIEW_MAX_BYTES
    assert photos.read(PROJECT,'TURNED')==raw
    with Image.open(io.BytesIO(result['bytes'])) as image:
        assert image.size==(640,1280) and image.getexif().get(274) is None


def test_transparent_png_is_a_bounded_jpeg_with_original_png_preserved():
    raw=image_bytes(size=(800,600),color=(255,0,0,128),kind='PNG')
    add('PNG',raw=raw)
    result=photos.preview(PROJECT,'PNG')
    assert result['bytes'].startswith(b'\xff\xd8\xff') and photos.read(PROJECT,'PNG')==raw
    with Image.open(io.BytesIO(result['bytes'])) as image:
        red,green,blue=image.getpixel((20,20))
        assert red>245 and 115<green<140 and 115<blue<140


def test_noisy_photo_is_adaptively_compressed_under_target_without_upscaling():
    image=Image.effect_noise((1800,1200),90)
    data=io.BytesIO();image.save(data,'PNG');raw=data.getvalue()
    assert len(raw)<photos.MAX_BYTES
    add('NOISE',raw=raw)
    result=photos.preview(PROJECT,'NOISE')
    assert len(result['bytes'])<=96*1024 and max(result['width'],result['height'])<=1280
    assert result['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert photos.read(PROJECT,'NOISE')==raw


def test_corrupt_selected_photo_has_a_reason_and_does_not_remove_other_photos_or_the_block():
    from developaid_management_report import _photos_html
    add('GOOD');add('BAD',raw=b'\xff\xd8\xffbroken image')
    block=report()
    assert block['selected']==2 and [r['id'] for r in block['items']]==['GOOD']
    assert block['skipped'][0]['id']=='BAD' and block['skipped'][0]['code']=='image_unreadable'
    html=_photos_html(block,'week')
    assert html.count('<img ')==1 and 'Не удалось прочитать исходный снимок' in html
    photos.select(PROJECT,'GOOD',False,'Владелец')
    empty=report()
    assert empty['items']==[] and len(empty['skipped'])==1
    assert 'Не удалось прочитать' in _photos_html(empty,'week')


def test_missing_original_and_pixel_guard_are_per_photo_failures(monkeypatch):
    add('MISSING');add('BIG')
    (monitor._project_dir(PROJECT)/'photos'/'files'/'MISSING.jpg').unlink()
    monkeypatch.setattr(photos,'PREVIEW_MAX_PIXELS',10)
    block=report()
    assert not block['items']
    assert {x['code'] for x in block['skipped']}=={'source_missing','image_bounds'}


def test_picker_chosen_ids_equal_report_items_plus_visible_failures():
    for i in range(7):add('P'+str(i))
    chosen=selected()
    block=report()
    assert chosen=={x['id'] for x in block['items']}|{x['id'] for x in block['skipped']}
    assert all(x['preview_bytes']<=photos.PREVIEW_MAX_BYTES for x in block['items'])
    assert all(base64.b64decode(x['src'].split(',',1)[1]).startswith(b'\xff\xd8\xff') for x in block['items'])


def test_cache_is_bounded_only_derived_files_are_removed(monkeypatch):
    monkeypatch.setattr(photos,'PREVIEW_CACHE_FILES',2)
    monkeypatch.setattr(photos,'PREVIEW_CACHE_BYTES',2000)
    for i in range(6):add('P'+str(i),raw=image_bytes(color=(i*40,90,100)))
    before=source_state()
    folder=monitor._project_dir(PROJECT)/'photos'/'.report-previews';folder.mkdir()
    sentinel=folder/'unrelated-original.txt';sentinel.write_bytes(b'keep')
    (folder/'.preview-interrupted.tmp').write_bytes(b'incomplete')
    for i in range(6):photos.preview(PROJECT,'P'+str(i))
    owned=list(folder.glob('*.jpg'))
    assert len(owned)<=2 and sum(p.stat().st_size for p in owned)<=2000
    assert sentinel.read_bytes()==b'keep' and not list(folder.glob('.preview-*.tmp'))
    assert source_state()==before


def test_corrupt_derived_cache_is_rebuilt_from_original():
    add('P0')
    first=photos.preview(PROJECT,'P0')
    path=next((monitor._project_dir(PROJECT)/'photos'/'.report-previews').glob('*.jpg'))
    path.write_bytes(b'\xff\xd8\xffbroken cache')
    second=photos.preview(PROJECT,'P0')
    assert second['sha256']==first['sha256'] and not second['cache_hit']


def _worker_preview(project,photo_id,queue):
    try:
        p=photos.preview(project,photo_id)
        queue.put((p['sha256'],p['source_sha256'],len(p['bytes'])))
    except Exception as exc:queue.put(('ERROR',type(exc).__name__))


def test_two_worker_cache_writes_are_atomic_and_do_not_touch_originals():
    add('P0',raw=image_bytes(size=(800,600)))
    before=source_state()
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
    workers=[ctx.Process(target=_worker_preview,args=(PROJECT,'P0',queue)) for _ in range(2)]
    for worker in workers:worker.start()
    for worker in workers:
        worker.join(10);assert worker.exitcode==0
    results=[queue.get(timeout=2) for _ in workers]
    assert results[0]==results[1] and results[0][0]!='ERROR'
    folder=monitor._project_dir(PROJECT)/'photos'/'.report-previews'
    assert len(list(folder.glob('*.jpg')))==1 and not list(folder.glob('.preview-*.tmp'))
    assert source_state()==before


def test_cache_io_failure_uses_compressed_preview_never_full_original(monkeypatch):
    add('P0',raw=image_bytes(size=(2000,1200)))
    raw=photos.read(PROJECT,'P0')
    monkeypatch.setattr(photos,'_atomic_bytes',lambda *args:(_ for _ in ()).throw(OSError('synthetic cache failure')))
    result=photos.preview(PROJECT,'P0')
    assert result['bytes']!=raw and len(result['bytes'])<=photos.PREVIEW_MAX_BYTES
    assert not result['cache_hit'] and photos.read(PROJECT,'P0')==raw


def _worker_select(project,photo_id,queue):
    try:
        queue.put(photos.select(project,photo_id,False,'Учебный выбор'))
    except Exception as exc:queue.put({'ERROR':type(exc).__name__})


def test_two_workers_first_manual_edit_snapshot_and_changes_are_one_locked_journal_history():
    for i in range(9):add('P'+str(i))
    defaults=selected();targets=sorted(defaults)[:2]
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
    workers=[ctx.Process(target=_worker_select,args=(PROJECT,target,queue)) for target in targets]
    for worker in workers:worker.start()
    for worker in workers:
        worker.join(10);assert worker.exitcode==0
    events=[queue.get(timeout=2) for _ in workers]
    assert all('ERROR' not in event for event in events)
    assert sum('selection_base_ids' in event for event in events)==1
    assert selected()==defaults-set(targets)
    add('LATE')
    assert selected()==defaults-set(targets)
