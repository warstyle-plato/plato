"""Факт разносится по статьям движка кодом БДДС, а не догадкой по названию.

Ключ — код БДДС, а не код РСС. РСС сваливает в один код разное: в 2.6 сидят
технадзор, ФОТ, временные сооружения и получение РВЭ; в 2.2.1.10 —
вознаграждение генподрядчика вместе с содержанием площадки; в 2.7 — ИРД,
стадия П, стадия РД и авторский надзор разом. Разложить это по нашим статьям,
зная только код РСС, нельзя.

Соответствие снято с листа «статьи_БДДС» финансовой модели Гродненской. На её
реестре карта разносит все 3 622,3 млн ₽ оплат без остатка.
"""

from __future__ import annotations

import datetime

import pytest

import developaid_actuals as actuals


@pytest.mark.parametrize("code, article", [
    ("2.1.1.1.1", "purchase"),               # приобретение земельного участка
    ("2.1.1.3.2", "land_rights"),            # смена ВРИ
    ("2.1.1.4.1", "land_rights"),            # текущие арендные платежи
    ("2.1.2.1.3", "social"),                 # компенсации за соцобъекты
    ("2.1.2.2.2", "social"),                 # строительство ДОУ
    ("2.2.1.1", "preparation"),
    ("2.2.2.2.1", "gc_fee"),                 # вознаграждение генподрядчика
    ("2.2.2.3.4", "main_under"),             # фундаментная плита
    ("2.2.2.4.1", "main_above"),             # несущие конструкции надземной
    ("2.2.2.5.1", "main_above"),             # фасад
    ("2.2.2.7.9", "main_above"),             # монтаж вертикального транспорта
    ("2.2.5.1.5", "utilities"),              # СМР сетей водоснабжения
    ("2.2.6.1.1", "landscaping"),
    ("2.2.9.1.1", "technical_supervision"),
    ("2.2.10.1.2", "ird"),                   # разработка ДПТ
    ("2.2.10.2.1", "design_p"),
    ("2.2.10.2.2", "design_rd"),
    ("2.2.10.4.1", "author_supervision"),
    ("2.2.11.1.1", "reserve"),
    ("2.3.3.1", "marketing"),
    ("2.3.4.1", "selling"),
    ("2.4.1.1", "project_management"),
    ("2.4.5.1", "tax"),
    ("3.1.4.1.2", "financing"),              # выплата процентов по ПФ
])
def test_a_code_lands_on_its_article(code, article):
    assert actuals.article_for(code)[0] == article


def test_the_longest_prefix_wins():
    """Исключение живёт рядом с правилом и побеждает его.

    `2.2.2.3` — подземная часть целиком, но `2.2.2.3.8` внутри неё это
    содержание стройплощадки, и у него своя статья. Правило «первый совпавший
    префикс» отправило бы его в бетон.
    """
    assert actuals.article_for("2.2.2.3.4")[0] == "main_under"
    assert actuals.article_for("2.2.2.3.8")[0] == "site_maintenance"
    assert actuals.article_for("2.2.2.4.1")[0] == "main_above"
    assert actuals.article_for("2.2.2.4.5")[0] == "site_maintenance"
    # Отделка МОП разведена по частям здания: подземная и надземная.
    assert actuals.article_for("2.2.2.6.1")[0] == "main_under"
    assert actuals.article_for("2.2.2.6.2")[0] == "main_above"
    # Дизайн-проект отделки — это проектирование, а не отделка.
    assert actuals.article_for("2.2.2.8.1")[0] == "design_p"
    assert actuals.article_for("2.2.2.8.3")[0] == "main_above"


def test_an_unsplittable_code_is_refused_not_guessed():
    """Внешний генподряд идёт одной суммой — разносить его долями нельзя.

    Модель считает наземную и подземную части по разным удельным ставкам.
    Разложить общую сумму генподряда между ними значит подменить факт
    расчётом и не сказать об этом.
    """
    article, reason = actuals.article_for("2.2.2.1.1")

    assert article is None
    assert "генподряд" in reason


def test_an_unknown_code_names_itself():
    """Незнакомый код возвращается с причиной, а не молча исчезает."""
    article, reason = actuals.article_for("9.9.9")

    assert article is None
    assert "9.9.9" in reason


def test_payments_are_split_by_article_and_nothing_is_lost():
    """Разнос по статьям сходится с суммой оплат до копейки."""
    register = {
        "rows": [
            {"bdds_code": "2.1.1.1.1", "paid_amount": 950e6,
             "paid_date": datetime.date(2024, 2, 5)},
            {"bdds_code": "2.2.2.3.4", "paid_amount": 200e6,
             "paid_date": datetime.date(2025, 3, 20)},
            {"bdds_code": "2.2.2.3.4", "paid_amount": 13e6,
             "paid_date": datetime.date(2025, 3, 28)},
            {"bdds_code": "2.3.3.1", "paid_amount": 50e6,
             "paid_date": datetime.date(2025, 7, 1)},
        ],
        "paid": 1213e6,
    }

    result = actuals.articles_from_register(register)

    assert result["mapped"] == pytest.approx(result["total"])
    assert not result["unresolved"]
    capex = result["capex_by_article"]
    assert capex["purchase"][datetime.date(2024, 2, 1)] == pytest.approx(950e6)
    # Два платежа одного месяца складываются в один месяц.
    assert capex["main_under"][datetime.date(2025, 3, 1)] == pytest.approx(213e6)
    # Реклама — не CAPEX: у движка это коммерческие расходы.
    assert "marketing" not in capex
    assert result["other_by_article"]["marketing"][
        datetime.date(2025, 7, 1)] == pytest.approx(50e6)


def test_money_that_found_no_article_is_named_with_its_reason():
    """Нерасписанное не растворяется в «прочем» — у него сумма и причина."""
    register = {
        "rows": [
            {"bdds_code": "2.2.2.1.1", "paid_amount": 300e6,
             "paid_date": datetime.date(2025, 5, 1)},
            {"bdds_code": "2.2.2.3.4", "paid_amount": 100e6, "paid_date": None},
            {"bdds_code": "", "paid_amount": 7e6,
             "paid_date": datetime.date(2025, 5, 1)},
        ],
        "paid": 407e6,
    }

    result = actuals.articles_from_register(register)

    assert result["mapped"] == 0.0
    assert sum(result["unresolved"].values()) == pytest.approx(407e6)
    assert any("генподряд" in reason for reason in result["unresolved"])
    assert result["unresolved"]["платёж без даты"] == pytest.approx(100e6)


def test_every_mapped_article_exists_in_the_engine():
    """Статья, которой в движке нет, — опечатка, и она должна падать тестом.

    Карта пишется руками по чужому кодификатору; ошибка в имени статьи иначе
    проявится нулевым рядом в отчёте, а не сообщением.
    """
    import main_legacy as engine

    known = set(engine._MONTHLY_CAPEX_LABELS) | actuals._NON_CAPEX_ARTICLES
    mapped = {article for _, article in actuals._BDDS_TO_ARTICLE}

    assert mapped <= known, f"нет таких статей у движка: {sorted(mapped - known)}"
