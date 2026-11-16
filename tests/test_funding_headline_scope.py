"""A whole-project diagnostic gap cannot become a bank-only or accepted total."""
import copy
import datetime as dt

import pytest

import developaid_admin_expenses_cash as cash
import developaid_management_report as report
import developaid_monitor_dashboard as dashboard
from test_funding_source_dates import source_case
from test_the_approved_budget_says_what_it_is_made_of import _read, _finmodel, SMETA, PAID


@pytest.mark.parametrize("cash_model", [{}, {"remaining_need": None, "coverage": {"known_count": 0}}])
def test_whole_budget_with_ahr_and_no_observations_has_no_known_headline(tmp_path, monkeypatch, cash_model):
    built, _ = source_case(tmp_path, monkeypatch)
    limit = built["funding"]["limit"]
    canonical = limit["own_money"]["reconciliation"]
    assert canonical["basis"] == "approved_budget"
    assert canonical["budget"] == 1_440_000  # Includes the same 40,000 AHR; never add it twice.
    assert limit["own_money"]["admin"]["total"] == 40_000
    assert canonical["calculated_additional"] is not None
    assert canonical["confirmed_additional"] is None and canonical["primary_source_gate"] == "BLOCKED"
    before = copy.deepcopy(limit)
    built["admin_expenses_cash"] = copy.deepcopy(cash_model)
    tile, = [tile for tile in report.tiles(built) if tile.get("group") == "additional_funding"]
    assert tile["label"] == "Потребность в допфинансировании"
    assert tile["value"] == "нет данных" and tile["tone"] == "missing"
    assert "без АХР" not in tile["note"].lower()
    assert "по смете банка" not in tile["note"].lower()
    assert "сверка первичных источников не завершена" in tile["note"]
    summary = dashboard.funding_cash_summary(limit, cash_model, report._rub)
    assert summary["amount"] is None and summary["scope"] == "unconfirmed_total"
    finding, = [f for f in report.findings(built) if f["topic"] == "Финансирование"]
    assert finding["tone"] == "missing" and "общая потребность пока не определена" in finding["text"]
    html = report._funding_html(built)
    row = next(row for row in canonical["display_rows"] if row["key"] == "calculated_additional")
    assert f"<td>{row['label']}</td><td>{report._rub(row['value'])}</td>" in html
    assert limit == before


def test_unaccepted_confirmed_field_does_not_bypass_the_source_gate():
    funding = {"known": True, "own_money": {"need": 250, "reconciliation": {
        "basis": "approved_budget", "calculated_additional": 250,
        "confirmed_additional": 250, "primary_source_gate": "BLOCKED",
        "financial_acceptance_performed": False}}}
    assert dashboard.funding_cash_summary(funding, {}, cash.money)["amount"] is None


def test_explicit_bank_chapter_basis_keeps_its_separate_native_component():
    funding = {"known": True, "approved": 1_000, "need_basis": "budget",
               "funding_scope": {"basis": "bank_chapters", "chapters": ["2", "3"]},
               "deficit_ladder": {"total": 250}}
    model = {key: None for key, _ in cash.FIELDS}
    model["remaining_need"] = None
    before = copy.deepcopy((funding, model))
    summary = dashboard.funding_cash_summary(funding, model, cash.money)
    assert summary["scope"] == "bank_only" and summary["amount"] == 250
    html = cash.render_funding(summary, cash.render(model))
    assert "Потребность по смете банка" in html
    assert "Потребность в допфинансировании</small>" not in html
    assert (funding, model) == before


@pytest.mark.parametrize("money_chapter,explicit_included", [("2", 10_000), ("3", 20_000)])
def test_reallocated_money_does_not_inherit_a_dictionary_based_ahr_split(
        tmp_path, monkeypatch, money_chapter, explicit_included):
    import developaid_finance_money_bridge as bridge
    admin = {"total": 40_000., "fact": 20_000., "plan": 20_000.,
             "monthly": {"2026-11-01": 20_000.}}
    # Isolate the reader boundary after an explicit monetary extractor result;
    # a coincident chapter or amount does not qualify the dictionary metadata.
    monkeypatch.setattr(bridge, "admin_allocations", lambda *a, **kw: {"2.4.1": {
        "by_chapter": {money_chapter: copy.deepcopy(admin)}, "proofs": [], "parts": [],
        "allocation_known": True, "reasons": [], "basis": "synthetic_explicit_money"}})
    model = _read(tmp_path, _finmodel())
    flows = model["chapter_flow"]
    assert flows[money_chapter]["sections"]["2.4"] == 40_000

    def own(source_flows):
        return dashboard._own_money(model["budget_composition"], SMETA, PAID,
            ["1", "2", "3"], dt.date(2026, 10, 20),
            paid_since={"2": 610_000, "3": 0}, chapter_flow=source_flows)

    qualified = copy.deepcopy(flows)
    for flow in qualified.values():
        flow["admin_expenses"] = {"total": 0., "fact": 0., "plan": 0., "monthly": {}}
    qualified[money_chapter]["admin_expenses"] = copy.deepcopy(admin)
    control = own(qualified)
    assert control["admin_expenses_included"] == explicit_included
    assert control["need_without_admin_expenses"] == control["need"] - explicit_included
    observed = own(flows)
    assert observed["reconciliation"] == control["reconciliation"]
    assert "admin_expenses_included" not in observed
    assert "need_without_admin_expenses" not in observed
