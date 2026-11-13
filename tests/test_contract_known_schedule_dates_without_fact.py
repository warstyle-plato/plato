"""Source GPR dates remain visible when plan/fact cannot yet be calculated."""
import copy

import pytest

import developaid_contract_files as files
import developaid_monitor as monitor
from tests.test_contract_documents_are_read_from_their_tables import schedule_pdf
from tests.test_contract_card_shows_its_documents import ROW
from tests.test_monitor_cumulative_controls import CONTRACT, browser_page

PROJECT='Учебный'
CUT='2026-02-04'


@pytest.fixture
def source_card(monkeypatch,tmp_path):
    monkeypatch.setattr(monitor,'_SNAPSHOT_DIR',tmp_path/'monitor')
    files.store(PROJECT,ROW,'График.pdf',schedule_pdf(title=(
        'Приложение № 2 к Дополнительному соглашению № 4 от 01.02.2026',
        'к Договору подряда № 12-ТСТ от 01.09.2025')))
    return files.listing(PROJECT,CONTRACT,CUT)


def test_source_dates_do_not_require_an_estimate_links_or_actual_ks(source_card):
    control=source_card['control']
    assert control['total'] is None and not source_card['plan']['editions']
    source=control['schedule_source']
    assert (source['start'],source['finish'])==('2026-01-29','2026-02-05')
    assert source['basis']=='source_gpr' and source['sha256']==source_card['documents'][0]['sha256']
    assert 'forecast' not in source and 'deadline' not in source


def test_a_future_or_unconfirmed_source_is_not_selected(source_card):
    records=copy.deepcopy(source_card['documents'])
    assert files._schedule_source(records,'2026-01-31') is None
    records[0]['scan']={'confirmed_at':None}
    assert files._schedule_source(records,CUT) is None


def test_conflicting_documents_of_one_edition_do_not_pick_one_silently(source_card):
    records=copy.deepcopy(source_card['documents'])
    records.append(copy.deepcopy(records[0]));records[-1]['sha256']='f'*64
    assert files._schedule_source(records,CUT) is None


def test_the_register_and_card_share_the_same_source_interval(source_card):
    row={'id':CONTRACT,'physical_items':[]}
    got=files.register_control(PROJECT,{'rows':[row]},CUT)['rows'][0]['schedule_control']
    assert got['state'] is None and got['finish'] is None
    assert got['schedule_source']==source_card['control']['schedule_source']


@pytest.mark.parametrize('width',[390,1440])
def test_real_page_shows_known_plan_dates_when_forecast_is_unavailable(source_card,width):
    from playwright.sync_api import expect
    row={'id':CONTRACT,'physical_items':[]}
    control=files.register_control(PROJECT,{'rows':[row]},CUT)['rows'][0]['schedule_control']
    with browser_page(width) as (page,responses,errors):
        responses.data['rows'][0]['schedule_control']=control
        page.route('**/monitor/contracts/document*',lambda route:route.fulfill(json={
            'pending':False,'ok':True,**source_card}))
        page.locator('#contractsTab').click()
        line=page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        expect(line).to_contain_text('Прогноз не рассчитан')
        expect(line).to_contain_text('План по ГПР: 29.01.2026 — 05.02.2026')
        expect(line.locator('.term')).to_contain_text('Окончание ГПР: 05.02.2026')
        expect(line.locator('.term')).to_contain_text('Прогноз по ГПР не рассчитан')
        expect(line.locator('.term')).not_to_contain_text('Прогноз неизвестен')
        line.locator('.contract-open').click()
        expect(page.locator('.contract-control')).to_contain_text('План по ГПР: 29.01.2026 — 05.02.2026')
        expect(page.locator('.contract-control')).to_contain_text('прогноз окончания ещё не рассчитан')
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('contract_deadline',[None,'2026-02-03'])
def test_known_gpr_forecast_is_the_same_in_the_term_tile_and_schedule(width,contract_deadline):
    from playwright.sync_api import expect
    from tests.contract_rows import opened
    from tests.test_contract_register_shows_schedule_control import BEHIND

    with browser_page(width) as (page,responses,errors):
        row=responses.data['rows'][0]
        row.update(deadline=contract_deadline,deadline_passed=False)
        # The old monetary forecast cannot override an existing work-schedule result.
        row['risk']={'status':'unknown','label':'Прогноз неизвестен','forecast_finish':None}
        row['schedule_control']=copy.deepcopy(BEHIND)
        row['schedule_control'].update(percent=-0.45,plan_share=10/11,plan_done=0.55)
        if contract_deadline:
            row['schedule_control'].update(deadline=contract_deadline,from_register=True,days_over=3)
        page.locator('#contractsTab').click()
        line=page.locator(f'tr[data-contract-id="{CONTRACT}"]')
        term=line.locator('.term')
        target='Срок договора: 03.02.2026' if contract_deadline else 'Окончание ГПР: 05.02.2026'
        expect(term).to_contain_text(target)
        expect(term).to_contain_text('Прогноз по ГПР: 06.02.2026')
        expect(term).not_to_contain_text('Прогноз неизвестен')
        expect(line.locator('.contract-schedule')).to_contain_text('прогноз 06.02.2026')
        more=opened(page,CONTRACT)
        expect(more.locator('.contract-more-term')).to_contain_text(target)
        expect(more.locator('.contract-more-term')).to_contain_text('Прогноз по ГПР: 06.02.2026')
        expect(more.locator('.contract-more-term')).not_to_contain_text('Прогноз неизвестен')
        expect(more.locator('.contract-schedule-forecast')).to_contain_text('06.02.2026')
        if not contract_deadline:
            expect(term).to_contain_text('Срок договора не указан')
            expect(more.locator('.contract-term')).to_have_text('Указать срок')
        if width==1440 and contract_deadline is None:
            page.screenshot(path='/tmp/contracts-known-gpr-term-1440.png',full_page=True)
        assert not errors and page.evaluate('document.documentElement.scrollWidth<=innerWidth')
