"""Предложение по акции строится на двух половинах, а не на одной.

«Платон может сделать предложения по акционным программам для Кутузов сити,
чтобы поднять продажи? У тебя же есть данные по факт продажам и ценам»
(владелец, 08.09.2026).

Мог — но из половины картины. Свод продаж несёт вымывание, воронку и эскроу и
ничего не знает про условия соседей; рыночный отчёт несёт цены и рассрочку и
ничего не знает про наши продажи. Промо-программа живёт ровно на их
пересечении, и спрошенный из любой одной он предложил бы обоснованно и мимо.

Теперь условия рынка — раздел свода продаж: наша рассрочка и рассрочка соседей
ПО РАЙОНУ. Отбор соседей здесь другой, чем в отчёте о рынке (там радиус и
класс), и это сказано в самом разделе: два разных набора под одним словом
«соседи» читались бы как один.

Измерено на живом своде (08.09.2026): Кутузов Сити даёт ПВ 5 % на 15 мес. и
все четыре программы — на базовой цене, то есть мягче всех в Можайском районе;
Верейская 41 берёт за рассрочку удорожание, Родина Парк просит ПВ 20 %. Зато
все наши четыре программы стоят жёсткой датой «до 31.12.2027» — такой срок
тает каждый месяц, а в рекламе выглядит как обычный; так живёт 27 проектов из
155 в своде.

Запуск: python3 -m pytest tests/test_the_promo_question_has_both_halves.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_search.installments import Installments  # noqa: E402
from market_search.installments_import import term_is_deadline  # noqa: E402

# Сборщик вопроса — тот же, что у проверки бюджета: он зовёт настоящий
# `SALES_SURFACE.message` страницы. Второй сборщик того же вопроса однажды
# разошёлся бы с первым, и оба выглядели бы верными.
from test_the_question_fits_the_limit import _fat_summary, _question  # noqa: E402


TERMS = {
    "source": "TrendAgent, свод рассрочек по Москве",
    "saved_at": "2026-09-08",
    "peers_rule": "соседи по району справочника, не выборка отчёта о рынке",
    "district": "Можайский",
    "known": 2,
    "total": 4,
    "ours": {"installment": True, "installment_down_payment_pct": 5.0,
             "installment_term_months": 15, "installment_programs": 4,
             "installment_term_deadline_programs": 4,
             "installment_keys_before_payment": False,
             "installment_price_terms": {"базовая": 4}},
    "peers": [
        {"name": "Верейская 41", "installment": True,
         "installment_down_payment_pct": 20.0, "installment_term_months": 12,
         "installment_programs": 1, "installment_term_deadline_programs": 0,
         "installment_keys_before_payment": False,
         "installment_price_terms": {"удорожание": 1}},
        {"name": "Родина Парк", "installment": True,
         "installment_down_payment_pct": 20.0, "installment_term_months": 17,
         "installment_programs": 5, "installment_term_deadline_programs": 5,
         "installment_keys_before_payment": False,
         "installment_price_terms": {"базовая": 5}},
    ],
    "unknown": ["Веер", "СЕТ"],
}


def _slim() -> dict:
    """Обычный проект: свод, в который раздел помещается.

    Полный свод `_fat_summary` намеренно не влезает в предел — на нём
    проверяется бюджет, и раздел там честно уходит в «не поместилось».
    """
    return {
        "project": "Кутузов Сити",
        "total": {"contracts": 76, "area": 4321.5, "amount": 2_345_300_000,
                  "price_per_sqm": 542_700, "escrow": 1_988_000_000,
                  "escrow_share": 0.848},
        "market_terms": TERMS,
    }


def test_the_term_tied_to_a_date_is_told_from_the_term_from_the_deal() -> None:
    """«до 31.12.2027» тает, «2 года» — нет, а выглядят одинаково."""
    assert term_is_deadline("до 31.12.2027") is True
    assert term_is_deadline("2 года") is False
    assert term_is_deadline("до ввода в эксплуатацию") is False
    assert term_is_deadline("") is False


def test_the_bundled_digest_knows_our_own_project_and_its_district() -> None:
    """База отвечает по живому проекту, а не только по фикстуре."""
    from market_search.registry import ProjectRegistry

    store = Installments.bundled()
    registry = ProjectRegistry.load(ProjectRegistry.bundled_directory())
    terms = store.district_terms("Кутузов Сити", registry)
    assert terms["district"] == "Можайский"
    ours = terms["ours"]
    assert ours["installment"] is True
    # Все программы жёсткой датой — то, что и делает наш срок тающим.
    assert ours["installment_term_deadline_programs"] == ours["installment_programs"]
    assert terms["known"] >= 2 and terms["total"] > terms["known"]
    # Незнание не выдаётся за ответ: сосед вне свода стоит отдельным списком.
    assert terms["unknown"] and all(
        name not in [p["name"] for p in terms["peers"]] for name in terms["unknown"])
    # Правило отбора соседей названо: это НЕ выборка отчёта о рынке.
    assert "не выборка отчёта о рынке" in terms["peers_rule"]
    # Проекта нет в справочнике — это причина, а не пустой ответ.
    assert store.district_terms("Такого проекта нет", registry)["missing"]


def test_the_terms_reach_the_question() -> None:
    """Раздел доезжает до Платона со своими числами и своим охватом."""
    message = _question(_slim())
    assert "УСЛОВИЯ РЫНКА" in message
    assert "TrendAgent" in message and "срез 2026-09-08" in message
    assert "не выборка отчёта о рынке" in message
    assert "условия известны у 2 соседей из 4" in message
    assert "«не знаем», а не «рассрочки не дают»" in message
    assert "НАША РАССРОЧКА" in message and "ПВ 5,0%" in message
    assert "жёсткой датой — такой срок тает" in message
    assert "Верейская 41" in message and "удорожание 1" in message
    # Свода рассрочек нет — раздела нет вовсе, и пустой строки тоже.
    plain = _question({k: v for k, v in _slim().items() if k != "market_terms"})
    assert "УСЛОВИЯ РЫНКА" not in plain

    # А на полностью загруженном проекте раздел не влезает — и это НАЗВАНО,
    # а не выброшено молча: молчаливая обрезка читается как отсутствие данных.
    fat = _question({**_fat_summary(), "market_terms": TERMS})
    assert "НЕ ПОМЕСТИЛОСЬ В ВОПРОС" in fat and "условия рынка" in fat


def test_the_promo_ask_names_what_we_do_not_know() -> None:
    """Эластичность спроса не измерена ничем — и это сказано в самом вопросе."""
    page = (ROOT / "market_search" / "cabinet.py").read_text(encoding="utf-8")
    asks = page[page.index("const SALES_ASKS=["):]
    asks = asks[:asks.index("\n];") + 3]
    assert "Предложи акции" in asks
    promo = asks[asks.index("Предложи акции"):]
    promo = promo[:promo.index("{chip:", 10)] if "{chip:" in promo[10:] else promo
    assert "условия рынка" in promo, "вопрос обязан назвать раздел, из которого берёт"
    assert "не выдумывай" in promo and "неизвестным" in promo
    assert "Числа не пересчитывай" in promo

    # И сам вопрос собирается тем же кодом страницы, а не пересказом.
    message = _question(_slim(), ask="Предложи две акции.")
    assert "ВОПРОС: Предложи две акции." in message


def test_the_screen_shows_the_same_terms(tmp_path) -> None:
    """Посчитанное на сервере, но не показанное, неотличимо от непосчитанного.

    Раздел уезжает в вопрос Платону — значит человек обязан видеть то же
    самое: иначе он читает ответ про условия, которых на экране нет.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch
    from market_search import cabinet

    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page()
            errors: list[str] = []
            tab.on("pageerror", lambda exc: errors.append(str(exc)))
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            # Зовём ВЕСЬ отчёт, а не один рисовальщик: раздел, посчитанный и
            # нарисованный, но не поставленный на экран, неотличим от
            # непосчитанного — а проверять надо ту поверхность, на которую
            # жалуются.
            whole = tab.evaluate(
                "d => { const box = document.createElement('div');"
                " box.id = 'sales'; document.body.appendChild(box);"
                " renderSales(d); return box.innerHTML; }", _slim())
            drawn = tab.evaluate("d => salesTermsBlock(d)", _slim())
            silent = tab.evaluate(
                "d => salesTermsBlock(d)",
                {"project": "Наш дом", "market_terms": {
                    "ours": {}, "peers": [], "missing": "проект не найден в справочнике"}})
            none_at_all = tab.evaluate("d => salesTermsBlock(d)", {"project": "Наш дом"})
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert 'id="sb-terms"' in whole and "Рассрочка: мы и соседи" in whole
    assert "Верейская 41" in whole
    assert "Кутузов Сити" in drawn and "Верейская 41" in drawn
    assert "Программ жёсткой датой" in drawn
    assert "4 из 4" in drawn, "все наши программы стоят жёсткой датой"
    assert "условия известны у 2 из 4" in drawn
    # Фраза целиком: «не знаем» без второй половины читается как «нет».
    assert "Веер" in drawn
    assert "это «не знаем», а не «рассрочки не дают»" in drawn
    assert "не выборка отчёта о рынке" in drawn
    assert "TrendAgent" in drawn and "2026-09-08" in drawn
    # Свод есть, а про проект молчит — названная причина, а не пустая таблица.
    assert "проект не найден в справочнике" in silent and "<table" not in silent
    # Свода нет вовсе — раздела нет, и пустой строки тоже.
    assert none_at_all == ""
