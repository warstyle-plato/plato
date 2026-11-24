"""Document totals stay visible beside an unavailable plan, without becoming GPR facts."""
import copy
import datetime as dt
import io
import json

from openpyxl import load_workbook
import pytest

import developaid_contract_comparison_export as export
from developaid_monitor_page import MONITOR_PAGE
from tests import page_blocks
from tests.test_contract_comparison_export import native_card, table, xlsx, PROJECT, CUT, CONTRACT
from tests.test_contract_comparison_export_ui import _browser_export


def evidence():
    return {'count': 2, 'total': 770.0, 'known_total': 770.0, 'unread_count': 1, 'acts': [
        {'number': '1', 'date': '2026-02-20', 'start': '2026-02-01', 'finish': '2026-02-20',
         'day': '2026-02-20', 'sha256': '1' * 64, 'filename': 'Первый.pdf',
         'positions': 1, 'total': 330.0, 'warnings': []},
        {'number': '2', 'date': '2026-02-28', 'start': '2026-02-21', 'finish': '2026-02-28',
         'day': '2026-02-28', 'sha256': '2' * 64, 'filename': 'Второй.pdf',
         'positions': 0, 'total': 440.0, 'warnings': ['Позиции второго акта не прочитаны.']}]}


def card_with_evidence(*, empty=False):
    cached = native_card(empty=empty)
    cached['comparison'].update(source='ks2', source_note='КС-6а отсутствует. Выполнение по загруженным КС-2.',
        act_evidence=evidence(), confirmation={'state': 'acts_only', 'message': 'Полнота комплекта актов не подтверждена.'})
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {'contract': 'Т-1'})
    return cached


@pytest.mark.parametrize('empty', [False, True])
def test_excel_preserves_document_totals_and_the_original_plan_fact_cells(empty):
    baseline = native_card(empty=empty)
    original, original_header = table(xlsx(baseline))
    cached = card_with_evidence(empty=empty)
    before = copy.deepcopy(cached)
    sheet, header = table(xlsx(cached))
    rows = list(sheet.values)
    assert next(row for row in rows if row[0] == 'Итого по документам')[1] == 770
    assert next(row for row in rows if row[0] == 'Количество актов')[1] == 2
    first = next(row for row in rows if row[0] == 'КС-2 № 1')
    assert first[1].date() == dt.date(2026, 2, 20) and first[2] == 330
    text = '\n'.join(str(v) for row in rows for v in row if v is not None)
    assert 'Полнота комплекта актов не подтверждена' in text
    assert 'Актов без прочитанных позиций: 1' in text
    assert 'КС-6а отсутствует' in text
    assert list(sheet.values)[header:] == list(original.values)[original_header:]
    assert cached == before


def test_excel_leaves_an_unread_document_total_unknown():
    cached = card_with_evidence(empty=True)
    cached['comparison']['act_evidence'].update(total=None, known_total=330)
    cached['comparison']['act_evidence']['acts'][1]['total'] = None
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {})
    sheet = load_workbook(io.BytesIO(xlsx(cached))).active
    rows = list(sheet.values)
    assert next(row for row in rows if row[0] == 'Итого по документам')[1] is None
    assert next(row for row in rows if row[0] == 'Сумма прочитанных итогов')[1] == 330


@pytest.mark.parametrize('width', [390, 1440])
def test_browser_shows_acts_without_a_plan_and_retains_unknown_execution(width):
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT as BROWSER_CONTRACT, KEY

    cached = card_with_evidence(empty=True)
    with browser_page(width) as (page, responses, errors):
        responses.data['rows'][0].update(completed=None, completion_ratio=None, remaining=None,
            physical_items=[], source_kind='contract_document', schedule_control={
                'documents': 2, 'note': 'Нет редакции плана.', 'act_evidence': evidence()})
        _browser_export(page, cached, BROWSER_CONTRACT, KEY, [])
        block = page.locator('#contractKs2Confirmation .contract-act-evidence')
        expect(block).to_be_visible()
        expect(block).to_contain_text('Итоги загруженных КС-2')
        expect(block).to_contain_text('770')
        expect(block).to_contain_text('Полнота комплекта актов не подтверждена')
        expect(page.locator('#contractComparisonInfo')).to_contain_text('КС-6а отсутствует')
        expect(page.locator('#contractComparisonRows')).to_contain_text('нет действующей редакции плана')
        expect(page.locator('#contractKs2Confirmation')).not_to_contain_text('Источник объёмов выполнения — накопительная КС-6а')
        block.get_by_text('Проверить акты и суммы', exact=True).click()
        expect(block.locator('tbody tr')).to_have_count(2)
        expect(block.locator('tbody tr').nth(1)).to_contain_text('Позиции не прочитаны')
        page.locator('#contractDialogClose').click()
        brief = page.locator(f'tr[data-contract-id="{BROWSER_CONTRACT}"] .contract-money .contract-act-evidence-brief')
        expect(brief).to_be_visible()
        expect(brief).to_contain_text('Итоги КС-2: 770')
        expect(brief.locator('..')).to_contain_text('выполнение не подтверждено')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors


@pytest.mark.parametrize('note', ['Нет редакции плана.', ''])
def test_actual_fact_block_keeps_evidence_and_escapes_source_strings(note):
    actual = {'note': note, 'source': 'ks2', 'cut': CUT, 'total': None, 'positions': [],
              'source_note': 'Выполнение по загруженным КС-2.', 'act_evidence': evidence()}
    actual['act_evidence']['acts'][0]['filename'] = '<img src=x onerror=alert(1)>'
    rendered = page_blocks.run_json('const fact=' + json.dumps(actual, ensure_ascii=False) + ';',
        'console.log(JSON.stringify({html:contractFactHtml(fact)}));', page=MONITOR_PAGE)['html']
    assert 'Итоги загруженных КС-2' in rendered and 'Выполнение по загруженным КС-2' in rendered
    assert '&lt;img' in rendered and '<img' not in rendered


def test_actual_register_brief_does_not_present_a_known_subtotal_as_the_full_document_total():
    actual = evidence()
    actual.update(total=None, known_total=330)
    result = page_blocks.run_json('const evidence=' + json.dumps(actual) + ';',
        'console.log(JSON.stringify({html:contractActEvidenceBrief(evidence)}));', page=MONITOR_PAGE)['html']
    assert 'Прочитанные итоги КС-2: 330' in result
    assert 'Общий итог не определён' in result


@pytest.mark.parametrize('raw', [False, True])
def test_refresh_updates_the_selected_operational_or_raw_row_without_copying_financial_fields(raw):
    prelude = 'let contractRawMode=' + json.dumps(raw) + ';\n' + '''
const logical={id:'logical',completed:null,source_correction:{roles:{documents_raw_id:'raw'}},schedule_control:{fact:null}};
const original={id:'raw',completed:12,schedule_control:{fact:12}};
const contractRegister={rows:[logical],raw_source_rows:[original]};function $(){return null};
'''
    result = page_blocks.run_json(prelude,
        "updateContractActEvidence(contractRawMode?'raw':'logical',{control:{act_evidence:{count:1,total:33},fact:999}});"
        "console.log(JSON.stringify({logical,original}));", page=MONITOR_PAGE)
    changed, untouched = (result['original'], result['logical']) if raw else (result['logical'], result['original'])
    assert changed['schedule_control']['act_evidence'] == {'count': 1, 'total': 33}
    assert 'act_evidence' not in untouched['schedule_control']
    assert result['logical']['completed'] is None and result['logical']['schedule_control']['fact'] is None
    assert result['original']['completed'] == result['original']['schedule_control']['fact'] == 12


def test_browser_upload_and_removal_refresh_the_register_evidence_without_closing_the_card():
    from playwright.sync_api import expect
    from tests.test_monitor_cumulative_controls import browser_page, CONTRACT as BROWSER_CONTRACT, KEY

    cached = card_with_evidence(empty=True)
    cached['comparison']['act_evidence'] = {'count': 0, 'acts': [], 'total': None, 'known_total': 0, 'unread_count': 0}
    with browser_page(390) as (page, responses, errors):
        responses.data['rows'][0].update(completed=None, completion_ratio=None, remaining=None,
            schedule_control={'documents': 0, 'note': 'Нет редакции плана.'})
        _browser_export(page, cached, BROWSER_CONTRACT, KEY, [])
        empty = copy.deepcopy(cached)
        fresh = copy.deepcopy(cached)
        first = evidence()
        first.update(count=1, total=330, known_total=330, unread_count=0, acts=first['acts'][:1])
        fresh['comparison']['act_evidence'] = first
        fresh['documents'] = [{'sha256': '1' * 64, 'filename': 'Первый.pdf', 'title': 'Акт КС-2 № 1',
            'uploaded_at': CUT, 'pages': 1, 'warnings': [], 'act': {'number': '1', 'date': '2026-02-20',
            'start': '2026-02-01', 'finish': '2026-02-20', 'total': 330}, 'estimates': []}]
        def upload(route):
            body = route.request.post_data_json
            assert body['contract_id'] == BROWSER_CONTRACT and body['content_base64']
            route.fulfill(json={**fresh, 'ticket': body['ticket'], 'document': {'already': False}})
            cached.update(fresh)
        def remove(route):
            body = route.request.post_data_json
            assert body['sha256'] == '1' * 64
            route.fulfill(json={**empty, 'ticket': body['ticket']})
            cached.update(empty)
        page.route('**/monitor/contracts/document-upload', upload)
        page.route('**/monitor/contracts/document-remove', remove)
        page.locator('#contractKs2File').set_input_files({'name': 'Первый.pdf', 'mimeType': 'application/pdf',
                                                        'buffer': b'%PDF synthetic upload fixture'})
        expect(page.locator('#contractDocumentsMsg')).to_contain_text('Документ прочитан и сохранён')
        expect(page.locator('#contractDialog')).to_be_visible()
        expect(page.locator('#contractKs2Confirmation .contract-act-evidence')).to_contain_text('330')
        page.locator('#contractDialogClose').click()
        brief = page.locator(f'tr[data-contract-id="{BROWSER_CONTRACT}"] .contract-money .contract-act-evidence-brief')
        expect(brief).to_be_visible()
        expect(brief).to_contain_text('Итоги КС-2: 330')
        page.locator(f'tr[data-contract-id="{BROWSER_CONTRACT}"] .contract-open').click()
        expect(page.locator('.contract-document')).to_have_count(1)
        page.locator('#contractDocumentList > summary').click()
        page.locator('.contract-document > summary').click()
        page.once('dialog', lambda dialog: dialog.accept())
        page.locator('[data-document-remove]').click()
        expect(page.locator('#contractDocumentsMsg')).to_contain_text('Документ убран из карточки')
        expect(page.locator('#contractDialog')).to_be_visible()
        expect(page.locator('#contractKs2Confirmation .contract-act-evidence')).to_have_count(0)
        page.locator('#contractDialogClose').click()
        expect(brief).to_have_count(0)
        assert not errors
