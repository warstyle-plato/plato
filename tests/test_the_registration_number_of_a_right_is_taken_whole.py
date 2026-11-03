"""Номер регистрации права из печатной формы берётся целиком, а не с середины.

Замер прода 15.09.2026 (0.23.80, девять складов выписок одиннадцати площадок КРТ
с живым лотом): записей права 149, ИСКАЛЕЧЕНЫ 56, и все 56 — из печатной формы;
обе XML-формы (77 записей) целы. Печатная даёт 72 записи права, цела 16 — врут
четыре из пяти.

Три дефекта, и каждый проверяется здесь на структуре ЖИВОГО документа:

33 записи несли обрывок кадастрового номера вместо номера регистрации. Образец
искал «прогон цифр, дефисов и косых не короче семи», двоеточие в класс не
входило — и в «Собственность 77:01:0003027:1049-77/051/2021-1» он брал
«0003027», а вид забирал «Собственность 77:01:». Цена не в подписи: номер и дату
берут в СВОЙ запрос в ЕГРН за именем, которого эта форма не раскрывает, — а
обрывок, похожий на номер, хуже пустого поля.

23 записи несли видом права заголовок соседнего раздела: сбор значения кончается
на строке с двоеточием, а «Сведения об осуществлении государственной регистрации
сделки, права без необходимого в силу закона согласия третьего лица, органа:» в
форме переносится на три строки, и двоеточием кончается только третья. Клетка
при этом говорила «не зарегистрировано» — то есть права нет.

2 записи: форма объявила раздел 2 отсутствующим, а права разобраны. У
77:05:0012007:17 их пять, и из-за первого свод территории говорил «право
зарегистрировано, имени в этом виде выписки нет» — прямая инверсия того, что
чинилось в своде: там зарегистрированное показывалось незарегистрированным,
здесь наоборот.

Запуск: python3 -m pytest tests/test_the_registration_number_of_a_right_is_taken_whole.py -q
"""

from __future__ import annotations

import re

from auction_search import egrn_extracts, egrn_print_form

from egrn_fixtures import ABSENT_NOTE, LIVE, LIVE_RIGHT_NUMBERS, with_right


def test_the_examples_are_the_shapes_the_old_rule_broke_on():
    """Предохранитель: без двоеточия в номере проверка ниже не значит ничего.

    Прежний образец не умел переходить двоеточие — значит номер, в котором его
    нет, он брал целиком и был прав. Взяв в примеры только такие формы, мы
    получили бы зелёную проверку на сломанном разборе.
    """
    assert any(":" in number for number in LIVE_RIGHT_NUMBERS)
    broken = re.compile(r"\b(\d[\d\-/]{6,})\b")  # прежнее правило, дословно
    for number in LIVE_RIGHT_NUMBERS:
        if ":" not in number:
            continue
        got = broken.search(number)
        assert got and got.group(1) != number, (
            f"прежнее правило взяло бы {number!r} целиком — пример не тот")


def test_the_registration_number_is_read_whole_even_when_it_starts_with_a_cadastral_one():
    """Номер регистрации бывает с кадастровым номером в начале — он часть номера.

    Формы сняты с живых XML-выписок; документ вокруг клетки настоящий.
    """
    for number in LIVE_RIGHT_NUMBERS:
        record = egrn_print_form.read_text(with_right(
            f"Собственность\n{number}\n18.06.2021 08:55:34\n"))
        right = (record["rights"] or [{}])[0]
        assert right.get("type") == "Собственность", (number, right)
        assert right.get("number") == number, (number, right)
        assert right.get("date") == "18.06.2021", (number, right)
        assert egrn_extracts.owner_state(record) == "withheld", number


def test_the_heading_of_the_next_section_does_not_become_a_kind_of_right():
    """«Не зарегистрировано» — ответ полный, и права по нему нет.

    Утаскивает заголовок сам живой документ: клетка заменена на одну строку, а
    перенос заголовка по словам в снимке настоящий.
    """
    record = egrn_print_form.read_text(with_right("не зарегистрировано\n"))
    assert record["rights"] == []
    assert egrn_extracts.owner_state(record) == "unregistered"
    assert record["rights_outside_section"] == []


def test_a_section_declared_absent_beats_our_parse_but_is_not_dropped_silently():
    """Форма сказала «раздела 2 нет» — значит права нет, что бы мы ни выловили.

    Выловленное уходит своим полем: молча выброшенное читается как его
    отсутствие. На экран оно не идёт намеренно — это НАШ артефакт разбора, а не
    ответ документа, и показанное рядом с ответом реестра читалось бы как факт
    об объекте.
    """
    text = with_right("Собственность\n77:06:0012015:1312-77/051/2022-2\n"
                      "18.06.2021 08:55:34\n")
    text = text.replace("Особые отметки:\n", "Особые отметки:\n" + ABSENT_NOTE + "\n", 1)

    record = egrn_print_form.read_text(text)
    assert record["rights_section"] == "absent"
    assert record["rights"] == []
    assert egrn_extracts.owner_state(record) == "unregistered"

    outside = record["rights_outside_section"]
    assert [right["number"] for right in outside] == [
        "77:06:0012015:1312-77/051/2022-2"]

    # Предохранитель: тот же документ БЕЗ объявленного отсутствия раздела право
    # читает — иначе проверка зелена на разборе, который прав не видит вовсе.
    present = egrn_print_form.read_text(with_right(
        "Собственность\n77:06:0012015:1312-77/051/2022-2\n18.06.2021 08:55:34\n"))
    assert [right["number"] for right in present["rights"]] == [
        "77:06:0012015:1312-77/051/2022-2"]
    assert present["rights_outside_section"] == []


def test_the_live_document_still_reads_as_before():
    """Приёмка «ничего лишнего не сдвинулось»: у живой выписки номер без двоеточий.

    Его прежнее правило брало целиком и было право, и правка обязана оставить
    ответ тем же — иначе чинёное сломало нечинёное.
    """
    record = egrn_print_form.read_text(LIVE)
    assert [right["number"] for right in record["rights"]] == [
        "77-77/005-77/009/277/2016-603/2"]
    assert record["rights"][0]["date"] == "23.12.2016"
    assert record["rights"][0]["type"] == "Собственность"
    assert egrn_extracts.owner_state(record) == "withheld"


def test_the_reader_version_grew_so_the_store_rereads():
    """Починка читателя до прочитанных лотов доезжает только с новой версией.

    Хранимая производная расходится с правилом молча: 0.23.71 научил читать
    краткую форму, а на 1-й Горловской собственники появились лишь после того,
    как лот перечитали рукой.
    """
    from auction_search import egrn_archive
    assert egrn_archive.READER_VERSION >= 3
