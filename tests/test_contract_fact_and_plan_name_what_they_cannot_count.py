"""Что план и факт договора не могут посчитать, они называют с причиной, а не считают нулём.

Позиция без цены и период КС с суммой, но без объёма, уходят на проверку. Объём, который не
вошёл в факт, не делает строку графика выполненной. Позиции без суммы в плане и в приложении
о принятых работах названы числом. Ручные доли строк дают ровно всю позицию. Номер акта
берётся только из явной записи. При нулевом плане на дату среза процент не считается.
Данные выдуманы: репозиторий публичный.
"""
from __future__ import annotations

import json

import pytest

import developaid_contract_act_dates as act_dates
import developaid_contract_control as control
import developaid_contract_fact as fact
import developaid_contract_link_choices as choices
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links
from test_contract_positions_are_linked_to_schedule_lines import SCHEDULE, _line, _position

# --- номер акта -------------------------------------------------------------------


@pytest.mark.parametrize("label, expected", [
    ("Акт КС-2 № 5 от 15.03.2026", "5"), ("КС-2 №2", "2"), ("Акт № 4", "4"), ("№ 3", "3"),
    ("Период № 3", None), ("Этап №2", None), ("Акт КС-2 от 15.03.2026", None), ("Работы этапа № 2 по акту", None),
])
def test_an_act_number_is_taken_only_from_an_explicit_record(label, expected):
    assert act_dates.number(label) == expected


# --- факт ---------------------------------------------------------------------------

WALLS = {"number": "1.1", "name": "Устройство стен", "unit": "м3", "quantity": 10.0,
         "unit_price": {"total": 800.0}, "amount": {"total": 8000.0}}
SLABS = {"number": "1.2", "name": "Устройство плит", "unit": "м3", "quantity": None,
         "unit_price": {"total": None}, "amount": {"total": None}}
WORKS = {"lines": [_line("1", "Каркас"), _line("1.1", "Стены", "2026-01-01", "2026-01-31"),
                   _line("1.2", "Плиты", "2026-01-01", "2026-01-31")]}


def _confirmed(position, code):
    return {"key": links.position_key(position), "status": "confirmed", "lines": [{"code": code, "share": 1.0}]}


EDITION = {"sha256": "a" * 64, "title": "Договор", "date": "2026-01-15", "start": None, "schedule": WORKS,
           "estimates": [{"scope": "full", "positions": [WALLS, SLABS],
                          "links": {"positions": [_confirmed(WALLS, "1.1"), _confirmed(SLABS, "1.2")]}}]}


def _act(item, number, name, quantity, amount, end):
    return {"item": item, "number": number, "name": name, "unit": "м3", "quantity": quantity, "act_amount": amount,
            "start": None, "end": end, "label": "", "source": {}}


def _fact(*acts):
    found = {"acts": list(acts), "unread": [], "works": 2,
             "items": [{"item": 0, "number": "1.1", "name": "Устройство стен", "unit": "м3", "plan_quantity": 10.0},
                       {"item": 1, "number": "1.2", "name": "Устройство плит", "unit": "м3", "plan_quantity": 2.0}]}
    return fact.build([EDITION], EDITION["sha256"], found, "2026-02-01")


def test_a_position_without_a_price_goes_to_review_and_gives_no_money():
    result = _fact(_act(1, "1.2", "Устройство плит", 1.0, 700.0, "2026-01-31"))
    (review,) = result["review"]
    assert review["reason"] == "У позиции № 1.2 в расчёте не прочитана цена за единицу."
    assert (result["total"], result["lines"], result["positions"]) == (0.0, [], [])


def test_a_ks_period_with_a_sum_and_no_volume_goes_to_review_with_the_sum():
    row = {"physical_items": [{"position": "1.1", "name": "Устройство стен", "unit": "м3", "completed_quantity": 0,
                               "periods": [{"quantity": 0, "amount": 5000.0, "date_start": "2026-01-20",
                                            "date_end": "2026-01-31", "label": "январь"}]}]}
    (act,) = fact.acts(row)["acts"]
    assert (act["quantity"], act["act_amount"]) == (None, 5000.0)
    result = _fact(act)
    (review,) = result["review"]
    assert review["reason"] == ("В периоде КС записана сумма 5 000,00 ₽, а объём не записан (например, оплачена "
                                "только поставка материалов): без объёма выполнение не пересчитать по цене расчёта.")
    assert result["total"] == 0.0


def test_volume_left_on_review_does_not_make_the_line_complete():
    # Половина стен принята до первой редакции расчёта: она на проверке, а не выполнена.
    early, late = (_act(0, "1.1", "Устройство стен", 5.0, None, end) for end in ("2026-01-10", "2026-01-31"))
    result = _fact(early, late)
    assert [r["reason"] for r in result["review"]] == [
        "Период КС закончился раньше даты первой редакции расчёта, загруженной в карточку."]
    (line,) = result["lines"]
    assert (line["code"], line["fact"], line["complete"]) == ("1.1", 4000.0, False)
    whole = _fact(_act(0, "1.1", "Устройство стен", 10.0, None, "2026-01-31"))
    assert whole["lines"][0]["complete"] is True


# --- план ---------------------------------------------------------------------------

OVER = "Корпус 1. Надземная часть (выше отм. 0.000)"


def _proposed(*positions):
    return links.propose({"positions": list(positions)}, SCHEDULE)


def _confirm(result, number, lines=None, shares=None):
    item = next(p for p in result["positions"] if p["number"] == number)
    return {item["key"]: choices.decide(item, SCHEDULE, lines, shares, "2026-01-01T00:00:00+00:00")}


def test_a_confirmed_position_without_a_sum_is_named_not_planned_as_zero():
    proposed = _proposed(_position("1.1", "Мобилизация", "Организация строительной площадки", total=None),
                         _position("3.1", "Устройство стен", OVER, total=1500.0))
    chosen = {**_confirm(proposed, "1.1"), **_confirm(proposed, "3.1")}
    edition = plan.edition([{"scope": "full", "links": choices.apply(proposed, chosen, SCHEDULE)}], SCHEDULE, None)
    assert edition["without_amount"] == 1
    assert [line["code"] for line in edition["lines"]] == ["3.1.1", "3.1.3"] and edition["total"] == 1500.0


def _accepted(*totals):
    proposed = _proposed(*(_position(f"{n}.1", f"Работа {n}", total=t) for n, t in enumerate(totals, 1)))
    return plan.edition([{"scope": "accepted", "links": proposed}], SCHEDULE, None)


def test_accepted_works_without_a_sum_are_counted_apart_from_the_sum_of_the_others():
    some = _accepted(1000.0, None, 250.0)
    assert (some["accepted"], some["accepted_without_amount"]) == (1250.0, 1)
    none = _accepted(None, None)
    assert (none["accepted"], none["accepted_without_amount"]) == (None, 2)
    assert (_accepted()["accepted"], _accepted()["accepted_without_amount"]) == (0.0, 0)


def test_manual_shares_within_the_rounding_give_the_whole_position():
    proposed = _proposed(_position("3.1", "Устройство стен", OVER, total=1500.0))
    chosen = _confirm(proposed, "3.1", ["3.1.1", "3.1.2", "3.1.3"], [33.33, 33.33, 33.33])
    (choice,) = chosen.values()
    assert sum(choice["shares"]) == pytest.approx(1, abs=1e-12)
    edition = plan.edition([{"scope": "full", "links": choices.apply(proposed, chosen, SCHEDULE)}], SCHEDULE, None)
    assert edition["total"] == pytest.approx(1500.0, abs=1e-9)
    # Выбор, сохранённый раньше долями без приведения, тоже даёт всю позицию.
    (key,) = chosen
    old = {key: {**choice, "shares": [0.3333, 0.3333, 0.3333]}}
    proposed = _proposed(_position("3.1", "Устройство стен", OVER, total=1500.0))
    edition = plan.edition([{"scope": "full", "links": choices.apply(proposed, old, SCHEDULE)}], SCHEDULE, None)
    assert edition["total"] == pytest.approx(1500.0, abs=1e-9)


# --- отклонение ---------------------------------------------------------------------

LATER = {"code": "1.1", "name": "Стены", "start": "2026-03-01", "finish": "2026-03-10", "amount": 1000.0,
         "planned": 0.0}
PLANNED = {"editions": [{"in_force": True, "start": None, "lines": [LATER], "planned": 0.0, "total": 1000.0}]}
LEFT_OUT = [{"reason": "Период КС закончился раньше даты первой редакции расчёта, загруженной в карточку."}] * 2


def _control(review=()):
    found = {"lines": [], "review": list(review), "note": ""}
    return control.build(PLANNED, found, None, "", "2026-02-01")


def test_a_zero_plan_on_the_cut_gives_no_percent():
    result = _control()
    assert result["total"]["planned"] == 0.0 and result["total"]["percent"] is None
    assert result["lines"][0]["percent"] is None


def test_periods_left_out_of_the_fact_are_counted_and_mark_the_lag_incomplete():
    assert (_control()["left_out"], _control()["total"]["incomplete"]) == ({"count": 0, "reasons": []}, False)
    result = _control(LEFT_OUT)
    assert result["left_out"] == {"count": 2, "reasons": [LEFT_OUT[0]["reason"]]}
    assert result["total"]["incomplete"] is True


def test_the_card_says_why_there_is_no_percent_and_what_is_left_out():
    from test_monitor_cumulative_controls import browser_page
    with browser_page(1440) as (page, _, errors):
        shown = page.evaluate(f"""() => {{const box = document.createElement('div');
            box.innerHTML = contractControlHtml({json.dumps(_control(LEFT_OUT), ensure_ascii=False)});
            document.body.append(box); return box.innerText}}""")
        assert errors == []
    assert "Процент не посчитан: по плану на дату среза ещё ничего не должно быть выполнено." in shown
    assert "0 %" not in shown
    assert ("2 периода КС не вошли в факт: " + LEFT_OUT[0]["reason"] + " Поэтому отставание и отклонение неполные: "
            "выполнение этих периодов в них не учтено.") in shown


def _remaining(*totals):
    accepted = _proposed(*(_position(f"{n}.1", f"Работа {n}", total=t) for n, t in enumerate(totals, 1)))
    rest = _proposed(_position("3.1", "Устройство стен", OVER, total=1500.0))
    edition = {"sha256": "b" * 64, "title": "Дополнительное соглашение № 2", "date": "2026-03-01",
               "start": "2026-03-01", "schedule": SCHEDULE, "schedule_title": "График",
               "estimates": [{"scope": "accepted", "links": accepted},
                             {"scope": "remaining", "links": choices.apply(rest, _confirm(rest, "3.1"), SCHEDULE)}]}
    return plan.build([edition], "2026-03-05")


@pytest.mark.parametrize("totals, said", [
    ((1000.0, None, 250.0), "по приложению о выполненных и принятых работах их стоимость 1 250 ₽, без позиций, "
                            "у которых сумма в приложении не прочитана: 1."),
    ((None, None), "в приложении о выполненных и принятых работах сумма не прочитана ни у одной позиции "
                   "(позиций: 2)."),
])
def test_the_card_names_accepted_works_without_a_sum(totals, said):
    from test_monitor_cumulative_controls import browser_page
    with browser_page(1440) as (page, _, errors):
        shown = page.evaluate(f"""() => {{const box = document.createElement('div');
            box.innerHTML = contractPlanHtml({json.dumps(_remaining(*totals), ensure_ascii=False)});
            document.body.append(box); box.querySelectorAll('details').forEach(d => d.open = true);
            return box.innerText.replaceAll('\\u00a0', ' ')}}""")
        assert errors == []
    assert said in shown
    assert "стоимость 0 ₽" not in shown
