"""Итог сверки акта в реестре несёт своё доказательство.

Поручение владельца (25.10.2026): каждая строка реестра — либо «сверено»
(редакция, пункт, дословная цитата и адрес источника), либо «не подтверждено»
с причиной и тем, что нужно для подтверждения. Подтверждать без источника
нельзя. Проверка падает на подделке: строка «сверено» без цитаты и строка «не
подтверждено» без причины — недоказанные.
"""
from __future__ import annotations

import normatives_registry as registry


def _rows() -> list[dict]:
    return registry._load_registry()


def test_every_verdict_in_the_registry_is_proven() -> None:
    bad = {row["id"]: registry.verdict_problems(row) for row in _rows()}
    bad = {key: value for key, value in bad.items() if value}
    assert not bad, bad


def test_every_status_has_a_word_on_the_page() -> None:
    for row in _rows():
        status = str(row.get("status") or "")
        assert registry._status_label(status)[0] != status, row["id"]


def test_a_verified_row_without_a_quote_is_caught() -> None:
    fake = {
        "id": "fake", "status": "verified",
        "verification": {"checked_at": "2026-10-25", "edition": "ред. от 01.01.2026",
                         "sources": [{"label": "x", "url": "https://example.org/"}],
                         "provisions": [{"point": "ст. 1", "quote": ""}]},
    }
    assert "нет пункта с дословной цитатой" in registry.verdict_problems(fake)
    fake["verification"]["sources"] = [{"label": "x", "url": ""}]
    assert "нет источника с адресом" in registry.verdict_problems(fake)


def test_not_confirmed_without_a_reason_is_caught() -> None:
    fake = {"id": "fake", "status": "not_confirmed", "unconfirmed_reason": "текста нет"}
    assert registry.verdict_problems(fake) == ["нет поля to_confirm"]


def test_the_page_shows_the_quote_and_hides_the_queue_from_readers() -> None:
    row = {"id": "x", "short_name": "Акт", "status": "not_confirmed",
           "unconfirmed_reason": "текст недоступен", "to_confirm": "нужен текст",
           "verification": {"checked_at": "2026-10-25", "edition": "ред. от 01.01.2026",
                            "sources": [{"label": "Источник", "url": "https://example.org/"}],
                            "provisions": [{"point": "ст. 1", "quote": "Дословный текст статьи"}],
                            "discrepancies": ["код считает иначе"]}}
    reader = registry._card(row, admin=False)
    admin = registry._card(row, admin=True)
    assert "Дословный текст статьи" in reader and "https://example.org/" in reader
    assert "текст недоступен" not in reader and "код считает иначе" not in reader
    assert "текст недоступен" in admin and "нужен текст" in admin and "код считает иначе" in admin
