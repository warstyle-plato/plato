"""Право аренды участка — аренда земли, а не продажа; аренда помещения — не ЗИК.

Формулировки взяты с живой выдачи ГИС Торгов (раздел «Торги · Москва»).
Рубрика процедуры «Аренда и продажа земельных участков» общая — вид решает
название лота.
"""
from auction_search.adapters.torgi_gov import classify
from auction_search.classifier import classify_lot
from auction_search.models import LotKind

LAND_PROCEDURE = {"code": "ZK", "name": "Аренда и продажа земельных участков · Электронный аукцион"}
LEASE_PROCEDURE = {"code": "PA", "name": "Аренда, безвозмездное пользование, доверительное управление имуществом"}


def card(name, description="", category="Земельные участки", bidd=LAND_PROCEDURE):
    return {"lotName": name, "lotDescription": description,
            "category": {"name": category}, "biddType": bidd}


def test_the_right_to_lease_a_parcel_is_a_land_lease():
    kind, _ = classify(card(
        "Право заключения договора аренды земельного участка по адресу: город Москва, "
        "вн.тер.г. муниципальный округ Ново-Переделкино"))
    assert kind is LotKind.LAND_LEASE


def test_a_parcel_sold_under_the_shared_procedure_stays_a_sale():
    kind, _ = classify(card(
        "Продажа земельного участка, Московская область, г.о. Наро-Фоминский, Бекасово",
        "Участок расположен рядом с земельным участком, находящимся в аренде"))
    assert kind is LotKind.LAND_SALE


def test_a_premises_lease_is_not_a_property_complex():
    for name in ("Аренда нежилого помещения площадью 54,3 кв. м",
                 "Право заключения договора аренды имущества"):
        kind, _ = classify(card(name, category="Нежилые помещения", bidd=LEASE_PROCEDURE))
        assert kind is LotKind.OTHER, name


def test_other_platforms_read_the_same_rule():
    procedure = "Аренда и продажа земельных участков"
    assert classify_lot("Продажа земельного участка", procedure) is LotKind.LAND_SALE
    assert classify_lot("Право на заключение договора аренды земельного участка", procedure) \
        is LotKind.LAND_LEASE
    assert classify_lot("Аренда нежилого помещения") is LotKind.OTHER
