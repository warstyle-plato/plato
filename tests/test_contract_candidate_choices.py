"""Contract choices are source-backed, not all contracts in the project."""
from __future__ import annotations

import copy

import pytest

import developaid_monitor_contract_links as links
from test_monitor_contract_links import (
    CUT, FIRST, PROJECT, SECOND, evidence, install_register, isolated, register, report,
)

OTHER = "c" * 64


def choices_register():
    data = register(two=True)
    data["rows"].append({**copy.deepcopy(data["rows"][0]), "id": OTHER,
                         "contractor": "ООО Другой подрядчик", "contract": "Ч-01"})
    return data


def test_only_contracts_of_the_reported_party_are_selectable_and_post_rechecks_them(monkeypatch):
    data = install_register(monkeypatch, choices_register())
    report()
    item, = evidence(data)["unmatched_works"]
    assert item["selectable_contract_ids"] == [FIRST, SECOND]
    assert item["suggested_contract_id"] == ""
    assert item["match_status"] == "ambiguous"
    with pytest.raises(links.LinkProblem, match="подрядчика"):
        links.set_link(PROJECT, OTHER, item["id"], CUT)
    assert not links._path(PROJECT).exists()
    links.set_link(PROJECT, SECOND, item["id"], CUT)
    assert evidence(data)["unmatched_works"] == []


@pytest.mark.parametrize("change,line,reason", [
    ({"contractor": "ИП Альфа"}, "Корпус 1 бетон", "подрядчика"),
    ({"contractor": "Альфа Строй"}, "Корпус 1 бетон", "подрядчика"),
    ({"contract_date": "2026-10-15"}, "Корпус 1 бетон", "после сообщения"),
    ({}, "Корпус 1 работы по договору № A-123", "номер"),
    ({}, "Корпус 1 и 2 бетон", "Корпус"),
    ({}, "Корпус 1/2 бетон", "Корпус"),
])
def test_invalid_source_cannot_offer_or_manually_accept_a_contract(monkeypatch, change, line, reason):
    data = register()
    data["rows"][0].update(change)
    install_register(monkeypatch, data)
    report(line, party="ООО Альфа")
    item, = evidence(data)["unmatched_works"]
    assert item["selectable_contract_ids"] == []
    assert item["suggested_contract_id"] == ""
    assert item["match_status"] == "unmatched"
    assert reason.casefold() in item["match_reason"].casefold()
    with pytest.raises(links.LinkProblem, match=reason):
        links.set_link(PROJECT, FIRST, item["id"], CUT)
    assert not links._path(PROJECT).exists()


def test_future_competitor_does_not_block_the_one_current_contract():
    data = register(two=True)
    data["rows"][1]["contract_date"] = "2026-10-15"
    report()
    result = evidence(data)
    assert result["unmatched_works"] == []
    item, = result["rows"][0]["reconciliation"]["daily_evidence"]
    assert item["contract_id"] == FIRST
    assert item["selectable_contract_ids"] == [FIRST]


def test_revoked_single_link_has_an_explicit_single_proposal(monkeypatch):
    data = install_register(monkeypatch)
    report()
    original, = links._evidence(PROJECT, data, CUT)
    links.set_link(PROJECT, FIRST, original["id"], CUT, confirmed=False)
    item, = evidence(data)["unmatched_works"]
    assert item["match_status"] == "proposed"
    assert item["suggested_contract_id"] == FIRST
    assert item["selectable_contract_ids"] == [FIRST]


def test_legacy_foreign_manual_record_is_visible_revocable_and_not_active(monkeypatch):
    data = install_register(monkeypatch, choices_register())
    report()
    original, = links._evidence(PROJECT, data, CUT)
    with links._locked(PROJECT):
        links._write(PROJECT, {"version": 1, "links": {original["id"]: {
            "signature": original["signature"], "evidence_id": original["id"],
            "contract_id": OTHER, "confirmed": True, "source_date": original["date"],
            "confirmed_at": "2026-10-14T12:00:00+00:00", "basis": "manual",
            "candidate_contract_ids": [FIRST, SECOND],
        }}})
    result = evidence(data)
    item, = result["unmatched_works"]
    assert item["contract_id"] == "" and item["link_basis"] == "manual_review"
    assert item["manual_contract_id"] == OTHER and item["manual_review_required"]
    assert item["selectable_contract_ids"] == [FIRST, SECOND]
    assert links._read(PROJECT)["links"][item["id"]]["confirmed"]
    old_row = result["rows"][2]
    assert old_row["reconciliation"]["status"] != "Есть подтверждённые связи"
    groups = [{"contractor": "Альфа", "lines": [
        {"line": "Корпус 1 бетонирование", "days": ["2026-10-14"]}]}]
    output = links.enrich_report_works(PROJECT, groups, "2026-10-12", CUT,
                                      context={"register": result})[0]["lines"][0]
    assert output["contract_links"] == []
    assert {row["id"] for row in output["contract_candidates"]} == {FIRST, SECOND}
    assert "Прежняя ручная связь требует проверки" in output["contract_match_reason"]
    links.set_link(PROJECT, OTHER, item["id"], CUT, confirmed=False)
    assert not links._read(PROJECT)["links"][item["id"]]["confirmed"]
    with pytest.raises(links.LinkProblem, match="подрядчика"):
        links.set_link(PROJECT, OTHER, item["id"], CUT)


def test_an_omitted_legal_form_never_picks_between_two_distinct_parties():
    data = register(two=True)
    data["rows"][1]["contractor"] = "ИП Альфа"
    report(party="Альфа")
    item, = evidence(data)["unmatched_works"]
    assert item["match_status"] == "ambiguous"
    assert item["selectable_contract_ids"] == [FIRST, SECOND]
    assert item["suggested_contract_id"] == ""


def test_repeated_days_leave_only_real_ambiguities_in_the_pending_count():
    data = register(two=True)
    data['rows'][1].update(scope=['Корпус 2'], physical_items=[{'scope': 'Корпус 2'}])
    data['rows'].append({**copy.deepcopy(data['rows'][1]), 'id': OTHER, 'contract': 'А-14'})
    data['rows'].append({**copy.deepcopy(data['rows'][0]), 'id': 'd'*64,
                         'contractor': 'Другой подрядчик', 'contract': 'Ч-01'})
    for day in range(1, 11):
        report('Корпус 1 бетонирование', day=f'2026-09-{day:02d}')
    for day in range(11, 16):
        report('Корпус 2 бетонирование', day=f'2026-09-{day:02d}')
    for day in range(16, 19):
        report('Корпус 1 бетонирование', day=f'2026-09-{day:02d}', party='Неизвестный подрядчик')
    assert len(links._evidence(PROJECT, data, CUT)) == 18
    result = evidence(data)
    determined = result['rows'][0]['reconciliation']['daily_evidence']
    assert len(determined) == 10
    assert all(item['contract_id'] == FIRST and item['link_basis'] == 'exact_party'
               for item in determined)
    pending = result['unmatched_works']
    assert len(pending) == 8
    assert sum(item['match_status'] == 'ambiguous' for item in pending) == 5
    assert sum(item['match_status'] == 'unmatched' for item in pending) == 3
    assert all('d'*64 not in item['selectable_contract_ids'] for item in pending)
    assert not links._path(PROJECT).exists()


@pytest.mark.parametrize('wording', [
    'по договору на устройство фасада',
    'по договору подрядчика',
    'по договору выполняются работы',
    'по договору на 2026 год',
    'по договору согласно графику',
])
def test_ordinary_words_after_contract_allow_both_unique_auto_and_manual_link(monkeypatch, wording):
    data = install_register(monkeypatch)
    report('Корпус 1 монтаж ' + wording)
    result = evidence(data)
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['contract_id'] == FIRST and item['link_basis'] == 'exact_party'
    assert item['selectable_contract_ids'] == [FIRST]
    assert links.set_link(PROJECT, FIRST, item['id'], CUT)['confirmed']


@pytest.mark.parametrize('reference,number', [
    ('по договору № A-12', 'A-12'),
    ('по договору A-12', 'A-12'),
    ('по договору N A-12', 'A-12'),
    ('по дог. A-12', 'A-12'),
    ('по договору № «АБ-12/3»', 'АБ-12/3'),
    ('по договором A-12.', 'A-12'),
    ('по договору N123', 'N123'),
    ('по договору подряда № A-12', 'A-12'),
    ('по договору строительного подряда № A-12', 'A-12'),
    ('по договору на выполнение работ № A-12', 'A-12'),
    ('по договору номер A-12', 'A-12'),
    ('по договору под номером A-12', 'A-12'),
    ('по договору No. A-12', 'A-12'),
    ('по договору N°A-12', 'A-12'),
    ('по договору NºA-12', 'A-12'),
    ('по договору #A-12', 'A-12'),
    ('по договорам № A-12', 'A-12'),
])
def test_real_number_signature_identifies_only_the_full_number(reference, number):
    data = register(two=True)
    data['rows'][0]['contract'] = number
    data['rows'][1]['contract'] = '123' if number == 'N123' else number + '3'
    report('Корпус 1 монтаж ' + reference)
    result = evidence(data)
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['contract_id'] == FIRST and item['link_basis'] == 'explicit_number'
    assert item['selectable_contract_ids'] == [FIRST]


@pytest.mark.parametrize('reference', [
    'по договору A-123',
    'по договору A-12/1',
    'по договору Б-12',
    'по договору № ЧУЖОЙ',
    'по договору №',
    'по договору подряда № A-123',
    'по договору строительного подряда № A-123',
    'по договору на выполнение работ № A-123',
    'по договору номер A-123',
    'по договору под номером A-123',
    'по договору No. A-123',
    'по договору N°A-123',
    'по договору NºA-123',
    'по договору #A-123',
])
def test_explicit_other_or_incomplete_number_cannot_fall_back_to_unique_party(monkeypatch, reference):
    data = install_register(monkeypatch)
    report('Корпус 1 монтаж ' + reference)
    item, = evidence(data)['unmatched_works']
    assert item['contract_id'] == ''
    assert item['selectable_contract_ids'] == []
    assert 'номер' in item['match_reason']
    with pytest.raises(links.LinkProblem, match='номер'):
        links.set_link(PROJECT, FIRST, item['id'], CUT)


@pytest.mark.parametrize('reference', [
    'по договору на монтаж корпуса № 2',
    'по договору выполняются работы на этаже № 3',
    'по договору работы отражены в акте № 17',
])
def test_number_of_another_named_entity_is_not_a_contract_number(monkeypatch, reference):
    data = register()
    data['rows'][0].update(scope=['Корпус 1', 'Корпус 2'], physical_items=[])
    install_register(monkeypatch, data)
    report('Корпус 1 монтаж ' + reference)
    result = evidence(data)
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['link_basis'] == 'exact_party' and item['contract_id'] == FIRST
    assert links.set_link(PROJECT, FIRST, item['id'], CUT)['confirmed']


@pytest.mark.parametrize('two', [False, True])
@pytest.mark.parametrize('reference', [
    'по договору № A-12 и договору № A-13',
    'по договорам № A-12 и № A-13',
    'по договорам № A-12, A-13',
    'по договорам с номерами A-12 и A-13',
    'по договору № A-12; № A-13',
])
def test_two_different_explicit_numbers_keep_whole_message_pending_and_block_manual(monkeypatch, two, reference):
    data = install_register(monkeypatch, register(two=two))
    report('Корпус 1 кладка ' + reference)
    item, = evidence(data)['unmatched_works']
    assert item['contract_id'] == ''
    assert item['selectable_contract_ids'] == [] and item['suggested_contract_id'] == ''
    assert 'несколько номеров договоров' in item['match_reason']
    for row in data['rows']:
        with pytest.raises(links.LinkProblem, match='несколько номеров договоров'):
            links.set_link(PROJECT, row['id'], item['id'], CUT)
    assert not links._path(PROJECT).exists()


@pytest.mark.parametrize('reference', [
    'по договору № A-12 и договору № a-12',
    'по договору № A-12 и договору строительного подряда № A–12',
    'по дог. № A-12 и договору N A-12',
    'по договорам № A-12, A-12',
    'по договорам с номерами A-12 и a-12',
])
def test_repeated_aliases_of_the_same_explicit_number_still_identify_one_contract(monkeypatch, reference):
    data = install_register(monkeypatch)
    report('Корпус 1 монтаж ' + reference)
    assert links._explicit_contract_numbers(reference) == {'a-12'}
    result = evidence(data)
    assert result['unmatched_works'] == []
    item, = result['rows'][0]['reconciliation']['daily_evidence']
    assert item['contract_id'] == FIRST and item['link_basis'] == 'explicit_number'
    assert links.set_link(PROJECT, FIRST, item['id'], CUT)['confirmed']


@pytest.mark.parametrize("width", [390, 1440])
def test_real_dropdown_contains_only_server_admitted_choices_and_counts_messages(width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import browser_page, register as page_register
    data = page_register()
    own, foreign = copy.deepcopy(data['rows'])
    own.update(contractor='ООО «Подрядчик А»', contract='А-01', subject='Монолит',
               scope=['Корпус 1'], physical_items=[])
    another = {**copy.deepcopy(own), 'id': OTHER, 'contract': 'А-02'}
    foreign.update(contractor='Другой подрядчик', contract='Ч-01', scope=['Корпус 1'])
    data['rows'] = [foreign, own, another]
    report(party='Подрядчик А', twice=True)
    report(party='Подрядчик А', day='2026-10-15')
    resolved = evidence(data)
    assert len(resolved['unmatched_works']) == 2
    with browser_page(width) as (page, responses, errors):
        responses.data = resolved
        page.locator('#contractsTab').click()
        pending = page.locator('#contractsUnmatched')
        expect(pending).to_contain_text('Записи о работах: уточнить договор (2)')
        pending.locator('summary').first.click()
        expect(pending).to_contain_text('Одинаковая работа за разные дни считается отдельно')
        for choice in pending.locator('select').all():
            options = choice.locator('option[value]:not([value=""])')
            assert options.evaluate_all('(items)=>items.map(x=>x.value)') == [FIRST, OTHER]
            assert all('Ч-01' not in text for text in options.all_text_contents())
            assert all('Подрядчик А' in text for text in options.all_text_contents())
        expect(pending).not_to_contain_text('Предложено соответствие')
        expect(pending).to_contain_text('Подходит несколько договоров подрядчика')
        assert responses.links == []
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors
        page.screenshot(path=f'/tmp/plato1042-choices-{width}.png', full_page=True)


@pytest.mark.parametrize('width', [390, 1440])
def test_real_proposal_names_the_contract_and_no_candidates_means_no_fake_action(width):
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import CONTRACT, MARKER, browser_page
    with browser_page(width) as (page, responses, errors):
        proposed = responses.data['rows'][0]['reconciliation']['daily_evidence'][0]
        proposed.update(text=MARKER, selectable_contract_ids=[CONTRACT],
                        suggested_contract_id=CONTRACT)
        missing = copy.deepcopy(proposed)
        missing.update(id='no-choice', contractor='Неизвестный подрядчик',
                       selectable_contract_ids=[], suggested_contract_id='',
                       match_reason='Договор этого подрядчика в накопительных не найден.')
        responses.data['unmatched_works'] = [copy.deepcopy(proposed), missing]
        page.locator('#contractsTab').click()
        pending = page.locator('#contractsUnmatched')
        pending.locator('summary').first.click()
        expect(pending).to_contain_text('Предложен договор: Подрядчик Учебный проект · Д-01')
        expect(pending).to_contain_text('Договор этого подрядчика в накопительных не найден')
        assert pending.locator('select').count() == 1
        assert pending.locator('.evidence-confirm').count() == 1
        assert pending.locator('img,script').count() == 0
        assert not page.evaluate('window.untrustedRan===true')
        assert responses.links == []
        assert not errors
        page.screenshot(path=f'/tmp/plato1042-proposal-{width}.png', full_page=True)


def test_real_legacy_warning_keeps_revocation_without_offering_the_foreign_contract():
    from playwright.sync_api import expect
    from test_monitor_cumulative_controls import CONTRACT, OTHER as foreign_id, browser_page
    with browser_page() as (page, responses, errors):
        item = copy.deepcopy(responses.data['rows'][0]['reconciliation']['daily_evidence'][0])
        item.update(match_status='ambiguous', contract_id='', manual_review_required=True,
                    manual_contract_id=foreign_id,
                    manual_review_reason='Договор относится к другому подрядчику.',
                    selectable_contract_ids=[CONTRACT], suggested_contract_id=CONTRACT)
        responses.data['unmatched_works'] = [item]
        page.locator('#contractsTab').click()
        pending = page.locator('#contractsUnmatched')
        pending.locator('summary').first.click()
        expect(pending).to_contain_text('Прежняя ручная связь с договором Другой подрядчик · Д-02 требует проверки')
        expect(pending).to_contain_text('Подходит договор: Подрядчик Учебный проект · Д-01')
        assert pending.locator('option[value="'+foreign_id+'"]').count() == 0
        expect(pending.locator('.evidence-remove')).to_have_text('Снять прежнюю связь')
        assert responses.links == []
        with page.expect_response('**/monitor/contracts/result') as completed:
            pending.locator('.evidence-remove').click()
        completed.value.finished()
        assert len(responses.links) == 1
        assert responses.links[0]['contract_id'] == foreign_id
        assert responses.links[0]['confirmed'] is False
        assert not errors
