"""The owner supplies a fixed permit plan independently of source revisions."""
from concurrent.futures import ThreadPoolExecutor
import base64
import datetime as dt
import json

import pytest

import developaid_monitor as monitor
import developaid_schedule_versions as versions
import developaid_schedule_gpr_forecast as forecast
import developaid_management_report as report
import developaid_report_schedule as executive
from test_schedule_completed_facts import site, book, PROJECT, TODAY, OLD_DAY  # noqa: F401
from test_monitor_cumulative_api import api, post  # noqa: F401

TARGET='2027-09-30'
NOTE='Решение владельца: сохранить плановую дату РНВ 30.09.2027.'


def approve_owner(data, *, date=TARGET, day=TODAY, revision=None, scope=None):
    preview=monitor.schedule_version_preview(PROJECT,data,day,owner_rnv_date=date,
        owner_rnv_note=NOTE,baseline_scope=scope)
    return monitor.approve_schedule_version(PROJECT,data,day,
        expected_previous_sha256=preview['expected_previous_sha256'],
        expected_source_sha256=preview['source_sha256'],owner_rnv_date=date,owner_rnv_note=NOTE,
        expected_owner_rnv_revision=preview['owner_rnv_revision'] if revision is None else revision,
        baseline_scope=scope)


def test_date_only_owner_decision_does_not_change_source_revision_or_legacy_facts(site):
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],OLD_DAY)
    path=monitor._project_dir(PROJECT)/'work_fact'/(OLD_DAY+'.json')
    payload=json.loads(path.read_text());payload.pop('source_sha256');path.write_text(json.dumps(payload))
    result=approve_owner(site[2])
    assert result['revision']==0 and result['owner_rnv_revision']==1
    assert monitor._baseline_file(PROJECT,TODAY).read_bytes()==site[2]
    assert monitor.work_facts(PROJECT,TODAY)['1']['progress']==1
    assert monitor._baseline_state(PROJECT,OLD_DAY)['owner_rnv'] is None
    decision=monitor._baseline_state(PROJECT,TODAY)['owner_rnv']
    assert decision['date']==TARGET and decision['source']=='owner_decision' and decision['note']==NOTE


def test_source_and_owner_decision_commit_together_and_remaining_plan_is_not_project_progress(site):
    new=book('Оставшаяся кровля',.25,'2027-06-30')
    approve_owner(new,scope='remaining_work')
    state=monitor._baseline_state(PROJECT,TODAY)
    assert state['revision']==state['owner_rnv_revision']==1 and state['baseline_scope']=='remaining_work'
    view=monitor.build(PROJECT,TODAY)
    plan=view['schedule']['dependency_timeline']['rnv']
    assert plan['approved']==plan['approved_rnv']==plan['plan_date']==TARGET
    assert plan['owner_rnv']['source']=='owner_decision' and plan['approved_source']=='owner_decision'
    assert plan['rnv_forecast'] is None and plan['delay_days'] is None
    assert view['schedule']['approved_end']==view['dashboard']['schedule']['approved_finish']==TARGET
    assert view['schedule']['approved_plan']['owner_rnv_revision']==1
    block=report.physical(PROJECT,'week',TODAY)
    assert block['fact'] is None and block['state']=='not_aggregated'
    assert view['schedule']['rows'][0]['gpr_progress']==.25
    assert executive.model(view['schedule']['dependency_timeline'])['plan_date']==TARGET


def test_late_work_is_a_plan_conflict_without_changing_owner_rnv(site):
    approve_owner(book('Поздняя работа',.25,'2027-12-31'),scope='remaining_work')
    view=monitor.build(PROJECT,TODAY);plan=view['schedule']['dependency_timeline']['rnv']
    assert plan['approved_rnv']==TARGET and len(plan['plan_conflicts'])==1
    assert plan['plan_conflicts'][0]['plan_finish']=='2027-12-31'
    assert any('позже даты РНВ' in reason for reason in plan['reasons'])
    html=executive.render(executive.model(view['schedule']['dependency_timeline']))
    assert '30.09.2027' in html and 'План РНВ владельца' in html


def test_omitted_owner_fields_never_clear_an_existing_decision(site):
    approve_owner(site[2]);new=book('Новый план',.4,'2027-06-30')
    preview=monitor.schedule_version_preview(PROJECT,new,TODAY)
    monitor.approve_schedule_version(PROJECT,new,TODAY,
        expected_previous_sha256=preview['expected_previous_sha256'],expected_source_sha256=preview['source_sha256'])
    state=monitor._baseline_state(PROJECT,TODAY)
    assert state['owner_rnv']['date']==TARGET and state['owner_rnv_revision']==1


def test_future_owner_decision_waits_for_its_effective_date(site):
    approve_owner(site[2],day='2026-11-12')
    assert monitor._baseline_state(PROJECT,TODAY)['owner_rnv'] is None
    assert monitor._baseline_state(PROJECT,'2026-11-12')['owner_rnv']['date']==TARGET
    assert monitor._baseline_state(PROJECT,'2026-11-12')['revision']==0


def test_owner_cas_stale_or_missing_rejects_before_new_source_bytes_are_written(site):
    approve_owner(site[2]);before={str(p):p.read_bytes() for p in site[0].rglob('*') if p.is_file()}
    with pytest.raises(versions.ScheduleVersionConflict,match='РНВ'):
        approve_owner(book('Несохранённый новый план'),revision=0)
    assert before=={str(p):p.read_bytes() for p in site[0].rglob('*') if p.is_file()}


def test_only_one_owner_writer_can_consume_one_revision(site):
    def write(date):
        try:
            approve_owner(site[2],date=date,revision=0)
            return 'saved'
        except versions.ScheduleVersionConflict:
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(write,[TARGET,'2027-10-31']))==['saved','stale']
    state=monitor._baseline_state(PROJECT,TODAY)
    assert state['owner_rnv_revision']==1 and state['revision']==0


def test_one_read_freezes_owner_revision_and_source_together(site):
    @monitor.approved_schedule_read
    def read():
        before=monitor._baseline_state(PROJECT,TODAY)
        assert before['owner_rnv'] is None
        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(approve_owner,site[2]).result()
        assert monitor._baseline_state(PROJECT,TODAY)==before
    read()
    assert monitor._baseline_state(PROJECT,TODAY)['owner_rnv_revision']==1


@pytest.mark.parametrize('date,note',[('2027-02-31',NOTE),(TARGET,''),(None,NOTE)])
def test_invalid_owner_decision_is_not_silently_saved(site,date,note):
    before={str(p):p.read_bytes() for p in site[0].rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        monitor.schedule_version_preview(PROJECT,site[2],TODAY,owner_rnv_date=date,owner_rnv_note=note)
    assert before=={str(p):p.read_bytes() for p in site[0].rglob('*') if p.is_file()}


@pytest.mark.parametrize('path',['version-preview','version-approve'])
def test_owner_api_admission_precedes_reads(api,monkeypatch,path):
    client,_=api
    monkeypatch.setattr(monitor,'schedule_version_preview',lambda *a,**k:pytest.fail('read before admission'))
    result=post(client,'schedule/'+path,key='wrong',project=PROJECT,effective_from=TODAY,
        gpr_base64='eA==',owner_rnv_date=TARGET,owner_rnv_note=NOTE,
        expected_previous_sha256='a'*64,expected_source_sha256='b'*64,expected_owner_rnv_revision=0)
    assert result.status_code==403 and result.headers['cache-control']=='private, no-store'


def test_owner_api_roundtrip_and_strict_cas(api,site):
    client,_=api
    body={'project':PROJECT,'effective_from':TODAY,'gpr_base64':base64.b64encode(site[2]).decode(),
          'owner_rnv_date':TARGET,'owner_rnv_note':NOTE}
    preview=post(client,'schedule/version-preview',**body)
    assert preview.status_code==200 and preview.json()['proposed_owner_rnv']['source']=='owner_decision'
    tokens={'expected_previous_sha256':preview.json()['expected_previous_sha256'],
            'expected_source_sha256':preview.json()['source_sha256'],'expected_owner_rnv_revision':0}
    assert post(client,'schedule/version-approve',**body,**dict(tokens,expected_owner_rnv_revision=True)).status_code==422
    result=post(client,'schedule/version-approve',**body,**tokens)
    assert result.status_code==200 and result.json()['revision']==0 and result.json()['owner_rnv']['date']==TARGET
    assert post(client,'schedule/version-approve',**body,**tokens).status_code==409


def test_broken_owner_journal_fails_closed(site):
    approve_owner(site[2])
    path=monitor._project_dir(PROJECT)/'baseline'/'schedule_versions.json'
    payload=json.loads(path.read_text());payload['owner_decisions'][0]['source']='old_plan_guess'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='История'):
        monitor._baseline_state(PROJECT,TODAY)


def test_operational_past_fact_cut_keeps_one_current_plan_and_archival_identity(site):
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],'2026-11-07')
    old=monitor._baseline_state(PROJECT,OLD_DAY)['source_sha256']
    new=book('Единственная оставшаяся работа',.25,'2027-06-30')
    approve_owner(new,scope='remaining_work')
    for cut in (OLD_DAY,TODAY):
        view=monitor.build(PROJECT,cut)
        assert view['schedule']['rows'][0]['name']=='Единственная оставшаяся работа'
        assert view['schedule']['owner_rnv']['date']==TARGET
        assert view['schedule']['owner_rnv']['effective_from']==TODAY
        fact,=view['schedule']['completed_facts']['qualified_task_completions']
        assert fact['name']=='Завершённый фасад' and fact['source_sha256']==old
        assert monitor.work_facts(PROJECT,cut)=={}
    assert monitor._baseline_state(PROJECT,OLD_DAY)['source_sha256']==old
    assert monitor._baseline_state(PROJECT,OLD_DAY)['owner_rnv'] is None
    assert monitor.work_facts(PROJECT,OLD_DAY,archival=True)['1']['progress']==1


def test_past_fact_cut_cannot_take_a_later_current_source_reading(site,monkeypatch):
    import copy
    import developaid_schedule_gpr_physical as physical
    from test_gpr_corpus_preview import book as corpus_book
    snap=site[1]
    monkeypatch.setattr(physical.ledgers,'effective_snapshot',lambda project,cut='',**kwargs:
        copy.deepcopy(snap) if not cut or cut>=snap['snapshot_id'][:10] else None)
    approve_owner(corpus_book(bad_date='30.06.2027'),scope='remaining_work')
    view=monitor.build(PROJECT,'2026-11-05')
    assert view['schedule']['corpus_gpr']['taken_at']==TODAY
    assert view['schedule']['corpus_gpr']['packages'][0]['scopes'][0]['fact_day']=='2026-11-06'
    assert all(row['gpr_progress'] is None for row in view['schedule']['rows'])
    assert view['schedule']['owner_rnv']['date']==TARGET


def test_admin_fact_audit_remains_exact_when_public_oldcut_changes_to_active_plan(api,site):
    import re
    client,_=api
    monitor.store_work_fact(PROJECT,[{'id':'1','progress':1}],'2026-11-05')
    new=book('Текущий остаточный план',.25,'2027-06-30')
    body={'project':PROJECT,'effective_from':TODAY,'gpr_base64':base64.b64encode(new).decode(),
          'owner_rnv_date':TARGET,'owner_rnv_note':NOTE,'baseline_scope':'remaining_work',
          'audit_cut':'2026-11-06'}
    before=post(client,'schedule/version-preview',**body)
    assert before.status_code==200
    old=before.json()['audit']
    assert old['known'] is True
    for name in ('archival_source_sha256','snapshot_sha256','physical_configuration_sha256','factual_state_sha256'):
        assert isinstance(old[name],str) and re.fullmatch('[0-9a-f]{64}',old[name])
    assert not any('forecast' in name or 'plan_finish' in name for name in old)
    approve_owner(new,scope='remaining_work')
    after=post(client,'schedule/version-preview',**body)
    assert after.status_code==200 and after.json()['audit']==old
    assert after.json()['active_source_sha256']!=old['archival_source_sha256']
    assert after.json()['approved_previous_sha256']==old['archival_source_sha256']


@pytest.mark.parametrize('placement',['finance','legacy_gpr_cashflow'])
def test_independent_payment_baseline_is_not_replaced_by_source_or_owner_date(site,placement):
    import io
    from openpyxl import load_workbook
    import developaid_monitor_manager as manager
    def with_cashflow(data,value):
        workbook=load_workbook(io.BytesIO(data));sheet=workbook.create_sheet('CF ПЛАН-ФАКТ')
        sheet.append(['Статья',dt.datetime(2026,11,1),None,dt.datetime(2026,12,1),None])
        sheet.append(['Статья','План','Факт','План','Факт'])
        sheet.append(['Итого проект',value,0,value*2,0])
        output=io.BytesIO();workbook.save(output);return output.getvalue()
    project='Учебная независимая финансовая база'
    old=with_cashflow(book(),10) if placement=='legacy_gpr_cashflow' else book()
    monitor.store_schedule(project,old,None,'2026-11-01')
    if placement=='finance':
        (monitor._project_dir(project)/'baseline'/'finance.xlsx').write_bytes(with_cashflow(book(),10))
    before=monitor._payment_baseline(project),manager._payment_baseline(project)
    assert all(value['known'] and value['series']['2026-11-01']==10_000_000 for value in before)
    new=with_cashflow(book('Только новый рабочий план',.25,'2027-06-30'),999)
    preview=monitor.schedule_version_preview(project,new,TODAY,owner_rnv_date=TARGET,
        owner_rnv_note=NOTE,baseline_scope='remaining_work')
    monitor.approve_schedule_version(project,new,TODAY,
        expected_previous_sha256=preview['expected_previous_sha256'],expected_source_sha256=preview['source_sha256'],
        owner_rnv_date=TARGET,owner_rnv_note=NOTE,expected_owner_rnv_revision=0,baseline_scope='remaining_work')
    assert (monitor._payment_baseline(project),manager._payment_baseline(project))==before


def test_future_queued_plan_and_owner_date_cannot_replace_the_current_plan(site):
    first=book('Действующий план',.25,'2027-06-30')
    approve_owner(first,scope='remaining_work')
    future=book('Будущий план',.5,'2027-07-31')
    approve_owner(future,date='2027-10-31',day='2026-11-12',scope='remaining_work')
    for cut in (OLD_DAY,TODAY,'2026-11-20'):
        view=monitor.build(PROJECT,cut)
        assert view['schedule']['rows'][0]['name']=='Действующий план'
        assert view['schedule']['owner_rnv']['date']==TARGET


def test_uploading_an_archived_corpus_does_not_offer_it_as_an_active_alternative(site):
    import hashlib
    import developaid_gpr_corpus as corpus
    from test_gpr_corpus_preview import book as corpus_book
    active=corpus_book(name='Действующий корпусный план',bad_date='30.06.2027')
    approve_owner(active,scope='remaining_work')
    archived=corpus_book(name='Архивный альтернативный план',bad_date='30.06.2027')
    result=monitor.store_schedule_fact(PROJECT,archived,TODAY)
    assert result['archived_source_sha256']==hashlib.sha256(archived).hexdigest()
    assert result['corpus_gpr']['sha256']==hashlib.sha256(active).hexdigest()
    assert 'Архивный альтернативный план' not in result['corpus_gpr_html']
    assert corpus.latest(PROJECT,TODAY)['sha256']==result['archived_source_sha256']
