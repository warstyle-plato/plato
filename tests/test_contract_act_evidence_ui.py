"""Document totals stay visible beside an unavailable plan, without becoming GPR facts."""
import copy
import io
import json

from openpyxl import load_workbook
import pytest

import developaid_contract_comparison_export as export
import developaid_contract_acts as acts
from tests.test_contract_rds_projection import card, edition
from tests.test_contract_ks2_positions_accumulate import _record
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


def export_card_with_acts(*, no_gpr=False, unread=True, unknown_total=False):
    # Actual synthetic source positions pass through native accumulation/matching;
    # quoted document330 deliberately differs from the admitted RDS fact300.
    first = _record('1', '1', '2026-02-20', [('1', 'Монтаж', 'м2', 3, 330)], start='2026-02-01')
    first['act']['total'] = 330
    second = _record('2', '2', '2026-02-28', [], start='2026-02-21')
    second['act']['total'] = None if unknown_total else 440
    second['warnings'] = ['Позиции второго акта не прочитаны.']
    records = [first, second] if unread else [first]
    cached = card([edition(no_schedule=no_gpr)], None, acts.accumulated(records, CUT), cut=CUT)
    cached.update(ok=True)
    cached['documents'].extend(records)
    cached['comparison_export'] = export.bind_snapshot(PROJECT, CUT, CONTRACT, cached, {'contract': 'Т-1'})
    return cached


@pytest.mark.parametrize('no_gpr', [False, True])
def test_excel_qualifies_document_totals_in_comments_and_preserves_all_sixteen_rds_cells(no_gpr):
    original, original_header = table(xlsx(export_card_with_acts(no_gpr=no_gpr, unread=False)))
    cached = export_card_with_acts(no_gpr=no_gpr)
    before = copy.deepcopy(cached)
    raw = xlsx(cached)
    sheet, header = table(raw)
    values, values_header = table(raw, data_only=True)
    assert values_header == header
    assert len(sheet.parent.worksheets) == 1 and sheet.max_column == 16
    assert cached['fact']['act_evidence']['total'] == 770
    assert cached['fact']['act_evidence']['count'] == 2
    assert cached['fact']['act_evidence']['unread_count'] == 1
    assert '770,00 ₽' in sheet['L6'].comment.text
    assert 'отдельная сверка' in sheet['L6'].comment.text
    assert 'Полнота комплекта актов не подтверждена' in sheet['A3'].comment.text
    assert 'КС-6а отсутствует' in sheet['A3'].comment.text
    assert list(sheet.values)[header:] == list(original.values)[original_header:]
    assert sheet.cell(header+1, 8).value == 3
    assert sheet.cell(header+1, 12).value == 300  # Neither quoted total770 nor loaded position330.
    if no_gpr:
        # Guarded deviation formulas remain editable, but a missing plan must
        # still download as unknown rather than as -fact or a fabricated zero.
        assert all(values.cell(header+1, column).value is None for column in (4,5,6,7,10,11,13,14,15,16))
        assert all(sheet.cell(header+1, column).data_type == 'f' for column in (10,13))
        assert all(sheet.cell(header+1, column).comment for column in (4,5,6,7,10,11,13,14,15,16))
    assert not any(value in ('Итого по документам', 'Количество актов', 'Сумма прочитанных итогов')
                   for row in sheet.values for value in row)
    assert cached == before


def test_excel_does_not_promote_known_document_subtotal_to_full_value_fact():
    cached = export_card_with_acts(no_gpr=True, unknown_total=True)
    raw = xlsx(cached)
    sheet, header = table(raw)
    values, values_header = table(raw, data_only=True)
    assert values_header == header
    assert cached['fact']['act_evidence']['total'] is None
    assert cached['fact']['act_evidence']['known_total'] == 330
    assert 'Итоги загруженных актов по самим документам:' not in sheet['L6'].comment.text
    assert '330,00 ₽' not in sheet['L6'].comment.text
    assert sheet.cell(header+1, 12).value == 300
    assert sheet.cell(header+1, 11).value is None
    assert sheet.cell(header+1, 13).data_type == 'f'
    assert values.cell(header+1, 11).value is None and values.cell(header+1, 13).value is None
    assert values.cell(header+1, 12).value == 300
    assert 'Полнота комплекта актов не подтверждена' in sheet['A3'].comment.text


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
        block.get_by_text('Загруженные акты КС-2 (2)', exact=True).click()
        expect(block.locator('tbody tr')).to_have_count(2)
        expect(block.locator('tbody tr').nth(1)).to_contain_text('Позиции не прочитаны')
        if width == 390:
            metrics = block.locator('tbody tr').first.evaluate('''row => ({
                width: row.getBoundingClientRect().width,
                cells: [...row.cells].map(cell => ({width: cell.getBoundingClientRect().width,
                    label: getComputedStyle(cell, '::before').content}))})''')
            assert all(cell['width'] >= metrics['width'] * .9 for cell in metrics['cells'])
            assert all(cell['label'] not in ('none', '""') for cell in metrics['cells'])
        page.locator('#contractDialogClose').click()
        brief = page.locator(f'tr[data-contract-id="{BROWSER_CONTRACT}"] .contract-money .contract-act-evidence-brief')
        expect(brief).to_be_visible()
        expect(brief).to_contain_text('Итоги КС-2: 770')
        expect(brief.locator('..')).to_contain_text('Процент денежного закрытия не подтверждён')
        assert brief.locator('..').locator('.contract-progress').count() == 0
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
