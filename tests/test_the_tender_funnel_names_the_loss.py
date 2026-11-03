"""«Одна карточка КРТ» обязана сказать, куда делись остальные.

02.09.2026 порядок чтения карточек Росэлторга был починен — КРТ читаются
первыми, — а на экране владельца по-прежнему стоял один лот. Ответить «почему»
было нечем: отчёт источника говорил «карточек N, лотов M», и «остальные торги
закрыты» выглядело ровно так же, как «мы их потеряли».

Отсюда две проверки. Отсев называет шаг, на котором лот ушёл. И подписи ссылок
собираются на ВСЕХ страницах разведки: прежде они брались только из раздела
имущества, поэтому у карточек с теговых страниц заголовка не было вовсе —
порядок их не поднимал, а счётчик «КРТ по заголовкам» их не видел, и правка
выглядела применённой.

Запуск: python3 -m pytest tests/test_the_tender_funnel_names_the_loss.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402
from auction_search.models import (  # noqa: E402
    AuctionLot, AuctionSource, LotKind, SourceKind,
)

SECTION = "https://www.roseltorg.ru/imuschestvo/prochee/razvitie-territorii"
KRT_TITLE = ("Право на заключение договора о комплексном развитии территории "
             "нежилой застройки города Москвы")


def lot(url: str, *, status: str, deadline: str, title: str = KRT_TITLE) -> AuctionLot:
    return AuctionLot(
        source=AuctionSource(
            platform=SourceKind.ROSELTORG, lot_url=url,
            external_lot_id=url.rsplit("/", 2)[-2], fetched_at="2026-09-02T00:00:00Z"),
        lot_kind=LotKind.KRT, title=title, status=status,
        application_deadline=deadline, address="Москва",
        raw={"trading_section": "Развитие территории", "lot_region_code": "77"})


def test_titles_are_taken_from_every_page_of_discovery() -> None:
    """Подпись ссылки помнится и с теговой страницы, не только с раздела."""
    titles: dict[str, str] = {}
    RoseltorgAdapter._remember_titles(
        "https://www.roseltorg.ru/procedures?tags%5B%5D=1",
        [("/procedure/AAA/1", KRT_TITLE), ("/procedure/BBB/1", "Гараж")],
        titles)
    assert titles["https://www.roseltorg.ru/procedure/AAA/1"] == KRT_TITLE
    assert titles["https://www.roseltorg.ru/procedure/BBB/1"] == "Гараж"
    # Первая непустая подпись выигрывает: та же ссылка ниже по странице часто
    # висит на картинке и приходит пустой.
    RoseltorgAdapter._remember_titles(
        SECTION, [("/procedure/AAA/1", "")], titles)
    assert titles["https://www.roseltorg.ru/procedure/AAA/1"] == KRT_TITLE


def test_the_discovery_collects_titles_on_tag_pages_too() -> None:
    """Сбор подписей стоит в обеих ветках разведки, а не в одной."""
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text("utf-8")
    body = source[source.index("    def discover_moscow("):
                  source.index("    def discover_moscow_history(")]
    assert body.count("_remember_titles(") == 2, \
        "подписи собираются не на всех страницах разведки"


def test_a_dropped_krt_names_the_step_it_left_on() -> None:
    """Просроченный КРТ уходит с названной причиной, а не молча."""
    adapter = RoseltorgAdapter()
    urls = ["https://www.roseltorg.ru/procedure/AAA/1",
            "https://www.roseltorg.ru/procedure/BBB/1"]
    cards = {
        urls[0]: lot(urls[0], status="Приём заявок", deadline="21.09.2099"),
        urls[1]: lot(urls[1], status="Работа комиссии", deadline="01.01.2020"),
    }
    adapter.fetch_lot = lambda url, *, deadline=None: cards[url]  # type: ignore[method-assign]
    adapter._discovery_urls = classmethod(lambda cls, tag, page=1: "")  # type: ignore
    adapter.SECTION_URLS = ()  # сеть здесь не поднимаем
    adapter.DISCOVERY_TAGS = ()
    adapter._candidate_urls_for_test = urls  # noqa: SLF001

    # Разведку подменяем прямо списком: проверяется отсев, а не сеть.
    original = RoseltorgAdapter._ordered_candidates
    RoseltorgAdapter._ordered_candidates = classmethod(  # type: ignore[assignment]
        lambda cls, found, titles: urls)
    try:
        kept = adapter.discover_moscow(deadline=None)
    finally:
        RoseltorgAdapter._ordered_candidates = original  # type: ignore[assignment]

    assert [item.source.lot_url for item in kept] == [urls[0]], "живой лот потерян"
    reasons = adapter.last_report.get("krt_dropped") or {}
    assert reasons, "КРТ отсеян молча — «один лот» неотличим от «остальные закрыты»"
    assert any("статус" in why or "срок" in why for why in reasons), reasons
    assert adapter.last_report.get("krt_read") == 2, "дочитанные КРТ не посчитаны"


def test_the_screen_shows_the_funnel() -> None:
    page = (ROOT / "auction_search" / "ui.py").read_text("utf-8")
    assert "r.krt_read" in page and "r.krt_dropped" in page, \
        "воронка КРТ не доезжает до строки охвата"
