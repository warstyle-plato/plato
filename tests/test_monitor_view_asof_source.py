"""Native full-view routes select RSS by the cut without rewriting history."""
import datetime as dt
import time

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
import pytest

import developaid_management_report_jobs as jobs
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import main as wrapper
from test_monitor_keeps_every_snapshot import _baseline_book, _rss_book

KEY = 'synthetic-monitor-asof-owner'
SESSION = 'synthetic-asof-session'
PROJECT = 'Synthetic historical Monitor'
OLD = '2026-09-12'
CUT = '2026-09-15'
FUTURE = '2026-09-19'


@pytest.fixture
def sources(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVELOPAID_ADMIN_KEY', KEY)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr(monitor, '_SNAPSHOT_DIR', tmp_path/'monitor')
    monitor.store_schedule(PROJECT, _baseline_book(), None, '2026-07-01')
    # Both versions report acts/payments BEFORE the selected cut. Filtering
    # payment dates alone cannot hide selection of the later rewritten file.
    for day, estimate, accepted, paid in ((OLD, 1000, 80, 25), (FUTURE, 9000, 900, 700)):
        monitor.store_estimate(PROJECT, _rss_book(estimate=estimate,
            acts=[('10.09.2026', accepted)], payments=[(dt.date(2026,9,10),paid)]), day)
    root = monitor._project_dir(PROJECT)
    return TestClient(wrapper.core.app), root


def request(client, *, background=False, cut=CUT, ticket='a'*32, key=KEY):
    return client.post('/monitor/view', json={'project':PROJECT, 'cut':cut, 'key':key,
        'session':SESSION, 'ticket':ticket, 'background':background})


def terminal(client, ticket='a'*32):
    deadline = time.monotonic()+10
    while time.monotonic()<deadline:
        response = client.post('/monitor/view/result', json={'ticket':ticket,'key':KEY,'session':SESSION})
        if response.status_code!=202:
            return response
        time.sleep(.01)
    pytest.fail('Synthetic historical full view did not finish')


@pytest.mark.parametrize('background', [False, True])
def test_full_view_uses_old_source_and_values_with_all_canonical_gpr_fields(sources, background):
    client, root = sources
    before = {p.name:p.read_bytes() for p in (root/'estimate').glob('*.xlsx')}
    expected = jsonable_encoder(monitor.build(PROJECT,CUT,upto=CUT))
    response = request(client,background=background)
    if background:
        assert response.status_code==202
        response = terminal(client)
    assert response.status_code==200, response.text
    view = response.json()['snapshot']
    assert view['source']['estimate']==OLD
    assert view['money']['estimate']==1000
    assert view['money']['accepted']==80
    assert view['money']['payment_fact']==25
    assert view['payments']['fact_total']==25
    assert view['dashboard']['funding']['source_dates']['rss']['data_date']==OLD
    assert view==expected
    quick = client.post('/monitor/gpr-view',json={'project':PROJECT,'cut':CUT,'key':KEY}).json()
    for field in ('physical_progress','completed_facts','corpus_gpr','readiness'):
        assert field in view['schedule'] and field in quick['schedule']
        assert view['schedule'][field]==quick['schedule'][field]
    assert view['dashboard']['schedule']['qualified_rnv']==quick['dashboard']['schedule']['qualified_rnv']
    assert {p.name:p.read_bytes() for p in (root/'estimate').glob('*.xlsx')}==before


@pytest.mark.parametrize('cut', [CUT, ' '+CUT+' ', CUT+'T12:34:56+00:00'])
def test_legacy_accepted_date_forms_bind_the_same_source(sources, cut):
    client, _ = sources
    response = request(client,cut=cut)
    assert response.status_code==200
    assert response.json()['snapshot']==jsonable_encoder(monitor.build(PROJECT,cut,upto=CUT))
    assert response.json()['snapshot']['source']['estimate']==OLD


def test_legacy_empty_cut_keeps_latest_source_fallback(sources):
    client, _ = sources
    response = request(client,cut='')
    assert response.status_code==200
    assert response.json()['snapshot']==jsonable_encoder(monitor.build(PROJECT,''))
    assert response.json()['snapshot']['source']['estimate']==FUTURE


def test_legacy_unparsed_cut_keeps_existing_downstream_validation(sources):
    client, _ = sources
    with pytest.raises(ValueError) as original:
        monitor.build(PROJECT,'not-a-date')
    with pytest.raises(ValueError) as route:
        request(client,cut='not-a-date')
    assert str(route.value)==str(original.value)


@pytest.mark.parametrize('cut', ['', ' '+CUT+' ', CUT+'T12:34:56+00:00', 'not-a-date'])
def test_async_canonical_cut_validation_is_unchanged(sources, cut):
    client, _ = sources
    assert request(client,background=True,cut=cut).status_code==400
    assert not (monitor._SNAPSHOT_DIR/'.view_jobs').exists()


@pytest.mark.parametrize('background', [False, True])
def test_future_only_file_is_never_read_or_used_as_known_money(sources, background):
    client, root = sources
    (root/'estimate'/f'{OLD}.xlsx').unlink()
    future = root/'estimate'/f'{FUTURE}.xlsx'
    future.write_bytes(b'Unparseable future synthetic source: must not be opened')
    response = request(client,background=background)
    if background:
        assert response.status_code==202
        response = terminal(client)
    assert response.status_code==200, response.text
    view = response.json()['snapshot']
    assert view['source']['estimate'] is None
    assert all(view['money'][field] is None for field in ('estimate','paid','accepted','payment_fact'))
    assert view['financial_state']['state']=='missing'
    assert view['schedule']['rows']  # Approved GPR remains readable.


def test_global_unbounded_builder_and_existing_tickets_are_not_reinterpreted(sources):
    client, _ = sources
    old_snapshot = jsonable_encoder(monitor.build(PROJECT,CUT))
    assert old_snapshot['source']['estimate']==FUTURE
    assert old_snapshot['money']['accepted']==900
    store = jobs.Store(monitor._SNAPSHOT_DIR/'.view_jobs')
    owner = jobs.owner_binding(KEY,SESSION,'admin')
    store.start(owner,'admin',{'project':PROJECT,'cut':CUT,'click':'a'*32},
        lambda:{'snapshot':old_snapshot},'a'*32,result_limit_bytes=jobs.MAX_EXTENDED_RESULT_BYTES,
        context=ledgers.snapshot_job_context(PROJECT))
    assert terminal(client).json()['snapshot']==old_snapshot
    before = store._meta('a'*32)
    assert request(client,background=True).json()['snapshot']==old_snapshot
    assert store._meta('a'*32)==before
    assert request(client,background=True,ticket='b'*32).status_code==202
    assert terminal(client,'b'*32).json()['snapshot']['source']['estimate']==OLD


@pytest.mark.parametrize('background', [False, True])
def test_current_admin_gate_stays_before_source_reading(sources, monkeypatch, background):
    client, _ = sources
    monkeypatch.setattr(monitor.actuals,'_sheet',lambda *a,**k:pytest.fail('Unauthorized source read'))
    assert request(client,background=background,key='wrong').status_code==403
    assert not (monitor._SNAPSHOT_DIR/'.view_jobs').exists()
