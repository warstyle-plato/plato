"""A question identifies uncertainty; it never merges legal contracts or rewrites dates."""
import copy
import datetime as dt

import pytest

from market_search import sales_dialogue as dialogue, sales_questions as questions, salesroom


def parking(suffix="", **changes):
    return dict({"contract": f"ДДУ №0042М{suffix}/ТЕСТ от 18.11.2026",
                 "signed": "2026-11-18", "product": "Машиноместа", "unit": "",
                 "state": "Действующий", "area": 14, "amount": 800_000,
                 "escrow_paid": 0, "escrow_observed": True, "payment_variant": "1"}, **changes)


def ask(rows, asked=None):
    return questions.questions(None, {"rows": rows}, "2026-11-27", "2026-11-27", asked)


def test_possible_reissue_is_one_neutral_question_not_one_payment_target():
    rows = [parking(), parking("-1")]
    before = copy.deepcopy(rows)
    [item] = ask(rows)
    assert item["kind"] == "contract_identity"
    assert {x["contract"] for x in item["subjects"]} == {r["contract"] for r in rows}
    assert set(item["related_question_keys"]) == {questions.money_key(r) for r in rows}
    assert "оба договора действуют или один заменил другой?" in item["text"]
    assert all(r["contract"] in item["text"] for r in rows)
    assert not ({"amount", "subject", "baseline", "expected_event"} & item.keys())
    assert ask(list(reversed(rows)))[0]["key"] == item["key"]
    assert rows == before


@pytest.mark.parametrize("change", [
    {"area": 13.9}, {"amount": 800_001}, {"signed": "2026-11-19"},
    {"product": "Кладовая"}, {"unit": "корп 2 м/м 42"},
    {"state": "Расторгнут"}, {"escrow_observed": False}, {"escrow_observed": None},
    {"area": 0}, {"area": None}, {"area": float("nan")}, {"area": float("inf")},
    {"area": True}, {"escrow_paid": None}, {"escrow_paid": ""}, {"escrow_paid": True},
])
def test_different_or_unknown_observations_never_become_one_contract(change):
    found = ask([parking(), parking("-1", **change)])
    assert not any(x["kind"] == "contract_identity" for x in found)


@pytest.mark.parametrize("contract", [
    "ДДУ №0042М-2/ТЕСТ от 18.11.2026", "ДДУ №0042М-10/ТЕСТ от 18.11.2026",
    "ДДУ №0042М-1/ДРУГОЙ от 18.11.2026", "ДДУ №42М-1/ТЕСТ от 18.11.2026",
    "ДДУ №0042M-1/ТЕСТ от 18.11.2026", "ДДУ №0042М-1/ТЕСТ от 17.11.2026",
    "Дополнение к ДДУ №0042М-1/ТЕСТ от 18.11.2026",
    "ДДУ №0042М-1/ТЕСТ от 18.11.2026 приложение",
])
def test_legal_number_boundaries_are_not_alias_rules(contract):
    found = ask([parking(), parking("-1", contract=contract)])
    assert [x["kind"] for x in found] == ["money", "money"]


def test_another_family_member_or_conflicting_source_row_prevents_the_pair():
    for rows in ([parking(), parking("-1"), parking("-2")],
                 [parking(), parking("-1"), parking("-1", amount=800_001)]):
        assert not any(x["kind"] == "contract_identity" for x in ask(rows))


@pytest.mark.parametrize("member", [0, 1, 2])
def test_any_prior_question_blocks_the_pair_without_changing_history(tmp_path, member):
    rows = [parking(), parking("-1")]
    [item] = ask(rows)
    key = [questions.money_key(rows[0]), questions.money_key(rows[1]), item["key"]][member]
    asked = {key}
    assert ask(rows, asked) == [] and asked == {key}
    questions.remember(tmp_path, "Тест", [item], "2026-11-27")
    stored = set(questions.load_asked(tmp_path, "Тест"))
    assert stored == questions.question_keys(item)
    assert ask([rows[0]], stored) == [] and ask([rows[1]], stored) == []


def test_dialogue_keeps_related_keys_when_one_version_later_leaves_the_source(tmp_path):
    rows = [parking(), parking("-1")]
    [item] = ask(rows)
    batch_id = dialogue.prepare(tmp_path, "Тест", -10012345, [item], "2026-11-27")
    saved = dialogue.load(tmp_path, "Тест")["batches"][batch_id]["questions"][0]
    assert saved["subjects"] == item["subjects"]
    assert saved["related_question_keys"] == item["related_question_keys"]
    asked = dialogue.asked_keys(tmp_path, "Тест")
    assert asked == questions.question_keys(item)
    assert ask(rows, asked) == [] and ask([rows[1]], asked) == []


def message(day, present=True, header=None):
    return {"day": day, "text": f"Отчёт за {header or day} г. Текущих броней: {int(present)} "
            + ("квартира № 307, башня Учебная, 99,2 кв.м." if present else "")}


def test_last_sighting_names_the_current_message_not_the_first_ever_booking():
    read = {"messages": [message("2026-10-24"), message("2026-10-25", False),
                         message("2026-11-24"), message("2026-11-25", False)]}
    before = copy.deepcopy(read)
    outcome = salesroom.booking_outcomes(read, [], None, "2026-11-20", "2026-11-25")["period"][0]
    assert outcome["first"] == "2026-10-24" and outcome["last"] == "2026-11-24"
    [item] = questions._dropped(read, [], None, "2026-11-25", False)
    assert "в сообщении от 24.11.2026" in item["text"]
    assert "в сообщении от 25.11.2026" in item["text"]
    assert "24.10" not in item["text"]
    assert item["key"].endswith(":2026-11-25") and read == before


def test_genuine_october_observation_is_not_shifted_to_november():
    read = {"messages": [message("2026-10-24"), message("2026-10-25", False)]}
    [item] = questions._dropped(read, [], None, "2026-10-25", False)
    assert "24.10.2026" in item["text"] and "25.10.2026" in item["text"]
    assert "11.2026" not in item["text"] and item["key"].endswith(":2026-10-25")


def test_message_date_is_not_presented_as_an_inconsistent_report_heading():
    source = message("2026-11-24", header="24.10.2026")
    assert salesroom._report_day(source) == "2026-10-24"
    [item] = questions._dropped({"messages": [source, message("2026-11-25", False)]},
                                [], None, "2026-11-25", False)
    assert "в сообщении от 24.11.2026" in item["text"] and "24.10.2026" not in item["text"]


def test_source_years_remain_explicit_across_a_year_boundary():
    read = {"messages": [message("2025-12-31"), message("2026-01-01", False)]}
    [item] = questions._dropped(read, [], None, "2026-01-01", False)
    assert "31.12.2025" in item["text"] and "01.01.2026" in item["text"]
