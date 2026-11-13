"""Что читатель Расчёта и ГПР не смог сверить или прочитать, он называет, а не пропускает молча.

Итог с иной подписью, чем «Всего», итог без читаемой суммы и расчёт без общего итога
получают признак «не сверено» с причиной. Итог подраздела не сверяется со всем разделом.
Строка номеров граф на странице продолжения — не позиция. Непрочитанная цена и
непрочитанная дата графика названы своим напечатанным текстом. Источник каждой даты
строки графика записан отдельно. Документы нарисованы здесь же, с выдуманными данными.
"""
from __future__ import annotations

import pytest

import developaid_contract_documents as documents
from tests.test_contract_documents_are_read_from_their_tables import (LINES, NUMBERS, SECOND_PAGE, estimate_pdf,
                                                                      schedule_pdf)

ALL = "ВСЕГО с учетом НДС, руб.:"


def _second(label=ALL, amount="127 150,00", extra=()):
    rows = [row for row in SECOND_PAGE if row[1] != ALL]
    total = ("", label, "", "", "", "", "", "", "", amount) if label else None
    return rows[:-1] + list(extra) + ([total] if total else []) + rows[-1:]


def _estimate(second):
    (estimate,) = documents.read(estimate_pdf(second=second))["estimates"]
    return estimate


def _overall(estimate):
    return [t for t in estimate["totals"] if t["kind"] == "overall"]


def test_an_overall_total_signed_otherwise_than_all_is_checked():
    estimate = _estimate(_second("ИТОГО по расчёту", "127 000,00"))
    (total,) = _overall(estimate)
    assert (total["checked"], total["reason"]) == (False, "сумма позиций 127 150,00 не равна итогу 127 000,00")
    assert "ИТОГО по расчёту: сумма позиций 127 150,00 не равна итогу 127 000,00." in estimate["warnings"]
    (total,) = _overall(_estimate(_second("ИТОГО по расчёту")))
    assert (total["checked"], total["reason"]) == (True, None)


def test_an_unreadable_total_is_not_checked_and_says_its_printed_text():
    estimate = _estimate(_second(amount="127 15O,00"))
    (total,) = _overall(estimate)
    assert (total["amount"], total["checked"]) == (None, False)
    assert total["reason"] == "сумма итога «127 15O,00» не прочитана"
    assert f"{ALL}: не сверено — сумма итога «127 15O,00» не прочитана." in estimate["warnings"]


def test_an_estimate_without_an_overall_total_says_it_is_not_checked():
    estimate = _estimate(_second(label=None))
    assert _overall(estimate) == []
    assert ("В расчёте не найден общий итог («Всего» или «Итого» по расчёту): сумма позиций 127 150,00 "
            "не сверена с документом.") in estimate["warnings"]
    assert all(t["checked"] for t in estimate["totals"])


def test_a_total_without_vat_is_settled_by_the_total_that_equals_the_positions():
    estimate = _estimate(_second(extra=[("", "Итого без НДС", "", "", "", "", "", "", "", "105 958,33")]))
    without, with_vat = _overall(estimate)
    assert with_vat["checked"] and not without["checked"]
    assert "другой общий итог" in without["reason"]
    assert not any(w.startswith("Итого без НДС") for w in estimate["warnings"])


def test_a_subsection_total_is_not_checked_against_the_whole_section():
    subsection = ("", "Итого по подразделу 1.1", "", "", "", "", "", "", "", "50 000,00")
    rows = list(SECOND_PAGE)
    rows.insert(1, subsection)
    (estimate,) = documents.read(estimate_pdf(second=rows))["estimates"]
    total = next(t for t in estimate["totals"] if t["label"] == "Итого по подразделу 1.1")
    assert (total["kind"], total["section"], total["checked"]) == ("subsection", None, False)
    assert not any("сумма позиций 57 150,00 не равна итогу 50 000,00" in w for w in estimate["warnings"])
    assert any(w.startswith("Итого по подразделу 1.1: не сверено — позиции подраздела") for w in estimate["warnings"])
    section = next(t for t in estimate["totals"] if t["label"].startswith("Итого по Разделу № 1"))
    assert (section["kind"], section["checked"]) == ("section", True)


def test_the_row_of_column_numbers_repeated_on_a_continuation_page_is_no_position():
    estimate = _estimate([NUMBERS] + list(SECOND_PAGE))
    assert [p["number"] for p in estimate["positions"]] == ["1.1", "1.2", "1.3", "2.1", "2.1"]
    assert not any("не распознана" in w for w in estimate["warnings"])


def test_an_unreadable_price_is_named_not_left_out_of_the_check():
    rows = [row if row[0] != "1.3" else row[:6] + ("2OO,00",) + row[7:] for row in SECOND_PAGE]
    estimate = _estimate(rows)
    position = next(p for p in estimate["positions"] if p["number"] == "1.3")
    assert position["unit_price"]["total"] is None
    assert ("Стр. 2: у позиции 1.3 не прочитано: цена «2OO,00». Сверка по этим графам не выполнена."
            in estimate["warnings"])


@pytest.mark.parametrize("count, text", [(1, "1 раз"), (2, "2 раза"), (4, "4 раза"), (5, "5 раз"), (11, "11 раз"),
                                         (12, "12 раз"), (21, "21 раз"), (22, "22 раза"), (112, "112 раз")])
def test_a_count_of_times_is_said_in_words(count, text):
    assert documents._times(count) == text


def test_a_position_number_repeated_five_times_says_five_times():
    plate = next(row for row in SECOND_PAGE if row[0] == "2.1")
    rows = [row for row in SECOND_PAGE if row[0] != "2.1"]
    rows[3:3] = [plate] * 5
    warnings = _estimate(rows)["warnings"]
    assert any(w.startswith("Номер позиции 2.1 повторяется в расчёте 5 раз (стр. 2)") for w in warnings)


def test_sums_in_warnings_have_a_decimal_comma_and_the_rest_of_the_phrase_is_kept():
    rows = [row if row[0] != "1.3" else row[:9] + ("5 000,00",) for row in SECOND_PAGE]
    warnings = _estimate(rows)["warnings"]
    assert "Позиция 1.3: количество × цена = 4 000,00, а в графе «Всего» 5 000,00." in warnings


def _schedule(lines):
    return documents.read(schedule_pdf(lines=lines))["schedule"]


def test_an_unreadable_date_is_corrected_by_the_bar_with_its_printed_text():
    lines = LINES[:2] + (("1.2", "Ограждение", "01.02.26", "03.02.2026", (3, 5)),)
    schedule = _schedule(lines)
    fence = schedule["lines"][2]
    assert (fence["start"], fence["finish"], fence["corrected"]) == ("2026-02-01", "2026-02-03", True)
    assert fence["dates_from"] == {"start": "bar", "finish": "cells"}
    assert fence["unread"] == {"start": "01.02.26"}
    (correction,) = schedule["corrections"]
    assert correction["text"] == ("Стр. 1: у строки 1.2 «Ограждение» дата начала «01.02.26» не прочитана: нужна "
                                  "запись вида 01.02.2026. Взята дата полосы: 01.02.2026.")
    assert (correction["basis"], correction["unread"]) == ("bar", {"start": "01.02.26"})


def test_an_unreadable_date_without_a_bar_is_named_once():
    lines = LINES[:2] + (("1.2", "Ограждение", "01.02.26", "03.02.2026", None),)
    schedule = _schedule(lines)
    fence = schedule["lines"][2]
    assert (fence["start"], fence["finish"], fence["corrected"]) == (None, "2026-02-03", False)
    assert schedule["warnings"] == ["Стр. 1: у строки 1.2 «Ограждение» дата начала «01.02.26» не прочитана: нужна "
                                    "запись вида 01.02.2026, а полосы на диаграмме нет: срок взять неоткуда."]


def test_a_group_with_unreadable_dates_takes_its_works_as_a_correction():
    lines = (("1", "Подготовка", "29.01.26", "03.02.26", None),) + LINES[1:3]
    schedule = _schedule(lines)
    group = schedule["lines"][0]
    assert (group["start"], group["finish"], group["corrected"]) == ("2026-01-29", "2026-02-03", True)
    assert group["dates_from"] == {"start": "works", "finish": "works"}
    (correction,) = schedule["corrections"]
    assert correction["text"] == ("Строка 1 «Подготовка»: даты начала «29.01.26» и окончания «03.02.26» не "
                                  "прочитаны: нужна запись вида 01.02.2026. Взяты сроки входящих в неё работ: "
                                  "29.01.2026 — 03.02.2026.")
    assert schedule["warnings"] == []


def test_each_date_of_a_line_says_where_it_came_from():
    lines = LINES[:1] + (("1.1", "Разметка", "", "31.01.2026", (0, 2)),)
    marking = _schedule(lines)["lines"][1]
    assert (marking["start"], marking["finish"], marking["corrected"]) == ("2026-01-29", "2026-01-31", False)
    assert marking["dates_from"] == {"start": "bar", "finish": "cells"}


@pytest.mark.parametrize("finish, said", [
    ("03.02.26", "дата окончания «03.02.26» не прочитана: нужна запись вида 01.02.2026; в графе начала 29.01.2026"),
    ("", "в графе начала 29.01.2026, в графе окончания даты нет"),
])
def test_a_bar_correction_names_an_unread_date_once_and_an_empty_cell_as_empty(finish, said):
    lines = LINES[:2] + (("1.2", "Ограждение", "29.01.2026", finish, (3, 5)),)
    (correction,) = _schedule(lines)["corrections"]
    assert correction["text"] == (f"Стр. 1: у строки 1.2 «Ограждение» {said}, а полоса на диаграмме идёт "
                                  "01.02.2026 — 03.02.2026. Взяты даты полосы: 01.02.2026 — 03.02.2026.")


def test_a_bar_correction_with_both_dates_unread_names_them_once():
    lines = LINES[:2] + (("1.2", "Ограждение", "29.01.26", "03.02.26", (3, 5)),)
    (correction,) = _schedule(lines)["corrections"]
    assert correction["text"] == ("Стр. 1: у строки 1.2 «Ограждение» даты начала «29.01.26» и окончания "
                                  "«03.02.26» не прочитаны: нужна запись вида 01.02.2026. Взяты даты полосы: "
                                  "01.02.2026 — 03.02.2026.")
