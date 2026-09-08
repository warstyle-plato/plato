"""Рассрочка соседей: чем сосед торгует помимо цены.

«Это надо положить в базу и проанализировать в отчёте» (владелец, 08.09.2026)
— про свод рассрочек TrendAgent. Он отвечает на вопрос, которого нет ни у
«Пульса», ни у bnMAP: сравнение цен у нас витрина против витрины (так и
подписано), а витрину двигает рассрочка — сосед с тем же прайсом, взносом 10 %
и годом рассрочки продаёт мягче, чем выглядит в таблице цен.

Измерено в самом файле до разбора: 1115 программ, 195 застройщиков, 580 имён
объектов; «Есть рассрочка?» Да 1024 / Нет 92; «Цена» базовая 464, со скидкой
279, с удорожанием 135. Колонка «Месяц обновления» источником свежести быть не
может — заполнена в 314 строках из 1116, и все даты весны 2025 года; свежесть
доказывают сроки самих программ («до 20.12.2026», «до 30.09.2027»), а дата
снимка берётся у файла. Совпадение с нашим справочником — 179 имён из 580,
накрыто 175 проектов из 685: это и есть охват, и он называется числом.

Запуск: python3 -m pytest tests/test_the_report_reads_the_installment_terms.py -q
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import installments_import as importer  # noqa: E402
from market_search.installments import Installments  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402
from market_search.metrics import BLOCK_INSTALLMENT, installment_block  # noqa: E402
from market_search.narrative import findings  # noqa: E402
from market_search.normalize import canonical_key  # noqa: E402
from market_search.verdict import NOTE_BUILDERS  # noqa: E402

# Настоящие номера «Пульса» из поставляемого свода: фикстуры здесь не годятся —
# проверяется, что база ЧИТАЕТСЯ, а не что словарь можно собрать руками.
RIVER_PARK = 1471   # Ривер Парк Кутузовский — рассрочка есть, взнос 20 %
ILOVE = 1226        # ILove — свод говорит «рассрочки нет»
SYDNEY = 1599       # Сидней Сити — в своде записан латиницей, «Sydney City»
ABSENT = 900_000    # такого проекта в своде нет вовсе


def test_the_bundled_digest_names_the_terms_and_its_own_coverage() -> None:
    store = Installments.bundled()
    assert store.available and store.covered > 100
    # Охват называется числом: свод накрывает четверть справочника, и без него
    # молчание про соседа читалось бы как «рассрочки не даёт».
    assert store.registry_projects > store.covered
    assert store.saved_at and store.source

    river = store.facts(RIVER_PARK)
    assert river["installment"] is True
    assert river["installment_down_payment_pct"] == 20.0
    assert river["installment_term_months"] == 18

    # Три ответа разные, и слить их нельзя.
    assert store.facts(ILOVE)["installment"] is False
    assert store.facts(ABSENT) == {}
    # Имя работает тем же ключом, что идентификатор: у bnMAP своих номеров
    # «Пульса» нет, а второго правила «это один проект» в модуле не бывает.
    assert store.facts(None, "Ривер Парк Кутузовский") == river
    # Битый или пустой файл отменяет рассрочки, а не отчёт.
    assert Installments({}).facts(RIVER_PARK) == {}


def test_a_latin_name_and_its_cyrillic_twin_are_one_project() -> None:
    """«Sydney City» и «Сидней Сити» — одна вывеска в двух алфавитах.

    Свёртка для того и написана; «c» латиницы она сводила к одному звуку, и
    пары расходились. Проверяется парами, а не строкой в исходнике: тот же
    текст стоит и у сломанной свёртки.
    """
    for latin, cyrillic in (
        ("Sydney City", "Сидней Сити"),
        ("Amber City", "Амбер Сити"),
        ("Citimix Новокосино", "Ситимикс Новокосино"),
        ("SEZAR CITY", "Сезар Сити"),
    ):
        assert canonical_key(latin) == canonical_key(cyrillic), latin
    # И «c» перед прочими буквами по-прежнему «к»: иначе «Cult» и «Культ»
    # разошлись бы ради того, ради чего правило и написано.
    assert canonical_key("Cult") == canonical_key("Культ")
    assert Installments.bundled().facts(SYDNEY).get("installment") is not None


def test_the_reader_takes_the_number_whole_and_refuses_what_is_not_a_share() -> None:
    """Разбор полей: вилка, рубли, срок датой и срок, которого нет."""
    assert importer.down_payment_pct(0.3) == 30.0
    assert importer.down_payment_pct("20.1%") == 20.1
    # У вилки берётся нижняя граница — это взнос, с которым в проект можно войти.
    assert importer.down_payment_pct("от 30% до 50%") == 30.0
    # Рублёвая сумма долей не является: доля от неизвестной цены выглядела бы
    # измеренной ровно так же, как настоящая.
    assert importer.down_payment_pct("1 600 000 р.") is None
    assert importer.down_payment_pct("Нет рассрочки") is None

    today = datetime.date(2026, 9, 8)
    assert importer.term_months("1 год") == 12
    assert importer.term_months("1.5 года") == 18
    assert importer.term_months("6 месяцев") == 6
    assert importer.term_months("до 30.09.2027", today=today) == 12
    # «до ввода в эксплуатацию» сроком не становится: ввод у каждого свой, и
    # подставить его нам нечем.
    assert importer.term_months("до ввода в эксплуатацию") is None
    assert importer.term_months("за 1 месяц до РВ") is None

    assert importer.price_term("Базовая цена со скидкой") == importer.PRICE_DISCOUNT
    assert importer.price_term("100% цена с удорожанием") == importer.PRICE_MARKUP
    assert importer.price_term("Базовая цена") == importer.PRICE_BASE
    assert importer.price_term("Нет рассрочки") is None

    # Уточнение, перенесённое на свою строку, именем не становится: без этого
    # правила в свод приезжали объекты «(3» и «(кроме этажа № -1)».
    assert importer.object_names("Level Мичуринский\n(2 корпус)") == ["Level Мичуринский"]
    assert importer.object_names("Павелецкая от Гранель корп. 2") == ["Павелецкая от Гранель"]
    assert importer.object_names("Кантемировский 1 оч\nАлиа") == ["Кантемировский", "Алиа"]
    assert importer.object_names("нет рассрочки") == []


def _blocks(subject, peers):
    block = installment_block(subject, peers, MoscowMarket.bundled())
    assert block.code == BLOCK_INSTALLMENT
    return block.to_dict()


def _peer(name, **extra):
    return {"name": name, **extra}


SOFT_PEERS = [
    _peer("Мягкий", installment=True, installment_down_payment_pct=10.0,
          installment_term_months=24, installment_keys_before_payment=True,
          installment_price_terms={"скидка": 2}),
    _peer("Средний", installment=True, installment_down_payment_pct=20.0,
          installment_term_months=12, installment_price_terms={"удорожание": 1}),
    _peer("Без рассрочки", installment=False),
    _peer("Неизвестный"),
]


def test_the_block_tells_no_installment_from_no_data() -> None:
    hard = {"installment": True, "installment_down_payment_pct": 40.0,
            "installment_term_months": 6, "installment_programs": 1}
    block = _blocks(hard, SOFT_PEERS)
    peers = block["peers"]
    assert peers["known"] == 3 and peers["total"] == 4 and peers["offering"] == 2
    assert peers["down_payment"]["median"] == 15.0
    assert peers["term"]["median"] == 18
    assert peers["keys_before_payment"] == 1
    assert peers["price_terms"] == {"скидка": 2, "удорожание": 1}
    # Сосед без ответа свода назван, а не сложен с «рассрочки не даёт».
    assert any("из 4" in note for note in block["notes"])

    # Про сам проект свод может молчать — и это «не знаем», а не «нет».
    silent = _blocks({}, SOFT_PEERS)
    assert silent["subject"] == {}
    assert any("«не знаем»" in note for note in silent["notes"])
    # Соседей нет вовсе — сравнивать не с чем, и так и сказано.
    assert any("сравнивать не с чем" in note for note in _blocks(hard, [])["notes"])


def test_the_note_and_the_finding_say_who_sells_softer() -> None:
    hard = {"installment": True, "installment_down_payment_pct": 40.0,
            "installment_term_months": 6, "installment_programs": 1}
    block = _blocks(hard, SOFT_PEERS)
    note = NOTE_BUILDERS["installment"](block)
    assert "2 соседей из 3" in note["text"]
    assert note["tone"] == "watch"

    found = findings({}, SOFT_PEERS, {}, segment=None, blocks=[block])
    picked = [item for item in found if item.get("code") == "installment"]
    assert len(picked) == 1
    text = picked[0]["text"]
    assert "взнос 15,0 %" in text.replace(".", ",") or "15,0 %" in text
    assert "со скидкой" in text and "удорожанием" in text
    assert picked[0]["tone"] == "watch"

    # Рассрочки нет вовсе — это утверждение, а не молчание.
    none = _blocks({"installment": False, "installment_programs": 1}, SOFT_PEERS)
    said = [i for i in findings({}, SOFT_PEERS, {}, segment=None, blocks=[none]) if i["code"] == "installment"]
    assert "рассрочки нет" in said[0]["text"]
    assert said[0]["tone"] == "watch"

    # Мягкие условия тревогой не объявляются.
    soft = _blocks({"installment": True, "installment_down_payment_pct": 10.0,
                    "installment_term_months": 24, "installment_programs": 3}, SOFT_PEERS)
    calm = [i for i in findings({}, SOFT_PEERS, {}, segment=None, blocks=[soft]) if i["code"] == "installment"]
    assert calm[0]["tone"] == "flat"

    # Ни одного соседа со сводом — вывода нет вовсе: пустое утверждение о рынке
    # читалось бы как измеренное.
    blind = _blocks({}, [_peer("Неизвестный")])
    assert not [i for i in findings({}, [], {}, segment=None, blocks=[blind]) if i["code"] == "installment"]


def test_the_screen_and_the_digest_carry_the_terms(tmp_path) -> None:
    """Проверяется отрисовкой: в исходнике страницы подписи есть всегда.

    Смотрится то, на что жалуются: плитки раздела, колонки таблицы и сводка,
    которая уезжает Платону. Наш вывод он пересказать может, а ответить
    «дороже ли у нас вход» — нет, пока взносов и сроков у него на руках не было.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch
    from market_search import cabinet

    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    hard = {"installment": True, "installment_down_payment_pct": 40.0,
            "installment_term_months": 6, "installment_programs": 1}
    block = _blocks(hard, SOFT_PEERS)
    payload = {
        "subject": {"project_name": "Наш дом", "segment": "Бизнес", "metrics": {}},
        "retrieved_at": "2026-09-08",
        "comparison": {"radius_km": 3, "found": 4, "comparable": 4, "used": 4,
                       "installments_known": 3,
                       "installments_source": "TrendAgent, свод рассрочек по Москве",
                       "installments_saved_at": "2026-09-08"},
        "blocks": [block],
        "analysis": {"blocks": {}},
    }
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
            card = tab.evaluate(
                "([b, peers]) => blockCard(b, {analysis: {blocks: {}}, peers,"
                " series: [], sales: [], subjectMetrics: {}, subjectName: 'Наш дом'})",
                [block, SOFT_PEERS],
            )
            digest = tab.evaluate("d => reportDigest(d)", payload)
            head = tab.evaluate("d => printHead(d)", payload)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Плитки раздела: наши условия, условия соседей и охват.
    assert "первый взнос, самая мягкая программа" in card
    assert "взнос у соседей, медиана" in card and "15,0 %" in card
    assert "2 из 3" in card and "соседей дают рассрочку" in card
    # Колонки сравнения: у соседа без ответа свода прочерк, а не «нет».
    assert '<th class="num">ПВ, %</th>' in card and "<th>Ключи до оплаты</th>" in card
    # Сколько соседей отвечают на вопрос раздела — сказано под таблицей.
    assert "знает про 3 из 4 соседей" in card
    assert card.count(">есть<") >= 2 and ">нет<" in card
    # Сводка уезжает Платону ЧИСЛАМИ, а не одной нашей фразой.
    assert "Рассрочка:" in digest
    assert "медиана взноса 15,0 %" in digest and "срок 18 мес." in digest
    assert "программ со скидкой к прайсу 2" in digest
    # Охват свода стоит в шапке отчёта: без числа молчание про соседа
    # читается как «рассрочки не даёт».
    assert "Условия рассрочки известны у 3 соседей из 4" in head
    assert "TrendAgent" in head
