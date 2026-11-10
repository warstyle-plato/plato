"""Позиции Расчёта предлагаются строкам ГПР по корпусу, части здания, виду работ и этажу.

Неуверенное соответствие уходит на проверку с причиной, а не угадывается. Расчёт
и график выдуманы: репозиторий публичный, документы владельца в него не попадают.
"""
from __future__ import annotations

import developaid_contract_files as files
import developaid_contract_schedule_links as links


def _line(code, name, start="", finish=""):
    return {"code": code, "name": name, "start": start or None, "finish": finish or None,
            "parent": code.rsplit(".", 1)[0] if "." in code else None}


SCHEDULE = {"lines": [
    _line("1", "Мобилизация", "2026-01-01", "2026-01-05"),
    _line("1.1", "Мобилизация", "2026-01-01", "2026-01-05"),
    _line("2", "Строительство подземной части", "2026-01-06", "2026-02-28"),
    _line("2.1", "Корпус 1", "2026-01-06", "2026-02-28"),
    _line("2.1.1", "Устройство фундаментной плиты", "2026-01-06", "2026-01-20"),
    _line("2.1.2", "Устройство стен подземной части", "2026-01-21", "2026-02-10"),
    _line("2.1.3", "Устройство лестниц", "2026-02-11", "2026-02-28"),
    _line("2.2", "Автостоянка", "2026-01-06", "2026-02-28"),
    _line("2.2.1", "Устройство плиты покрытия", "2026-02-01", "2026-02-28"),
    _line("3", "Строительство надземной части", "2026-03-01", "2026-04-30"),
    _line("3.1", "Монолитные работы К1", "2026-03-01", "2026-04-30"),
    _line("3.1.1", "Возведение вертикальных конструкций 1-ого этажа", "2026-03-01", "2026-03-10"),
    _line("3.1.2", "устройство плиты перекрытия 1-го этажа", "2026-03-11", "2026-03-15"),
    _line("3.1.3", "Возведение вертикальных конструкций 2-ого этажа", "2026-03-16", "2026-03-20"),
    _line("3.1.4", "Устройство лестниц", "2026-03-01", "2026-04-30"),
    # Корпус 2 пронумерован разделом 4, которого в графике нет: часть здания не названа.
    _line("4.1", "Монолитные работы К2", "2026-03-01", "2026-04-30"),
    _line("4.1.1", "Возведение вертикальных конструкций 1-ого этажа", "2026-03-01", "2026-03-10"),
]}
UNDER, OVER = "Корпус 1. Подземная часть", "Корпус 1. Надземная часть (выше отм. 0.000)"


def _position(number, name, section="", group="", total=1000.0):
    return {"number": number, "name": name, "unit": "м3", "section": section,
            "group": {"name": group} if group else None, "amount": {"total": total}}


ESTIMATE = {"positions": [
    _position("1.1", "Мобилизация", "Организация строительной площадки"),
    _position("2.1", "Устройство фундаментной плиты", UNDER),
    _position("3.1", "Устройство стен", OVER, total=1500.0),
    _position("3.2", "Устройство стен 2-го этажа", OVER),
    _position("4.1", "Устройство стен", "Корпус 2. Надземная часть"),
    _position("5.1", "Гидроизоляция фундаментов корпусов 1, 2", "Подземная часть"),
    _position("6.1", "Устройство пандуса", "Автостоянка"),
    _position("7.1", "Прочие работы", UNDER),
    _position("8.1", "Устройство лестниц", "Корпус 1"),
]}


def _by_number(result):
    return {p["number"]: p for p in result["positions"]}


def test_clear_positions_are_proposed_and_a_coarse_one_is_split_by_duration():
    found = _by_number(links.propose(ESTIMATE, SCHEDULE))
    assert [line["code"] for line in found["1.1"]["lines"]] == ["1.1"]
    assert [line["code"] for line in found["2.1"]["lines"]] == ["2.1.1"]
    walls = found["3.1"]
    assert walls["status"] == "proposed" and [line["code"] for line in walls["lines"]] == ["3.1.1", "3.1.3"]
    assert [round(line["share"], 4) for line in walls["lines"]] == [round(10 / 15, 4), round(5 / 15, 4)]
    assert walls["assumption"] == links.SHARE_ASSUMPTION
    floor = found["3.2"]
    assert [line["code"] for line in floor["lines"]] == ["3.1.3"] and floor["assumption"] == ""


def test_an_unsure_position_goes_to_review_with_its_reason():
    found = _by_number(links.propose(ESTIMATE, SCHEDULE))
    assert all(found[n]["status"] == "review" and found[n]["lines"] == [] for n in ("4.1", "5.1", "6.1", "7.1", "8.1"))
    assert found["4.1"]["reason"] == (
        "Строка графика 4.1.1 подходит по объекту «корпус 2» и виду работ, но в графике не сказано, подземная "
        "это часть или надземная: строки пронумерованы под разделом 4, а самого раздела в графике нет.")
    assert "нескольким объектам (корпус 1, корпус 2)" in found["5.1"]["reason"]
    assert found["6.1"]["reason"] == "В графике нет строки «пандус» для объекта «автостоянка» в подземной части."
    assert found["7.1"]["reason"] == "Вид работ по названию позиции не определён."
    assert found["8.1"]["reason"].endswith("для объекта «корпус 1» есть в графике в обеих частях.")


def test_an_agreement_position_without_a_line_is_extra_scope_without_a_term():
    result = links.propose(ESTIMATE, SCHEDULE, agreement=True)
    ramp = _by_number(result)["6.1"]
    assert ramp["status"] == "extra" and ramp["reason"].startswith("Дополнительный объём без срока")
    assert result["counts"] == {"confirmed": 0, "proposed": 4, "review": 4, "extra": 1}


def test_schedule_lines_without_positions_are_listed():
    result = links.propose(ESTIMATE, SCHEDULE)
    assert [line["code"] for line in result["lines_without_positions"]] == [
        "2.1.2", "2.1.3", "2.2.1", "3.1.2", "3.1.4", "4.1.1"]
    nothing = links.propose(ESTIMATE, None)
    assert {p["status"] for p in nothing["positions"]} == {"review"}
    assert nothing["positions"][0]["reason"].startswith("График производства работ этой или прежней редакции")


def test_each_estimate_is_compared_with_the_schedule_in_force_at_its_edition():
    first, second = ({"positions": [_position("3.1", "Устройство стен", OVER)]} for _ in range(2))
    records = [{"title": "Договор № 1 от 01.09.2025", "estimates": [first]},
               {"title": "Дополнительное соглашение № 1 от 01.02.2026", "agreement": {"number": "1"},
                "schedule": SCHEDULE, "estimates": [second]},
               {"title": "Дополнительное соглашение № 2 от 01.03.2026", "agreement": {"number": "2"},
                "estimates": [first]}]
    in_force = [(r["title"][-10:], s and s["title"][-10:]) for r, _, _, s in files._in_force(records)]
    assert in_force == [("01.09.2025", None), ("01.02.2026", "01.02.2026"), ("01.03.2026", "01.02.2026")]


# --- связь по номеру и названию ---------------------------------------------------

def _facade(code, name, section, start="2026-08-01", finish="2027-02-28", parent=None):
    return {**_line(code, name, start, finish), "section": section,
            **({"parent": parent} if parent else {})}


FACADES = {"lines": [
    _facade("4", "Монтаж светопрозрачных конструкций", "Корпус 1", "", ""),
    _facade("4.1", "(В-3) Витраж из алюминиевого профиля", "Корпус 1"),
    # Своя полоса у 4.1 — работа, а не заголовок: 4.1.1 пронумерована под ней, но относится к 4.
    _facade("4.1.1", "Оконный блок витражной системы В-3", "Корпус 1", parent="4"),
    # Шум соседней графы в начале названия строки.
    _facade("4.2", "Х 12 (В-8) Витраж из алюминиевого профиля", "Корпус 1"),
    _facade("6.1", "(В-3) Витраж из алюминиевого профиля", "Корпус 2"),
    _facade("7.1", "(ОГ-4) Ограждение кровли", "Корпус 2"),
    _facade("7.1", "(В-1) Витраж из алюминиевого профиля", "Корпус 2"),
    _facade("8.1", "(Ф1) Облицовка панелями", "Корпус 2", "", ""),
    _facade("5.1", "Устройство стен", "Корпус 1. Надземная часть"),
]}


def _facade_position(number, name, section, group=None):
    return {**_position(number, name, section), "group": group}


GLAZING = {"number": "4.1", "name": "(В-3) Витраж из алюминиевого профиля или аналог"}
FACADE_ESTIMATE = {"positions": [
    _facade_position("4.1", GLAZING["name"], "Корпус 1 этаж 1-9"),
    _facade_position("4.1.1", "Оконный блок витражной системы В-3, поворотно-откидной", "Корпус 1 этаж 1-9"),
    # Этапы под заголовком расчёта 4.1: строки графика с их номерами нет, есть строка заголовка.
    _facade_position("4.1.2", "В-3. Герметизация швов и изоляция", "Корпус 1 этаж 1-9", GLAZING),
    _facade_position("4.2", "(В-8) Витраж из алюминиевого профиля", "Корпус 1 этаж 1-9"),
    # Тот же номер и название, но в графике это другой корпус: не вид работ, а проверка.
    _facade_position("6.1.2", "В-3. Герметизация швов и изоляция", "Корпус 1 этаж 1-9",
                     {"number": "6.1", "name": GLAZING["name"]}),
    _facade_position("7.1", "(В-1) Витраж из алюминиевого профиля", "Корпус 2 этаж 1-7"),
    _facade_position("8.1", "(Ф1) Облицовка панелями", "Корпус 2 этаж 1-7"),
    _facade_position("9.1", "(В-9) Витражная система", "Корпус 2 этаж 1-7"),
    _facade_position("5.1", "Устройство стен", "Корпус 1. Подземная часть"),
]}


def test_a_position_numbered_and_named_like_a_line_gets_that_line():
    found = _by_number(links.propose(FACADE_ESTIMATE, FACADES))
    assert {n: [line["code"] for line in found[n]["lines"]] for n in ("4.1", "4.1.1", "4.1.2", "4.2")} == {
        "4.1": ["4.1"], "4.1.1": ["4.1.1"], "4.1.2": ["4.1"], "4.2": ["4.2"]}
    assert all(found[n]["status"] == "proposed" and found[n]["assumption"] == "" for n in ("4.1", "4.1.1", "4.1.2"))


def test_a_repeated_number_another_building_or_part_or_no_dates_go_to_review_not_to_the_kind_of_work():
    found = _by_number(links.propose(FACADE_ESTIMATE, FACADES))
    assert found["6.1.2"]["status"] == "review" and found["6.1.2"]["lines"] == []
    assert found["6.1.2"]["reason"] == (
        "Строка графика 6.1 совпадает с позицией по номеру и названию, но в графике она относится к объекту "
        "«корпус 2», а в расчёте позиция стоит в разделе объекта «корпус 1».")
    assert found["7.1"]["reason"] == ("В графике 2 строки с номером 7.1: номер повторяется, поэтому связь по нему "
                                      "не определить, пока в графике не исправят нумерацию.")
    assert found["8.1"]["reason"] == "У строки графика 8.1 нет дат начала и окончания."
    assert found["5.1"]["status"] == "review" and found["5.1"]["reason"] == (
        "Строка графика 5.1 совпадает с позицией по номеру и названию, но в графике она относится к надземной "
        "части, а в расчёте позиция стоит в подземной части.")
    # Ни номера, ни названия в графике нет, а вида работ среди монолитных нет: на проверку.
    assert found["9.1"]["reason"] == "Вид работ по названию позиции не определён."


def test_a_name_only_starting_alike_is_not_the_same_line():
    assert links._same_name("(В-3) Витраж из алюминиевого профиля",
                            "(В-3) Витраж из алюминиевого профиля")
    assert not links._same_name("(В-3) Витражная система", "(В-8) Витражная система")
    assert not links._same_name("", "Витражная система")
