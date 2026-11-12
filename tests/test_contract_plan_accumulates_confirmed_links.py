"""Накопленный план договора: деньги подтверждённых связей по дням строк ГПР, по редакциям.

Расчёт и график выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import datetime as dt

import pytest

import developaid_contract_files as files
import developaid_contract_link_choices as choices
import developaid_contract_plan as plan
import developaid_contract_schedule_links as links
import developaid_monitor as monitor
from test_contract_positions_are_linked_to_schedule_lines import ESTIMATE, SCHEDULE
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, FIRST, LINES, ROW, SECOND
from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf, schedule_pdf

D = dt.date.fromisoformat
LINE = {"start": "2026-03-01", "finish": "2026-03-10"}


def test_a_line_is_planned_evenly_over_its_days_and_from_the_agreement_date():
    assert [plan.done(LINE, D(day)) for day in ("2026-02-28", "2026-03-01", "2026-03-05", "2026-03-31")] == [
        0.0, 0.1, 0.5, 1.0]
    # «На завершение работ» с 06.03: остаток делится на 06–10.03.
    assert [plan.done(LINE, D(day), D("2026-03-06")) for day in ("2026-03-05", "2026-03-06", "2026-03-10")] == [
        0.0, 0.2, 1.0]
    # Срок строки закончился до соглашения: весь остаток — на дату соглашения, не раньше.
    assert [plan.done(LINE, D(day), D("2026-04-01")) for day in ("2026-03-31", "2026-04-01")] == [0.0, 1.0]


def _linked(estimate, schedule, confirm, scope="full"):
    proposed = links.propose(estimate, schedule)
    chosen = {}
    for number in confirm:
        item = next(p for p in proposed["positions"] if p["number"] == number)
        chosen[item["key"]] = choices.decide(item, schedule, None, None, "2026-01-01T00:00:00+00:00")
    return {"scope": scope, "links": choices.apply(proposed, chosen, schedule)}


def _edition(sha, date, estimates, start=None, schedule=SCHEDULE):
    return {"sha256": sha * 64, "title": f"Редакция {sha}", "date": date, "estimates": estimates,
            "schedule": schedule, "schedule_title": "График", "start": start}


def test_only_confirmed_links_enter_the_plan_of_the_edition_in_force():
    contract = _edition("a", "2025-12-01", [_linked(ESTIMATE, SCHEDULE, ["1.1", "3.1"])])
    agreement = _edition("b", "2026-03-11", [_linked(ESTIMATE, SCHEDULE, ["2.1"], "accepted"),
                                             _linked(ESTIMATE, SCHEDULE, ["1.1", "3.1", "3.2"], "remaining")],
                         start="2026-03-11")
    early = plan.build([contract, agreement], "2026-03-05")
    first, second = early["editions"]
    assert early["in_force"] == "a" * 64 and first["in_force"] and second["planned"] is None
    assert first["until"] == "2026-03-10" and second["until"] is None
    assert [(line["code"], line["amount"]) for line in first["lines"]] == [
        ("1.1", 1000.0), ("3.1.1", 1000.0), ("3.1.3", 500.0)]
    # 1.1 закончена, 3.1.1 — 5 дней из 10, 3.1.3 ещё не начата.
    assert first["planned"] == pytest.approx(1000 + 500)
    assert first["outside"]["proposed"] == {"count": 2, "amount": 2000.0}
    assert first["outside"]["review"] == {"count": 5, "amount": 5000.0}
    assert first["months"][-1] == {"month": "2026-03", "planned": pytest.approx(2500.0)}

    later = plan.build([contract, agreement], "2026-03-16")
    current = later["editions"][1]
    assert later["in_force"] == "b" * 64 and later["editions"][0]["planned"] is None
    assert current["accepted"] == 9500.0 and current["start"] == "2026-03-11"
    # 1.1 и 3.1.1 закончились до соглашения: их остаток — на 11.03; 3.1.3 — 1 день из 5.
    assert [line["overdue"] for line in current["lines"]] == [True, True, False]
    assert current["overdue"] == 2
    assert current["planned"] == pytest.approx(1000 + 1000 + (500 + 1000) * 1 / 5)
    assert [m["month"] for m in current["months"]] == ["2026-03"]


def test_no_edition_in_force_says_so_and_a_dateless_one_is_never_chosen():
    contract = _edition("a", "2025-12-01", [_linked(ESTIMATE, SCHEDULE, ["1.1"])])
    before = plan.build([contract], "2025-11-30")
    assert before["in_force"] is None
    assert before["note"] == "На дату среза 30.11.2025 ни одна редакция с Расчётом ещё не действовала."
    dateless = plan.build([_edition("c", None, contract["estimates"])], "2026-05-01")
    assert dateless["in_force"] is None and dateless["editions"][0]["note"].startswith("Дата документа не прочитана")


# --- карточка договора ------------------------------------------------------------

AGREEMENT_6 = ("Приложение № 3 к Дополнительному соглашению № 6 от 03.02.2026",
               "к Договору подряда № 12-ТСТ от 01.09.2025")
# Новый график: стены 2-го этажа короче, плиты позже.
MOVED = {"1.2": ("01.02.2026", "03.02.2026", (3, 5)), "1.3": ("04.02.2026", "05.02.2026", (6, 7))}
LATER = tuple((code, name, *MOVED.get(code, (start, finish, bar))) for code, name, start, finish, bar in LINES)


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")
    files.store("Учебный", ROW, "ГПР.pdf", schedule_pdf(lines=LINES))
    return files.store("Учебный", ROW, "ДС4.pdf", estimate_pdf(FIRST, SECOND))["sha256"]


def _confirm_all(sha, cut):
    listed = files.listing("Учебный", CONTRACT, cut)
    estimate = next(d for d in listed["documents"] if d["sha256"] == sha)["estimates"][0]
    indexes = [p["index"] for p in estimate["links"]["positions"] if p["status"] == "proposed"]
    return files.save_links("Учебный", CONTRACT, sha, 0, [{"index": n} for n in indexes], cut=cut)


def test_the_card_plan_follows_confirmations_a_new_schedule_and_removal(card):
    empty = files.listing("Учебный", CONTRACT, "2026-02-02")["plan"]
    (edition,) = empty["editions"]
    assert edition["in_force"] and edition["lines"] == [] and edition["total"] == 0
    assert edition["outside"]["proposed"] == {"count": 2, "amount": 11000.0}
    confirmed = _confirm_all(card, "2026-02-02")["plan"]["editions"][0]
    assert confirmed["start"] == "2026-02-01" and confirmed["schedule"] == "Документ без номера договора и соглашения"
    assert [(line["code"], line["amount"], line["overdue"]) for line in confirmed["lines"]] == [
        ("1.1", 3000.0, True), ("1.2", 5000.0, False), ("1.3", 3000.0, False)]
    assert confirmed["planned"] == pytest.approx(3000 + 5000 * 2 / 5 + 3000 * 2 / 3)

    # Соглашение № 6 приносит только новый график: тот же расчёт ложится на новые сроки.
    sixth = files.store("Учебный", ROW, "ДС6.pdf", schedule_pdf(lines=LATER, title=AGREEMENT_6))["sha256"]
    moved = files.listing("Учебный", CONTRACT, "2026-02-04")["plan"]
    assert moved["in_force"] == sixth
    current = moved["editions"][-1]
    assert current["estimate"] == "Дополнительное соглашение № 4 от 01.02.2026"
    assert current["schedule"] == "Дополнительное соглашение № 6 от 03.02.2026"
    # Доли стен пересчитаны по новым срокам: 3 и 3 дня вместо 3 и 5.
    assert [(line["code"], line["amount"], line["finish"]) for line in current["lines"]] == [
        ("1.1", 4000.0, "2026-01-31"), ("1.2", 4000.0, "2026-02-03"), ("1.3", 3000.0, "2026-02-05")]
    assert current["planned"] == pytest.approx(4000 + 4000 + 3000 * 1 / 2)
    back = files.remove("Учебный", CONTRACT, sixth, cut="2026-02-04")["plan"]
    assert back["in_force"] == card and len(back["editions"]) == 1
