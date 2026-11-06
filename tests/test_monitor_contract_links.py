"""Legal work links are evidence, not attendance-based acceptance or money."""
from __future__ import annotations

import copy
import json
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import developaid_monitor as monitor
import developaid_monitor_contract_links as links
import developaid_monitor_daily as daily

PROJECT = "Synthetic Site"
CUT = "2026-10-18"
FIRST = "a" * 64
SECOND = "b" * 64


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")


def register(*, two=False, scope="Корпус 1"):
    rows = [{"id": FIRST, "contractor": 'ООО «Альфа»', "customer": "Заказчик",
             "contract": "A-12", "subject": "Монолит", "scope": [scope],
             "amount": 1000.0, "completed": 250.0, "completion_ratio": 0.25,
             "source_date": "2026-10-10", "physical_items": [{"name": "Бетонирование", "scope": scope}]}]
    if two:
        rows.append({**rows[0], "id": SECOND, "contract": "A-13"})
    return {"cut": CUT, "source_date": "2026-10-10", "rows": rows}


def report(line="Корпус 1 бетонирование", *, day="2026-10-14", party="Альфа", project=PROJECT,
           twice=False, attendance=False):
    folder = monitor._project_dir(project) / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    works = [] if attendance else [{"contractor": party, "line": line}]
    if twice:
        works *= 2
    (folder / f"{day}.json").write_text(json.dumps({"date": day, "parsed": {
        "contractors": [{"name": party, "workers": 5, "itr": 1}], "works": works}}, ensure_ascii=False))


def install_register(monkeypatch, data=None):
    data = data or register()
    monkeypatch.setitem(sys.modules, "developaid_monitor_contracts",
                        types.SimpleNamespace(build=lambda project, cut: copy.deepcopy(data)))
    return data


def evidence(data=None, **kwargs):
    return links.enrich(PROJECT, data or register(), CUT, **kwargs)


def test_a_unique_party_match_is_only_proposed_and_money_does_not_change():
    report()
    data = register()
    before = copy.deepcopy(data)
    result = evidence(data)
    found = result["unmatched_works"][0]
    assert found["match_status"] == "proposed"
    assert found["contract_id"] == ""
    assert found["candidate_contract_ids"] == [FIRST]
    assert found["source"] == {"kind": "daily_report", "date": "2026-10-14", "line_index": 1}
    assert data == before
    for key in ("amount", "completed", "completion_ratio"):
        assert result["rows"][0][key] == before["rows"][0][key]


def test_same_party_multiple_contracts_require_choice_and_other_scope_is_excluded():
    report()
    data = register(two=True)
    assert evidence(data)["unmatched_works"][0]["match_status"] == "ambiguous"
    data["rows"][1]["scope"] = ["Корпус 2"]
    data["rows"][1]["physical_items"][0] = {"scope": "Корпус 2"}
    item = evidence(data)["unmatched_works"][0]
    assert item["candidate_contract_ids"] == [FIRST]
    assert item["match_status"] == "proposed"


@pytest.mark.parametrize("line", ["Корпус 1 бетонирование № A-12", "Корпус 1 квартира № A-12",
                                  "Корпус 1 работы по договору № A-123"])
def test_arbitrary_numbers_or_contract_prefixes_do_not_auto_confirm(line):
    report(line)
    assert evidence()["unmatched_works"][0]["match_status"] == "proposed"


def test_explicit_contract_number_and_exact_party_identify_a_contract():
    report("Корпус 1 по договору № A-12 бетонирование")
    result = evidence(register(two=True))
    row = result["rows"][0]
    item = row["reconciliation"]["daily_evidence"][0]
    assert item["contract_id"] == FIRST
    assert item["match_status"] == "confirmed"
    assert item["link_basis"] == "explicit_number"
    assert result["unmatched_works"] == []


def test_substring_party_and_fuzzy_inline_alias_do_not_auto_confirm():
    report("Корпус 1 по договору A-12 бетонирование", party="Альфа Строй")
    assert evidence()["unmatched_works"][0]["candidate_contract_ids"] == []
    report("Альф — Корпус 1 по договору A-12 бетонирование")
    item = evidence()["unmatched_works"][0]
    assert item["match_status"] != "confirmed"


@pytest.mark.parametrize("party", ["ИП Альфа", "АО Альфа", "ПАО Альфа"])
def test_different_explicit_legal_forms_cannot_auto_confirm_a_contract(party):
    report("Корпус 1 по договору A-12 бетонирование", party=party)
    result = evidence()
    assert result["unmatched_works"][0]["match_status"] != "confirmed"
    assert result["rows"][0]["reconciliation"]["status"] != "Есть подтверждённые связи"


def test_inline_different_legal_form_does_not_become_an_exact_known_party():
    report("ИП Альфа — Корпус 1 по договору A-12 бетонирование")
    assert evidence()["unmatched_works"][0]["match_status"] != "confirmed"


def test_inline_explicit_legal_form_survives_shorthand_alias_and_continuation():
    folder = monitor._project_dir(PROJECT) / "daily"
    folder.mkdir(parents=True)
    (folder / "2026-10-14.json").write_text(json.dumps({"date": "2026-10-14", "parsed": {
        "contractors": [{"name": "Альфа", "workers": 5}],
        "works": [{"contractor": "Альфа", "line": "ИП Альфа — Корпус 1 подготовка"},
                  {"contractor": "Альфа", "line": "Корпус 1 по договору A-12 бетонирование"}]}}, ensure_ascii=False))
    result = evidence()
    assert len(result["unmatched_works"]) == 2
    assert result["unmatched_works"][0]["reported_contractor"] == "ИП Альфа"
    assert result["unmatched_works"][1]["party_attribution_uncertain"]
    assert all(item["match_status"] != "confirmed" for item in result["unmatched_works"])


def test_attendance_is_not_a_work_record_or_acceptance():
    report(attendance=True)
    data = register()
    data["rows"][0]["completed"] = None
    result = evidence(data)
    assert result["unmatched_works"] == []
    assert result["rows"][0]["completed"] is None
    assert result["rows"][0]["reconciliation"]["daily_evidence"] == []
    assert "не подтверждает остановку" in result["rows"][0]["reconciliation"]["issues"][0]


def test_same_work_is_deduplicated_within_day_and_dates_stay_separate():
    report(twice=True)
    report(day="2026-10-15")
    report(day="2026-10-19")
    report(day="2026-10-09")
    items = evidence(start="2026-10-12")["unmatched_works"]
    assert [item["date"] for item in items] == ["2026-10-14", "2026-10-15"]
    assert len({item["id"] for item in items}) == 2


def test_manual_link_is_persistent_and_exact_work_signature_only(monkeypatch):
    install_register(monkeypatch)
    report()
    item = evidence()["unmatched_works"][0]
    saved = links.set_link(PROJECT, FIRST, item["id"], CUT)
    assert saved["confirmed"]
    report(day="2026-10-15")
    report("Корпус 1 армирование", day="2026-10-16")
    result = evidence()
    related = result["rows"][0]["reconciliation"]["daily_evidence"]
    assert [item["link_basis"] for item in related] == ["manual", "manual", "candidate"]
    assert [item["text"] for item in result["unmatched_works"]] == ["Корпус 1 армирование"]
    path = links._path(PROJECT)
    assert path.stat().st_mode & 0o077 == 0
    assert not any(field in path.read_text() for field in ('"key"', '"session"', '"text"'))


def test_changed_tail_after_display_limit_changes_identity_and_does_not_inherit_manual_link(monkeypatch):
    install_register(monkeypatch)
    prefix = "Корпус 1 " + "Длинное описание работы " * 1000
    report(prefix + "ПЕРВЫЙ ИСХОДНЫЙ ХВОСТ")
    one = evidence()["unmatched_works"][0]
    assert len(one["text"]) <= links._MAX_TEXT and one["text_truncated"]
    links.set_link(PROJECT, FIRST, one["id"], CUT)
    assert evidence()["unmatched_works"] == []
    report(prefix + "ИЗМЕНЁННЫЙ ИСХОДНЫЙ ХВОСТ")
    two = evidence()["unmatched_works"][0]
    assert one["id"] != two["id"]
    assert two["link_basis"] != "manual" and two["match_status"] == "proposed"
    assert one["text"] == two["text"]  # display equality is not source identity


def test_explicit_legal_form_change_invalidates_prior_manual_signature(monkeypatch):
    install_register(monkeypatch)
    report(party="ООО Альфа")
    one = evidence()["unmatched_works"][0]
    links.set_link(PROJECT, FIRST, one["id"], CUT)
    report(party="ИП Альфа")
    two = evidence()["unmatched_works"][0]
    assert one["id"] != two["id"] and two["link_basis"] != "manual"


def test_scope_after_display_limit_is_still_considered_for_contract_identity():
    report("Работы по договору A-12 " + "Длинное описание " * 1500 + " Корпус 2")
    item = evidence()["unmatched_works"][0]
    assert item["scope"] == "Корпус 2"
    assert item["match_status"] == "unmatched" and item["candidate_contract_ids"] == []


def test_revocation_suppresses_explicit_auto_link_and_can_be_undone(monkeypatch):
    install_register(monkeypatch)
    report("Корпус 1 по договору № A-12 бетонирование")
    item = evidence()["rows"][0]["reconciliation"]["daily_evidence"][0]
    links.set_link(PROJECT, FIRST, item["id"], CUT, confirmed=False)
    assert evidence()["unmatched_works"][0]["match_status"] == "proposed"
    links.set_link(PROJECT, FIRST, item["id"], CUT)
    assert evidence()["unmatched_works"] == []


def test_new_competing_contract_does_not_inherit_a_previous_daily_confirmation(monkeypatch):
    install_register(monkeypatch)
    report()
    original = evidence()["unmatched_works"][0]
    links.set_link(PROJECT, FIRST, original["id"], CUT)
    report(day="2026-10-15")
    result = evidence(register(two=True))
    later = [item for item in result["unmatched_works"] if item["date"] == "2026-10-15"]
    assert len(later) == 1 and later[0]["match_status"] == "ambiguous"
    prior = result["rows"][0]["reconciliation"]["daily_evidence"][0]
    assert prior["id"] == original["id"] and prior["link_basis"] == "manual"


def test_later_contract_change_preserves_the_prior_exact_source_decision(monkeypatch):
    data = install_register(monkeypatch, register(two=True))
    report()
    earlier = evidence(data)["unmatched_works"][0]
    links.set_link(PROJECT, FIRST, earlier["id"], CUT)
    report(day="2026-10-15")
    later = links._evidence(PROJECT, data, CUT)[-1]
    links.set_link(PROJECT, SECOND, later["id"], CUT)
    report(day="2026-10-16")
    result = evidence(data)
    all_items = {item["id"]: item for row in result["rows"]
                 for item in row["reconciliation"]["daily_evidence"]}
    assert all_items[earlier["id"]]["contract_id"] == FIRST
    assert all_items[later["id"]]["contract_id"] == SECOND
    assert all_items[links._evidence(PROJECT, data, CUT)[-1]["id"]]["contract_id"] == SECOND


def test_cross_project_evidence_and_future_evidence_are_not_a_write_capability(monkeypatch):
    install_register(monkeypatch)
    report(project="Other Site")
    item = links.enrich("Other Site", register(), CUT)["unmatched_works"][0]
    with pytest.raises(links.LinkProblem, match="не найдена"):
        links.set_link(PROJECT, FIRST, item["id"], CUT)
    report(day="2026-10-19")
    future = links.enrich(PROJECT, register(), "2026-10-20")["unmatched_works"][0]
    with pytest.raises(links.LinkProblem, match="не найдена"):
        links.set_link(PROJECT, FIRST, future["id"], CUT)
    assert not links._path(PROJECT).exists()


def test_scope_mismatch_and_unknown_contract_do_not_create_manual_links(monkeypatch):
    install_register(monkeypatch)
    report("Корпус 2 бетонирование")
    item = evidence()["unmatched_works"][0]
    with pytest.raises(links.LinkProblem, match="Корпус"):
        links.set_link(PROJECT, FIRST, item["id"], CUT)
    with pytest.raises(links.LinkProblem, match="Договор не найден"):
        links.set_link(PROJECT, SECOND, item["id"], CUT)
    assert not links._path(PROJECT).exists()


def test_entire_mixed_corpus_line_cannot_be_confirmed_for_a_partial_contract(monkeypatch):
    install_register(monkeypatch)
    report("Корпус 1 и корпус 2 по договору A-12 бетонирование")
    item = evidence()["unmatched_works"][0]
    assert item["candidate_contract_ids"] == [FIRST]
    assert item["match_status"] == "proposed"
    with pytest.raises(links.LinkProblem, match="Корпус"):
        links.set_link(PROJECT, FIRST, item["id"], CUT)
    assert not links._path(PROJECT).exists()


def test_explicit_mixed_corpus_link_can_cover_both_documented_contract_scopes():
    report("Корпус 1 и корпус 2 по договору A-12 бетонирование")
    data = register()
    data["rows"][0]["scope"] = ["Корпус 1", "Корпус 2"]
    result = evidence(data)
    assert result["unmatched_works"] == []
    assert result["rows"][0]["reconciliation"]["daily_evidence"][0]["match_status"] == "confirmed"


@pytest.mark.parametrize("scope", ["Корпус 1 и 2", "Корпус 1,2", "Корпуса 1 и 2",
                                   "Корпуса №1, №2", "Корпус1и2", "Корпуса 1, 2 и 3"])
def test_corpus_enumeration_cannot_drop_later_corpora_for_auto_or_manual_confirmation(monkeypatch, scope):
    install_register(monkeypatch)
    report(scope + " по договору A-12 бетонирование")
    item = evidence()["unmatched_works"][0]
    assert "Корпус 2" in item["scope"]
    assert item["match_status"] == "proposed"
    with pytest.raises(links.LinkProblem, match="Корпус"):
        links.set_link(PROJECT, FIRST, item["id"], CUT)


@pytest.mark.parametrize("scope", ["Корпус 1 и 2", "Корпус 1,2", "Корпуса 1 и 2"])
def test_matching_complete_documented_corpus_enumeration_can_confirm(scope):
    report(scope + " по договору A-12 бетонирование")
    data = register()
    data["rows"][0]["scope"] = ["Корпуса 1 и 2"]
    assert evidence(data)["unmatched_works"] == []


@pytest.mark.parametrize("scope", ["Корпус 1/2", "Корпуса 1–2", "Корпус 1-2"])
def test_ambiguous_corpus_notation_requires_clarification_instead_of_first_number(monkeypatch, scope):
    install_register(monkeypatch)
    report(scope + " по договору A-12 бетонирование")
    result = evidence()
    item = result["unmatched_works"][0]
    assert item["scope_ambiguous"] and item["match_status"] != "confirmed"
    assert any("неоднозначно" in message for message in result["rows"][0]["reconciliation"]["issues"])
    with pytest.raises(links.LinkProblem, match="неоднозначно"):
        links.set_link(PROJECT, FIRST, item["id"], CUT)


def test_ambiguous_contract_corpus_scope_also_blocks_whole_line_confirmation():
    report("Корпус 1 по договору A-12 бетонирование")
    data = register()
    data["rows"][0]["scope"] = ["Корпус 1/2"]
    assert evidence(data)["unmatched_works"][0]["match_status"] != "confirmed"


def test_concurrent_confirmations_do_not_lose_a_link(monkeypatch):
    install_register(monkeypatch)
    report()
    report("Корпус 1 армирование", day="2026-10-15")
    items = evidence()["unmatched_works"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda item: links.set_link(PROJECT, FIRST, item["id"], CUT), items))
    assert len(results) == 2
    assert len(links._read(PROJECT)["links"]) == 2
    assert evidence()["unmatched_works"] == []


def test_duplicate_contract_identity_is_never_chosen():
    report("Корпус 1 по договору A-12 бетонирование")
    data = register()
    data["rows"] *= 2
    assert evidence(data)["unmatched_works"][0]["match_status"] == "unmatched"


def test_gencontract_does_not_become_subcontract_based_on_presence():
    report(party="Исполнитель")
    data = register()
    data["rows"][0]["contractor"] = "Генподрядчик"
    result = evidence(data)
    assert result["unmatched_works"][0]["match_status"] == "unmatched"
    assert result["rows"][0]["completed"] == 250.0


def test_report_uses_same_confirmed_links_with_project_scoped_deeplink(monkeypatch):
    install_register(monkeypatch)
    monkeypatch.setitem(sys.modules, "developaid_monitor_ledgers",
                        types.SimpleNamespace(latest_snapshot=lambda project, cut: {"snapshot_id": "fixture"}))
    report()
    item = evidence()["unmatched_works"][0]
    links.set_link(PROJECT, FIRST, item["id"], CUT)
    groups = [{"contractor": "Альфа", "lines": [{"line": "Корпус 1 бетонирование", "days": ["2026-10-14"]},
                                                   {"line": "Корпус 1 армирование", "days": ["2026-10-15"]}]}]
    out = links.enrich_report_works(PROJECT, groups, "2026-10-12", CUT)
    found = out[0]["lines"][0]["contract_links"][0]
    assert found["id"] == FIRST
    assert found["href"] == f"/monitor#tab=contracts&project=Synthetic+Site&contract={FIRST}"
    assert out[0]["lines"][1]["contract_links"] == []
    assert "contract_links" not in groups[0]["lines"][0]
    import developaid_management_report as management
    html = management._works_html({"state": "ok", "works": out}, "week")
    assert "Договор A-12" in html and "Договор не уточнён" in html
    assert "project=Synthetic+Site" in html
    assert management._work_contract_text(out[0]["lines"][0]) == " (Договор A-12)"


def test_authoritative_crew_links_works_only_report_without_headcount(monkeypatch):
    data = install_register(monkeypatch, register(two=True))
    monkeypatch.setitem(sys.modules, "developaid_monitor_ledgers",
                        types.SimpleNamespace(latest_snapshot=lambda project, cut: {"snapshot_id": "fixture"}))
    daily.store_daily_report(PROJECT, "По работам:\nООО Альфа — Корпус 1 бетонирование", "2026-10-14")
    stored = daily._load_reports(PROJECT)[0]
    assert stored["parsed"]["contractors"] == []
    item = evidence(data)["unmatched_works"][0]
    assert item["match_status"] == "ambiguous"
    links.set_link(PROJECT, FIRST, item["id"], CUT)
    calls = []
    def build_once(project, cut):
        calls.append((project, cut))
        return copy.deepcopy(data)
    sys.modules["developaid_monitor_contracts"].build = build_once
    import developaid_management_report as management
    block = management.crew(PROJECT, "week", CUT)
    found = [entry for group in block["works"] for entry in group["lines"] if entry.get("contract_links")]
    assert len(found) == 1 and found[0]["contract_links"][0]["id"] == FIRST
    assert block["works"][0]["contractor"] == 'ООО «Альфа»'
    assert "ООО Альфа" not in found[0]["line"]
    assert "Договор A-12" in management._works_html(block, "week")
    assert calls == [(PROJECT, CUT)]


def test_report_without_cumulative_sources_keeps_old_work_shape(monkeypatch):
    monkeypatch.setitem(sys.modules, "developaid_monitor_ledgers",
                        types.SimpleNamespace(latest_snapshot=lambda project, cut: None))
    groups = [{"contractor": "Альфа", "lines": [{"line": "Бетонирование", "days": ["2026-10-14"]}]}]
    assert links.enrich_report_works(PROJECT, groups, "2026-10-12", CUT) is groups


def test_proposed_contract_is_not_printed_as_an_accepted_report_link(monkeypatch):
    install_register(monkeypatch)
    monkeypatch.setitem(sys.modules, "developaid_monitor_ledgers",
                        types.SimpleNamespace(latest_snapshot=lambda project, cut: {"snapshot_id": "fixture"}))
    report()
    groups = [{"contractor": "Альфа", "lines": [{"line": "Корпус 1 бетонирование", "days": ["2026-10-14"]}]}]
    out = links.enrich_report_works(PROJECT, groups, "2026-10-12", CUT)
    import developaid_management_report as management
    html = management._works_html({"state": "ok", "works": out}, "week")
    assert "Договор не уточнён" in html
    assert "Договор A-12" not in html and "<a " not in html


def test_invalid_saved_link_is_an_explicit_problem_instead_of_an_approval():
    report()
    links._path(PROJECT).write_text('{"version":1,"links":{"wrong":[]}}')
    with pytest.raises(links.LinkProblem, match="не распознан"):
        evidence()


def test_report_contract_text_is_escaped_and_survives_actual_pdf():
    from browser import chromium_or_skip
    from market_search import report_pdf
    import developaid_management_report as management
    import pymupdf

    chrome = chromium_or_skip()
    block = {"state": "ok", "works": [{"contractor": "Альфа", "lines": [{
        "line": "Корпус 1 бетонирование <script>bad()</script>", "days": ["2026-10-14"],
        "contract_links": [{"label": "Договор A-12", "href": f"/monitor#tab=contracts&project=Fixture&contract={FIRST}"}]}]}]}
    html = management._works_html(block, "week")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    document = report_pdf.document(html, style=management.REPORT_STYLE, title="Проверка договоров")
    raw = report_pdf.render(document, footer="Проверка", executable_path=str(chrome))
    pdf = pymupdf.open(stream=raw, filetype="pdf")
    text = " ".join(page.get_text() for page in pdf)
    assert "Договор A-12" in text and "бетонирование" in text
    assert any((link.get("uri") or "").endswith(FIRST) for page in pdf for link in page.get_links())
