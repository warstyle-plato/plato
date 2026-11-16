"""The actual modal chooses a fictional raw card before requesting documents."""
from __future__ import annotations

import copy

from playwright.sync_api import expect

from test_monitor_cumulative_controls import CONTRACT, OTHER, browser_page


def test_logical_row_chooses_second_raw_card_and_closes_by_escape_and_button():
    logical_id = "c" * 64
    with browser_page(390) as (page, responses, errors):
        first = copy.deepcopy(responses.data["rows"][0])
        first.update(contract="SOURCE-A", contractor="Учебный подрядчик А", amount=1000,
                     completed=100, completion_ratio=.1, remaining=900, source_kind="cumulative",
                     subject="Учебные работы А", warnings=[], reconciliation={})
        second = copy.deepcopy(first)
        second.update(id=OTHER, contract="SOURCE-B", contractor="Учебный подрядчик Б", amount=2000,
                      completed=200, remaining=1800, subject="Учебные работы Б")
        state = {"status": "confirmed", "logical_id": logical_id, "member_ids": [CONTRACT, OTHER]}
        responses.data.update(rows=[{
            "id": logical_id, "contract": "Учебный общий номер", "source_kind": "logical_ownership",
            "logical_ownership": {"resolution_status": "confirmed"}, "raw_member_ids": [CONTRACT, OTHER],
            "raw_observations": [first, second], "amount": None, "completed": None,
            "completion_ratio": None, "remaining": None, "physical_items": [], "warnings": [],
        }], raw_rows=[first, second], unmatched_works=[], logical_ownership={
            "states": {CONTRACT: state, OTHER: state}, "logical_contracts": 1,
            "raw_source_cards": 2, "financial_acceptance": False})
        requested = []

        def documents(route):
            body = route.request.post_data_json
            requested.append(body["contract_id"])
            route.fulfill(json={"pending": False, "ok": True, "contract_id": body["contract_id"],
                "documents": [], "removed": [], "plan": {"editions": []},
                "fact": {"note": "Учебных документов нет."},
                "control": {"total": None, "forecast": None, "note": "Учебных документов нет."},
                "comparison": {"cut": responses.data["cut"], "lines": [], "total": None,
                               "reason": "Учебных документов нет.", "coverage": {}}})

        page.route("**/monitor/contracts/documents", documents)
        page.locator("#contractsTab").click()
        opener = page.locator(f'tr[data-contract-id="{logical_id}"] .contract-open')
        opener.click()
        dialog = page.locator("#contractDialog")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("heading", name="Выберите исходную карточку договора")).to_be_visible()
        expect(dialog.locator("[data-raw-contract]")).to_have_count(2)
        assert dialog.locator("[data-raw-contract]").evaluate_all("""buttons => {
            const viewport=document.getElementById('contractDialogScroll').getBoundingClientRect();
            return buttons.every(button => {
                const box=button.getBoundingClientRect();
                return box.width>0 && box.height>0
                    && box.left>=Math.max(0,viewport.left)-1 && box.right<=Math.min(innerWidth,viewport.right)+1
                    && box.top>=Math.max(0,viewport.top)-1 && box.bottom<=Math.min(innerHeight,viewport.bottom)+1;
            });
        }""")
        expect(dialog.locator("[data-raw-contract][aria-current]")).to_have_count(0)
        expect(dialog).to_contain_text("Финансовый источник, срок и общий прогноз между ними не выбраны")
        expect(dialog).not_to_contain_text("₽")
        expect(dialog.locator("#contractCardSummary, #contractFinancialSources, #contractPhysicalSources, #contractDocumentList")).to_have_count(0)
        expect(page.locator("#contractDialogDocuments")).to_be_disabled()
        assert requested == []

        dialog.locator(f'[data-raw-contract="{OTHER}"]').click()
        expect(page.locator("#contractDialogTitle")).to_contain_text("SOURCE-B")
        expect(dialog.locator(f'[data-raw-contract="{OTHER}"][aria-current="true"]')).to_be_visible()
        expect(dialog.locator('#contractCardSummary [data-label="Сумма договора"]')).to_contain_text("2\u00a0000 ₽")
        expect(page.locator("#contractDocumentsMsg")).to_contain_text("Документы этого договора ещё не загружены")
        assert requested == [OTHER]
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(opener).to_be_focused()

        opener.click()
        expect(dialog.get_by_role("heading", name="Выберите исходную карточку договора")).to_be_visible()
        expect(dialog).not_to_contain_text("₽")
        assert requested == [OTHER]
        page.locator("#contractDialogClose").click()
        expect(dialog).to_be_hidden()
        expect(opener).to_be_focused()
        assert requested == [OTHER]
        assert not [path for path, _, _ in responses.calls
                    if path.startswith("/monitor/contracts/")
                    and path not in {"/monitor/contracts/build", "/monitor/contracts/result"}]
        assert errors == []
