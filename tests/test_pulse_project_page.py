"""Стадия, сроки и остатки аналога — со страницы проекта «Пульса», по корпусам.

Сверка владельца по ЗИЛАРТ (05.10.2026): у Пульса «Начало продаж — Ноябрь
2015», «Срок сдачи 18/IV-27/IV», стадия по корпусам «ввз (сдан/гк) — 18,
верхние этажи — 2»; у нас — старт 01.09.2015, «план. ввод —», «стадия не
указана», «Остаток 1 416» без единиц. Стадия искалась по смыслу ключа в
карте и таблице проекта, где её нет; живёт она на странице проекта.

Образцы в `tests/fixtures/pulse/` собраны по тексту скриншотов владельца:
содержание — как в ЛК, вёрстка — реконструкция. Что разбор узнаёт на живой
странице, показывает маршрут `/market/pulse/project-page`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from market_search import price_hint_ui
from market_search.pulse import PulseClient, PulseProject, _dates_from_project_html, _stage_from_payload
from market_search.pulse_page import delivery_span, month_date, parse_project_page, remaining_figures

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pulse"
PAGE = (FIXTURES / "zilart_project_page.html").read_text(encoding="utf-8")
BALLOON = (FIXTURES / "zilart_balloon.html").read_text(encoding="utf-8")


def test_the_old_reading_misses_what_the_owner_saw() -> None:
    """Контрпример: прежний разбор на этих образцах ничего из нужного не видит."""
    assert _stage_from_payload({"html": PAGE}) is None
    assert _dates_from_project_html(BALLOON).get("sales_start") != "2015-11-01"
    assert not _dates_from_project_html(BALLOON).get("commissioning")


def test_the_project_page_gives_the_stage_by_buildings() -> None:
    parsed = parse_project_page(PAGE)
    assert parsed["as_of"] == "2026-10-01"
    summary = parsed["stage"]
    assert [(row["code"], row["buildings"]) for row in summary["distribution"]] == [
        ("done", 18), ("frame", 2)]
    assert summary["buildings"] == 20
    # Для цены — самая ранняя незавершённая стадия: в продаже строящиеся
    # корпуса, а не сданные проданные. Самая поздняя — рядом.
    assert summary["price_stage"]["code"] == "frame"
    assert summary["latest_stage"]["code"] == "done"
    assert "незавершённая" in summary["rule"]

    assert parsed["contract"] == [{"value": "ДКПН", "buildings": 18}, {"value": "ДДУ", "buildings": 2}]
    assert parsed["status"] == [{"value": "полностью продан", "buildings": 16},
                                {"value": "в продаже", "buildings": 4}]
    assert parsed["escrow"] == [{"value": "нет", "buildings": 15},
                                {"value": "Россельхозбанк", "buildings": 5}]
    assert parsed["flats"] == {"units": 11321, "area_sqm": 631246.0, "remaining_pct": 10.48}
    assert parsed["commercial"] == {"units": 1145, "area_sqm": 124420.0}
    assert parsed["parking"] == {"units": 7749, "ratio": 0.68}
    assert parsed["storage"] == {"units": 634}
    assert parsed["buildings"] == 20
    assert parsed["land_ha"] == 129.68
    assert parsed["floors"] == {"min": 5.0, "max": 43.0}
    assert parsed["ceiling"] == {"min": 2.85, "max": 5.7}
    assert parsed["technology"] == "монолит"


def test_the_balloon_gives_dates_remaining_and_pace_with_units() -> None:
    parsed = parse_project_page(BALLOON)
    assert parsed["as_of"] == "2026-09-01"
    assert parsed["sales_start"] == "2015-11-01"
    assert parsed["delivery"] == {"raw": "18/IV-27/IV", "first": "2018-12-01", "last": "2027-12-01"}
    assert parsed["remaining"] == {"area_sqm": 55926.0, "remaining_pct": 9.0}
    assert parsed["pace"] == {"sqm_per_month": 3786.0, "window_months": 3}
    assert parsed["exposure_price_per_sqm"] == 666698
    # Стадия без разбивки по корпусам: число корпусов неизвестно, а не ноль.
    assert parsed["stage"]["buildings"] is None
    assert parsed["stage"]["price_stage"]["code"] == "frame"
    figures = remaining_figures(parsed)
    assert {"value": 55926.0, "unit": "м²", "basis": "жильё, м²", "as_of": "2026-09-01"} in figures


def test_dates_in_words_and_quarters() -> None:
    assert month_date("Ноябрь 2015") == "2015-11-01"
    assert month_date("1 октября 2026") == "2026-10-01"
    assert month_date("мая 2027") == "2027-05-01"
    assert month_date("март 2027") == "2027-03-01"
    assert month_date("2015") is None
    assert delivery_span("21/II") == {"raw": "21/II", "first": "2021-06-01", "last": "2021-06-01"}
    assert delivery_span("нет") is None


def _client(tmp_path: Path, page: str, table: dict | None = None) -> PulseClient:
    client = PulseClient(tmp_path, login="l", password="p")
    client._projects = [PulseProject("1695", "ЗИЛАРТ", 55.70, 37.64)]
    client._post_json = lambda path, payload: dict(table or {})  # type: ignore[assignment]
    client._cookie = lambda name: "cookie"  # type: ignore[assignment]
    client._open = lambda path, **kwargs: page.encode("utf-8")  # type: ignore[assignment]
    return client


def test_the_client_reads_the_stage_from_the_page_and_names_the_source(tmp_path: Path) -> None:
    client = _client(tmp_path, PAGE)
    got = client.project_stage("1695")
    assert got["source"] == "pulse_project_page"
    assert got["raw"].startswith("верхние этажи")
    assert got["latest_raw"] == "ввз (сдан/гк)"
    assert got["as_of"] == "2026-10-01"
    assert sum(row["buildings"] for row in got["distribution"]) == 20

    facts = client.project_facts("1695")
    assert facts["source"] == "страница проекта Пульса" and facts["as_of"] == "2026-10-01"
    assert {"value": 10.48, "unit": "%", "basis": "квартиры, шт.", "as_of": "2026-10-01"} in facts["remaining_figures"]


def test_dates_disagreeing_between_sources_are_all_shown(tmp_path: Path) -> None:
    """Сентябрь против ноября: берётся страница, а все источники видны."""
    client = _client(tmp_path, BALLOON, table={"sales_start_date": "2015-09-01"})
    got = client.project_dates("1695")
    assert got["sales_start"] == "2015-11-01"
    assert got["commissioning"] == "2027-12-01"
    assert got["commissioning_first"] == "2018-12-01"
    assert "последний корпус" in got["commissioning_rule"]
    assert got["sources"] == {"sales_start": "pulse_project_page", "commissioning": "pulse_project_page"}
    assert got["candidates"]["sales_start"] == {
        "pulse_project_page": "2015-11-01", "pulse_api_table": "2015-09-01"}


def test_the_page_is_fetched_once_and_a_failure_is_not_cached(tmp_path: Path) -> None:
    import urllib.error

    client = _client(tmp_path, PAGE)
    calls: list[str] = []

    def failing(path, **kwargs):
        calls.append(path)
        raise urllib.error.URLError("timeout")

    client._open = failing  # type: ignore[assignment]
    assert "не открылась" in client.project_page("1695")["reason"]
    client._open = lambda path, **kwargs: (calls.append(path), PAGE.encode("utf-8"))[1]  # type: ignore[assignment]
    assert client.project_page("1695")["parsed"]["stage"]
    client.project_page("1695")
    client.project_stage("1695")
    assert calls == ["/complex/1695/", "/complex/1695/"]


def test_the_price_hint_carries_the_distribution_and_counts_coverage(tmp_path: Path, monkeypatch) -> None:
    from market_search.service_v6 import MarketDiscoveryService

    service = MarketDiscoveryService(tmp_path)
    service.pulse.login = "x"
    service.pulse.password = "x"
    service.verified_prices.today = date(2026, 10, 5)
    zilart = PulseProject("1695", "ЗИЛАРТ", 55.70, 37.64)
    other = PulseProject("7", "Без страницы", 55.71, 37.64)
    monkeypatch.setattr(service.pulse, "near", lambda *_a, **_k: [(0.5, zilart), (0.9, other)])
    monkeypatch.setattr(service.pulse, "segments", lambda: {"1695": "Бизнес", "7": "Бизнес"})
    monkeypatch.setattr(service.pulse, "price", lambda cid: {
        "price_per_sqm": 668_362, "lot_count": 10, "observed_at": "2026-10-01"})
    monkeypatch.setattr(service.cards, "card", lambda cid: {})
    monkeypatch.setattr(service.dynamics, "latest", lambda *_a, **_k: {})
    monkeypatch.setattr(service.dynamics, "series", lambda *_a, **_k: [])
    pages = {"1695": PAGE, "7": "<html></html>"}
    monkeypatch.setattr(service.pulse, "_cookie", lambda name: "cookie")
    monkeypatch.setattr(service.pulse, "_post_json", lambda path, payload: {})
    monkeypatch.setattr(service.pulse, "_open",
                        lambda path, **kw: pages.get(path.strip("/").split("/")[-1], "").encode("utf-8"))

    hint = service.price_hint(address="Москва", latitude=55.70, longitude=37.64, include_projects=True)
    row = next(p for p in hint["projects"] if p["complex_id"] == "1695")
    assert row["construction_stage"] == "frame"
    assert row["construction_stage_origin"] == "pulse"
    assert row["construction_stage_source"] == "pulse_project_page"
    assert row["construction_stage_latest_label"] == "сдан"
    assert [r["buildings"] for r in row["construction_stage_distribution"]] == [18, 2]
    assert row["page_facts"]["status"][1] == {"value": "в продаже", "buildings": 4}
    blank = next(p for p in hint["projects"] if p["complex_id"] == "7")
    assert blank["construction_stage_reason"] == "на странице проекта нет подписи «Стадия строительства»"

    coverage = hint["source_coverage"]
    assert coverage["peers"] == 2
    assert coverage["stage_from_pulse"] == {"count": 1, "pct": 50.0}
    assert coverage["stage_distribution"]["count"] == 1


def _details() -> dict:
    return {
        "available": True, "basis": "peers", "basis_title": "по сопоставимым проектам рядом",
        "price_per_sqm": 668362, "sample": 1, "segment": "Бизнес",
        "source_coverage": {
            "peers": 4, "stage_from_pulse": {"count": 1, "pct": 25.0},
            "stage_from_calendar": {"count": 1, "pct": 25.0},
            "stage_distribution": {"count": 1, "pct": 25.0},
            "commissioning": {"count": 2, "pct": 50.0}, "sales_start": {"count": 3, "pct": 75.0},
        },
        "projects": [{
            "complex_id": "1695", "name": "ЗИЛАРТ", "price_per_sqm": 668362, "eligible": True,
            "sales_start": "2015-11-01", "commissioning": "2027-12-01",
            "commissioning_first": "2018-12-01", "commissioning_raw": "18/IV-27/IV",
            "date_sources": {"sales_start": "pulse_project_page", "commissioning": "pulse_project_page"},
            "date_candidates": {"sales_start": {"pulse_project_page": "2015-11-01",
                                                "pulse_api_table": "2015-09-01"}},
            "construction_stage": "frame", "construction_stage_label": "каркас",
            "construction_stage_origin": "pulse", "construction_stage_origin_title": "Пульс",
            "construction_stage_latest_label": "сдан",
            "construction_stage_rule": "самая ранняя незавершённая стадия корпусов",
            "construction_stage_distribution": [
                {"raw": "ввз (сдан/гк)", "code": "done", "buildings": 18},
                {"raw": "верхние этажи", "code": "frame", "buildings": 2}],
            "page_facts": {"as_of": "2026-10-01",
                           "status": [{"value": "в продаже", "buildings": 4}],
                           "remaining_figures": [{"value": 10.48, "unit": "%", "basis": "квартиры, шт.",
                                                  "as_of": "2026-10-01"}]},
            "sales": {"rem": 1416},
        }],
        "stage_filter": None,
    }


def test_the_rendered_page_shows_coverage_buildings_and_units() -> None:
    import browser

    path = browser.chromium_or_skip()
    from playwright.sync_api import sync_playwright

    def route(route):
        if route.request.url.endswith("/market/price-hint/details"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(_details()))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=price_hint_ui.page())

    with sync_playwright() as pw, pw.chromium.launch(executable_path=str(path)) as engine:
        page = engine.new_page()
        page.route("http://stand.local/**", route)
        page.goto("http://stand.local/cabinet/price-hint?latitude=55.75&longitude=37.6")
        page.wait_for_selector("#sourceCoverage")
        coverage = page.inner_text("#sourceCoverage")
        badge = page.inner_text("#rows tr:first-child td:nth-child(9)")
        page.click("button.open")
        page.wait_for_selector("#pageFacts")
        modal = page.inner_text("#modalBody")

    assert "Аналогов 4" in coverage and "стадия с Пульса 1 из 4" in coverage, coverage
    assert "плановый ввод 2 из 4" in coverage, coverage
    assert "каркас" in badge and "самая поздняя: сдан" in badge, badge
    assert "ввз (сдан/гк) — 18 корп." in modal and "верхние этажи — 2 корп." in modal, modal
    assert "в продаже — 4 корп." in modal, modal
    assert "10,48 %" in modal.replace(" ", " ") or "10.48 %" in modal, modal
    assert "Остаток, шт · месячная выгрузка" in modal, modal
    assert "«18/IV-27/IV»" in modal and "Первый корпус сдан" in modal, modal
    assert "таблица проекта (API): 01.09.2015" in modal, modal


def test_a_worded_month_is_no_longer_dropped_by_the_common_date_reader() -> None:
    """«Ноябрь 2015» в карте/таблице прежде отбрасывался, и побеждал другой источник."""
    from market_search.pulse import _dates_from_payload, _pulse_date

    assert _pulse_date("Ноябрь 2015") == "2015-11-01"
    assert _dates_from_payload({"sales_start": "Ноябрь 2015"}) == {"sales_start": "2015-11-01"}
