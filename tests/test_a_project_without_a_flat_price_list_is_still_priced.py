"""Цена метра у проекта, который продаёт не квартиры.

Владелец 08.09.2026: «Почему поиск видит ЖК Зорге 9, я выбираю его, а в отчёте
написано что проект не найден». В отчёте по Зорге 9 раздел «Цена метра» стоял
пустым — «Данных по проекту нет, сравнивать нечего», — а страницей ниже тот же
отчёт считал по этому проекту премию к соседям +16,0 % и вёл его линию в
динамике цены числом 707 246 ₽/м². Два раздела одного отчёта об одной величине
говорили разное, и оба выглядели верными.

Причина в том, о чём спрошен источник. Прайс-лист приходит по КВАРТИРАМ
(`current_price.flat_sqm_price`), а помесячный ряд — по жилью целиком
(`object_type: "living"`). У Зорге 9 в справочнике 921 апартамент и ни одной
квартиры, и прайс-лист пуст по построению; таких проектов в выгрузке за
2026-08 — 77 из 685.

Что ряд и прайс-лист — одна и та же величина источника, видно в самом отчёте:
у соседей, где есть оба числа, они совпадают до рубля (ИНДИ Тауэрз 612 278,
Ракурс 582 029 — и в столбиках прайсов, и в легенде ряда).
"""

import math
from datetime import date
from types import SimpleNamespace

from market_search.metrics import BLOCK_PRICE


def _price_block(report):
    return next(block for block in report["blocks"] if block["code"] == BLOCK_PRICE)


def _pulse(segments, metrics, projects, history):
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
        segments=lambda: segments,
        near=near,
        # `complex_id` в метриках — не украшение: строка соседа собирается из
        # них, и по нему потом ищется его ряд цен.
        metrics=lambda cid: ({"complex_id": cid, **metrics[cid]} if cid in metrics else {}),
        price=lambda cid: (
            {"price_per_sqm": metrics[cid]["price_per_sqm"],
             "observed_at": metrics[cid].get("observed_at")}
            if metrics.get(cid, {}).get("price_per_sqm") else None
        ),
        project_totals=lambda cid: {},
        find_project=lambda query: None,
        price_history=lambda ids, months=12: {
            cid: points for cid, points in history.items() if cid in ids
        },
        remaining=lambda cid: {},
    )


def _service(tmp_path, history, *, subject_price=None):
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    # Порог свежести считается от «сегодня», и прибитая дата держит проверку на
    # своём месте: без неё она позеленеет сегодня и покраснеет через полгода.
    service.verified_prices.today = date(2026, 9, 8)
    segments = {476: "Бизнес", 4987: "Бизнес", 5549: "Бизнес"}
    metrics = {
        # У объекта прайс-листа нет вовсе — он продаёт апартаменты.
        476: {"units_per_month": 10.2, "sold_lot_avg": 45.7},
        4987: {"price_per_sqm": 541_612, "observed_at": "2026-08-20", "units_per_month": 8.1},
        5549: {"units_per_month": 27.0},
    }
    if subject_price:
        metrics[476] = {**metrics[476], **subject_price}
    projects = [
        {"complex_id": 476, "name": "Зорге 9", "developer": "St Michael",
         "latitude": 55.78270, "longitude": 37.50884,
         "address": "Москва, ул. Зорге, вл.9 А"},
        {"complex_id": 4987, "name": "Дом на Зорге", "developer": "А101",
         "latitude": 55.78500, "longitude": 37.51200,
         "address": "г. Москва, ул. Зорге, вл. 25"},
        {"complex_id": 5549, "name": "ИНДИ Тауэрз", "developer": "Аквилон",
         "latitude": 55.78900, "longitude": 37.51900,
         "address": "Москва, Хорошевское ш., вл. 38"},
    ]
    service.pulse = _pulse(segments, metrics, projects, history)
    return service


def test_the_subject_price_comes_from_the_series_when_the_list_is_empty(tmp_path) -> None:
    service = _service(
        tmp_path,
        {
            476: [{"month": "2026-07", "value": 700_000},
                  {"month": "2026-08", "value": 707_246}],
            5549: [{"month": "2026-08", "value": 612_278}],
        },
    )
    report = service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE])

    assert report["subject"]["metrics"]["price_per_sqm"] == 707_246
    price = _price_block(report)
    assert price["subject"]["price_per_sqm"] == 707_246
    # Основание — часть числа: ряд, подписанный прайс-листом, это одно,
    # названное другим.
    assert price["subject"]["basis"] == "помесячный ряд источника, не сделка"
    assert price["subject"]["observed_at"] == "2026-08"
    assert any("Прайс-листа квартир у проекта нет" in note for note in price["notes"])
    assert not any("сравнивать нечего" in note for note in price["notes"])


def test_the_flat_price_list_wins_where_it_exists(tmp_path) -> None:
    """Ряд подставляется только вместо пустого прайса, а не вместо прайса."""
    service = _service(
        tmp_path,
        {476: [{"month": "2026-08", "value": 707_246}]},
        subject_price={"price_per_sqm": 690_000, "observed_at": "2026-08-30"},
    )
    price = _price_block(service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE]))
    assert price["subject"]["price_per_sqm"] == 690_000
    assert price["subject"]["basis"] == "прайс-лист, не сделка"


def test_an_old_point_is_not_a_price_but_is_not_silence_either(tmp_path) -> None:
    """«Цены нет» и «цены нет с ноября» — разные ответы, и второй у нас есть."""
    service = _service(tmp_path, {476: [{"month": "2025-11", "value": 640_000}]})
    price = _price_block(service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE]))
    assert "subject" not in price or not price["subject"].get("price_per_sqm")
    assert any("2025-11" in note and "640 000" in note for note in price["notes"])


def test_a_neighbour_is_priced_by_the_same_rule_and_the_count_is_named(tmp_path) -> None:
    """Одна величина — один ответ: у соседа цена берётся тем же правилом.

    И берётся не молча: сколько цен пришло не из прайс-листа, стоит в своде
    рядом с «цены нет вовсе у стольких-то».
    """
    service = _service(
        tmp_path,
        {
            476: [{"month": "2026-08", "value": 707_246}],
            5549: [{"month": "2026-08", "value": 612_278}],
        },
    )
    report = service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE])
    peer = next(row for row in report["peers"] if row["name"] == "ИНДИ Тауэрз")
    assert peer["price_per_sqm"] == 612_278
    assert peer["price_status"] == "по ряду"
    assert report["comparison"]["price_from_series"] == 1
    assert report["comparison"]["no_price"] == 0


def test_a_neighbour_without_any_series_stays_without_a_price(tmp_path) -> None:
    """Пустой ряд ценой не становится: «нет» остаётся «нет»."""
    service = _service(tmp_path, {476: [{"month": "2026-08", "value": 707_246}]})
    report = service.build_report("55.78270, 37.50884", codes=[BLOCK_PRICE])
    peer = next(row for row in report["peers"] if row["name"] == "ИНДИ Тауэрз")
    assert not peer.get("price_per_sqm")
    assert peer["price_status"] == "нет"
    assert report["comparison"]["no_price"] == 1
    assert report["comparison"]["price_from_series"] == 0


def test_the_screen_names_how_many_prices_came_from_the_series(tmp_path) -> None:
    """Молча подставленная цена неотличима от прайсовой — значит она названа.

    Строка охвата уже говорит «цены нет вовсе у стольких-то»; рядом с ней стоит
    и число цен, взятых из ряда. Проверяется отрисовкой: строка есть в исходнике
    страницы всегда, а появляется она только при непустом числе.
    """
    import pytest

    play = pytest.importorskip("playwright.sync_api")

    import browser_launch
    from market_search import cabinet

    page = cabinet.cabinet_page("market").replace("__DEVELOPAID_VERSION__", "test")
    file = tmp_path / "market.html"
    file.write_text(page, encoding="utf-8")
    payload = {
        "subject": {"project_name": "Зорге 9", "metrics": {}},
        "retrieved_at": "2026-09-08",
        "comparison": {"radius_km": 3, "found": 69, "comparable": 66, "used": 40,
                       "stale_price": 6, "no_price": 13, "fresh_since": "2026-03-01",
                       "price_from_series": 1},
    }
    silent = {**payload, "comparison": {**payload["comparison"], "price_from_series": 0}}
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
            said = tab.evaluate("d => printHead(d)", payload)
            quiet = tab.evaluate("d => printHead(d)", silent)
            tab.close()
        finally:
            browser.close()
    assert not errors, errors
    assert "цена взята из помесячного ряда" in said
    assert "цены нет вовсе у 13" in said
    # Ни одной такой цены — и строки нет: постоянная приписка перестаёт читаться.
    assert "помесячного ряда" not in quiet
