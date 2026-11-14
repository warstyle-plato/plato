"""A new cumulative archive supplements the register instead of replacing it."""
from __future__ import annotations

import base64
import datetime as dt
import io

import openpyxl
import pytest

import developaid_monitor_contracts as contracts
import developaid_monitor_ledgers as ledgers
from test_contracts_from_cumulative_headers import ARCHIVE_READER, archive, context, ks  # noqa: F401
from test_monitor_cumulative_api import api, poll, post  # noqa: F401

PROJECT = 'Объединение'
TODAY = dt.date.today()
FIRST = (TODAY - dt.timedelta(days=8)).isoformat()
MIDDLE = (TODAY - dt.timedelta(days=4)).isoformat()
SECOND = TODAY.isoformat()


def ru(day):
    return dt.date.fromisoformat(day).strftime('%d.%m.%Y')


def grown(number='A-12'):
    """The same contract a week later: the second period closed 300 instead of 200."""
    wb = openpyxl.load_workbook(io.BytesIO(ks(number=number)))
    ws = wb.active
    ws['L9'], ws['M9'], ws['O9'] = 300, 500, 500
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


@pytest.fixture
def stored(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    first = ledgers.store_archive(PROJECT, archive([
        ('A.xlsx', ks()), ('B.xlsx', ks(number='B-24')), ('C.xlsx', ks(number='C-36'))]), FIRST, 'Первый.zip')
    second = ledgers.store_archive(PROJECT, archive([('A.xlsx', grown())]), SECOND, 'Второй.zip')
    return first['snapshot_id'], second['snapshot_id']


def by_number(view):
    return {row['contract']: row for row in view['rows']}


def check_union(view, first, second):
    rows = by_number(view)
    assert set(rows) == {'A-12', 'B-24', 'C-36'}
    # The newest archive owns contract A whole; its cumulative figure is not summed.
    assert rows['A-12']['completed'] == 500
    assert rows['A-12']['source_date'] == SECOND and rows['A-12']['source_snapshot_id'] == second
    assert 'carried_from_archive' not in rows['A-12']
    for number in ('B-24', 'C-36'):
        row = rows[number]
        assert row['completed'] == 400
        assert row['source_date'] == FIRST and row['source_snapshot_id'] == first
        assert row['carried_from_archive']['snapshot_id'] == first
        assert row['carried_from_archive']['text'] == f'Данные на {ru(FIRST)}: в архиве от {ru(SECOND)} этого договора нет.'
        assert all(e['binding']['snapshot_id'] == first for e in row['date_evidence'] if e.get('binding'))
    assert view['source_date'] == SECOND
    assert view['snapshots']['cumulative_id'] == second
    assert view['snapshots']['carried'] == [{'snapshot_id': first, 'taken_at': FIRST, 'contracts': 2}]
    assert view['counts']['contracts_from_newest_archive'] == 1
    assert view['counts']['contracts_carried'] == 2
    assert view['counts']['cumulative_sheets'] == 3


def test_new_archive_keeps_contracts_it_does_not_contain(stored):
    first, second = stored
    check_union(contracts.build(PROJECT, SECOND), first, second)


def test_latest_archive_only_is_not_accepted(stored, monkeypatch):
    first, second = stored
    monkeypatch.setattr(contracts, '_archives', lambda project, cut, cache=None: [contracts._archive(project, cut)])
    with pytest.raises(AssertionError):
        check_union(contracts.build(PROJECT, SECOND), first, second)


def test_earlier_cut_reads_only_the_earlier_archive(stored):
    first, _ = stored
    view = contracts.build(PROJECT, MIDDLE)
    rows = by_number(view)
    assert set(rows) == {'A-12', 'B-24', 'C-36'}
    assert rows['A-12']['completed'] == 400
    assert all(row['source_snapshot_id'] == first and 'carried_from_archive' not in row for row in view['rows'])
    assert view['counts']['contracts_carried'] == 0 and view['snapshots']['carried'] == []


def test_carried_contract_keeps_its_id_and_history_is_not_doubled(stored):
    earlier = by_number(contracts.build(PROJECT, MIDDLE))
    later = by_number(contracts.build(PROJECT, SECOND))
    assert {k: v['id'] for k, v in earlier.items()} == {k: v['id'] for k, v in later.items()}
    # Being carried is provenance, not a source problem to reconcile.
    for number in ('B-24', 'C-36'):
        assert later[number]['warnings'] == earlier[number]['warnings']
        assert later[number]['requires_reconciliation'] == earlier[number]['requires_reconciliation']
    carried = later['B-24']['progress']
    assert carried['observation_date'] == FIRST and carried['snapshot_id'] == later['B-24']['source_snapshot_id']
    assert [p['observation_date'] for p in carried['series']] == [FIRST]
    assert carried['comparison_state'] == 'no_previous_snapshot'
    current = later['A-12']['progress']
    assert [p['observation_date'] for p in current['series']] == [FIRST, SECOND]
    assert current['ratio'] == pytest.approx(500/1020) and current['previous_ratio'] == pytest.approx(400/1020)


def test_undated_contract_in_a_changed_file_is_not_doubled(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    ledgers.store_archive(PROJECT, archive([('Old.xlsx', ks(number='D-48', date='03.07.124'))]), FIRST)
    ledgers.store_archive(PROJECT, archive([('Renamed.xlsx', ks(number='D-48', date='03.07.124'))]), SECOND)
    view = contracts.build(PROJECT, SECOND)
    row, = view['rows']
    assert row['source_date'] == SECOND and 'carried_from_archive' not in row
    withheld = [x for x in view['unresolved_sources'] if 'не перенесён' in x['reason']]
    assert len(withheld) == 1 and withheld[0]['source_date'] == FIRST
    assert f'из архива от {ru(FIRST)}' in withheld[0]['reason'].lower()


def test_same_number_with_another_confirmed_date_is_another_contract(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    ledgers.store_archive(PROJECT, archive([('Old.xlsx', ks())]), FIRST)
    ledgers.store_archive(PROJECT, archive([('New.xlsx', ks(date=dt.date(2026, 3, 1)))]), SECOND)
    rows = contracts.build(PROJECT, SECOND)['rows']
    assert sorted((r['contract_date'], r['source_date']) for r in rows) == [('2026-01-01', FIRST), ('2026-03-01', SECOND)]


def test_a_carried_header_date_is_clarified_in_its_own_archive(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    first = ledgers.store_archive(PROJECT, archive([('E.xlsx', ks(number='E-60', date='03.07.124'))]), FIRST)
    ledgers.store_archive(PROJECT, archive([('A.xlsx', ks())]), SECOND)
    row = by_number(contracts.build(PROJECT, SECOND))['E-60']
    binding, = [e['binding'] for e in row['date_evidence']]
    assert binding['snapshot_id'] == first['snapshot_id']
    contracts.confirm_header_date(PROJECT, SECOND, contract_date='2024-07-03', **binding)
    row = by_number(contracts.build(PROJECT, SECOND))['E-60']
    assert row['contract_date'] == '2024-07-03' and row['source_date'] == FIRST


def test_archive_summary_names_contracts_kept_from_earlier_archives(stored):
    assert contracts.archive_summary(PROJECT, SECOND)['contracts_in_archive'] == 1
    assert contracts.archive_summary(PROJECT, SECOND)['contracts_carried'] == 2
    assert contracts.archive_summary(PROJECT, FIRST)['contracts_carried'] == 0


def test_upload_result_says_which_contracts_stay(api):  # noqa: F811
    client, _ = api

    def upload(files, day):
        response = post(client, 'cumulative/upload', project=PROJECT, taken_at=day, filename='Архив.zip',
                        content_base64=base64.b64encode(archive(files)).decode())
        return poll(client, response.json()['ticket'], family='cumulative').json()

    upload([('A.xlsx', ks()), ('B.xlsx', ks(number='B-24'))], FIRST)
    result = upload([('A.xlsx', grown())], SECOND)
    assert result['ok'] is True
    assert result['contracts']['contracts_in_archive'] == 1 and result['contracts']['contracts_carried'] == 1


@pytest.mark.parametrize('width', [390, 1440])
def test_page_names_each_archive_and_the_missing_contract(stored, width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    from tests.contract_rows import row as contract_row
    view = contracts.build(PROJECT, SECOND)
    carried = by_number(view)['B-24']
    note = f'Данные на {ru(FIRST)}: в архиве от {ru(SECOND)} этого договора нет.'
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        expect(page.locator('#contractsMsg')).to_contain_text(
            f'Из архива от {ru(SECOND)}: 1, из прежних архивов: 2 — в новом архиве этих договоров нет.', timeout=10000)
        line = contract_row(page, carried['id']).locator('.contract-carried')
        expect(line).to_have_text(note)
        assert line.is_visible()
        box = line.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width
        assert contract_row(page, by_number(view)['A-12']['id']).locator('.contract-carried').count() == 0
        contract_row(page, carried['id']).locator('td.party').click()
        page.locator('#contractDialog').wait_for(state='visible')
        expect(page.locator('#contractsDetails > .contract-carried')).to_have_text(note)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('width', [390, 1440])
def test_upload_message_names_contracts_kept_from_earlier_archives(width, monkeypatch):
    from playwright.sync_api import expect
    from urllib.parse import urlparse
    import test_monitor_cumulative_controls as controls

    class Kept(controls.Responses):
        def __call__(self, route):
            path = urlparse(route.request.url).path
            try:
                body = route.request.post_data_json or {}
            except Exception:
                body = {}
            if path == '/monitor/cumulative/result' and self.jobs.get(body.get('ticket'), ('',))[0] == '/monitor/cumulative/upload':
                self.uploaded = True
                return route.fulfill(json={'pending': False, 'ok': True, 'snapshot': {'taken_at': SECOND, 'files': []},
                                           'contracts': {'contracts_in_archive': 1, 'contracts_carried': 2}})
            return super().__call__(route)

    monkeypatch.setattr(controls, 'Responses', Kept)
    with controls.browser_page(width) as (page, responses, errors):
        page.locator('#dataTab').click()
        page.locator('#cumulativeFile').set_input_files({'name': 'Новый.zip', 'mimeType': 'application/zip', 'buffer': b'synthetic'})
        page.locator('#cumulativeUpload').click()
        message = page.locator('#cumulativeMsg')
        expect(message).to_contain_text('Договоров в этом архиве: 1.', timeout=10000)
        expect(message).to_contain_text('Ещё договоров из прежних архивов остаются в реестре: 2 — в этом архиве их нет')
        assert message.is_visible() and not errors


def test_other_contract_archives_do_not_repeat_a_carried_observation_before_its_update(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    days = [(TODAY - dt.timedelta(days=n)).isoformat() for n in (12, 8, 4, 0)]
    first = ledgers.store_archive(PROJECT, archive([('A.xlsx', ks())]), days[0])
    ledgers.store_archive(PROJECT, archive([('B.xlsx', ks(number='B-24'))]), days[1])
    ledgers.store_archive(PROJECT, archive([('C.xlsx', ks(number='C-36'))]), days[2])
    latest = ledgers.store_archive(PROJECT, archive([('A.xlsx', grown())]), days[3])
    row = by_number(contracts.build(PROJECT, days[3]))['A-12']
    points = row['progress']['series']
    assert [(p['observation_date'], p['snapshot_id']) for p in points] == [
        (days[0], first['snapshot_id']), (days[3], latest['snapshot_id'])]
    assert row['progress']['previous_ratio'] == pytest.approx(400/1020)
    assert row['progress']['ratio'] == pytest.approx(500/1020)
    assert row['observation_forecast']['state'] == 'estimated'
    assert row['observation_forecast']['point_count'] == 2


def test_an_unchanged_amount_in_a_new_own_archive_is_still_a_real_observation(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    first = ledgers.store_archive(PROJECT, archive([('A.xlsx', ks())]), FIRST)
    ledgers.store_archive(PROJECT, archive([('B.xlsx', ks(number='B-24'))]), MIDDLE)
    latest = ledgers.store_archive(PROJECT, archive([('A.xlsx', ks())]), SECOND)
    row = by_number(contracts.build(PROJECT, SECOND))['A-12']
    assert [p['snapshot_id'] for p in row['progress']['series']] == [first['snapshot_id'], latest['snapshot_id']]
    assert row['progress']['change_kind'] == 'unchanged'
    assert row['observation_forecast']['state'] == 'no_recent_growth'


def test_fewer_new_sheets_are_named_without_adding_the_previous_month(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    ledgers.store_archive(PROJECT, archive([
        ('A-January.xlsx', ks(period='jan')), ('A-February.xlsx', ks(period='feb'))]), FIRST)
    latest = ledgers.store_archive(PROJECT, archive([('A-January.xlsx', ks(period='jan'))]), SECOND)
    row = by_number(contracts.build(PROJECT, SECOND, include_history=False))['A-12']
    assert row['completed'] == 200 and len(row['sources']) == 1
    assert row['source_snapshot_id'] == latest['snapshot_id'] and row['source_date'] == SECOND
    assert any(f'1 вместо 2 в архиве от {ru(FIRST)}' in reason and 'прежние листы не добавлены' in reason
               for reason in row['warnings'])


def test_another_partial_archive_does_not_silently_confirm_the_reduced_sheet_set(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    ledgers.store_archive(PROJECT, archive([
        ('A-January.xlsx', ks(period='jan')), ('A-February.xlsx', ks(period='feb'))]), FIRST)
    ledgers.store_archive(PROJECT, archive([('A-January.xlsx', ks(period='jan'))]), MIDDLE)
    ledgers.store_archive(PROJECT, archive([('A-January.xlsx', ks(period='jan'))]), SECOND)
    row = by_number(contracts.build(PROJECT, SECOND, include_history=False))['A-12']
    assert row['completed'] == 200 and len(row['sources']) == 1
    assert any(f'1 вместо 2 в архиве от {ru(FIRST)}' in reason for reason in row['warnings'])


def test_identical_workbook_copies_are_not_a_false_sheet_loss(context):  # noqa: F811
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    same = ks()
    ledgers.store_archive(PROJECT, archive([('A.xlsx', same), ('A-copy.xlsx', same)]), FIRST)
    ledgers.store_archive(PROJECT, archive([('A.xlsx', same)]), SECOND)
    row = by_number(contracts.build(PROJECT, SECOND, include_history=False))['A-12']
    assert not any('листов ведомостей этого договора меньше' in reason for reason in row['warnings'])


@pytest.mark.parametrize('width', [390, 1440])
def test_reduced_sheet_warning_is_visible_in_the_existing_card_sources(context, width):  # noqa: F811
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page
    from tests.contract_rows import row as contract_row
    context.setattr(contracts, '_archive', ARCHIVE_READER)
    ledgers.store_archive(PROJECT, archive([
        ('A-January.xlsx', ks(period='jan')), ('A-February.xlsx', ks(period='feb'))]), FIRST)
    ledgers.store_archive(PROJECT, archive([('A-January.xlsx', ks(period='jan'))]), SECOND)
    view = contracts.build(PROJECT, SECOND, include_history=False)
    current = by_number(view)['A-12']
    with browser_page(width) as (page, responses, errors):
        responses.data = view
        page.locator('#contractsTab').click()
        line = contract_row(page, current['id'])
        expect(line.locator('.contract-attention')).to_contain_text('Есть замечания')
        line.locator('.contract-open').click()
        page.locator('#contractRecordSources > summary').click()
        page.locator('#contractRecordSources > .contract-sources > summary').click()
        warning = page.locator('#contractRecordSources .contract-warning')
        expect(warning).to_contain_text(f'1 вместо 2 в архиве от {ru(FIRST)}')
        assert warning.is_visible() and not errors
