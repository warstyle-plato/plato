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
from tests.test_contract_fact_dates_ks6_periods_by_acts import KS2_ROWS, act_pdf

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
            ("1", "3.2", "Каменная кладка", "м2", "52,40", "", "", ""),
            ("2", "3.2.1", "Кладка стен", "м2", "52,40", "-", "3 000,00", "157 200,00"),
            ("3", "3.4.1", "Монтаж перемычек", "шт", "2,00", "1 500,00", "500,00", "4 000,00"))
    got = _act(header=header, columns=columns, rows=rows, total="161 200,00")
    act = got["act"]
    # Строка номеров граф и раздел с объёмом без цены — не позиции.
    assert _rows(act) == [(2, "3.2.1", "м2", 52.4, "work", 157200.0), (3, "3.4.1", "шт", 2.0, "work", 4000.0)]
    assert act["positions"][0]["group"] == "Каменная кладка"
    assert act["table_total"] == 161200.0 and got["warnings"] == []


def test_quantities_of_materials_and_of_work_and_costs_split_in_two():
    header = ("по порядку", "позиции по смете", "Наименование", "Ед. изм.", "кол-во (материал)", "кол-во (СМР)",
              "цена материал", "цена СМР", "сумма материал", "сумма СМР")
    columns = (10, 60, 135, 215, 255, 330, 395, 455, 520, 600, 680)
    rows = (("1", "2.3.1", "Монтаж лесов", "м2", "31,50", "30,00", "12 000,00", "4 000,00",
             "378 000,00", "120 000,00"),
            ("2", "2.4.1", "Монтаж откосов", "м2", "-", "10,00", "-", "1 000,00", "-", "10 000,00"))
    got = _act(header=header, columns=columns, rows=rows, total="508 000,00")
    act = got["act"]
    assert _rows(act) == [(1, "2.3.1", "м2", 30.0, "work", 498000.0), (2, "2.4.1", "м2", 10.0, "work", 10000.0)]
    first = act["positions"][0]
    assert first["quantity_material"] == 31.5 and first["amount"] == {
        "material": 378000.0, "work": 120000.0, "total": 498000.0}
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
    assert "b" * 64 not in got["replaced"]
    assert got["copies"]["b" * 64] == "Тот же акт КС-2 № 2 загружен ещё и файлом «копия.pdf»: его объёмы учтены один раз."
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
    rows = (KS2_ROWS[0], ("2", "1.1", "Устройство стен", "м3", "0,75", "8 000,00", "6 000,00"))
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


def test_a_copy_of_the_act_in_force_is_named_a_copy_in_the_card(card, monkeypatch):
    times = iter(["2026-02-10T10:00:00", "2026-02-11T10:00:00"])
    monkeypatch.setattr(files, "_now", lambda: next(times))
    first = files.store(PROJECT, ROW, "КС-2 2.pdf", act_pdf())["sha256"]
    # Тот же акт, напечатанный в файл иначе: другой файл, то же содержание.
    again = files.store(PROJECT, ROW, "КС-2 2 копия.pdf", act_pdf(twice=True))["sha256"]
    listed = files.listing(PROJECT, CONTRACT, "2026-02-04")
    states = {d["sha256"]: d["act_state"] for d in listed["documents"]}
    assert states == {first: "copy", again: "in_force"}
    walls, = listed["performed"]["positions"]
    assert walls["quantity"] == 0.5


SECTIONS = (("1", ".", "Раздел № 1. Подземная часть", "", "", "", ""),
            ("2", "1.1", "Устройство стен", "м3", "0,5", "8 000,00", "4 000,00"),
            ("", "", "Итого по разделу 1", "", "", "", "4 000,00"),
            ("", "", "Раздел № 2. Надземная часть", "", "", "", ""),
            ("3", "1.1", "Устройство стен", "м3", "1,0", "8 000,00", "8 000,00"),
            ("", "", "Итого по разделу 2", "", "", "", "8 000,00"))


def test_a_section_total_does_not_end_the_table_and_one_number_in_two_sections_stays_two():
    got = _act(rows=SECTIONS, total="12 000,00")
    act = got["act"]
    assert [(p["row"], p["number"], p["quantity"], p["section"]) for p in act["positions"]] == [
        (2, "1.1", 0.5, "Раздел № 1. Подземная часть"), (3, "1.1", 1.0, "Раздел № 2. Надземная часть")]
    assert act["table_total"] == 12000.0 and got["warnings"] == []
    record = {"sha256": "e" * 64, "filename": "КС-2 2.pdf", "uploaded_at": "2026-02-10T10:00:00",
              "title": "Акт КС-2 № 2", "act": act}
    summed = acts.accumulated([record], "2026-03-31")
    assert sorted((p["quantity"], p["amount"]) for p in summed["positions"]) == [(0.5, 4000.0), (1.0, 8000.0)]


def test_without_the_total_row_of_the_table_the_positions_are_checked_against_the_total_of_the_act():
    got = _act(total="5 000,00", table_total="")
    assert got["act"]["table_total"] is None and got["act"]["total"] == 5000.0
    assert ("Сумма позиций акта 4 000,00 не равна строке «Итого по акту» 5 000,00: проверьте, все ли строки "
            "прочитаны.") in got["warnings"]


def test_a_row_with_a_volume_and_no_cost_that_heads_nothing_is_named_and_not_counted():
    rows = (("1", "2.1", "Кладка перегородок", "м2", "10,0", "", ""),
            ("2", "1.1", "Устройство стен", "м3", "0,5", "8 000,00", "4 000,00"))
    got = _act(rows=rows)
    assert _rows(got["act"]) == [(2, "1.1", "м3", 0.5, "work", 4000.0)]
    assert got["act"]["positions"][0]["group"] is None
    assert ("Стр. 1: у строки № 1 акта «Кладка перегородок» есть единица и объём, но нет цены и стоимости. "
            "Это не позиция, и это не заголовок группы: следующая строка не входит в неё по номеру. "
            "Её объём не учтён.") in got["warnings"]


def test_positions_without_a_number_are_not_merged_across_acts():
    records = [_record("c", "3", "2026-02-28", [("", "Устройство стен", "м3", 1.0, 100.0)]),
               _record("d", "4", "2026-02-28", [("", "Устройство стен", "м3", 2.0, 200.0)])]
    got = acts.accumulated(records, "2026-03-31")
    assert sorted(p["quantity"] for p in got["positions"]) == [1.0, 2.0]


def test_without_a_date_on_every_edition_the_edition_uploaded_last_is_in_force():
    earlier = _record("a", "2", "2026-02-28", [(*WALLS, 5.0, 500.0)], date="2026-03-05",
                      uploaded="2026-03-01T09:00:00", filename="прежний.pdf")
    later = _record("b", "2", "2026-02-28", [(*WALLS, 6.0, 600.0)], uploaded="2026-03-02T09:00:00",
                    filename="без даты.pdf")
    later["act"]["date"] = None
    got = acts.accumulated([later, earlier], "2026-03-31")
    assert [p["quantity"] for p in got["positions"]] == [6.0]
    note = got["replaced"]["a" * 64]
    assert note.startswith("Заменён: в карточке есть загруженная позже редакция акта КС-2 № 2")
    assert "действующей считается загруженная последней" in note


NOT_HEADING = ("Стр. 1: у строки № 2 акта «Кладка перегородок» есть единица и объём, но нет цены и стоимости. "
               "Это не позиция, и это не заголовок группы: следующая строка не входит в неё по номеру. "
               "Её объём не учтён.")


@pytest.mark.parametrize("table_total", [None, ""])
def test_a_row_with_a_volume_and_no_cost_at_the_end_of_the_table_is_named(table_total):
    # С «Итого» таблицы заголовок решается на нём, без «Итого» — в конце таблицы.
    rows = (("1", "1.1", "Устройство стен", "м3", "0,5", "8 000,00", "4 000,00"),
            ("2", "2.1", "Кладка перегородок", "м2", "10,0", "", ""))
    got = _act(rows=rows, table_total=table_total)
    assert _rows(got["act"]) == [(1, "1.1", "м3", 0.5, "work", 4000.0)]
    assert NOT_HEADING in got["warnings"]


@pytest.mark.parametrize("closing", [("", "", "Раздел № 2. Кровля", "", "", "", ""),
                                     ("", "", "Итого по разделу 1", "", "", "", "")])
def test_a_new_section_or_a_section_total_settles_a_row_with_a_volume_and_no_cost(closing):
    rows = (("1", ".", "Группа А", "", "", "", ""),
            ("2", "2.1", "Кладка перегородок", "м2", "10,0", "", ""),
            closing,
            # Номер позиции продолжает строку 2.1, но раздел уже закрыт: заголовком она не становится.
            ("3", "2.1.1", "Устройство кровли", "м2", "5,0", "800,00", "4 000,00"))
    got = _act(rows=rows)
    position, = got["act"]["positions"]
    assert NOT_HEADING in got["warnings"]
    if closing[2].startswith("Раздел"):
        assert (position["section"], position["group"]) == ("Раздел № 2. Кровля", None)
    else:
        assert position["group"] == "Группа А"


def test_acts_with_one_last_number_in_a_longer_number_are_two_acts():
    one = _record("a", "1/2026", "2026-01-31", [(*WALLS, 1.0, 100.0)])
    two = _record("b", "2/2026", "2026-02-28", [(*WALLS, 2.0, 200.0)])
    again = _record("c", "№ 02/2026", "2026-02-28", [(*WALLS, 2.0, 200.0)], uploaded="2026-02-11T10:00:00")
    got = acts.accumulated([one, two, again], "2026-03-31")
    assert got["replaced"] == {} and list(got["copies"]) == ["b" * 64]
    walls, = got["positions"]
    assert walls["quantity"] == 3.0
    # Период КС-6а «КС-2 № 2026» к двум разным актам не подставляется.
    import developaid_contract_act_dates as act_dates
    dated = act_dates._dates("2026", [one, two], [])
    assert dated["end"] is None and dated["reason"].startswith("в карточке несколько актов КС-2 № 2026")


def _in_section(record, section):
    for p in record["act"]["positions"]:
        p["section"] = section
    return record


def test_one_section_printed_with_another_ending_is_one_section_and_a_position_without_it_joins_it():
    records = [_in_section(_record("a", "1", "2026-01-31", [(*WALLS, 1.0, 100.0)]), "Раздел № 5. Монтаж конструкций"),
               _in_section(_record("b", "2", "2026-02-28", [(*WALLS, 2.0, 200.0)]), "Раздел № 5. Монтаж конструкции"),
               _in_section(_record("c", "3", "2026-02-28", [(*WALLS, 4.0, 400.0)]), None)]
    got = acts.accumulated(records, "2026-03-31")
    walls, = got["positions"]
    assert (walls["quantity"], [x["act"] for x in walls["parts"]]) == (7.0, ["1", "2", "3"])
    assert got["warnings"] == []


def test_a_position_without_its_section_is_not_guessed_between_two_sections():
    records = [_in_section(_record("a", "1", "2026-01-31", [(*WALLS, 1.0, 100.0)]), "Раздел № 1. Корпус 1"),
               _in_section(_record("b", "2", "2026-02-28", [(*WALLS, 2.0, 200.0)]), "Раздел № 2. Корпус 2"),
               _in_section(_record("c", "3", "2026-02-28", [(*WALLS, 4.0, 400.0)]), None)]
    got = acts.accumulated(records, "2026-03-31")
    assert sorted(p["quantity"] for p in got["positions"]) == [1.0, 2.0, 4.0]
    assert got["warnings"] == ["Позиция 1.1 «Устройство стен» в акте № 3 прочитана без раздела, а в карточке она "
                               "есть в разделах Раздел № 1. Корпус 1, Раздел № 2. Корпус 2: к какому разделу "
                               "отнести её объём, не ясно, он показан отдельно."]


def test_a_table_total_before_tax_is_named_as_such_and_not_as_unread_rows():
    got = _act(total="4 880,00", table_total="4 000,00")
    assert got["act"]["total"] == 4880.0 and got["act"]["table_total"] == 4000.0
    assert ("Строка «Итого» таблицы акта 4 000,00 не равна строке «Итого по акту» 4 880,00. Позиции прочитаны "
            "все; разница может быть налогом или коэффициентом — проверьте акт.") in got["warnings"]
    assert not any(w.startswith("Сумма позиций акта") for w in got["warnings"])


def test_a_numbered_position_printed_with_another_name_is_summed_by_its_number_and_named():
    records = [_record("a", "1", "2026-01-31", [("1.1", "Устройство стен", "м3", 1.0, 100.0)]),
               _record("b", "2", "2026-02-28", [("1.1", "Устройство стены", "м3", 2.0, 200.0)])]
    got = acts.accumulated(records, "2026-03-31")
    walls, = got["positions"]
    assert walls["quantity"] == 3.0 and walls["name"] == "Устройство стен"
    assert got["warnings"] == ["У позиции 1.1 в актах разное название: «Устройство стен» — № 1; «Устройство стены» "
                               "— № 2. Объёмы сложены по номеру позиции по смете; проверьте, одна ли это работа."]
