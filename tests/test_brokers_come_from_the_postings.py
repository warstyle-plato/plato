"""Канал продаж из проводок, когда колонки брокера в «Контрактации» нет.

Владелец, 01.09.2026: «почему в отчёте по продажам полностью пропали продажи
через брокеров? их как будто нет вовсе». Разбор живого файла показал: колонок
«Наименование брокера», «Брокеры» и «% брокера» в листе не стало — автор
выгрузки пересобрал умную таблицу и убрал шесть колонок. При этом 23,07 млн ₽
комиссий лежали в том же файле листом левее, проводками 1С.

Реестра владельца в репозитории нет и не будет: в нём ФИО покупателей. Форма
листов воспроизведена синтетикой.

Запуск: python3 -m pytest tests/test_brokers_come_from_the_postings.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import contracting  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def _book(*, with_broker_column: bool, postings: list[tuple[str, str, float, str]]) -> bytes:
    """Книга той же формы: «Контрактация» с шапкой в 6-й строке и «Раб.файл»."""
    import io

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = contracting.SHEET_CONTRACTS
    sheet.cell(row=3, column=1, value="Название проекта:")
    sheet.cell(row=3, column=2, value="Тестовый ЖК")
    head = ["Квартал", "Год", "Месяц", "Объект недвижимости", "Корпус", "Проектная S",
            "Договор", "Тип договора", "Состояние договора", "Сумма договор",
            "Дата договора", "Покупатель", "Шт", "Цена ДДУ за кв. м", "Вариант оплаты",
            "% оплаты", "остаток к оплате", "оплачено эскроу всего"]
    if with_broker_column:
        head += ["Брокеры", "% брокера", "Наименование брокера"]
    for i, name in enumerate(head, start=1):
        sheet.cell(row=6, column=i, value=name)
    people = [("Тагиров Шахназар Магомедович", "ДДУ №3-3-89/ГР", 36_000_000.0),
              ("Пушкин Николай Николаевич", "ДДУ №3-5-106/ГР", 20_000_000.0),
              ("Аэробилдинг ООО", "ДДУ №1-12-43/ГР", 62_000_000.0),
              ("Иванов Пётр Петрович", "ДДУ №0037М/ГР", 4_000_000.0)]
    for n, (buyer, contract, amount) in enumerate(people, start=7):
        sheet.cell(row=n, column=4, value="Квартира")
        sheet.cell(row=n, column=6, value=40.0)
        sheet.cell(row=n, column=7, value=contract)
        sheet.cell(row=n, column=10, value=amount)
        sheet.cell(row=n, column=11, value="12.08.2025")
        sheet.cell(row=n, column=12, value=buyer)
        sheet.cell(row=n, column=13, value=1)

    work = book.create_sheet(contracting.SHEET_POSTINGS)
    head2 = ["N", "Дата", "Уточнение периода", "Документ", "Организация", "Счет Дт",
             "Подразделение Дт", "Субконто1 Дт", "Субконто2 Дт", "Субконто3 Дт",
             "Счет Кт", "Субконто1 Кт", "Субконто2 Кт", "Субконто3 Кт", "Сумма", "Содержание"]
    for i, name in enumerate(head2, start=1):
        work.cell(row=14, column=i, value=name)
    for n, (article, broker, amount, content) in enumerate(postings, start=15):
        work.cell(row=n, column=8, value=article)
        work.cell(row=n, column=12, value=broker)
        work.cell(row=n, column=15, value=amount)
        work.cell(row=n, column=16, value=content)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _filled_column_book(*, postings: list[tuple[str, str, float, str]]) -> bytes:
    """Та же книга, но колонка брокера заполнена — канал прочитан из неё."""
    import io

    data = _book(with_broker_column=True, postings=postings)
    book = openpyxl.load_workbook(io.BytesIO(data))
    sheet = book[contracting.SHEET_CONTRACTS]
    sheet.cell(row=7, column=19, value=1_000_000.0)   # Брокеры
    sheet.cell(row=7, column=21, value="БРОКЕР ИЗ КОЛОНКИ ООО")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_the_channel_is_read_from_the_postings_when_the_column_is_gone() -> None:
    """Колонки нет — канал берётся из первички, а не пропадает."""
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 1_800_000.0,
         "Комиссия брокерам (5%) ДДУ Тагиров по вх.д. от 12.09.2025")])
    read = contracting.read_contracts(data)
    brokered = [row for row in read["rows"] if row["broker"]]
    assert len(brokered) == 1 and brokered[0]["broker"] == "УМНАЯ НЕДВИЖИМОСТЬ ООО"
    assert brokered[0]["broker_fee"] == 1_800_000.0
    assert brokered[0]["broker_source"] == "проводки 1С"

    said = contracting.summarise(read)
    assert said["broker_column"] is True, "плашка «канал не прочитан» кричала бы зря"
    assert said["broker_source"] == "проводки 1С", "чем прочитан канал — часть ответа"
    assert {c["channel"] for c in said["by_channel"]} == {"напрямую", "УМНАЯ НЕДВИЖИМОСТЬ ООО"}


def test_a_wrong_contract_is_caught_by_the_rate_named_in_the_payment() -> None:
    """Ставка в назначении платежа — проверка привязки, а не украшение.

    На живом файле «Комиссия брокерам (5%) ДДУ №1-12-43/ГР Аэробилдинг» сначала
    село на договор в 4,0 млн ₽: вышло бы 77% комиссии. Число выглядело обычным
    — брокер, сумма, канал, — и заметить это можно было только счётом.
    """
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "ЛЕВЧЕНКО-РЕАЛТИ ООО", 3_100_000.0,
         "Комиссия брокерам (5%) ДДУ №1-12-43/ГР Аэробилдинг по вх.д.")])
    read = contracting.read_contracts(data)
    hit = [row for row in read["rows"] if row["broker"]]
    assert len(hit) == 1, hit
    assert hit[0]["contract"] == "ДДУ №1-12-43/ГР", "комиссия села не на тот договор"
    assert abs(hit[0]["broker_fee"] / hit[0]["amount"] - 0.05) < 0.001


def test_an_unmatched_commission_is_named_not_dropped() -> None:
    """Молча выброшенная комиссия читается как её отсутствие."""
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 1_150_000.0,
         "Комиссия брокерам (5%) ДДУ Скрипченко Н.Я. по вх.д. от 31.12.2025")])
    read = contracting.read_contracts(data)
    assert not any(row["broker"] for row in read["rows"])
    assert any("не свелась" in note and "1.15" in note for note in read["missing"]), read["missing"]


def test_a_surname_inside_another_surname_is_not_a_match() -> None:
    """«Бертяев» лежит внутри «Бертяевой» — это два разных договора.

    Вольное совпадение с падежным хвостом принимается только когда подходит
    ровно одна строка: иначе комиссия мужа села бы на договор жены.
    """
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "ИННОВАЦИОННАЯ НЕДВИЖИМОСТЬ ООО", 700_000.0,
         "Комиссия брокерам (3,5%) ДДУ Пушкины по вх.д. от 04.09.2025")])
    read = contracting.read_contracts(data)
    hit = [row for row in read["rows"] if row["broker"]]
    assert len(hit) == 1 and hit[0]["contract"] == "ДДУ №3-5-106/ГР", \
        "множественное число фамилии не сведено"


def test_an_empty_column_is_not_a_read_channel() -> None:
    """Колонка на месте и пустая — та же картинка «свой отдел 100%».

    «Колонка есть» и «канал прочитан» — разные утверждения. Пока проверяли
    первое, пустая колонка молча выдавала себя за прочитанный канал.
    """
    data = _book(with_broker_column=True, postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 1_800_000.0,
         "Комиссия брокерам (5%) ДДУ Тагиров по вх.д. от 12.09.2025")])
    read = contracting.read_contracts(data)
    assert [row["broker"] for row in read["rows"] if row["broker"]] == ["УМНАЯ НЕДВИЖИМОСТЬ ООО"]


def test_the_column_wins_and_the_gap_between_two_sources_is_named() -> None:
    """Колонка заполнена — проводки её не переписывают, а расхождение называется.

    Два источника на одну величину: молча выбрать из них один нельзя — так уже
    расходились бот с сайтом и книга с движком.
    """
    data = _filled_column_book(postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 9_000_000.0,
         "Комиссия брокерам (5%) ДДУ Тагиров по вх.д. от 12.09.2025")])
    read = contracting.read_contracts(data)
    named = [row["broker"] for row in read["rows"] if row["broker"]]
    assert named == ["БРОКЕР ИЗ КОЛОНКИ ООО"], "проводки переписали колонку"
    assert any("расхождение не сведено" in note for note in read["missing"]), read["missing"]


def test_the_reader_says_what_it_read_the_channel_from() -> None:
    """Проводка появляется по акту — недавний договор брокера в ней не виден."""
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 1_800_000.0,
         "Комиссия брокерам (5%) ДДУ Тагиров по вх.д. от 12.09.2025")])
    notes = " ".join(contracting.read_contracts(data)["missing"])
    assert "прочитан из проводок" in notes
    assert "по подписанному акту" in notes, "оговорка о запаздывании потерялась"
    assert "премии" in notes, "премия своего отдела в этих строках не лежит"


def test_the_buyer_name_does_not_leave_the_reader() -> None:
    """Фамилия нужна только для сведения и наружу не идёт."""
    data = _book(with_broker_column=False, postings=[
        ("Комиссия брокерам", "УМНАЯ НЕДВИЖИМОСТЬ ООО", 1_800_000.0,
         "Комиссия брокерам (5%) ДДУ Тагиров по вх.д. от 12.09.2025")])
    for row in contracting.read_contracts(data)["rows"]:
        assert "_surname" not in row
        assert not any(isinstance(v, str) and "Тагиров" in v for v in row.values())
