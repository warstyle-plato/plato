"""Апартаменты и квартиры — разный товар, и отчёт обязан это назвать.

«Это надо положить в базу и проанализировать в отчёте» (владелец, 08.09.2026)
— про находку того же дня: у Зорге 9 в выгрузке 921 апартамент и ни одной
квартиры, поэтому прайс-листа квартир у него нет по построению.

Состав дома лежал в базе с самого начала: `moscow-cards-*.json` собирает импорт
отчёта «Пульса» (колонки AN/AO), и до сих пор этот файл не читал НИКТО. Теперь
вид жилья едет со строкой проекта — и у объекта, и у соседа, — и отчёт считает
по нему медиану своего вида.

Что это не мелочь, измерено на самой выгрузке за 2026-08 (685 карточек:
квартиры 471, апартаменты 77, смешанные 20, состав не назван у 117):

* в 25 парах «тот же район, тот же класс» апартаменты дешевле в 21 паре,
  медиана разницы −21,0 %;
* бизнес: 410,9 против 552,1 тыс ₽/м², темп 10,2 против 16,2 ДДУ/мес,
  средний лот 47,2 против 56,9 м²;
* НО в премиуме апартаменты дороже квартир (Хамовники +12,8 %, Басманный
  +31,1 %) — значит поправки из этого не выводится, ответ у каждого проекта
  свой, и отчёт считает его по собственной выборке.

Запуск: python3 -m pytest tests/test_the_report_tells_apartments_from_flats.py -q
"""

from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.cards import ProjectCards  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402
from market_search.metrics import BLOCK_PRICE, price_block  # noqa: E402
from market_search.narrative import findings  # noqa: E402

# Настоящие номера «Пульса» из поставляемой выгрузки: фикстуры здесь не годятся
# — проверяется, что база ЧИТАЕТСЯ, а не что словарь можно собрать руками.
ZORGE = 476        # Зорге 9 — 921 апартамент, ни одной квартиры
DOM_NA_ZORGE = 4987  # Дом на Зорге — 308 квартир


def test_the_bundled_cards_name_the_housing_kind() -> None:
    cards = ProjectCards.bundled()
    assert cards.available and len(cards._cards) > 300
    assert cards.facts(ZORGE) == {
        "housing_kind": "апартаменты", "flats_units": 0, "apartment_units": 921}
    assert cards.facts(DOM_NA_ZORGE)["housing_kind"] == "квартиры"
    # Ни квартир, ни апартаментов — это «не назван», а не «квартиры»:
    # молчание источника ответом не становится.
    assert ProjectCards({"cards": {"1": {"flats": 0, "apartments": 0}}}).facts(1) == {}
    assert ProjectCards({}).facts(ZORGE) == {}


def _pulse(metrics, projects, history):
    def near(lat, lon, radius_km):
        out = []
        for row in projects:
            dy = (row["latitude"] - lat) * 111.0
            dx = (row["longitude"] - lon) * 111.0 * math.cos(math.radians(lat))
            distance = math.hypot(dx, dy)
            if distance <= radius_km:
                out.append((round(distance, 3), SimpleNamespace(**row)))
        return sorted(out, key=lambda item: item[0])

    return SimpleNamespace(
        available=True,
        segments=lambda: {row["complex_id"]: "Бизнес" for row in projects},
        near=near,
        metrics=lambda cid: ({"complex_id": cid, **metrics[cid]} if cid in metrics else {}),
        price=lambda cid: (
            {"price_per_sqm": metrics[cid]["price_per_sqm"],
             "observed_at": metrics[cid].get("observed_at")}
            if metrics.get(cid, {}).get("price_per_sqm") else None
        ),
        project_totals=lambda cid: {},
        find_project=lambda query: None,
        price_history=lambda ids, months=12: {c: p for c, p in history.items() if c in ids},
        remaining=lambda cid: {},
    )


def _report(tmp_path):
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    service.verified_prices.today = date(2026, 9, 8)
    metrics = {
        ZORGE: {"units_per_month": 10.2},
        DOM_NA_ZORGE: {"price_per_sqm": 541_612, "observed_at": "2026-08-20"},
        900_000: {"price_per_sqm": 612_278, "observed_at": "2026-08-20"},
    }
    projects = [
        {"complex_id": ZORGE, "name": "Зорге 9", "developer": "St Michael",
         "latitude": 55.78270, "longitude": 37.50884, "address": "Москва, ул. Зорге, вл.9 А"},
        {"complex_id": DOM_NA_ZORGE, "name": "Дом на Зорге", "developer": "А101",
         "latitude": 55.78500, "longitude": 37.51200, "address": "Москва, ул. Зорге, вл. 25"},
        # Этого номера в выгрузке нет — вид жилья у него неизвестен, и это
        # отдельный ответ, а не «квартиры».
        {"complex_id": 900_000, "name": "Сосед без карточки", "developer": "—",
         "latitude": 55.78900, "longitude": 37.51900, "address": "Москва, Хорошевское ш."},
    ]
    service.pulse = _pulse(metrics, projects, {ZORGE: [{"month": "2026-08", "value": 707_246}]})
    return service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE])


def test_the_kind_rides_with_the_subject_and_the_peers(tmp_path) -> None:
    report = _report(tmp_path)
    assert report["subject"]["metrics"]["housing_kind"] == "апартаменты"
    peers = {row["name"]: row for row in report["peers"]}
    assert peers["Дом на Зорге"]["housing_kind"] == "квартиры"
    assert "housing_kind" not in peers["Сосед без карточки"]
    # Сколько соседей с названным видом — часть ответа: «не назван» нельзя
    # складывать с «квартиры».
    assert report["comparison"]["housing_kind_known"] == 1


APARTMENTS = {"housing_kind": "апартаменты", "price_per_sqm": 707_246, "segment": "Бизнес"}
MIXED_PEERS = [
    {"name": "Кв. 1", "segment": "Бизнес", "housing_kind": "квартиры", "price_per_sqm": 612_278},
    {"name": "Кв. 2", "segment": "Бизнес", "housing_kind": "квартиры", "price_per_sqm": 541_612},
    {"name": "Ап. 1", "segment": "Бизнес", "housing_kind": "апартаменты", "price_per_sqm": 497_800},
    {"name": "Без вида", "segment": "Бизнес", "price_per_sqm": 582_029},
]


def test_the_price_block_names_the_median_of_its_own_kind() -> None:
    block = price_block(APARTMENTS, MIXED_PEERS, MoscowMarket({}))
    own = block.peers["same_kind"]
    assert own["kind"] == "апартаменты" and own["count"] == 1 and own["known"] == 3
    assert own["median"] == 497_800
    assert any("апартаменты" in note and "497 800" in note for note in block.notes)

    # Все соседи того же вида — сравнивать нечего, и строки нет: пустая плитка
    # читалась бы как сравнение.
    same = [{**row, "housing_kind": "апартаменты"} for row in MIXED_PEERS[:3]]
    assert "same_kind" not in price_block(APARTMENTS, same, MoscowMarket({})).peers
    # Вид объекта неизвестен — тоже молчим, а не считаем его квартирами.
    blind = {key: value for key, value in APARTMENTS.items() if key != "housing_kind"}
    assert "same_kind" not in price_block(blind, MIXED_PEERS, MoscowMarket({})).peers


def test_the_finding_says_what_the_price_was_compared_with() -> None:
    said = findings(APARTMENTS, MIXED_PEERS, {}, segment="Бизнес")
    kind = next(row for row in said if row["code"] == "housing_kind")
    assert "апартаменты" in kind["headline"]
    # Три числа: медиана своего вида, медиана остальных и наш прайс к своему
    # виду. Без них вывод — утверждение, которое нечем проверить.
    assert "497 800" in kind["text"] and "576 945" in kind["text"] and "707 246" in kind["text"]

    # В выборке нет ни одного своего вида — это другой ответ, а не молчание.
    alone = findings(APARTMENTS, MIXED_PEERS[:2], {}, segment="Бизнес")
    lonely = next(row for row in alone if row["code"] == "housing_kind")
    assert "нет ни одного" in lonely["text"]

    # Вид у всех один — новости нет, и вывода тоже.
    same = [{**row, "housing_kind": "апартаменты"} for row in MIXED_PEERS[:3]]
    assert not [row for row in findings(APARTMENTS, same, {}, segment="Бизнес")
                if row["code"] == "housing_kind"]


def test_the_screen_shows_the_kind_of_every_row(tmp_path) -> None:
    """Проверяется отрисовкой: в исходнике страницы слово есть всегда."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch
    from market_search import cabinet

    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    payload = {
        "subject": {"project_name": "Зорге 9", "segment": "Бизнес",
                    "metrics": {"housing_kind": "апартаменты"}},
        "retrieved_at": "2026-09-08",
        "comparison": {"radius_km": 3, "found": 3, "comparable": 2, "used": 2,
                       "housing_kind_known": 1},
    }
    block = price_block(APARTMENTS, MIXED_PEERS, MoscowMarket({})).to_dict()
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
            table = tab.evaluate("peers => peersCard(peers)", MIXED_PEERS)
            card = tab.evaluate(
                "([b, peers]) => blockCard(b, {analysis: {blocks: {}}, peers, series: [], sales: []})",
                [block, MIXED_PEERS],
            )
            digest = tab.evaluate("d => reportDigest(d)", payload)
            head = tab.evaluate(
                "d => { render(d); return document.getElementById('out').innerHTML; }",
                {**payload, "blocks": [], "analysis": {}, "peers": MIXED_PEERS,
                 "price_series": [], "sales_series": []},
            )
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "<th>Вид</th>" in table
    assert table.count("квартиры") == 2 and table.count("апартаменты") == 1
    # Неизвестный вид — прочерк, а не подстановка большинства.
    assert table.count("<td class=\"muted\">—</td>") >= 1
    assert "медиана своего вида" in card and "497 800" in card
    assert "вид жилья апартаменты" in digest
    # Охват тоже уезжает Платону: без него «в выборке квартиры» читается как
    # утверждение обо всех соседях, а не о тех, чей состав назван.
    assert "вид назван у 1 из 2" in digest
    # Вид объекта стоит в шапке рядом с классом: два разных товара под одним
    # классом иначе неразличимы.
    assert "класс: Бизнес" in head and "· апартаменты ·" in head
