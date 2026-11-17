from auction_search.krt_reconciliation import expected_lots, reconcile
from auction_search.adapters.roseltorg import RoseltorgAdapter
from auction_search.models import AuctionLot, AuctionSource, LotKind, SourceKind


def test_unique_live_saved_lots_and_concrete_reasons():
    known = {'a': {'lots': [{'url': 'u1', 'deadline': '30.11.2099 15:00'},
                           {'url': 'old', 'deadline': '01.01.20 15:00'}]},
             'b': {'lots': [{'url': 'u1', 'deadline': '30.11.2099 15:00'}]},
             'c': {'lots': [{'url': 'u2', 'deadline': '30.11.2099 15:00'}]},
             'd': {'lots': [{'url': 'u3', 'deadline': '30.11.2099 15:00'}]}}
    expected = expected_lots(known)
    assert len(expected) == 3
    assert expected[0]['slugs'] == ['a', 'b']
    result = reconcile(expected, [{'source': {'lot_url': 'u1'}, 'main_selection': True}],
                       {'u2': {'state': 'excluded', 'reason': 'статус «Отменен»'},
                        'u3': {'state': 'unread', 'reason': 'HTTP 429'}})
    assert result['included'] == 1
    assert [r['state'] for r in result['rows']] == ['included', 'excluded', 'unread']
    assert [r['reason'] for r in result['rows']][1:] == ['статус «Отменен»', 'HTTP 429']


def test_quality_rejection_is_not_a_download_error():
    result = reconcile([{'url': 'u', 'slugs': ['a']}],
                       [{'source': {'lot_url': 'u'}, 'main_selection': False,
                         'quality': {'reasons': ['не опубликована площадь территории']}}], {})
    assert result['rows'][0]['state'] == 'excluded'
    assert result['rows'][0]['reason'] == 'не опубликована площадь территории'


def test_known_cards_are_read_before_catalogue_and_failures_are_named(monkeypatch):
    adapter = RoseltorgAdapter()
    base = 'https://www.roseltorg.ru/procedure/'
    urls = [base + str(i) + '/1' for i in range(100, 104)]
    adapter.known_krt_lots = [{'url': u} for u in urls] + [{'url': 'https://evil.test/1'}]
    events = []

    def fetch(url, **kw):
        events.append(url)
        if url == urls[2]:
            raise RuntimeError('HTTP 429')
        return AuctionLot(source=AuctionSource(SourceKind.ROSELTORG, url, url, 'now'),
                          lot_kind=LotKind.KRT, title='КРТ города Москвы',
                          application_deadline='30.11.2099 15:00',
                          status='Отменен' if url == urls[1] else 'Прием заявок',
                          raw={'lot_region_code': '77'})

    monkeypatch.setattr(adapter, 'fetch_lot', fetch)

    def empty_catalogue(*args, **kw):
        assert set(urls).issubset(events)
        return ''
    monkeypatch.setattr(adapter, '_read', empty_catalogue)
    lots = adapter.discover_moscow()
    assert {lot.source.lot_url for lot in lots} == {urls[0], urls[3]}
    checks = adapter.last_report['lot_checks']
    assert checks[urls[0]]['state'] == 'collected'
    assert checks[urls[1]] == {'state': 'excluded', 'reason': 'статус «Отменен»'}
    assert checks[urls[2]] == {'state': 'unread', 'reason': 'HTTP 429'}
    assert len(events) == 4


def test_a_search_failure_does_not_erase_the_verified_known_card(monkeypatch):
    adapter = RoseltorgAdapter()
    url = 'https://www.roseltorg.ru/procedure/100/1'
    adapter.known_krt_lots = [{'url': url}]
    lot = AuctionLot(source=AuctionSource(SourceKind.ROSELTORG, url, '100/1', 'now'),
                     lot_kind=LotKind.KRT, title='КРТ города Москвы',
                     application_deadline='30.11.2099 15:00', status='Прием заявок',
                     raw={'lot_region_code': '77'})
    monkeypatch.setattr(adapter, 'fetch_lot', lambda *a, **kw: lot)
    def fail(*a, **kw):
        raise RuntimeError('HTTP 429')
    monkeypatch.setattr(adapter, '_read', fail)
    assert adapter.discover_moscow() == [lot]
    assert adapter.last_report['lot_checks'][url]['state'] == 'collected'
    assert 'HTTP 429' in adapter.last_report['reason']


def test_real_saved_catalogue_has_five_missing_lots(monkeypatch):
    import json
    from datetime import datetime, timezone
    from pathlib import Path
    from auction_search import krt_reconciliation as module
    from auction_search.parsing import deadline_is_current
    fixed = datetime(2026, 11, 16, 10, 2, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'deadline_is_current',
                        lambda value: deadline_is_current(value, now=fixed))
    data = json.loads((Path(__file__).parent / 'fixtures/krt_reconciliation_20261116.json').read_text())
    result = reconcile(expected_lots(data['known']), data['collected'], {})
    assert result['expected'] == 14
    assert result['included'] == 9
    missing = {r['url'].split('/')[-2] for r in result['rows'] if r['state'] != 'included'}
    assert missing == {'21000005000000033939', '21000005000000031369',
                       '21000005000000031312', '21000005000000031293',
                       '21000005000000031472'}
    assert all(r['state'] == 'unread' for r in result['rows'] if r['state'] != 'included')


def test_first_lot_url_alias_is_not_a_missing_lot():
    url = 'https://www.roseltorg.ru/procedure/100/1'
    expected = [{'url': url, 'slugs': ['a']}]
    actual = [{'source': {'lot_url': url[:-2]}, 'main_selection': True}]
    result = reconcile(expected, actual, {url: {'state': 'excluded', 'reason': 'дубль'}})
    assert result['included'] == 1
    assert result['rows'][0]['state'] == 'included'


def test_quality_reason_survives_main_selection_filter():
    from auction_search.service import AuctionSearchService
    url = 'https://www.roseltorg.ru/procedure/100/1'
    lot = AuctionLot(source=AuctionSource(SourceKind.ROSELTORG, url, '100/1', 'now'),
                     lot_kind=LotKind.KRT, title='КРТ города Москвы', address='г. Москва',
                     application_deadline='30.11.2099 15:00', status='Прием заявок')
    class Adapter:
        def discover_moscow(self):
            return [lot]
    service = AuctionSearchService([Adapter()])
    for noise in (False, True):
        lots = service.discover_moscow(include_noise=noise)
        assert len(lots) == int(noise)
        check = service.last_selection_checks[url]
        assert check['state'] == 'excluded'
        assert 'площадь территории' in check['reason']


def test_known_first_page_does_not_hide_new_lot_on_second_page(monkeypatch):
    adapter = RoseltorgAdapter()
    url = 'https://www.roseltorg.ru/procedure/100/1'
    new = 'https://www.roseltorg.ru/procedure/101/1'
    adapter.known_krt_lots = [{'url': url}]
    monkeypatch.setattr(adapter, 'SECTION_URLS', [('КРТ', 'https://www.roseltorg.ru/section')])
    monkeypatch.setattr(adapter, 'DISCOVERY_TAGS', ())
    monkeypatch.setattr(adapter, '_discover_privatization', lambda *a: [])
    monkeypatch.setattr(adapter, '_paged', lambda base, page: f'{base}?page={page}')
    pages = {'1': f'<a href="{url}">КРТ</a>', '2': f'<a href="{new}">КРТ</a>'}
    monkeypatch.setattr(adapter, '_read', lambda page, *a, **kw: pages.get(page.split('=')[-1], ''))
    def fetch(link, **kw):
        return AuctionLot(source=AuctionSource(SourceKind.ROSELTORG, link, link, 'now'),
                          lot_kind=LotKind.KRT, title='КРТ города Москвы',
                          application_deadline='30.11.2099 15:00', status='Прием заявок',
                          raw={'lot_region_code': '77'})
    monkeypatch.setattr(adapter, 'fetch_lot', fetch)
    assert {lot.source.lot_url for lot in adapter.discover_moscow()} == {url, new}
