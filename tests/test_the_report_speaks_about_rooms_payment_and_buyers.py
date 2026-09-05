"""Комнатность, способы оплаты и состав покупателей в отчёте о рынке.

«Дополняй отчёты тем, что нам интересно… комнаты и каналы продаж и способы
оплаты ты провафлил» (владелец, 04.09.2026). Всё это месячный отчёт «Пульса»
даёт по каждому проекту, а мы брали из него только цену, темп и остаток.
"""

from __future__ import annotations

from market_search.market_reference import MoscowMarket
from market_search.metrics import BUILDERS, channel_block, payment_block, rooms_block


CITY = MoscowMarket(
    {
        "last_month": "2026-08",
        "current": {"Бизнес": {"projects": 90, "price_median": 560_700, "mortgage_median": 48.2}},
    }
)

SUBJECT = {
    "segment": "Бизнес",
    "room_mix": {
        "studio": {"sold": 1, "rem": 10, "total": 24, "price": 763_700},
        "r1": {"sold": 3, "rem": 62, "total": 87, "price": 795_800},
        "r3": {"sold": 0, "rem": 76, "total": 87, "price": 729_700},
    },
    "bands": {"28-40": 3, "40-55": 1},
    "mortgage": 28.6,
    "mortgage_at": "2026-07",
    "legal": 12.5,
    "legal_at": "2026-07",
    "resale": 2,
    "banks": {"Сбербанк России": 3, "ВТБ": 1},
}

PEERS = [
    {
        "name": "Сосед А",
        "room_mix": {"studio": {"sold": 4, "rem": 96}, "r3": {"sold": 9, "rem": 78}},
        "bands": {"28-40": 5, "55-85": 5},
        "mortgage": 52.0,
        "legal": 4.3,
    },
    {
        "name": "Сосед Б",
        "room_mix": {"r1": {"sold": 6, "rem": 40}},
        "mortgage": 61.0,
        "legal": 0.0,
    },
]


def test_rooms_show_what_sells_against_what_is_left() -> None:
    """Вымывание — это доля в проданном против доли в остатке."""
    block = rooms_block(SUBJECT, PEERS, CITY)
    own = block.subject["rooms"]
    assert own["studio"]["sold_share_pct"] == 25.0
    assert own["r1"]["sold_share_pct"] == 75.0
    # Трёшки не продаются и копятся в остатке — это и есть ответ блока.
    assert own["r3"]["sold_share_pct"] == 0.0
    assert own["r3"]["rem_share_pct"] > own["r1"]["rem_share_pct"]
    assert own["studio"]["title"] == "студии"

    # У соседей складывается ОБЪЁМ: проект на тысячу лотов и проект на сорок
    # иначе весили бы одинаково.
    theirs = block.peers["rooms"]
    assert block.peers["projects"] == 2
    assert theirs["r1"]["sold"] == 6
    assert theirs["studio"]["sold"] == 4


def test_area_bands_stand_next_to_the_rooms() -> None:
    """Двушка бывает и 44 м², и 84 — комнатность на вопрос о метраже не
    отвечает."""
    block = rooms_block(SUBJECT, PEERS, CITY)
    assert block.subject["bands"]["28-40"]["share_pct"] == 75.0
    assert block.subject["bands_deals"] == 4
    assert block.peers["bands"]["55-85"]["share_pct"] == 50.0


def test_an_empty_room_mix_says_so_instead_of_showing_zero() -> None:
    block = rooms_block({"segment": "Бизнес"}, [], CITY)
    assert not block.subject
    assert any("не раскрыта" in note for note in block.notes)


def test_payment_puts_the_project_against_neighbours_and_the_city() -> None:
    block = payment_block(SUBJECT, PEERS, CITY)
    assert block.subject["mortgage_pct"] == 28.6
    assert block.subject["observed_at"] == "2026-07"
    assert block.peers["median"] == 56.5
    assert block.city["mortgage_median_pct"] == 48.2
    # Банки — из выписок: отчёт даёт долю, но не говорит, кому платят.
    assert block.subject["banks"]["Сбербанк России"]["share_pct"] == 75.0


def test_no_sales_means_no_mortgage_share_not_a_zero_one() -> None:
    """Доля считается от сделок месяца: нет сделок — нет доли."""
    block = payment_block({"segment": "Бизнес"}, PEERS, CITY)
    assert "mortgage_pct" not in block.subject
    assert any("продаж не было" in note for note in block.notes)


def test_buyers_split_persons_from_companies() -> None:
    block = channel_block(SUBJECT, PEERS, CITY)
    assert block.subject["company_pct"] == 12.5
    assert block.subject["person_pct"] == 87.5
    assert block.subject["resale_deals"] == 2
    assert block.peers["median"] == 2.1


def test_the_new_sections_are_offered_in_the_cabinet() -> None:
    """Раздел, который считается, но не предлагается, — раздела нет."""
    from market_search.cabinet import CABINET_PAGE, SECTIONS

    codes = [code for code, _, _ in SECTIONS]
    for code in ("rooms", "payment", "channel"):
        assert code in codes, f"раздел {code} не предлагается в конструкторе"
        assert code in BUILDERS
    assert "roomsTable(b)" in CABINET_PAGE
    assert "banksTable(b)" in CABINET_PAGE


def test_an_unknown_section_does_not_borrow_the_absorption_numbers() -> None:
    """Ветка «всё остальное» — не утверждение о величине.

    Пока последним `else` стояло поглощение, любой новый раздел рисовал бы
    метры в месяц под своим заголовком, и выглядело бы это посчитанным.
    """
    from market_search.cabinet import CABINET_PAGE

    assert "b.code==='absorption'){" in CABINET_PAGE
    assert "на экране ещё не описан" in CABINET_PAGE
