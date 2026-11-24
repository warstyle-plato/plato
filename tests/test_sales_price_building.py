"""Ценовые вопросы сравнивают квартиры только внутри явного корпуса. Синтетика."""

from __future__ import annotations

import datetime as dt

import pytest

from market_search import chessboard, sales_dialogue, sales_questions


UPLOADED = "2026-11-02"


def row(unit, rate=80_000, *, signed="2026-09-01", rooms="2К", product="Квартира"):
    return {"unit": unit, "contract": f"Тест {unit}", "signed": signed,
            "rooms": rooms, "product": product, "area": 50,
            "amount": rate * 50, "escrow_paid": rate * 50,
            "payment_variant": "Рассрочка"}


def peers(corpus, rates=(70_000, 80_000, 90_000), **kwargs):
    return [row(f"корп {corpus} кв.{i}", rate, **kwargs)
            for i, rate in enumerate(rates, 501)]


def target(rate=80_000, unit="корп 3 кв.509", **kwargs):
    return row(unit, rate, signed="2026-10-20", **kwargs)


def price_questions(rows, *, asked=None, uploaded=UPLOADED, today=UPLOADED):
    return [q for q in sales_questions.questions(None, {"rows": rows}, uploaded, today, asked)
            if q["kind"] == "price"]


def expensive_peers():
    return peers(1, (120_000, 140_000, 160_000)) + peers(2, (120_000, 140_000, 160_000))


def test_cheaper_building_is_not_compared_with_expensive_buildings():
    rows = expensive_peers() + peers(3) + [target()]
    assert price_questions(rows) == []
    assert price_questions(list(reversed(rows))) == []


def test_real_discount_uses_same_building_median_and_names_it():
    rows = expensive_peers() + peers(3, (70_000, 80_000, 150_000)) + [target(60_000)]
    [question] = price_questions(rows)
    assert question == {
        "key": "price:Тест корп 3 кв.509:2026-10-20", "kind": "price",
        "text": "Договор на корп 3 кв.509 от 20.10: цена метра 60 тыс. ₽ — на "
                "25% ниже медианы по договорам 2К в корпусе 3 за три месяца "
                "(80 тыс. ₽). Были особые условия?",
    }


def test_other_buildings_do_not_supply_missing_same_building_peers():
    assert price_questions(expensive_peers() + peers(3)[:2] + [target(50_000)]) == []


@pytest.mark.parametrize("unit", ["", "кв.509", "башня Пример кв.509",
                                  "корп 3 / корп 1 кв.509", "3 корпус, 2 корпус кв.509",
                                  "корп 3А кв.509", "корп 3.1 кв.509", "корп 3/1 кв.509",
                                  "3А корпус кв.509", "3.1 корпус кв.509", "3/1 корпус кв.509"])
def test_unknown_or_conflicting_building_has_no_price_comparator(unit):
    assert price_questions(expensive_peers() + peers(3) + [target(50_000, unit)]) == []


def test_unknown_and_conflicting_peer_buildings_do_not_reach_minimum():
    unclear = [row(unit, 140_000) for unit in
               ("кв.511", "башня Пример кв.512", "корп 3 / корп 1 кв.513")]
    assert price_questions(peers(3)[:2] + unclear + [target(50_000)]) == []


@pytest.mark.parametrize("unit", ["корп 3 / корп 1 кв.509", "корп 3А кв.509",
                                  "корп 3.1 кв.509", "корп 1 кв.509", "кв.509"])
def test_conflicting_contract_building_is_suppressed_before_source_reconciliation(unit):
    low = target(50_000)
    unclear = dict(low, unit=unit)
    for pair in ([low, unclear], [unclear, low]):
        assert price_questions(peers(3) + pair) == []
    # Неоднозначный договор не служит и третьим ценовым ориентиром.
    same = peers(3)
    unclear_peer = dict(same[-1], unit=unit)
    for pair in ([same[-1], unclear_peer], [unclear_peer, same[-1]]):
        assert price_questions(same[:2] + pair + [low]) == []


def test_ambiguous_building_does_not_suppress_money_or_unknown_terms():
    low = dict(target(50_000), unit="корп 3 / корп 1 кв.509", escrow_paid=0,
               payment_variant="синтетическая неизвестная схема")
    found = sales_questions.questions(None, {"rows": peers(3) + [low]}, UPLOADED, UPLOADED)
    assert [q["kind"] for q in found] == ["money", "terms"]


def test_explicit_building_reuses_canonical_number_and_accepts_repeated_same_corpus():
    same = [row("корп. 03 кв.501", 100_000), row("3 корпус кв.502", 100_000),
            row("корпус 3, корпус 03 кв.503", 100_000)]
    [question] = price_questions(same + [target(70_000, "корпус 003 кв.509")])
    assert "в корпусе 3" in question["text"]
    assert "30% ниже медианы" in question["text"]
    assert chessboard.explicit_building("башня Пример кв.509") == ""


@pytest.mark.parametrize("rate,expected", [(85_000, False), (84_999.99, True),
                                          (100_000, False), (120_000, False)])
def test_same_building_discount_threshold_stays_strictly_over_fifteen_percent(rate, expected):
    assert bool(price_questions(peers(3, (100_000,) * 3) + [target(rate)])) is expected


@pytest.mark.parametrize("rooms", ["1К", "3К", ""])
def test_room_groups_do_not_supply_missing_peers(rooms):
    other_rooms = peers(3, (140_000,) * 3, rooms=rooms)
    assert price_questions(peers(3)[:2] + other_rooms + [target(50_000)]) == []


@pytest.mark.parametrize("product", ["Машиноместа", "Кладовые", "Коммерческие площади"])
def test_other_products_do_not_supply_apartment_peers(product):
    assert price_questions(peers(3)[:2] + peers(3, product=product) + [target(50_000)]) == []
    assert price_questions(peers(3) + [target(50_000, product=product)]) == []


def test_apartment_product_aliases_keep_the_existing_canonical_group():
    [question] = price_questions(peers(3, product="Квартиры") + [target(50_000)])
    assert "в корпусе 3" in question["text"]


def test_duplicate_contracts_do_not_inflate_peer_count():
    two = peers(3)[:2]
    assert price_questions(two + [dict(two[0]), dict(two[1]), target(50_000)]) == []
    rows = peers(3) + [target(50_000)]
    assert price_questions(rows + [dict(r) for r in rows]) == price_questions(rows)


@pytest.mark.parametrize("changed", [{"area": 60}, {"amount": 8_000_000},
                                     {"contract_price_per_sqm": 123_000}])
def test_conflicting_price_facts_remain_excluded(changed):
    low = target(50_000)
    assert price_questions(peers(3) + [low, dict(low, **changed)]) == []
    same = peers(3)
    assert price_questions(same + [dict(same[0], **changed), low]) == []


@pytest.mark.parametrize("storage", ["asked", "dialogue"])
def test_legacy_price_keys_suppress_reasking_after_comparator_and_wording_correction(tmp_path, storage):
    low = target(50_000)
    legacy = {"key": "price:Тест корп 3 кв.509:2026-10-20", "kind": "price",
              "text": "Договор на корп 3 кв.509: цена метра ниже средней по договорам 2К."}
    if storage == "asked":
        sales_questions.remember(tmp_path, "Синтетический проект", [legacy], "2026-10-25")
        path = sales_questions._asked_path(tmp_path, "Синтетический проект")
        asked = set(sales_questions.load_asked(tmp_path, "Синтетический проект"))
    else:
        sales_dialogue.prepare(tmp_path, "Синтетический проект", -999, [legacy], "2026-10-25")
        path = sales_dialogue._path(tmp_path, "Синтетический проект")
        asked = sales_dialogue.asked_keys(tmp_path, "Синтетический проект")
    saved = path.read_bytes()
    rows = expensive_peers() + peers(3) + [low]
    assert price_questions(rows)[0]["key"] == legacy["key"]
    assert price_questions(rows, asked=asked) == []
    # Уточнение цены и записи корпуса не создаёт новый ключ договора.
    corrected = dict(low, unit="3 корпус кв.509", amount=2_000_000)
    assert price_questions(expensive_peers() + peers(3) + [corrected], asked=asked) == []
    assert path.read_bytes() == saved


def test_new_price_question_is_remembered_with_the_same_legacy_key(tmp_path):
    rows = peers(3) + [target(50_000)]
    found = price_questions(rows)
    sales_questions.remember(tmp_path, "Синтетический проект", found, UPLOADED)
    asked = set(sales_questions.load_asked(tmp_path, "Синтетический проект"))
    assert asked == {"price:Тест корп 3 кв.509:2026-10-20"}
    assert price_questions(rows, asked=asked, today="2026-11-03") == []


@pytest.mark.parametrize("age,expected", [(30, True), (31, False)])
def test_target_age_limit_is_unchanged(age, expected):
    signed = (dt.date.fromisoformat(UPLOADED) - dt.timedelta(days=age)).isoformat()
    low = dict(target(50_000), signed=signed)
    assert bool(price_questions(peers(3) + [low])) is expected


@pytest.mark.parametrize("age,expected", [(90, True), (91, False), (-1, False)])
def test_peer_window_stays_relative_to_upload_day(age, expected):
    signed = (dt.date.fromisoformat(UPLOADED) - dt.timedelta(days=age)).isoformat()
    same = peers(3, signed=signed)
    assert bool(price_questions(same + [target(50_000)])) is expected


def test_price_check_keeps_existing_freshness_semantics_for_an_old_export():
    rows = peers(3) + [target(50_000)]
    assert price_questions(rows, today="2026-11-20") == price_questions(rows)
