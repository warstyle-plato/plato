"""The project retains building size after nominal element normalization."""
import copy
import io

import pytest
from playwright.sync_api import expect
from pypdf import PdfReader

import developaid_schedule_elements as elements
import developaid_schedule_readiness as ready
from test_monitor_cumulative_controls import browser_page

DAY = '2026-11-13'


def buildings():
    rows, assignments = [], {}
    for obj, amount, progress in [('Large', 100_000_000, 1), ('Small', 1_000_000, 0)]:
        for element, _, fraction in elements.ELEMENTS:
            key = obj+':'+element
            rows.append(dict(id=key, name=key, object=obj, section=element,
                             primary=dict(value=progress, date=DAY, label='Synthetic dated statement')))
            assignments[key] = dict(element_id=element, share=None, weight=dict(
                basis='smr_cost', value=amount*fraction/100, unit='RUB',
                source_reference='Synthetic complete estimate', valuation_key='Same complete estimate v1',
                cost_basis='without_vat', position_keys=['estimate:'+key], full_scope=True))
    return rows, dict(id=elements.PROFILE_ID, overrides={},
                      objects={'Large':'residential', 'Small':'residential'}, assignments=assignments)


def model(rows, config):
    full = {row['id']:{key:value for key,value in row.items() if key!='primary'} for row in rows}
    profile = dict(full_scope_confirmed=True, remaining_source_sha256='a'*64,
                   effective_from=DAY, crosswalk=[dict(remaining_id=key,full_id=key) for key in full],
                   outside_completed_ids=[], included_ids=list(full), excluded_ids=[], weights=[],
                   basis='estimated_elements', scope_kind='construction', label='Synthetic profile',
                   source_reference='Synthetic source', element_profile=config)
    return ready.model({'works':{row['id']:{key:value for key,value in row.items() if key!='id'} for row in rows}},
                       cut=DAY, baseline_scope='full_schedule', source_sha256='a'*64,
                       profile=profile, full_rows=full)


def test_project_uses_comparable_full_plan_and_keeps_each_buildings_owner_shares():
    rows, config = buildings()
    state = model(rows, config)
    assert state['project']['progress'] == pytest.approx(100/101)
    assert state['project']['coverage'] == pytest.approx(100)
    assert not state['project']['partial']
    assert state['project_weight_basis'] == 'Полная плановая стоимость СМР'
    assert {r['name']:r['progress'] for r in state['corpora']} == {'Large':1,'Small':0}
    # Very different actual stage costs must not replace the approved25%frame
    # share inside one building, nor be added as an extra nominal stage weight.
    for row in rows:
        row['primary']['value'] = int(row['section']=='frame')
    config['assignments']['Large:frame']['weight']['value'] *= 30
    changed = model(rows, config)
    assert changed['project']['progress'] == pytest.approx(.25)
    assert all(r['progress']==pytest.approx(.25) for r in changed['corpora'])
    assert [value for _,_,value in elements.ELEMENTS] == [12,25,5,17,3,7,18,4,5,4]


def test_rescaling_a_building_changes_only_its_project_contribution():
    rows, config = buildings()
    before = model(rows, config)
    for key, value in config['assignments'].items():
        if key.startswith('Small:'):
            value['weight']['value'] *= 100
    after = model(rows, config)
    assert before['project']['progress'] == pytest.approx(100/101)
    assert after['project']['progress'] == pytest.approx(.5)
    assert before['corpora'] == after['corpora']
    assert before['matrix'] == after['matrix']


@pytest.mark.parametrize('parts',[1,3,20])
def test_splitting_a_work_preserves_both_building_and_project_contribution(parts):
    rows, config = buildings()
    expected = model(rows, config)
    source = next(row for row in rows if row['id']=='Small:frame')
    rows.remove(source)
    assignment = config['assignments'].pop(source['id'])
    for i in range(parts):
        child=copy.deepcopy(source);child['id']+=':'+str(i);rows.append(child)
        value=copy.deepcopy(assignment);value['weight']['value']/=parts
        value['weight']['position_keys']=['estimate:'+child['id']]
        config['assignments'][child['id']]=value
    actual = model(rows, config)
    assert actual['project']['progress'] == pytest.approx(expected['project']['progress'])
    assert actual['project']['coverage'] == pytest.approx(expected['project']['coverage'])
    assert [r['progress'] for r in actual['corpora']] == [r['progress'] for r in expected['corpora']]


@pytest.mark.parametrize('mutation',[
    lambda cfg:cfg['assignments']['Small:frame'].pop('weight'),
    lambda cfg:cfg['assignments']['Small:frame']['weight'].update(value=None),
    lambda cfg:cfg['assignments']['Small:frame']['weight'].update(full_scope=False),
    lambda cfg:[node['weight'].update(valuation_key='Other full estimate') for key,node in cfg['assignments'].items() if key.startswith('Small:')],
    lambda cfg:[node['weight'].update(cost_basis='with_vat') for key,node in cfg['assignments'].items() if key.startswith('Small:')],
    lambda cfg:cfg['assignments']['Small:frame']['weight'].update(position_keys=['estimate:Large:frame']),
])
def test_missing_incompatible_or_duplicated_building_plan_never_becomes_equal_size(mutation):
    rows, config = buildings();mutation(config)
    state=model(rows,config)
    assert state['project']['progress'] is None
    assert state['project']['coverage'] is None
    assert state['project']['partial']
    assert 'общий вес корпусов' in state['project']['reason']
    assert state['corpora'][0]['progress'] == 1 or 'повторно' in state['corpora'][0]['reason']
    assert state['project']['eligible_readings'] == 20


def test_explicit_nominal_shares_have_no_implicit_relative_building_size():
    rows, config=buildings()
    for assignment in config['assignments'].values():
        assignment.pop('weight')
    state=model(rows,config)
    assert state['project']['progress'] is None and state['project']['coverage'] is None
    assert [row['progress'] for row in state['corpora']] == [1,0]
    assert all(cell['progress'] is not None for stage in state['matrix'] for cell in stage['cells'])


def test_missing_positive_element_does_not_establish_a_full_building_scale():
    rows,config=buildings()
    rows=[row for row in rows if row['id']!='Small:engineering']
    config['assignments'].pop('Small:engineering')
    state=model(rows,config)
    assert state['project']['progress'] is None and state['project']['coverage'] is None
    assert 'не содержит всех учитываемых разделов' in state['project']['reason']
    assert [row['progress'] for row in state['corpora']] == [1,0]
    assert state['corpora'][1]['partial']


def test_physical_project_scale_requires_one_comparable_operation_and_unit():
    rows,config=buildings()
    for node in config['assignments'].values():
        node['weight'].update(basis='planned_quantity',unit='м3',valuation_key='Same homogeneous operation',cost_basis='')
    assert model(rows,config)['project']['progress'] == pytest.approx(100/101)
    for key,node in config['assignments'].items():
        if key.startswith('Small:'):
            node['weight']['unit']='м2'
    state=model(rows,config)
    assert state['project']['progress'] is None and 'одинаковых единицах' in state['project']['reason']
    assert [row['progress'] for row in state['corpora']] == [1,0]


def test_missing_reading_retains_correct_cost_coverage_without_reweighting_a_building():
    rows, config=buildings()
    next(row for row in rows if row['id']=='Small:frame')['primary']['value']=None
    state=model(rows,config)
    assert state['project']['partial']
    assert state['project']['known_readings']==19
    assert state['project']['coverage']==pytest.approx(100*(1-.25/101))
    assert state['project']['progress']==pytest.approx(100/100.75)


@pytest.mark.parametrize('width',[390,1440])
def test_actual_report_html_and_pdf_preserve_project_scale_and_unknown_reason(width):
    import developaid_management_report as report
    rows,config=buildings();state=model(rows,config)
    actual=lambda s:report._gantt_html({'gantt':{'readiness':s,'state':'error','reason':'Synthetic empty timeline'},'end':DAY})
    with browser_page(width) as (page,_,errors):
        page.set_content(actual(state))
        expect(page.locator('.readiness-project-value')).to_have_text('99,0%')
        expect(page.locator('.readiness-summary')).to_contain_text('Доли корпусов в общей готовности определены')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(page.pdf())).pages)
        assert '99,0%' in text and 'Полная плановая стоимость СМР' in text
        config['assignments']['Small:frame']['weight']['value']=None
        missing=model(rows,config);page.set_content(actual(missing))
        expect(page.locator('.readiness-project-value')).to_have_count(0)
        expect(page.locator('.readiness-gap')).to_contain_text('Не определён общий вес корпусов')
        text=''.join(p.extract_text() for p in PdfReader(io.BytesIO(page.pdf())).pages)
        assert 'Не определён общий вес корпусов' in text
        assert '99,0%' not in text
        assert not errors
