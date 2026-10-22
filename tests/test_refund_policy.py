"""Оферта и политика возврата: опубликованный текст, реквизиты и цены из одного источника.

Решение владельца 22.10.2026: полный возврат — 14 дней, пока участок не
посчитан; частному лицу после расчёта — остаток дней минус половина цены.
Здесь закреплено:

- `/refund` — не заготовка: плашки нет, оплата этим текстом не заблокирована;
- продавец, свидетельство и цены в тексте — из `docs/legal/product.json` и
  `access_terms()`, а не вписаны руками: смена цены меняет и политику;
- поле, которого нет в источнике, видно как ошибка и блокирует оплату.

Запуск: python3 -m pytest tests/test_refund_policy.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as _wrapper  # noqa: E402

core = _wrapper.core
client = TestClient(core.app)


def test_the_refund_policy_is_published_not_a_placeholder():
    text, filled = core.legal_text("refund")
    assert filled, "в refund.md осталась пометка заготовки"
    page = client.get("/refund").text
    assert "Заготовка." not in page
    assert "<h2>Как попросить возврат</h2>" in page
    assert "14 дней" in page and "половины цены" in page
    assert not any("политики возврата" in m for m in core.payments_missing())


def test_the_seller_and_prices_come_from_one_source(monkeypatch):
    seller = core.seller_info()
    page = client.get("/refund").text
    for value in (seller["name"], seller["inn"], seller["ogrnip"], seller["email"]):
        assert value in page
    assert core.product_info()["certificate_number"] in page
    assert "{{" not in page and "не задано" not in page
    plain = page.replace("\u00a0", " ")
    assert "стоит 10 000 ₽" in plain and "стоит 100 000 ₽" in plain
    monkeypatch.setenv("DEVELOPAID_PLOT_PRICE_RUB", "12000")
    assert "стоит 12 000 ₽" in client.get("/refund").text.replace("\u00a0", " ")


def test_an_unknown_field_is_an_error_and_blocks_payment(monkeypatch, tmp_path):
    legal = tmp_path / "legal"
    legal.mkdir()
    (legal / "product.json").write_text(
        (core._LEGAL_DIR / "product.json").read_text(encoding="utf-8"), encoding="utf-8")
    (legal / "offer.md").write_text("# Оферта\n\nТекст.", encoding="utf-8")
    (legal / "refund.md").write_text("# Возврат\n\nПишите на {{seller.fax}}.", encoding="utf-8")
    monkeypatch.setattr(core, "_LEGAL_DIR", legal)
    filled, missing = core.legal_fill(core.legal_text("refund")[0])
    assert missing == ["seller.fax"] and "[не задано: seller.fax]" in filled
    assert any("seller.fax" in m for m in core.payments_missing())


def test_the_offer_is_published_with_the_same_sources(monkeypatch):
    assert core.legal_text("offer")[1], "в offer.md осталась пометка заготовки"
    assert not any("оферты" in m or "offer.md" in m for m in core.payments_missing())
    page = client.get("/offer").text
    assert "Заготовка." not in page and "{{" not in page and "не задано" not in page
    assert "<h2>4. Тарифы и оплата</h2>" in page
    seller = core.seller_info()
    for value in (seller["inn"], seller["ogrnip"], seller["email"],
                  core.product_info()["certificate_number"]):
        assert value in page
    monkeypatch.setenv("DEVELOPAID_SUBSCRIPTION_DAYS", "31")
    monkeypatch.setenv("DEVELOPAID_SUBSCRIPTION_PRICE_RUB", "90000")
    plain = client.get("/offer").text.replace("\u00a0", " ")
    assert "Подписка стоит 90 000 ₽" in plain and "составляет 31 дней" in plain
