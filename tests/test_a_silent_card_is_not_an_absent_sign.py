"""Непрочитанная карточка города — не «реновации нет».

«Нет никаких признаков реновации и тп» (владелец, 02.09.2026). Застройщик и
реновация приходят с карточки krt.mos.ru — бесплатно, без поиска, — и колонка
была пуста у всех подряд. Причина оказалась не в разборе: чтение карточки
падало на цепочке сертификата, а отказ НЕ ЗАПИСЫВАЛСЯ вовсе. Отсюда три беды
разом: неотвечающая карточка не становилась «известной» никогда, фоновой добор
перечитывал её при каждом открытии каталога, и посчитать, что не отвечает ни
одна, было нечем. Общий отказ источника выглядел на экране ровно как
отсутствие признака.

Запуск: python3 -m pytest tests/test_a_silent_card_is_not_an_absent_sign.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import KrtRegistry  # noqa: E402


def registry(tmp_path: Path, fetch) -> KrtRegistry:
    reg = KrtRegistry(str(tmp_path))
    reg.fetch = fetch  # type: ignore[method-assign]
    return reg


def test_a_refused_card_is_written_down(tmp_path: Path) -> None:
    """Отказ ложится на диск: иначе он не виден никакому счёту."""
    def refuse(url: str, **kwargs):
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")

    reg = registry(tmp_path, refuse)
    out = reg.card_facts("nagatino-1")
    assert out["available"] is False
    assert "CERTIFICATE" in out["reason"]
    saved = tmp_path / "krt" / "cards" / "nagatino-1.json"
    assert saved.exists(), "отказ не записан — посчитать его будет нечем"


def test_a_refusal_is_not_asked_again_at_once(tmp_path: Path) -> None:
    """Второе открытие каталога не стучится в город повторно."""
    calls: list[str] = []

    def refuse(url: str, **kwargs):
        calls.append(url)
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED")

    reg = registry(tmp_path, refuse)
    reg.card_facts("nagatino-1")
    reg.card_facts("nagatino-1")
    assert len(calls) == 1, "отказ спрашивается заново при каждом чтении"
    # Но и навсегда он не запоминается: срок у отказа свой и короткий.
    assert reg.card_facts_failure_ttl_seconds < reg.ttl_seconds


def test_the_coverage_names_how_many_and_why(tmp_path: Path) -> None:
    """Свод отвечает «прочитано / не ответили / не спрашивали» и называет причину."""
    def refuse(url: str, **kwargs):
        raise RuntimeError("CERTIFICATE_VERIFY_FAILED: unable to get local issuer")

    reg = registry(tmp_path, refuse)
    reg.card_facts("one")
    reg.card_facts("two")
    state = reg.card_facts_coverage(["one", "two", "three"])
    assert state["read"] == 0
    assert state["failed"] == 2
    assert state["unknown"] == 1, "не спрошенная карточка — не «не ответила»"
    assert state["reasons"], "причина не названа — общий отказ не виден"
    assert sum(state["reasons"].values()) == 2


def test_the_screen_tells_unread_from_absent() -> None:
    page = (ROOT / "auction_search" / "ui.py").read_text("utf-8")
    assert "state.krtCardsState" in page and "renderKrtCardsNote" in page
    assert "а неизвестны" in page, "экран не различает «не прочитано» и «нет признака»"
    api = (ROOT / "auction_search" / "api.py").read_text("utf-8")
    assert '"cards_state"' in api, "охват карточек не доезжает до экрана"


def test_the_screen_says_how_many_await_re_reading() -> None:
    """«Заново каждый раз» — это непоказанное число устаревших находок."""
    api = (ROOT / "auction_search" / "api.py").read_text("utf-8")
    assert '"stale_rules_count"' in api
    page = (ROOT / "auction_search" / "ui.py").read_text("utf-8")
    assert "renderKrtStaleNote" in page and "прежним правилом" in page
