"""Personnel compares one source date/category/cohort, never a company pool."""
import copy
import datetime as dt
import io
import json
import os

import pytest
from openpyxl import Workbook, load_workbook

import developaid_contract_workforce as workforce


def inputs():
    row={'id':'a'*64,'contract':'A-123','contract_date':'2026-01-01',
         'contractor':'ООО «Исполнитель»','scope':['Устройство кровли Корпус 1']}
    source={'sha256':'b'*64,'contract':{'number':row['contract'],'date':row['contract_date']},
            'edition':{'kind':'agreement','date':'2026-02-01'}}
    schedule={'source_identity':source,'resources':[
        {'category':kind,'name':'Количество '+('рабочих' if kind=='workers' else 'ИТР')+' на объекте','period_basis':'literal_date','source':{'page':1,'row':index},
         'values':[{'start':'2026-01-20','finish':'2026-01-20','value':count,'raw':str(count)}]}
        for index,(kind,count) in enumerate([('workers',10),('itr',2)],1)]}
    reports=[{'date':'2026-01-20','text':'ООО «Исполнитель», договор A-123 ИТР 1, рабочие 8'}]
    return row,source,schedule,reports,{'rows':[row]}


def view(values=None, **kw):
    row,source,schedule,reports,register=values or inputs()
    return workforce.project(schedule,reports,row,register,'2026-01-25',source=source,**kw)


def test_explicit_contract_is_a_real_source_binding_without_new_manual_gate():
    got=view();r=got['rows'][0]
    assert (r['workers_plan'],r['workers_fact'],r['workers_delta'])==(10,8,-2)
    assert (r['itr_plan'],r['itr_fact'],r['itr_delta'])==(2,1,-1)
    assert got['coverage']=={'dates':1,'workers_pairs':1,'itr_pairs':1,'project_total':False}
    assert any('более поздней' in reason for reason in r['reasons'])


def test_unread_report_source_is_distinct_from_a_loaded_empty_source():
    values=list(inputs());values[3]=None
    unread=view(values)
    assert unread['report_input_status']=='not_loaded' and unread['report_sources_revision'] is None
    assert unread['rows'][0]['workers_plan']==10 and unread['rows'][0]['workers_fact'] is None
    assert workforce.REPORTS_NOT_LOADED in unread['rows'][0]['reasons']
    values[3]=[];empty=view(values)
    assert empty['report_input_status']=='loaded' and empty['report_sources_revision']
    assert any('нет подходящей строки' in r for r in empty['rows'][0]['reasons'])


def test_one_party_with_two_contracts_is_not_a_distribution_even_if_count_equal():
    values=inputs();row,_,_,reports,register=values
    reports[0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    register['rows'].append(dict(row,id='c'*64,contract='A-456'))
    got=view(values)['rows'][0]
    assert got['workers_fact'] is got['itr_fact'] is None
    assert got['candidates'][0]['workers']==8
    assert 'между договорами' in ' '.join(got['reasons'])


def test_one_party_one_contract_still_needs_full_work_scope():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None
    assert 'полного состава' in ' '.join(got['reasons'])


def test_partial_objects_do_not_become_the_whole_contract_crew():
    values=inputs();values[0]['scope']=['Кровля Корпус 1','Кровля Корпус 2']
    values[3][0]['text']='ООО «Исполнитель», договор A-123 Корпус 1 ИТР 1, рабочие 8'
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None and 'объектов' in ' '.join(got['reasons'])


def test_only_same_literal_dates_are_compared_and_future_is_excluded():
    values=inputs();values[3][0]['date']='2026-01-21'
    values[3].append({'date':'2026-02-10','text':'ООО «Исполнитель», договор A-123 ИТР 1, рабочие 8'})
    got=view(values)
    assert [r['date'] for r in got['rows']]==['2026-01-20','2026-01-21']
    assert all(r['workers_delta'] is None for r in got['rows'])
    assert got['rows'][1]['workers_fact']==8  # Applicable dated fact survives a missing same-day plan.


@pytest.mark.parametrize('raw,expected',[(None,None),('ООО «Исполнитель», договор A-123 рабочие 0',0)])
def test_absent_parsed_category_is_not_confirmed_zero(raw, expected):
    values=inputs()
    values[3][0]={'date':'2026-01-20','parsed':{'contractors':[{'name':'ООО «Исполнитель», договор A-123','workers':0,'itr':0}]}}
    if raw is not None:values[3][0]['text']=raw
    got=view(values)['rows'][0]
    assert got['workers_fact']==expected
    assert got['itr_fact'] is None


def test_duplicate_saved_report_is_one_source_but_two_crew_lines_are_not_summed():
    values=inputs();values[3].append(copy.deepcopy(values[3][0]))
    assert view(values)['rows'][0]['workers_fact']==8
    values=inputs();values[3][0]['text']+='\n'+values[3][0]['text']
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None


def test_repeated_itr_resources_are_not_summed_or_deduplicated_by_equal_counts():
    values=inputs();values[2]['resources'].extend(copy.deepcopy(values[2]['resources'][1]) for _ in range(7))
    got=view(values)['rows'][0]
    assert got['itr_plan'] is got['itr_delta'] is None
    assert got['workers_delta']==-2


def test_mixed_category_and_range_stay_visible_without_invented_split():
    values=inputs();values[2]['resources'][0]['category']='workers_and_itr'
    values[2]['resources'][1]['values'][0]['value']={'min':1,'max':2,'raw':'1–2'}
    got=view(values)['rows'][0]
    assert got['workers_plan'] is got['itr_plan'] is None
    assert got['combined_plan'][0]['value']==10
    assert got['itr_plan_sources'][0]['range']['raw']=='1–2'


def test_plan_scope_hint_is_not_a_whole_object_fact_binding():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» (кровля) ИТР 1, рабочие 8'
    for r in values[2]['resources']:r.update(name='Численность',scope_hint='кровля',scope_state='requires_confirmation')
    got=view(values)['rows'][0]
    assert got['workers_fact'] is None


def test_existing_source_binding_must_pin_report_plan_category_and_one_owner():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» ИТР 1, рабочие 8'
    p=workforce.personnel(values[3],'2026-01-25')[0]
    binding={'personnel_key':p['personnel_key'],'contract_id':values[0]['id'],
        'plan_sha256':values[1]['sha256'],'scope_complete':True,'confirmed':True,
        'categories':['workers'],'scope':'Полный состав кровельной бригады','source':{'sha256':'d'*64}}
    got=view(values,existing_bindings=[binding])['rows'][0]
    assert got['workers_delta']==-2 and got['itr_fact'] is None
    changed=dict(binding,plan_sha256='e'*64)
    assert view(values,existing_bindings=[changed])['rows'][0]['workers_fact'] is None
    foreign=dict(binding,contract_id='f'*64,plan_sha256='f'*64)
    assert view(values,existing_bindings=[binding,foreign])['rows'][0]['workers_fact'] is None


def test_no_resources_still_explains_real_report_candidate_without_fake_zeros():
    values=inputs();values[2]['resources']=[]
    got=view(values)
    assert got['rows'][0]['workers_plan'] is got['rows'][0]['workers_fact'] is None
    assert got['rows'][0]['candidates'][0]['workers']==8
    assert 'нет подтверждённого календарного' in ' '.join(got['rows'][0]['reasons'])
    assert not got['available'] and 'записи подрядчика' in got['reason']
    wb=Workbook()
    assert workforce.write_sheet(wb,got) is None and len(wb.worksheets)==1


def test_excluded_or_wrong_contract_source_never_becomes_a_comparison():
    values=inputs();values[0]['excluded']=True
    assert not view(values)['available']
    values=inputs();values[1]['contract']['number']='OTHER'
    assert not view(values)['available']


def test_writer_has_trusted_deviation_formulas_no_freeze_and_preserves_provenance():
    got=view();wb=Workbook();wb.active.title='ГПР'
    sheet=workforce.write_sheet(wb,got)
    assert sheet.freeze_panes is None and sheet.max_column==8
    assert [sheet.cell(6,c).value for c in (1,2,3,5,6)]==[dt.date(2026,1,20),10,8,2,1]
    assert {c.coordinate for r in sheet for c in r if c.data_type=='f'}=={'D6','G6'}
    assert 'более поздней' in sheet['H6'].value and 'text_sha256' in sheet['H6'].comment.text
    assert not any(c.data_type=='e' for r in sheet for c in r)
    buf=io.BytesIO();wb.save(buf);buf.seek(0)
    assert load_workbook(buf)['Численность'].freeze_panes is None
    from developaid_contract_builder_plan import cache_builder_formulas
    cached=load_workbook(io.BytesIO(cache_builder_formulas(buf.getvalue(),wb)),data_only=True)
    assert [cached[sheet.title].cell(6,c).value for c in range(2,8)]==[10,8,-2,2,1,-1]


def test_report_counts_in_work_prose_and_missing_party_are_not_silent_facts():
    reports=[{'date':'2026-01-20','text':'Рабочие 8\nПо работам\nЧужая бригада ИТР 99'}]
    assert workforce.personnel(reports,'2026-01-25')==[]


@pytest.mark.parametrize('raw,category',[
    ('ИТР 1–2, рабочие 8','itr'),('ИТР 1, ИТР 2, рабочие 8','itr'),
    ('ИТР 1, рабочие 8+2','workers'),('ИТР 1, рабочие 8/2','workers'),
    ('ИТР 1, рабочие 8,5','workers'),('ИТР 1, рабочие 8 и 2','workers'),
    ('ИТР 1, рабочие 8\nИТР 2','itr')])
def test_ambiguous_raw_category_keeps_other_exact_category(raw,category):
    values=inputs();values[3][0]['text']='ООО «Исполнитель», договор A-123 '+raw
    got=view(values)['rows'][0]
    assert got[category+'_fact'] is got[category+'_delta'] is None
    other='workers' if category=='itr' else 'itr'
    assert got[other+'_fact'] is not None
    assert any('исходн' in reason or 'повтор' in reason for reason in got['reasons'])


@pytest.mark.parametrize('basis',[None,'unknown','literal_date'])
def test_unknown_or_literal_basis_never_spreads_a_plan_between_dates(basis):
    values=inputs()
    for resource in values[2]['resources']:
        resource['period_basis']=basis
        resource['values'][0].update(start='2026-01-15',finish='2026-01-22')
    got=view(values)
    assert all(r['workers_plan'] is None and r['itr_plan'] is None for r in got['rows'])
    assert all(r['workers_delta'] is None and r['itr_delta'] is None for r in got['rows'])


@pytest.mark.parametrize('basis',['explicit_interval','relative_explicit_period'])
def test_source_interval_only_and_relative_requires_native_anchor(basis):
    values=inputs()
    for resource in values[2]['resources']:
        resource['period_basis']=basis
        resource['values'][0].update(start='2026-01-15',finish='2026-01-22')
    if basis=='relative_explicit_period':
        assert all(r['workers_plan'] is None for r in view(values)['rows'])
        values[2].update(calendar_state='anchored',anchor={'handover_date':'2026-01-01'})
    got=view(values)
    assert next(r for r in got['rows'] if r['date']=='2026-01-20')['workers_delta']==-2


def test_contract_reference_does_not_prove_resource_cohort():
    values=inputs()
    for resource in values[2]['resources']:
        resource.update(name='Рабочие каменной кладки',scope_hint='каменная кладка',scope_state='requires_confirmation')
    got=view(values)['rows'][0]
    assert got['workers_plan']==10 and got['workers_fact'] is got['workers_delta'] is None


def test_unique_source_work_context_and_object_resource_need_no_new_assignment():
    values=inputs();row,_,_,reports,register=values
    reports[0]['text']='ООО «Исполнитель» (кровля) ИТР 1, рабочие 8'
    register['rows'].append(dict(row,id='c'*64,contract='A-456',scope=['Временные дороги']))
    got=view(values)['rows'][0]
    assert got['workers_delta']==-2 and got['itr_delta']==-1
    register['rows'][1]['scope']=['Кровля Корпус 2']
    assert view(values)['rows'][0]['workers_fact'] is None


def test_work_context_uses_every_word_not_only_one_matching_word():
    values=inputs();values[3][0]['text']='ООО «Исполнитель» (кровля монолит) ИТР 1, рабочие 8'
    got=view(values)
    assert all(r['workers_fact'] is None for r in got['rows'])


def test_download_guard_pins_raw_presence_sources_and_existing_bindings(monkeypatch,tmp_path):
    import developaid_monitor_daily as daily
    native_home(monkeypatch,tmp_path)
    values=inputs();reports=values[3]
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    got=view(values)
    got['cohort_source_guard']=workforce.cohort_sources('test','2026-01-25')
    assert workforce.require_current(got,'test')
    assert not workforce.require_current(got,'test',existing_bindings=[{'scope':'changed'}])
    reports[0]['text']=reports[0]['text'].replace('ИТР 1, ','')
    assert not workforce.require_current(got,'test')
    reports.append({'date':'2026-01-21','text':'Новый исходник без категории численности'})
    assert not workforce.require_current(got,'test')


def test_empty_and_unbound_projection_never_creates_placeholder_sheet():
    wb=Workbook()
    assert workforce.write_sheet(wb,{}) is None
    values=inputs();values[3].clear();values[2]['resources']=[]
    assert not view(values)['available']
    assert workforce.write_sheet(wb,view(values)) is None


def test_source_text_is_always_excel_text_even_if_it_starts_with_formula():
    got=view();got['rows'][0]['reasons']=['=HYPERLINK("bad")']
    sheet=workforce.write_sheet(Workbook(),got)
    assert sheet['H6'].data_type=='s' and sheet['H6'].value.startswith('=')
    assert {c.coordinate for row in sheet for c in row if c.data_type=='f'}=={'D6','G6'}


@pytest.mark.parametrize('caption',[
    'Рабочие каменной кладки на объекте',
    'Количество рабочих каменной кладки на объекте',
    'Количество рабочих на объекте (каменная кладка)',
    'Количество рабочих на объекте (отделочники,подсобники)',
    'Всего рабочих на монтаж лифта 1',
    'Количество рабочих на объекте Корпус 2',
    'Количество рабочих на объекте (подсобники)'])
def test_restrictive_or_foreign_resource_caption_does_not_become_full_roof_crew(caption):
    values=inputs();values[2]['resources'][0]['name']=caption
    got=view(values)['rows'][0]
    assert got['workers_plan']==10 and got['workers_fact'] is got['workers_delta'] is None
    assert got['itr_delta']==-1


def test_compact_counts_keep_every_digit():
    values=inputs();values[3][0]['text']='ООО «Исполнитель», договор A-123 ИТР12, рабочие123'
    got=view(values)['rows'][0]
    assert got['workers_fact']==123 and got['itr_fact']==12


def native_home(monkeypatch,tmp_path):
    import developaid_monitor as monitor
    base=tmp_path/'monitor';base.mkdir()
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',base)
    root=monitor._project_dir('test');root.mkdir(exist_ok=True)
    folder=root/'contract_documents'/('a'*64);folder.mkdir(parents=True)
    (folder/('b'*64+'.json')).write_text('{"reader":15,"scope":"кровля"}')
    (folder/('b'*64+'.pdf')).write_bytes(b'%PDF-native-immutable-source')
    cumulative=root/'cumulative';cumulative.mkdir()
    stem='2026-01-01-'+'c'*64
    (cumulative/(stem+'.json')).write_text('{"taken_at":"2026-01-01"}')
    (cumulative/(stem+'.zip')).write_bytes(b'ZIP-native-source-not-read')
    return root,folder


def native_projection(monkeypatch,tmp_path):
    import developaid_monitor_daily as daily
    root,folder=native_home(monkeypatch,tmp_path)
    row,source,schedule,reports,register=inputs()
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    register[workforce.REGISTER_GUARD]=workforce.cohort_sources('test','2026-01-25')
    view=workforce.from_cached('test',row,register,'2026-01-25',{'schedule':schedule,'source':source})
    return root,folder,view,(row,register,{'schedule':schedule,'source':source})


def test_native_source_guard_never_builds_register_or_reads_pdf_zip(monkeypatch,tmp_path):
    import developaid_monitor_contracts as contracts
    import developaid_contract_identity_store as store
    native_home(monkeypatch,tmp_path)
    monkeypatch.setattr(contracts,'build',lambda *a,**k:pytest.fail('financial register rebuilt'))
    original=store.read_bytes
    read=[]
    def bounded(path,*args,**kw):
        assert path.suffix not in {'.pdf','.zip'}
        read.append(path.name)
        return original(path,*args,**kw)
    monkeypatch.setattr(store,'read_bytes',bounded)
    first=workforce.cohort_sources('test','2026-01-25')
    assert first==workforce.cohort_sources('test','2026-01-25')
    assert 'b'*64+'.json' in read


def test_new_peer_contract_invalidates_old_preview_without_daily_or_target_change(monkeypatch,tmp_path):
    root,folder,got,args=native_projection(monkeypatch,tmp_path)
    assert workforce.require_current(got,'test')
    peer=root/'contract_documents'/('d'*64);peer.mkdir()
    (peer/('e'*64+'.json')).write_text('{"contract":"A-456","scope":"Кровля"}')
    assert not workforce.require_current(got,'test')
    row,register,gpr=args
    with pytest.raises(workforce.SourceChanged) as error:
        workforce.from_cached('test',row,register,'2026-01-25',gpr)
    assert error.value.status==409


def test_peer_scope_content_hash_changes_even_if_size_and_mtime_are_preserved(monkeypatch,tmp_path):
    root,folder,got,args=native_projection(monkeypatch,tmp_path)
    peer=root/'contract_documents'/('d'*64);peer.mkdir()
    path=peer/('e'*64+'.json');path.write_text('{"scope":"alpha"}')
    pin=workforce.cohort_sources('test','2026-01-25');got['cohort_source_guard']=pin
    old=path.stat();path.write_text('{"scope":"bravo"}')
    os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
    assert path.stat().st_size==old.st_size and path.stat().st_mtime_ns==old.st_mtime_ns
    assert not workforce.require_current(got,'test')


@pytest.mark.parametrize('relative',[
    'contract_identity_decisions.jsonl','cumulative_terms.json','cumulative_header_dates.json',
    'contract_links.json','contract_pdf_sources.json',
    'contract_documents/'+'a'*64+'/links.json',
    'cumulative/.snapshot-activity.json',
    'cumulative/2026-01-02-'+'f'*64+'.json'])
def test_identity_terms_choices_and_active_source_roster_are_pinned(monkeypatch,tmp_path,relative):
    root,_,got,_=native_projection(monkeypatch,tmp_path)
    (root/relative).write_text('{}')
    assert not workforce.require_current(got,'test')


def test_mid_build_peer_edit_cannot_get_a_new_signature_for_old_register(monkeypatch,tmp_path):
    import developaid_monitor_daily as daily
    root,_=native_home(monkeypatch,tmp_path)
    row,source,schedule,reports,register=inputs()
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    register[workforce.REGISTER_GUARD]=workforce.cohort_sources('test','2026-01-25')
    (root/'cumulative_terms.json').write_text('{"changed_peer":true}')  # Between register build and projection.
    with pytest.raises(workforce.SourceChanged):
        workforce.from_cached('test',row,register,'2026-01-25',{'schedule':schedule,'source':source})


def test_one_derived_cache_upgrade_requires_one_fresh_producer_not_an_endless_refresh(monkeypatch,tmp_path):
    import developaid_monitor_daily as daily
    _,folder=native_home(monkeypatch,tmp_path)
    path=folder/('b'*64+'.json');path.write_text('{"reader":14,"scope":"кровля"}')
    row,source,schedule,reports,register=inputs()
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    register[workforce.REGISTER_GUARD]=workforce.cohort_sources('test','2026-01-25')
    path.write_text('{"reader":15,"scope":"кровля","resources":[]}')
    with pytest.raises(workforce.SourceChanged):
        workforce.from_cached('test',row,register,'2026-01-25',{'schedule':schedule,'source':source})
    register[workforce.REGISTER_GUARD]=workforce.cohort_sources('test','2026-01-25')
    got=workforce.from_cached('test',row,register,'2026-01-25',{'schedule':schedule,'source':source})
    assert got['rows'][0]['workers_delta']==-2
    assert workforce.require_current(got,'test') and workforce.require_current(got,'test')


def test_partial_existing_native_family_is_reused_without_nested_or_expanded_locks(monkeypatch,tmp_path):
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as store
    root,folder=native_home(monkeypatch,tmp_path)
    with store.namespace('test'),identity._binding_path_locks([folder/'.lock']):
        monkeypatch.setattr(identity,'_binding_path_locks',lambda *a,**kw:pytest.fail('expanded held locks'))
        monkeypatch.setattr(store,'locked',lambda *a,**kw:pytest.fail('nested nonreentrant identity lock'))
        assert workforce.cohort_sources('test','2026-01-25')['sources_sha256']


def test_symlink_and_bounded_metadata_fail_closed(monkeypatch,tmp_path):
    _,folder,got,_=native_projection(monkeypatch,tmp_path)
    path=folder/('b'*64+'.json');path.unlink();path.symlink_to(tmp_path/'foreign.json')
    assert not workforce.require_current(got,'test')
    path.unlink();path.write_text('{}')
    monkeypatch.setattr(workforce,'MAX_COHORT_BYTES',1)
    assert not workforce.require_current(got,'test')


def test_two_pass_peer_inventory_rejects_drift_while_only_a_partial_family_is_held(monkeypatch,tmp_path):
    import developaid_contract_identity as identity
    import developaid_contract_identity_store as store
    import developaid_contract_files as files
    root,folder=native_home(monkeypatch,tmp_path)
    actual=workforce._cohort_inventory;calls=[]
    def changing(*args,**kwargs):
        result=actual(*args,**kwargs);calls.append(1)
        if len(calls)==1:
            (root/'cumulative_terms.json').write_text('{"other_contract":"changed"}')
        return result
    monkeypatch.setattr(workforce,'_cohort_inventory',changing)
    with store.namespace('test'),identity._binding_path_locks([folder/'.lock']):
        with pytest.raises(files.ContractFilesProblem,match='изменились'):
            workforce.cohort_sources('test','2026-01-25')


def test_projection_cannot_create_its_own_before_build_peer_pin(monkeypatch,tmp_path):
    import developaid_monitor_daily as daily
    native_home(monkeypatch,tmp_path)
    row,source,schedule,reports,register=inputs()
    monkeypatch.setattr(daily,'_load_reports',lambda _:reports)
    with pytest.raises(workforce.SourceChanged):
        workforce.from_cached('test',row,register,'2026-01-25',{'source':source,'schedule':schedule})


def test_own_calendar_event_uses_separate_target_gpr_guard_not_peer_cohort_scope(monkeypatch,tmp_path):
    _,folder,got,_=native_projection(monkeypatch,tmp_path)
    (folder/'gpr-events.json').write_text('[{"action":"handover"}]')
    assert workforce.require_current(got,'test')


def test_rss_inventory_can_change_register_subject_and_is_also_pinned(monkeypatch,tmp_path):
    root,_,got,_=native_projection(monkeypatch,tmp_path)
    estimate=root/'estimate';estimate.mkdir()
    (estimate/'2026-01-01.xlsx').write_bytes(b'native-workbook-not-read')
    assert not workforce.require_current(got,'test')


def test_summary_observations_keep_two_disciplines_without_allocating_a_contract_crew():
    values=list(inputs());row,_,_,_,register=values
    register['rows'].append(dict(row,id='c'*64,contract='A-456',scope=['Кладка']))
    values[3]=[{'date':'2026-01-20','parsed':{'contractors':[
        {'name':'Исполнитель (кровля)','workers':8,'itr':1},
        {'name':'Исполнитель (кладка)','workers':15,'itr':1}]},
        'source':{'kind':'monitor_daily_summary','contract_scope_confirmed':False}}]
    result=view(values)
    assert len(result['company_observations'])==2
    assert [p['candidate']['workers'] for p in result['company_observations']]==[8,15]
    assert result['report_dates']==['2026-01-20']
    assert result['available']  # Source plan remains available.
    assert all(r['workers_fact'] is r['itr_fact'] is r['workers_delta'] is None for r in result['rows'])
    assert any('полный состав' in reason for r in result['rows'] for reason in r['reasons'])
