"""Комнатность проданного читается и доходит до экрана, а этажа в источнике нет.

Колонка «Кол-во комнат» лежала в листе «Контрактация» выгрузки ЦФ с самого
начала и не читалась никем: `_COLUMNS` её не знал, и свод резал проданное
метражными полосами книги — а в полосе 28,3-40 м² лежат и студия, и
однокомнатная. Та же болезнь, что уже записана в CLAUDE.md: файл, который
импорт пишет, а код не читает, — это ответ, которого нет на экране.

Этаж — отдельный ответ, и он отрицательный: в 27 листах выгрузки слова «этаж»
нет ни одной подписью (проверено байтовым поиском 08.09.2026), «Корпус» несёт
«корп 3 кв.168» — дом и номер квартиры. Молчание об этом читалось бы как «по
этажам ничего не продано», поэтому граница названа вслух и здесь проверяется.

Запуск: python3 -m pytest tests/test_the_sales_report_reads_the_rooms.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import contracting  # noqa: E402
from market_search.cabinet import cabinet_page  # noqa: E402


def flat(rooms: str, area: float, amount: float) -> dict:
    return {"month": "2026-08", "signed": "2026-08-01", "product": "Квартира",
            "unit": "корп 3 кв.168", "kind": "", "rooms": rooms, "area": area,
            "contract": "1", "contract_type": "ДДУ", "state": "Действующий",
            "amount": amount, "units": 1.0, "payment_variant": "", "broker": "",
            "broker_fee": 0.0, "broker_rate": None, "sales_bonus_paid": 0.0,
            "escrow_paid": 0.0, "company_buyer": False, "escrow_schedule": []}


def test_a_room_count_is_one_label_whatever_the_source_wrote() -> None:
    """Под двумя написаниями одна комнатность выглядит двумя строками свода."""
    assert contracting.rooms_label("1К") == "1К"
    assert contracting.rooms_label("1к") == "1К"
    assert contracting.rooms_label(" 3 комн. ") == "3К"
    assert contracting.rooms_label(2) == "2К"
    assert contracting.rooms_label("студия") == "Студия"
    # Пусто — «не названа», а не «студия»: подставленная комнатность
    # неотличима от прочитанной.
    assert contracting.rooms_label("") == ""
    assert contracting.rooms_label(None) == ""


def test_the_summary_counts_the_flats_by_rooms() -> None:
    rows = [flat("1К", 40.0, 24_000_000.0), flat("1К", 38.0, 23_000_000.0),
            flat("3К", 90.0, 63_000_000.0),
            {**flat("", 26.0, 9_000_000.0), "product": "Машиноместа"}]
    summary = contracting.summarise({"rows": rows, "project": "П", "missing": []})
    by_rooms = {item["rooms"]: item for item in summary["by_rooms"]}
    # Названы именно квартиры: машино-место комнатности не имеет по построению,
    # и строки «—» в своде быть не должно.
    assert list(by_rooms) == ["1К", "3К"], summary["by_rooms"]
    assert by_rooms["1К"]["contracts"] == 2
    assert by_rooms["1К"]["area"] == 78.0
    assert by_rooms["3К"]["amount"] == 63_000_000.0
    # Знаменатель рядом: «названа у 3 из 3» и «у 1 из 3» — разные утверждения.
    assert summary["rooms_known"] == 3.0 and summary["rooms_total"] == 3.0
    # Этажа в источнике нет, и свод говорит это сам, а не молчит.
    assert summary["floors_known"] is False


def _book(rooms_header: str = "Кол-во комнат") -> bytes:
    """Лист «Контрактация» с шапкой на своей строке — как в выгрузке ЦФ."""
    import io

    from openpyxl import Workbook

    book = Workbook()
    page = book.active
    page.title = contracting.SHEET_CONTRACTS
    header = ["Квартал", "Год", "Месяц", "Объект недвижимости", "Корпус",
              rooms_header, "Проектная S", "Договор", "Тип договора",
              "Состояние договора", "Сумма договор", "Дата договора", "Покупатель",
              "Шт", "Цена ДДУ за кв. м", "Вариант оплаты", "% оплаты",
              "остаток к оплате", "оплачено эскроу всего"]
    for _ in range(contracting._HEADER_ROW - 1):
        page.append([])
    page.append(header)
    page.append(["3кв2026", 2026, "08.2026", "Квартира", "корп 3 кв.168", "1К", 40.0,
                 "Д-1", "ДДУ", "Действующий", 24_000_000.0, "01.08.2026", "Иванов И",
                 1, 600_000.0, "ипотека", 100, 0, 24_000_000.0])
    page.append(["3кв2026", 2026, "08.2026", "Квартира", "корп 3 кв.169", "3К", 90.0,
                 "Д-2", "ДДУ", "Действующий", 63_000_000.0, "02.08.2026", "Петров П",
                 1, 700_000.0, "ипотека", 100, 0, 63_000_000.0])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_the_column_is_read_from_the_sheet_and_not_from_our_own_dict() -> None:
    """Комнатность приходит ИЗ ЛИСТА — иначе свод считает то, чего не читал.

    Свод можно накормить готовыми строками, и он честно разложит их по
    комнатам, ничего не прочитав. Проверять надо ту дверь, в которую ходят:
    колонка «Кол-во комнат» лежала в выгрузке всё это время и в `_COLUMNS`
    её не было.
    """
    read = contracting.read_contracts(_book())
    assert [row["rooms"] for row in read["rows"]] == ["1К", "3К"], read["rows"]
    assert "Кол-во комнат" not in read["missing"], read["missing"]


def test_a_sheet_without_the_column_says_so_instead_of_silently_zeroing() -> None:
    """Колонки нет — это говорится, а не превращается в «комнатность не назвали».

    Лист чужой и его пересобирают руками: молча пропавшая колонка даёт пустой
    раздел, неотличимый от проекта, где комнатность просто не заполняют.
    """
    read = contracting.read_contracts(_book(rooms_header="Комнат"))
    assert "Кол-во комнат" in read["missing"], read["missing"]
    assert all(not row["rooms"] for row in read["rows"])


def test_a_flat_without_a_room_count_is_not_a_studio() -> None:
    """Непрочитанная комнатность не встаёт строкой свода и названа числом."""
    rows = [flat("1К", 40.0, 24_000_000.0), flat("", 90.0, 63_000_000.0)]
    summary = contracting.summarise({"rows": rows, "project": "П", "missing": []})
    assert [x["rooms"] for x in summary["by_rooms"]] == ["1К"]
    assert summary["rooms_known"] == 1.0 and summary["rooms_total"] == 2.0
    said = contracting.conclusions(summary)["rooms"]
    assert "названа у 1 квартир из 2" in said, said


def test_the_conclusion_names_the_border_of_the_answer() -> None:
    """Доли пула по комнатам у нас нет, и вывод обязан это сказать сам.

    Без границы «продано 39 однокомнатных» читается как вымывание, а сравнить
    его не с чем: книга нарезана метражными полосами.
    """
    rows = [flat("1К", 40.0, 24_000_000.0), flat("3К", 90.0, 63_000_000.0)]
    said = contracting.conclusions(
        contracting.summarise({"rows": rows, "project": "П", "missing": []}))["rooms"]
    assert "Доли пула по комнатам нет" in said, said
    assert "этажа в выгрузке нет ни одной колонкой" in said, said
    # Число сделок у самой дорогой комнатности: «дороже всего метр у 5К» на
    # одной сделке и на двадцати — разные утверждения.
    assert "на 1 сделке" in said, said


def test_the_rooms_section_is_drawn_by_the_report_itself() -> None:
    """Раздел стоит НА ЭКРАНЕ, а не только в рисовальщике.

    Тест, зовущий рисовальщик, доказывает, что блок рисуется, — не что он в
    отчёте: ровно на этом уже попадались условия рынка. Поэтому зовётся весь
    `renderSales`, а раздел ищется в его выводе.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    page = cabinet_page("sales").replace("__DEVELOPAID_VERSION__", "test")
    file = Path(__file__).resolve().parent / "_rooms_page.html"
    file.write_text(page, encoding="utf-8")
    payload = {
        "project": "Кутузов Сити",
        "total": {"contracts": 3.0, "units": 3.0, "area": 168.0, "amount": 110_000_000.0,
                  "escrow": 0.0, "escrow_share": 0.0, "price_per_sqm": 654_761.0,
                  "broker_fee": 0.0, "sales_bonus": 0.0, "cost": 0.0},
        "by_rooms": [
            {"rooms": "1К", "contracts": 2.0, "area": 78.0, "amount": 47_000_000.0,
             "price_per_sqm": 602_564.0},
            {"rooms": "3К", "contracts": 1.0, "area": 90.0, "amount": 63_000_000.0,
             "price_per_sqm": 700_000.0},
        ],
        "rooms_known": 3.0, "rooms_total": 3.0, "floors_known": False,
        "conclusions": {"rooms": "Из 3 квартир с названной комнатностью 2 — 1К."},
        "dynamics": [], "by_product": [], "by_payment": [], "by_channel": [],
        "by_size": [], "terminated": [], "sources": [],
    }
    try:
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
                    """d => { let box=document.querySelector('#sales');
                              if(!box){ box=document.createElement('div'); box.id='sales';
                                        document.body.appendChild(box); }
                              renderSales(d); return box.innerHTML; }""", payload)
                tab.close()
            finally:
                browser.close()
    finally:
        file.unlink(missing_ok=True)
    assert not errors, errors
    assert 'id="sb-rms"' in drawn, "раздел комнатности до экрана не доехал"
    assert "Комнатность проданного" in drawn
    assert "1К" in drawn and "3К" in drawn
    # Граница ответа стоит рядом с числами, а не в коде: без неё доли читаются
    # как вымывание, а пустой этаж — как «по этажам не продано».
    assert "Доли пула по комнатам нет" in drawn, drawn[-900:]
    assert "Этажа в выгрузке ЦФ нет ни одной колонкой" in drawn, drawn[-900:]
