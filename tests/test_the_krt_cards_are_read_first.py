"""В разделе читаются сначала КРТ, а потом всё остальное.

«В торгах от Росэлторга так и остался один КРТ, хотя их там вагон» (владелец,
02.09.2026, пять снимков экрана: аукционы Департамента градостроительной
политики на 2,90 / 4,74 / 6,61 / 8,97 / 11,74 / 14,54 / 16,9 / 63,91 га).
Живая проба того же дня: раздел отдаёт 79 ссылок на карточки. За каждой идёт
свой запрос, а на весь каталог отведено сорок секунд на ВСЕ источники — в срок
помещается десяток карточек, и пока порядок был случайным, КРТ читались
вперемешку с гаражами и автостоянками.

Заголовок лота стоит прямо в разделе, и по нему видно КРТ, не открывая
карточку. Значит очередь чтения — не «как пришло», а «сначала то, за чем
пришли»; сколько КРТ обещал сам раздел, говорится в строке охвата: иначе «из
них КРТ 1» не отличить от «КРТ там один».

Запуск: python3 -m pytest tests/test_the_krt_cards_are_read_first.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from auction_search.adapters.roseltorg import RoseltorgAdapter  # noqa: E402

KRT_TITLE = ("Аукцион на право заключения договора о комплексном развитии "
             "территорий нежилой застройки города Москвы, площадью 14,54 га")
JUNK_TITLE = "Аукцион по продаже гаражного бокса, 26 кв. м"


def urls(count: int) -> list[str]:
    return [f"https://www.roseltorg.ru/procedure/{index}" for index in range(count)]


def test_the_title_of_the_listing_tells_a_krt() -> None:
    assert RoseltorgAdapter._looks_like_krt(KRT_TITLE) is True
    assert RoseltorgAdapter._looks_like_krt(
        "Комплексное развитие территории нежилой застройки, 2,90 га") is True
    assert RoseltorgAdapter._looks_like_krt(JUNK_TITLE) is False
    # Пустая подпись — это «не знаем», а не «не КРТ»: такие читаются, просто
    # позже. Выбрасывать их нельзя.
    assert RoseltorgAdapter._looks_like_krt("") is False


def test_the_krt_cards_go_to_the_head_of_the_queue() -> None:
    listed = urls(20)
    titles = {url: JUNK_TITLE for url in listed}
    titles[listed[17]] = KRT_TITLE
    titles[listed[19]] = "Аукцион на право заключения договора о комплексном развитии территории"
    ordered = RoseltorgAdapter._ordered_candidates(listed, titles)
    assert ordered[:2] == [listed[17], listed[19]], ordered[:4]
    # Ни одна карточка не потеряна: порядок меняется, состав нет.
    assert sorted(ordered) == sorted(listed)


def test_the_order_inside_a_group_is_kept() -> None:
    """Раздел города спрашивается первым, и менять это местами нельзя."""
    listed = urls(6)
    titles = {listed[0]: KRT_TITLE, listed[3]: KRT_TITLE}
    ordered = RoseltorgAdapter._ordered_candidates(listed, titles)
    assert ordered == [listed[0], listed[3], listed[1], listed[2], listed[4], listed[5]]


def test_the_coverage_line_says_how_many_krt_the_listing_promised() -> None:
    source = (ROOT / "auction_search" / "adapters" / "roseltorg.py").read_text("utf-8")
    body = source[source.index("    def discover_moscow("):
                  source.index("    def discover_moscow_history(")]
    assert '_ordered_candidates(candidate_urls, titles)' in body, "очередь не переставлена"
    assert 'self.last_report["krt_titles"]' in body, "обещанное разделом не названо"
    page = (ROOT / "auction_search" / "ui.py").read_text("utf-8")
    assert "КРТ по заголовкам раздела" in page, "строка охвата молчит об этом"
