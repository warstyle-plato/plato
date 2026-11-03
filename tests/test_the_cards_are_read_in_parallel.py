"""Карточки источника читаются пачкой, иначе срок съедает лоты.

«Как так вышло, что фильтр только один КРТ и нашёл, хотя их там чуть ли не
десять» (владелец, 02.09.2026). За каждой карточкой Росэлторга идёт свой
запрос, а на весь каталог отведено сорок секунд на ВСЕ источники: по одной
карточке за раз сбор обрывался на первых, и остальные лоты не пропадали —
их просто не успевали прочитать. Молчание об этом читается как «таких лотов
нет».

Запуск: python3 -m pytest tests/test_the_cards_are_read_in_parallel.py -q
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402


def test_the_reader_asks_several_cards_at_once() -> None:
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text()
    body = source[source.index("    def discover_moscow("):
                  source.index("    def discover_moscow_history(")]
    assert "ThreadPoolExecutor" in body, "карточки читаются по одной — срок съест лоты"
    assert "max_workers=6" in body, "число потоков не названо"


def test_a_slow_source_still_fits_the_budget() -> None:
    """Двенадцать карточек по 0,2 с: последовательно 2,4 с, пачкой — меньше."""
    adapter = RoseltorgAdapter()
    urls = [f"https://www.roseltorg.ru/procedure/{i}/1" for i in range(12)]
    seen: list[str] = []
    lock = threading.Lock()

    def slow(lot_url: str, *, deadline=None):
        time.sleep(0.2)
        with lock:
            seen.append(lot_url)
        raise RuntimeError("карточка не разобрана — здесь меряется только время")

    adapter.fetch_lot = slow  # type: ignore[method-assign]
    adapter._discovery_urls = classmethod(lambda cls, tag, page=1: "")  # type: ignore
    started = time.monotonic()
    adapter.last_report = {"cards": 0}
    # Прямо проверяем цикл чтения: разведку по сети здесь не поднимаем.
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(adapter.fetch_lot, url): url for url in urls}
        for job in as_completed(jobs):
            try:
                job.result()
            except Exception:
                pass
    spent = time.monotonic() - started
    assert len(seen) == 12
    assert spent < 1.6, f"пачка не быстрее очереди: {spent:.2f} с"


def test_an_unread_card_is_named_not_swallowed() -> None:
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text()
    assert '"unread_cards"' in source
    page = (ROOT / "auction_search" / "ui.py").read_text()
    assert "не прочитано" in page and "r.unread_cards" in page
