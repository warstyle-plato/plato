"""Строка охвата отвечает на «а где КРТ», а не только «лотов девять».

Владелец, 02.09.2026: «как так вышло, что фильтр только один КРТ и нашёл в
торгах, хотя их там чуть ли не десять». По строке охвата ответить было нечем:
она говорит «Roseltorg — лотов 9 · из 42 карточек», а сколько из них КРТ и
ответил ли вообще раздел «Развитие территории» — не сказано нигде. Молчание о
том, чего мы не спрашивали, читается как отсутствие таких лотов.

Запуск: python3 -m pytest tests/test_the_coverage_says_which_source_gave_the_krt.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.models import (  # noqa: E402
    AuctionLot, AuctionSource, LotKind, SourceKind,
)
from auction_search.service import AuctionSearchService  # noqa: E402


class _Adapter:
    platform_name = "Проба"

    def __init__(self) -> None:
        self.last_report = {"source": "Проба", "kept": 2, "cards": 40}


def _lot(kind: LotKind) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(platform=SourceKind.ROSELTORG,
                             lot_url="https://www.roseltorg.ru/procedure/1/1",
                             external_lot_id="1/1", fetched_at="", source_name="Проба"),
        lot_kind=kind, title="", raw={})


def test_the_source_says_how_many_krt_it_gave() -> None:
    adapter = _Adapter()
    AuctionSearchService._count_kinds(
        adapter, [_lot(LotKind.KRT), _lot(LotKind.LAND_SALE)])
    assert adapter.last_report["kept_krt"] == 1


def test_a_source_without_a_report_is_not_a_crash() -> None:
    class Silent:
        platform_name = "Молчун"

    AuctionSearchService._count_kinds(Silent(), [_lot(LotKind.KRT)])  # не падает


def test_the_count_is_declared_once_for_every_source() -> None:
    body = (ROOT / "auction_search" / "service.py").read_text(encoding="utf-8")
    assert body.count("def _count_kinds(") == 1
    # Зовётся на обеих ветках опроса: параллельной и последовательной, — иначе
    # число появляется через раз и читается как «у этого источника КРТ нет».
    assert body.count("self._count_kinds(") == 2


def test_the_page_prints_the_krt_count_and_the_section() -> None:
    page = (ROOT / "auction_search" / "ui.py").read_text(encoding="utf-8")
    assert "из них КРТ" in page
    assert "r.sections" in page and "не ответил" in page
