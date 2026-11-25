"""Only one approved, source-audited date correction preserves saved choices."""
import copy
import datetime as dt
import io
import json
import zipfile

from openpyxl import load_workbook
import pytest

import developaid_gpr_source_prepare as prepare
import developaid_monitor as monitor
import developaid_readiness_date_carry as carry
import developaid_schedule_elements as elements
import developaid_schedule_readiness as ready
import developaid_schedule_versions as versions
from test_gpr_corpus_preview import book

PROJECT='Synthetic date correction profile'
DAY='2026-11-14'
NOW='2026-11-17'


def changed(data, edits):
    wb=load_workbook(io.BytesIO(data))
    for sheet,cell,value in edits:wb[sheet][cell]=value
    stream=io.BytesIO();wb.save(stream);wb.close()
    return stream.getvalue()


def rewritten_xml(data, transform):
    stream=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(stream,'w') as target:
        for item in source.infolist():
            raw=source.read(item)
            if item.filename=='xl/worksheets/sheet2.xml':raw=transform(raw)
            target.writestr(item,raw)
    return stream.getvalue()


def measurements(result):
    # Planned dates legitimately change the conditional forecast, not saved weights/facts.
    return {key:value for key,value in result.items() if key!='forecast'}


@pytest.fixture
def site(tmp_path,monkeypatch):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    clock=[dt.datetime(2026,11,14,12,tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(versions,'_now',lambda:clock[0])
    initial=book(bad_date='31.07.2027',name='Initial source')
    monitor.store_schedule(PROJECT,initial,None,'2026-11-06')
    raw=changed(book(bad_date='31.07.2027',name='Synthetic facade'),[
        ('ГПР','A4','Фасады'),('ГПР','E5',0),('ГПР','E6',.5)])
    state=monitor._working_baseline_state(PROJECT)
    monitor.approve_schedule_version(PROJECT,raw,DAY,
        expected_previous_sha256=state['source_sha256'],expected_source_sha256=versions.digest(raw),baseline_scope='remaining_work')
    parent=monitor._working_baseline_state(PROJECT)
    full=ready._catalog(PROJECT,parent['source_sha256'])
    included=[key for key,row in full.items() if row['object']=='КОРПУС 1']
    excluded=sorted(set(full)-set(included))
    cfg=dict(label='Synthetic explicit choices',scope_kind=ready.CURRENT_ESTIMATE,
        scope_note=ready.CURRENT_ESTIMATE_NOTE,basis='estimated_elements',source_reference='Synthetic expert decision',
        building_type='Synthetic',full_source_sha256=parent['source_sha256'],effective_from=DAY,
        full_scope_confirmed=False,included_ids=included,excluded_ids=excluded,
        outside_completed_ids=[],owner_note='',crosswalk=[],weights=[],element_profile=dict(
            id=elements.PROFILE_ID,overrides={key:0 for key,_,_ in elements.ELEMENTS if key!='frame'},
            objects={'КОРПУС 1':'residential','КОРПУС 2':'separate'},corpus_shares={'КОРПУС 1':100},
            assignments={included[0]:{'element_id':'frame','share':25},included[1]:{'element_id':'frame','share':75}}))
    return dict(root=monitor._project_dir(PROJECT),clock=clock,parent=parent,raw=raw,cfg=cfg)


def save_profile(site, *, effective=DAY, partial=False):
    cfg=copy.deepcopy(site['cfg']);cfg['effective_from']=effective
    if partial:cfg['element_profile']['assignments'].pop(cfg['included_ids'][0])
    opts=dict(expected_source_sha256=site['parent']['source_sha256'],expected_source_revision=site['parent']['revision'],expected_revision=len(ready._events(PROJECT)))
    draft=ready.preview(PROJECT,cfg,**opts)
    ready.save(PROJECT,cfg,**opts,expected_profile_sha256=draft['profile_sha256'],author='synthetic-owner')
    return ready._events(PROJECT)[-1]


def prepared(site):
    site['clock'][0]=dt.datetime(2026,11,17,12,tzinfo=dt.timezone.utc)
    return prepare.prepare(PROJECT,site['parent']['source_sha256'],
        expected_active_sha256=site['parent']['source_sha256'],expected_revision=site['parent']['revision'],
        corrections=[{'cell':'F5','expected_raw':'01.11.2026','value':'25.02.2027','note':'Synthetic explicit date correction'}])['data']


def approve(data):
    state=monitor._working_baseline_state(PROJECT)
    return monitor.approve_schedule_version(PROJECT,data,NOW,
        expected_previous_sha256=state['source_sha256'],expected_source_sha256=versions.digest(data),baseline_scope='remaining_work')


@pytest.mark.parametrize('partial',[False,True])
def test_native_date_only_approval_preserves_asof_choices_and_uses_child_dates(site,partial):
    save_profile(site,partial=partial)
    original=save_profile(site,partial=partial)
    before={cut:monitor.build(PROJECT,cut)['schedule']['readiness'] for cut in ('2026-11-16',NOW)}
    journal=site['root']/'readiness_profiles.json';original_bytes=journal.read_bytes()
    approve(prepared(site))
    source_bytes={p:p.read_bytes() for p in (site['root']/'baseline').rglob('*.xlsx')}
    child=monitor._working_baseline_state(PROJECT)
    for cut in ('2026-11-16',NOW):
        view=monitor.build(PROJECT,cut);state=view['schedule']['readiness']
        assert measurements(state['project'])==measurements(before[cut]['project'])
        assert [measurements(row) for row in state['corpora']]==[measurements(row) for row in before[cut]['corpora']]
        assert state['project']['forecast']['finish']=='2027-07-31'
        assert before[cut]['project']['forecast']['finish']!='2027-07-31'
        assert state['profile_revision']==original['revision']
        assert state['profile_sha256']==original['profile_sha256']
        assert state['profile_effective_from']==DAY
        assert state['profile_source_carry']['source_effective_from']==NOW
        assert state['profile_source_carry']['persisted'] is False
        assert state['source_sha256']==child['source_sha256']
        assert state['forecast_identity']['full_source_sha256']==child['source_sha256']
        assert not state['full_scope_confirmed']
        row=next(r for r in view['schedule']['rows'] if r['id']==site['cfg']['included_ids'][0])
        assert row['plan_start']=='2027-02-25'
        assert row['gpr_progress']==0
        if cut=='2026-11-16':
            proof=state['fact_source_carry']
            assert proof['from_source_sha256']==site['parent']['source_sha256']
            assert proof['to_source_sha256']==child['source_sha256']
            assert proof['parent_effective_from']==DAY and proof['source_effective_from']==NOW
            assert row['gpr_fact_source_carry']['fact_date']<cut
    editor=ready.editor(PROJECT)
    for field in ('weights','included_ids','excluded_ids','element_profile'):
        assert editor['configuration'][field]==original['profile'][field]
    assert editor['configuration']['full_source_sha256']==child['source_sha256']
    assert editor['configuration']['effective_from']==NOW  # Unsaved draft, not backdating the original.
    assert editor['source_carry']['profile_sha256']==original['profile_sha256']
    assert editor['history'][-1]['source_sha256']==site['parent']['source_sha256']
    assert editor['history'][-1]['profile_sha256']==original['profile_sha256']
    assert editor['options']['expected_source_revision']==child['revision']
    assert editor['options']['expected_revision']==original['revision']
    assert journal.read_bytes()==original_bytes
    assert all(p.read_bytes()==raw for p,raw in source_bytes.items())
    historical=monitor.build(PROJECT,'2026-11-13')['schedule']['readiness']
    assert historical['profile_revision']==0 and 'profile_source_carry' not in historical


def test_future_profile_is_not_selected_or_projected(site):
    save_profile(site,effective='2026-11-18')
    approve(prepared(site))
    state=monitor.build(PROJECT,'2026-11-16')['schedule']['readiness']
    assert state['profile_revision']==0 and state['pending_profile']=='future'
    assert state['project']['progress'] is None and 'profile_source_carry' not in state
    editor=ready.editor(PROJECT)
    assert editor['source_carry'] is None
    assert editor['configuration']['element_profile']['assignments']=={}


@pytest.mark.parametrize('edits',[
    [('ГПР','E5',.75)], [('ГПР','E3','Факт 07.11.2026')],
    [('ГПР','B5','Another work')], [('ГПР','D5','Different status')],
    [('ГПР','A4','Another scope')],
    [('Происхождение','B2','f'*64)], [('Происхождение','B3','f'*64)],
    [('Происхождение','B4',99)], [('Происхождение','B6','wrong prior raw')],
    [('Происхождение','C6','26.02.2027')], [('Происхождение','A6','G5')],
    [('Происхождение','E6','unknown extra audit column')],
    [('Происхождение','A161','unknown extra audit row')],
])
def test_semantic_and_provenance_changes_never_carry(site,edits):
    original=save_profile(site)
    approve(changed(prepared(site),edits))
    state=monitor.build(PROJECT,'2026-11-16')['schedule']['readiness']
    assert state['project']['progress'] is None
    assert 'profile_source_carry' not in state
    assert state['profile_sha256']==original['profile_sha256']
    assert 'Перенос долей' in state['reason']


def test_second_hop_and_arbitrary_replacement_do_not_map_a_profile(site):
    original=save_profile(site)
    approve(prepared(site))
    current=monitor._working_baseline_state(PROJECT)
    second=prepare.prepare(PROJECT,current['source_sha256'],expected_active_sha256=current['source_sha256'],
        expected_revision=current['revision'],corrections=[{'cell':'F5','expected_raw':'25.02.2027',
            'value':'26.02.2027','note':'Another synthetic correction'}])['data']
    approve(second)
    state=monitor.build(PROJECT,'2026-11-16')['schedule']['readiness']
    assert state['project']['progress'] is None and 'profile_source_carry' not in state
    with pytest.raises(ValueError):carry.project(PROJECT,original['profile'],current['source_sha256'])


@pytest.mark.parametrize('which',['parent','child'])
def test_independent_saved_source_digest_guard(site,which):
    original=save_profile(site);approve(prepared(site))
    schedule=monitor.build(PROJECT,'2026-11-16')['schedule']
    child=monitor._working_baseline_state(PROJECT)
    sha=site['parent']['source_sha256'] if which=='parent' else child['source_sha256']
    path=site['root']/'baseline'/'schedule_sources'/(sha+'.xlsx')
    path.write_bytes(path.read_bytes()+b'corrupt')
    result=ready.build(PROJECT,'2026-11-16',schedule)
    assert result['project']['progress'] is None and 'profile_source_carry' not in result
    assert result['profile_sha256']==original['profile_sha256']


def test_unknown_or_duration_weight_method_fails_closed_without_a_new_500(site):
    save_profile(site);approve(prepared(site))
    path=site['root']/'readiness_profiles.json';payload=json.loads(path.read_text())
    event=payload['events'][-1];assignment=next(iter(event['profile']['element_profile']['assignments'].values()))
    assignment.update(share=None,weight={'basis':'duration','value':100,'unit':'days','source_reference':'unsupported',
        'valuation_key':'unsupported','cost_basis':'','position_keys':['unsupported'],'full_scope':True})
    event['profile_sha256']=ready._digest(event['profile']);path.write_text(json.dumps(payload))
    result=monitor.build(PROJECT,'2026-11-16')['schedule']['readiness']
    assert result['project']['progress'] is None and 'profile_source_carry' not in result
    assert ready.editor(PROJECT)['source_carry'] is None


@pytest.mark.parametrize('transform',[
    lambda xml:xml.replace(b'<row r="100">',b'<row r="9999">'),
    lambda xml:xml.replace(b'<row r="100">',b'<row r="0100">'),
    lambda xml:xml.replace(b'<row r="100">',b'<row r="6">'),
    lambda xml:xml.replace(b'</sheetData>',b'</sheetData><c r="D100"><v>1</v></c>'),
])
def test_entire_provenance_xml_is_validated_before_bounded_iteration(site,transform):
    raw=changed(prepared(site),[('Происхождение','D100','Unknown hidden audit content')])
    malicious=rewritten_xml(raw,transform)
    assert malicious!=raw
    with pytest.raises(carry.DateCarryProblem):carry._audit(malicious)


def test_arbitrary_date_only_replacement_without_saved_prepare_provenance_is_rejected(site):
    save_profile(site)
    site['clock'][0]=dt.datetime(2026,11,17,12,tzinfo=dt.timezone.utc)
    approve(changed(site['raw'],[('ГПР','F5','25.02.2027')]))
    view=monitor.build(PROJECT,'2026-11-16')
    assert view['schedule']['readiness']['project']['progress'] is None
    assert 'fact_source_carry' not in view['schedule']


def test_corrupt_native_zip_with_missing_mandatory_members_has_a_typed_failure():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr('xl/worksheets/sheet1.xml','<worksheet/>')
    with pytest.raises(carry.DateCarryProblem):carry._audit(stream.getvalue())


def test_fact_lineage_does_not_require_any_readiness_profile(site):
    import developaid_schedule_gpr_forecast as facts
    before=facts.history(PROJECT,dt.date(2026,11,16))
    assert not ready._events(PROJECT)
    approve(prepared(site))
    after=facts.history(PROJECT,dt.date(2026,11,16))
    assert after==before
    assert after.source_carry['kind']=='unchanged_parent_gpr_facts'
    assert any(reading[1]==0 for readings in after.values() for reading in readings)


def test_full_schedule_scope_never_reuses_remaining_profile_decisions(site):
    original=save_profile(site);raw=prepared(site)
    current=monitor._working_baseline_state(PROJECT)
    monitor.approve_schedule_version(PROJECT,raw,NOW,
        expected_previous_sha256=current['source_sha256'],expected_source_sha256=versions.digest(raw),baseline_scope='full_schedule')
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],versions.digest(raw))
    result=monitor.build(PROJECT,NOW)['schedule']['readiness']
    assert result['project']['progress'] is None and 'profile_source_carry' not in result


def test_parent_fact_approval_and_effective_date_must_already_be_available(site):
    save_profile(site);approve(prepared(site))
    import developaid_schedule_gpr_forecast as facts
    from unittest.mock import patch
    parent,child,proof=carry.verified_transition(PROJECT,monitor._working_baseline_state(PROJECT)['source_sha256'])
    for field,value in [('parent_effective_from',NOW),('parent_approved_at',NOW+'T01:00:00+00:00')]:
        with patch.object(carry,'verified_transition',return_value=(parent,child,dict(proof,**{field:value}))):
            with pytest.raises(carry.DateCarryProblem):carry.parent_facts(PROJECT,proof['to_source_sha256'],'2026-11-16')
            assert not facts.history(PROJECT,dt.date(2026,11,16))


def test_unsupported_earlier_history_is_visible_without_becoming_an_active_method(site):
    save_profile(site);latest=save_profile(site);approve(prepared(site))
    path=site['root']/'readiness_profiles.json';payload=json.loads(path.read_text())
    event=payload['events'][0]
    assignment=next(iter(event['profile']['element_profile']['assignments'].values()))
    assignment['weight']={'basis':'future_unknown_method'}
    event['profile_sha256']=ready._digest(event['profile']);path.write_text(json.dumps(payload))
    saved=path.read_bytes()
    editor=ready.editor(PROJECT)
    assert editor['source_carry']['profile_revision']==latest['revision']
    assert editor['configuration']['element_profile']==latest['profile']['element_profile']
    assert editor['history'][0]['internal_methods']==['Неизвестное основание внутренних долей']
    assert editor['history'][0]['profile_sha256']==event['profile_sha256']
    assert path.read_bytes()==saved


def test_future_header_facts_stay_unknown_even_with_verified_date_only_lineage(site):
    # A verified date-only transition cannot authorize a future header reading.
    import developaid_schedule_gpr_forecast as facts
    from unittest.mock import patch
    approve(prepared(site))
    child=monitor._working_baseline_state(PROJECT)
    parent,rows,proof=carry.verified_transition(PROJECT,child['source_sha256'])
    parent=copy.deepcopy(parent)
    for row in parent.values():row['progress_date']='2026-11-18'
    with patch.object(carry,'verified_transition',return_value=(parent,rows,proof)):
        assert not facts.history(PROJECT,dt.date(2026,11,16))


def test_successful_projection_does_not_hide_unexpected_programming_errors(site,monkeypatch):
    save_profile(site);approve(prepared(site))
    def broken(*args,**kwargs):raise RuntimeError('synthetic implementation bug')
    monkeypatch.setattr(carry,'project',broken)
    with pytest.raises(RuntimeError,match='synthetic implementation bug'):monitor.build(PROJECT,'2026-11-16')
    with pytest.raises(RuntimeError,match='synthetic implementation bug'):ready.editor(PROJECT)


def test_projected_editor_is_an_unsaved_draft_requiring_fresh_native_confirmation(site):
    original=save_profile(site);approve(prepared(site))
    editor=ready.editor(PROJECT)
    saved_events=copy.deepcopy(ready._events(PROJECT))
    with pytest.raises(versions.ScheduleVersionConflict):
        ready.preview(PROJECT,editor['configuration'],expected_source_sha256=site['parent']['source_sha256'],
            expected_source_revision=site['parent']['revision'],expected_revision=original['revision'])
    preview=ready.preview(PROJECT,editor['configuration'],**editor['options'])
    assert preview['profile_sha256']!=original['profile_sha256']
    result=ready.save(PROJECT,editor['configuration'],**editor['options'],
        expected_profile_sha256=preview['profile_sha256'],author='synthetic-new-confirmation')
    assert result['revision']==original['revision']+1
    assert ready._events(PROJECT)[:-1]==saved_events
    assert ready.editor(PROJECT)['source_carry'] is None


from test_monitor_cumulative_api import api
from test_monitor_cumulative_controls import browser_page, KEY as BROWSER_KEY


@pytest.mark.parametrize('width',[390,1440])
def test_native_editor_explains_retained_choices_without_claiming_a_saved_child_profile(site,api,monkeypatch,width,tmp_path):
    from urllib.parse import urlsplit
    from playwright.sync_api import expect
    save_profile(site);approve(prepared(site))
    journal=site['root']/'readiness_profiles.json';saved=journal.read_bytes()
    client,_=api
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY',BROWSER_KEY)
    with browser_page(width) as (page,responses,errors):
        def native_readiness(route):
            response=client.post(urlsplit(route.request.url).path,json=route.request.post_data_json)
            route.fulfill(status=response.status_code,json=response.json())
        page.route('**/monitor/readiness/**',native_readiness)
        page.route('**/monitor/daily/summary*',lambda route:route.fulfill(json={}))
        page.locator('#project').fill(PROJECT);page.locator('#cut').fill('2026-11-16')
        page.evaluate('(value)=>{currentView=value;renderGantt(value)}',monitor.build(PROJECT,'2026-11-16'))
        page.locator('#readinessEditor>summary').click()
        body=page.locator('#readinessEditorBody')
        expect(body).to_contain_text('Использованы доли сохранённого профиля № 1')
        expect(body).to_contain_text('Отдельное подтверждение профиля для новой версии не записано.')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert journal.read_bytes()==saved
        page.screenshot(path=str(tmp_path/f'date-only-choices-{width}.png'),full_page=True)
        assert not errors
