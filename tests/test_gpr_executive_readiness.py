"""Real saved synthetic sources reach Monitor, executive HTML and native PDF."""
import copy
import datetime as dt
import io
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

import developaid_management_report as report
import developaid_monitor as monitor
import developaid_schedule_elements as elements
import developaid_schedule_readiness as ready
import developaid_schedule_versions as versions
from developaid_gpr_summary import gpr_summary
from browser import chromium_or_skip, serve
from test_monitor_management_gantt import _gpr_book

PROJECT = 'Учебная готовность для руководства'
CUT = '2034-04-16'
FACT = '2034-04-11'
KEY = 'offline-readiness-executive-key'


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monkeypatch.setenv('DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2034, 4, 14, 12, tzinfo=dt.timezone.utc))
    import developaid_monitor_page  # noqa: F401 — install the real Monitor projection
    rows = [(i, name, progress, dt.date(2034, 1, 1), finish, 'В работе', '2.2')
            for i, name, progress, finish in [
                (1, 'Учебная подземная часть', 0, dt.date(2034, 8, 30)),
                (2, 'Учебный каркас', .6, dt.date(2034, 9, 30)),
                (3, 'Учебная работа без веса', .3, dt.date(2034, 10, 30)),
                (4, 'Работа вне выбранного состава', 1, dt.date(2038, 12, 31))]]
    raw = _gpr_book(rows)
    monitor.store_schedule(PROJECT, raw, None, '2034-04-03')
    monitor.store_schedule_fact(PROJECT, raw, FACT)
    source = monitor._working_baseline_state(PROJECT)
    cfg = dict(label='Учебная оценка текущего состава', scope_kind=ready.CURRENT_ESTIMATE,
        scope_note='Учебный выбранный состав', basis='estimated_elements',
        source_reference='Учебные экспертные веса', building_type='Учебный жилой корпус',
        full_source_sha256=source['source_sha256'], effective_from='2034-04-14',
        full_scope_confirmed=False, included_ids=['1', '2', '3'], excluded_ids=['4'],
        outside_completed_ids=[], weights=[],
        element_profile=dict(id=elements.PROFILE_ID, overrides={},
            objects={'Корпус 1': 'residential'},
            assignments={'1': dict(element_id='underground', share=100),
                         '2': dict(element_id='frame', share=100)}))
    opts = dict(expected_source_sha256=source['source_sha256'],
                expected_source_revision=source['revision'], expected_revision=0)
    preview = ready.preview(PROJECT, cfg, **opts)
    ready.save(PROJECT, cfg, **opts, expected_profile_sha256=preview['profile_sha256'])
    return cfg, opts, preview


def test_saved_source_uses_one_summary_in_monitor_tiles_and_findings(saved):
    view = monitor.build(PROJECT, CUT)
    state = view['schedule']['readiness']
    before = copy.deepcopy(state)
    summary = gpr_summary(state, CUT)
    built = report.build(PROJECT, 'week', CUT)
    assert summary['progress'] == pytest.approx((25*.6)/37)
    assert summary['progress'] != pytest.approx(built['physical']['fact'])
    assert summary['total'] == 3 and summary['known_readings'] == 2
    assert summary['coverage'] == 37 and summary['partial'] and summary['estimated']
    assert summary['fact_as_of'] == FACT
    assert summary['profile_sha256'] == saved[2]['profile_sha256']
    assert built['gantt']['readiness'] == state
    tiles = report.tiles(built)
    assert tiles[0]['value'] == summary['value']
    assert tiles[1]['value'] == report._day(summary['finish'])
    assert summary['forecast_text'] in tiles[1]['note']
    assert summary['as_of_text'] in tiles[0]['note']
    findings = {r['topic']: r['text'] for r in built['findings']}
    assert findings['Стройка'] == summary['readiness_text']
    assert summary['forecast_text'] in findings['Срок']
    html = ready.render(state)
    assert summary['value'] in html and summary['forecast_text'] in html
    assert state == before
    assert gpr_summary(state, '2034-04-15') is None


@pytest.mark.parametrize('progress', [0, None])
def test_zero_and_unknown_stay_distinct_and_never_fall_back_to_physical(saved, progress):
    state = monitor.build(PROJECT, CUT)['schedule']['readiness']
    state['project']['progress'] = progress
    state['project']['coverage'] = None
    built = dict(end=CUT, kind='week', gantt=dict(readiness=state),
                 physical=dict(state='ok', fact=.99, plan=.5, lag=.49))
    tile = report.tiles(built)[0]
    assert tile['value'] == ('0,0%' if progress == 0 else 'нет данных')
    assert 'Покрытие веса:' not in tile['note']
    assert tile['value'] != '99,0%'


def test_future_profile_is_not_the_selected_profile_for_an_earlier_report(saved, monkeypatch):
    cfg, opts, previous = saved
    cfg = copy.deepcopy(cfg)
    cfg['effective_from'] = '2034-04-18'
    cfg['element_profile']['overrides'] = {'frame': 50}
    monkeypatch.setattr(versions, '_now', lambda: dt.datetime(2034, 4, 17, 12, tzinfo=dt.timezone.utc))
    opts = dict(opts, expected_revision=1)
    future = ready.preview(PROJECT, cfg, **opts)
    ready.save(PROJECT, cfg, **opts, expected_profile_sha256=future['profile_sha256'])
    old = report.build(PROJECT, 'week', CUT)['gantt']['readiness']
    summary = gpr_summary(old, CUT)
    assert old['latest_profile_sha256'] == future['profile_sha256']
    assert summary['profile_revision'] == 1 and old['latest_profile_revision'] == 2
    assert summary['profile_sha256'] == previous['profile_sha256']
    assert summary['profile_effective_from'] == '2034-04-14'
    assert summary['profile_sha256'] != old['latest_profile_sha256']
    assert gpr_summary(report.build(PROJECT, 'week', '2034-04-13')['gantt']['readiness'], '2034-04-13')['progress'] is None
    assert gpr_summary(report.build(PROJECT, 'week', '2034-04-18')['gantt']['readiness'], '2034-04-18')['profile_sha256'] == future['profile_sha256']


def test_wrong_forecast_source_cannot_supply_the_summary_date(saved):
    state = monitor.build(PROJECT, CUT)['schedule']['readiness']
    state['project']['forecast']['source_sha256'] = 'f'*64
    summary = gpr_summary(state, CUT)
    assert summary['finish'] is None and summary['plan_finish'] is None
    assert summary['progress'] is not None


def test_real_report_page_tiles_and_downloaded_pdf_use_readiness(saved, monkeypatch):
    import main_legacy as core
    monkeypatch.setattr(core, '_require_web_access', lambda *_a, **_k: None)
    summary = gpr_summary(monitor.build(PROJECT, CUT)['schedule']['readiness'], CUT)
    with serve(core.app, 18862) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()), args=['--no-sandbox'])
        try:
            page = browser.new_page(accept_downloads=True)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('plato_projects_key','{KEY}')")
            page.goto(base+'/report', wait_until='domcontentloaded')
            page.wait_for_selector(f'#project option[value="{PROJECT}"]', state='attached')
            page.select_option('#project', PROJECT)
            page.fill('#cut', CUT)
            page.click('#reportBtn')
            expect(page.locator('#reportBox .report-gpr-compact')).to_be_visible(timeout=90000)
            for width in (390, 1440):
                page.set_viewport_size(dict(width=width, height=1000))
                host=page.locator('#reportBox .report-gpr-compact')
                expect(host.locator('[data-gpr-block]')).to_have_count(3)
                expect(host.locator('[data-gpr-block=forecast]')).to_contain_text(summary['value'])
                expect(host.locator('[data-gpr-block=forecast]')).to_contain_text('11.04.2034')
                dates=host.locator('[data-gpr-block]').evaluate_all('es=>es.map(e=>e.dataset.projectForecast)')
                assert dates==[dates[0]]*3
                assert host.locator('details,.readiness-summary,.executive-schedule').count()==0
                assert page.locator('#reportBox .gpr-broader-physical').count()==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=f'/tmp/gpr-executive-readiness-{width}.png', full_page=True)
            with page.expect_download(timeout=90000) as download:
                page.click('#reportPdfBtn')
            raw = Path(download.value.path()).read_bytes()
            Path('/tmp/gpr-executive-readiness.pdf').write_bytes(raw)
            reader = PdfReader(io.BytesIO(raw))
            all_text = ' '.join(' '.join((p.extract_text() or '').split()) for p in reader.pages)
            assert summary['value'] in all_text and '11.04.2034' in all_text
            assert 'Прогноз учтённых работ'in all_text and 'Матрица готовности'in all_text and 'Гант по корпусам'in all_text
            assert '78,7%'not in all_text and 'по плановой длительности'not in all_text
            assert 'Сроки по строительным работам текущего ГПР'not in all_text
            assert not errors
        finally:
            browser.close()
