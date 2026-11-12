"""Incomplete dates and legacy repeated identities cannot become contract links.

All PDFs and saved records are synthetic; a missing original is not reconstructed.
"""
from __future__ import annotations

import copy
import json

import pytest

import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_contract_link_choices as choices
import developaid_contract_schedule_links as links
import developaid_monitor as monitor
from tests.test_contract_documents_are_read_from_their_tables import _page, _text, schedule_pdf

pymupdf = pytest.importorskip("pymupdf")
NAME = "Стены корпус 1 подземная часть"


def position(number="1", building=1):
    return {"number": number, "name": f"Стены корпус {building} подземная часть",
            "unit": "м3", "quantity": 1, "amount": {"total": 100}}


def line(code="1", start="2026-02-02", finish="2026-02-01", building=1, parent=None):
    return {"code": code, "name": f"Стены корпус {building} подземная часть", "parent": parent,
            "start": start, "finish": finish, "level": 1, "page": 1}


def test_three_column_schedule_returns_an_explicit_incomplete_read():
    with pymupdf.open() as pdf:
        page = _page(pdf)
        _text(page, 30, 40, "График производства работ")
        columns = [30, 70, 260, 380]
        for x in columns:
            page.draw_line((x, 60), (x, 120), width=.5)
        for y in (60, 100, 120):
            page.draw_line((30, y), (380, y), width=.5)
        for y, texts in [(72, ["№", "Наименование работ", "Дата начала"]),
                         (112, ["1", NAME, "01.02.2026"])]:
            for i, text in enumerate(texts):
                _text(page, columns[i] + 2, y, text)
        read = documents.read(pdf.tobytes())
    assert read["schedule"]["lines"] == []
    assert any("граф" in w.lower() and "окончан" in w.lower() for w in read["schedule"]["warnings"])


@pytest.mark.parametrize("start,finish,cells", [
    ("05.02.2026", "", {"start": "2026-02-05", "finish": None}),
    ("", "27.01.2026", {"start": None, "finish": "2026-01-27"}),
])
def test_a_partial_cell_cannot_make_the_bar_backwards(start, finish, cells):
    schedule = documents.read(schedule_pdf(lines=(("1", NAME, start, finish, (0, 2)),)))["schedule"]
    row, = schedule["lines"]
    assert (row["start"], row["finish"]) == ("2026-01-29", "2026-01-31")
    assert row["cells"] == cells and row["corrected"]
    correction, = schedule["corrections"]
    assert correction["cells"] == cells
    assert correction["basis"] == "bar" and "полос" in correction["text"]


def test_even_a_tolerated_one_day_difference_cannot_reverse_a_partial_interval():
    schedule = documents.read(schedule_pdf(lines=(("1", NAME, "30.01.2026", "", (0, 0)),)))["schedule"]
    row, = schedule["lines"]
    assert (row["start"], row["finish"]) == ("2026-01-29", "2026-01-29")
    assert row["corrected"] and schedule["corrections"]
    assert row["cells"] == {"start": "2026-01-30", "finish": None}


@pytest.mark.parametrize("start,finish,unread", [
    ("29.01.26", "05.02.2026", {"start": "29.01.26"}),
    ("05.02.2026", "31.01.26", {"finish": "31.01.26"}),
])
def test_conflicting_bar_correction_names_the_unread_printed_date(start, finish, unread):
    schedule = documents.read(schedule_pdf(lines=(("1", NAME, start, finish, (0, 2)),)))["schedule"]
    row, = schedule["lines"]
    correction, = schedule["corrections"]
    assert (row["start"], row["finish"]) == ("2026-01-29", "2026-01-31")
    assert row["unread"] == correction["unread"] == unread
    # The card renders correction.text; keeping the source in metadata alone is insufficient.
    assert all(value in correction["text"] for value in unread.values())
    assert "не прочитана" in correction["text"] and "нужна запись вида" in correction["text"]
    assert "Взяты даты полосы" in correction["text"]


@pytest.mark.parametrize("start,finish", [
    ("2026-02-02", "2026-02-01"),  # zero inclusive duration
    ("2026-02-03", "2026-02-01"),  # negative duration
    (None, "2026-02-01"),
    ("bad date", "2026-02-01"),
])
@pytest.mark.parametrize("number", ["1", "9"])
def test_invalid_duration_is_a_review_gap_in_number_and_kind_matching(start, finish, number):
    schedule = {"lines": [line(start=start, finish=finish)]}
    proposed = links.propose({"positions": [position(number)]}, schedule, agreement=True)["positions"][0]
    assert proposed["status"] == "review"
    assert proposed["lines"] == [] and proposed["fix"] is None
    assert "дат" in proposed["reason"].lower() or "срок" in proposed["reason"].lower()


def test_invalid_dates_do_not_allow_confirming_an_old_manual_choice():
    schedule = {"lines": [line()]}
    proposed = links.propose({"positions": [position()]}, schedule)
    key = proposed["positions"][0]["key"]
    selected = {key: {"lines": [{"code": "1", "name": NAME}], "origin": "manual", "shares": [1.],
                      "chosen": True, "decided_at": "2026-02-01"}}
    assert choices.apply(proposed, selected, schedule)["positions"][0]["status"] == "review"
    with pytest.raises(choices.LinkChoiceProblem):
        choices.decide(proposed["positions"][0], schedule, ["1"], [100], "2026-02-01")


def test_a_single_day_remains_a_valid_duration():
    schedule = {"lines": [line(start="2026-02-01", finish="2026-02-01")]}
    row, = links.propose({"positions": [position()]}, schedule)["positions"]
    assert row["status"] == "proposed" and row["lines"][0]["share"] == 1.


def test_legacy_duplicate_identity_does_not_become_both_buildings_or_a_saved_choice(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    folder = files._directory("Synthetic legacy", "c" * 64)
    folder.mkdir(parents=True)
    schedule = {"lines": [line(start="2026-01-29", finish="2026-01-31", building=b) for b in (1, 2)],
                "warnings": [], "corrections": [], "pages": [1]}
    record = {"sha256": "a" * 64, "filename": "synthetic-old.pdf", "uploaded_at": "2026-11-01T12:00:00+00:00",
              "reader": 4, "contract": {"number": "Synthetic-1", "date": "2026-01-01"}, "agreement": None,
              "estimates": [{"scope": "full", "positions": [position("9", 2)], "totals": [], "warnings": []}],
              "schedule": schedule, "warnings": [], "pages": 1}
    raw = json.dumps(record, ensure_ascii=False).encode()
    stored = folder / ("a" * 64 + ".json")
    stored.write_bytes(raw)
    key = links.position_key(position("9", 2))
    (folder / files.CHOICES).write_text(json.dumps({"choices": {key: {
        "lines": [{"code": "1", "name": "Стены корпус 2 подземная часть"}], "origin": "duration",
        "shares": None, "chosen": True, "decided_at": "2026-02-01"}}}))
    listed = files.listing("Synthetic legacy", "c" * 64, "2026-02-01")
    document, = listed["documents"]
    row, = document["estimates"][0]["links"]["positions"]
    assert row["status"] == "review" and row["lines"] == [] and row["fix"] is None
    assert "повтор" in row["reason"].lower()
    assert stored.read_bytes() == raw and not (folder / ("a" * 64 + ".pdf")).exists()
    assert document["reader"] == 4
    assert document["schedule"] == schedule


def test_an_unambiguous_line_is_usable_beside_legacy_duplicate_identities():
    schedule = {"lines": [line(building=1), line(building=2),
                           line(code="2", building=3, start="2026-02-01", finish="2026-02-02")]}
    before = copy.deepcopy(schedule)
    row, = links.propose({"positions": [position("9", 3)]}, schedule)["positions"]
    assert row["status"] == "proposed" and [x["code"] for x in row["lines"]] == ["2"]
    assert schedule == before


def test_a_child_of_ambiguous_legacy_headings_cannot_inherit_the_last_building():
    schedule = {"lines": [line(code="1", building=1, start=None, finish=None),
                           line(code="1", building=2, start=None, finish=None),
                           {**line(code="1.1", start="2026-02-01", finish="2026-02-02", parent="1"),
                            "name": "Стены подземная часть"}]}
    row, = links.propose({"positions": [position("9", 2)]}, schedule)["positions"]
    assert row["status"] == "review" and row["lines"] == []
    assert links.leaves(schedule) == []


def test_a_saved_reversed_pdf_returns_the_card_with_a_review_gap(tmp_path, monkeypatch):
    from tests.test_contract_documents_are_read_from_their_tables import estimate_pdf
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path)
    card = {"id": "c" * 64, "contract": "№ 12-ТСТ", "contract_date": "2025-09-01"}
    files.store("Synthetic", card, "schedule.pdf", schedule_pdf(lines=(("1", NAME, "02.02.2026", "01.02.2026", None),)))
    positions = [("1", NAME, "м3", "1", "0", "100", "100", "0", "100", "100")]
    files.store("Synthetic", card, "estimate.pdf", estimate_pdf(positions, []))
    listed = files.listing("Synthetic", card["id"], "2026-02-04")
    result = next(d for d in listed["documents"] if d["estimates"])["estimates"][0]["links"]
    assert result["counts"]["review"] == 1 and result["positions"][0]["lines"] == []
