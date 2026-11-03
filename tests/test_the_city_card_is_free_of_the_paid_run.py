"""Карточка города называет застройщика без платного прогона.

Владелец, 01.09.2026: «где очевидно что КРТ уже с оператором — ничего не стоит,
наоборот». Причина не в разборе: застройщика бесплатно называет сама карточка
krt.mos.ru (27 из 30 площадок «В реализации»), но читалась она только внутри
прогона каталога — вместе с платным поиском по публикациям. Пока прогона не
было, колонка занятости пустовала у всех, и «мы не спрашивали» читалось как
«оператора нет».

Бесплатный официальный источник не должен зависеть от платного. Строка каталога
несёт то, что уже прочитано, недостающее дочитывается фоном порциями, а маршрут
каталога в сеть не ходит: 263 запроса, пока человек ждёт ответа, — это не ответ.

Запуск: python3 -m pytest tests/test_the_city_card_is_free_of_the_paid_run.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_search.krt_registry import CARD_FACTS_SCHEMA_VERSION, KrtRegistry  # noqa: E402


def _cache(registry: KrtRegistry, slug: str, developer: str) -> None:
    registry.card_facts_dir.mkdir(parents=True, exist_ok=True)
    (registry.card_facts_dir / f"{slug}.json").write_text(json.dumps({
        "schema_version": CARD_FACTS_SCHEMA_VERSION,
        "available": True,
        "slug": slug,
        "developers": [developer],
        "renovation": False,
    }, ensure_ascii=False), encoding="utf-8")


def test_what_is_already_read_is_returned_without_a_single_request(tmp_path) -> None:
    asked: list[str] = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        raise AssertionError("маршрут каталога не имеет права ходить в сеть")

    registry = KrtRegistry(tmp_path, fetch=fetch)
    _cache(registry, "site-a", "АО «Главстрой»")
    known = registry.card_facts_known(["site-a", "site-b"])
    assert known["site-a"]["developers"] == ["АО «Главстрой»"]
    assert "site-b" not in known, "непрочитанная карточка — это «не знаем», а не пустая"
    assert asked == []


def test_a_bad_slug_is_ignored_not_read(tmp_path) -> None:
    registry = KrtRegistry(tmp_path, fetch=lambda url: b"")
    assert registry.card_facts_known(["../../etc/passwd", ""]) == {}


def test_the_missing_ones_are_read_in_the_background_and_one_failure_is_not_all(tmp_path) -> None:
    seen: list[str] = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        if "boom" in url:
            raise RuntimeError("источник не ответил")
        return "<html><body>Застройщик АО «Главстрой»</body></html>".encode("utf-8")

    registry = KrtRegistry(tmp_path, fetch=fetch)
    assert registry.fill_card_facts_in_background(["boom-site", "site-b"], limit=10)
    for _ in range(200):
        if len(seen) >= 2:
            break
        import time
        time.sleep(0.02)
    assert len(seen) >= 2, "один отказ не оставляет колонку пустой у остальных"


def test_nothing_to_read_starts_no_thread(tmp_path) -> None:
    registry = KrtRegistry(tmp_path, fetch=lambda url: b"")
    _cache(registry, "site-a", "АО «Главстрой»")
    assert registry.fill_card_facts_in_background(["site-a"]) is False


def test_the_catalogue_row_carries_the_card_and_the_page_reads_it() -> None:
    api = (ROOT / "auction_search" / "api.py").read_text()
    assert "card_facts_known" in api and "fill_card_facts_in_background" in api
    page = (ROOT / "auction_search" / "ui.py").read_text()
    assert "x.card_facts" in page, (
        "строка каталога несёт карточку — иначе колонка занятости пуста до прогона")


def test_the_static_frame_opens_the_live_map() -> None:
    """«Карта крт статичная и неудобная» (владелец, 01.09.2026).

    Живая карта была только за кнопкой, а первым человек видел неподвижный
    кадр. Кадр остаётся — он уходит в отчёт, подвижную картинку туда не
    вставить, — но открывает живую карту сам.
    """
    page = (ROOT / "auction_search" / "ui.py").read_text()
    assert "id=\"krtMapShot\"" in page
    assert "shot.onclick=()=>openKrtLiveMap(sites)" in page
    assert "Открыть живую карту" in page
    # Своей живой карты у модуля нет: разошедшиеся проекции кладут контур рядом
    # с подложкой, а выглядит это как неточность источника.
    assert "openLandMap(" in page
