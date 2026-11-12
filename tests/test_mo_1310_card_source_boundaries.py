"""A reviewed amendment text is not a proved commencement date; the deduction is a user-entered sum."""
import json

import pytest

import normatives_registry as registry

WARNING = "Уменьшение Ксу* в расчёте — по сумме компенсации, которую вписал пользователь"
COMMENCEMENT = "Настоящее постановление вступает в силу на следующий день после дня его официального опубликования."


def cards():
    return {row["id"]: row for row in registry._load_registry()
            if row["id"] in {"mo-1745-vri-kd", "mo-1310-vri-ksu"}}


def test_the_two_cards_end_in_a_proven_unknown_without_an_invented_commencement_date():
    for row in cards().values():
        assert row["status"] == "not_confirmed"
        assert row["unconfirmed_reason"] and row["to_confirm"]
        assert not registry.verdict_problems(row)
        text = json.dumps(row, ensure_ascii=False)
        assert "16.10.2026" not in text and "2026-10-16" not in text
        assert "опубликовано 15.10.2026" not in text
        assert row["affects"][0].startswith(WARNING)
    assert cards()["mo-1310-vri-ksu"]["adopted_at"] == "2026-10-15"
    assert cards()["mo-1310-vri-ksu"]["effective_from"] == ""


def test_the_amendment_card_quotes_the_rule_and_names_its_nonmonetary_changes():
    row = cards()["mo-1310-vri-ksu"]
    provisions = row["verification"]["provisions"]
    assert any(item.get("quote") == COMMENCEMENT for item in provisions)
    assert any(item.get("quote") == "Пункт 4.9 признать утратившим силу." for item in provisions)
    assert any("S — площадь квартир" in item.get("quote", "") for item in provisions)
    assert any("Срок действия банковской гарантии должен соответствовать сроку действия Соглашения."
               in item.get("quote", "") for item in provisions)
    assert all(item.get("quote") and "PDF" in item["point"] for item in provisions)


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("width", [390, 1440])
def test_reader_and_admin_see_how_the_deduction_is_counted_before_opening_and_the_exact_quote_after(monkeypatch, admin, width):
    from types import SimpleNamespace
    from playwright.sync_api import sync_playwright, expect
    from browser import chromium_or_skip
    from test_normatives_registry import _checker, _request

    rows = list(cards().values())
    monkeypatch.setattr(registry, "_merged_registry", lambda: rows)
    html = registry._page(_request("key=synthetic" if admin else ""),
                          SimpleNamespace(_is_admin_request=_checker(answer=admin)))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            tab = browser.new_page(viewport={"width": width, "height": 1000})
            tab.set_content(html)
            for name in ["1310-ПП — уменьшение платы за ВРИ (Ксу*)", "1745-ПП — плата за смену ВРИ в области"]:
                card = tab.locator(".ncard").filter(has=tab.get_by_role("heading", name=name, exact=True))
                expect(card.locator(".nhead .gist")).to_contain_text(WARNING)
                expect(card.locator(".nhead .gist")).to_be_visible()
            card = tab.locator(".ncard").filter(has=tab.get_by_role("heading", name="1310-ПП — уменьшение платы за ВРИ (Ксу*)", exact=True))
            card.locator(":scope > summary").click()
            proof = card.locator("details.history").filter(has_text=COMMENCEMENT)
            proof.locator(":scope > summary").click()
            expect(proof).to_contain_text(COMMENCEMENT)
            expect(proof.get_by_text(COMMENCEMENT, exact=False)).to_be_visible()
            if admin:
                expect(card.locator(".probe").filter(has_text="Не подтверждено:")).to_contain_text("официального опубликования")
        finally:
            browser.close()
