"""A coherent Monitor read parses source bytes once without caching decisions."""
import copy
import datetime as dt

import pytest

import developaid_gpr_corpus as corpus
import developaid_monitor as monitor
import developaid_monitor_ledgers as ledgers
import developaid_schedule_gpr_physical as gpr
import developaid_schedule_physical as physical
from test_gpr_corpus_preview import book
from test_schedule_physical import snapshot, network, config


def count_workbooks(monkeypatch):
    calls = []
    original = ledgers._read_workbook

    def read(*args, **kwargs):
        calls.append(None)
        return original(*args, **kwargs)

    monkeypatch.setattr(ledgers, '_read_workbook', read)
    return calls


def test_nested_consumers_share_exact_bytes_but_not_mutable_results(monkeypatch):
    data = book()
    expected = corpus.read(data)
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def nested():
        return corpus.read(data)

    @monitor.approved_schedule_read
    def read():
        first = corpus.read(data)
        first['packages'][0]['scopes'][0]['source_cells']['progress'] = 'corrupted'
        first['packages'].clear()
        assert nested() == expected
        return corpus.read(data)

    assert read() == expected
    assert len(calls) == 1
    # A different request must revalidate/reparse even unchanged source bytes.
    assert read() == expected
    assert len(calls) == 2


def test_different_bytes_in_the_same_read_are_not_a_cache_hit(monkeypatch):
    first, second = book(name='Один источник'), book(name='Другой источник')
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def read():
        a, b = corpus.read(first), corpus.read(second)
        assert a['sha256'] != b['sha256']
        assert a['packages'][0]['name'] != b['packages'][0]['name']
        assert corpus.read(first) == a

    read()
    assert len(calls) == 2


def test_standalone_reads_do_not_keep_a_process_cache(monkeypatch):
    data = book()
    calls = count_workbooks(monkeypatch)
    assert corpus.read(data) == corpus.read(data)
    assert len(calls) == 2


def test_exception_discards_the_whole_read_context(monkeypatch):
    data = book()
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def interrupted():
        corpus.read(data)
        raise RuntimeError('interrupted consumer')

    with pytest.raises(RuntimeError, match='interrupted'):
        interrupted()
    assert monitor._APPROVED_SCHEDULE_READ.get() is None
    assert corpus.read(data)['packages']
    assert len(calls) == 2


def test_same_source_bytes_keep_distinct_project_dates_and_historical_facts(tmp_path, monkeypatch):
    import hashlib
    import developaid_schedule_gpr_forecast as forecast
    data = book(bad_date='30.06.2027')
    path = tmp_path / 'source.xlsx'
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(monitor, '_working_baseline_state', lambda project, cut='': {
        'path': path, 'source_sha256': digest, 'baseline_scope': 'remaining_work',
        'taken_at': '2026-11-06' if project == 'Первый' else '2026-11-10'})
    monkeypatch.setattr(monitor, '_project_dir', lambda project: tmp_path / project)
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def read():
        first = corpus.for_view('Первый', '2026-11-08', baseline_sha256=digest)
        second = corpus.for_view('Второй', '2026-11-08', baseline_sha256=digest)
        assert first['taken_at'] == '2026-11-06'
        assert second['taken_at'] == '2026-11-10'
        assert forecast.history('Первый', dt.date(2026, 11, 8))
        assert forecast.history('Второй', dt.date(2026, 11, 8)) == {}

    read()
    assert len(calls) == 1


def test_failed_read_is_not_replaced_with_a_cached_unknown(monkeypatch):
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def read():
        for _ in range(2):
            with pytest.raises(ValueError):
                corpus.read(b'not a workbook')

    read()
    assert len(calls) == 2


@pytest.mark.parametrize('limit', ['entries', 'bytes'])
def test_read_cache_stays_bounded_and_does_not_change_results(monkeypatch, limit):
    first, second = book(name='Первый'), book(name='Второй')
    expected = corpus.read(second)
    if limit == 'entries':
        monkeypatch.setattr(corpus, '_READ_CACHE_ENTRIES', 1)
    else:
        monkeypatch.setattr(corpus, '_READ_CACHE_BYTES', 1)
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def read():
        corpus.read(first)
        assert corpus.read(second) == expected
        assert corpus.read(second) == expected

    read()
    assert len(calls) == 3


def test_unrecognized_source_can_be_cached_only_within_this_read(monkeypatch):
    from test_monitor_keeps_every_snapshot import _rss_book
    data = _rss_book()
    calls = count_workbooks(monkeypatch)

    @monitor.approved_schedule_read
    def read():
        assert corpus.read(data) is None
        assert corpus.read(data) is None

    read()
    assert len(calls) == 1
    assert corpus.read(data) is None
    assert len(calls) == 2


def test_trend_keeps_canonical_build_and_never_reads_a_future_snapshot(monkeypatch):
    monkeypatch.setattr(monitor, 'snapshots', lambda project: {
        'estimate': ['2026-11-01', '2026-11-05', '2026-11-09']})
    data = book()
    calls, built = count_workbooks(monkeypatch), []

    def build(project, cut, *, upto):
        built.append((project, cut, upto))
        assert corpus.read(data)['packages']
        number = int(cut[-2:])
        return {'money': {'paid': number, 'accepted': number+1, 'payment_fact': number+2},
                'schedule': {'risks': number+3, 'forecast_end': '2027-09-30'}}

    monkeypatch.setattr(monitor, 'build', build)
    points = monitor.trend('Профиль', '2026-11-06')
    assert built == [('Профиль', day, day) for day in ['2026-11-01', '2026-11-05']]
    assert [point['paid'] for point in points] == [1, 5]
    assert [point['payment_fact'] for point in points] == [3, 7]
    assert [point['risks'] for point in points] == [4, 8]
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['pm', 'gpr'])
def test_duplicate_evidence_is_validated_once_for_all_components(monkeypatch, kind):
    source = snapshot()
    for row in (9, 10):
        ledger = copy.deepcopy(source['ledgers'][0])
        ledger['items'][0]['source']['row'] = row
        source['ledgers'].append(ledger)
    configuration = config()
    configuration['components'].append(dict(configuration['components'][0], component_id='Другой компонент'))
    pm = network()
    if kind == 'gpr':
        pm = {'tasks': {key: {'task_id': key, 'name': value.get('name', key)}
                        for key, value in pm['tasks'].items()}}
    evaluate = physical.evaluate if kind == 'pm' else gpr.evaluate
    expected = evaluate(pm, source, copy.deepcopy(configuration), '2026-11-06')
    original, calls = ledgers.verified_duplicate_sources, []
    size = len(physical._items(source))

    def checked(items):
        if len(items) == size:
            calls.append(None)
        return original(items)

    monkeypatch.setattr(ledgers, 'verified_duplicate_sources', checked)
    assert evaluate(pm, source, configuration, '2026-11-06') == expected
    assert len(calls) == 1


def test_an_explicit_empty_duplicate_result_is_not_recomputed(monkeypatch):
    source = snapshot()
    items = physical._items(source)
    component = config()['components'][0]
    expected = physical._component(component, items, dt.date(2026, 11, 6))
    monkeypatch.setattr(ledgers, 'verified_duplicate_sources', lambda *args: pytest.fail('repeated full proof'))
    assert physical._component(component, items, dt.date(2026, 11, 6), _duplicates={}) == expected


@pytest.mark.parametrize('kind', ['pm', 'gpr'])
def test_evaluate_revalidates_copy_proof_after_source_changes(kind):
    from test_cumulative_proven_duplicates import snapshot as duplicate_snapshot
    source = duplicate_snapshot()
    configuration = config(['0:2'])
    pm = network()
    if kind == 'gpr':
        pm = {'tasks': {key: {'task_id': key, 'name': value.get('name', key)}
                        for key, value in pm['tasks'].items()}}
    evaluate = physical.evaluate if kind == 'pm' else gpr.evaluate

    def component():
        result = evaluate(pm, source, configuration, '2026-11-06')
        return next(row for row in result['tasks'] if row['task_id'] == '1')['components'][0]

    assert component()['excluded_duplicate_item_ids'] == ['0:2']
    source['ledgers'][0]['items'][0]['completed_quantity'] = 8
    source['ledgers'][0]['items'][2]['completed_quantity'] = 8
    assert not component().get('excluded_duplicate_item_ids')
