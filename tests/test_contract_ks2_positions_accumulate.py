"""Позиции актов КС-2 читаются из таблицы акта и копятся с начала строительства.

Решения владельца 12.11.2026: факт работ — объёмы позиций КС-2, каждый акт добавляет
свои объёмы к прежним; из двух актов одного номера с разным содержанием действует
более поздний, прежний остаётся в карточке и назван заменённым; акт без отчётного
периода датируется датой акта, и зависящий от него итог предварительный. Акты
выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import pytest

import developaid_contract_acts as acts
import developaid_contract_documents as documents
import developaid_contract_files as files
import developaid_monitor as monitor
from tests.test_contract_card_confirms_and_chooses_links import CONTRACT, ROW
from tests.test_contract_fact_dates_ks6_periods_by_acts import act_pdf

pytest.importorskip("pymupdf")
PROJECT = "Учебный"


def _act(**kw):
    return documents.read(act_pdf(**kw))


def _rows(act):
    return [(p["row"], p["number"], p["unit"], p["quantity"], p["quantity_basis"], p["amount"]["total"])
            for p in act["positions"]]


def test_a_price_of_materials_and_of_work_with_one_cost_and_a_heading_with_its_volume():
    header = ("по порядку", "позиции по смете", "Наименование работ", "Ед. изм.", "кол-во", "цена материалы",
              "цена СМР", "стоимость итого")
    columns = (30, 75, 145, 330, 390, 440, 520, 600, 680)
    numbers = ("1", "2", "3", "4", "5", "6", "7", "8")
    rows = (numbers,
            ("1", "6.1", "Витражная система", "м2", "79,60", "", "", ""),
            ("2", "6.1.1", "Монтаж каркаса", "м2", "79,60", "-", "8 000,00", "636 800,00"),
            ("3", "6.5.1", "Монтаж стеклопакета", "м2", "2,00", "20 000,00", "7 000,00", "54 000,00"))
    got = _act(header=header, columns=columns, rows=rows, total="690 800,00")
    act = got["act"]
    # Строка номеров граф и раздел с объёмом без цены — не позиции.
    assert _rows(act) == [(2, "6.1.1", "м2", 79.6, "work", 636800.0), (3, "6.5.1", "м2", 2.0, "work", 54000.0)]
    assert act["positions"][0]["group"] == "Витражная система"
    assert act["table_total"] == 690800.0 and got["warnings"] == []


def test_quantities_of_materials_and_of_work_and_costs_split_in_two():
    header = ("по порядку", "позиции по смете", "Наименование", "Ед. изм.", "кол-во (материал)", "кол-во (СМР)",
              "цена материал", "цена СМР", "сумма материал", "сумма СМР")
    columns = (10, 60, 135, 215, 255, 330, 395, 455, 520, 600, 680)
    rows = (("1", "4.5.1", "Монтаж каркаса", "м2", "42,84", "40,00", "21 000,00", "7 000,00",
             "899 640,00", "280 000,00"),
            ("2", "4.6.1", "Монтаж откосов", "м2", "-", "10,00", "-", "1 000,00", "-", "10 000,00"))
    got = _act(header=header, columns=columns, rows=rows, total="1 189 640,00")
    act = got["act"]
    assert _rows(act) == [(1, "4.5.1", "м2", 40.0, "work", 1179640.0), (2, "4.6.1", "м2", 10.0, "work", 10000.0)]
    first = act["positions"][0]
    assert first["quantity_material"] == 42.84 and first["amount"] == {
        "material": 899640.0, "work": 280000.0, "total": 1179640.0}
    assert got["warnings"] == []


def test_the_works_end_at_their_total_and_the_customers_materials_are_no_works():
    after = (("№ п/п", "Основание", "Давальческие материалы", "Ед. изм.", "Кол-во", "Цена", "Стоимость"),
             ("1", "М-15", "Арматура", "т", "6,500", "60 000,00", "390 000,00"))
    got = _act(after=after)
    assert _rows(got["act"]) == [(2, "1.1", "м3", 0.5, "work", 4000.0)]


def test_the_sum_of_positions_is_checked_against_the_total_row_and_a_row_without_cost_is_named():
    rows = (("1", "1.1", "Устройство стен", "м3", "0,5", "8 000,00", "4 000,00"),
            ("2", "1.2", "Устройство плит", "м3", "1,0", "7 000,00", "семь тысяч"))
    got = _act(rows=rows, total="11 000,00")
    assert ("Стр. 1: строка № 2 акта «Устройство плит» не распознана как позиция: не хватает единицы, объёма "
            "или стоимости.") in got["warnings"]
    assert ("Сумма позиций акта 4 000,00 не равна строке «Итого» таблицы 11 000,00: проверьте, все ли строки "
            "прочитаны.") in got["warnings"]


def test_the_number_of_the_act_is_read_under_a_lone_sign_beside_the_date():
    got = _act(number="7", number_label=("№", ""))
    assert got["act"]["number"] == "7"


def _record(sha, number, finish, positions, *, date=None, start=None, uploaded="2026-02-10T10:00:00",
            filename=None):
    return {"sha256": sha * 64, "filename": filename or f"КС-2 {number}.pdf", "uploaded_at": uploaded,
            "title": f"Акт КС-2 № {number}",
            "act": {"number": number, "date": date or finish, "start": start, "finish": finish,
                    "total": sum(p[3] for p in positions),
                    "positions": [{"row": n + 1, "number": code, "name": name, "unit": unit, "quantity": q,
                                   "quantity_basis": "work", "amount": {"total": money}}
                                  for n, (code, name, unit, money, q) in enumerate(
                                      (c, nm, u, m, q) for c, nm, u, q, m in positions)]}}


WALLS = ("1.1", "Устройство стен", "м3")


def test_acts_add_their_volumes_from_the_start_and_an_act_after_the_cut_waits():
    records = [_record("a", "1", "2026-01-31", [(*WALLS, 10.0, 1000.0)]),
               _record("b", "2", "2026-02-28", [(*WALLS, 5.0, 500.0), ("1.2", "Плиты", "м2", 3.0, 300.0)]),
               _record("c", "3", "2026-03-31", [(*WALLS, 7.0, 700.0)])]
    got = acts.accumulated(records, "2026-03-01")
    assert [(p["number"], p["quantity"], p["amount"], [x["act"] for x in p["parts"]]) for p in got["positions"]] == [
        ("1.1", 15.0, 1500.0, ["1", "2"]), ("1.2", 3.0, 300.0, ["2"])]
    assert got["later"] == 1 and got["preliminary"] is False and got["note"] == ""


def test_an_act_without_its_period_counts_on_its_date_and_marks_the_result_preliminary():
    records = [_record("a", "1", None, [(*WALLS, 10.0, 1000.0)], date="2026-01-31")]
    got = acts.accumulated(records, "2026-02-01")
    assert got["acts"][0]["day"] == "2026-01-31" and got["acts"][0]["preliminary"] is True
    assert got["positions"][0]["preliminary"] is True
    assert got["note"] == "Период выполнения неизвестен; для расчёта использована дата акта."
    undated = acts.accumulated([_record("b", "2", None, [(*WALLS, 1.0, 1.0)], date=None)], "2026-02-01")
    undated_row, = undated["excluded"]
    assert undated["positions"] == [] and undated_row["reason"].startswith(
        "у акта не прочитаны ни отчётный период, ни дата составления")


def test_the_later_act_of_one_number_replaces_the_earlier_and_a_copy_counts_once():
    earlier = _record("a", "2", "2026-02-28", [(*WALLS, 5.0, 500.0)], uploaded="2026-03-01T09:00:00",
                      filename="прежний.pdf")
    later = _record("b", "2", "2026-02-28", [(*WALLS, 6.0, 600.0)], uploaded="2026-03-02T09:00:00",
                    filename="исправленный.pdf")
    copy = {**later, "sha256": "c" * 64, "filename": "копия.pdf", "uploaded_at": "2026-03-03T09:00:00"}
    got = acts.accumulated([later, earlier, copy], "2026-03-31")
    assert [(p["quantity"], p["amount"]) for p in got["positions"]] == [(6.0, 600.0)]
    assert got["replaced"]["a" * 64].startswith("Заменён: в карточке есть более поздняя редакция акта КС-2 № 2")
    assert "копия.pdf" in got["replaced"]["a" * 64]
    assert got["replaced"]["b" * 64] == "Тот же акт КС-2 № 2 загружен ещё и файлом «копия.pdf»: его объёмы учтены один раз."
    assert got["notes"]["c" * 64] == ("Действует вместо прежней редакции акта № 2: акт КС-2 № 2 от 28.02.2026 "
                                      "(файл «прежний.pdf»).")


def test_different_units_and_acts_without_a_number_are_never_merged():
    records = [_record("a", "1", "2026-01-31", [(*WALLS, 10.0, 1000.0)]),
               _record("b", "2", "2026-02-28", [("1.1", "Устройство стен", "м2", 4.0, 400.0)]),
               _record("c", "", "2026-02-28", [(*WALLS, 1.0, 100.0)]),
               _record("d", "", "2026-02-28", [(*WALLS, 1.0, 100.0)])]
    got = acts.accumulated(records, "2026-03-31")
    assert sorted((p["unit"], p["quantity"]) for p in got["positions"]) == [("м2", 4.0), ("м3", 12.0)]
    assert got["replaced"] == {}


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "_SNAPSHOT_DIR", tmp_path / "monitor")


def test_the_card_lists_the_accumulated_volumes_and_names_the_replaced_act(card):
    files.store(PROJECT, ROW, "КС-2 1.pdf", act_pdf(number="1", date="31.01.2026", start="01.01.2026",
                                                    finish="31.01.2026"))
    first = files.store(PROJECT, ROW, "КС-2 2.pdf", act_pdf())["sha256"]
    rows = (("1", "1.1", "Устройство стен", "м3", "0,75", "8 000,00", "6 000,00"),)
    fixed = files.store(PROJECT, ROW, "КС-2 2 исправленный.pdf", act_pdf(rows=rows, total="6 000,00"))["sha256"]
    listed = files.listing(PROJECT, CONTRACT, "2026-02-04")
    performed = listed["performed"]
    walls, = performed["positions"]
    assert (walls["number"], walls["quantity"], walls["amount"]) == ("1.1", 1.25, 10000.0)
    assert [a["number"] for a in performed["acts"]] == ["1", "2"]
    documents_by_sha = {d["sha256"]: d for d in listed["documents"]}
    assert documents_by_sha[first]["act_state"] == "replaced"
    assert documents_by_sha[first]["warnings"][0].startswith("Заменён: в карточке есть более поздняя редакция")
    assert documents_by_sha[fixed]["act_state"] == "in_force"
    assert documents_by_sha[fixed]["warnings"][0].startswith("Действует вместо прежней редакции акта № 2")
