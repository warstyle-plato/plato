"""Спрос из CRM против витрины — ответ на «почему не покупают».

Прямого ответа в выгрузке нет: поля стадии и причины отказа не существует,
«История касаний» и «Комментарий по касанию» пусты во всех сделках, а слово
«отказ» в комментарии почти всегда означает отказ дать контакты, отказ от
контрольного звонка или отказ спамщику. Счёт по нему дал бы уверенное число,
которого никто не проверит: тридцать «отказов» на живой выгрузке оказались
двумя.

Поэтому ответ собирается из РАЗРЫВА: какую площадь и какой бюджет просят —
против того, что осталось в витрине и по какой цене.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from market_search import demand

SOURCE = Path(__file__).resolve().parent.parent / "market_search" / "demand.py"


def test_a_number_is_taken_whole_not_from_the_middle() -> None:
    """«26,856 млн руб.» читалось как 856 млн — и осталось бы правдоподобным.

    Та же ошибка уже была в ценах рынка: «3 306 021 ₽/м²» читался как 306 021,
    в десять раз меньше и всё ещё внутри допустимого диапазона.
    """
    assert demand.budgets_asked("за 26,856 млн рублей") == [26_856_000.0]
    assert demand.budgets_asked("от 22,644 млн рублей") == [22_644_000.0]
    assert demand.budgets_asked("стоимостью 134 640 000 рублей") == [134_640_000.0]
    assert "(?<![\\d.,])" in SOURCE.read_text(), "граница числа не задана"


def test_a_range_gives_both_bounds() -> None:
    assert demand.areas_asked("Требуемая площадь: 55–60 кв.м") == [55.0, 60.0]
    assert demand.budgets_asked("бюджет 55–60 млн руб.") == [55e6, 60e6]


def test_a_room_is_not_a_flat() -> None:
    """«Кухня-гостиная около 25 кв. м» описывает часть лота, а не запрос."""
    assert demand.areas_asked("Интересует кухня-гостиная около 25 кв. м") == []
    assert demand.areas_asked("ванная ~6 кв. м, гардеробная 2,3 кв. м") == []
    assert demand.areas_asked("терраса 12 м², квартира 90 кв.м") == [90.0]


def test_nonsense_is_out_of_range_not_in_the_answer() -> None:
    assert demand.areas_asked("высота потолков 3,10 м") == []
    assert demand.budgets_asked("телефон 8 900 000 00 00") == []
    assert demand.areas_asked("целый этаж около 1000 кв. м") == []


def test_the_reason_for_refusal_is_not_counted() -> None:
    """Слово «отказ» в комментарии — почти всегда не отказ от покупки."""
    body = SOURCE.read_text()
    assert "отказ" in body, "почему не считаем — сказано в самом модуле"
    for guessed in ("_REFUSAL", "refusal_reason", "loss_reason"):
        assert guessed not in body, "причина отказа не выводится по словам"
    got = demand.demand_summary([], [], {"empty_columns": []})
    assert any("отказ" in note for note in got["notes"]), "оговорка не доехала"


def test_the_empty_column_that_matters_is_named() -> None:
    """Пустая «История касаний» — находка; пустая «Компания» — шум."""
    got = demand.demand_summary(
        [], [], {"empty_columns": ["История касаний с Клиентом в Сделке"]})
    assert any("История касаний" in note for note in got["notes"])
    assert all("Компания" not in note for note in got["notes"])


def test_a_request_touching_two_bands_is_counted_in_both_and_said() -> None:
    """«55–60 м²» — запрос сразу к двум полосам, и приписать его одной нельзя."""
    bands = [{"band": "40 - 55", "low": 40.0, "high": 55.0, "left_units": 10.0,
              "left_share": 0.5, "sold_share": 0.5},
             {"band": "55 - 85", "low": 55.0, "high": 85.0, "left_units": 10.0,
              "left_share": 0.5, "sold_share": 0.5}]
    deals = [{"area_min": 50.0, "area_max": 60.0, "budget_max": None, "wants": []}]
    got = demand.demand_summary(deals, bands, {})
    assert [b["asked"] for b in got["bands"]] == [1.0, 1.0]
    assert any("больше одной полосы" in note for note in got["notes"])


def test_a_request_bigger_than_the_project_is_named() -> None:
    """Просят 250 м², а самый большой лот — 168,6: это сам по себе ответ."""
    bands = [{"band": "85 - 168,6", "low": 85.0, "high": 168.6, "left_units": 5.0,
              "left_share": 1.0, "sold_share": 1.0}]
    deals = [{"area_min": 250.0, "area_max": 250.0, "budget_max": None, "wants": []}]
    got = demand.demand_summary(deals, bands, {})
    assert any("крупнее самого большого лота" in note for note in got["notes"])


def test_no_names_or_phones_leave_the_reader() -> None:
    """Комментарии полны имён и телефонов — наружу идут только числа."""
    body = SOURCE.read_text()
    kept = body[body.index("deals.append({"):body.index("# Пустыми называются")]
    for personal in ('"comment"', '"buyer"', '"name"', '"phone"', '"contact"'):
        assert personal not in kept, f"наружу уходит {personal}"


def test_the_screen_draws_the_gap_and_computes_nothing() -> None:
    page = (Path(__file__).resolve().parent.parent / "market_search" / "cabinet.py").read_text()
    start = page.index("function salesDemandBlock(")
    block = page[start:page.index("\nfunction salesTable(", start)]
    assert "b.asked_share" in block and "b.left_share" in block
    for forbidden in ("/want.deals", "/asked.length", "b.asked/"):
        assert forbidden not in block, f"экран считает сам: {forbidden}"
    # Оговорки приходят с сервера: придуманные на экране, они обещали бы разбор,
    # которого не было.
    assert "want.notes" in block


@pytest.mark.parametrize("text,expected", [
    ("рассрочка с ПВ 5%", "рассрочка"),
    ("Интерес к ипотеке", "ипотека"),
    ("скидка 5% при 100% оплате", "скидка"),
])
def test_what_they_ask_about_is_a_word_not_a_guess(text: str, expected: str) -> None:
    got = demand.demand_summary(
        [{"area_min": None, "budget_max": None,
          "wants": [name for name, pattern in demand._WANTS if pattern.search(text)]}],
        [], {})
    assert expected in [w["want"] for w in got["wants"]]


def test_the_demand_stops_at_the_budget_not_at_the_metres() -> None:
    """Полоса, которую просят чаще всех, бывает закрыта ценой — и это причина.

    Владелец, 31.08.2026, о Кутузов Сити: медиана бюджетного запроса 30 млн ₽,
    а вход в полосу 55–85 м² по цене остатка — 33,7 млн. Спрос отрезан не
    дефицитом витрины, а деньгами, и по двум полосам «просят / осталось» это
    неразличимо: обе говорят про метры.
    """
    from market_search.demand import demand_summary

    bands = [
        {"band": "28,3–40", "low": 28.3, "high": 40, "book_price_per_sqm": 614466,
         "left_share": 0.152, "left_units": 25},
        {"band": "40–55", "low": 40, "high": 55, "book_price_per_sqm": 644507,
         "left_share": 0.293, "left_units": 48},
        {"band": "55–85", "low": 55, "high": 85, "book_price_per_sqm": 612170,
         "left_share": 0.329, "left_units": 54},
        {"band": "85–168,6", "low": 85, "high": 168.6, "book_price_per_sqm": 734077,
         "left_share": 0.226, "left_units": 37},
    ]
    deals = [{"area_min": area, "area_max": area, "budget_max": budget}
             for area, budget in ((40, 30e6), (45, 30e6), (38, 25e6), (60, 45e6), (50, 32e6))]
    said = demand_summary(deals, bands)
    rows = {row["band"]: row for row in said["bands"]}
    # Вход считается по НИЖНЕЙ границе: не дотянулся до самого дешёвого лота
    # полосы — полоса закрыта целиком.
    assert round(rows["55–85"]["entry_amount"] / 1e6, 1) == 33.7
    assert rows["28,3–40"]["budget_reach_share"] == 1.0
    assert rows["85–168,6"]["budget_reach_share"] == 0.0

    cut = said["budget_cut"]
    assert round(cut["reach_sqm"]) == 49, "медианный бюджет упирается около 50 м²"
    assert cut["closed_bands"] == ["55–85", "85–168,6"]
    assert round(cut["closed_left_share"], 2) == 0.56 or cut["closed_left_share"] > 0.5

    # Полоса без цены — «не знаем», а не «бесплатно»: доля не считается вовсе.
    blind = demand_summary(deals, [{"band": "нет цены", "low": 30, "high": 50}])
    assert blind["bands"][0]["budget_reach_share"] is None
    assert blind["budget_cut"] == {}


def test_the_budget_cut_reaches_the_screen_and_the_digest() -> None:
    """Считает сервер, экран показывает — и оба говорят про деньги."""
    from market_search import cabinet

    page = cabinet.cabinet_page("sales")
    start = page.index("function salesDemandBlock(")
    block = page[start:page.index("\n}", start)]
    assert "b.budget_reach_share" in block, "третья полоса про деньги не рисуется"
    assert "want.budget_cut" in block and "Ценой закрыты полосы" in block
    from pathlib import Path

    body = (Path(__file__).resolve().parent.parent / "market_search"
            / "contracting.py").read_text()
    assert "медианный бюджет" in body and "не по деньгам" in body
