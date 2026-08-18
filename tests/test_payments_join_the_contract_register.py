"""Оплаты берутся из полного реестра, а статья подтягивается по договору.

Оплаты лежат в двух местах, и ни одно не годится в одиночку.

Реестр платежей РСС полон: 2 251 платёж, 4 077,2 млн ₽, 32 месяца по июнь
2026, ни одной строки без даты, плюс источник платежа — свои или заёмные. Но
несёт он только код РСС, а тот сваливает разное в один код.

Реестр договоров финансовой модели несёт код БДДС и раскладывается без остатка
— но отстаёт на два месяца: 3 622,3 млн ₽ против 4 077,2. Ровно эта разница и
была «расхождением источников», которое мы искали в методике: 04.2026 — 239,9
против 136,4, май — 166,0 против нуля, июнь — 185,4 против нуля.

Сшивка по паре «контрагент + договор», суженной кодом РСС платежа, разносит
98,0% денег.
"""

from __future__ import annotations

import datetime

import pytest

import developaid_actuals as actuals


def _payments(rows):
    return {
        "rows": rows,
        "total": sum(r["amount"] for r in rows),
        "undated": 0.0,
        "own_funds": sum(r["amount"] for r in rows if r.get("own_funds")),
        "first": None, "last": None,
    }


def _register(rows):
    return {"rows": rows, "paid": 0.0}


def _row(counterparty, contract, bdds, estimate_code):
    return {"counterparty": counterparty, "contract": contract,
            "bdds_code": bdds, "estimate_code": estimate_code,
            "paid_amount": 0.0, "paid_date": None, "act_amount": 0.0,
            "act_date": None}


def _payment(contractor, contract, estimate_code, amount, day=1, **extra):
    return {"contractor": contractor, "contract": contract,
            "estimate_code": estimate_code, "amount": amount,
            "date": datetime.date(2026, 3, day), **extra}


def test_the_contract_carries_the_article_to_the_payment():
    """Договор опознан — статья приходит с него, а не гадается по коду РСС."""
    register = _register([_row("СтройКо", "№12", "2.2.2.3.4", "2.2.1.4")])
    payments = _payments([_payment("СтройКо", "№ 12", "2.2.1.4", 100e6)])

    result = actuals.payments_by_article(payments, register)

    assert result["matched"]["по договору и коду РСС"] == pytest.approx(100e6)
    assert result["capex_by_article"]["main_under"][
        datetime.date(2026, 3, 1)] == pytest.approx(100e6)


def test_the_key_ignores_punctuation_and_case():
    """«№ 12» и «№12», «СтройКо» и «СТРОЙКО» — один договор."""
    register = _register([_row("СТРОЙКО", "№12", "2.2.2.3.4", "2.2.1.4")])
    payments = _payments([_payment("СтройКо  ", "№ 12", "2.2.1.4", 50e6)])

    result = actuals.payments_by_article(payments, register)

    assert result["mapped"] == pytest.approx(50e6)


def test_one_contract_over_several_articles_is_narrowed_by_the_code():
    """Договор покрывает несколько статей — сужаем кодом РСС самого платежа.

    Без этого пара «контрагент + договор» ведёт к двум кодам БДДС сразу, и
    платёж уходит в неразнесённое, хотя его статья известна.
    """
    register = _register([
        _row("ГенПодряд", "№7", "2.2.2.3.4", "2.2.1.4"),   # фундаментная плита
        _row("ГенПодряд", "№7", "2.2.2.4.1", "2.2.2.1"),   # несущие надземной
    ])
    payments = _payments([
        _payment("ГенПодряд", "№7", "2.2.1.4", 300e6),
        _payment("ГенПодряд", "№7", "2.2.2.1", 200e6, day=2),
    ])

    result = actuals.payments_by_article(payments, register)
    capex = result["capex_by_article"]

    assert capex["main_under"][datetime.date(2026, 3, 1)] == pytest.approx(300e6)
    assert capex["main_above"][datetime.date(2026, 3, 1)] == pytest.approx(200e6)
    assert not result["unresolved"]


def test_the_crosswalk_beats_the_register_when_they_disagree():
    """Перекодировка берётся с листа «статьи_БДДС», а не выводится из реестра.

    В реестре «Код банк» местами разошёлся с листом: фундаментная плита
    помечена кодом РСС 2.2.2.1, хотя по листу это 2.2.1.4. Выведенное из
    реестра соответствие делает 2.2.2.1 сборным, и 284,6 млн ₽ уходят в
    «неоднозначное» на пустом месте.
    """
    register = _register([
        _row("Прочий", "№1", "2.2.2.3.4", "2.2.2.1"),   # ошибка кода в реестре
        _row("Прочий", "№2", "2.2.2.4.1", "2.2.2.1"),
    ])
    crosswalk = {"rows": [], "articles_by_estimate_code": {"2.2.2.1": {"main_above"}}}
    payments = _payments([_payment("НеИзвестный", "№99", "2.2.2.1", 90e6)])

    without = actuals.payments_by_article(payments, register)
    assert without["mapped"] == 0.0

    with_sheet = actuals.payments_by_article(payments, register, crosswalk=crosswalk)
    assert with_sheet["matched"]["по коду РСС"] == pytest.approx(90e6)


def test_a_genuinely_mixed_code_stays_unresolved():
    """Код, который и по листу ведёт к двум статьям, разносить нечем.

    РСС 2.2.1.10 держит и вознаграждение генподрядчика, и содержание
    стройплощадки. Долями это не делится — деньги называются суммой и причиной.
    """
    register = _register([])
    crosswalk = {"rows": [],
                 "articles_by_estimate_code": {"2.2.1.10": {"gc_fee", "site_maintenance"}}}
    payments = _payments([_payment("Кто-то", "№5", "2.2.1.10", 71.3e6)])

    result = actuals.payments_by_article(payments, register, crosswalk=crosswalk)

    assert result["mapped"] == 0.0
    assert any("2.2.1.10" in reason for reason in result["unresolved"])


def test_every_step_of_the_join_names_itself():
    """Отчёт говорит, чем именно разнесён каждый рубль.

    Разница между «по договору» и «по коду РСС» — это разница между фактом и
    приближением, и в отчёте она должна быть видна.
    """
    register = _register([_row("СтройКо", "№12", "2.2.2.3.4", "2.2.1.4")])
    crosswalk = {"rows": [], "articles_by_estimate_code": {"2.2.6.1": {"landscaping"}}}
    payments = _payments([
        _payment("СтройКо", "№12", "2.2.1.4", 100e6),
        _payment("Озеленитель", "№3", "2.2.6.1", 40e6, day=2),
    ])

    result = actuals.payments_by_article(payments, register, crosswalk=crosswalk)

    assert result["matched"]["по договору и коду РСС"] == pytest.approx(100e6)
    assert result["matched"]["по коду РСС"] == pytest.approx(40e6)
    assert result["mapped"] == pytest.approx(140e6)


def test_the_source_of_funds_is_kept():
    """Свои деньги процентов не несут — значит источник платежа надо читать."""
    payments = _payments([
        _payment("А", "№1", "2.2.1.4", 100e6, source="Собственные средства",
                 own_funds=True),
        _payment("Б", "№2", "2.2.1.4", 300e6, source="Заемные средства",
                 own_funds=False, day=2),
    ])

    assert payments["own_funds"] == pytest.approx(100e6)
