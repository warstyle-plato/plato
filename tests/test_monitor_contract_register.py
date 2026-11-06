"""Contract money, scope and deadlines must keep their source boundaries."""
from __future__ import annotations

import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import json

import openpyxl
import pytest

import developaid_monitor as monitor
import developaid_monitor_contracts as contracts


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    monkeypatch.setattr(contracts, "_archive", lambda project, cut: None)
    return "Synthetic site"


def rss(project, rows, day="2026-04-01", headers=None):
    folder = monitor._project_dir(project) / "estimate"
    folder.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Реестр договоров"
    for column, text in (headers or {}).items():
        ws.cell(6, column, text)
    for i, row in enumerate(rows, 9):
        for field, index in {"contractor": 2, "contract": 3, "contract_date": 4,
                             "subject": 5, "estimate_code": 6, "article_name": 7,
                             "amount": 8, "paid": 9, "completed": 12,
                             "deadline": 13}.items():
            if field in row:
                ws.cell(i, index, row[field])
    wb.save(folder / f"{day}.xlsx")
    wb.close()


def entry(**kw):
    return {"contractor": "Builder A", "contract": "№ C-12/7", "amount": 1000,
            "completed": 250, "estimate_code": "2.1", **kw}


def archive(monkeypatch, *, summaries=(), ledgers=(), day="2026-04-01"):
    snapshot = {"snapshot_id": "a"*64, "taken_at": day,
                "summary_contracts": list(summaries), "ledgers": list(ledgers)}
    monkeypatch.setattr(contracts, "_archive", lambda project, cut: snapshot)


def summary(**kw):
    return {"customer": "Developer A", "contractor": "Builder A", "contract": "C-12/7",
            "amount": 1000, "amount_date": "2026-03-01",
            "acts": [{"number": "1", "date": "2026-03-12", "amount": 200}], **kw}


def test_contract_completion_is_accepted_money_not_paid(project):
    rss(project, [entry(paid=800)])
    row, = contracts.build(project, "2026-04-02")["rows"]
    assert (row["amount"], row["completed"], row["completion_ratio"], row["remaining"]) == (1000, 250, .25, 750)
    assert row["deadline"] is None
    assert row["physical_items"] == []
    assert "не оплата" in row["performance_basis"]


@pytest.mark.parametrize("bad", [None, "#REF!", "=1+2", float("inf"), "not a number"])
def test_missing_or_invalid_amount_never_becomes_zero(project, bad):
    # Nonfinite values cannot be written by Excel; the production numeric
    # predicate also rejects them directly.
    if bad == float("inf"):
        assert contracts._number(bad) is None
        bad = "inf"
    rss(project, [entry(amount=bad)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None
    assert row["completion_ratio"] is None


def test_missing_completion_is_unknown_but_explicit_zero_is_zero(project):
    rss(project, [entry(completed=None), entry(contract="C-13", completed=0)])
    rows = {r["contract"]: r for r in contracts.build(project)["rows"]}
    assert rows["№ C-12/7"]["completed"] is None
    assert rows["№ C-12/7"]["completion_ratio"] is None
    assert rows["C-13"]["completed"] == 0
    assert rows["C-13"]["completion_ratio"] == 0


def test_identical_rss_duplicate_does_not_double_money(project):
    rss(project, [entry(), entry()])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1000
    assert row["completed"] == 250


def test_article_split_is_not_automatically_a_contract_total(project):
    rss(project, [entry(), entry(estimate_code="2.2", amount=1000, completed=300)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None
    assert row["completed"] is None
    assert any("несколько строк" in w for w in row["warnings"])


def test_explicit_contract_total_can_resolve_the_article_split(project):
    rss(project, [entry(amount=300), entry(amount=700, estimate_code="2.2"),
                  entry(subject="Итого по договору", estimate_code="", amount=1000, completed=400)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1000
    assert row["completed"] == 400


def test_total_row_and_another_contractor_are_not_part_of_this_contract(project):
    rss(project, [entry(), entry(contractor="ИТОГО", contract="", amount=9000),
                  entry(contractor="Builder B", amount=3000)])
    rows = contracts.build(project)["rows"]
    assert len(rows) == 2
    assert len({r["id"] for r in rows}) == 2


def test_archive_summary_deduplicates_acts_and_filters_future_dates(project, monkeypatch):
    acts = [{"number": "1", "date": "2026-03-12", "amount": 200},
            {"number": "1", "date": "2026-03-12", "amount": 200},
            {"number": "2", "date": "2026-04-20", "amount": 800}]
    archive(monkeypatch, summaries=[summary(acts=acts)])
    row, = contracts.build(project, "2026-04-02")["rows"]
    assert row["completed"] == 200
    assert row["completion_ratio"] == .2


@pytest.mark.parametrize("acts", [
    [{"number": "1", "date": None, "amount": 200}],
    [{"number": "1", "date": "2026-03-12", "amount": None}],
    [{"number": "1", "date": "2026-03-12", "amount": 200},
     {"number": "1", "date": "2026-03-12", "amount": 300}],
])
def test_unresolved_acts_do_not_create_a_partial_false_percent(project, monkeypatch, acts):
    archive(monkeypatch, summaries=[summary(acts=acts)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1000
    assert row["completed"] is None
    assert row["completion_ratio"] is None


def test_amount_versions_are_not_summed(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=800, amount_date="2026-02-01"),
                                   summary(amount=1200, amount_date="2026-03-01")])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1200
    assert row["completed"] == 200  # Repeated act in both versions is one act.


def test_explicit_amendment_versions_respect_the_cut(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=1800, amount_date="2026-07-01",
        amount_versions=[{"amount": 800, "date": "2026-01-01"},
                         {"amount": 1200, "date": "2026-03-01"},
                         {"amount": 1800, "date": "2026-07-01"}])])
    row, = contracts.build(project, "2026-04-01")["rows"]
    assert row["amount"] == 1200


def test_conflicting_undated_contract_amounts_stay_unknown(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=800, amount_date=None),
                                   summary(amount=1200, amount_date=None)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None


def test_yearly_ledger_amount_is_not_full_contract_and_supply_not_installation(project, monkeypatch):
    ledger = {**summary(), "contract_amount": 9000, "amount_scope": "year_or_sheet", "period_year": 2026,
              "items": [{"name": "Curtain wall frame", "scope": "Building 2",
                         "unit": "м²", "plan_quantity": 100, "completed_quantity": 20,
                         "material_quantity": 80, "planned_amount": 9000, "completed_amount": 6000,
                         "periods": [{"date_start": "2026-03-01", "date_end": "2026-03-31",
                                      "quantity": 20, "material_quantity": 80, "amount": 6000}],
                         "source": {"filename": "synthetic.xlsx", "sheet": "1", "row": 30}}]}
    archive(monkeypatch, ledgers=[ledger])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None
    assert row["completed"] is None
    physical, = row["physical_items"]
    assert physical["completion_ratio"] == .2
    assert physical["material_quantity"] == 80
    assert row["scope"] == ["Building 2"]


def test_overplan_is_visible_and_does_not_close_whole_contract(project, monkeypatch):
    ledger = {**summary(), "items": [{"name": "Slab", "plan_quantity": 50,
                                      "completed_quantity": 90, "unit": "м³",
                                      "periods": [{"date_start": "2026-03-01", "date_end": "2026-03-31",
                                                   "quantity": 90}]}]}
    archive(monkeypatch, ledgers=[ledger])
    row, = contracts.build(project)["rows"]
    physical, = row["physical_items"]
    assert physical["completion_ratio"] == 1.8
    assert any("превышает" in w for w in physical["warnings"])
    assert row["completion_ratio"] is None


def test_unknown_customer_does_not_join_another_customer(project, monkeypatch):
    rss(project, [entry()])
    archive(monkeypatch, summaries=[summary()])
    rows = contracts.build(project)["rows"]
    assert len(rows) == 2
    assert len({r["id"] for r in rows}) == 2
    assert all(any("заказчиков" in w for w in r["warnings"]) for r in rows)


def test_punctuation_and_contract_dates_disambiguate_identity(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(contract="12/3"), summary(contract="123"),
                                   summary(contract="Same", contract_date="2025-01-01"),
                                   summary(contract="Same", contract_date="2026-01-01")])
    rows = contracts.build(project)["rows"]
    assert len(rows) == 4
    assert len({r["id"] for r in rows}) == 4


def test_stable_identity_survives_snapshot_and_quantity_changes(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(contract_date="2024-01-01")])
    before, = contracts.build(project)["rows"]
    archive(monkeypatch, summaries=[summary(amount=1400, contract_date="2024-01-01")], day="2026-05-01")
    after, = contracts.build(project)["rows"]
    assert before["id"] == after["id"]


def test_missing_date_refinement_requires_fresh_manual_confirmation(project, monkeypatch):
    archive(monkeypatch, summaries=[summary()])
    before, = contracts.build(project)["rows"]
    archive(monkeypatch, summaries=[summary(contract_date="2024-01-01")])
    after, = contracts.build(project)["rows"]
    assert before["id"] != after["id"]


def test_even_identically_named_contracts_are_scoped_to_the_project(project, monkeypatch):
    archive(monkeypatch, summaries=[summary()])
    first, = contracts.build(project)["rows"]
    second, = contracts.build("Other site")["rows"]
    assert first["id"] != second["id"]


def test_internal_party_punctuation_is_not_a_fuzzy_join(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(contractor="Builder D'Art"),
                                   summary(contractor="Builder DArt")])
    assert len(contracts.build(project)["rows"]) == 2


def test_future_archive_cannot_enter_a_past_view_even_if_provider_returns_it(project, monkeypatch):
    archive(monkeypatch, summaries=[summary()], day="2026-07-01")
    view = contracts.build(project, "2026-04-01")
    assert view["rows"] == []
    assert any("позже среза" in warning for warning in view["warnings"])


def test_reissued_contract_in_a_separate_snapshot_does_not_inherit_a_term(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(contract_date="2025-01-01")])
    old, = contracts.build(project)["rows"]
    contracts.set_term(project, old["id"], "2027-05-01", "Only the original contract")
    archive(monkeypatch, summaries=[summary(contract_date="2026-01-01")], day="2026-05-01")
    new, = contracts.build(project)["rows"]
    assert new["id"] != old["id"]
    assert new["deadline"] is None
    assert new["manual_deadline_reference"] is None


def test_latest_ambiguous_amendment_invalidates_the_old_full_price(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=None, amount_scope="ambiguous_amendment",
        amount_date="2026-02-01", amount_versions=[
            {"amount": 1000, "date": "2026-01-01", "scope": "full_contract"},
            {"amount": None, "stated_amount": 200, "date": "2026-02-01", "scope": "ambiguous_amendment"}])])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None  # Neither 1000, 200 nor 1200 is supported.
    assert row["completion_ratio"] is None
    assert row["remaining"] is None
    assert any("допсоглашения" in warning for warning in row["warnings"])


def test_undated_amendment_cannot_resurrect_an_old_dated_price(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=None, amount_scope="ambiguous_amendment",
        amount_versions=[{"amount": 1000, "date": "2026-01-01", "scope": "full_contract"},
                         {"amount": None, "stated_amount": 200, "date": None,
                          "scope": "ambiguous_amendment"}])])
    row, = contracts.build(project)["rows"]
    assert row["amount"] is None


def test_explicit_new_full_price_after_an_amendment_is_usable(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount_versions=[
        {"amount": 1000, "date": "2026-01-01", "scope": "full_contract"},
        {"amount": None, "stated_amount": 200, "date": "2026-02-01", "scope": "ambiguous_amendment"},
        {"amount": 1300, "date": "2026-03-01", "scope": "full_contract"}])])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1300
    assert row["completion_ratio"] == pytest.approx(200/1300)


def test_different_explicit_vat_bases_do_not_produce_ratio_or_remaining(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=1200, amount_basis="with_vat", acts=[
        {"number": "1", "date": "2026-03-12", "amount": 1000, "amount_basis": "without_vat"}])])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1200 and row["completed"] == 1000
    assert row["amount_basis"] == "with_vat" and row["completed_basis"] == "without_vat"
    assert row["completion_ratio"] is None and row["remaining"] is None
    assert row["monetary_comparable"] is False
    assert any("НДС" in warning for warning in row["warnings"])


def test_matching_explicit_vat_basis_keeps_the_source_ratio(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=1200, amount_basis="with_vat", acts=[
        {"number": "1", "date": "2026-03-12", "amount": 600, "amount_basis": "with_vat"}])])
    row, = contracts.build(project)["rows"]
    assert row["completion_ratio"] == .5 and row["remaining"] == 600


def test_different_vat_bases_inside_acts_are_not_summed(project, monkeypatch):
    archive(monkeypatch, summaries=[summary(amount=1200, amount_basis="with_vat", acts=[
        {"number": "1", "date": "2026-03-12", "amount": 100, "amount_basis": "with_vat"},
        {"number": "2", "date": "2026-03-13", "amount": 100, "amount_basis": "without_vat"}])])
    row, = contracts.build(project)["rows"]
    assert row["completed"] is None and row["completion_ratio"] is None


def test_explicit_rss_vat_mismatch_is_also_not_a_comparable_pair(project):
    rss(project, [entry(amount=1200, completed=1000)],
        headers={8: "Сумма договора с НДС", 12: "Выполнено без НДС"})
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1200 and row["completed"] == 1000
    assert row["completion_ratio"] is None and row["remaining"] is None


def physical_view(monkeypatch, project, item, cut="2026-03-15"):
    ledger = {"contractor": "Builder A", "customer": "Developer A", "contract": "C-10",
              "contract_date": "2026-01-01", "period_year": 2026, "items": [item]}
    archive(monkeypatch, ledgers=[ledger], day="2026-03-01")
    return contracts.build(project, cut)["rows"][0]["physical_items"][0]


def test_future_physical_period_and_annual_total_do_not_enter_the_cut(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "unit": "м³", "plan_quantity": 100, "completed_quantity": 100,
        "completed_amount": 1000, "periods": [
            {"quantity": 10, "amount": 100, "date_start": "2026-02-01", "date_end": "2026-02-28"},
            {"quantity": 90, "amount": 900, "date_start": "2026-04-01", "date_end": "2026-04-30"}]})
    assert item["completed_quantity"] == 10 and item["completion_ratio"] == .1
    assert item["completed_amount"] == 100
    assert item["reported_completed_quantity"] is None
    assert len(item["periods"]) == 1
    assert item["quantity_date"] == "2026-02-28" and item["snapshot_date"] == "2026-03-01"
    assert item["quantity_cut"] == "2026-03-15"


def test_undated_quantity_is_only_a_reference_not_dated_by_the_archive(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "unit": "м³", "plan_quantity": 100, "completed_quantity": 40,
        "periods": [{"quantity": 40, "label": "КС-2 №1"}]})
    assert item["completed_quantity"] is None and item["completion_ratio"] is None
    assert item["reported_completed_quantity"] == 40
    assert item["reported_completion_ratio"] == .4
    assert item["quantity_date"] is None and item["snapshot_date"] == "2026-03-01"
    assert "без дат" in item["quantity_basis"]


def test_mixed_dated_and_undated_quantities_do_not_make_a_full_asof_total(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "plan_quantity": 100, "completed_quantity": 40, "periods": [
            {"quantity": 10, "date_start": "2026-02-01", "date_end": "2026-02-28"},
            {"quantity": 30, "label": "Unknown date"}]})
    assert item["completed_quantity"] is None and item["completion_ratio"] is None
    assert item["dated_completed_quantity"] == 10
    assert item["reported_completed_quantity"] == 40


def test_overlapping_period_is_not_prorated_across_the_cut(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "plan_quantity": 100, "completed_quantity": 40, "periods": [
            {"quantity": 40, "date_start": "2026-03-01", "date_end": "2026-03-31"}]})
    assert item["completed_quantity"] is None and item["completion_ratio"] is None
    assert item["periods"] == [] and item["reported_completed_quantity"] is None
    assert "пересекает" in item["quantity_basis"]


def test_periods_must_reconcile_with_the_cumulative_quantity(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "plan_quantity": 100, "completed_quantity": 50, "periods": [
            {"quantity": 40, "date_start": "2026-02-01", "date_end": "2026-02-28"}]})
    assert item["completed_quantity"] is None and item["completion_ratio"] is None
    assert item["dated_completed_quantity"] == 40
    assert "не сходится" in item["quantity_basis"]


def test_blank_future_slots_do_not_invalidate_a_reconciled_past_quantity(project, monkeypatch):
    item = physical_view(monkeypatch, project, {
        "name": "Slab", "plan_quantity": 100, "completed_quantity": 10, "periods": [
            {"quantity": 10, "date_start": "2026-02-01", "date_end": "2026-02-28"},
            {"quantity": None, "date_start": "2026-04-01", "date_end": "2026-04-30"},
            {"quantity": None, "label": "Unused slot"}]})
    assert item["completed_quantity"] == 10 and item["completion_ratio"] == .1


def test_later_manual_deadline_remains_a_current_reference_not_historical_fact(project):
    rss(project, [entry(deadline="2026-09-01")], headers={13: "Срок исполнения"})
    row, = contracts.build(project)["rows"]
    path = monitor._project_dir(project) / "cumulative_terms.json"
    path.write_text(json.dumps({row["id"]: {"deadline": "2027-01-01", "note": "Later decision",
                                          "updated_at": "2026-06-01T10:00:00+00:00"}}))
    old, = contracts.build(project, "2026-04-15")["rows"]
    assert old["deadline"] == "2026-09-01"
    assert old["manual_deadline_reference"]["deadline"] == "2027-01-01"
    assert old["manual_deadline_reference"]["updated_at"].startswith("2026-06-01")
    assert old["manual_deadline_reference"]["applicable_to_cut"] is False
    assert any("позже даты среза" in warning for warning in old["warnings"])


def test_rss_is_primary_but_conflicting_summary_is_not_hidden(project, monkeypatch):
    rss(project, [entry()])
    archive(monkeypatch, summaries=[summary(customer="", amount=2000)])
    row, = contracts.build(project)["rows"]
    assert row["amount"] == 1000
    assert any("разные денежные" in w for w in row["warnings"])
    assert len(row["financial_sources"]) == 2


def test_deadline_must_be_explicit_not_contract_or_snapshot_date(project):
    rss(project, [entry(contract="C-1 от 01.03.2026", contract_date=dt.datetime(2026, 3, 1),
                        deadline=dt.datetime(2026, 9, 1))])
    row, = contracts.build(project)["rows"]
    assert row["contract_date"] == "2026-03-01"
    assert row["deadline"] is None  # An unlabeled adjacent date is not evidence.
    rss(project, [entry(deadline=dt.datetime(2026, 9, 1))], headers={13: "Срок исполнения"})
    row, = contracts.build(project)["rows"]
    assert row["deadline"] == "2026-09-01"


def test_manual_deadline_is_project_scoped_explicit_and_removable(project):
    rss(project, [entry()])
    row, = contracts.build(project)["rows"]
    saved = contracts.set_term(project, row["id"], "2027-02-01", "Дополнительное соглашение")
    assert saved["deadline"] == "2027-02-01"
    changed, = contracts.build(project)["rows"]
    assert changed["deadline"] == "2027-02-01"
    assert changed["deadline_source"]["label"] == "Указан вручную"
    assert changed["manual_deadline_reference"]["applicable_to_cut"] is True
    assert changed["amount"] == 1000
    path = monitor._project_dir(project) / "cumulative_terms.json"
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="не найден"):
        contracts.set_term("Other site", row["id"], "2027-02-01")
    contracts.set_term(project, row["id"], "")
    cleared, = contracts.build(project)["rows"]
    assert cleared["deadline"] is None


@pytest.mark.parametrize("bad", ["2026-02-30", "01.02.2026", "2026-01-01/../../x", "tomorrow"])
def test_bad_term_does_not_mutate_storage(project, bad):
    rss(project, [entry()])
    row, = contracts.build(project)["rows"]
    with pytest.raises(ValueError):
        contracts.set_term(project, row["id"], bad)
    assert not (monitor._project_dir(project) / "cumulative_terms.json").exists()


def test_concurrent_term_updates_preserve_both_contracts(project):
    rss(project, [entry(), entry(contract="C-2")])
    rows = contracts.build(project)["rows"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda row: contracts.set_term(
            project, row["id"], "2027-03-01", "Explicit deadline"), rows))
    assert len(results) == 2
    saved = json.loads((monitor._project_dir(project) / "cumulative_terms.json").read_text())
    assert set(saved) == {row["id"] for row in rows}


def test_invalid_identity_or_null_deadline_cannot_clear_an_existing_term(project):
    rss(project, [entry()])
    row, = contracts.build(project)["rows"]
    contracts.set_term(project, row["id"], "2027-03-01")
    with pytest.raises(contracts.ContractProblem):
        contracts.set_term(project, "../outside", "2027-03-01")
    with pytest.raises(contracts.ContractProblem):
        contracts.set_term(project, row["id"], None)
    assert contracts.build(project)["rows"][0]["deadline"] == "2027-03-01"


def test_future_rss_snapshot_is_not_used(project):
    rss(project, [entry()], day="2026-04-01")
    rss(project, [entry(amount=9000)], day="2026-07-01")
    row, = contracts.build(project, "2026-05-01")["rows"]
    assert row["amount"] == 1000
    assert row["source_date"] == "2026-04-01"


def test_view_without_sources_is_empty_not_zero_contracts_with_fabricated_values(project):
    view = contracts.build(project, "2026-04-01")
    assert view["rows"] == []
    assert view["source_date"] is None
    assert "total" not in view


@pytest.mark.parametrize("cut", ["2026-13-01", "2026-02-30", "May", "2026-01-01garbage"])
def test_invalid_cut_rejected(project, cut):
    with pytest.raises(ValueError):
        contracts.build(project, cut)
