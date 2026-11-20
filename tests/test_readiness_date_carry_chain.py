"""Only synthetic 2031/2032 dates; no pending owner correction is modelled."""
import copy
import datetime as dt
import io
import json

from openpyxl import Workbook
import pytest

import developaid_gpr_source_prepare as prepare
import developaid_gpr_work_forecast as work
import developaid_monitor as monitor
import developaid_readiness_date_carry as carry
import developaid_schedule_elements as elements
import developaid_schedule_gpr_forecast as facts
import developaid_schedule_readiness as ready
import developaid_schedule_versions as versions
from test_readiness_date_only_projection import changed

PROJECT = 'Synthetic bounded date lineage'
ROOT_DAY, CUT, FIRST_DAY, SECOND_DAY = '2031-04-10', '2031-04-11', '2031-04-12', '2031-04-13'


def book(label):
    wb = Workbook(); ws = wb.active; ws.title = 'ГПР'
    ws.append(['Synthetic'])
    ws.append(['№', 'Наименование работ', 'Стадия', 'Статус', 'КОРПУС 1', None, None,
               'КОРПУС 2', None, None, 'ПАРКИНГ'])
    ws.append([None]*4+['Факт 03.04.2031', 'Старт', 'Финиш']*3)
    ws.append(['Конструктив'])
    ws.append([1, label, 'СМР', 'В работе', .25, '01.01.2031', '31.03.2032',
               .5, '01.01.2031', '31.03.2032', 0, None, None])
    ws.append([2, 'Synthetic second work', 'СМР', 'В работе', .5, '01.02.2031', '30.04.2032',
               0, '01.02.2031', '30.04.2032', 0, None, None])
    out = io.BytesIO(); wb.save(out); wb.close(); return out.getvalue()


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    clock = [dt.datetime(2031, 4, 10, 12, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(versions, '_now', lambda: clock[0])
    monitor.store_schedule(PROJECT, book('Initial source'), None, '2031-04-03')
    current = monitor._working_baseline_state(PROJECT); raw = book('Synthetic root work')
    monitor.approve_schedule_version(PROJECT, raw, ROOT_DAY,
        expected_previous_sha256=current['source_sha256'], expected_source_sha256=versions.digest(raw),
        baseline_scope='remaining_work')
    root = monitor._working_baseline_state(PROJECT); catalog = ready._catalog(PROJECT, root['source_sha256'])
    ids = [key for key, row in catalog.items() if row['object']=='КОРПУС 1']
    cfg = dict(label='Synthetic saved choices', scope_kind=ready.CURRENT_ESTIMATE,
        scope_note=ready.CURRENT_ESTIMATE_NOTE, basis='estimated_elements', source_reference='Synthetic',
        building_type='Synthetic', full_source_sha256=root['source_sha256'], effective_from=ROOT_DAY,
        full_scope_confirmed=False, included_ids=ids, excluded_ids=sorted(set(catalog)-set(ids)),
        outside_completed_ids=[], owner_note='', crosswalk=[], weights=[], element_profile=dict(
            id=elements.PROFILE_ID, overrides={key:0 for key,_,_ in elements.ELEMENTS if key!='frame'},
            objects={'КОРПУС 1':'residential','КОРПУС 2':'separate'}, corpus_shares={'КОРПУС 1':100},
            assignments={ids[0]:{'element_id':'frame','share':25}, ids[1]:{'element_id':'frame','share':75}}))
    return dict(clock=clock, root=root, directory=monitor._project_dir(PROJECT), cfg=cfg)


def save_profile(site, effective=ROOT_DAY):
    cfg = copy.deepcopy(site['cfg']); cfg['effective_from'] = effective
    state = monitor._working_baseline_state(PROJECT)
    opts = dict(expected_source_sha256=state['source_sha256'], expected_source_revision=state['revision'],
                expected_revision=len(ready._events(PROJECT)))
    preview = ready.preview(PROJECT, cfg, **opts)
    ready.save(PROJECT, cfg, **opts, expected_profile_sha256=preview['profile_sha256'], author='synthetic')
    return ready._events(PROJECT)[-1]


def next_source(site, cell, old, new, day, edits=()):
    site['clock'][0] = dt.datetime.fromisoformat(day+'T12:00:00+00:00')
    state = monitor._working_baseline_state(PROJECT)
    data = prepare.prepare(PROJECT, state['source_sha256'], expected_active_sha256=state['source_sha256'],
        expected_revision=state['revision'], corrections=[dict(cell=cell, expected_raw=old,
            value=new, note='Synthetic date-only correction')])['data']
    if edits: data = changed(data, edits)
    monitor.approve_schedule_version(PROJECT, data, day, expected_previous_sha256=state['source_sha256'],
        expected_source_sha256=versions.digest(data), baseline_scope='remaining_work')
    return monitor._working_baseline_state(PROJECT)


def two_hops(site, edits=()):
    first = next_source(site, 'F5', '01.01.2031', '02.01.2031', FIRST_DAY, edits)
    second = next_source(site, 'F6', '01.02.2031', '02.02.2031', SECOND_DAY)
    return first, second


def semantic_readiness(s):
    return {k:copy.deepcopy(s[k]) for k in ('profile_revision','profile_sha256','profile_effective_from',
        'profile_reference_source_sha256','share_total','internal_weight_methods')}


def test_two_verified_edges_preserve_selected_profile_facts_editor_and_truthful_proof(site):
    original = save_profile(site); journal = site['directory']/'readiness_profiles.json'; saved = journal.read_bytes()
    before = monitor.build(PROJECT, CUT)['schedule']
    historical_before = facts.history(PROJECT, dt.date.fromisoformat(CUT))
    first, second = two_hops(site)
    inputs = {p:p.read_bytes() for p in (site['directory']/'baseline').rglob('*.xlsx')}
    after = monitor.build(PROJECT, CUT)['schedule']; state = after['readiness']; proof = state['profile_source_carry']
    assert semantic_readiness(state)==semantic_readiness(before['readiness'])
    assert state['project']['progress']==before['readiness']['project']['progress']
    assert state['project']['known_weights']==before['readiness']['project']['known_weights']
    assert proof['from_source_sha256']==proof['reference_source_sha256']==site['root']['source_sha256']
    assert proof['immediate_parent_source_sha256']==first['source_sha256']
    assert proof['parent_effective_from']==FIRST_DAY and proof['reference_effective_from']==ROOT_DAY
    assert proof['source_revision']==second['revision'] and proof['changed_date_cells']==['F5','F6']
    assert len(proof['lineage_steps'])==2 and work._carry_consistent(after,state,proof)
    assert state['fact_source_carry']['reference_effective_from']==ROOT_DAY
    assert facts.history(PROJECT,dt.date.fromisoformat(CUT))==historical_before
    assert after['owner_rnv']==before['owner_rnv']
    old_primary={k:v['primary'] for k,v in before['work_fact']['works'].items()}
    new_primary={k:{f:x for f,x in v['primary'].items() if f!='source_carry'} for k,v in after['work_fact']['works'].items()}
    assert new_primary==old_primary
    assert work.build(after,CUT)['state'] != 'unavailable'
    editor = ready.editor(PROJECT)
    for field in ('weights','included_ids','excluded_ids','element_profile'):
        assert editor['configuration'][field]==original['profile'][field]
    assert editor['source_carry']['reference_source_sha256']==site['root']['source_sha256']
    assert editor['history'][-1]['profile_sha256']==original['profile_sha256']
    assert journal.read_bytes()==saved and all(p.read_bytes()==raw for p,raw in inputs.items())
    with pytest.raises(carry.DateCarryProblem):
        carry.verified_transition(PROJECT,second['source_sha256'],expected_parent_sha=site['root']['source_sha256'])


def test_nearer_fact_origin_is_suffix_of_original_profile_chain(site):
    save_profile(site); first, second = two_hops(site)
    # This cut predates the current approval but includes the first correction.
    s = monitor.build(PROJECT,FIRST_DAY)['schedule']; state=s['readiness']
    profile=state['profile_source_carry']; fact=state['fact_source_carry']
    assert len(profile['lineage_steps'])==2 and 'lineage_steps'not in fact
    assert fact['from_source_sha256']==first['source_sha256']!=profile['from_source_sha256']
    assert work._carry_consistent(s,state,profile) and work.build(s,FIRST_DAY)['state'] != 'unavailable'
    for row in s['rows']:
        if row.get('gpr_fact_source_carry'):
            assert row['gpr_fact_source_carry']['from_source_sha256']==first['source_sha256']


@pytest.mark.parametrize('edits',[
    [('ГПР','E5',.125)], [('ГПР','E3','Факт 04.04.2031')],
    [('ГПР','B5','Different definition')], [('ГПР','D5','Different status')],
    [('ГПР','A4','Different group')], [('ГПР','I5','03.01.2031')],
    [('ГПР','G5','30.03.2032')], [('Происхождение','B2','f'*64)],
    [('Происхождение','B3','f'*64)], [('Происхождение','B4',99)],
])
def test_every_intermediate_edge_must_pass_unchanged_native_proof(site,edits):
    original=save_profile(site); first, second=two_hops(site,edits)
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],second['source_sha256'])
    assert monitor.build(PROJECT,CUT)['schedule']['readiness']['profile_state']=='invalid'


@pytest.mark.parametrize('case',['missing_file','raw_sha','missing_event','scope'])
def test_missing_corrupt_or_unindexed_edge_fails_closed(site,case):
    original=save_profile(site);first,second=two_hops(site)
    path=site['directory']/'baseline'/'schedule_sources'/(first['source_sha256']+'.xlsx')
    if case=='missing_file':path.unlink()
    elif case=='raw_sha':path.write_bytes(path.read_bytes()+b'changed')
    else:
        path=site['directory']/'baseline'/'schedule_versions.json';payload=json.loads(path.read_bytes())
        if case=='missing_event':payload['versions'].pop(-2)
        else:payload['versions'][-2]['baseline_scope']='full_schedule'
        path.write_text(json.dumps(payload))
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],second['source_sha256'])


def test_no_profile_dependency_and_future_profile_not_revived(site):
    before=facts.history(PROJECT,dt.date.fromisoformat(CUT));save_profile(site,effective='2031-04-14')
    two_hops(site)
    assert facts.history(PROJECT,dt.date.fromisoformat(CUT))==before
    state=monitor.build(PROJECT,CUT)['schedule']['readiness']
    assert state['profile_revision']==0 and state['profile_state']=='future' and 'profile_source_carry'not in state


@pytest.mark.parametrize('bad',['suffix','intermediate','approval','root','parent','cells','revision','cycle','dropped','row'])
def test_owned_work_guard_rejects_tampered_proof_without_source_reads(site,bad):
    save_profile(site);two_hops(site);s=monitor.build(PROJECT,CUT)['schedule'];state=s['readiness'];proof=state['profile_source_carry']
    if bad=='suffix':
        state['fact_source_carry']['lineage_steps'][0]['changed_date_cells']=['G5']
        s['fact_source_carry']=copy.deepcopy(state['fact_source_carry'])
    elif bad=='intermediate':proof['lineage_steps'][0]['to_source_sha256']='f'*64
    elif bad=='approval':proof['lineage_steps'][0]['source_approved_at']='2031-04-20T12:00:00+00:00'
    elif bad=='root':proof['reference_source_sha256']='f'*64
    elif bad=='parent':proof['immediate_parent_source_sha256']='f'*64
    elif bad=='cells':proof['changed_date_cells']=['F5']
    elif bad=='revision':proof['lineage_steps'][0]['source_revision']=True
    elif bad=='cycle':proof['lineage_steps'][1]['to_source_sha256']=proof['lineage_steps'][0]['from_source_sha256']
    elif bad=='dropped':proof['lineage_steps']=None
    else:
        row=next(r for r in s['rows']if r.get('gpr_fact_source_carry'))
        row['gpr_fact_source_carry']['reference_effective_from']='2031-04-09'
    assert not work._carry_consistent(s,state,proof)


def test_chain_depth_is_bounded_and_single_hop_wire_has_no_new_fields(site,monkeypatch):
    original=save_profile(site);first=next_source(site,'F5','01.01.2031','02.01.2031',FIRST_DAY)
    projected,rows,one=carry.project(PROJECT,original['profile'],first['source_sha256'])
    assert set(one)=={'kind','from_source_sha256','to_source_sha256','source_revision','source_effective_from',
        'source_approved_at','parent_effective_from','parent_approved_at','changed_date_cells','persisted','profile_decisions_unchanged'}
    assert projected['element_profile']==original['profile']['element_profile']
    next_source(site,'F6','01.02.2031','02.02.2031',SECOND_DAY)
    monkeypatch.setattr(carry,'MAX_CHAIN_EDGES',1)
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],monitor._working_baseline_state(PROJECT)['source_sha256'])


@pytest.mark.parametrize('case', ['audit_suffix','same_endpoints','typed_revision','drop_steps'])
def test_consistent_individual_proofs_still_require_the_same_suffix(site,case):
    save_profile(site);two_hops(site)
    cut = CUT if case in ('same_endpoints','drop_steps') else FIRST_DAY
    s=monitor.build(PROJECT,cut)['schedule'];state=s['readiness'];profile=state['profile_source_carry']
    fact=copy.deepcopy(state['fact_source_carry'])
    if case=='audit_suffix':
        fact['changed_date_cells']=['G6']  # Same native endpoints, different audit.
    elif case=='same_endpoints':
        fact['lineage_steps'][0]['changed_date_cells']=['G5']
        fact['changed_date_cells']=['F6','G5']
    elif case=='typed_revision':
        fact['source_revision']=float(fact['source_revision'])
    else:
        profile.pop('lineage_steps')
    state['fact_source_carry']=copy.deepcopy(fact);s['fact_source_carry']=copy.deepcopy(fact)
    for row in s['rows']:
        if row.get('gpr_fact_source_carry'):
            row['gpr_fact_source_carry']={**copy.deepcopy(fact),'fact_date':row['gpr_fact_source_carry']['fact_date']}
    if case!='drop_steps':assert work._carry_steps(fact) is not None
    assert not work._carry_consistent(s,state,profile)


def test_unproven_intermediate_replacement_cannot_be_hidden_by_a_later_valid_edge(site):
    original=save_profile(site);site['clock'][0]=dt.datetime.fromisoformat(FIRST_DAY+'T12:00:00+00:00')
    state=monitor._working_baseline_state(PROJECT)
    raw=versions._read(state['path']);replacement=changed(raw,[('ГПР','F5','02.01.2031')])
    monitor.approve_schedule_version(PROJECT,replacement,FIRST_DAY,
        expected_previous_sha256=state['source_sha256'],expected_source_sha256=versions.digest(replacement),
        baseline_scope='remaining_work')
    latest=next_source(site,'F6','01.02.2031','02.02.2031',SECOND_DAY)
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],latest['source_sha256'])


@pytest.mark.parametrize('field,value', [('format','unsupported'),('packages',[])])
def test_each_catalog_format_and_roster_is_checked(site,monkeypatch,field,value):
    original=save_profile(site);first,second=two_hops(site);reader=carry.corpus.read
    def altered(data):
        result=reader(data)
        if versions.digest(data)==site['root']['source_sha256']:
            result=copy.deepcopy(result);result[field]=value
        return result
    monkeypatch.setattr(carry.corpus,'read',altered)
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],second['source_sha256'])


def test_no_eligible_ancestor_or_future_header_never_admits_past_facts(site,monkeypatch):
    two_hops(site);target=monitor._working_baseline_state(PROJECT)['source_sha256']
    with pytest.raises(carry.DateCarryProblem):carry.parent_facts(PROJECT,target,'2031-04-09')
    original=carry._verified_edge
    def future_header(*a,**kw):
        parent,child,proof=original(*a,**kw);parent=copy.deepcopy(parent)
        for row in parent.values():row['progress_date']='2031-04-14'
        return parent,child,proof
    monkeypatch.setattr(carry,'_verified_edge',future_header)
    assert not facts.history(PROJECT,dt.date.fromisoformat(CUT))


def test_report_reconstruction_and_ks_rnv_preserve_the_same_native_dto(site):
    import developaid_report_gantt as gantt
    save_profile(site);before=monitor.build(PROJECT,CUT)['schedule'];two_hops(site)
    s=monitor.build(PROJECT,CUT)['schedule'];dto=work.build(s,CUT);s['work_forecast']=dto
    block=dict(calendar=gantt.calendar(s,CUT),approved_plan=s['approved_plan'],
        readiness=s['readiness'],work_forecast=dto,work_forecast_groups=s.get('display_groups'))
    result=work.report_model(block,CUT)
    assert result['qualified'] and result['work_forecast']
    assert s['owner_rnv']==before['owner_rnv']
    # Source-identity metadata legitimately names the newly approved book.
    # Physical measurements, coverage and all KS values remain unchanged.
    physical, previous = s['physical_progress'], before['physical_progress']
    assert {k:v for k,v in physical.items() if k not in ('source_sha256','available_corpus')} == {k:v for k,v in previous.items() if k not in ('source_sha256','available_corpus')}
    assert physical['source_sha256']==s['approved_plan']['source_sha256']
    assert physical['available_corpus']['sha256']==s['approved_plan']['source_sha256']
    assert {k:v['ks']for k,v in s['work_fact']['works'].items()}=={k:v['ks']for k,v in before['work_fact']['works'].items()}


def test_repeated_reference_source_is_ambiguous_not_an_implicit_shortcut(site):
    original=save_profile(site)
    root_bytes=versions._read(site['root']['path'])
    next_source(site,'F5','01.01.2031','02.01.2031',FIRST_DAY)
    current=monitor._working_baseline_state(PROJECT)
    site['clock'][0]=dt.datetime.fromisoformat(SECOND_DAY+'T12:00:00+00:00')
    monitor.approve_schedule_version(PROJECT,root_bytes,SECOND_DAY,
        expected_previous_sha256=current['source_sha256'],expected_source_sha256=versions.digest(root_bytes),
        baseline_scope='remaining_work')
    latest=next_source(site,'F6','01.02.2031','02.02.2031','2031-04-14')
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],latest['source_sha256'])


def test_eight_verified_edges_succeed_but_ninth_does_not_extend_budget(site):
    original=save_profile(site);old='01.01.2031'
    for number in range(1,10):
        new=f'{number+1:02d}.01.2031'
        latest=next_source(site,'F5',old,new,f'2031-04-{10+number:02d}')
        old=new
        if number==8:
            _,_,proof=carry.project(PROJECT,original['profile'],latest['source_sha256'])
            assert len(proof['lineage_steps'])==carry.MAX_CHAIN_EDGES==8
    with pytest.raises(carry.DateCarryProblem):carry.project(PROJECT,original['profile'],latest['source_sha256'])


@pytest.mark.parametrize('target',['fact_and_rows','row_only'])
@pytest.mark.parametrize('field,kind',[
    ('source_revision','float'), ('source_revision','bool'),
    ('persisted','int'), ('persisted','float'), ('persisted','true'),
])
def test_multi_edge_summary_json_kinds_cannot_be_normalized_away(site,target,field,kind):
    save_profile(site);two_hops(site)
    s=monitor.build(PROJECT,CUT)['schedule'];state=s['readiness'];profile=state['profile_source_carry']
    assert work._carry_consistent(s,state,profile)
    def corrupt(proof):
        if field=='source_revision':proof[field]=float(proof[field]) if kind=='float' else True
        else:proof[field]={'int':0,'float':0.0,'true':True}[kind]
    if target=='fact_and_rows':
        corrupt(state['fact_source_carry']);s['fact_source_carry']=copy.deepcopy(state['fact_source_carry'])
    for row in s['rows']:
        if row.get('gpr_fact_source_carry'):corrupt(row['gpr_fact_source_carry'])
    assert not work._carry_consistent(s,state,profile)


@pytest.mark.parametrize('hops,cut,owned,forged,expected',[
    (1, CUT, False, False, True),
    (2, CUT, False, False, True),
    (2, FIRST_DAY, False, False, False),
    (2, FIRST_DAY, False, True, False),
    (2, FIRST_DAY, True, False, True),
    (2, FIRST_DAY, True, True, False),
    (2, CUT, False, True, False),
])
def test_original_owner_reference_or_complete_fact_chain_is_required(site,hops,cut,owned,forged,expected):
    save_profile(site)
    if hops == 1:
        next_source(site,'F5','01.01.2031','02.01.2031',FIRST_DAY)
    else:
        two_hops(site)
    schedule=monitor.build(PROJECT,cut)['schedule'];state=schedule['readiness']
    profile=state['profile_source_carry'];fact=state['fact_source_carry']
    assert work._carry_consistent(schedule,state,profile)
    assert len(work._carry_steps(profile)) == hops
    assert len(work._carry_steps(fact)) == (1 if cut == FIRST_DAY else hops)
    if not owned:
        state.pop('profile_reference_source_sha256')
    if forged:
        # A valid nearest-ancestor suffix says nothing about an earlier root.
        false_root='f'*64
        profile['from_source_sha256']=profile['reference_source_sha256']=false_root
        profile['lineage_steps'][0]['from_source_sha256']=false_root
        assert work._carry_steps(profile) is not None
    assert work._carry_consistent(schedule,state,profile) is expected
    assert (work.build(schedule,cut)['state'] != 'unavailable') is expected
