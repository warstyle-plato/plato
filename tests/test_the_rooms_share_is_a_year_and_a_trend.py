"""Доля в проданном по комнатности: за год и в динамике по кварталам.

«На счёт доли — но хотелось бы видеть в динамике как эта доля менялась. По
месяцам» (владелец, 06.09.2026), и следом, увидев результат: «Абсолютно не
информативные графики» (07.09.2026).

Оба замечания верны, и второе объясняет первое. Помесячная доля рисует шум как
сигнал: замер по августовской книге (365 проектов с рядом) дал 40 % активных
месяцев с менее чем десятью сделками и медианный месячный скачок ведущей доли
21,7 п.п. при девяностом процентиле в 60. Квартал даёт 36 сделок в точке и
скачок 17,7 п.п. Поэтому шаг квартальный, состав рисуется колонкой на сто
процентов, а не пятью пересекающимися линиями, и сдвиг называется, только если
он больше того разброса, который дают сами сделки.

До всего этого доля считалась по ОДНОМУ месяцу — последнему в отчёте «Пульса»:
в тихий месяц продаж нет вовсе, и полосы «доля в проданном» не было ни одной
(25 проектов из 202 на выпуске 2026-08).

Запуск: python3 -m pytest tests/test_the_rooms_share_is_a_year_and_a_trend.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search import cabinet, dynamics, metrics, pulse_report_import  # noqa: E402
from market_search.market_reference import MoscowMarket  # noqa: E402


PAGE = cabinet.cabinet_page("market")


def _body(name: str) -> str:
    """Тело функции по скобкам, а не по соседней строке.

    Функция — контракт: она либо есть, либо её нет, и второе настоящая
    поломка. Границу считаем скобками, иначе проверка падает при правке соседа.
    """
    start = PAGE.index(f"function {name}(")
    depth, opened = 0, False
    for index in range(start, len(PAGE)):
        if PAGE[index] == "{":
            depth += 1
            opened = True
        elif PAGE[index] == "}":
            depth -= 1
            if opened and depth == 0:
                return PAGE[start:index + 1]
    raise AssertionError(f"не нашёл конца функции {name}")


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
    gap = block["subject"]["rooms_trend_gap"]
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


def test_the_trend_is_quarterly_because_a_month_draws_noise() -> None:
    """Помесячная доля рисует шум как сигнал — это измерено, а не решено на глаз.

    Замер по августовской книге (365 проектов с рядом): в 40 % активных
    месяцев меньше десяти сделок, а месячный скачок ведущей доли медианно
    21,7 п.п. при девяностом процентиле в 60. Квартал даёт 36 сделок в точке и
    скачок 17,7 п.п.
    """
    trend = metrics._room_trend(_row())
    assert metrics.ROOM_TREND_STEP == 3
    assert len(trend) == 4
    assert trend[0]["from"] == "2025-09" and trend[0]["to"] == "2025-11"
    assert trend[-1]["from"] == "2026-06" and trend[-1]["to"] == "2026-08"
    # Сколько сделок в точке — часть ответа: доля на пяти сделках и доля на
    # пятидесяти на картинке неразличимы.
    assert [point["deals"] for point in trend] == [21, 21, 27, 15]
    # Сколько месяцев в точке — тоже ответ: подпись «09.25–11.25» читается и
    # как три месяца, и как два (вычитанием крайних), и оспорить второе
    # прочтение нечем («у тебя написано что сдвиг квартальный, а на графике
    # даты = 2 месяцам», владелец, 07.09.2026).
    assert [point["months"] for point in trend] == [3, 3, 3, 3]
    assert trend[0]["shares"] == {"r3": 33.3, "studio": 66.7}


def test_an_empty_quarter_is_dropped_instead_of_drawn_as_a_zero() -> None:
    """Пропуск в ряду — не ноль: колонка нулевой высоты показала бы состав
    спроса там, где спроса не было вовсе."""
    row = _row(rooms_sold={"studio": [4, 6, 4, 0, 0, 0, 4, 6, 8, 4, 6, 2]})
    trend = metrics._room_trend(row)
    assert [point["from"] for point in trend] == ["2025-09", "2026-03", "2026-06"]


def test_a_single_quarter_of_sales_is_not_a_dynamic() -> None:
    """Одна точка — не динамика, и колонку из неё сравнивать не с чем."""
    row = _row(rooms_sold={"studio": [None] * 11 + [5]})
    block = metrics.rooms_block(row, [], CITY).to_dict()
    assert "rooms_trend" not in block["subject"]
    assert "один квартал" in block["subject"]["rooms_trend_gap"]


def test_a_thin_quarter_is_drawn_but_named_thin() -> None:
    row = _row(rooms_sold={"studio": [1, 1, 1, 8, 6, 4, 4, 6, 8, 4, 6, 2]},
               rooms_r3=None)
    row["rooms_sold"] = {"studio": [1, 1, 1, 8, 6, 4, 4, 6, 8, 4, 6, 2],
                         "r3": [0, 0, 0, 4, 3, 2, 2, 3, 4, 2, 3, 1]}
    row.pop("rooms_r3", None)
    block = metrics.rooms_block(row, [], CITY).to_dict()
    assert block["subject"]["rooms_trend"][0]["deals"] == 3
    assert block["subject"]["rooms_trend_thin"] == 1


def test_a_shift_is_named_only_when_it_beats_the_deals_it_stands_on() -> None:
    """Доля, снятая с горстки сделок, гуляет сама по себе.

    Порог берётся из числа сделок обеих точек, а не из ощущения: названный без
    него сдвиг выглядел бы измеренным ровно так же, как настоящий.
    """
    # Ровный год: доли не меняются вовсе — сдвига нет.
    assert metrics._room_shift(metrics._room_trend(_row())) is None

    # Настоящий разворот на сотнях сделок.
    moved = _row(rooms_sold={
        "studio": [10, 10, 10, 20, 20, 20, 40, 40, 40, 60, 60, 60],
        "r3": [50, 50, 50, 40, 40, 40, 25, 25, 25, 10, 10, 10],
    })
    shift = metrics._room_shift(metrics._room_trend(moved))
    # При равных по величине сдвигах называется выросшая комнатность: «берут
    # больше студий» отвечает на вопрос раздела, «берут меньше трёшек» — его
    # зеркало. И называется она ОДНА И ТА ЖЕ на каждом запуске: порядок
    # множества давал то одну, то другую, и обе выглядели бы верными.
    assert shift["name"] == "studio"
    assert all(metrics._room_shift(metrics._room_trend(moved))["name"] == "studio"
               for _ in range(5))
    assert shift["was_pct"] == 16.7 and shift["now_pct"] == 85.7
    assert shift["deals_was"] == 180 and shift["deals_now"] == 210

    # Тот же разворот, но на горстке сделок, — не называется.
    tiny = _row(rooms_sold={"studio": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2],
                            "r3": [3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]})
    assert metrics._room_shift(metrics._room_trend(tiny)) is None


def test_the_engine_writes_the_conclusion_under_the_columns() -> None:
    """Разбор под разделом пишет движок, а не Платон.

    И молчание тоже: пустое место под колонками читается как «сказать нечего»,
    а не как «состав спроса не менялся».
    """
    from market_search import verdict

    moved = _row(rooms_sold={
        "studio": [10, 10, 10, 20, 20, 20, 40, 40, 40, 60, 60, 60],
        "r3": [50, 50, 50, 40, 40, 40, 25, 25, 25, 10, 10, 10],
    })
    said = verdict.rooms_note(metrics.rooms_block(moved, [], CITY).to_dict())["text"]
    assert "состав спроса сместился" in said, said
    assert "16,7 %" in said and "85,7 %" in said and "180" in said

    flat = verdict.rooms_note(metrics.rooms_block(_row(), [], CITY).to_dict())["text"]
    assert "не сдвинулся" in flat, flat


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
    peered = metrics.rooms_block(
        _row(), [{"name": "Без ряда", "room_mix": {"studio": {"sold": 9, "rem": 5}}}], CITY
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
            withpeers = tab.evaluate("block => roomsTable(block)", peered)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    # Две картинки: полосы и колонки состава спроса.
    assert drawn.count("<svg") == 2, drawn.count("<svg")
    assert "Как менялся состав спроса" in drawn
    # Окно названо у самой полосы: «за месяц» и «за год» — разные величины.
    assert "за 12 мес. (2025-09 — 2026-08)" in drawn, drawn[:600]
    # Пять пересекающихся линий сняты: состав — это доли, дающие сто
    # процентов, и рисуется он колонкой на сто процентов.
    assert "<path" not in drawn and "<circle" not in drawn
    # Четыре квартала на две комнатности — восемь кусков, и у каждой колонки
    # подписано, на скольких сделках она стоит.
    columns = drawn.split("Как менялся состав спроса")[1]
    assert columns.count("<rect") == 4 * 2 + 2, columns.count("<rect")
    for label in ("09.25–11.25", "06.26–08.26", "3 мес. · 21 сд.", "3 мес. · 15 сд."):
        assert label in columns, label
    # Шаг назван вслух: иначе квартальную долю читают как месячную.
    assert "Шаг квартальный" in drawn
    # Оба графика стоят НАД таблицей.
    assert drawn.rindex("<svg") < drawn.index("<table")
    # А без ряда рисуется не пустое поле, а причина.
    assert "<svg" not in silent.split("<table")[0].split("Как менялся")[-1]
    assert "прежним импортом" in silent
    # Про окно соседей говорим, только когда соседи есть: оговорка об окне
    # пустого множества читается как настоящая, а мерить там нечего.
    said = "У соседей продано — за последний месяц отчёта"
    assert said not in drawn, "оговорка о соседях без соседей"
    assert said in withpeers


# У «Пульса» снимок комнатности стоит только в том месяце, где по проекту были
# сделки: на августовской книге он есть у 202 проектов из 368, а годовой ряд —
# у 365. Пересечение 197, и 75 проектов имели ЦЕЛЫЙ ГОД продаж, о которых блок
# молчал: он требовал снимок и без него не строил ничего. Тот же случай, что
# пустой ответ НСПД, выданный за отсутствие ограничений.
def _no_snapshot() -> dict:
    row = _row()
    row.pop("room_mix")
    row["rooms_rem"] = {
        "studio": [50, 48, 46, 44, 42, 42, 40, 38, 36, 34, 32, None],
        "r3": [70, 69, 68, 66, 65, 65, 64, 63, 61, 60, 58, None],
    }
    return row


def test_a_year_of_sales_is_shown_even_without_the_last_month_snapshot() -> None:
    block = metrics.rooms_block(_no_snapshot(), [], CITY).to_dict()
    rooms = block["subject"]["rooms"]
    assert rooms["studio"]["sold_share_pct"] == 66.7
    assert rooms["r3"]["sold_share_pct"] == 33.3
    # Остаток берётся из последнего месяца, где он назван, — и вымывание видно.
    assert rooms["studio"]["rem"] == 32 and rooms["r3"]["rem"] == 58
    assert rooms["studio"]["rem_share_pct"] < rooms["studio"]["sold_share_pct"]


def test_a_remainder_that_is_not_todays_names_its_month() -> None:
    """«Сегодняшний» и «на июль» — разные ответы про одно число."""
    block = metrics.rooms_block(_no_snapshot(), [], CITY).to_dict()
    assert block["subject"]["rooms_rem_at"] == "2026-07"
    # А там, где снимок есть, даты нет: остаток и правда сегодняшний.
    assert "rooms_rem_at" not in metrics.rooms_block(_row(), [], CITY).to_dict()["subject"]


def test_a_peer_without_a_snapshot_is_counted_too() -> None:
    """Сосед с годом продаж и без снимка — это данные, а не пробел."""
    block = metrics.rooms_block(_row(), [{"name": "Без снимка", **_no_snapshot()}], CITY).to_dict()
    assert block["peers"]["projects"] == 1
    assert block["peers"]["rooms"]["studio"]["sold"] == 56
    assert block["peers"]["rooms"]["studio"]["rem"] == 32


def test_the_screen_names_the_month_of_the_remainder(tmp_path) -> None:
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    dated = metrics.rooms_block(_no_snapshot(), [], CITY).to_dict()
    today = metrics.rooms_block(_row(), [], CITY).to_dict()
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
            old = tab.evaluate("block => roomsTable(block)", dated)
            now = tab.evaluate("block => roomsTable(block)", today)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "остаток — на 2026-07" in old, old[:400]
    assert "остаток — сегодняшний" not in old, "остаток чужого месяца назван сегодняшним"
    assert "остаток — сегодняшний" in now


def test_the_dynamic_reaches_plato_by_numbers_not_by_our_sentence() -> None:
    """Пересказ своего же вывода Платон объяснить может, ответить о динамике — нет.

    Наш вывод называет ОДИН сдвиг; «что менялось у нас» — это вся таблица
    кварталов, и без неё вопрос о ней остаётся без ответа.
    """
    body = _body("reportDigest")
    assert "rooms_trend" in body, "динамика до Платона не доезжает"
    assert "по кварталам" in body
    # Числа берутся у сервера, а не считаются заново: второй счёт той же
    # величины однажды разошёлся бы с колонками, и обе картинки выглядели бы
    # верными.
    inside = body[body.index("rooms_trend"):body.index("rooms_sold_gap")]
    assert not any(sign in inside for sign in ("/100", "*100", "reduce(")), inside


def test_a_wide_table_keeps_its_first_column_when_scrolled(tmp_path) -> None:
    """Имя строки уезжает за край — и числа стоят без того, к чему относятся.

    На телефоне это читалось как «ОМНАТНОСТЬ», «тудии», «-комнатные» (экран
    владельца, 07.09.2026). Ширина — поведение, и меряется она браузером, а не
    чтением стилей.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch

    block = metrics.rooms_block(_row(), [], CITY).to_dict()
    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    with play.sync_playwright() as pw:
        try:
            browser = browser_launch.launch(pw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium недоступен: {exc}")
        try:
            tab = browser.new_page(viewport={"width": 390, "height": 780})
            tab.route("**/*", lambda route: route.abort()
                      if route.request.url.startswith("http") else route.continue_())
            tab.goto(file.as_uri())
            left = tab.evaluate(
                """block => {
                  const host=document.createElement('div');
                  host.style.width='390px';
                  host.innerHTML=roomsTable(block);
                  document.body.appendChild(host);
                  const wrap=[...host.querySelectorAll('.wrap')]
                    .find(w=>w.querySelector('table.peers'));
                  wrap.scrollLeft=wrap.scrollWidth;
                  const cell=wrap.querySelector('table.peers td');
                  return {cell:cell.getBoundingClientRect().left,
                          box:wrap.getBoundingClientRect().left,
                          text:cell.textContent, scrolled:wrap.scrollLeft};
                }""",
                block,
            )
            tab.close()
        finally:
            browser.close()
    assert left["scrolled"] > 0, "таблица не прокручивается — мерить нечего"
    assert left["cell"] >= left["box"] - 1, left
