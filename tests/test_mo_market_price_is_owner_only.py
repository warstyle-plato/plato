"""Справочник Кср меняет только владелец сервиса.

Кср — множитель платы за смену ВРИ в каждом расчёте по Подмосковью, а запись
ложится на диск для всех. Маршруты записи были открыты любому посетителю:
одним запросом можно было подменить плату в чужих расчётах и PDF.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

main = _wrapper.core
client = TestClient(main.app)

ROWS = {"rows": [{"municipality": "Мытищи", "price_rub_per_sqm": 1}]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:mo-price-test-token")
    monkeypatch.setenv("DEVELOPAID_ADMIN_KEY", "owner-key-for-test")
    monkeypatch.setattr(main, "_MO_MARKET_PRICE_PATH", tmp_path / "mo_market_price.csv")
    monkeypatch.setattr(main, "_mo_market_price", None)
    yield


def test_a_stranger_cannot_rewrite_the_reference():
    before = main._mo_market_price_for("Мытищи")[0]
    answer = client.post("/mo/market-price", json=ROWS)
    assert answer.status_code == 403
    assert main._mo_market_price_for("Мытищи")[0] == before
    assert not main._MO_MARKET_PRICE_PATH.exists()


def test_a_stranger_cannot_import_the_reference():
    answer = client.post("/mo/market-price/import", content=b"PK\x03\x04junk")
    assert answer.status_code == 403
    assert not main._MO_MARKET_PRICE_PATH.exists()


def test_a_wrong_key_is_refused():
    answer = client.post("/mo/market-price", json={**ROWS, "key": "not-the-key"})
    assert answer.status_code == 403


def test_without_an_owner_configured_writing_stays_closed(monkeypatch):
    monkeypatch.delenv("DEVELOPAID_ADMIN_KEY", raising=False)
    monkeypatch.setattr(main, "usage_admin_ids", lambda: set())
    assert client.post("/mo/market-price", json=ROWS).status_code == 403


def test_the_owner_still_writes_it():
    answer = client.post("/mo/market-price", json={**ROWS, "key": "owner-key-for-test"})
    assert answer.status_code == 200, answer.text
    assert main._mo_market_price_for("Мытищи")[0] == 1


def test_reading_stays_open():
    assert client.get("/mo/market-price").status_code == 200
