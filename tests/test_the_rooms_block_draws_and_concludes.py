"""Комнатность: картинка и вывод, а не две таблицы.

«Блок с комнатностью интересный, но там ни графика с полосами или чем-то
наглядным, ни выводов. Получается, соседи-то продают крупные лоты больше и
поэтому возможно цена у них ниже» (владелец, 05.09.2026).

Обе половины проверяются здесь. Картинка — парные полосы «доля в проданном
против доли в остатке»: вымывание это и есть расхождение двух полос одной
строки. Вывод — разложение разрыва в цене метра на набор квартир и уровень цен:
догадка владельца верна ВНУТРИ проекта (метр тем дороже, чем мельче квартира) и
неверна по рынку (у 174 проектов августа корреляция «средний проданный лот ↔
медианная цена метра» +0,64 — крупные форматы строят в дорогих классах), поэтому
отвечать на неё надо счётом на своём проекте, а не правилом.

Запуск: python3 -m pytest tests/test_the_rooms_block_draws_and_concludes.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet, metrics, verdict  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402


CITY = MoscowMarket({"last_month": "2026-08", "current": {"Бизнес": {"projects": 90}}})

# Мелкий метр дороже крупного — так устроен прайс внутри проекта. У нас набор
# мелкий, у соседей крупный, а цены по комнатности ОДИНАКОВЫЕ: значит весь
# разрыв средней цены объясняется набором, и блок обязан это назвать.
LADDER = {
    "studio": 760_000,
    "r1": 700_000,
    "r2": 640_000,
    "r3": 600_000,
}
SUBJECT = {
    "segment": "Бизнес",
    "room_mix": {
        "studio": {"sold": 12, "rem": 60, "price": LADDER["studio"]},
        "r1": {"sold": 8, "rem": 30, "price": LADDER["r1"]},
        "r2": {"sold": 2, "rem": 8, "price": LADDER["r2"]},
        "r3": {"sold": 0, "rem": 2, "price": LADDER["r3"]},
    },
    "bands": {"28-40": 15, "40-55": 5, "55-85": 2},
}
PEERS = [
    {
        "name": "Сосед А",
        "room_mix": {
            "studio": {"sold": 1, "rem": 5, "price": LADDER["studio"]},
            "r1": {"sold": 3, "rem": 15, "price": LADDER["r1"]},
            "r2": {"sold": 6, "rem": 40, "price": LADDER["r2"]},
            "r3": {"sold": 5, "rem": 40, "price": LADDER["r3"]},
        },
        "bands": {"40-55": 4, "55-85": 8, "85-120": 4},
    },
    {
        "name": "Сосед Б",
        "room_mix": {
            "r2": {"sold": 4, "rem": 30, "price": LADDER["r2"]},
            "r3": {"sold": 4, "rem": 30, "price": LADDER["r3"]},
        },
        "bands": {"55-85": 6, "85-120": 2},
    },
]


def _block() -> dict:
    return metrics.rooms_block(SUBJECT, PEERS, CITY).to_dict()


def test_the_gap_is_split_into_the_mix_and_the_price_level() -> None:
    """Одни и те же цены по комнатам, разный набор — разрыв целиком от набора."""
    mix = _block()["subject"]["mix"]
    assert mix["own_at_own_mix"] > mix["peers_at_peers_mix"], "мелкий набор обязан стоить дороже"
    # Цены по комнатам совпадают, значит уровень цен ни при чём — и это должен
    # сказать сам расчёт, а не читатель.
    assert abs(mix["level_pct"]) < 0.5, mix
    assert mix["mix_pct"] < -5, mix
    # Покрытие называется рядом: цена «при наборе соседей» на трети набора —
    # это оценка, а не измерение.
    assert mix["own_coverage_pct"] == 100.0
    assert mix["cross_coverage_pct"] == 100.0


def test_the_level_shows_when_prices_differ_and_the_mix_does_not() -> None:
    """Обратный случай: набор один и тот же, цены разные — набор не при чём."""
    dearer = [
        {
            "name": "Сосед В",
            "room_mix": {
                name: {"sold": item["sold"], "rem": item["rem"], "price": item["price"] * 1.25}
                for name, item in SUBJECT["room_mix"].items()
            },
        }
    ]
    mix = metrics.rooms_block(SUBJECT, dearer, CITY).to_dict()["subject"]["mix"]
    assert abs(mix["mix_pct"]) < 0.5, mix
    assert mix["level_pct"] < -15, mix


def test_a_room_without_a_price_leaves_the_weight_instead_of_averaging_it() -> None:
    """Комнатность без цены выбрасывается из веса, а не считается по средней.

    Иначе неизвестная цена молча считалась бы средней — а средняя тут и есть
    предмет спора.
    """
    price, covered = metrics._weighted_price(
        {"r1": 700_000, "r2": 640_000}, {"r1": 50, "r2": 50, "r3": 100}
    )
    assert price == 670_000
    assert covered == 50.0
    assert metrics._weighted_price({}, {"r1": 10}) == (None, 0.0)


def test_the_note_answers_the_question_about_the_mix() -> None:
    """Вывод отвечает на вопрос словами, а не именами величин.

    «Ничего не понятно в выводах по комнатности, не русским понятным языком
    описано» (владелец, 05.09.2026). Прежний текст говорил «из этого набором
    квартир объясняется −12,4 %», и читателю приходилось складывать в уме
    проценты с разными знаками. Проверяется не оборот речи, а то, что в тексте
    названы ОБА сравниваемых метра и наш же метр на наборе соседей: без
    третьего числа разложение проверить нечем.
    """
    block = _block()
    mix = block["subject"]["mix"]
    note = verdict.rooms_note(block)
    text = note["text"]
    for value in (mix["own_at_own_mix"], mix["peers_at_peers_mix"], mix["own_at_peers_mix"]):
        assert verdict._num(value) in text, (value, text)
    assert "набор" in text, text
    # Вымывание названо своим числом, а не словом «вымывается».
    assert "% продаж при" in text, text
    assert note["tone"] in {verdict.TONE_WATCH, verdict.TONE_FLAT}

    empty = verdict.rooms_note({"subject": {}, "peers": {}})
    assert "не раскрыта" in empty["text"]


def test_the_note_names_the_winner_of_the_two_causes() -> None:
    """Три случая — набор, цены и оба — говорятся разными фразами.

    Одна фраза на все три означала бы, что вывод не сделан: читатель узнаёт из
    неё только то, что мы посчитали, а не что получилось.
    """
    def say(own: float, cross: float, peers: float) -> str:
        return " ".join(
            verdict._mix_lines(
                {
                    "own_at_own_mix": own,
                    "own_at_peers_mix": cross,
                    "peers_at_peers_mix": peers,
                    "gap_pct": round((own / peers - 1) * 100, 1),
                    "mix_pct": round((cross / own - 1) * 100, 1),
                    "level_pct": round((cross / peers - 1) * 100, 1),
                }
            )
        )

    by_mix = say(729_200, 639_000, 639_000)
    assert "Дело в наборе" in by_mix, by_mix
    assert "639 000" in by_mix and "729 200" in by_mix, by_mix

    by_price = say(800_000, 796_000, 640_000)
    assert "Набор тут ни при чём" in by_price, by_price
    assert "24,4 %" in by_price, by_price

    by_both = say(830_000, 742_000, 640_000)
    assert "Часть разницы делает набор" in by_both, by_both
    assert "Остальное — цены" in by_both, by_both

    level = say(642_000, 641_000, 640_000)
    assert "вровень" in level, level


def test_the_notes_exist_for_every_new_section() -> None:
    """Раздел без вывода читается как «сказать нечего»."""
    for code in ("rooms", "payment", "channel"):
        assert code in verdict.NOTE_BUILDERS, code


def test_the_block_is_drawn_with_bars_in_a_real_browser(tmp_path) -> None:
    """Спор «наглядно или нет» решает экран, а не рассуждение о коде."""
    import json

    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    block = _block()
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
            drawn = tab.evaluate(
                "([block, say]) => blockCard(block, {analysis:{blocks:{rooms:say}}})",
                [block, verdict.rooms_note(block)],
            )
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Две картинки: комнатность и полосы площади. Полос столько же, сколько
    # известных долей, — пустой <svg> выглядит на экране так же, как полный.
    assert drawn.count("<svg") == 2, drawn.count("<svg")
    assert drawn.count("<rect") >= 12, drawn.count("<rect")
    assert "доля в проданном" in drawn and "доля в остатке" in drawn
    assert "наши сделки" in drawn and "у соседей" in drawn
    # Картинка стоит НАД своей таблицей: в колоде чертится та таблица, над
    # которой стоит график.
    assert drawn.index("<svg") < drawn.index("<table"), "график встал под таблицу"
    # И числа разложения — на плитках, а не только в тексте вывода. Подписи
    # плиток названы вопросом, а не именем величины: «из разрыва — уровень цен»
    # читателю пришлось бы расшифровывать.
    assert "сколько из разницы даёт набор квартир" in drawn
    assert "сколько дают сами цены" in drawn
    assert "если бы набор был как у соседей" in drawn
    assert "Дело в наборе" in drawn


# Продажи по комнатности отчёт даёт помесячно, и в последнем месяце их у
# проекта может не быть вовсе: на выпуске 2026-08 это 25 проектов из 202 —
# каждый восьмой. Тогда оранжевой полосы нет ни в одной строке, а легенда её
# по-прежнему обещала: на экране это читается как поломка отрисовки, а не как
# молчание источника («а где доля то цветом её нет?», владелец, 06.09.2026).
QUIET = {
    "segment": "Бизнес",
    "room_mix": {
        "studio": {"sold": 0, "rem": 60, "total": 72, "price": LADDER["studio"]},
        "r1": {"sold": 0, "rem": 30, "total": 38, "price": LADDER["r1"]},
        "r2": {"sold": 0, "rem": 8, "total": 10, "price": LADDER["r2"]},
    },
}


def test_a_month_without_sales_names_the_missing_bar() -> None:
    block = metrics.rooms_block(QUIET, PEERS, CITY).to_dict()
    gap = (block.get("subject") or {}).get("rooms_sold_gap")
    assert gap and "продаж" in gap.lower(), block.get("subject")
    rooms = block["subject"]["rooms"]
    # Доля в остатке при этом считается: «продаж не было» — это утверждение о
    # проданном, а не об остатке.
    assert all(item["sold_share_pct"] is None for item in rooms.values())
    assert any(item["rem_share_pct"] for item in rooms.values())


def test_a_quiet_month_does_not_promise_a_bar_it_cannot_draw(tmp_path) -> None:
    """Легенда обещает ровно те полосы, которые нарисованы.

    Проверяется отрисовкой, а не строкой в исходнике: обе подписи в файле есть
    всегда, и текстовый поиск был бы зелёным на сломанном экране.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    block = metrics.rooms_block(QUIET, PEERS, CITY).to_dict()
    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "quiet.html"
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
            drawn = tab.evaluate("block => roomsTable(block)", block)
            full = tab.evaluate("block => roomsTable(block)", _block())
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Пустой серии нет ни в легенде, ни подписью под графиком — вместо неё
    # стоит причина.
    assert "доля в проданном" not in drawn.split("<table")[0]
    assert "доля в остатке" in drawn
    assert "вымывается" not in drawn, "подпись зовёт сравнить полосы, которых одна"
    assert "продаж" in drawn.lower()
    # А там, где обе полосы есть, обещание прежнее.
    assert "доля в проданном" in full.split("<table")[0]
    assert "вымывается" in full


def test_plato_gets_the_numbers_of_these_sections_not_only_our_phrase(tmp_path) -> None:
    """В вопрос Платону уезжают доли, а не пересказ нашего же вывода.

    Раньше сводка несла по блоку только `say.text` — фразу, которую мы сами и
    написали. Объяснить её Платон может, а ответить «что это значит против
    соседей» — нет: долей комнатности, ипотеки и юрлиц у него на руках не было.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    from market_search.metrics import build_blocks

    # У объекта этого файла есть только комнатность: доли ипотеки и юрлиц
    # приезжают из тех же месячных строк отчёта, и без них проверялась бы
    # половина сводки.
    subject = {**SUBJECT, "mortgage": 28.6, "legal": 12.5, "resale": 2}
    peers = [
        {**PEERS[0], "mortgage": 52.0, "legal": 4.3},
        {**PEERS[1], "mortgage": 61.0, "legal": 0.0},
    ]
    blocks = build_blocks(subject, peers, CITY, ["rooms", "payment", "channel"])
    report = {
        "subject": {"project_name": "Наш", "segment": "Бизнес"},
        "comparison": {"radius_km": 3, "found": 3, "comparable": 2, "used": 2},
        "retrieved_at": "2026-09-06",
        "blocks": blocks,
        "peers": [{"name": "Сосед А", "segment": "Бизнес", "distance_km": 1.2,
                   "price_per_sqm": 640_000, "units_per_month": 9}],
    }
    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "digest.html"
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
            digest = tab.evaluate("d => reportDigest(d)", report)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "Комнатность:" in digest and "остаток" in digest
    assert "Разложение разрыва цены" in digest
    assert "Ипотека:" in digest and "у соседей" in digest
    assert "Покупатели:" in digest and "юрлиц" in digest


def test_the_digest_keeps_the_question_inside_the_limit(tmp_path) -> None:
    """Бюджет считают на всё сообщение, а не на его середину.

    Предел вопроса у Платона 4 000 знаков. Сводка росла разделами, и на самом
    полном отчёте — там, где данных больше всего, — она перевалила бы предел
    молча, а человек прочитал бы «вопрос слишком длинный», то есть претензию к
    себе. Не поместившееся называется вслух.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    from market_search.metrics import build_blocks

    ladder = {"studio": 760_000, "r1": 700_000, "r2": 640_000,
              "r3": 600_000, "r4": 580_000, "r5": 560_000}
    subject = {"segment": "Бизнес", "price_per_sqm": 729_200, "mortgage": 28.6,
               "legal": 12.5, "resale": 2,
               "room_mix": {k: {"sold": 5, "rem": 40, "total": 80, "price": v}
                            for k, v in ladder.items()}}
    peers = [{"name": f"ЖК «Сосед номер {i}» — жилой комплекс бизнес-класса", "segment": "Бизнес",
              "distance_km": round(0.4 * i, 2), "price_per_sqm": 600_000 + i * 7000,
              "units_per_month": 6 + i, "mortgage": 50 + i, "legal": 3 + i,
              "room_mix": {k: {"sold": 3, "rem": 30, "price": v} for k, v in ladder.items()}}
             for i in range(1, 13)]
    blocks = build_blocks(subject, peers, CITY,
                          ["price", "pace", "stock", "rooms", "payment", "channel"])
    # Разборы по разделам в сводке тоже стоят — на живом отчёте они есть
    # всегда, и без них проверялся бы не тот объём.
    notes = verdict.build_notes(blocks, None)
    report = {"subject": {"project_name": "ЖК «Проект с довольно длинным именем»",
                          "segment": "Бизнес", "segment_source": "Пульс"},
              "comparison": {"radius_km": 3, "found": 40, "comparable": 18, "used": 12},
              "retrieved_at": "2026-09-06", "blocks": blocks, "peers": peers,
              "analysis": {"overall": notes["overall"], "blocks": notes["blocks"]}}
    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "budget.html"
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
            digest = tab.evaluate("d => reportDigest(d)", report)
            budget = tab.evaluate("() => DIGEST_BUDGET")
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Хвост «не поместилось» пишется сверх бюджета: он и есть предупреждение,
    # и обрезать его первым значило бы потерять именно то, ради чего он есть.
    assert len(digest) <= budget + 160, len(digest)
    # Обязательное — кто мы и на какой выборке — на месте всегда.
    assert "Объект:" in digest and "В радиусе" in digest
    # На этом отчёте бюджет действительно жмёт — иначе проверка была бы
    # зелёной и без него, то есть не проверяла бы ничего.
    assert "Не поместилось в вопрос:" in digest, len(digest)
    assert digest.rstrip().endswith("спросите об этом отдельно.")
