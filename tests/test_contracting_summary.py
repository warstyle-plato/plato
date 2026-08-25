"""Свод продаж действующего проекта считается по первичке, а не по своду.

Файл ЦФ несёт два листа, которые нельзя путать: «Контрактация» — обогащённый
реестр договоров (вариант оплаты, брокер, премии, график эскроу), «1С_Факт» —
проводки, где 76.06 это заключение ДДУ, а 008.01 — движение денег на эскроу.

Проверяется здесь то, что на живом файле уже подводило.

Реестра владельца в репозитории нет и не будет: в нём ФИО покупателей. Форма
листа воспроизведена синтетикой — правило проверяется правилом, а не чужими
персональными данными.

Запуск: python3 -m pytest tests/test_contracting_summary.py -q
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import contracting  # noqa: E402

HEAD = ["Квартал", "Год", "Месяц", "Объект недвижимости", "Корпус",
        "Тип объекта недвижимости", "Вид отделки", "Проектная S", "Договор",
        "Тип договора", "Состояние договора", "Сумма договор", "Дата договора",
        "Покупатель", "Шт", "Цена ДДУ за кв. м", "Вариант оплаты",
        "Оплачено премии ОП ", "Брокеры", "% брокера", "Наименование брокера",
        "% оплаты", "остаток к оплате", "оплачено эскроу всего"]

DEALS = [
    # квартира через брокера, рассрочка: оплачено меньше суммы договора
    ["3Q 2025", 2025, 45900, "Квартира", "корп.1 кв.1", "жилая", "без отделки", 40.0,
     "ДДУ №1-1-1/ГР от 12.08.2025", "ДДУ", "Действующий", 24_000_000, "12.08.2025",
     "Иванов Иван Иванович", 1, 600_000, "Рассрочка 20% ПВ и далее по 200 000 в месяц",
     0, 1_200_000, 0.05, "БРОКЕР ООО", 0.25, 18_000_000, 6_000_000],
    # квартира напрямую, 100% оплата
    ["3Q 2025", 2025, 45900, "Квартира", "корп.1 кв.2", "жилая", "без отделки", 60.0,
     "ДДУ №1-1-2/ГР от 20.08.2025", "ДДУ", "Действующий", 30_000_000, "20.08.2025",
     "Петров Пётр Петрович", 1, 500_000, "1.0", 90_000, 0, None, "", 1.0, 0, 30_000_000],
    # машино-место юрлицу через брокера без заполненной комиссии
    [None, 2025, 45930, "Машиноместа", None, "нежилая", " ", 14.0,
     "ДДУ №0001М/ГР от 05.09.2025", "ДДУ", "Действующий", 4_000_000, "05.09.2025",
     "Аэробилдинг ООО", 1, 285_714, "1.0", 0, 0, 0.05, "ТИХИЙ БРОКЕР ООО", 1.0, 0, 4_000_000],
]

LEDGER = [
    ["Год", "Квартал", "Месяц", "Дата", "Документ", "Организация", "Счет Дт",
     "Субконто1 Дт", "Субконто2 Дт", "Субконто3 Дт", "Счет Кт", "Субконто1 Кт",
     "Субконто2 Кт", "Субконто3 Кт", "Сумма", "Содержание"],
    [2025, "3Q 2025", 45900, "12.08.2025", "Операция", "СЗ", "76.06", "Иванов",
     "ДДУ №1-1-1/ГР от 12.08.2025", None, "86.02", "ЖК", None, None, 24_000_000, "корп.1 кв.1 S=40 м2"],
    [2025, "3Q 2025", 45900, "15.08.2025", "Операция", "СЗ", "008.01", "Иванов",
     "ДДУ №1-1-1/ГР от 12.08.2025", None, None, None, None, None, 6_000_000, None],
    # расторгнутый договор: начисление, деньги, сторно и возврат
    [2025, "3Q 2025", 45930, "09.09.2025", "Операция", "СЗ", "76.06", "Сидоров",
     "ДДУ №1-2-9/ГР от 09.09.2025", None, "86.02", "ЖК", None, None, 50_000_000, "корп.1 кв.9 S=80 м2"],
    [2025, "4Q 2025", 45991, "01.11.2025", "Операция", "СЗ", "008.01", "Сидоров",
     "ДДУ №1-2-9/ГР от 09.09.2025", None, None, None, None, None, 50_000_000, None],
    [2026, "1Q 2026", 46065, 46065, None, "СЗ", "76.06", "Сидоров",
     "Расторжение ДДУ №1-2-9/ГР от 09.09.2025", None, "86.02", "ЖК", None, None,
     -50_000_000, "корп.1 кв.9 S=80 м2"],
    [2026, "1Q 2026", 46071, 46071, None, "СЗ", "008.01", "Сидоров",
     "ДДУ №1-2-9/ГР от 09.09.2025", None, None, None, None, None, -49_800_000, None],
]


def _book() -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = contracting.SHEET_CONTRACTS
    sheet["A2"] = "Контрактация"
    sheet["A3"] = "Название проекта:"
    sheet["E3"] = "Тестовый ЖК"
    for column, title in enumerate(HEAD, start=1):
        sheet.cell(row=6, column=column, value=title)
    for index, deal in enumerate(DEALS):
        for column, value in enumerate(deal, start=1):
            sheet.cell(row=7 + index, column=column, value=value)
    ledger = book.create_sheet(contracting.SHEET_LEDGER)
    for index, row in enumerate(LEDGER, start=1):
        for column, value in enumerate(row, start=1):
            ledger.cell(row=index, column=column, value=value)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _summary():
    data = _book()
    return contracting.summarise(contracting.read_contracts(data),
                                 contracting.read_ledger(data))


def test_the_file_names_its_own_project() -> None:
    """Привязка к проекту берётся из листа, а не из выбора в кабинете."""
    got = _summary()
    assert got["project"] == "Тестовый ЖК"
    assert got["missing"] == []


def test_the_commission_share_is_measured_on_its_own_deals() -> None:
    """«Процент от наполнения» по всему проекту делит на чужие сделки.

    На живом файле это давало 4,50% вместо 7,32%: в знаменатель попадал эскроу
    прямых продаж, где комиссии нет вовсе.
    """
    brokers = _summary()["brokers"]
    assert round(brokers["amount"]) == 28_000_000
    assert round(brokers["escrow"]) == 10_000_000
    assert round(brokers["fee_of_sales"], 4) == round(1_200_000 / 28_000_000, 4)
    assert round(brokers["fee_of_escrow"], 4) == round(1_200_000 / 10_000_000, 4)
    assert brokers["fee_of_escrow"] > brokers["fee_of_sales"]


def test_an_empty_commission_is_not_a_free_broker() -> None:
    """Ноль вознаграждения при названном брокере — «не заполнено»."""
    channels = {item["channel"]: item for item in _summary()["by_channel"]}
    assert channels["ТИХИЙ БРОКЕР ООО"]["fee_unknown"] is True
    assert channels["напрямую"]["fee_unknown"] is False


def test_a_reversal_is_a_termination_with_its_own_return() -> None:
    """Сторно — расторжение, а возврат эскроу — отдельное движение.

    Складывать приход и возврат в сальдо нельзя: 50 − 49,8 даёт остаток, а не
    ноль, и вернувшиеся 49,8 млн ₽ обязаны быть видны.
    """
    terminated = _summary()["terminated"]
    assert len(terminated) == 1
    only = terminated[0]
    assert only["contract"] == "1-2-9/ГР"
    assert only["on"] == "2026-02-12"
    assert round(only["escrow_paid"]) == 50_000_000
    assert round(only["escrow_returned"]) == 49_800_000


def test_a_deal_without_a_quarter_lands_by_its_contract_date() -> None:
    """У части строк колонка квартала пуста — терять их в «прочем» нельзя."""
    months = {item["month"] for item in _summary()["dynamics"]}
    assert months == {"2025-08", "2025-09"}


def test_the_payment_variant_keeps_what_it_did_not_recognise() -> None:
    """Свободный текст раскладывается правилом, неопознанное остаётся собой."""
    assert contracting.payment_variant("Рассрочка 20% ПВ и далее по 200 000 в месяц") == "рассрочка"
    assert contracting.payment_variant("Ипотека СПБ Банка") == "ипотека"
    assert contracting.payment_variant("1.0") == "100% оплата"
    assert contracting.payment_variant("5 млн на эскроу") == "5 млн на эскроу"
    assert contracting.payment_variant("") == "не указан"


def test_the_buyer_name_never_leaves_the_reader() -> None:
    """Свод агрегатный, а вопрос Платону уходит внешнему поставщику модели.

    Остаётся признак «юрлицо»: оптовая сделка тянет среднюю цену и должна быть
    видна, а фамилия для этого не нужна.
    """
    data = _book()
    rows = contracting.read_contracts(data)["rows"]
    assert all("buyer" not in row for row in rows)
    assert [row["company_buyer"] for row in rows] == [False, False, True]
    assert _summary()["company_buyers"] == 1
