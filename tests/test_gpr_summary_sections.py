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
from gpr_view_fixtures import projected_readiness, readiness_view


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
        task.update(section=sections[i%7], construction_work=i%7>=5, forecast_known=False)
        if i%7==6: task['name']='Благоустройство — озеленение'
        task['plan_pace_scenario'] = dict(finish='2027-02-03',complete=False,source_date='2026-11-06')
    view['schedule']['display_groups'] = groups.metadata(tasks)
    # The weighted selected works are leaves of this exact source roster.
    selected=[next(task for task in tasks if task['object']==obj and task['construction_work'])
              for obj in ['Корпус 1','Корпус 2']]
    for i,task in enumerate(selected):
        reading_value=[.2,.8][i]
        task.update(actual_progress=reading_value,
            primary=dict(value=reading_value,date=DAY,label='Учебное показание'),
            plan_start='2026-11-01',plan_finish=['2027-01-12','2027-01-20'][i])
    config=dict(id=elements.PROFILE_ID,overrides={},
        objects={'Корпус 1':'residential','Корпус 2':'residential'},
        assignments={task['id']:dict(element_id='frame',share=100) for task in selected},
        corpus_shares={'Корпус 1':20,'Корпус 2':80})
    state=projected_readiness(tasks,config,DAY,included_ids=[task['id'] for task in selected])
    view=readiness_view(tasks,state,milestone=dict(plan_date='2027-09-30',plan_label='План РНВ владельца'))
    serve_view(monkeypatch,view)
    with browser_page(width) as (page,_,errors):
        settled(page,view)
        expect(page.locator('.readiness-milestone-plan')).to_be_visible()
        expect(page.locator('.readiness-milestone-plan')).to_have_text('План РНВ владельца: 30.09.2027')
        headline=page.locator('.canonical-work-forecast')
        expect(headline.locator('strong')).to_have_text('03.02.2027')
        expect(headline).to_contain_text('План того же учтённого состава: 20.01.2027')
        expect(page.locator('.readiness-project-plan,.readiness-project-forecast')).to_have_count(0)
        stages=page.locator('#gprFactMatrix .gpr-matrix-stage')
        expect(stages).to_have_count(3)
        assert stages.evaluate_all('(xs)=>xs.map(x=>x.dataset.stage)')==['ПИР','Конструктив','Благоустройство']
        expect(stages.first.locator('.gpr-source-stage')).to_have_count(5)
        expect(stages.first.locator(':scope > summary')).to_contain_text('Вне общей оценки')
        expect(stages.first.locator(':scope > summary')).not_to_contain_text('03.02.2027')
        page.locator('#gprMatrixExpand').click()
        expect(page.locator('#gprFactMatrix [data-work-id]:visible')).to_have_count(len(tasks))
        assert page.locator('#gprFactMatrix [data-work-id]').evaluate_all('(xs)=>xs.map(x=>x.dataset.workId).sort()')==sorted(t['id'] for t in tasks)
        for box in stages.all(): box.evaluate('(x)=>x.open=false')
        total=page.locator('#gprMatrix .readiness-total')
        expect(total.locator('td strong')).to_have_text(['20,0%','80,0%'])
        expect(total.locator('.readiness-cell-forecast')).to_have_text(['03.02.2027']*2)
        expect(total.locator('.readiness-cell-plan')).to_have_text(['План: 12.01.2027','План: 20.01.2027'])
        expect(total.locator('.readiness-forecast-label')).to_have_text(['Оценка']*2)
        expect(total.locator('.readiness-forecast-basis')).to_have_text(['Плановый темп']*2)
        for label in total.locator('.readiness-forecast-label').all():
            expect(label).to_be_visible()
        expect(page.locator('.readiness-project-total')).to_contain_text('68,0%')
        expect(page.locator('.readiness-project-total .readiness-cell-forecast')).to_be_visible()
        expect(page.locator('.readiness-project-total .readiness-cell-plan')).to_have_text('План: 20.01.2027')
        expect(page.locator('.readiness-project-total .readiness-forecast-label')).to_have_text('Оценка')
        expect(page.locator('.readiness-project-total .readiness-forecast-label')).to_be_visible()
        expect(page.locator('.readiness-corpus-assumption')).to_contain_text('ПИР и паркинг в неё не включены')
        expect(page.locator('.readiness-project-coverage')).to_be_visible()
        expect(page.locator('.readiness-project-coverage')).to_contain_text('25,0%')
        reasons=page.locator('.readiness-project-reasons')
        expect(reasons.locator('summary')).to_be_visible()
        expect(reasons.locator('p')).to_be_hidden()
        assert page.locator('#gprMatrix table').bounding_box()['height']<500
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not errors
