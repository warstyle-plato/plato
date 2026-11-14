"""Explicit building scales and source-preserving presentation groups."""
import copy

import pytest
from playwright.sync_api import expect

import developaid_schedule_elements as elements
import developaid_schedule_groups as groups
import developaid_schedule_plan_scenario as scenario
import developaid_schedule_readiness as ready
from test_schedule_readiness_elements import reading, DAY
from test_gpr_readable_matrix import matrix_view, serve_view, settled
from test_monitor_cumulative_controls import browser_page


def weighted_rows():
    rows = [dict(reading('a', .2, obj='Корпус 1'), section='Конструктив'),
            dict(reading('b', .8, obj='Корпус 2'), section='Конструктив')]
    config = dict(id=elements.PROFILE_ID, overrides={},
                  objects={'Корпус 1':'residential', 'Корпус 2':'residential'},
                  assignments={r['id']:dict(element_id='frame', share=100) for r in rows})
    return rows, config


def test_explicit_corpus_scales_change_the_project_but_not_the_buildings():
    rows, config = weighted_rows()
    original = copy.deepcopy(rows)
    assert elements.projection(rows, config, cut=DAY, confirmed=True)['project']['progress'] is None
    config['corpus_shares'] = {'Корпус 1':20, 'Корпус 2':80}
    elements.validate(config, {r['id']:r for r in rows})
    result = elements.projection(rows, config, cut=DAY, confirmed=True)
    assert result['project']['progress'] == pytest.approx(.68)
    assert result['project']['coverage'] == 25
    assert result['project']['partial'] and result['project_weight_estimated']
    assert [c['progress'] for c in result['corpora']] == [.2, .8]
    config['corpus_shares'] = {'Корпус 1':80, 'Корпус 2':20}
    assert elements.projection(rows, config, cut=DAY, confirmed=True)['project']['progress'] == pytest.approx(.32)
    assert rows == original


def test_project_scales_apply_to_work_weights_before_normalizing_partial_coverage():
    rows, config = weighted_rows()
    rows.append(dict(reading('c', 1, obj='Корпус 2'), section='Кладка'))
    config['assignments']['c']=dict(element_id='masonry', share=100)
    config['corpus_shares']={'Корпус 1':20,'Корпус 2':80}
    result=elements.projection(rows,config,cut=DAY,confirmed=True)
    assert result['project']['progress']==pytest.approx((.2*25*.2+.8*25*.8+1*5*.8)/(25*.2+30*.8))
    assert result['project']['progress']!=pytest.approx(sum(c['progress']*s for c,s in zip(result['corpora'],(.2,.8))))


@pytest.mark.parametrize('shares', [None, [], {'Корпус 1':100}, {'Корпус 1':50,'Корпус 2':49},
    {'Корпус 1':True,'Корпус 2':99}, {'Корпус 1':0,'Корпус 2':100},
    {'Корпус 1':float('nan'),'Корпус 2':50}, {'Корпус 1':50,'Паркинг':50}])
def test_invalid_or_incomplete_scales_are_rejected(shares):
    rows, config = weighted_rows(); config['corpus_shares'] = shares
    with pytest.raises(ValueError, match='доли'):
        elements.validate(config, {r['id']:r for r in rows})


def test_display_groups_preserve_source_and_do_not_assign_weights():
    rows = [dict(id=str(i), section=stage, name='Работа', construction_work=False) for i,stage in enumerate([
        'Этап 1. Разработка проекта стадии "П"', 'Этап 2. Разработка проекта стадии "Р"',
        'Этап 3. АГР', 'Этап 4. Экспертиза', 'Этап 5. Сопроводительная и разрешительная документация'])]
    rows += [dict(id='land',section='Наружные сети',name='Благоустройство — озеленение',construction_work=True),
             dict(id='design',section='Иные работы',name='Проект благоустройства',construction_work=False)]
    before = copy.deepcopy(rows); meta = groups.metadata(rows)
    assert [meta['by_id'][str(i)] for i in range(5)] == ['ПИР']*5
    assert meta['by_id']['land'] == 'Благоустройство'
    assert meta['by_id']['design'] == 'Иные работы'
    assert rows == before


@pytest.mark.parametrize('width', [390, 1440])
def test_native_page_groups_pir_and_displays_totals_and_dates_with_closed_work_lists(monkeypatch, width):
    view = matrix_view(7)
    tasks = view['schedule']['management'][0]['children'][0]['children'][0]['children']
    sections = ['Этап 1. Разработка проекта стадии "П"','Этап 2. Разработка проекта стадии "Р"',
                'Этап 3. АГР','Этап 4. Экспертиза','Этап 5. Сопроводительная и разрешительная документация',
                'Конструктив','Наружные сети']
    for i, task in enumerate(tasks):
        task.update(section=sections[i%7], construction_work=i%7>=5)
        if i%7==6: task['name']='Благоустройство — озеленение'
        task['plan_pace_scenario'] = dict(finish='2027-02-03',complete=False,source_date='2026-11-06')
    view['schedule']['display_groups'] = groups.metadata(tasks)
    rows, config = weighted_rows()
    config['corpus_shares']={'Корпус 1':20,'Корпус 2':80}
    for row in rows:
        row['plan_pace_scenario']=dict(finish='2027-02-03',source_date='2026-11-06')
    state = ready.model({'works':{r['id']:r for r in rows}},cut=DAY,baseline_scope='remaining_work',source_sha256='a'*64)
    state.update(elements.projection(rows,config,cut=DAY,confirmed=True))
    scenario.decorate_readiness(state, rows)
    view['schedule']['readiness_html']=ready.render(state)
    serve_view(monkeypatch,view)
    with browser_page(width) as (page,_,errors):
        settled(page,view)
        stages=page.locator('#gprFactMatrix .gpr-matrix-stage')
        expect(stages).to_have_count(3)
        assert stages.evaluate_all('(xs)=>xs.map(x=>x.dataset.stage)')==['ПИР','Конструктив','Благоустройство']
        expect(stages.first.locator('.gpr-source-stage')).to_have_count(5)
        expect(stages.first.locator(':scope > summary')).to_contain_text('При плановом темпе: 03.02.2027')
        page.locator('#gprMatrixExpand').click()
        expect(page.locator('#gprFactMatrix [data-work-id]:visible')).to_have_count(len(tasks))
        assert page.locator('#gprFactMatrix [data-work-id]').evaluate_all('(xs)=>xs.map(x=>x.dataset.workId).sort()')==sorted(t['id'] for t in tasks)
        for box in stages.all(): box.evaluate('(x)=>x.open=false')
        total=page.locator('#gprMatrix .readiness-total')
        expect(total.locator('td strong')).to_have_text(['20,0%','80,0%'])
        expect(total.locator('.readiness-cell-forecast')).to_have_text(['03.02.2027']*2)
        expect(page.locator('.readiness-project-total')).to_contain_text('68,0%')
        expect(page.locator('.readiness-project-total .readiness-cell-forecast')).to_be_visible()
        expect(page.locator('.readiness-corpus-assumption')).to_contain_text('ПИР и паркинг в неё не включены')
        expect(page.locator('.readiness-project-coverage')).to_be_visible()
        expect(page.locator('.readiness-project-coverage')).to_contain_text('25,0%')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
