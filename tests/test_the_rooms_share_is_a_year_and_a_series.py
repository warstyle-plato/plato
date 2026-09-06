"""Доля в проданном по комнатности: за окно и в динамике по месяцам.

«На счёт доли — но хотелось бы видеть в динамике как эта доля менялась. По
месяцам. Если это невозможно, то на твоё усмотрение с момента начала продаж
наверное или год» (владелец, 06.09.2026).

До этого доля считалась по ОДНОМУ месяцу — последнему в отчёте «Пульса»: у
одного ЖК это десяток сделок, то есть шум, а в тихий месяц продаж нет вовсе, и
полосы «доля в проданном» не было ни одной (25 проектов из 202 на выпуске
2026-08). Помесячные числа в книге есть — импорт их выбрасывал, оставляя снимок
последнего месяца.

Запуск: python3 -m pytest tests/test_the_rooms_share_is_a_year_and_a_series.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet, dynamics, metrics, pulse_report_import  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402


CITY = MoscowMarket({"last_month": "2026-08", "current": {"Бизнес": {"projects": 90}}})

MONTHS = [f"2025-{m:02d}" for m in range(9, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]

# Год продаж: студии берут ровно вдвое чаще трёшек, в СЕРЕДИНЕ года месяц без
# сделок, и в ПОСЛЕДНЕМ месяце сделок нет вовсе. По последнему месяцу такой
# проект отвечал «продаж нет»; по году — «берут студии».
def _row(**extra) -> dict:
    sold_studio = [4, 6, 4, 8, 6, 0, 4, 6, 8, 4, 6, 0]
    sold_r3 = [2, 3, 2, 4, 3, 0, 2, 3, 4, 2, 3, 0]
    row = {
        "room_mix": {
            "studio": {"sold": 0, "rem": 40, "price": 760_000},
            "r3": {"sold": 0, "rem": 60, "price": 600_000},
        },
        "rooms_sold": {"studio": sold_studio, "r3": sold_r3},
        "rooms_months": list(MONTHS),
        "segment": "Бизнес",
    }
    row.update(extra)
    return row


def test_the_window_sums_a_year_and_names_itself() -> None:
    window = metrics._room_window(_row())
    assert window["months"] == metrics.ROOM_WINDOW_MONTHS == 12
    assert window["from"] == "2025-09" and window["to"] == "2026-08"
    assert window["sold"]["studio"] == 56 and window["sold"]["r3"] == 28


def test_a_reference_without_the_series_says_so_instead_of_a_zero() -> None:
    """«Ряда нет» и «продаж не было» — разные ответы.

    Справочник, собранный прежним импортом, помесячной комнатности не несёт, и
    показывать это как отсутствие продаж нельзя.
    """
    assert metrics._room_window({"room_mix": {"studio": {"sold": 3}}}) is None
    block = metrics.rooms_block({"segment": "Бизнес", "room_mix": {
        "studio": {"sold": 3, "rem": 10}}}, [], CITY).to_dict()
    gap = block["subject"]["rooms_series_gap"]
    assert "прежним импортом" in gap, gap
    assert "rooms_window" not in block["subject"]


def test_the_share_is_counted_over_the_window_not_the_last_month() -> None:
    block = metrics.rooms_block(_row(), [], CITY).to_dict()
    rooms = block["subject"]["rooms"]
    # По последнему месяцу доли не было бы вовсе — продаж в нём ноль.
    assert rooms["studio"]["sold_share_pct"] == 66.7
    assert rooms["r3"]["sold_share_pct"] == 33.3
    assert "rooms_sold_gap" not in block["subject"]
    window = block["subject"]["rooms_window"]
    assert window["deals"] == 84 and window["months"] == 12
    # Остаток остаётся сегодняшним: он и есть сегодняшний.
    assert rooms["r3"]["rem"] == 60


def test_a_month_without_sales_breaks_the_series_instead_of_drawing_a_zero() -> None:
    series = metrics._room_series(_row())
    months = [point["month"] for point in series]
    assert "2026-08" not in months and "2026-02" not in months, "тихий месяц нарисован нулём"
    assert len(series) == 10
    first = series[0]
    assert first["month"] == "2025-09" and first["sold"] == 6
    assert first["shares"] == {"r3": 33.3, "studio": 66.7}


def test_a_single_month_of_sales_is_not_a_dynamic() -> None:
    """Одна точка — не динамика, и линию из неё рисовать нельзя."""
    row = _row(rooms_sold={"studio": [None] * 11 + [5]})
    block = metrics.rooms_block(row, [], CITY).to_dict()
    assert "rooms_series" not in block["subject"]
    assert "одном месяце" in block["subject"]["rooms_series_gap"]


def test_peers_are_pooled_over_the_same_window_and_the_rest_are_named() -> None:
    """Год одного соседа и последний месяц другого — не одна величина.

    Сложенные, они дают третью: она не за год и не за месяц, а выглядит
    посчитанной.
    """
    with_series = {"name": "С рядом", **_row()}
    without = {"name": "Без ряда", "room_mix": {"studio": {"sold": 100, "rem": 5}}}
    block = metrics.rooms_block(_row(), [with_series, without], CITY).to_dict()
    peers = block["peers"]
    # Сотня сделок соседа без ряда в полосу не вошла — иначе доля студий у
    # соседей стала бы 85 % вместо 67 %.
    assert peers["rooms"]["studio"]["sold"] == 56
    assert peers["sold_projects"] == 1 and peers["projects"] == 2
    assert peers["rooms_window"]["months"] == 12
    assert any("Помесячной комнатности нет у 1 из 2" in note for note in block["notes"])
    # Остаток складывается по всем: он сегодняшний у любого.
    assert peers["rooms"]["studio"]["rem"] == 45


def test_the_import_keeps_the_rooms_month_by_month() -> None:
    """Импорт хранил снимок последнего месяца, а ряд выбрасывал."""
    series = {
        "77": {
            "2026-07": {"price": 700_000, "room_mix": {"studio": {"sold": 3, "rem": 40}}},
            "2026-08": {"price": 710_000, "room_mix": {"studio": {"sold": 0, "rem": 38}}},
        }
    }
    built = pulse_report_import.build_dynamics(
        {"77": {"name": "Наш"}}, series, months=["2026-07", "2026-08"], source="книга"
    )
    row = built["projects"]["77"]
    assert row["rooms_sold"] == {"studio": [3, 0]}
    assert row["rooms_rem"] == {"studio": [40, 38]}
    # Снимок последнего месяца остаётся: на нём стоят цены и остаток.
    assert row["room_mix"]["studio"]["rem"] == 38

    # И доезжает до метрик вместе со своей шкалой времени.
    latest = dynamics.SalesDynamics(built).latest("77", ())
    assert latest["rooms_sold"] == {"studio": [3, 0]}
    assert latest["rooms_months"] == ["2026-07", "2026-08"]


def test_an_old_reference_without_the_series_does_not_grow_the_field() -> None:
    built = pulse_report_import.build_dynamics(
        {"77": {"name": "Наш"}}, {"77": {"2026-08": {"price": 700_000}}},
        months=["2026-08"], source="книга",
    )
    assert "rooms_sold" not in built["projects"]["77"]


def test_the_screen_draws_the_series_and_names_the_window(tmp_path) -> None:
    """Спор «видно динамику или нет» решает экран, а не строка в исходнике."""
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    block = metrics.rooms_block(_row(), [], CITY).to_dict()
    bare = metrics.rooms_block(
        {"segment": "Бизнес", "room_mix": {"studio": {"sold": 3, "rem": 10}}}, [], CITY
    ).to_dict()
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
            drawn = tab.evaluate("block => roomsTable(block)", block)
            silent = tab.evaluate("block => roomsTable(block)", bare)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Две картинки: полосы и линия по месяцам.
    assert drawn.count("<svg") == 2, drawn.count("<svg")
    assert "Как доля менялась по месяцам" in drawn
    # Окно названо у самой полосы: «за месяц» и «за год» — разные величины.
    assert "за 12 мес. (2025-09 — 2026-08)" in drawn, drawn[:600]
    # Тихий месяц линию рвёт, а не ведёт нулём, и это сказано вслух.
    assert "Месяцев без продаж: 1" in drawn
    assert drawn.count("<path") == 2, "линия на комнатность"
    # Точек столько, сколько месяцев с продажами, у каждой из двух линий.
    assert drawn.count("<circle") == 20, drawn.count("<circle")
    # Оба графика стоят НАД таблицей.
    assert drawn.rindex("<svg") < drawn.index("<table")
    # А без ряда рисуется не пустое поле, а причина.
    assert "<svg" not in silent.split("<table")[0].split("Как доля")[-1]
    assert "прежним импортом" in silent
