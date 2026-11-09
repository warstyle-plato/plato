"""A legal-form suffix is the same exact party, without fuzzy name merging."""
from __future__ import annotations

import copy

import pytest

import developaid_monitor_contract_links as links
import developaid_monitor_daily as daily
from test_monitor_contract_links import (
    CUT, FIRST, PROJECT, SECOND, evidence, install_register, isolated, register, report,
)


@pytest.mark.parametrize("left,right", [
    ("НУР", "НУР ООО"),
    ("НУР ООО", 'ООО «НУР»'),
    ('Общество с ограниченной ответственностью «НУР»', "НУР ООО"),
    ("НУР общество с ограниченной ответственностью", 'ООО «НУР»'),
    ("АО Север", "Север АО"),
    ("ОАО Север", "Север ОАО"),
    ("Иванов Иван Иванович ИП", "ИП Иванов Иван Иванович"),
    ('ООО «НУР ИП»', 'ООО «НУР ИП»'),
])
def test_legal_form_can_precede_or_follow_the_exact_name(left, right):
    assert links._same_party_exact(left, right)
    assert links._same_party_exact(right, left)


@pytest.mark.parametrize("left,right", [
    ("НУР ООО", "НУР ИП"),
    ("НУР ООО", "АО НУР"),
    ("НУР ООО", "НУР Строй ООО"),
    ("НУР ООО Сервис", "НУР Сервис ООО"),
    ("ООО НУР ИП", "ООО НУР"),
    ("ОАО НУР ООО", "ООО ОАО НУР"),
    ('ООО «НУР ООО»', 'ООО «НУР»'),
    ("ООО", "ООО"),
    ("", "НУР ООО"),
])
def test_moved_form_does_not_merge_other_names_or_legal_entities(left, right):
    assert not links._same_party_exact(left, right)
    assert not links._same_party_exact(right, left)


@pytest.mark.parametrize("source_name,contract_name", [
    ("НУР", "НУР ООО"),
    ("НУР ООО", 'ООО «НУР»'),
    ('ООО «НУР»', "НУР ООО"),
])
def test_daily_report_resolves_the_one_current_contract_with_suffix(source_name, contract_name):
    data = register()
    data["rows"][0]["contractor"] = contract_name
    report(party=source_name)
    before = copy.deepcopy(data)
    result = evidence(data)
    assert result["unmatched_works"] == []
    item, = result["rows"][0]["reconciliation"]["daily_evidence"]
    assert item["contract_id"] == FIRST
    assert item["link_basis"] == "exact_party"
    assert item["reported_contractor"] == source_name
    assert item["selectable_contract_ids"] == [FIRST]
    assert data == before
    assert not links._path(PROJECT).exists()


def test_suffix_multiple_contracts_stay_ambiguous_manual_and_report_use_the_same_party(monkeypatch):
    data = register(two=True)
    for row in data["rows"]:
        row["contractor"] = 'ООО «НУР»'
    foreign = {**copy.deepcopy(data["rows"][0]), "id": "c" * 64,
               "contractor": "НУР ИП", "contract": "ИП-01"}
    data["rows"].append(foreign)
    install_register(monkeypatch, data)
    report(party="НУР ООО")
    unresolved, = evidence(data)["unmatched_works"]
    assert unresolved["match_status"] == "ambiguous"
    assert unresolved["selectable_contract_ids"] == [FIRST, SECOND]
    assert unresolved["suggested_contract_id"] == ""
    with pytest.raises(links.LinkProblem, match="подрядчика"):
        links.set_link(PROJECT, foreign["id"], unresolved["id"], CUT)
    links.set_link(PROJECT, SECOND, unresolved["id"], CUT)
    confirmed = evidence(data)
    assert confirmed["unmatched_works"] == []
    groups = [{"contractor": "НУР", "lines": [
        {"line": "Корпус 1 бетонирование", "days": ["2026-10-14"]}]}]
    line = links.enrich_report_works(
        PROJECT, groups, "2026-10-12", CUT, context={"register": confirmed},
    )[0]["lines"][0]
    assert [item["id"] for item in line["contract_links"]] == [SECOND]
    assert line["contract_links"][0]["completion_ratio"] == .25
    links.set_link(PROJECT, SECOND, unresolved["id"], CUT, confirmed=False)
    assert evidence(data)["unmatched_works"][0]["match_status"] == "ambiguous"


def test_inline_suffix_and_its_continuation_reach_contracts_from_the_stored_daily_report():
    data = register()
    data["rows"][0]["contractor"] = 'ООО «НУР»'
    daily.store_daily_report(PROJECT, "По работам:\nНУР ООО — Корпус 1 бетонирование\n"
                             "Корпус 1 армирование", "2026-10-14")
    result = evidence(data)
    assert result["unmatched_works"] == []
    items = result["rows"][0]["reconciliation"]["daily_evidence"]
    assert [item["text"] for item in items] == ["Корпус 1 бетонирование", "Корпус 1 армирование"]
    assert all(item["contract_id"] == FIRST and item["link_basis"] == "exact_party" for item in items)
    assert all(item["reported_contractor"] == "НУР ООО" for item in items)
