"""Страница нормативной базы отвечает читателю, а не показывает нашу кухню.

Три замечания владельца 07.09.2026, все по делу:

- «Зачем пользователю видеть что источник требует проверки» — `review_required`
  это НАША отметка: мы не сверили консолидированную редакцию. Читателю она
  говорит «половине базы не верьте», при том что расчёт на этих нормах уже
  идёт. Его касается другое: какая редакция учтена и не изменился ли документ
  у публикатора — и то и другое приходит от ИСТОЧНИКА, а не из нашей очереди.
- «Вся информация должна быть свернута и при необходимости только открыта из
  списка» — тринадцать развёрнутых карточек это стена, которую не читают.

Проверяется собранная страница, а не исходник: обе подписи есть в файле всегда,
и строковый тест был бы зелёным на сломанном экране.

Запуск: python3 -m pytest tests/test_the_registry_page_speaks_to_the_reader.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import normatives_registry as nr  # noqa: E402

ENTRY = {
    "scope": "Москва",
    "short_name": "945-ПП — транспорт и парковки",
    "title": "Постановление Правительства Москвы № 945-ПП",
    "status": "review_required",
    "current_as_of": "2026-09-01",
    "affects": ["Нормативы приобъектной парковки нежилья"],
    "engine_usage": [{"module": "parking_norms", "usage": "приложение 6"}],
    "source_url": "https://www.mos.ru/x",
    "source_label": "mos.ru",
}

OUR_QUEUE = ("Требует ревизии", "Нужен первичный источник",
             "Подтверждено source pack движка", "HTTP")


def test_our_review_queue_is_not_shown_to_the_reader() -> None:
    card = nr._card(dict(ENTRY), admin=False)
    for word in OUR_QUEUE:
        assert word not in card, f"кухня на экране читателя: {word}"
    # Читателю сказано то, что его касается: какая редакция учтена.
    assert "Учтено на" in card, card[:400]


def test_the_admin_still_sees_the_queue() -> None:
    """Убрать с экрана читателя — не значит убрать вовсе: чинить это нам."""
    card = nr._card(dict(ENTRY), admin=True)
    assert "Требует ревизии" in card
    # Проба показывается администратору и тогда, когда её ещё не запускали:
    # «не запускалась» и «прошла» — разные ответы, и молчание их смешивает.
    assert "не запускалась" in card, card[-400:]
    with_probe = nr._card(
        dict(ENTRY, check={"result": "ok", "message": "…", "http_status": 200}),
        admin=True)
    assert "HTTP" in with_probe


def test_a_source_change_is_the_readers_business() -> None:
    """Новость ИСТОЧНИКА читателя касается, в отличие от нашей очереди."""
    entry = dict(ENTRY, check={"result": "amended", "message": "…", "http_status": 200})
    card = nr._card(entry, admin=False)
    assert "новая редакция" in card.lower(), card[:400]
    assert "Требует ревизии" not in card


def test_the_card_is_collapsed_and_its_summary_says_the_gist() -> None:
    card = nr._card(dict(ENTRY), admin=False)
    assert card.lstrip().startswith("<details"), card[:120]
    summary = card[card.index("<summary"):card.index("</summary>")]
    # Закрытый список без сути читается как отсутствующий: в строке стоит имя
    # документа И на что он влияет.
    assert "945-ПП" in summary
    assert "Нормативы приобъектной парковки нежилья" in summary
    # Раскрытое остаётся внутри, а не пропадает.
    body = card[card.index("</summary>"):]
    assert "parking_names" not in body  # опечатка бы прошла молча
    assert "приложение 6" in body and "Где используется в движке" in body


def test_the_page_opens_nothing_by_default() -> None:
    """Ни одна карточка не открыта заранее — иначе это та же стена."""
    card = nr._card(dict(ENTRY), admin=False)
    assert "<details open" not in card and "open>" not in card.split("</summary>")[0]
