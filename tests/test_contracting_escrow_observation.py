"""Native cumulative-cell evidence and an explicit, separate source date."""
from __future__ import annotations

import copy
import datetime
import math
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from market_search import chessboard, contracting, sales_store
from test_the_cabinet_takes_the_project_file import client, _workbook, KEY


@pytest.mark.parametrize(("raw", "paid", "observed", "reason"), [
    (0, 0.0, True, "observed"),
    (1250.25, 1250.25, True, "observed"),
    ("0", 0.0, True, "observed"),
    ("1 250,25", 1250.25, True, "observed"),
    ("1\u00a0250,25", 1250.25, True, "observed"),
    (-15, -15.0, True, "observed"),
    ("-15,25", -15.25, True, "observed"),
    (None, 0.0, False, "blank"),
    ("", 0.0, False, "blank"),
    ("  ", 0.0, False, "blank"),
    (True, 1.0, False, "boolean"),
    (False, 0.0, False, "boolean"),
    ("gibberish", 0.0, False, "not_numeric"),
    ("1 25", 125.0, False, "not_numeric"),
    ("1.2.3", 0.0, False, "not_numeric"),
    (float("nan"), float("nan"), False, "non_finite"),
    (float("inf"), float("inf"), False, "non_finite"),
    ("NaN", float("nan"), False, "not_numeric"),
    ("inf", float("inf"), False, "not_numeric"),
    ("1 250,25 ₽", 0.0, False, "unsupported_legacy_numeric_rendering"),
    ("0 руб.", 0.0, False, "unsupported_legacy_numeric_rendering"),
    ("1\u202f250,25", 0.0, False, "unsupported_legacy_numeric_rendering"),
])
def test_native_reader_observes_cells_without_rewriting_money(monkeypatch, raw, paid, observed, reason):
    header = list(contracting._COLUMNS.values())
    values = {"product": "Квартира", "unit": "корп 1 кв.1", "date": "12.08.2025",
              "area": 40, "amount": 4_000_000, "units": 1,
              "price_per_sqm": 100_000, "broker_fee": 100, "broker_rate": 0.03,
              "sales_bonus_paid": 5, "broker_name": "Тест", "escrow_total": raw}
    rows = [[] for _ in range(5)] + [header, [values.get(k) for k in contracting._COLUMNS]]
    monkeypatch.setattr(contracting, "_rows", lambda *_a: rows)
    monkeypatch.setattr(contracting, "_attach_brokers", lambda *_a, **_k: [])
    row = contracting.read_contracts(b"synthetic-raw-cells")["rows"][0]
    if math.isnan(paid):
        assert math.isnan(row["escrow_paid"])
    else:
        assert row["escrow_paid"] == paid
    assert {k: row[k] for k in ["area", "amount", "units", "contract_price_per_sqm",
                               "broker_fee", "broker_rate", "sales_bonus_paid"]} == {
        "area": 40.0, "amount": 4_000_000.0, "units": 1.0,
        "contract_price_per_sqm": 100_000.0, "broker_fee": 100.0,
        "broker_rate": 0.03, "sales_bonus_paid": 5.0}
    assert row["escrow_observed"] is observed
    evidence = row["escrow_evidence"]
    assert evidence["reason"] == reason
    assert evidence["sheet"] == "Контрактация" and evidence["row"] == 7
    assert evidence["column"] == header.index("оплачено эскроу всего") + 1
    assert evidence["header"] == "оплачено эскроу всего"
    assert "value" not in evidence
    # A numeric cell in an unrecognised adjacent column cannot prove completeness.
    header[-1] = "неизвестная сумма"
    row = contracting.read_contracts(b"synthetic-raw-cells")["rows"][0]
    assert row["escrow_paid"] == 0.0
    assert row["escrow_observed"] is False
    assert row["escrow_evidence"]["reason"] == "native_column_missing"


def _stored(project="Проверочный ЖК"):
    return sales_store.load(sales_store.default_dir(), project)


def test_explicit_date_is_persisted_only_with_contracting_and_absent_date_stays_unknown(client):
    data = _workbook()
    baseline = contracting.read_contracts(data)
    first = client.post("/cabinet/contracting", content=data,
                        params={"escrow_as_of": "2026-01-02", "as_of": "2025-12-01"})
    assert first.status_code == 200, first.text
    source = _stored()["sources"]["contracting"]
    saved = source["data"]
    assert saved["as_of"] == "2026-01-02"
    assert saved["as_of_provenance"] == "uploader_declared"
    assert {k: v for k, v in saved.items() if k not in {"as_of", "as_of_provenance"}} == baseline
    assert source["at"][:10] != "2026-01-02"  # Upload timestamp is separate evidence.
    second = client.post("/cabinet/contracting", content=data,
                         params={"escrow_as_of": "2026-01-03"})
    assert second.status_code == 200
    assert _stored()["sources"]["contracting"]["data"]["as_of"] == "2026-01-03"
    # A later undated upload cannot borrow the previous date or its upload time.
    third = client.post("/cabinet/contracting", content=data, headers={"x-file-name": "2026-01-04.xlsx"})
    assert third.status_code == 200
    assert _stored()["sources"]["contracting"]["data"] == baseline


@pytest.mark.parametrize("value", ["2026-02-30", "2026-1-02", "2026-01-02T00:00:00", "not-a-date", "future"])
def test_invalid_date_never_partially_overwrites_sources(client, value):
    data = _workbook()
    assert client.post("/cabinet/contracting", content=data).status_code == 200
    before = _stored()
    if value == "future":
        value = (datetime.datetime.now(ZoneInfo("Europe/Moscow")).date() + datetime.timedelta(days=1)).isoformat()
    response = client.post("/cabinet/contracting", content=data, params={"escrow_as_of": value})
    assert response.status_code == 422
    assert "эскроу" in response.json()["detail"]
    assert _stored() == before


def test_both_dates_remain_separate_and_bad_chessboard_date_saves_neither(client, monkeypatch):
    from test_sales_chessboard import snapshot
    board = snapshot()
    monkeypatch.setattr(chessboard, "read", lambda *_a: copy.deepcopy(board))
    response = client.post("/cabinet/contracting", content=_workbook(), params={
        "as_of": "2026-01-01", "escrow_as_of": "2026-01-02"})
    assert response.status_code == 200, response.text
    sources = _stored()["sources"]
    assert sources["contracting"]["data"]["as_of"] == "2026-01-02"
    assert all(b["as_of"] == "2026-01-01" for b in sources["chessboard"]["data"]["buildings"].values())
    before = _stored()
    rejected = client.post("/cabinet/contracting", content=_workbook(), params={"escrow_as_of": "2026-01-03"})
    assert rejected.status_code == 422
    assert _stored() == before


def test_validation_uses_the_moscow_calendar_day_at_the_utc_boundary(client, monkeypatch):
    from market_search import api

    class BoundaryClock(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            assert str(tz) == "Europe/Moscow"
            return datetime.datetime(2026, 1, 1, 21, 30, tzinfo=datetime.timezone.utc).astimezone(tz)

    monkeypatch.setattr(api, "datetime", SimpleNamespace(date=datetime.date, datetime=BoundaryClock))
    accepted = client.post("/cabinet/contracting", content=_workbook(), params={"escrow_as_of": "2026-01-02"})
    assert accepted.status_code == 200, accepted.text
    before = _stored()
    rejected = client.post("/cabinet/contracting", content=_workbook(), params={"escrow_as_of": "2026-01-03"})
    assert rejected.status_code == 422 and _stored() == before


def test_optional_date_does_not_grant_guest_or_web_session_upload_access(client):
    guest = TestClient(client.app)
    for session in [False, True]:
        if session:
            guest.cookies.set("plato_web_session", "synthetic-unprivileged-session")
        response = guest.post("/cabinet/contracting", content=_workbook(),
                              params={"escrow_as_of": "not-a-date"})
        assert response.status_code == 401
    assert _stored().get("sources", {}) == {}


def test_actual_cabinet_upload_captures_both_dates_separately(client):
    import main_registry
    from browser import chromium_or_skip, serve
    from playwright.sync_api import expect, sync_playwright

    captured = []
    with serve(main_registry.app, 18943) as base, sync_playwright() as pw:
        chromium = pw.chromium.launch(executable_path=str(chromium_or_skip()))
        try:
            page = chromium.new_page(viewport={"width": 1280, "height": 900})
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
            page.request.post(base + "/cabinet/login", form={"key": KEY})
            page.goto(base + "/cabinet/sales", wait_until="domcontentloaded")
            expect(page.locator("#cf")).to_be_enabled()
            expect(page.locator("#escrowAsOf")).to_be_visible()
            assert "Дата состояния эскроу (если указана в выгрузке)" in page.locator("#escrowAsOf").locator("..").inner_text()
            assert page.locator("#escrowAsOf").input_value() == ""
            page.locator("#chessboardDate").fill("2026-01-01")
            page.locator("#escrowAsOf").fill("2026-01-02")

            def upload(route):
                captured.append(parse_qs(urlsplit(route.request.url).query))
                route.fulfill(status=422, json={"detail": "Проверка параметров"})

            page.route("**/cabinet/contracting?*", upload)
            page.locator("#cf").set_input_files({"name": "synthetic.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": b"probe"})
            expect(page.locator("#cfstate")).to_have_text("Проверка параметров")
            assert captured[-1]["as_of"] == ["2026-01-01"]
            assert captured[-1]["escrow_as_of"] == ["2026-01-02"]
            page.locator("#escrowAsOf").fill("")
            page.locator("#cf").set_input_files({"name": "synthetic.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": b"probe"})
            expect(page.locator("#cf")).to_be_enabled()
            page.wait_for_function("document.getElementById('cf').value === ''")
            assert captured[-1]["as_of"] == ["2026-01-01"]
            assert "escrow_as_of" not in captured[-1]
        finally:
            chromium.close()
