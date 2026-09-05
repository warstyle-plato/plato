"""Разбор месячного отчёта «Пульс Продаж Новостроек».

Книга — 177 МБ и в репозиторий не кладётся, поэтому здесь проверяется разбор
по частям: перевод чисел Excel, тип объекта, имя банка, полосы площади и сборка
сводов. Живой прогон по книге делается руками командой импорта — он печатает
сверку выписок с отчётом и число месяцев.
"""

from __future__ import annotations

from market_search import pulse_report_import as imp


def test_a_month_is_a_date_and_not_a_quantity() -> None:
    """`46235` — это август 2026, а не количество чего-либо."""
    assert imp.month_of(46235) == "2026-08"
    assert imp.month_of("46235") == "2026-08"
    assert imp.month_of(45658) == "2025-01"
    assert imp.month_of("2026-08") == "2026-08"
    assert imp.month_of("не месяц") is None
    assert imp.date_of(46235) == "2026-08-01"


def test_a_share_comes_as_a_part_of_one() -> None:
    """0,103 в книге — это 10,3 %, а не 0,1 %."""
    assert imp.percent(0.103) == 10.3
    assert imp.percent(1) == 100.0
    assert imp.percent(None) is None


def test_a_storage_room_is_not_a_flat() -> None:
    """Без типа объекта кладовка встаёт в один ряд с квартирой.

    На живом августе у одного проекта из 295 сделок 130 попали в полосу «до
    28 м²», а 246 покупателей оказались юрлицами — это паркинг, а не рынок
    жилья.
    """
    assert imp.kind_of("Квартира") == "living"
    assert imp.kind_of("Апартамент") == "living"
    assert imp.kind_of("Кладовка") == "storage"
    assert imp.kind_of("Машиноместо") == "parking"
    assert imp.kind_of("") == "unknown"


def test_one_bank_is_not_three() -> None:
    """Один Сбербанк приезжает тремя написаниями в одном месяце."""
    names = {
        imp.bank_of('ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО "СБЕРБАНК РОССИИ"'),
        imp.bank_of('Публичное акционерное общество "Сбербанк России", ИНН: 7707083893'),
    }
    assert names == {"Сбербанк России"}
    # Аббревиатура остаётся аббревиатурой: `.title()` делает из «ВТБ» «Втб».
    assert imp.bank_of("Банк ВТБ (публичное акционерное общество)") == "ВТБ"
    # А внутри «Альфа-Банк» слово «банк» — часть имени, и дефис для `\b` такая
    # же граница, как пробел.
    assert imp.bank_of('АО "АЛЬФА-БАНК"') == "Альфа-банк"
    # И «банк» посреди названия — тоже часть имени: без него остаётся
    # «Всероссийский развития регионов».
    assert (
        imp.bank_of('Акционерным Обществом Всероссийский банк развития регионов')
        == "Всероссийский Банк Развития Регионов"
    )


def test_the_top_band_has_no_ceiling() -> None:
    """Самая большая квартира иначе выпала бы вместе со своим договором."""
    assert imp.band_of(27.9) == "0-28"
    assert imp.band_of(28) == "28-40"
    assert imp.band_of(168.6) == "120+"
    assert imp.band_of(0) is None
    assert imp.band_of(None) is None


def test_a_room_block_is_nine_columns_further_along() -> None:
    assert imp._shift("AN", 0) == "AN"
    assert imp._shift("AN", 8) == "AV"
    assert imp._shift("Z", 1) == "AA"
    assert imp._shift("CG", 8) == "CO"


def test_the_shop_window_and_the_deal_stand_side_by_side() -> None:
    """Цена прайса и цена по ДДУ — разные величины, и одна не заменяет другую.

    В самом отчёте средняя цена по ДДУ заполнена в 552 строках из 17 586, а в
    августе ни в одной: сводить их в одно поле значило бы подписать витрину
    словом «сделка».
    """
    passport = {"1": {"name": "А", "segment": "Бизнес", "okrug": "ЗАО"}}
    series = {
        "1": {
            "2026-08": {"price": 700_000, "ddu": 640_000, "disc": 8.5, "sold": 4, "rem": 100},
        }
    }
    market = imp.build_market(passport, series, months=["2026-08"], source="проба")
    snapshot = market["current"]["Бизнес"]
    assert snapshot["price_median"] == 700_000
    assert snapshot["ddu_median"] == 640_000
    assert snapshot["disc_median"] == 8.5

    empty = imp.build_market(
        passport,
        {"1": {"2026-08": {"price": 700_000, "sold": 4}}},
        months=["2026-08"],
        source="проба",
    )
    # Сделки нет — это «не знаем», а не «равна витрине».
    assert empty["current"]["Бизнес"]["ddu_median"] is None
    assert empty["current"]["Бизнес"]["ddu_projects"] == 0


def test_the_deals_summary_checks_itself_against_the_report() -> None:
    """Свод, посчитанный по другой дате, выглядел бы так же уверенно."""
    deals = {
        "1|2026-08": {
            "complex_id": "1",
            "month": "2026-08",
            "deals": 4,
            "bands": {"28-40": 3, "40-55": 1},
            "banks": {"ВТБ": 2},
        },
        "2|2026-08": {
            "complex_id": "2",
            "month": "2026-08",
            "deals": 9,
            "bands": {},
            "banks": {},
        },
    }
    series = {"1": {"2026-08": {"sold": 4}}, "2": {"2026-08": {"sold": 7}}}
    summary = imp.build_deals(deals, series, months=["2026-08"])
    assert summary["check"] == {"compared": 2, "matched": 1}
    assert summary["projects"]["1"]["bands"] == {"28-40": 3, "40-55": 1}


def test_a_zero_discount_is_an_answer_and_does_not_speak_for_the_market() -> None:
    """Медиана скидки по всем объявившим выходит нулём — её дают не все.

    На августе это 194 проекта с числом, из них 88 с ненулевой скидкой и
    медианой 13,9 %. Одна медиана по всем читается как «скидок на рынке нет»,
    поэтому рядом стоит, сколько проектов её дают и какая она у них.
    """
    passport = {
        "1": {"name": "А", "segment": "Бизнес"},
        "2": {"name": "Б", "segment": "Бизнес"},
        "3": {"name": "В", "segment": "Бизнес"},
        "4": {"name": "Г", "segment": "Бизнес"},
        "5": {"name": "Д", "segment": "Бизнес"},
    }
    series = {
        "1": {"2026-08": {"price": 700_000, "disc": 0.0}},
        "2": {"2026-08": {"price": 700_000, "disc": 0.0}},
        "3": {"2026-08": {"price": 700_000, "disc": 12.0}},
        "4": {"2026-08": {"price": 700_000, "disc": 16.0}},
        "5": {"2026-08": {"price": 700_000, "disc": 0.0}},
    }
    snapshot = imp.build_market(passport, series, months=["2026-08"], source="проба")
    row = snapshot["current"]["Бизнес"]
    assert row["disc_median"] == 0.0
    assert row["disc_projects"] == 5
    assert row["disc_offering"] == 2
    assert row["disc_median_offered"] == 14.0

    # Пустая колонка — не нулевая скидка: проект без числа в счёт не идёт.
    quiet = imp.build_market(
        {"1": {"name": "А", "segment": "Бизнес"}},
        {"1": {"2026-08": {"price": 700_000}}},
        months=["2026-08"],
        source="проба",
    )
    assert quiet["current"]["Бизнес"]["disc_projects"] == 0
    assert quiet["current"]["Бизнес"]["disc_median"] is None
